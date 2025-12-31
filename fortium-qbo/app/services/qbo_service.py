"""QuickBooks Online service using python-quickbooks SDK."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.account import Account
from quickbooks.objects.bill import Bill
from quickbooks.objects.customer import Customer
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.payment import Payment
from quickbooks.objects.vendor import Vendor
from sqlalchemy.orm import Session

from app.config import settings
from app.models.qbo_company import QboCompany

logger = logging.getLogger(__name__)

# QBO API minor version (69 is latest stable as of 2025)
QBO_MINOR_VERSION = 69

# Token refresh buffer - refresh if expiring within this time
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


class QBOService:
    """
    QuickBooks Online service providing SDK-based entity access.

    Handles:
    - Token management with auto-refresh
    - Entity queries (Invoice, Customer, Vendor, Account, Bill, Payment)
    - Report fetching (Trial Balance, Balance Sheet, P&L) via direct API
    """

    def __init__(self, db: Session):
        self.db = db
        self._clients: dict[str, QuickBooks] = {}

    def _get_company(self, company_id: int) -> QboCompany:
        """Get QBO company by ID."""
        company = self.db.query(QboCompany).filter(QboCompany.id == company_id).first()
        if not company:
            raise ValueError(f"QBO company not found: {company_id}")
        return company

    def _get_company_by_realm(self, realm_id: str) -> QboCompany:
        """Get QBO company by realm ID."""
        company = (
            self.db.query(QboCompany).filter(QboCompany.realm_id == realm_id).first()
        )
        if not company:
            raise ValueError(f"QBO company not found for realm: {realm_id}")
        return company

    def get_company_by_code(self, code: str) -> QboCompany:
        """
        Get QBO company by code.

        Args:
            code: Company code (e.g., "FOR-482")

        Returns:
            QboCompany instance

        Raises:
            ValueError: If company not found or disconnected
        """
        company = self.db.query(QboCompany).filter(QboCompany.code == code).first()
        if not company:
            raise ValueError(f"QBO company not found: {code}")
        if company.token_status == "disconnected":
            raise ValueError(
                f"QBO company {code} is disconnected. Please reconnect via /admin/companies."
            )
        return company

    def _needs_refresh(self, company: QboCompany) -> bool:
        """Check if token needs refresh."""
        if not company.token_expires_at:
            return True
        return datetime.utcnow() + TOKEN_REFRESH_BUFFER >= company.token_expires_at

    def _refresh_token(self, company: QboCompany) -> None:
        """Refresh OAuth token and persist to database."""
        credentials = settings.get_qbo_credentials(company.region)
        if not credentials:
            raise ValueError(f"QBO credentials not configured for region: {company.region}")

        client_id, client_secret = credentials
        # Both US and Canada now use production environment
        environment = "production"

        auth_client = AuthClient(
            client_id=client_id,
            client_secret=client_secret,
            access_token=company.access_token,
            refresh_token=company.refresh_token,
            environment=environment,
            redirect_uri=settings.qbo_callback_url,
        )

        # Refresh the token
        auth_client.refresh()

        # Update company record
        company.access_token = auth_client.access_token
        company.refresh_token = auth_client.refresh_token
        company.token_expires_at = datetime.utcnow() + timedelta(hours=1)
        company.last_refreshed_at = datetime.utcnow()
        company.token_status = "active"

        self.db.commit()
        logger.info(f"Refreshed token for company {company.code}")

    def _get_client(self, company: QboCompany) -> QuickBooks:
        """Get or create QuickBooks client for a company."""
        cache_key = f"{company.id}:{company.token_expires_at}"

        if cache_key not in self._clients:
            # Check if token needs refresh
            if self._needs_refresh(company):
                self._refresh_token(company)

            credentials = settings.get_qbo_credentials(company.region)
            if not credentials:
                raise ValueError(f"QBO credentials not configured for region: {company.region}")

            client_id, client_secret = credentials
            # Both US and Canada now use production environment
            environment = "production"

            auth_client = AuthClient(
                client_id=client_id,
                client_secret=client_secret,
                access_token=company.access_token,
                refresh_token=company.refresh_token,
                environment=environment,
                redirect_uri=settings.qbo_callback_url,
            )

            self._clients[cache_key] = QuickBooks(
                auth_client=auth_client,
                refresh_token=company.refresh_token,
                company_id=company.realm_id,
                minorversion=QBO_MINOR_VERSION,
            )

        return self._clients[cache_key]

    # -------------------------------------------------------------------------
    # Entity Methods (async via to_thread)
    # -------------------------------------------------------------------------

    async def get_invoices(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get invoices, optionally filtered by date range."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if start_date and end_date:
                return Invoice.where(
                    f"TxnDate >= '{start_date.strftime('%Y-%m-%d')}' "
                    f"AND TxnDate <= '{end_date.strftime('%Y-%m-%d')}'",
                    max_results=max_results,
                    qb=client,
                )
            return Invoice.all(max_results=max_results, qb=client)

        invoices = await asyncio.to_thread(_fetch)
        return [inv.to_dict() for inv in invoices]

    async def get_invoice_by_id(
        self, company_id: int, invoice_id: int
    ) -> dict[str, Any] | None:
        """Get a specific invoice by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Invoice.get(invoice_id, qb=client)

        invoice = await asyncio.to_thread(_fetch)
        return invoice.to_dict() if invoice else None

    async def get_customers(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        """Get customers."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Customer.filter(Active=True, max_results=max_results, qb=client)
            return Customer.all(max_results=max_results, qb=client)

        customers = await asyncio.to_thread(_fetch)
        return [c.to_dict() for c in customers]

    async def get_customer_by_id(
        self, company_id: int, customer_id: int
    ) -> dict[str, Any] | None:
        """Get a specific customer by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Customer.get(customer_id, qb=client)

        customer = await asyncio.to_thread(_fetch)
        return customer.to_dict() if customer else None

    async def get_vendors(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        """Get vendors."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Vendor.filter(Active=True, max_results=max_results, qb=client)
            return Vendor.all(max_results=max_results, qb=client)

        vendors = await asyncio.to_thread(_fetch)
        return [v.to_dict() for v in vendors]

    async def get_vendor_by_id(
        self, company_id: int, vendor_id: int
    ) -> dict[str, Any] | None:
        """Get a specific vendor by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Vendor.get(vendor_id, qb=client)

        vendor = await asyncio.to_thread(_fetch)
        return vendor.to_dict() if vendor else None

    async def get_accounts(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        """Get chart of accounts."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Account.filter(Active=True, max_results=max_results, qb=client)
            return Account.all(max_results=max_results, qb=client)

        accounts = await asyncio.to_thread(_fetch)
        return [a.to_dict() for a in accounts]

    async def get_account_by_id(
        self, company_id: int, account_id: int
    ) -> dict[str, Any] | None:
        """Get a specific account by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Account.get(account_id, qb=client)

        account = await asyncio.to_thread(_fetch)
        return account.to_dict() if account else None

    async def get_account_by_number(
        self, company_id: int, account_number: str
    ) -> dict[str, Any] | None:
        """Get account by account number."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            results = Account.where(f"AcctNum = '{account_number}'", qb=client)
            return results[0] if results else None

        account = await asyncio.to_thread(_fetch)
        return account.to_dict() if account else None

    async def get_bills(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        """Get bills."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Bill.all(max_results=max_results, qb=client)

        bills = await asyncio.to_thread(_fetch)
        return [b.to_dict() for b in bills]

    async def get_bill_by_id(
        self, company_id: int, bill_id: int
    ) -> dict[str, Any] | None:
        """Get a specific bill by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Bill.get(bill_id, qb=client)

        bill = await asyncio.to_thread(_fetch)
        return bill.to_dict() if bill else None

    async def get_payments(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        """Get payments."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Payment.all(max_results=max_results, qb=client)

        payments = await asyncio.to_thread(_fetch)
        return [p.to_dict() for p in payments]

    async def get_payment_by_id(
        self, company_id: int, payment_id: int
    ) -> dict[str, Any] | None:
        """Get a specific payment by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Payment.get(payment_id, qb=client)

        payment = await asyncio.to_thread(_fetch)
        return payment.to_dict() if payment else None

    # -------------------------------------------------------------------------
    # Reports (Direct API - SDK doesn't support QBO Reports)
    # -------------------------------------------------------------------------

    async def _fetch_report(
        self, company: QboCompany, report_name: str, params: dict[str, str]
    ) -> dict[str, Any]:
        """Fetch a QBO report via direct API call."""
        # Ensure token is fresh
        if self._needs_refresh(company):
            self._refresh_token(company)

        url = (
            f"https://quickbooks.api.intuit.com/v3/company/"
            f"{company.realm_id}/reports/{report_name}"
        )
        params["minorversion"] = str(QBO_MINOR_VERSION)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {company.access_token}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_trial_balance(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        accounting_method: str = "Accrual",
    ) -> dict[str, Any]:
        """Get Trial Balance report."""
        company = self._get_company(company_id)

        params = {"accounting_method": accounting_method}
        if start_date:
            params["start_date"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["end_date"] = end_date.strftime("%Y-%m-%d")

        return await self._fetch_report(company, "TrialBalance", params)

    async def get_balance_sheet(
        self,
        company_id: int,
        as_of_date: datetime | None = None,
        accounting_method: str = "Accrual",
    ) -> dict[str, Any]:
        """Get Balance Sheet report."""
        company = self._get_company(company_id)

        params = {"accounting_method": accounting_method}
        if as_of_date:
            params["date"] = as_of_date.strftime("%Y-%m-%d")

        return await self._fetch_report(company, "BalanceSheet", params)

    async def get_profit_and_loss(
        self,
        company_id: int,
        start_date: datetime,
        end_date: datetime,
        accounting_method: str = "Accrual",
    ) -> dict[str, Any]:
        """Get Profit & Loss report."""
        company = self._get_company(company_id)

        params = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "accounting_method": accounting_method,
        }

        return await self._fetch_report(company, "ProfitAndLoss", params)


def get_qbo_service(db: Session) -> QBOService:
    """Factory function to create QBOService instance."""
    return QBOService(db)
