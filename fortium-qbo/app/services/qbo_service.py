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
from quickbooks.objects.attachable import Attachable
from quickbooks.objects.bill import Bill
from quickbooks.objects.billpayment import BillPayment, BillPaymentLine, CheckPayment
from quickbooks.objects.base import Address, EmailAddress, LinkedTxn, PhoneNumber, Ref
from quickbooks.objects.company_info import CompanyInfo
from quickbooks.objects.companycurrency import CompanyCurrency
from quickbooks.objects.creditmemo import CreditMemo
from quickbooks.objects.detailline import (
    AccountBasedExpenseLine,
    AccountBasedExpenseLineDetail,
)
from quickbooks.objects.customer import Customer
from quickbooks.objects.customertype import CustomerType
from quickbooks.objects.department import Department
from quickbooks.objects.deposit import Deposit
from quickbooks.objects.employee import Employee
from quickbooks.objects.estimate import Estimate
from quickbooks.objects.exchangerate import ExchangeRate
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.item import Item
from quickbooks.objects.journalentry import JournalEntry
from quickbooks.objects.payment import Payment
from quickbooks.objects.paymentmethod import PaymentMethod
from quickbooks.objects.preferences import Preferences
from quickbooks.objects.purchase import Purchase
from quickbooks.objects.purchaseorder import PurchaseOrder
from quickbooks.objects.recurringtransaction import RecurringTransaction
from quickbooks.objects.refundreceipt import RefundReceipt
from quickbooks.objects.salesreceipt import SalesReceipt
from quickbooks.objects.taxagency import TaxAgency
from quickbooks.objects.taxcode import TaxCode
from quickbooks.objects.taxrate import TaxRate
from quickbooks.objects.term import Term
from quickbooks.objects.timeactivity import TimeActivity
from quickbooks.objects.trackingclass import Class as TrackingClass
from quickbooks.objects.transfer import Transfer
from quickbooks.objects.vendor import Vendor
from quickbooks.objects.vendorcredit import VendorCredit
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
        """Refresh OAuth token and persist to database.

        IMPORTANT: Intuit rotates refresh tokens on each refresh.
        If we successfully refresh but fail to save, we lose the new token.
        """
        credentials = settings.get_qbo_credentials(company.region)
        if not credentials:
            raise ValueError(f"QBO credentials not configured for region: {company.region}")

        client_id, client_secret = credentials
        environment = "production"

        auth_client = AuthClient(
            client_id=client_id,
            client_secret=client_secret,
            access_token=company.access_token,
            refresh_token=company.refresh_token,
            environment=environment,
            redirect_uri=settings.qbo_callback_url,
        )

        try:
            # Refresh the token - this INVALIDATES the old refresh token!
            auth_client.refresh()

            # CRITICAL: Save new tokens immediately
            # If this fails, the old refresh token is already invalid
            company.access_token = auth_client.access_token
            company.refresh_token = auth_client.refresh_token
            company.token_expires_at = datetime.utcnow() + timedelta(hours=1)
            company.refresh_token_expires_at = datetime.utcnow() + timedelta(days=100)
            company.last_refreshed_at = datetime.utcnow()
            company.token_status = "active"

            self.db.commit()
            logger.info(f"Refreshed token for company {company.code}")

        except Exception as e:
            # Log the error with details
            logger.error(f"Token refresh failed for company {company.code}: {e}")

            # Try to mark the company as needing reconnection
            try:
                self.db.rollback()
                company.token_status = "refresh_failed"
                self.db.commit()
            except Exception as db_error:
                logger.error(f"Failed to update token_status: {db_error}")
                self.db.rollback()

            raise ValueError(
                f"Token refresh failed for {company.code}. "
                f"Please reconnect at /admin/companies. Error: {e}"
            )

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

    async def get_invoice_by_doc_number(
        self, company_id: int, doc_number: str
    ) -> dict[str, Any] | None:
        """Get a specific invoice by DocNumber."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            results = Invoice.where(f"DocNumber = '{doc_number}'", qb=client)
            return results[0] if results else None

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

    async def create_customer(
        self, company_id: int, customer_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a Customer in QBO.

        Args:
            company_id: QBO company ID
            customer_data: Dict with DisplayName, CompanyName, GivenName,
                FamilyName, Title, Suffix, PrimaryEmailAddr, PrimaryPhone,
                Mobile, BillAddr, ShipAddr, SalesTermRef, CurrencyRef,
                PaymentMethodRef, Notes, PrintOnCheckName, Taxable, Active,
                ParentRef, etc.

        Returns:
            Created Customer as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            cust = Customer()

            # Simple string/bool fields
            for field in (
                "DisplayName", "CompanyName", "GivenName", "FamilyName",
                "Title", "Suffix", "Notes", "PrintOnCheckName",
            ):
                if field in customer_data:
                    setattr(cust, field, customer_data[field])

            if "Taxable" in customer_data:
                cust.Taxable = customer_data["Taxable"]
            if "Active" in customer_data:
                cust.Active = customer_data["Active"]

            # Email
            if "PrimaryEmailAddr" in customer_data:
                email = EmailAddress()
                email.Address = customer_data["PrimaryEmailAddr"].get("Address", "")
                cust.PrimaryEmailAddr = email

            # Phone fields
            for phone_field in ("PrimaryPhone", "Mobile"):
                if phone_field in customer_data:
                    phone = PhoneNumber()
                    phone.FreeFormNumber = customer_data[phone_field].get("FreeFormNumber", "")
                    setattr(cust, phone_field, phone)

            # Address fields
            for addr_field in ("BillAddr", "ShipAddr"):
                if addr_field in customer_data:
                    addr_data = customer_data[addr_field]
                    addr = Address()
                    for key in ("Line1", "Line2", "City", "CountrySubDivisionCode", "PostalCode", "Country"):
                        if key in addr_data:
                            setattr(addr, key, addr_data[key])
                    setattr(cust, addr_field, addr)

            # Ref fields
            for ref_field in ("SalesTermRef", "CurrencyRef", "PaymentMethodRef", "ParentRef"):
                if ref_field in customer_data:
                    ref = Ref()
                    ref.value = str(customer_data[ref_field]["value"])
                    ref.name = customer_data[ref_field].get("name")
                    setattr(cust, ref_field, ref)

            return cust.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    async def create_vendor(
        self, company_id: int, vendor_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a Vendor in QBO.

        Args:
            company_id: QBO company ID
            vendor_data: Dict with DisplayName, CompanyName, GivenName,
                FamilyName, Title, Suffix, PrimaryEmailAddr, PrimaryPhone,
                Mobile, BillAddr, TermRef, CurrencyRef, TaxIdentifier,
                AcctNum, PrintOnCheckName, Active, Notes, etc.

        Returns:
            Created Vendor as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            vnd = Vendor()

            # Simple string fields
            for field in (
                "DisplayName", "CompanyName", "GivenName", "FamilyName",
                "Title", "Suffix", "Notes", "PrintOnCheckName",
                "TaxIdentifier", "AcctNum",
            ):
                if field in vendor_data:
                    setattr(vnd, field, vendor_data[field])

            if "Active" in vendor_data:
                vnd.Active = vendor_data["Active"]

            # Email
            if "PrimaryEmailAddr" in vendor_data:
                email = EmailAddress()
                email.Address = vendor_data["PrimaryEmailAddr"].get("Address", "")
                vnd.PrimaryEmailAddr = email

            # Phone fields
            for phone_field in ("PrimaryPhone", "Mobile"):
                if phone_field in vendor_data:
                    phone = PhoneNumber()
                    phone.FreeFormNumber = vendor_data[phone_field].get("FreeFormNumber", "")
                    setattr(vnd, phone_field, phone)

            # Address
            if "BillAddr" in vendor_data:
                addr_data = vendor_data["BillAddr"]
                addr = Address()
                for key in ("Line1", "Line2", "City", "CountrySubDivisionCode", "PostalCode", "Country"):
                    if key in addr_data:
                        setattr(addr, key, addr_data[key])
                vnd.BillAddr = addr

            # Ref fields (Vendor uses TermRef, not SalesTermRef)
            for ref_field in ("TermRef", "CurrencyRef"):
                if ref_field in vendor_data:
                    ref = Ref()
                    ref.value = str(vendor_data[ref_field]["value"])
                    ref.name = vendor_data[ref_field].get("name")
                    setattr(vnd, ref_field, ref)

            return vnd.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

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

    async def delete_bill(
        self, company_id: int, bill_id: int
    ) -> dict[str, Any]:
        """Delete a bill in QBO.

        Args:
            company_id: QBO company ID
            bill_id: QBO Bill ID to delete

        Returns:
            Deleted Bill as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _delete():
            bill = Bill.get(bill_id, qb=client)
            if not bill:
                raise ValueError(f"Bill {bill_id} not found")
            return bill.delete(qb=client)

        result = await asyncio.to_thread(_delete)
        return result.to_dict() if hasattr(result, 'to_dict') else {"Id": str(bill_id), "status": "Deleted"}

    async def create_bill(
        self, company_id: int, bill_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a Bill in QBO.

        Args:
            company_id: QBO company ID
            bill_data: Dict with VendorRef, TxnDate, DueDate, DocNumber,
                PrivateNote, APAccountRef, DepartmentRef, CurrencyRef, and
                Line[] (each line: Amount, Description, plus
                AccountBasedExpenseLineDetail with AccountRef/ClassRef/
                CustomerRef/TaxCodeRef).

        Returns:
            Created Bill as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            bill = Bill()

            for field in ("TxnDate", "DueDate", "DocNumber", "PrivateNote"):
                if field in bill_data:
                    setattr(bill, field, bill_data[field])

            for ref_field in (
                "VendorRef", "APAccountRef", "DepartmentRef",
                "CurrencyRef", "SalesTermRef",
            ):
                if ref_field in bill_data:
                    ref = Ref()
                    ref.value = str(bill_data[ref_field]["value"])
                    ref.name = bill_data[ref_field].get("name")
                    setattr(bill, ref_field, ref)

            for line_data in bill_data.get("Line", []):
                line = AccountBasedExpenseLine()
                line.Amount = line_data["Amount"]
                if "Description" in line_data:
                    line.Description = line_data["Description"]

                detail_data = line_data.get("AccountBasedExpenseLineDetail", {})
                detail = AccountBasedExpenseLineDetail()
                if "BillableStatus" in detail_data:
                    detail.BillableStatus = detail_data["BillableStatus"]
                for ref_field in ("AccountRef", "CustomerRef", "ClassRef", "TaxCodeRef"):
                    if ref_field in detail_data:
                        ref = Ref()
                        ref.value = str(detail_data[ref_field]["value"])
                        ref.name = detail_data[ref_field].get("name")
                        setattr(detail, ref_field, ref)
                line.AccountBasedExpenseLineDetail = detail

                bill.Line.append(line)

            return bill.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    async def get_payments(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get payments, optionally filtered by date range."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if start_date and end_date:
                return Payment.where(
                    f"TxnDate >= '{start_date.strftime('%Y-%m-%d')}' "
                    f"AND TxnDate <= '{end_date.strftime('%Y-%m-%d')}'",
                    max_results=max_results,
                    qb=client,
                )
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
    # BillPayment
    # -------------------------------------------------------------------------

    async def get_bill_payments(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return BillPayment.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_bill_payment_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return BillPayment.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    async def get_bill_payments_by_bill_id(
        self, company_id: int, bill_id: int
    ) -> list[dict[str, Any]]:
        """Get bill payments linked to a specific bill.

        QBO doesn't support filtering by LinkedTxn in queries,
        so we fetch all and filter in Python.
        """
        company = self._get_company(company_id)
        client = self._get_client(company)
        bill_id_str = str(bill_id)

        def _fetch():
            all_payments = BillPayment.all(max_results=1000, qb=client)
            matched = []
            for bp in all_payments:
                for line in bp.Line:
                    for txn in line.LinkedTxn:
                        if txn.TxnId == bill_id_str and txn.TxnType == "Bill":
                            matched.append(bp)
                            break
                    else:
                        continue
                    break
            return matched

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def create_bill_payment(
        self, company_id: int, payment_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a BillPayment in QBO.

        Args:
            company_id: QBO company ID
            payment_data: Dict with PayType, VendorRef, TotalAmt, Line, etc.

        Returns:
            Created BillPayment as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            bp = BillPayment()
            bp.PayType = payment_data.get("PayType", "Check")
            bp.TotalAmt = payment_data["TotalAmt"]
            bp.PrivateNote = payment_data.get("PrivateNote", "")
            bp.DocNumber = payment_data.get("DocNumber", "")

            if "VendorRef" in payment_data:
                ref = Ref()
                ref.value = str(payment_data["VendorRef"]["value"])
                ref.name = payment_data["VendorRef"].get("name")
                bp.VendorRef = ref

            if "APAccountRef" in payment_data:
                ref = Ref()
                ref.value = str(payment_data["APAccountRef"]["value"])
                ref.name = payment_data["APAccountRef"].get("name")
                bp.APAccountRef = ref

            if "DepartmentRef" in payment_data:
                ref = Ref()
                ref.value = str(payment_data["DepartmentRef"]["value"])
                ref.name = payment_data["DepartmentRef"].get("name")
                bp.DepartmentRef = ref

            if payment_data.get("PayType") == "Check" and "CheckPayment" in payment_data:
                cp = CheckPayment()
                if "BankAccountRef" in payment_data["CheckPayment"]:
                    ref = Ref()
                    ref.value = str(payment_data["CheckPayment"]["BankAccountRef"]["value"])
                    ref.name = payment_data["CheckPayment"]["BankAccountRef"].get("name")
                    cp.BankAccountRef = ref
                cp.PrintStatus = payment_data["CheckPayment"].get("PrintStatus", "NotSet")
                bp.CheckPayment = cp

            for line_data in payment_data.get("Line", []):
                line = BillPaymentLine()
                line.Amount = line_data["Amount"]
                for txn_data in line_data.get("LinkedTxn", []):
                    txn = LinkedTxn()
                    txn.TxnId = str(txn_data["TxnId"])
                    txn.TxnType = txn_data["TxnType"]
                    line.LinkedTxn.append(txn)
                bp.Line.append(line)

            return bp.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    # -------------------------------------------------------------------------
    # CreditMemo
    # -------------------------------------------------------------------------

    async def get_credit_memos(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CreditMemo.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_credit_memo_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CreditMemo.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Deposit
    # -------------------------------------------------------------------------

    async def get_deposits(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Deposit.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_deposit_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Deposit.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Estimate
    # -------------------------------------------------------------------------

    async def get_estimates(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Estimate.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_estimate_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Estimate.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # JournalEntry
    # -------------------------------------------------------------------------

    async def get_journal_entries(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return JournalEntry.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_journal_entry_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return JournalEntry.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Purchase
    # -------------------------------------------------------------------------

    async def get_purchases(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Purchase.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_purchase_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Purchase.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # PurchaseOrder
    # -------------------------------------------------------------------------

    async def get_purchase_orders(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return PurchaseOrder.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_purchase_order_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return PurchaseOrder.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # RefundReceipt
    # -------------------------------------------------------------------------

    async def get_refund_receipts(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return RefundReceipt.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_refund_receipt_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return RefundReceipt.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # SalesReceipt
    # -------------------------------------------------------------------------

    async def get_sales_receipts(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return SalesReceipt.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_sales_receipt_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return SalesReceipt.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Transfer
    # -------------------------------------------------------------------------

    async def get_transfers(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Transfer.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_transfer_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Transfer.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # VendorCredit
    # -------------------------------------------------------------------------

    async def get_vendor_credits(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return VendorCredit.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_vendor_credit_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return VendorCredit.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    async def create_vendor_credit(
        self, company_id: int, credit_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a VendorCredit in QBO.

        Args:
            company_id: QBO company ID
            credit_data: Dict with VendorRef, TxnDate, DocNumber, PrivateNote,
                TotalAmt, APAccountRef, DepartmentRef, CurrencyRef, and Line[]
                (each line: Amount, Description, plus AccountBasedExpenseLineDetail
                with AccountRef/ClassRef/CustomerRef/TaxCodeRef).

        Returns:
            Created VendorCredit as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            vc = VendorCredit()

            for field in ("TxnDate", "DocNumber", "PrivateNote"):
                if field in credit_data:
                    setattr(vc, field, credit_data[field])

            if "TotalAmt" in credit_data:
                vc.TotalAmt = credit_data["TotalAmt"]

            for ref_field in (
                "VendorRef", "APAccountRef", "DepartmentRef", "CurrencyRef",
            ):
                if ref_field in credit_data:
                    ref = Ref()
                    ref.value = str(credit_data[ref_field]["value"])
                    ref.name = credit_data[ref_field].get("name")
                    setattr(vc, ref_field, ref)

            for line_data in credit_data.get("Line", []):
                line = AccountBasedExpenseLine()
                line.Amount = line_data["Amount"]
                if "Description" in line_data:
                    line.Description = line_data["Description"]

                detail_data = line_data.get("AccountBasedExpenseLineDetail", {})
                detail = AccountBasedExpenseLineDetail()
                if "BillableStatus" in detail_data:
                    detail.BillableStatus = detail_data["BillableStatus"]
                for ref_field in ("AccountRef", "CustomerRef", "ClassRef", "TaxCodeRef"):
                    if ref_field in detail_data:
                        ref = Ref()
                        ref.value = str(detail_data[ref_field]["value"])
                        ref.name = detail_data[ref_field].get("name")
                        setattr(detail, ref_field, ref)
                line.AccountBasedExpenseLineDetail = detail

                vc.Line.append(line)

            return vc.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    # -------------------------------------------------------------------------
    # Item
    # -------------------------------------------------------------------------

    async def get_items(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Item.filter(Active=True, max_results=max_results, qb=client)
            return Item.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_item_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Item.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Employee
    # -------------------------------------------------------------------------

    async def get_employees(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Employee.filter(Active=True, max_results=max_results, qb=client)
            return Employee.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_employee_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Employee.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Department
    # -------------------------------------------------------------------------

    async def get_departments(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Department.filter(Active=True, max_results=max_results, qb=client)
            return Department.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_department_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Department.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # TimeActivity
    # -------------------------------------------------------------------------

    async def get_time_activities(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TimeActivity.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_time_activity_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TimeActivity.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # CompanyInfo
    # -------------------------------------------------------------------------

    async def get_company_info(
        self, company_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            results = CompanyInfo.all(max_results=1, qb=client)
            return results[0] if results else None

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Preferences
    # -------------------------------------------------------------------------

    async def get_preferences(
        self, company_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Preferences.get(qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # TaxAgency
    # -------------------------------------------------------------------------

    async def get_tax_agencies(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxAgency.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_tax_agency_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxAgency.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # TaxCode
    # -------------------------------------------------------------------------

    async def get_tax_codes(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxCode.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_tax_code_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxCode.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # TaxRate
    # -------------------------------------------------------------------------

    async def get_tax_rates(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxRate.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_tax_rate_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxRate.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # CompanyCurrency
    # -------------------------------------------------------------------------

    async def get_company_currencies(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CompanyCurrency.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_company_currency_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CompanyCurrency.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # ExchangeRate (list only - no get by ID)
    # -------------------------------------------------------------------------

    async def get_exchange_rates(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return ExchangeRate.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    # -------------------------------------------------------------------------
    # PaymentMethod
    # -------------------------------------------------------------------------

    async def get_payment_methods(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return PaymentMethod.filter(Active=True, max_results=max_results, qb=client)
            return PaymentMethod.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_payment_method_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return PaymentMethod.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Term
    # -------------------------------------------------------------------------

    async def get_terms(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return Term.filter(Active=True, max_results=max_results, qb=client)
            return Term.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_term_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Term.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # TrackingClass
    # -------------------------------------------------------------------------

    async def get_classes(
        self, company_id: int, active_only: bool = True, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            if active_only:
                return TrackingClass.filter(Active=True, max_results=max_results, qb=client)
            return TrackingClass.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_class_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TrackingClass.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # CustomerType
    # -------------------------------------------------------------------------

    async def get_customer_types(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CustomerType.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_customer_type_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CustomerType.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Attachable
    # -------------------------------------------------------------------------

    async def get_attachables(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Attachable.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_attachable_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Attachable.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # RecurringTransaction
    # -------------------------------------------------------------------------

    async def get_recurring_transactions(
        self, company_id: int, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return RecurringTransaction.all(max_results=max_results, qb=client)

        items = await asyncio.to_thread(_fetch)
        return [i.to_dict() for i in items]

    async def get_recurring_transaction_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return RecurringTransaction.get(entity_id, qb=client)

        result = await asyncio.to_thread(_fetch)
        return result.to_dict() if result else None

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
            date_str = as_of_date.strftime("%Y-%m-%d")
            params["start_date"] = date_str
            params["end_date"] = date_str

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

    async def get_general_ledger(
        self,
        company_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        account: str | None = None,
        accounting_method: str = "Accrual",
    ) -> dict[str, Any]:
        """Get General Ledger report (all transactions by account)."""
        company = self._get_company(company_id)

        params = {"accounting_method": accounting_method}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if account:
            params["account"] = account

        return await self._fetch_report(company, "GeneralLedger", params)


def get_qbo_service(db: Session) -> QBOService:
    """Factory function to create QBOService instance."""
    return QBOService(db)
