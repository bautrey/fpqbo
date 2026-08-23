"""Voiding a BillPayment, and the order the two writes happen in.

The defect this closes is an accounting one. When a Wise transfer is funded,
a QBO BillPayment is created immediately. If Wise later cancels the transfer
— unclaimed claim-link transfers auto-cancel after about ten days — nothing
unwound the QBO side, so QuickBooks kept showing a payment that never happened
and the bill stayed falsely closed. The live case was BillPayment 659 in
FOR-971, $2,496 to David Bergh: Wise cancelled on 08/07, a human noticed and
voided it by hand on 08/12, and the books were wrong for five days in between.

Two things here are easy to get backwards, so both are pinned:

1. The void must go BEFORE the note, not after. Both survive — the void's
   payload is sparse, so a separately-written PrivateNote persists through it
   (verified on 659, which still carries its note at SyncToken 2). But if the
   note is written first and the void then fails, a live payment that is still
   closing its bill now carries a note claiming it was voided. That is worse
   than the state we started in.

2. A note that fails to save must not fail the request. The void is what the
   caller asked for; reporting failure after it succeeded would tell them the
   books were not corrected when they were.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.api_auth import verify_api_key
from quickbooks.exceptions import ObjectNotFoundException, SevereException

from app.exceptions import QboNotFound
from app.routers import bill_payments
from app.services.qbo_service import QBOService


def _run(coro):
    return asyncio.run(coro)


class _FakeBillPayment:
    """Stands in for the SDK class, recording the order of operations."""

    calls: list[str] = []
    existing = True
    void_raises: Exception | None = None
    save_raises: Exception | None = None

    def __init__(self, entity_id="659"):
        self.Id = entity_id
        self.SyncToken = "1"
        self.TotalAmt = 2496.0
        self.PrivateNote = None

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.existing = True
        cls.void_raises = None
        cls.save_raises = None
        cls._instance = _FakeBillPayment()

    @classmethod
    def get(cls, entity_id, qb=None):
        cls.calls.append("get")
        if not cls.existing:
            # What the real SDK does. ReadMixin.get() returns from_json(...)
            # or raises — it never returns a falsy object. The first version
            # of this fake returned None, so it validated a `if not bp` guard
            # that is dead against the real client and the endpoint answered
            # 500 where it documented 404.
            raise ObjectNotFoundException(
                "QB Object Not Found Exception", error_code=610
            )
        return cls._instance

    def void(self, qb=None):
        type(self).calls.append("void")
        if type(self).void_raises:
            raise type(self).void_raises
        self.TotalAmt = 0.0
        self.SyncToken = str(int(self.SyncToken) + 1)

    def save(self, qb=None):
        type(self).calls.append("save")
        if type(self).save_raises:
            raise type(self).save_raises
        self.SyncToken = str(int(self.SyncToken) + 1)
        return self

    def to_dict(self):
        return {
            "Id": self.Id,
            "TotalAmt": self.TotalAmt,
            "SyncToken": self.SyncToken,
            "PrivateNote": self.PrivateNote,
        }


def _svc(monkeypatch):
    _FakeBillPayment.reset()
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(QBOService, "_get_company", lambda self, cid: object())
    monkeypatch.setattr(QBOService, "_get_client", lambda self, c: object())
    monkeypatch.setattr("app.services.qbo_service.BillPayment", _FakeBillPayment)
    return svc


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_voiding_zeroes_the_payment(monkeypatch):
    svc = _svc(monkeypatch)

    result = _run(svc.void_bill_payment(company_id=2, entity_id=659))

    assert result["TotalAmt"] == 0.0, "a voided payment must stop closing its bill"
    assert "void" in _FakeBillPayment.calls


def test_an_unknown_payment_is_a_404_not_a_silent_success(monkeypatch):
    """Reporting success for an id QBO does not have would tell the caller
    the books were corrected when nothing happened."""
    svc = _svc(monkeypatch)
    _FakeBillPayment.existing = False

    with pytest.raises(QboNotFound) as caught:
        _run(svc.void_bill_payment(company_id=2, entity_id=999999))

    assert caught.value.status_code == 404
    assert "999999" in str(caught.value.detail)
    assert "void" not in _FakeBillPayment.calls, "must not void what it could not fetch"


def test_the_void_happens_before_the_note(monkeypatch):
    """The whole point of the ordering.

    Stamping first and then failing the void leaves a live payment carrying a
    note that says it was voided — a wrong record that reads as authoritative.
    """
    svc = _svc(monkeypatch)

    _run(svc.void_bill_payment(company_id=2, entity_id=659, note="Wise cancelled"))

    calls = _FakeBillPayment.calls
    assert "void" in calls and "save" in calls
    assert calls.index("void") < calls.index("save"), (
        f"note was written before the void: {calls}"
    )


def test_the_note_is_applied_and_reported(monkeypatch):
    svc = _svc(monkeypatch)

    result = _run(
        svc.void_bill_payment(
            company_id=2, entity_id=659,
            note="Voided - Wise transfer 2275843074 Cancelled on 08/07/26",
        )
    )

    assert result["note_applied"] is True
    assert "2275843074" in result["PrivateNote"]


def test_a_failed_note_does_not_fail_the_void(monkeypatch, caplog):
    """The void already succeeded. Raising now would report the books
    uncorrected when they were corrected."""
    svc = _svc(monkeypatch)
    _FakeBillPayment.save_raises = RuntimeError("QBO rejected the update")

    with caplog.at_level(logging.ERROR, logger="app.services.qbo_service"):
        result = _run(
            svc.void_bill_payment(company_id=2, entity_id=659, note="Wise cancelled")
        )

    assert result["TotalAmt"] == 0.0, "the void must stand"
    assert result["note_applied"] is False, (
        "the caller has to be able to tell the provenance did not stick, or "
        "they will believe QBO holds a record it does not"
    )
    assert [r for r in caplog.records if r.levelno == logging.ERROR], (
        "a swallowed failure with no log is invisible"
    )


def test_a_failed_void_is_not_reported_as_success(monkeypatch):
    """The one failure that must propagate."""
    svc = _svc(monkeypatch)
    _FakeBillPayment.void_raises = RuntimeError("QBO rejected the void")

    with pytest.raises(RuntimeError):
        _run(svc.void_bill_payment(company_id=2, entity_id=659, note="Wise cancelled"))

    assert "save" not in _FakeBillPayment.calls, (
        "a note must never be stamped onto a payment that is still live"
    )


def test_no_note_means_no_second_write(monkeypatch):
    svc = _svc(monkeypatch)

    result = _run(svc.void_bill_payment(company_id=2, entity_id=659))

    assert "save" not in _FakeBillPayment.calls
    assert "note_applied" not in result, (
        "the flag should only appear when a note was actually requested"
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _client(service):
    app = FastAPI()
    app.include_router(bill_payments.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[bill_payments._get_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_exists_and_is_a_post():
    paths = {
        (r.path, tuple(sorted(r.methods)))
        for r in bill_payments.router.routes
        if hasattr(r, "methods")
    }
    assert ("/bill-payments/{entity_id}/void", ("POST",)) in paths


def test_the_route_is_behind_the_api_key():
    """Router-level dependency, same as every other endpoint here. Asserted
    because a void is destructive and an unauthenticated one would be worse
    than the defect it fixes."""
    deps = [d.dependency for d in bill_payments.router.dependencies]
    assert verify_api_key in deps


def test_a_404_from_the_service_reaches_the_caller_as_404():
    """Through `run_qbo_write`, whose HTTPException guard re-raises it.

    An earlier draft of this endpoint hand-rolled its try/except, citing the
    carve-out that keeps the older void and delete endpoints out of the
    helper. That reasoning stopped being true at #15: not-found is no longer a
    ValueError, so the helper's ValueError->400 branch cannot reach it. The
    hand-rolled version's real cost was that it logged nothing on a 500.
    """

    class _Missing:
        async def void_bill_payment(self, *a, **k):
            raise QboNotFound("BillPayment 999999 not found")

    res = _client(_Missing()).post(
        "/bill-payments/999999/void", params={"company_id": 2}
    )

    assert res.status_code == 404
    assert res.status_code != 400, "the helper clobbered a deliberate 404"
    assert res.json()["detail"] == "BillPayment 999999 not found"


def test_the_note_reaches_the_service_from_the_query_string():
    recorded = {}

    class _Recording:
        async def void_bill_payment(self, company_id, entity_id, note=None):
            recorded.update(company_id=company_id, entity_id=entity_id, note=note)
            return {"Id": str(entity_id), "TotalAmt": 0, "note_applied": True}

    res = _client(_Recording()).post(
        "/bill-payments/659/void",
        params={"company_id": 2, "note": "Wise transfer 2275843074 cancelled"},
    )

    assert res.status_code == 200
    assert recorded["note"] == "Wise transfer 2275843074 cancelled"
    assert recorded["entity_id"] == 659
    assert recorded["company_id"] == 2


def test_an_unexpected_fault_is_a_500_and_leaves_a_traceback(caplog):
    """Narrowing must not turn a real bug into "no such payment" — and a 500
    nobody can see is the open half of #15, so this endpoint is not allowed to
    add to it. The logging is the reason this route uses `run_qbo_write`
    rather than its own try/except."""

    class _Broken:
        async def void_bill_payment(self, *a, **k):
            raise AttributeError("'NoneType' object has no attribute 'SyncToken'")

    with caplog.at_level(logging.ERROR, logger="app.routers._qbo_write"):
        res = _client(_Broken()).post(
            "/bill-payments/659/void", params={"company_id": 2}
        )

    assert res.status_code == 500
    assert res.status_code != 404, "a local bug must not read as a missing record"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "a 500 with no server-side trace is invisible"
    assert any(r.exc_info for r in errors), "the traceback is the useful part"


def test_the_void_is_not_retried_after_a_transient_fault(monkeypatch):
    """A void must fire exactly once, whatever QBO does afterwards.

    `_to_thread_with_retry` carries the warning "READ paths only — never wrap
    a non-idempotent mutation (double-post risk)". The first draft of this
    method used it anyway. A transient fault raised after QBO had already
    applied the void re-ran the whole closure and voided a second time; the
    re-void fails as a non-transient ValidationException, so the caller is
    told 500 for books that were in fact corrected — the same class of lie the
    note ordering exists to prevent, arriving by a different route.
    """
    svc = _svc(monkeypatch)

    calls = {"n": 0}
    real_get = _FakeBillPayment.get.__func__

    def _flaky_get(cls, entity_id, qb=None):
        calls["n"] += 1
        # Fault on the re-read, i.e. after the void has already been applied.
        #
        # SevereException, not a bare Exception with transient-sounding text.
        # `_is_transient_qbo_error` dispatches on TYPE, so the first version of
        # this test raised something the classifier declined to retry — no
        # retry happened, the void fired once, and the test passed whether or
        # not the mutation was wrapped in the retry helper. It proved nothing
        # about the thing it was named for.
        if calls["n"] == 2:
            raise SevereException("QB Severe Exception", error_code=10000)
        return real_get(cls, entity_id, qb=qb)

    monkeypatch.setattr(_FakeBillPayment, "get", classmethod(_flaky_get))

    with pytest.raises(Exception):
        _run(svc.void_bill_payment(company_id=2, entity_id=659))

    assert _FakeBillPayment.calls.count("void") == 1, (
        f"void fired {_FakeBillPayment.calls.count('void')} times: "
        f"{_FakeBillPayment.calls}"
    )
