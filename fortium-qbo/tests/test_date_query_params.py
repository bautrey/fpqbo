"""Tests for date query parameters on the read endpoints.

Two bugs, one symptom — a caller passes a date window, gets a 200, and gets
back rows outside the window with nothing saying the filter was discarded.

  Variant A (bills, purchases): the router never declared ``start_date`` /
  ``end_date`` at all. FastAPI drops undeclared query params, so the service
  was called without a window and returned the unfiltered set.

  Variant B (payments, invoices, trial-balance, profit-and-loss): the params
  were declared as ``datetime``, which will not accept a bare ``2024-01-01``.
  The handler received None and the ``if start_date and end_date`` guard in
  the service never fired.

These tests drive the real routers through FastAPI's query coercion with a
recording stub in place of QBOService, so what is asserted is exactly what
the handler passed downstream. Asserting on the response body would prove
nothing here: the pre-fix response was a perfectly valid 200.
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.dependencies.api_auth import verify_api_key
from app.routers import bills, invoices, payments, purchases, reports
from app.services.qbo_service import QBOService, _txn_date_clause
from app.utils.paging import PagedResult
from app.utils.query_dates import parse_date_param

# The shape Date.prototype.toISOString() emits — what the nightly gbrain
# invoice/spend sync has always sent. Accepting it is a hard requirement.
ISO_TIMESTAMP_START = "2024-01-01T00:00:00.000Z"
ISO_TIMESTAMP_END = "2024-03-31T00:00:00.000Z"

BARE_START = "2024-01-01"
BARE_END = "2024-03-31"


# ---------------------------------------------------------------------------
# parse_date_param — the shared parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_date",
    [
        (BARE_START, (2024, 1, 1)),
        (ISO_TIMESTAMP_START, (2024, 1, 1)),
        ("2024-01-01T00:00:00Z", (2024, 1, 1)),
        ("2024-01-01T00:00:00+00:00", (2024, 1, 1)),
        ("2024-01-01T13:45:12", (2024, 1, 1)),
        ("  2024-01-01  ", (2024, 1, 1)),
    ],
)
def test_parse_accepts_bare_dates_and_iso_timestamps(raw, expected_date):
    parsed = parse_date_param(raw, field="start_date")
    assert (parsed.year, parsed.month, parsed.day) == expected_date


def test_parse_returns_none_only_for_an_omitted_param():
    assert parse_date_param(None, field="start_date") is None


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-date",
        "",
        "   ",
        "01/31/2024",
        "2024-13-01",  # month out of range
        "2024-02-30",  # day out of range for February
        "2024",  # too coarse to be a date
    ],
)
def test_parse_rejects_unparseable_values_with_422(raw):
    with pytest.raises(RequestValidationError) as exc:
        parse_date_param(raw, field="end_date")
    (error,) = exc.value.errors()
    # The error has to name the offending param — a caller sending two dates
    # needs to know which one is wrong.
    assert tuple(error["loc"]) == ("query", "end_date")
    assert error["input"] == raw


# ---------------------------------------------------------------------------
# Endpoint harness
# ---------------------------------------------------------------------------


class _RecordingService:
    """Stand-in for QBOService that records the kwargs it was handed."""

    def __init__(self, result):
        self.calls = []
        self._result = result

    def __getattr__(self, name):
        async def _call(**kwargs):
            self.calls.append((name, kwargs))
            return self._result

        return _call

    @property
    def last_kwargs(self):
        assert self.calls, "service was never called"
        return self.calls[-1][1]


def _client(module, result):
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    service = _RecordingService(result)
    app.dependency_overrides[module._get_service] = lambda: service
    return TestClient(app), service


class Case(SimpleNamespace):
    pass


# start_date/end_date endpoints. `passes_strings` marks the one endpoint whose
# service takes pre-formatted strings rather than datetimes (general-ledger
# hands its dates to QBO's report API as-is). The four transaction endpoints
# take a page from their service rather than a bare list — see
# tests/test_result_paging.py.
RANGE_CASES = [
    Case(id="bills", module=bills, path="/bills/", method="get_bills",
         result=PagedResult(), required=False, passes_strings=False),
    Case(id="purchases", module=purchases, path="/purchases/", method="get_purchases",
         result=PagedResult(), required=False, passes_strings=False),
    Case(id="payments", module=payments, path="/payments/", method="get_payments",
         result=PagedResult(), required=False, passes_strings=False),
    Case(id="invoices", module=invoices, path="/invoices/", method="get_invoices",
         result=PagedResult(), required=False, passes_strings=False),
    Case(id="trial-balance", module=reports, path="/reports/trial-balance",
         method="get_trial_balance", result={}, required=False, passes_strings=False),
    Case(id="profit-and-loss", module=reports, path="/reports/profit-and-loss",
         method="get_profit_and_loss", result={}, required=True, passes_strings=False),
    Case(id="general-ledger", module=reports, path="/reports/general-ledger",
         method="get_general_ledger", result={}, required=False, passes_strings=True),
]

RANGE_IDS = [c.id for c in RANGE_CASES]
OPTIONAL_CASES = [c for c in RANGE_CASES if not c.required]
OPTIONAL_IDS = [c.id for c in OPTIONAL_CASES]


def _assert_window(case, kwargs, start=(2024, 1, 1), end=(2024, 3, 31)):
    got_start, got_end = kwargs["start_date"], kwargs["end_date"]
    if case.passes_strings:
        assert got_start == "%04d-%02d-%02d" % start
        assert got_end == "%04d-%02d-%02d" % end
        return
    assert isinstance(got_start, datetime)
    assert isinstance(got_end, datetime)
    assert (got_start.year, got_start.month, got_start.day) == start
    assert (got_end.year, got_end.month, got_end.day) == end


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", RANGE_CASES, ids=RANGE_IDS)
def test_bare_date_reaches_the_service(case):
    """A bare YYYY-MM-DD window must survive the trip to the service.

    Pre-fix this failed two different ways: bills/purchases never declared the
    params (KeyError — the kwargs simply are not there), and the datetime-typed
    endpoints passed None.
    """
    client, service = _client(case.module, case.result)
    res = client.get(
        case.path,
        params={"company_id": 1, "start_date": BARE_START, "end_date": BARE_END},
    )
    assert res.status_code == 200, res.text
    assert service.calls[-1][0] == case.method
    _assert_window(case, service.last_kwargs)


@pytest.mark.parametrize("case", RANGE_CASES, ids=RANGE_IDS)
def test_full_iso_timestamp_still_reaches_the_service(case):
    """The gbrain sync sends toISOString() values; that must keep working."""
    client, service = _client(case.module, case.result)
    res = client.get(
        case.path,
        params={
            "company_id": 1,
            "start_date": ISO_TIMESTAMP_START,
            "end_date": ISO_TIMESTAMP_END,
        },
    )
    assert res.status_code == 200, res.text
    _assert_window(case, service.last_kwargs)


@pytest.mark.parametrize("case", RANGE_CASES, ids=RANGE_IDS)
def test_unparseable_date_is_422_and_the_service_is_never_reached(case):
    """A bad date must fail loudly rather than return an unfiltered 200.

    The 422 also has to survive the handler's bare ``except Exception``, which
    rewrites whatever it catches into a 500 "QBO API error". Parsing therefore
    happens outside the try block.
    """
    client, service = _client(case.module, case.result)
    res = client.get(
        case.path,
        params={"company_id": 1, "start_date": "garbage", "end_date": BARE_END},
    )
    assert res.status_code == 422, f"got {res.status_code}: {res.text}"
    assert service.calls == [], "service ran despite an invalid date"
    # Same body shape a rejected `datetime` query param produced before this
    # change, so callers that read `detail[0].loc` keep working.
    (error,) = res.json()["detail"]
    assert error["loc"] == ["query", "start_date"]
    assert error["input"] == "garbage"


@pytest.mark.parametrize("case", OPTIONAL_CASES, ids=OPTIONAL_IDS)
def test_omitted_dates_pass_none_through(case):
    """Omitting the window is still allowed and still means unfiltered."""
    client, service = _client(case.module, case.result)
    res = client.get(case.path, params={"company_id": 1})
    assert res.status_code == 200, res.text
    assert service.last_kwargs["start_date"] is None
    assert service.last_kwargs["end_date"] is None


@pytest.mark.parametrize("case", OPTIONAL_CASES, ids=OPTIONAL_IDS)
def test_one_sided_window_is_honoured_not_dropped(case):
    """Half a window is still a window.

    Sending only start_date used to be another silent-drop path: the service's
    ``if start_date and end_date`` guard skipped filtering entirely.
    """
    client, service = _client(case.module, case.result)
    res = client.get(
        case.path, params={"company_id": 1, "start_date": BARE_START}
    )
    assert res.status_code == 200, res.text
    kwargs = service.last_kwargs
    assert kwargs["start_date"] is not None
    assert kwargs["end_date"] is None


@pytest.mark.parametrize("case", RANGE_CASES, ids=RANGE_IDS)
def test_compact_date_is_not_read_as_a_unix_timestamp(case):
    """20240101 is January 1st 2024, not 1970-08-23.

    The datetime-typed params handed this to pydantic, which saw digits and
    read them as seconds since the epoch — a 200 carrying a window fifty-four
    years off what the caller asked for.
    """
    client, service = _client(case.module, case.result)
    res = client.get(
        case.path,
        params={"company_id": 1, "start_date": "20240101", "end_date": "20240331"},
    )
    assert res.status_code == 200, res.text
    _assert_window(case, service.last_kwargs)


@pytest.mark.parametrize("case", RANGE_CASES, ids=RANGE_IDS)
def test_epoch_seconds_are_rejected(case):
    """The other half of the compact-date fix, stated deliberately.

    A bare integer cannot be both 2024-01-01 and 1700000000 seconds. These
    params are dates; an epoch is a 422.
    """
    client, service = _client(case.module, case.result)
    res = client.get(
        case.path,
        params={"company_id": 1, "start_date": "1700000000", "end_date": BARE_END},
    )
    assert res.status_code == 422, f"got {res.status_code}: {res.text}"
    assert service.calls == []


@pytest.mark.parametrize("case", RANGE_CASES, ids=RANGE_IDS)
def test_date_params_are_declared_in_the_schema(case):
    """Undeclared params are dropped in silence — they must be in the schema."""
    client, _ = _client(case.module, case.result)
    schema = client.app.openapi()
    params = schema["paths"][case.path]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert {"start_date", "end_date"} <= names


def test_profit_and_loss_dates_stay_required():
    client, service = _client(reports, {})
    res = client.get("/reports/profit-and-loss", params={"company_id": 1})
    assert res.status_code == 422
    assert service.calls == []

    res = client.get(
        "/reports/profit-and-loss",
        params={"company_id": 1, "start_date": BARE_START},
    )
    assert res.status_code == 422
    assert service.calls == []


# ---------------------------------------------------------------------------
# balance-sheet: single as_of_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [BARE_START, ISO_TIMESTAMP_START])
def test_balance_sheet_accepts_bare_and_iso_dates(raw):
    """The bare-date path already worked here; the ISO path did not.

    as_of_date was parsed with strptime("%Y-%m-%d"), so a toISOString() value
    raised ValueError.
    """
    client, service = _client(reports, {})
    res = client.get(
        "/reports/balance-sheet", params={"company_id": 1, "as_of_date": raw}
    )
    assert res.status_code == 200, res.text
    parsed = service.last_kwargs["as_of_date"]
    assert (parsed.year, parsed.month, parsed.day) == (2024, 1, 1)


def test_balance_sheet_bad_date_is_422_not_404():
    """This parse used to sit inside the try block.

    strptime raised ValueError, the ``except ValueError`` arm caught it, and a
    malformed date came back as a 404 — indistinguishable from an unknown
    company.
    """
    client, service = _client(reports, {})
    res = client.get(
        "/reports/balance-sheet", params={"company_id": 1, "as_of_date": "garbage"}
    )
    assert res.status_code == 422, f"got {res.status_code}: {res.text}"
    assert service.calls == []
    (error,) = res.json()["detail"]
    assert error["loc"] == ["query", "as_of_date"]


# ---------------------------------------------------------------------------
# Service layer — bills and purchases had no date filter to call at all
# ---------------------------------------------------------------------------


def test_txn_date_clause_both_bounds_is_unchanged_from_the_old_inline_string():
    """Byte-for-byte the clause invoices/payments have always sent to QBO.

    The nightly sync depends on this query; the shared builder must not have
    altered it while picking up the one-sided cases.
    """
    clause = _txn_date_clause(datetime(2024, 1, 1), datetime(2024, 3, 31))
    assert clause == "TxnDate >= '2024-01-01' AND TxnDate <= '2024-03-31'"


def test_txn_date_clause_one_sided_and_unbounded():
    assert _txn_date_clause(datetime(2024, 1, 1), None) == "TxnDate >= '2024-01-01'"
    assert _txn_date_clause(None, datetime(2024, 3, 31)) == "TxnDate <= '2024-03-31'"
    assert _txn_date_clause(None, None) is None


def test_txn_date_clause_uses_only_the_date_part_of_a_timestamp():
    clause = _txn_date_clause(
        datetime(2024, 1, 1, 23, 59, 59), datetime(2024, 3, 31, 12, 0, 0)
    )
    assert clause == "TxnDate >= '2024-01-01' AND TxnDate <= '2024-03-31'"


class _EntityRecorder:
    """Fake quickbooks entity class capturing where()/all()."""

    def __init__(self):
        self.where_clause = None
        self.all_called = False

    def where(self, clause, **kwargs):
        self.where_clause = clause
        return []

    def all(self, **kwargs):
        self.all_called = True
        return []


def _service_with_entity(monkeypatch, attr, recorder):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(QBOService, "_get_company", lambda self, cid: object())
    monkeypatch.setattr(QBOService, "_get_client", lambda self, company: object())
    monkeypatch.setattr("app.services.qbo_service." + attr, recorder)
    return svc


@pytest.mark.parametrize(
    "attr,method",
    [
        ("Bill", "get_bills"),
        ("Purchase", "get_purchases"),
        ("Invoice", "get_invoices"),
        ("Payment", "get_payments"),
    ],
)
def test_service_applies_the_date_window_to_the_qbo_query(monkeypatch, attr, method):
    """Bills and purchases had no start_date/end_date parameter before this."""
    recorder = _EntityRecorder()
    svc = _service_with_entity(monkeypatch, attr, recorder)

    asyncio.run(
        getattr(svc, method)(
            company_id=1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 31),
        )
    )

    assert recorder.where_clause == "TxnDate >= '2024-01-01' AND TxnDate <= '2024-03-31'"
    assert not recorder.all_called


@pytest.mark.parametrize(
    "attr,method",
    [
        ("Bill", "get_bills"),
        ("Purchase", "get_purchases"),
        ("Invoice", "get_invoices"),
        ("Payment", "get_payments"),
    ],
)
def test_service_fetches_everything_when_no_window_is_given(monkeypatch, attr, method):
    """No window means no TxnDate predicate — an empty clause, not a filter.

    The query still goes through where(): every paged read does, so that one
    ORDERBY spelling reaches QuickBooks instead of the two the SDK's where()
    and all() emit.
    """
    recorder = _EntityRecorder()
    svc = _service_with_entity(monkeypatch, attr, recorder)

    asyncio.run(getattr(svc, method)(company_id=1))

    assert recorder.all_called is False
    assert recorder.where_clause == ""
