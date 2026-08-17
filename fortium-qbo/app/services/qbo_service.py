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
    ObjectNotFoundException,
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
from app.utils.qbo_query import boolean_equals, date_bound, id_in, string_equals

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

# Sort key every paged query is ordered by. STARTPOSITION indexes into an
# ordering, so the ordering has to be one where a row written during a walk
# cannot land in front of the cursor. Id is ascending and assigned at creation;
# QBO's default order is neither Id nor TxnDate and is not documented at all.
QBO_PAGE_ORDER_BY = "Id"

# QBO writes the payment side of a bill/payment link onto the bill as a
# LinkedTxn whose TxnType is BillPaymentCheck or BillPaymentCreditCard. A bill
# also links to PurchaseOrders, VendorCredits and ReimburseCharges, which are
# not payments, so the type is matched rather than assumed.
BILL_PAYMENT_LINK_PREFIX = "BillPayment"

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

    The bounds are `datetime` objects rather than strings, and `date_bound`
    refuses anything that is not one, so the only text that reaches the query
    is a serialised date.
    """
    clauses = []
    if start_date:
        clauses.append(date_bound("TxnDate", ">=", start_date))
    if end_date:
        clauses.append(date_bound("TxnDate", "<=", end_date))
    return " AND ".join(clauses) if clauses else None


def _active_clause(active_only: bool) -> str | None:
    """Build the Active portion of a QBO query, or None for everything.

    `boolean_equals` is called before the branch rather than inside it. Testing
    `if active_only` first would hand the gate a literal `True` and let the
    caller's own value through unexamined: `_active_clause("false")` built
    `Active = true`, and `_active_clause(0)` dropped the filter and returned
    every inactive row. Unreachable over HTTP, where FastAPI coerces the query
    param to `bool` before it arrives — but a type gate its only call site
    steps around is not a gate.

    These endpoints used to reach QuickBooks through `Entity.filter(...)`,
    which does go through `where()` but builds its clause with the SDK's
    `build_where_clause` — the helper `qbo_query` exists to replace, since it
    escapes a quote and leaves a backslash alone. The unfiltered branch used
    `all()`, whose ORDERBY spelling differs from `where()`'s. One clause
    builder and one dialect now.
    """
    clause = boolean_equals("Active", active_only)
    return clause if active_only else None


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
        """Run one QBO query, ordered by Id, and return its rows as dicts.

        The ordering is load-bearing. QBO's default order is neither Id nor
        TxnDate — an unfiltered invoice query answers 94670, 93743, 94659,
        94679, 94678 — and STARTPOSITION indexes into whatever that order is.
        It is stable for a set nothing is writing to, which is why a walk looks
        correct in a quiet moment, but a row inserted mid-walk lands wherever
        that undocumented order puts it. Land it before the cursor and one row
        shifts across the page boundary: returned twice, or never returned at
        all. A walk of the bill ledger is ~28 pages and several minutes against
        a live AP ledger, and `/invoices/trailing-12m/summary` sums TotalAmt
        across its walk, so the skew reads as a wrong dollar figure inside a
        `complete: true` response — the same defect class this paging exists to
        remove. Ordering by an ascending Id puts every insert past the cursor,
        where it can neither duplicate nor skip a row.

        Both the filtered and unfiltered cases go through `where()` so exactly
        one ORDERBY spelling is ever sent. The SDK is internally inconsistent
        about it — `ListMixin.where()` emits ` ORDERBY `, `ListMixin.all()`
        emits ` ORDER BY ` — and splitting on `clause` would put two query
        dialects into production, one per code path. `where("")` builds the
        same SELECT `all()` would, minus one special case: `all()` asks for
        `SELECT *, Sku` when the entity is Item, because QBO leaves Sku out of
        `*`. So paging Item means carrying that column onto the clause path
        first, or every item comes back without its SKU and the response still
        looks well formed. Stated as the rule rather than as a list of which
        entities are currently safe — that list went stale twice in two PRs,
        and a checklist nobody updates is worse than no checklist.

        Two conditions an entity has to meet before it belongs here: it is not
        Item (above), and it has a top-level `Id` to order by. Ordering is what
        makes an offset mean the same thing on two different requests, so an
        entity without an `Id` cannot be paged at all — see
        `get_recurring_transactions`, which is why that one is still unpaged.
        """

        def _fetch():
            # QBO's STARTPOSITION is 1-based; `offset` is 0-based on the wire.
            return entity.where(
                clause or "",
                order_by=QBO_PAGE_ORDER_BY,
                start_position=offset + 1,
                max_results=limit,
                qb=client,
            )

        objects = await self._to_thread_with_retry(_fetch, op=op)
        return [obj.to_dict() for obj in objects]

    async def _count_matching(
        self, entity, *, client, clause: str | None, op: str
    ) -> int | None:
        """Count the rows a query matches in QBO, across all pages.

        Returns None when the size could not be established, whether because
        QBO answered without a `totalCount` or because the COUNT itself
        faulted. Callers treat None as "size unknown", never as "complete".

        Never raises. Both callers reach this only after QuickBooks has
        already served them rows, so a COUNT that fails leaves the size
        unknown rather than the page invalid — and letting it propagate
        discards data QBO successfully returned, turning a served page into a
        500 through the router's catch-all. In `_fetch_all_pages` that is up
        to twenty pages of rows thrown away over a failed follow-up query.

        Logged rather than swallowed. `total=None` makes `has_more` True at
        both call sites, so the caller is told the set may continue, which is
        the safe reading — but a COUNT failing every time is a real fault and
        the response is otherwise indistinguishable from QBO declining to
        count. The log line carries the same `{op}_count` label
        `_to_thread_with_retry` uses, so a degrading COUNT and its retries
        correlate.

        At ERROR, not WARNING: this branch is only reached once
        `_to_thread_with_retry` has exhausted its attempts or judged the fault
        non-transient, which is the terminal case. This module already draws
        that line — the retry loop warns per attempt, and a refresh that
        finally fails logs an error. A COUNT faulting on every request strips
        X-Total-Count from every list response indefinitely, and there is no
        error tracking in this service to catch it above the log.

        `except Exception` and not BaseException: `asyncio.CancelledError`
        derives from BaseException, so a cancelled request still unwinds
        rather than being recorded as an unknown count.
        """

        def _count():
            return entity.count(clause or "", qb=client)

        try:
            return await self._to_thread_with_retry(_count, op=f"{op}_count")
        except Exception:
            logger.error(
                "%s_count failed; serving the rows with an unknown total", op,
                exc_info=True,
            )
            return None

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

        An empty page past the first proves the end of the result set — QBO
        answers a STARTPOSITION beyond the end with no rows — but it does not
        establish the size, because `offset` there is a number the caller chose
        rather than the count of anything. So `has_more` is False on the
        evidence of the empty page while `total` comes from a COUNT, and stays
        None if QBO does not answer it. That is the one place the two facts
        come from different sources.
        """
        rows = await self._query_page(
            entity, client=client, clause=clause, offset=offset, limit=limit, op=op
        )
        overshot = not rows and offset > 0
        if len(rows) < limit and not overshot:
            return PagedResult(
                rows=rows, offset=offset, total=offset + len(rows), has_more=False
            )

        # `_count_matching` never raises: a COUNT that faults comes back as
        # None, the same "size unknown" this already handles.
        total = await self._count_matching(entity, client=client, clause=clause, op=op)
        if overshot:
            # has_more stays False even when the COUNT went unanswered. The
            # empty page is itself the proof that no row exists at or past this
            # offset, so completeness here is established rather than inferred
            # from `total`. Flipping it to True on `total is None` would claim
            # rows exist past a page just proven empty, and hand back a
            # next_offset of offset + 0 — a cursor that never advances.
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
            results = Invoice.where(string_equals("DocNumber", doc_number), qb=client)
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
        self,
        company_id: int,
        active_only: bool = True,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of vendors, optionally limited to active ones."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Vendor,
            client=client,
            clause=_active_clause(active_only),
            offset=offset,
            limit=max_results,
            op="get_vendors",
        )

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
        self,
        company_id: int,
        active_only: bool = True,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of the chart of accounts."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Account,
            client=client,
            clause=_active_clause(active_only),
            offset=offset,
            limit=max_results,
            op="get_accounts",
        )

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
            results = Account.where(string_equals("AcctNum", account_number), qb=client)
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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of bill payments."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            BillPayment,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_bill_payments",
        )

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
        """Get the bill payments linked to a specific bill.

        Read the link off the bill, then fetch the payments it names. The bill
        carries the payment side of the link — QBO writes a
        `BillPaymentCheck` / `BillPaymentCreditCard` LinkedTxn onto the bill
        when it is paid — so the payments are addressable by Id and this costs
        two queries whatever the age of the bill.

        It used to pull the first 1000 BillPayments in the ledger and filter
        them in Python for a link back to the bill. That window was the most
        recent few months, so a bill paid before it answered `[]` with a 200 —
        the same answer as a bill that was never paid, to a question that is
        usually asked as "has this been paid?". Measured against production on
        2026-08-03: bill 64848 (2024-01-31, $25,000, Balance 0) returned no
        payments, while its LinkedTxn named BillPayment 65852, whose own
        LinkedTxn names bill 64848. Across twelve bills recent enough for the
        old path to work, both routes returned the identical payment.

        Walking the whole BillPayment ledger instead would be correct and
        useless: ~27,000 rows is minutes per request for an answer two queries
        give.
        """
        company = self._get_company(company_id)
        client = self._get_client(company)

        def _read_bill():
            return Bill.get(bill_id, qb=client)

        try:
            bill = await self._to_thread_with_retry(
                _read_bill, op="get_bill_payments_by_bill_id_bill"
            )
        except ObjectNotFoundException as exc:
            # 404, not 500: the caller named a bill that does not exist. Also
            # not `[]` — that would read as "this bill has no payments".
            raise ValueError(f"Bill not found: {bill_id}") from exc

        payment_ids: list[str] = []
        for txn in bill.LinkedTxn:
            # BillPaymentCheck and BillPaymentCreditCard both appear here, as
            # do PurchaseOrder / VendorCredit / ReimburseCharge links, which
            # are not payments. str() because the SDK's LinkedTxn defaults
            # TxnType to 0 for a link QBO sent without one.
            if not str(txn.TxnType).startswith(BILL_PAYMENT_LINK_PREFIX):
                continue
            txn_id = str(txn.TxnId)
            if txn_id not in payment_ids:
                payment_ids.append(txn_id)

        if not payment_ids:
            return []

        def _read_payments():
            return BillPayment.where(
                id_in("Id", payment_ids),
                max_results=QBO_MAX_PAGE_SIZE,
                qb=client,
            )

        items = await self._to_thread_with_retry(
            _read_payments, op="get_bill_payments_by_bill_id"
        )
        rows = [i.to_dict() for i in items]

        # The bill named these ids; the query asked for exactly them. An id
        # that comes back short was named by the bill and could not be read —
        # QBO leaves the LinkedTxn in place on some delete paths, so the link
        # outlives the payment. Returning what did resolve answers "what paid
        # this bill?" with a subset that looks like the whole: a $25,000 bill
        # settled by $15,000 + $10,000 reads as $15,000 paid, and the 0-of-N
        # case reads as `[]`, which is the never-paid answer this lookup was
        # rewritten to stop giving. Refusing is the only answer that is not
        # quietly wrong.
        returned = {str(row.get("Id")) for row in rows}
        unresolved = [pid for pid in payment_ids if pid not in returned]
        if unresolved:
            logger.error(
                "Bill %s links %d BillPayment(s) but only %d resolved; "
                "unresolved id(s): %s",
                bill_id,
                len(payment_ids),
                len(rows),
                ", ".join(unresolved),
            )
            # RuntimeError, not ValueError: the router reads ValueError as
            # "Bill not found" and answers 404, and this bill was found.
            raise RuntimeError(
                f"Bill {bill_id} links {len(payment_ids)} BillPayment(s) but "
                f"only {len(rows)} resolved; unresolved id(s): "
                f"{', '.join(unresolved)}"
            )

        return rows

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of credit memos."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            CreditMemo,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_credit_memos",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of deposits."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Deposit,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_deposits",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of estimates."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Estimate,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_estimates",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of journal entries."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            JournalEntry,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_journal_entries",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of purchase orders."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            PurchaseOrder,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_purchase_orders",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of refund receipts."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            RefundReceipt,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_refund_receipts",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of sales receipts."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            SalesReceipt,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_sales_receipts",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of transfers."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            Transfer,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_transfers",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of vendor credits."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            VendorCredit,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_vendor_credits",
        )

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
        self,
        company_id: int,
        max_results: int = QBO_MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> PagedResult:
        """Get one page of time activities."""
        company = self._get_company(company_id)
        client = self._get_client(company)
        return await self._fetch_page(
            TimeActivity,
            client=client,
            clause=None,
            offset=offset,
            limit=max_results,
            op="get_time_activities",
        )

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
        """Get recurring transactions. Deliberately NOT paged — see below.

        This is the one entity in the group #12 covers that cannot go through
        `_fetch_page`. RecurringTransaction is a wrapper, not a row: the SDK
        class carries no `Id` field, only a `class_dict` mapping a wrapped
        type name to a Recurring<Type>, and live rows come back shaped
        `{"JournalEntry": {...}}` with no top-level Id at all.

        `_query_page` orders every page by `Id`, which is what makes an offset
        mean the same thing twice. Sending `ORDERBY Id` against an entity that
        has no Id gets one of two answers, and both are worse than not paging:
        QBO faults, turning a working 200 into a catch-all 500, or it ignores
        the clause, in which case `offset` silently does nothing while
        X-Has-More and X-Next-Offset tell the caller to keep going and it
        assembles the same rows over and over.

        Not paging costs nothing here. These are scheduling templates, not a
        ledger: measured against production on 2026-08-17 the four connected
        companies hold 14, 0, 0 and 0 of them. The 1000-row ceiling that #12
        is about is not reachable here, so the truncation this endpoint could
        suffer is theoretical while the paging breakage would be immediate.
        """
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
