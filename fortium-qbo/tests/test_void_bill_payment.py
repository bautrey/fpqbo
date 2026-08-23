"""Voiding a BillPayment, and the order the two writes happen in.

The defect this closes is an accounting one. When a Wise transfer is funded,
a QBO BillPayment is created immediately. If Wise later cancels the transfer
— unclaimed claim-link transfers auto-cancel after about ten days — nothing
unwound the QBO side, so QuickBooks kept showing a payment that never happened
and the bill stayed falsely closed. The live case was BillPayment 659 in
FOR-971, $2,496 to David Bergh: Wise cancelled on 08/07, a human noticed and
voided it by hand on 08/12, and the books were wrong for five days in between.

Three things here are easy to get wrong, so all three are pinned:

1. The void must fire exactly once. `_to_thread_with_retry` warns "READ paths
   only — never wrap a non-idempotent mutation"; wrapping it there re-voids
   after a transient fault and the re-void fails, so the caller is told 500
   for books that were corrected.

2. An already-voided payment is a no-op, not an error. The caller is a
   reconciler that re-runs over the same cancelled transfers, so every pass
   after the first would otherwise 500 on correct books.

3. A 610 on the re-read AFTER the void must not be reported as not-found.
   That would tell a reconciler which never retries a 404 that a void which
   actually happened never did.

The PrivateNote stamp this endpoint originally carried was cut to #25. The
SDK's save() is a FULL update for BillPayment — `sparse` defaults to False
and `to_json()` ships Line, TotalAmt and VendorRef — so it replaces rather
than amends, and cannot be verified without a live write.
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


def test_voiding_an_already_voided_payment_is_a_no_op(monkeypatch):
    """The reconciler re-runs over the same set of cancelled transfers.

    QBO rejects a re-void as a non-transient ValidationException, so without
    this the second and every later pass answers 500 for books that are
    already correct — and a 500 is what a reconciler retries forever.
    """
    svc = _svc(monkeypatch)
    _FakeBillPayment._instance.TotalAmt = 0.0  # QBO's mark of a voided payment

    result = _run(svc.void_bill_payment(company_id=2, entity_id=659))

    assert result["already_voided"] is True
    assert "void" not in _FakeBillPayment.calls, (
        "re-voiding is what makes the reconciler's second pass fail"
    )


def test_a_610_after_the_void_is_not_reported_as_not_found(monkeypatch):
    """The void already happened. Answering 404 tells a caller that never
    retries a 404 that it never happened, and the books silently diverge."""
    svc = _svc(monkeypatch)

    seen = {"n": 0}
    real_get = _FakeBillPayment.get.__func__

    def _vanishing_get(cls, entity_id, qb=None):
        seen["n"] += 1
        if seen["n"] == 2:  # the re-read, after void() has fired
            raise ObjectNotFoundException("gone", error_code=610)
        return real_get(cls, entity_id, qb=qb)

    monkeypatch.setattr(_FakeBillPayment, "get", classmethod(_vanishing_get))

    with pytest.raises(Exception) as caught:
        _run(svc.void_bill_payment(company_id=2, entity_id=659))

    assert "void" in _FakeBillPayment.calls, "precondition: the void must have fired"
    assert not isinstance(caught.value, QboNotFound), (
        "a completed void was reported as a missing payment"
    )
