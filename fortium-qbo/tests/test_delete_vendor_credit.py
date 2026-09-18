"""DELETE /api/vendor-credits/{entity_id}.

Why this exists (#35): bills had a delete and vendor credits did not, so a
credit could be created and read and never removed. A correction wrote three
credits into QuickBooks on the assumption they would sync into Bill.com, they
will not, and undoing that had no sanctioned route — the service exists so
QuickBooks access does not happen by hand, and a missing delete pushes it back
into the UI.

The three things these tests pin, in the order the caller cares about:

1. QuickBooks' refusal text survives. A credit in a closed period and a credit
   with a linked transaction both refuse, they are ordinary states rather than
   faults, and the caller has to tell them apart from the response alone.
2. A delete is never retried. It is not idempotent.
3. A missing credit is 404, not 500 — and the mapping covers only the fetch.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quickbooks.exceptions import ObjectNotFoundException, QuickbooksException

from app.dependencies.api_auth import verify_api_key
from app.exceptions import QboNotFound, QboUnavailable
from app.routers import vendor_credits
from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCredit:
    """Stands in for a python-quickbooks VendorCredit row.

    Records the client it was deleted with. An earlier version discarded `qb`,
    which meant the suite could not tell a delete against the caller's company
    from a delete against any other — the one property that matters most on a
    destructive endpoint.
    """

    def __init__(self, entity_id="96159", response=None, raises=None):
        self.Id = entity_id
        self.SyncToken = "0"
        self.DocNumber = "11712-85-Har-CR"
        self.TotalAmt = 312.55
        self._response = response
        self._raises = raises
        self.delete_calls = 0
        self.deleted_with_client = None

    def delete(self, qb=None):
        self.delete_calls += 1
        self.deleted_with_client = qb
        if self._raises is not None:
            raise self._raises
        return self._response

    def to_dict(self):
        return {"Id": self.Id, "DocNumber": self.DocNumber, "TotalAmt": self.TotalAmt}


class _Probe:
    """Captures which id was fetched and which company was resolved."""

    def __init__(self):
        self.fetched_ids = []
        self.companies = []
        self.client = object()


def _service(monkeypatch, credit=None, get_raises=None, probe=None):
    """A QBOService whose VendorCredit.get returns `credit` or raises.

    `probe` records the arguments the service actually used. Without it the
    fakes are id-blind and company-blind: hardcoding `VendorCredit.get(1)` or
    `_get_company(999)` in the service passed the whole suite.
    """
    probe = probe or _Probe()
    svc = QBOService.__new__(QBOService)

    def _get_company(cid):
        probe.companies.append(cid)
        return SimpleNamespace(id=cid)

    monkeypatch.setattr(svc, "_get_company", _get_company, raising=False)
    monkeypatch.setattr(svc, "_get_client", lambda company: probe.client, raising=False)

    async def _no_retry(fn, op=None):
        return fn()

    monkeypatch.setattr(svc, "_to_thread_with_retry", _no_retry, raising=False)

    class _FakeVendorCredit:
        @staticmethod
        def get(entity_id, qb=None):
            probe.fetched_ids.append(entity_id)
            if get_raises is not None:
                raise get_raises
            return credit

    monkeypatch.setattr(qbo_service_module, "VendorCredit", _FakeVendorCredit)
    svc._probe = probe
    return svc


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. QuickBooks' refusal text survives — the thing #35 asked for first
# ---------------------------------------------------------------------------


# QuickbooksException, NOT ValidationException. The SDK maps 2000-4999 to
# ValidationException; 6240 falls past that range to the bare class, which
# renders "QB Exception 6240:" rather than "QB Validation Exception 6240:".
# An earlier version of this fixture built a ValidationException by hand, so it
# agreed with a docstring that was also wrong and neither caught the other.
CLOSED_PERIOD = QuickbooksException(
    "The transaction date is prior to the closing date.",
    error_code=6240,
    detail="Transaction cannot be changed because it is in a closed period.",
)

# What the SDK raises when the response body will not parse — a gateway 502
# AFTER QuickBooks has already committed the delete looks exactly like this.
# _is_transient_qbo_error classifies >= 10000 as TRANSIENT, which is why this
# is the only exception that can tell asyncio.to_thread from
# _to_thread_with_retry on the delete call.
UNPARSEABLE_RESPONSE = QuickbooksException(
    "Error reading json response: <html>502 Bad Gateway</html>",
    error_code=10000,
    detail="",
)


def test_a_refusal_reaches_the_caller_with_quickbooks_own_words(monkeypatch):
    """A closed-period credit is an ordinary state, and the reason is the answer.

    The caller is reconciling against QuickBooks at the end of a correction.
    "500 QBO API error" with the body dropped tells it nothing it can act on;
    the error code and message tell it whether to reopen a period or unlink a
    transaction.
    """
    credit = _FakeCredit(raises=CLOSED_PERIOD)
    svc = _service(monkeypatch, credit=credit)

    with pytest.raises(QuickbooksException) as exc:
        _run(svc.delete_vendor_credit(1, 96159))

    rendered = str(exc.value)
    assert "QB Exception 6240" in rendered
    assert "closed period" in rendered.lower()


def test_the_router_renders_that_refusal_into_the_response_body(monkeypatch):
    """End to end: the words have to survive the router, not just the service."""

    async def _refuse(company_id, entity_id):
        raise CLOSED_PERIOD

    app = FastAPI()
    app.include_router(vendor_credits.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[vendor_credits._get_service] = lambda: SimpleNamespace(
        delete_vendor_credit=_refuse
    )
    client = TestClient(app, raise_server_exceptions=False)

    r = client.delete("/vendor-credits/96159", params={"company_id": 1})

    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "6240" in detail
    assert "closed period" in detail.lower()


# ---------------------------------------------------------------------------
# 2. A delete is not idempotent and must never be retried
# ---------------------------------------------------------------------------


def test_the_delete_is_issued_exactly_once(monkeypatch):
    """_to_thread_with_retry is READ-paths-only and this must not reach it.

    DeleteMixin sends Id + SyncToken, so a retry after a first attempt that
    succeeded but whose response was lost comes back as a QBO refusal — which
    reads to the caller as "the delete failed" when it did not.
    """
    credit = _FakeCredit(response={"VendorCredit": {"Id": "96159", "status": "Deleted"}})
    svc = _service(monkeypatch, credit=credit)

    _run(svc.delete_vendor_credit(1, 96159))

    assert credit.delete_calls == 1


def test_a_refused_delete_is_not_retried_either(monkeypatch):
    """The refusal path is where a retry would do the most damage."""
    credit = _FakeCredit(raises=CLOSED_PERIOD)
    svc = _service(monkeypatch, credit=credit)

    with pytest.raises(QuickbooksException):
        _run(svc.delete_vendor_credit(1, 96159))

    assert credit.delete_calls == 1


def test_a_TRANSIENT_fault_on_the_delete_is_still_issued_only_once(monkeypatch):
    """The only test here that can tell to_thread from _to_thread_with_retry.

    The other two cannot, and that was a real hole: success calls delete once
    under either implementation, and a 6240 is classified non-transient so it
    also calls once. Swapping the delete to the retry helper passed the whole
    file.

    error_code 10000 is what the SDK raises when the response body will not
    parse — a gateway 502 AFTER QuickBooks has committed the delete looks
    exactly like this — and _is_transient_qbo_error classifies >= 10000 as
    transient. So this is precisely the scenario the no-retry comments argue
    against, and it is the one that would double-fire.

    The real retry helper is restored for this test; _service stubs it out so
    the other cases stay fast.
    """
    credit = _FakeCredit(raises=UNPARSEABLE_RESPONSE)
    svc = _service(monkeypatch, credit=credit)
    # Put the genuine helper back, or stubbing it would hide the very mutation
    # this test exists to catch.
    monkeypatch.delattr(svc, "_to_thread_with_retry", raising=False)

    with pytest.raises(QuickbooksException) as exc:
        _run(svc.delete_vendor_credit(1, 96159))

    assert exc.value.error_code == 10000
    assert credit.delete_calls == 1, (
        f"the delete was issued {credit.delete_calls} times on a transient "
        "fault — a retry here can delete a second record after the first "
        "attempt already committed"
    )


# ---------------------------------------------------------------------------
# 3. Not-found is 404, and the mapping covers only the fetch
# ---------------------------------------------------------------------------


def test_a_missing_credit_is_qbo_not_found(monkeypatch):
    svc = _service(
        monkeypatch,
        get_raises=ObjectNotFoundException("not found", error_code=610, detail=""),
    )

    with pytest.raises(QboNotFound):
        _run(svc.delete_vendor_credit(1, 99999))


def test_a_610_from_the_DELETE_is_not_reported_as_not_found(monkeypatch):
    """The fetch succeeded, so the credit existed. A 610 from the delete itself
    means something else, and calling it 404 would tell a caller that never
    retries a 404 that a delete which may have fired never did. Same reasoning
    as void_bill_payment, which is where this mapping came from.
    """
    credit = _FakeCredit(
        raises=ObjectNotFoundException("gone mid-flight", error_code=610, detail="")
    )
    svc = _service(monkeypatch, credit=credit)

    with pytest.raises(ObjectNotFoundException):
        _run(svc.delete_vendor_credit(1, 96159))


# ---------------------------------------------------------------------------
# What comes back on success
# ---------------------------------------------------------------------------


def test_quickbooks_own_response_is_passed_through_whole(monkeypatch):
    """#35 asked for the response rather than a summary of it.

    Whole means whole. An earlier cut unwrapped to `["VendorCredit"]`, which
    dropped `time` — a caller can reach into a response we hand over intact,
    and cannot recover a field we discarded.
    """
    body = {
        "VendorCredit": {"Id": "96159", "status": "Deleted", "domain": "QBO"},
        "time": "2026-09-18T14:00:00.000-07:00",
    }
    credit = _FakeCredit(response=body)
    svc = _service(monkeypatch, credit=credit)

    result = _run(svc.delete_vendor_credit(1, 96159))

    assert result == body
    assert result["time"] == "2026-09-18T14:00:00.000-07:00"
    assert result["VendorCredit"]["status"] == "Deleted"


def test_a_swallowed_quickbooks_fault_is_never_reported_as_deleted(monkeypatch):
    """None back from the SDK means a Fault was dropped, not "no response shape".

    client.make_request does `if "Fault" in result: handle_exceptions(...)`, and
    handle_exceptions loops over results["Error"] — so an EMPTY Error list
    raises nothing, the function returns, and make_request falls off the end
    returning None. That is the one branch where we know least about whether the
    credit is gone.

    An earlier version answered 200 {"status": "Deleted"} here. That invents the
    outcome: an operator reconciling a correction reads "Deleted" and stops
    looking at a credit that may still be in the books. This is the test that
    makes inventing it impossible.
    """
    credit = _FakeCredit(response=None)
    svc = _service(monkeypatch, credit=credit)

    with pytest.raises(QboUnavailable) as exc:
        _run(svc.delete_vendor_credit(1, 96159))

    # The two things the caller has to be able to act on: which credit, and
    # that the outcome is genuinely unknown rather than a success or a failure.
    assert exc.value.status_code == 503
    detail = str(exc.value.detail).lower()
    assert "96159" in detail
    assert "unknown" in detail


def test_the_swallowed_fault_really_is_what_the_sdk_produces():
    """Pins the premise of the test above against the installed SDK.

    If handle_exceptions ever starts raising on an empty Error list, the None
    branch becomes unreachable and the QboUnavailable above is dead code that
    still passes. This is what notices.
    """
    from quickbooks.client import QuickBooks

    # staticmethod — called on the class so no QuickBooks is constructed, which
    # would emit the SDK's minorversion DeprecationWarning for nothing.
    assert QuickBooks.handle_exceptions({"Error": []}) is None, (
        "handle_exceptions now raises on an empty Error list — make_request no "
        "longer returns None, so re-check what the non-dict branch means"
    )


# ---------------------------------------------------------------------------
# Blast radius — the property that matters most on a destructive endpoint
# ---------------------------------------------------------------------------


def test_the_credit_the_caller_named_is_the_one_fetched_and_deleted(monkeypatch):
    """Earlier fakes ignored entity_id, so hardcoding `get(1)` passed the suite."""
    probe = _Probe()
    credit = _FakeCredit(response={"VendorCredit": {"Id": "96159"}})
    svc = _service(monkeypatch, credit=credit, probe=probe)

    _run(svc.delete_vendor_credit(1, 96159))

    assert probe.fetched_ids == [96159]
    assert credit.delete_calls == 1


def test_the_delete_goes_to_the_callers_company(monkeypatch):
    """Earlier fakes ignored the company, so hardcoding `_get_company(999)` passed.

    The client is built per company from the resolved realm, so "deleted with
    the client belonging to the company the caller named" is the assertion that
    would notice a credit being removed from someone else's books.
    """
    probe = _Probe()
    credit = _FakeCredit(response={"VendorCredit": {"Id": "96159"}})
    svc = _service(monkeypatch, credit=credit, probe=probe)

    _run(svc.delete_vendor_credit(4, 96159))

    assert probe.companies == [4]
    assert credit.deleted_with_client is probe.client


# ---------------------------------------------------------------------------
# The route exists, is a DELETE, and is behind the API key
# ---------------------------------------------------------------------------


def test_the_route_is_registered_as_a_delete():
    paths = {
        (r.path, tuple(sorted(r.methods)))
        for r in vendor_credits.router.routes
        if hasattr(r, "methods")
    }
    assert ("/vendor-credits/{entity_id}", ("DELETE",)) in paths


def test_the_route_is_behind_the_api_key():
    deps = [d.dependency for d in vendor_credits.router.dependencies]
    assert verify_api_key in deps


def test_vendor_credit_cannot_be_voided_so_delete_is_the_only_exit():
    """Pins the claim the docstrings make, rather than asserting it in prose.

    #35 asked for void alongside delete. QuickBooks does not offer it for this
    entity: the SDK's VoidMixin covers Invoice, Payment, BillPayment,
    SalesReceipt and the two recurring types. If VendorCredit ever gains it,
    this fails and the "delete is the only exit" wording has to change.
    """
    from quickbooks.mixins import DeleteMixin, VoidMixin
    from quickbooks.objects.billpayment import BillPayment
    from quickbooks.objects.vendorcredit import VendorCredit

    assert issubclass(BillPayment, VoidMixin), (
        "control broke: a voidable entity must carry VoidMixin, or the "
        "assertion below proves nothing"
    )
    assert issubclass(VendorCredit, DeleteMixin)
    assert not issubclass(VendorCredit, VoidMixin)
