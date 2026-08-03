"""QuickBooks Online service using python-quickbooks SDK."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
import requests.exceptions as requests_exceptions
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.exceptions import (
    QuickbooksException,
    SevereException,
    UnsupportedException,
)
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
from quickbooks.objects.journalentry import (
    Entity as JournalEntryEntity,
    JournalEntry,
    JournalEntryLine,
    JournalEntryLineDetail,
)
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
from app.utils.paging import QBO_MAX_PAGE_SIZE, PagedResult

logger = logging.getLogger(__name__)

# QBO API minor version (69 is latest stable as of 2025)
QBO_MINOR_VERSION = 69

# Token refresh buffer - refresh if expiring within this time
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)

# Bounded retry for transient QBO faults (e.g. the intermittent
# "QB Severe Exception 10000" 500s QBO returns on entity reads).
# 1 initial attempt + 2 retries, backing off 1s then 2s.
QBO_RETRY_ATTEMPTS = 3
QBO_RETRY_BACKOFF_SECONDS = (1, 2)

# Page budget for the endpoints that aggregate server-side and therefore have
# to read the whole result set. 20 pages is 20,000 rows — comfortably past the
# ~27,000-row bill ledger's largest realistic window and small enough that a
# runaway query cannot sit on a QBO connection indefinitely.
QBO_MAX_PAGES_PER_WALK = 20

# Raw transport-level errors that indicate a transient network blip rather
# than a deterministic client error. The SDK transports over `requests`
# (OAuth2Session), so requests errors surface unwrapped; the httpx errors
# cover the direct-API report path (_fetch_report), which is retried via
# _with_retry. Report HTTP 5xx surfaces as httpx.HTTPStatusError and is
# classified transient in _is_transient_qbo_error below.
_TRANSIENT_NETWORK_ERRORS = (
    requests_exceptions.ConnectionError,
    requests_exceptions.Timeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
)


def _txn_date_clause(
    start_date: datetime | None, end_date: datetime | None
) -> str | None:
    """Build the TxnDate portion of a QBO query, or None when unbounded.

    Either bound on its own produces a one-sided filter. Requiring both would
    mean a caller who sends only `start_date` gets every row back with a 200
    and no indication the bound was dropped.

    The bounds are `datetime` objects rather than strings so the values
    interpolated into the query are always a `strftime` result, never
    caller-supplied text.
    """
    clauses = []
    if start_date:
        clauses.append(f"TxnDate >= '{start_date.strftime('%Y-%m-%d')}'")
    if end_date:
        clauses.append(f"TxnDate <= '{end_date.strftime('%Y-%m-%d')}'")
    return " AND ".join(clauses) if clauses else None


def _is_transient_qbo_error(exc: Exception) -> bool:
    """Return True if `exc` is a transient QBO/network fault worth retrying.

    Transient (retry):
      - SevereException (QBO error_code >= 10000 — the "Severe Exception 10000")
      - UnsupportedException (QBO error_code 500-599)
      - Any QuickbooksException whose error_code is a 5xx HTTP status or
        >= 10000 (covers the SDK's bare `QuickbooksException(..., 10000)` raised
        on unparseable / non-OK responses in client.make_request)
      - Raw network connect/read timeouts
      - Direct-API report 5xx (httpx.HTTPStatusError with a 500-599 status,
        raised by response.raise_for_status() in _fetch_report)

    Deterministic (do NOT retry — must surface immediately):
      - AuthorizationException (1-499, incl. HTTP 401), ValidationException
        (2000-4999), ObjectNotFoundException (610), other GeneralException,
        ValueError, and report 4xx (httpx.HTTPStatusError < 500). None of
        these match the checks below.
    """
    if isinstance(exc, _TRANSIENT_NETWORK_ERRORS):
        return True
    # Direct-API report path: a 5xx surfaces as httpx.HTTPStatusError via
    # response.raise_for_status(); retry 5xx, but not deterministic 4xx.
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code <= 599
    if isinstance(exc, (SevereException, UnsupportedException)):
        return True
    if isinstance(exc, QuickbooksException):
        code = exc.error_code
        if isinstance(code, int) and (code >= 10000 or 500 <= code <= 599):
            return True
    return False


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
        credentials = settings.get_qbo_credentials(
            company.region, is_sandbox=company.is_sandbox
        )
        if not credentials:
            env_label = "sandbox" if company.is_sandbox else company.region
            raise ValueError(f"QBO credentials not configured for: {env_label}")

        client_id, client_secret = credentials
        environment = "sandbox" if company.is_sandbox else "production"

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

            credentials = settings.get_qbo_credentials(
                company.region, is_sandbox=company.is_sandbox
            )
            if not credentials:
                env_label = "sandbox" if company.is_sandbox else company.region
                raise ValueError(f"QBO credentials not configured for: {env_label}")

            client_id, client_secret = credentials
            # Sandbox companies use the "sandbox" environment (Development keys);
            # the QuickBooks SDK derives the sandbox API URL from this automatically.
            environment = "sandbox" if company.is_sandbox else "production"

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
    # Transient-fault retry
    # -------------------------------------------------------------------------

    async def _with_retry(self, operation, *, op: str):
        """Await ``operation()`` (an async callable) with transient-fault retry.

        Shared retry driver for READ paths. Retries up to QBO_RETRY_ATTEMPTS
        times (1 + 2) on transient faults (see `_is_transient_qbo_error`),
        backing off per QBO_RETRY_BACKOFF_SECONDS. Deterministic faults (auth,
        validation, not-found, ValueError, report 4xx) raise immediately. If
        retries are exhausted the original exception is re-raised — a
        persistent QBO outage is never masked as an empty/success result.

        Must NOT be used on mutation/create paths: retrying a non-idempotent
        write could double-post to QBO.
        """
        last_exc: Exception | None = None
        for attempt in range(1, QBO_RETRY_ATTEMPTS + 1):
            try:
                return await operation()
            except Exception as exc:
                if not _is_transient_qbo_error(exc):
                    raise
                last_exc = exc
                if attempt == QBO_RETRY_ATTEMPTS:
                    logger.warning(
                        "QBO transient fault on %s: exhausted %d attempts, "
                        "re-raising: %s",
                        op,
                        QBO_RETRY_ATTEMPTS,
                        exc,
                    )
                    raise
                # Clamp to the last backoff so bumping QBO_RETRY_ATTEMPTS beyond
                # the tuple length reuses the final delay instead of IndexError.
                backoff = QBO_RETRY_BACKOFF_SECONDS[
                    min(attempt - 1, len(QBO_RETRY_BACKOFF_SECONDS) - 1)
                ]
                logger.warning(
                    "QBO transient fault on %s (attempt %d/%d), retrying in "
                    "%ds: %s",
                    op,
                    attempt,
                    QBO_RETRY_ATTEMPTS,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
        # Unreachable: loop either returns or raises. Guard for type-checkers.
        raise last_exc  # type: ignore[misc]

    async def _to_thread_with_retry(self, fn, *, op: str):
        """Run a blocking SDK call in a thread, retrying transient QBO faults.

        Thin wrapper over `_with_retry` for the SDK read methods: runs the
        blocking `fn` via asyncio.to_thread on each attempt. See `_with_retry`
        for retry/backoff/re-raise semantics. READ paths only — never wrap a
        non-idempotent mutation (double-post risk).
        """
        return await self._with_retry(lambda: asyncio.to_thread(fn), op=op)

    # -------------------------------------------------------------------------
    # Result paging
    #
    # QBO answers a query with at most QBO_MAX_PAGE_SIZE rows no matter what
    # MAXRESULTS asks for, so a list endpoint cannot return a complete set by
    # raising a limit — it pages with STARTPOSITION, and it has to say when a
    # page is not the whole answer.
    # -------------------------------------------------------------------------

    async def _query_page(
        self,
        entity,
        *,
        client,
        clause: str | None,
        offset: int,
        limit: int,
        op: str,
    ) -> list[dict[str, Any]]:
        """Run one QBO query and return its rows as dicts."""

        def _fetch():
            # QBO's STARTPOSITION is 1-based; `offset` is 0-based on the wire.
            start_position = offset + 1
            if clause:
                return entity.where(
                    clause,
                    start_position=start_position,
                    max_results=limit,
                    qb=client,
                )
            return entity.all(
                start_position=start_position, max_results=limit, qb=client
            )

        objects = await self._to_thread_with_retry(_fetch, op=op)
        return [obj.to_dict() for obj in objects]

    async def _count_matching(
        self, entity, *, client, clause: str | None, op: str
    ) -> int | None:
        """Count the rows a query matches in QBO, across all pages.

        Returns None when QBO answers without a `totalCount`; callers treat
        that as "size unknown", never as "complete".
        """

        def _count():
            return entity.count(clause or "", qb=client)

        return await self._to_thread_with_retry(_count, op=f"{op}_count")

    async def _fetch_page(
        self,
        entity,
        *,
        client,
        clause: str | None,
        offset: int,
        limit: int,
        op: str,
    ) -> PagedResult:
        """Fetch one page and establish whether it is the whole result set.

        A short page ends the result set, so `offset + len(rows)` is the total
        and the COUNT round trip is skipped. A full page is ambiguous — it is
        equally the last page of an exactly-divisible set and the first of
        many — and that ambiguity is precisely what used to be resolved
        wrongly in silence, so it costs one COUNT query to resolve it.

        An empty page past the first is the one short page that proves
        nothing: QBO answers a STARTPOSITION beyond the end with no rows, so
        `offset` there is a number the caller chose rather than the size of
        anything. That case is counted rather than inferred.
        """
        rows = await self._query_page(
            entity, client=client, clause=clause, offset=offset, limit=limit, op=op
        )
        overshot = not rows and offset > 0
        if len(rows) < limit and not overshot:
            return PagedResult(
                rows=rows, offset=offset, total=offset + len(rows), has_more=False
            )

        total = await self._count_matching(entity, client=client, clause=clause, op=op)
        if overshot:
            return PagedResult(rows=rows, offset=offset, total=total, has_more=False)

        has_more = total is None or total > offset + len(rows)
        return PagedResult(rows=rows, offset=offset, total=total, has_more=has_more)

    async def _fetch_all_pages(
        self,
        entity,
        *,
        client,
        clause: str | None,
        op: str,
        max_pages: int = QBO_MAX_PAGES_PER_WALK,
    ) -> PagedResult:
        """Walk every page of a query, for endpoints that aggregate server-side.

        An aggregate computed over a truncated slice is a wrong number wearing
        a 200, so these walk to the end. The page budget bounds the walk at
        `max_pages * QBO_MAX_PAGE_SIZE` rows; exhausting it returns what was
        collected with `has_more` true rather than passing a prefix off as the
        whole ledger.
        """
        rows: list[dict[str, Any]] = []
        for _ in range(max_pages):
            page = await self._query_page(
                entity,
                client=client,
                clause=clause,
                offset=len(rows),
                limit=QBO_MAX_PAGE_SIZE,
                op=op,
            )
            rows.extend(page)
            if len(page) < QBO_MAX_PAGE_SIZE:
                return PagedResult(rows=rows, offset=0, total=len(rows), has_more=False)

        total = await self._count_matching(entity, client=client, clause=clause, op=op)
        return PagedResult(
            rows=rows,
            offset=0,
            total=total,
            has_more=total is None or total > len(rows),
        )

    # -------------------------------------------------------------------------
    # Entity Methods (async via to_thread)
    # -------------------------------------------------------------------------

    async def get_invoices(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of invoices, optionally filtered by date range."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Invoice,
            client=client,
            clause=_txn_date_clause(start_date, end_date),
            offset=offset,
            limit=max_results,
            op="get_invoices",
        )

    async def get_all_invoices(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> PagedResult:
        """Get every invoice in a date range, paging until QBO runs out."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_all_pages(
            Invoice,
            client=client,
            clause=_txn_date_clause(start_date, end_date),
            op="get_all_invoices",
        )

    async def get_invoice_by_id(
        self, company_id: int, invoice_id: int
    ) -> dict[str, Any] | None:
        """Get a specific invoice by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Invoice.get(invoice_id, qb=client)

        invoice = await self._to_thread_with_retry(_fetch, op="get_invoice_by_id")
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

        invoice = await self._to_thread_with_retry(_fetch, op="get_invoice_by_doc_number")
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

        customers = await self._to_thread_with_retry(_fetch, op="get_customers")
        return [c.to_dict() for c in customers]

    async def get_customer_by_id(
        self, company_id: int, customer_id: int
    ) -> dict[str, Any] | None:
        """Get a specific customer by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Customer.get(customer_id, qb=client)

        customer = await self._to_thread_with_retry(_fetch, op="get_customer_by_id")
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

        vendors = await self._to_thread_with_retry(_fetch, op="get_vendors")
        return [v.to_dict() for v in vendors]

    async def get_vendor_by_id(
        self, company_id: int, vendor_id: int
    ) -> dict[str, Any] | None:
        """Get a specific vendor by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Vendor.get(vendor_id, qb=client)

        vendor = await self._to_thread_with_retry(_fetch, op="get_vendor_by_id")
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
                if customer_data.get(ref_field):
                    ref = Ref()
                    ref.value = str(customer_data[ref_field]["value"])
                    ref.name = customer_data[ref_field].get("name")
                    setattr(cust, ref_field, ref)

            return cust.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    async def create_account(
        self, company_id: int, account_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an Account (chart-of-accounts entry) in QBO.

        Useful for seeding a sandbox company with the accounts that production
        Items / transactions reference before recreating them.

        Args:
            company_id: QBO company ID
            account_data: Dict with Name (required) and AccountType (required,
                e.g. "Bank", "Expense", "Income", "Other Current Asset",
                "Accounts Payable", "Credit Card", "Equity", "Fixed Asset").
                Optional: AccountSubType, AcctNum, Description, Classification,
                Active, SubAccount, CurrencyRef, ParentRef.

        Returns:
            Created Account as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            acct = Account()

            # Simple string fields
            for field in (
                "Name", "AccountType", "AccountSubType", "AcctNum",
                "Description", "Classification",
            ):
                if field in account_data:
                    setattr(acct, field, account_data[field])

            # Bool fields
            for bool_field in ("Active", "SubAccount"):
                if bool_field in account_data:
                    setattr(acct, bool_field, account_data[bool_field])

            # Ref fields
            for ref_field in ("CurrencyRef", "ParentRef"):
                if account_data.get(ref_field):
                    ref = Ref()
                    ref.value = str(account_data[ref_field]["value"])
                    ref.name = account_data[ref_field].get("name")
                    setattr(acct, ref_field, ref)

            return acct.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    async def create_item(
        self, company_id: int, item_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an Item (product/service) in QBO.

        Useful for recreating production Items in a sandbox for testing. Note
        that account Refs (IncomeAccountRef, etc.) must point at accounts in the
        *target* company — a production account Id won't exist in the sandbox,
        so resolve the sandbox account Id (e.g. via GET /api/accounts/) before
        creating.

        Args:
            company_id: QBO company ID
            item_data: Dict with Name (required) and Type (required: "Service",
                "NonInventory", or "Inventory"). Optional: Description,
                PurchaseDesc, Sku, UnitPrice, PurchaseCost, Taxable,
                SalesTaxIncluded, PurchaseTaxIncluded, TrackQtyOnHand, QtyOnHand,
                InvStartDate, Active, SubItem, and Ref fields IncomeAccountRef
                (required for sale-able items), ExpenseAccountRef,
                AssetAccountRef (required for Inventory), ParentRef,
                SalesTaxCodeRef, PurchaseTaxCodeRef.

        Returns:
            Created Item as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            item = Item()

            # Simple string fields
            for field in (
                "Name", "Type", "Description", "PurchaseDesc", "Sku",
                "InvStartDate",
            ):
                if field in item_data:
                    setattr(item, field, item_data[field])

            # Numeric fields
            for num_field in ("UnitPrice", "PurchaseCost", "QtyOnHand"):
                if num_field in item_data:
                    setattr(item, num_field, item_data[num_field])

            # Bool fields
            for bool_field in (
                "Active", "Taxable", "SalesTaxIncluded", "PurchaseTaxIncluded",
                "TrackQtyOnHand", "SubItem",
            ):
                if bool_field in item_data:
                    setattr(item, bool_field, item_data[bool_field])

            # Ref fields
            for ref_field in (
                "IncomeAccountRef", "ExpenseAccountRef", "AssetAccountRef",
                "ParentRef", "SalesTaxCodeRef", "PurchaseTaxCodeRef",
            ):
                if item_data.get(ref_field):
                    ref = Ref()
                    ref.value = str(item_data[ref_field]["value"])
                    ref.name = item_data[ref_field].get("name")
                    setattr(item, ref_field, ref)

            return item.save(qb=client)

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
                if vendor_data.get(ref_field):
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

        accounts = await self._to_thread_with_retry(_fetch, op="get_accounts")
        return [a.to_dict() for a in accounts]

    async def get_account_by_id(
        self, company_id: int, account_id: int
    ) -> dict[str, Any] | None:
        """Get a specific account by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Account.get(account_id, qb=client)

        account = await self._to_thread_with_retry(_fetch, op="get_account_by_id")
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

        account = await self._to_thread_with_retry(_fetch, op="get_account_by_number")
        return account.to_dict() if account else None

    async def get_bills(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of bills, optionally filtered by date range."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Bill,
            client=client,
            clause=_txn_date_clause(start_date, end_date),
            offset=offset,
            limit=max_results,
            op="get_bills",
        )

    async def get_bill_by_id(
        self, company_id: int, bill_id: int
    ) -> dict[str, Any] | None:
        """Get a specific bill by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Bill.get(bill_id, qb=client)

        bill = await self._to_thread_with_retry(_fetch, op="get_bill_by_id")
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

    async def delete_invoice(
        self, company_id: int, invoice_id: int
    ) -> dict[str, Any]:
        """Delete an invoice in QBO.

        Args:
            company_id: QBO company ID
            invoice_id: QBO Invoice ID to delete

        Returns:
            Deleted Invoice as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _delete():
            invoice = Invoice.get(invoice_id, qb=client)
            if not invoice:
                raise ValueError(f"Invoice {invoice_id} not found")
            return invoice.delete(qb=client)

        result = await asyncio.to_thread(_delete)
        return result.to_dict() if hasattr(result, 'to_dict') else {"Id": str(invoice_id), "status": "Deleted"}

    async def update_bill(
        self, company_id: int, bill_id: str, sparse_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Sparse-update a Bill in QBO.

        Builds a POST against /v3/company/{realm}/bill?operation=update with
        ``Id`` and ``sparse: true`` injected server-side, plus whatever fields
        the caller supplied (``SyncToken`` is required by QBO). Returns the
        updated Bill as a dict.

        SyncToken mismatch (QBO error code 5310) raises ValidationException;
        the router translates that into a 409.

        Args:
            company_id: QBO company ID
            bill_id: QBO Bill ID to update
            sparse_payload: Fields to update (must include SyncToken)

        Returns:
            Updated Bill as dict
        """
        import json as _json

        company = self._get_company(company_id)
        client = self._get_client(company)

        def _update():
            url = "{0}/company/{1}/bill".format(client.api_url, client.company_id)
            payload = dict(sparse_payload)
            payload["Id"] = str(bill_id)
            payload["sparse"] = True
            params = {"operation": "update"}
            response = client.post(url, _json.dumps(payload), params=params)
            if isinstance(response, dict) and "Bill" in response:
                return Bill.from_json(response["Bill"])
            return response

        logger.info(f"Updating Bill {bill_id} for company {company.code}")
        result = await asyncio.to_thread(_update)
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {"Id": str(bill_id), "status": "Updated"}

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
                if bill_data.get(ref_field):
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
                    if detail_data.get(ref_field):
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
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of payments, optionally filtered by date range."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Payment,
            client=client,
            clause=_txn_date_clause(start_date, end_date),
            offset=offset,
            limit=max_results,
            op="get_payments",
        )

    async def get_payment_by_id(
        self, company_id: int, payment_id: int
    ) -> dict[str, Any] | None:
        """Get a specific payment by ID."""
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Payment.get(payment_id, qb=client)

        payment = await self._to_thread_with_retry(_fetch, op="get_payment_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_bill_payments")
        return [i.to_dict() for i in items]

    async def get_bill_payment_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return BillPayment.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_bill_payment_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_bill_payments_by_bill_id")
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

            if payment_data.get("VendorRef"):
                ref = Ref()
                ref.value = str(payment_data["VendorRef"]["value"])
                ref.name = payment_data["VendorRef"].get("name")
                bp.VendorRef = ref

            if payment_data.get("APAccountRef"):
                ref = Ref()
                ref.value = str(payment_data["APAccountRef"]["value"])
                ref.name = payment_data["APAccountRef"].get("name")
                bp.APAccountRef = ref

            if payment_data.get("DepartmentRef"):
                ref = Ref()
                ref.value = str(payment_data["DepartmentRef"]["value"])
                ref.name = payment_data["DepartmentRef"].get("name")
                bp.DepartmentRef = ref

            if payment_data.get("PayType") == "Check" and payment_data.get("CheckPayment"):
                cp = CheckPayment()
                if payment_data["CheckPayment"].get("BankAccountRef"):
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

        items = await self._to_thread_with_retry(_fetch, op="get_credit_memos")
        return [i.to_dict() for i in items]

    async def get_credit_memo_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CreditMemo.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_credit_memo_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_deposits")
        return [i.to_dict() for i in items]

    async def get_deposit_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Deposit.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_deposit_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_estimates")
        return [i.to_dict() for i in items]

    async def get_estimate_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Estimate.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_estimate_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_journal_entries")
        return [i.to_dict() for i in items]

    async def get_journal_entry_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return JournalEntry.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_journal_entry_by_id")
        return result.to_dict() if result else None

    async def create_journal_entry(
        self, company_id: int, entry_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a JournalEntry in QBO.

        Args:
            company_id: QBO company ID
            entry_data: Dict with TxnDate, DocNumber, PrivateNote, Adjustment,
                CurrencyRef, ExchangeRate, and Line[] (each line: Amount,
                Description, plus JournalEntryLineDetail with PostingType,
                AccountRef, ClassRef, DepartmentRef, TaxCodeRef, and an
                optional Entity {Type, EntityRef}).

        Returns:
            Created JournalEntry as dict
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _create():
            je = JournalEntry()

            for field in ("TxnDate", "DocNumber", "PrivateNote"):
                if field in entry_data:
                    setattr(je, field, entry_data[field])

            if "Adjustment" in entry_data:
                je.Adjustment = entry_data["Adjustment"]
            if "ExchangeRate" in entry_data:
                je.ExchangeRate = entry_data["ExchangeRate"]
            if "TotalAmt" in entry_data:
                je.TotalAmt = entry_data["TotalAmt"]

            if entry_data.get("CurrencyRef"):
                ref = Ref()
                ref.value = str(entry_data["CurrencyRef"]["value"])
                ref.name = entry_data["CurrencyRef"].get("name")
                je.CurrencyRef = ref

            for line_data in entry_data.get("Line", []):
                line = JournalEntryLine()
                if "Amount" in line_data:
                    line.Amount = line_data["Amount"]
                if "Description" in line_data:
                    line.Description = line_data["Description"]
                if "DetailType" in line_data:
                    line.DetailType = line_data["DetailType"]

                detail_data = line_data.get("JournalEntryLineDetail", {}) or {}
                detail = JournalEntryLineDetail()
                if "PostingType" in detail_data:
                    detail.PostingType = detail_data["PostingType"]
                if "BillableStatus" in detail_data:
                    detail.BillableStatus = detail_data["BillableStatus"]
                if "TaxApplicableOn" in detail_data:
                    detail.TaxApplicableOn = detail_data["TaxApplicableOn"]
                if "TaxAmount" in detail_data:
                    detail.TaxAmount = detail_data["TaxAmount"]

                for ref_field in ("AccountRef", "ClassRef", "DepartmentRef", "TaxCodeRef"):
                    if detail_data.get(ref_field):
                        ref = Ref()
                        ref.value = str(detail_data[ref_field]["value"])
                        ref.name = detail_data[ref_field].get("name")
                        setattr(detail, ref_field, ref)

                entity_data = detail_data.get("Entity") or detail_data.get("EntityRef")
                if entity_data:
                    entity = JournalEntryEntity()
                    if "Type" in entity_data:
                        entity.Type = entity_data["Type"]
                    inner_ref = entity_data.get("EntityRef")
                    if inner_ref:
                        ref = Ref()
                        ref.value = str(inner_ref["value"])
                        ref.name = inner_ref.get("name")
                        entity.EntityRef = ref
                    detail.Entity = entity

                line.JournalEntryLineDetail = detail
                je.Line.append(line)

            return je.save(qb=client)

        result = await asyncio.to_thread(_create)
        return result.to_dict()

    async def void_journal_entry(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any]:
        """Void a JournalEntry in QBO.

        QBO has no first-class void endpoint for JournalEntry; the SDK's
        VoidMixin is not applied to this object. We fetch the JE for its
        SyncToken, then issue a sparse update with operation=update&include=void
        against the journalentry endpoint.

        Args:
            company_id: QBO company ID
            entity_id: QBO JournalEntry ID to void

        Returns:
            Voided JournalEntry as dict
        """
        import json as _json

        company = self._get_company(company_id)
        client = self._get_client(company)

        def _void():
            je = JournalEntry.get(entity_id, qb=client)
            if not je:
                raise ValueError(f"JournalEntry {entity_id} not found")

            url = "{0}/company/{1}/journalentry".format(client.api_url, client.company_id)
            payload = {
                "Id": str(je.Id),
                "SyncToken": je.SyncToken,
                "sparse": True,
            }
            params = {"operation": "update", "include": "void"}
            response = client.post(url, _json.dumps(payload), params=params)
            if isinstance(response, dict) and "JournalEntry" in response:
                return JournalEntry.from_json(response["JournalEntry"])
            return response

        result = await asyncio.to_thread(_void)
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {"Id": str(entity_id), "status": "Voided"}

    # -------------------------------------------------------------------------
    # Purchase
    # -------------------------------------------------------------------------

    async def get_purchases(
        self,
        company_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of purchases, optionally filtered by date range."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Purchase,
            client=client,
            clause=_txn_date_clause(start_date, end_date),
            offset=offset,
            limit=max_results,
            op="get_purchases",
        )

    async def get_purchase_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Purchase.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_purchase_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_purchase_orders")
        return [i.to_dict() for i in items]

    async def get_purchase_order_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return PurchaseOrder.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_purchase_order_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_refund_receipts")
        return [i.to_dict() for i in items]

    async def get_refund_receipt_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return RefundReceipt.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_refund_receipt_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_sales_receipts")
        return [i.to_dict() for i in items]

    async def get_sales_receipt_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return SalesReceipt.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_sales_receipt_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_transfers")
        return [i.to_dict() for i in items]

    async def get_transfer_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Transfer.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_transfer_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_vendor_credits")
        return [i.to_dict() for i in items]

    async def get_vendor_credit_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return VendorCredit.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_vendor_credit_by_id")
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
                if credit_data.get(ref_field):
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
                    if detail_data.get(ref_field):
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

        items = await self._to_thread_with_retry(_fetch, op="get_items")
        return [i.to_dict() for i in items]

    async def get_item_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Item.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_item_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_employees")
        return [i.to_dict() for i in items]

    async def get_employee_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Employee.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_employee_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_departments")
        return [i.to_dict() for i in items]

    async def get_department_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Department.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_department_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_time_activities")
        return [i.to_dict() for i in items]

    async def get_time_activity_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TimeActivity.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_time_activity_by_id")
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

        result = await self._to_thread_with_retry(_fetch, op="get_company_info")
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

        result = await self._to_thread_with_retry(_fetch, op="get_preferences")
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

        items = await self._to_thread_with_retry(_fetch, op="get_tax_agencies")
        return [i.to_dict() for i in items]

    async def get_tax_agency_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxAgency.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_tax_agency_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_tax_codes")
        return [i.to_dict() for i in items]

    async def get_tax_code_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxCode.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_tax_code_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_tax_rates")
        return [i.to_dict() for i in items]

    async def get_tax_rate_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TaxRate.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_tax_rate_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_company_currencies")
        return [i.to_dict() for i in items]

    async def get_company_currency_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CompanyCurrency.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_company_currency_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_exchange_rates")
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

        items = await self._to_thread_with_retry(_fetch, op="get_payment_methods")
        return [i.to_dict() for i in items]

    async def get_payment_method_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return PaymentMethod.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_payment_method_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_terms")
        return [i.to_dict() for i in items]

    async def get_term_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Term.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_term_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_classes")
        return [i.to_dict() for i in items]

    async def get_class_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return TrackingClass.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_class_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_customer_types")
        return [i.to_dict() for i in items]

    async def get_customer_type_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return CustomerType.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_customer_type_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_attachables")
        return [i.to_dict() for i in items]

    async def get_attachable_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return Attachable.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_attachable_by_id")
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

        items = await self._to_thread_with_retry(_fetch, op="get_recurring_transactions")
        return [i.to_dict() for i in items]

    async def get_recurring_transaction_by_id(
        self, company_id: int, entity_id: int
    ) -> dict[str, Any] | None:
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _fetch():
            return RecurringTransaction.get(entity_id, qb=client)

        result = await self._to_thread_with_retry(_fetch, op="get_recurring_transaction_by_id")
        return result.to_dict() if result else None

    # -------------------------------------------------------------------------
    # Reports (Direct API - SDK doesn't support QBO Reports)
    # -------------------------------------------------------------------------

    async def _fetch_report(
        self, company: QboCompany, report_name: str, params: dict[str, str]
    ) -> dict[str, Any]:
        """Fetch a QBO report via direct API call, retrying transient faults.

        Reports are read-only GETs, so they get the same bounded transient-
        fault retry as the SDK read paths (via `_with_retry`): connect/read
        timeouts and report 5xx (httpx.HTTPStatusError) are retried, while 4xx
        and other deterministic faults surface immediately.
        """
        # Ensure token is fresh
        if self._needs_refresh(company):
            self._refresh_token(company)

        base_url = (
            "https://sandbox-quickbooks.api.intuit.com"
            if company.is_sandbox
            else "https://quickbooks.api.intuit.com"
        )
        url = f"{base_url}/v3/company/{company.realm_id}/reports/{report_name}"
        params["minorversion"] = str(QBO_MINOR_VERSION)

        async def _do() -> dict[str, Any]:
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

        return await self._with_retry(_do, op=f"report:{report_name}")

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
