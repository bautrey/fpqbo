"""Tests for result paging on the transaction list endpoints.

The bug: QuickBooks answers a query with at most 1000 rows, the routers
offered no way to ask for the next 1000, and nothing in a response said a
page was not the whole answer. Probed live on 2026-08-03, `/api/bills/`
returned 1000 rows for no filter and 1000 rows for the whole of 2024 — while
January 2024 alone returned 314 and the twelve months of 2024 sum to 4,170.
The ledger holds roughly 27,000 bills. Every caller asking a broad question
got 3.7% of it back with a 200.

So the assertions here are about two things a caller could not previously do:
ask for rows past the first page, and tell a partial page from a complete one.
Asserting on the rows alone would prove nothing — a truncated response was
always a perfectly valid array of perfectly valid bills.

The fixture entities record the query arguments the service handed the SDK,
so what is asserted is the STARTPOSITION/MAXRESULTS that actually went to
QuickBooks, not a value that merely reached the handler.
"""

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickbooks.mixins import ListMixin

from app.dependencies.api_auth import verify_api_key
from app.routers import (
    accounts,
    bill_payments,
    bills,
    credit_memos,
    deposits,
    estimates,
    invoices,
    journal_entries,
    payments,
    purchase_orders,
    purchases,
    refund_receipts,
    sales_receipts,
    time_activities,
    transfers,
    vendor_credits,
    vendors,
)
from app.services.qbo_service import QBOService
from app.utils.paging import QBO_MAX_PAGE_SIZE, PagedResult, apply_paging_headers

PAGE = QBO_MAX_PAGE_SIZE


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Row:
    """Minimal stand-in for a python-quickbooks entity object."""

    def __init__(self, row_id: int):
        self._id = row_id

    def to_dict(self):
        return {"Id": str(self._id), "TxnDate": "2024-01-15"}


class _FakeEntity:
    """Fake quickbooks entity class backed by a fixed-size ledger.

    Honours STARTPOSITION/MAXRESULTS the way QuickBooks does — 1-based start,
    never more rows than asked for, never more than the page ceiling — so a
    test that pages off the end of the ledger reproduces the real shape.
    """

    def __init__(self, ledger_size: int):
        self.ledger_size = ledger_size
        self.queries: list[dict] = []
        self.count_calls: list[str] = []

    def _slice(self, where_clause, order_by, start_position, max_results):
        self.queries.append(
            {
                "where": where_clause,
                "order_by": order_by,
                "start_position": start_position,
                "max_results": max_results,
            }
        )
        start = int(start_position or 1) - 1
        limit = min(int(max_results or PAGE), PAGE)
        return [_Row(i) for i in range(start, min(start + limit, self.ledger_size))]

    def where(self, clause, order_by="", start_position="", max_results="", qb=None):
        return self._slice(clause, order_by, start_position, max_results)

    def all(self, order_by="", start_position="", max_results="", qb=None):
        # The paged reads go through where() for every query, filtered or not,
        # because the two SDK methods spell the ORDERBY clause differently and
        # only one spelling should ever reach QuickBooks.
        raise AssertionError("paged reads must not go through ListMixin.all()")

    def count(self, where_clause="", qb=None):
        self.count_calls.append(where_clause)
        return self.ledger_size


class _CountlessEntity(_FakeEntity):
    """QuickBooks answering a COUNT query without a totalCount."""

    def count(self, where_clause="", qb=None):
        self.count_calls.append(where_clause)
        return None


def _service(monkeypatch, attr, entity):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(QBOService, "_get_company", lambda self, cid: object())
    monkeypatch.setattr(QBOService, "_get_client", lambda self, company: object())
    monkeypatch.setattr("app.services.qbo_service." + attr, entity)
    return svc


LIST_METHODS = [
    ("Bill", "get_bills"),
    ("Purchase", "get_purchases"),
    ("Invoice", "get_invoices"),
    ("Payment", "get_payments"),
    # Vendor and Account carry a default `active_only=True` clause rather than
    # no clause. Everything asserted below holds either way — the point of
    # listing them here is that a filtered read pages exactly like an
    # unfiltered one, including that the COUNT is taken over the same filter.
    ("Vendor", "get_vendors"),
    ("Account", "get_accounts"),
    # The group from #12 and its follow-up comment (the issue body names
    # four; the comment expands it). No date range and no Active filter —
    # they page on offset alone, the plainest form of everything below.
    ("JournalEntry", "get_journal_entries"),
    ("BillPayment", "get_bill_payments"),
    ("Deposit", "get_deposits"),
    ("VendorCredit", "get_vendor_credits"),
    ("PurchaseOrder", "get_purchase_orders"),
    ("CreditMemo", "get_credit_memos"),
    ("SalesReceipt", "get_sales_receipts"),
    ("RefundReceipt", "get_refund_receipts"),
    ("Estimate", "get_estimates"),
    ("Transfer", "get_transfers"),
    ("TimeActivity", "get_time_activities"),
    # RecurringTransaction is NOT here, and must not be added. It is a wrapper
    # with no top-level Id, so it cannot be ordered by the key that makes an
    # offset stable. See test_recurring_transaction_has_no_id_to_order_by and
    # the docstring on QBOService.get_recurring_transactions.
]
LIST_IDS = [method for _, method in LIST_METHODS]

# The subset that takes a date range. Vendors and accounts are not
# transactions and carry no TxnDate, so a date-filtered assertion has nothing
# to say about them. Named rather than sliced off LIST_METHODS: a positional
# slice keeps returning four entries as that list grows, so an entity inserted
# ahead of the cut would quietly swap itself in for one of these and the
# date-clause assertion would stop covering a transaction endpoint without a
# single test going red.
TXN_LIST_METHODS = [
    ("Bill", "get_bills"),
    ("Purchase", "get_purchases"),
    ("Invoice", "get_invoices"),
    ("Payment", "get_payments"),
]
TXN_LIST_IDS = [method for _, method in TXN_LIST_METHODS]

# The subset whose default read is filtered rather than unfiltered.
ACTIVE_LIST_METHODS = [("Vendor", "get_vendors"), ("Account", "get_accounts")]
ACTIVE_LIST_IDS = [method for _, method in ACTIVE_LIST_METHODS]


# ---------------------------------------------------------------------------
# Service: paging past the first page
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_offset_reaches_quickbooks_as_a_one_based_startposition(
    monkeypatch, attr, method
):
    """Rows past the first page are reachable at all.

    Pre-fix there was no offset to pass: the service issued one query with no
    STARTPOSITION and the 1001st row was unreachable through the API.
    """
    entity = _FakeEntity(ledger_size=2500)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1, offset=1000))

    assert entity.queries[0]["start_position"] == 1001, entity.queries
    assert entity.queries[0]["max_results"] == PAGE
    assert [r["Id"] for r in page.rows[:2]] == ["1000", "1001"]
    assert page.offset == 1000


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_offset_zero_is_startposition_one(monkeypatch, attr, method):
    """The wire offset is 0-based; QuickBooks' STARTPOSITION is 1-based."""
    entity = _FakeEntity(ledger_size=10)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1))

    assert entity.queries[0]["start_position"] == 1
    assert [r["Id"] for r in page.rows] == [str(i) for i in range(10)]


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_a_result_set_larger_than_one_page_reports_has_more_and_the_total(
    monkeypatch, attr, method
):
    """The case the live ledger is in: 27,000 rows, 1000 returned.

    Pre-fix this returned a bare list of 1000 and there was nowhere to look
    for the other 26,000 or to learn they existed.
    """
    entity = _FakeEntity(ledger_size=27_187)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1))

    assert len(page.rows) == PAGE
    assert page.has_more is True
    assert page.total == 27_187
    assert page.next_offset == PAGE


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_a_full_page_that_is_the_whole_ledger_is_not_reported_as_truncated(
    monkeypatch, attr, method
):
    """Exactly one page, exactly. The boundary that a length check gets wrong.

    A consumer inferring truncation from `len(rows) == 1000` has to call this
    complete result truncated, because a full page is the same shape either
    way. Resolving it is what the COUNT query is for.
    """
    entity = _FakeEntity(ledger_size=PAGE)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1))

    assert len(page.rows) == PAGE
    assert page.total == PAGE
    assert page.has_more is False
    assert page.next_offset is None


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_one_row_past_the_page_size_is_reported_as_more(monkeypatch, attr, method):
    """The other side of the same boundary: 1001 rows, page of 1000."""
    entity = _FakeEntity(ledger_size=PAGE + 1)
    svc = _service(monkeypatch, attr, entity)

    first = asyncio.run(getattr(svc, method)(company_id=1))
    assert first.has_more is True
    assert first.total == PAGE + 1

    last = asyncio.run(getattr(svc, method)(company_id=1, offset=first.next_offset))
    assert [r["Id"] for r in last.rows] == [str(PAGE)]
    assert last.has_more is False
    assert last.total == PAGE + 1


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_the_final_short_page_costs_no_count_query(monkeypatch, attr, method):
    """A short page ends the result set, so its own length is the total.

    Spending a COUNT round trip to confirm what the row count already proves
    would double the QuickBooks calls of every ordinary request.
    """
    entity = _FakeEntity(ledger_size=42)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1))

    assert entity.count_calls == []
    assert page.total == 42
    assert page.has_more is False


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_an_offset_past_the_end_reports_the_real_total_not_the_offset(
    monkeypatch, attr, method
):
    """QuickBooks answers a STARTPOSITION past the end with no rows.

    Inferring the total from `offset + len(rows)` — right for every other
    short page — would publish the caller's chosen offset as the size of the
    ledger, which is the same class of confidently-wrong number this whole
    change exists to remove.
    """
    entity = _FakeEntity(ledger_size=27_187)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1, offset=30_000))

    assert page.rows == []
    assert page.total == 27_187
    assert page.has_more is False


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_an_overshot_offset_is_the_end_even_when_the_count_goes_unanswered(
    monkeypatch, attr, method
):
    """Size unknown and completeness unknown are different facts.

    This is where they come apart, and it is the one branch where has_more is
    False while total is None. The empty page is the evidence: QuickBooks
    answers a STARTPOSITION past the end with no rows, so no row exists at or
    past this offset whatever the COUNT did or did not say. Reporting
    has_more=True on the unanswered count would claim rows exist past a page
    just proven empty, and next_offset would come back as the same offset the
    caller already sent — a cursor a paging loop never gets off.
    """
    entity = _CountlessEntity(ledger_size=27_187)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1, offset=30_000))

    assert page.rows == []
    assert page.total is None
    assert page.has_more is False
    assert page.next_offset is None


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_an_empty_first_page_is_an_empty_result_set_not_an_overshoot(
    monkeypatch, attr, method
):
    """offset=0 with no rows means the query matches nothing — no COUNT
    needed to establish a total of zero."""
    entity = _FakeEntity(ledger_size=0)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1))

    assert page.rows == []
    assert page.total == 0
    assert page.has_more is False
    assert entity.count_calls == []


@pytest.mark.parametrize("attr,method", TXN_LIST_METHODS, ids=TXN_LIST_IDS)
def test_the_count_query_carries_the_same_where_clause_as_the_page(
    monkeypatch, attr, method
):
    """A total counted over the unfiltered ledger would describe a different
    question than the one the caller asked."""
    from datetime import datetime

    entity = _FakeEntity(ledger_size=5000)
    svc = _service(monkeypatch, attr, entity)

    asyncio.run(
        getattr(svc, method)(
            company_id=1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
    )

    clause = "TxnDate >= '2024-01-01' AND TxnDate <= '2024-12-31'"
    assert entity.queries[0]["where"] == clause
    assert entity.count_calls == [clause]


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_an_unanswerable_count_is_not_reported_as_complete(monkeypatch, attr, method):
    """QuickBooks not answering the count means the size is unknown.

    Unknown has to read as "there may be more". Defaulting it the other way
    would put the silent-truncation bug back, just behind a rarer branch.
    """
    entity = _CountlessEntity(ledger_size=PAGE)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1))

    assert page.total is None
    assert page.has_more is True


@pytest.mark.parametrize("attr,method", LIST_METHODS, ids=LIST_IDS)
def test_max_results_is_still_an_upper_bound_on_rows_returned(
    monkeypatch, attr, method
):
    """The gbrain spend adapter probes with max_results=1 to check the server
    honours it. Paging must not quietly return more than was asked for."""
    entity = _FakeEntity(ledger_size=5000)
    svc = _service(monkeypatch, attr, entity)

    page = asyncio.run(getattr(svc, method)(company_id=1, max_results=1))

    assert len(page.rows) == 1
    assert entity.queries[0]["max_results"] == 1
    assert page.has_more is True


# ---------------------------------------------------------------------------
# Service: the SQL that actually reaches QuickBooks
#
# STARTPOSITION indexes into an ordering, and the ordering QuickBooks picks
# when nothing asks for one is neither Id nor TxnDate: an unfiltered invoice
# query answers 94670, 93743, 94659, 94679, 94678. It is stable while nothing
# is writing, so an unordered walk looks right in a quiet moment and skews
# under concurrent writes — a row inserted ahead of the cursor pushes another
# across a page boundary, and the walk returns it twice or not at all.
#
# These pin the emitted SQL rather than the kwargs because the SDK is what
# chooses the spelling, and it is inconsistent about it: ListMixin.where()
# writes " ORDERBY ", ListMixin.all() writes " ORDER BY ". Two spellings would
# mean two dialects in production, split by whether the caller passed a date.
# ---------------------------------------------------------------------------


class _SqlRecorder(ListMixin):
    """Real SDK query building, with the SQL captured instead of sent."""

    qbo_object_name = "Bill"
    emitted: list[str] = []

    @classmethod
    def query(cls, select, qb=None):
        cls.emitted.append(select)
        return []

    @classmethod
    def count(cls, where_clause="", qb=None):
        return 0


def _emitted_sql(monkeypatch, **kwargs) -> str:
    _SqlRecorder.emitted = []
    svc = _service(monkeypatch, "Bill", _SqlRecorder)
    asyncio.run(svc.get_bills(company_id=1, **kwargs))
    assert len(_SqlRecorder.emitted) == 1
    return _SqlRecorder.emitted[0]


def test_the_filtered_page_query_orders_by_id(monkeypatch):
    from datetime import datetime

    sql = _emitted_sql(
        monkeypatch,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
    )

    assert sql == (
        "SELECT * FROM Bill "
        "WHERE TxnDate >= '2024-01-01' AND TxnDate <= '2024-12-31'"
        " ORDERBY Id STARTPOSITION 1 MAXRESULTS 1000"
    )


def test_the_unfiltered_page_query_orders_by_id(monkeypatch):
    sql = _emitted_sql(monkeypatch)

    assert sql == "SELECT * FROM Bill  ORDERBY Id STARTPOSITION 1 MAXRESULTS 1000"


def test_both_query_paths_send_one_orderby_spelling(monkeypatch):
    """The filtered and unfiltered paths must not be two query dialects."""
    from datetime import datetime

    filtered = _emitted_sql(monkeypatch, start_date=datetime(2024, 1, 1))
    unfiltered = _emitted_sql(monkeypatch)

    for sql in (filtered, unfiltered):
        assert " ORDERBY Id " in sql
        assert "ORDER BY" not in sql


def test_the_offset_reaches_the_sql_as_a_one_based_startposition(monkeypatch):
    sql = _emitted_sql(monkeypatch, offset=1000, max_results=500)

    assert sql.endswith(" ORDERBY Id STARTPOSITION 1001 MAXRESULTS 500")


# ---------------------------------------------------------------------------
# Service: walking every page for a server-side aggregate
# ---------------------------------------------------------------------------


def test_get_all_invoices_walks_past_the_page_ceiling(monkeypatch):
    """An aggregate computed over page one is a wrong number wearing a 200."""
    entity = _FakeEntity(ledger_size=2300)
    svc = _service(monkeypatch, "Invoice", entity)

    page = asyncio.run(svc.get_all_invoices(company_id=1))

    assert len(page.rows) == 2300
    assert [q["start_position"] for q in entity.queries] == [1, 1001, 2001]
    assert page.has_more is False
    assert page.total == 2300


def test_get_all_invoices_that_ends_on_a_page_boundary_stops_by_running_dry(
    monkeypatch,
):
    """A ledger that is an exact multiple of the page size needs one more
    query to discover it ended — and must not report the empty tail as rows."""
    entity = _FakeEntity(ledger_size=2 * PAGE)
    svc = _service(monkeypatch, "Invoice", entity)

    page = asyncio.run(svc.get_all_invoices(company_id=1))

    assert len(page.rows) == 2 * PAGE
    assert [q["start_position"] for q in entity.queries] == [1, 1001, 2001]
    assert page.has_more is False


def test_get_all_invoices_exhausting_its_page_budget_says_so(monkeypatch):
    """The walk is bounded, so it can end early — and when it does, the caller
    is told rather than handed a prefix presented as the whole window."""
    entity = _FakeEntity(ledger_size=100_000)
    svc = _service(monkeypatch, "Invoice", entity)

    page = asyncio.run(svc._fetch_all_pages(
        entity, client=object(), clause=None, op="get_all_invoices", max_pages=3
    ))

    assert len(page.rows) == 3 * PAGE
    assert page.has_more is True
    assert page.total == 100_000


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class _PageService:
    """Stand-in for QBOService that returns a fixed page and records kwargs."""

    def __init__(self, page: PagedResult):
        self.page = page
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name):
        async def _call(**kwargs):
            self.calls.append((name, kwargs))
            return self.page

        return _call


def _client(module, page):
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    service = _PageService(page)
    app.dependency_overrides[module._get_service] = lambda: service
    return TestClient(app), service


ENDPOINTS = [
    (bills, "/bills/"),
    (purchases, "/purchases/"),
    (payments, "/payments/"),
    (invoices, "/invoices/"),
    (vendors, "/vendors/"),
    (accounts, "/accounts/"),
    (journal_entries, "/journal-entries/"),
    (bill_payments, "/bill-payments/"),
    (deposits, "/deposits/"),
    (vendor_credits, "/vendor-credits/"),
    (purchase_orders, "/purchase-orders/"),
    (credit_memos, "/credit-memos/"),
    (sales_receipts, "/sales-receipts/"),
    (refund_receipts, "/refund-receipts/"),
    (estimates, "/estimates/"),
    (transfers, "/transfers/"),
    (time_activities, "/time-activities/"),
    # /recurring-transactions/ is NOT here — it is not paged. See
    # test_the_unpageable_endpoints_advertise_no_cursor.
]
ENDPOINT_IDS = [path.strip("/") for _, path in ENDPOINTS]


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_a_truncated_response_is_detectable_by_the_caller(module, path):
    """The whole point. A 200 that looks complete and is not is the bug.

    Pre-fix the response carried nothing but rows: no total, no cursor, no
    statement that more existed. A caller had exactly one signal available —
    "I got 1000, which is suspiciously round" — and that signal is wrong at
    both boundaries.
    """
    truncated = PagedResult(
        rows=[{"Id": str(i)} for i in range(PAGE)],
        offset=0,
        total=27_187,
        has_more=True,
    )
    client, _ = _client(module, truncated)

    res = client.get(path, params={"company_id": 1})

    assert res.status_code == 200
    assert res.headers["X-Has-More"] == "true"
    assert res.headers["X-Total-Count"] == "27187"
    assert res.headers["X-Result-Offset"] == "0"
    assert res.headers["X-Result-Count"] == str(PAGE)
    assert res.headers["X-Next-Offset"] == str(PAGE)


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_a_complete_response_says_so_rather_than_staying_quiet(module, path):
    """'Complete' and 'this server does not tell me' cannot be the same
    observation, so X-Has-More is present on the false case too."""
    complete = PagedResult(
        rows=[{"Id": str(i)} for i in range(12)], offset=0, total=12, has_more=False
    )
    client, _ = _client(module, complete)

    res = client.get(path, params={"company_id": 1})

    assert res.headers["X-Has-More"] == "false"
    assert res.headers["X-Total-Count"] == "12"
    assert "X-Next-Offset" not in res.headers


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_an_end_of_set_page_of_unknown_size_says_end_without_saying_size(module, path):
    """The overshoot branch on the wire: 'complete, size unknown'.

    An empty page past offset 0 with a COUNT QuickBooks did not answer. The
    empty page establishes there is nothing further, so X-Has-More is false
    and there is no cursor to hand back; the unanswered count means no
    X-Total-Count is published rather than a made-up one. Three headers that
    disagree would be worse than any of them being absent.
    """
    end_of_set = PagedResult(rows=[], offset=30_000, total=None, has_more=False)
    client, _ = _client(module, end_of_set)

    res = client.get(path, params={"company_id": 1, "offset": 30_000})

    assert res.json() == []
    assert res.headers["X-Has-More"] == "false"
    assert res.headers["X-Result-Offset"] == "30000"
    assert res.headers["X-Result-Count"] == "0"
    assert "X-Total-Count" not in res.headers
    assert "X-Next-Offset" not in res.headers


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_offset_is_declared_and_reaches_the_service(module, path):
    """FastAPI drops undeclared query params in silence — the same mechanism
    that swallowed start_date/end_date. An offset that is not in the schema is
    an offset the server ignores while answering 200."""
    client, service = _client(module, PagedResult())

    res = client.get(path, params={"company_id": 1, "offset": 2000})

    assert res.status_code == 200, res.text
    assert service.calls[-1][1]["offset"] == 2000

    schema = client.app.openapi()
    names = {p["name"] for p in schema["paths"][path]["get"]["parameters"]}
    assert "offset" in names


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_the_paging_headers_are_in_the_published_schema(module, path):
    """A header a caller cannot discover is a header a caller will not read."""
    client, _ = _client(module, PagedResult())

    headers = client.app.openapi()["paths"][path]["get"]["responses"]["200"]["headers"]

    assert {"X-Has-More", "X-Total-Count", "X-Next-Offset"} <= set(headers)


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_the_body_is_still_a_bare_array(module, path):
    """The gbrain spend adapter refuses a non-array body outright rather than
    risk reading a truncated page as a whole one, so the paging facts ride on
    headers. Wrapping the rows in an envelope would break every consumer."""
    page = PagedResult(rows=[{"Id": "1"}, {"Id": "2"}], offset=0, total=2)
    client, _ = _client(module, page)

    body = client.get(path, params={"company_id": 1}).json()

    assert isinstance(body, list)
    assert body == [{"Id": "1"}, {"Id": "2"}]


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_a_negative_offset_is_a_422_not_a_silent_first_page(module, path):
    client, service = _client(module, PagedResult())

    res = client.get(path, params={"company_id": 1, "offset": -1})

    assert res.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize("module,path", ENDPOINTS, ids=ENDPOINT_IDS)
def test_max_results_past_the_quickbooks_ceiling_is_a_422(module, path):
    """QuickBooks will not return more than 1000 for one query. Accepting a
    larger number would promise rows the upstream cannot deliver."""
    client, service = _client(module, PagedResult())

    res = client.get(path, params={"company_id": 1, "max_results": PAGE + 1})

    assert res.status_code == 422
    assert service.calls == []


def test_the_trailing_12m_summary_states_whether_it_saw_the_whole_window():
    """It aggregates money. Pre-fix it summed one 1000-row page and published
    the result as `grand_total` — against a ledger whose trailing 12 months
    exceeds 1000 invoices, a wrong dollar figure with nothing marking it."""
    rows = [
        {"TxnDate": "2026-01-15", "TotalAmt": 100.0},
        {"TxnDate": "2026-02-15", "TotalAmt": 250.0},
    ]
    client, service = _client(
        invoices, PagedResult(rows=rows, offset=0, total=2, has_more=False)
    )

    body = client.get(
        "/invoices/trailing-12m/summary", params={"company_id": 1}
    ).json()

    assert service.calls[-1][0] == "get_all_invoices"
    assert body["grand_total"] == 350.0
    assert body["complete"] is True
    assert body["invoices_in_window"] == 2


def test_the_trailing_12m_summary_marks_an_aggregate_it_could_not_finish():
    client, _ = _client(
        invoices,
        PagedResult(
            rows=[{"TxnDate": "2026-01-15", "TotalAmt": 100.0}],
            offset=0,
            total=50_000,
            has_more=True,
        ),
    )

    body = client.get(
        "/invoices/trailing-12m/summary", params={"company_id": 1}
    ).json()

    assert body["complete"] is False
    assert body["invoices_in_window"] == 50_000


def test_an_aggregation_failure_in_the_summary_is_not_reported_as_a_404():
    """404 means "no such company" here — the service raises ValueError for an
    unknown company and the handler answers 404.

    `float(inv["TotalAmt"])` raises ValueError too. With the aggregation
    inside the same try, an amount QuickBooks returned in a shape float()
    will not take came back as 404, and anything routing on the status code
    read a live company as missing. The walk now covers up to 20,000 invoices
    where it used to stop at 1,000, so there are twenty times as many values
    that can do it.
    """
    app = FastAPI()
    app.include_router(invoices.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[invoices._get_service] = lambda: _PageService(
        PagedResult(
            rows=[{"TxnDate": "2026-01-15", "TotalAmt": "1,234.56"}],
            offset=0,
            total=1,
            has_more=False,
        )
    )
    client = TestClient(app, raise_server_exceptions=False)

    res = client.get("/invoices/trailing-12m/summary", params={"company_id": 1})

    assert res.status_code == 500


def test_an_unknown_company_in_the_summary_is_still_a_404():
    """The catch narrowed to the fetch still has to catch the fetch."""

    class _Missing:
        async def get_all_invoices(self, **kwargs):
            raise ValueError("QBO company not found: 99")

    app = FastAPI()
    app.include_router(invoices.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[invoices._get_service] = lambda: _Missing()
    client = TestClient(app)

    res = client.get("/invoices/trailing-12m/summary", params={"company_id": 99})

    assert res.status_code == 404
    assert res.json()["detail"] == "QBO company not found: 99"


# ---------------------------------------------------------------------------
# Header helper
# ---------------------------------------------------------------------------


def test_an_unknown_total_omits_the_count_header_but_still_flags_more():
    from fastapi import Response

    response = Response()
    apply_paging_headers(
        response, PagedResult(rows=[{}] * PAGE, offset=0, total=None, has_more=True)
    )

    assert "X-Total-Count" not in response.headers
    assert response.headers["X-Has-More"] == "true"
    assert response.headers["X-Next-Offset"] == str(PAGE)


# ---------------------------------------------------------------------------
# active_only: the filter that used to be `Entity.filter(Active=True)`
#
# Vendors and accounts are the two endpoints that reached QuickBooks through
# `filter()` rather than `where()`. Paging them meant moving the filter into a
# clause, and a clause that silently went missing would page correctly over
# the wrong result set — every inactive vendor included, with a plausible
# total and a plausible page.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr,method", ACTIVE_LIST_METHODS, ids=ACTIVE_LIST_IDS
)
def test_active_only_reaches_quickbooks_as_a_where_clause(monkeypatch, attr, method):
    entity = _FakeEntity(ledger_size=12)
    svc = _service(monkeypatch, attr, entity)

    asyncio.run(getattr(svc, method)(company_id=1, active_only=True))

    assert entity.queries[0]["where"] == "Active = true"


@pytest.mark.parametrize(
    "attr,method", ACTIVE_LIST_METHODS, ids=ACTIVE_LIST_IDS
)
def test_active_only_false_asks_for_everything(monkeypatch, attr, method):
    entity = _FakeEntity(ledger_size=12)
    svc = _service(monkeypatch, attr, entity)

    asyncio.run(getattr(svc, method)(company_id=1, active_only=False))

    assert entity.queries[0]["where"] == ""


@pytest.mark.parametrize(
    "attr,method", ACTIVE_LIST_METHODS, ids=ACTIVE_LIST_IDS
)
def test_the_total_counts_only_the_filtered_set(monkeypatch, attr, method):
    """A COUNT over every vendor would report a total the pages never reach,
    leaving X-Has-More true forever and a caller paging into nothing."""
    entity = _FakeEntity(ledger_size=27_187)
    svc = _service(monkeypatch, attr, entity)

    asyncio.run(getattr(svc, method)(company_id=1, active_only=True))

    assert entity.count_calls == ["Active = true"]


class _CountFaultingEntity(_FakeEntity):
    """QuickBooks serves the page, then faults on the COUNT round trip."""

    def count(self, where_clause="", qb=None):
        self.count_calls.append(where_clause)
        raise RuntimeError("QBO fault on COUNT")


def test_a_failed_count_still_serves_the_page_it_already_has(monkeypatch, caplog):
    """A COUNT fault leaves the size unknown, not the page invalid.

    Before this, a full page QBO had already returned was discarded because
    the follow-up COUNT raised, and the router's catch-all turned it into a
    500. `total=None` is the state that means "size unknown" — the same one a
    COUNT answered without a totalCount produces — so has_more stays True and
    the caller is told the set may continue.
    """
    entity = _CountFaultingEntity(ledger_size=27_187)
    svc = _service(monkeypatch, "Bill", entity)

    with caplog.at_level(logging.ERROR, logger="app.services.qbo_service"):
        page = asyncio.run(svc.get_bills(company_id=1))

    assert len(page.rows) == PAGE, "the page QBO served must survive a COUNT fault"
    assert page.total is None
    assert page.has_more is True, "unknown size must read as possibly-more, not complete"
    assert page.next_offset == PAGE

    # Degrading quietly would look identical to QBO declining to count.
    # ERROR, not WARNING: this branch is only reached once the retries are
    # exhausted, which is the terminal case this module logs at ERROR.
    assert [r for r in caplog.records if r.levelno == logging.ERROR], (
        "a COUNT that faults every time must leave a server-side trace"
    )


def test_a_failed_count_does_not_discard_a_completed_walk(monkeypatch, caplog):
    """The same guarantee at the other _count_matching call site.

    `_fetch_all_pages` reaches its COUNT only after exhausting the page
    budget, so a fault there throws away up to twenty pages QuickBooks already
    served — the outcome is the same as the single-page case but the cost is
    twenty times larger. The guard lives in `_count_matching` rather than at
    either call site so there is one implementation of it.
    """
    # The budget has to be exhausted to reach the COUNT at all — a walk that
    # ends on a short page returns from there and never counts. An earlier
    # draft of this test used a ledger the walk could finish, so it proved
    # nothing about the COUNT path.
    entity = _CountFaultingEntity(ledger_size=2500)
    svc = _service(monkeypatch, "Invoice", entity)

    with caplog.at_level(logging.ERROR, logger="app.services.qbo_service"):
        page = asyncio.run(
            svc._fetch_all_pages(
                entity, client=object(), clause=None, op="walk", max_pages=2
            )
        )

    assert len(page.rows) == 2 * PAGE, "the walk's rows must survive a COUNT fault"
    assert page.total is None
    assert page.has_more is True
    assert [r for r in caplog.records if r.levelno == logging.ERROR]


def test_recurring_transaction_has_no_id_to_order_by():
    """Why /api/recurring-transactions/ stays on the unpaged path.

    RecurringTransaction is a wrapper, not a row — it holds a class_dict of
    twelve wrapped types, and live rows arrive shaped `{"JournalEntry": {...}}`.
    `_query_page` orders by `Id`, which is the whole reason an offset means the
    same thing on two requests, so paging this entity gets either a fault (a
    working 200 becomes a catch-all 500) or a silently ignored ORDERBY, where
    `offset` no-ops while the headers promise a cursor and the caller
    reassembles duplicates.

    Checked on an INSTANCE, not the class. python-quickbooks assigns `Id` in
    `__init__`, so `hasattr(SomeEntity, "Id")` is False for every entity in the
    SDK including the pageable ones — an assertion against the class passes
    always and pins nothing. BillPayment is asserted alongside it precisely so
    this test fails if that ever stops discriminating.
    """
    from quickbooks.objects.billpayment import BillPayment
    from quickbooks.objects.recurringtransaction import RecurringTransaction

    assert hasattr(BillPayment(), "Id"), (
        "control case broke: a pageable entity must expose Id, or the "
        "assertion below proves nothing"
    )
    assert not hasattr(RecurringTransaction(), "Id"), (
        "RecurringTransaction grew an Id — re-check whether it can now be paged"
    )


def _router_schema(module):
    """Generated OpenAPI for one router, independent of app.main.

    Not `app.main.app` — it mounts StaticFiles from a relative path, so
    importing it only works with the working directory set to fortium-qbo,
    and the suite is run from the repo root. The router objects are the thing
    under test anyway: the offset parameter is declared on the handler.
    """
    app = FastAPI()
    app.include_router(module.router)
    return app.openapi()


def test_the_unpageable_endpoints_advertise_no_cursor():
    """Asserted against generated OpenAPI, not this module's own constants.

    The first version of this test read LIST_IDS and ENDPOINTS — the test file
    checking itself, so paging the recurring router without editing those
    lists would have left the suite green. Reading what the router actually
    publishes is the only version that can catch what it is for.
    """
    from app.routers import recurring

    rec = _router_schema(recurring)["paths"]["/recurring-transactions/"]["get"]
    assert "offset" not in {q["name"] for q in rec.get("parameters", [])}, (
        "recurring-transactions must not advertise a cursor it cannot honour"
    )

    bb = _router_schema(bill_payments)["paths"]["/bill-payments/by-bill/{bill_id}"]["get"]
    assert "offset" not in {q["name"] for q in bb.get("parameters", [])}, (
        "by-bill resolves through LinkedTxn and must not gain a cursor"
    )

    # The positive direction, so this also fails if paging is lost wholesale
    # rather than only if it spreads somewhere it should not.
    paged = _router_schema(journal_entries)["paths"]["/journal-entries/"]["get"]
    assert "offset" in {q["name"] for q in paged.get("parameters", [])}
    assert "X-Has-More" in paged["responses"]["200"]["headers"]


def test_the_unpaged_endpoint_still_refuses_a_zero_page():
    """max_results=0 is falsy in ListMixin.all, which drops the MAXRESULTS
    clause entirely and lets QuickBooks answer with its own default — fewer
    rows than asked for, inside a 200, with no X-Has-More to contradict it.
    The paged endpoints got ge=1 from the conversion; this one needed it
    stated separately because it is the one that keeps no header."""
    from app.routers import recurring

    rec = _router_schema(recurring)["paths"]["/recurring-transactions/"]["get"]
    mr = next(q for q in rec["parameters"] if q["name"] == "max_results")
    assert mr["schema"]["minimum"] == 1


@pytest.mark.parametrize(
    "attr,method", ACTIVE_LIST_METHODS, ids=ACTIVE_LIST_IDS
)
def test_the_unfiltered_total_counts_the_whole_file(monkeypatch, attr, method):
    """The mirror of the test above, and it needs a full page to reach.

    `_fetch_page` skips the COUNT entirely on a short page, so a small fake
    ledger proves nothing about what the COUNT was given — the assertion would
    pass against an empty count_calls list either way.
    """
    entity = _FakeEntity(ledger_size=27_187)
    svc = _service(monkeypatch, attr, entity)

    asyncio.run(getattr(svc, method)(company_id=1, active_only=False))

    assert entity.count_calls == [""]
