"""Voiding a customer Payment: POST /api/payments/{id}/void.

POST /api/payments/ records ZRG client payments into 102500, and nothing could
undo one. A wrong amount or the wrong invoice had to be fixed by hand in
QuickBooks. This mirrors POST /api/bill-payments/{id}/void and pins the same
three properties: the void fires exactly once, a re-void is a no-op, and a 610
on the re-read after the void is never reported as not-found.

Voided shape, measured 2026-11-03: FOR-971 Payment 270 reads TotalAmt 0,
`Line: []` and PrivateNote "Voided", which QuickBooks writes itself. FOR-138
has 169 other zero-total payments, and the ones sampled carry two lines each
("Created by QB Online to link credits to charges."). Those are live, so the
zero total alone is not the void marker.
"""

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quickbooks.exceptions import ObjectNotFoundException, SevereException

from app.dependencies.api_auth import verify_api_key
from app.exceptions import QboNotFound
from app.routers import payments
from app.services.qbo_service import QBOService


def _run(coro):
    return asyncio.run(coro)


class _FakePayment:
    calls: list[str] = []
    existing = True

    def __init__(self, entity_id="404"):
        self.Id = entity_id
        self.SyncToken = "0"
        self.TotalAmt = 80.0
        self.Line = [{"Amount": 80.0, "LinkedTxn": [{"TxnId": "64", "TxnType": "Invoice"}]}]
        self.PrivateNote = None

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.existing = True
        cls.fetched_ids = []
        cls._instance = _FakePayment()

    @classmethod
    def get(cls, entity_id, qb=None):
        cls.calls.append("get")
        cls.fetched_ids.append(entity_id)
        if not cls.existing:
            raise ObjectNotFoundException("QB Object Not Found Exception", error_code=610)
        return cls._instance

    def void(self, qb=None):
        type(self).calls.append("void")
        self.TotalAmt = 0.0
        self.Line = []
        self.PrivateNote = "Voided"
        self.SyncToken = str(int(self.SyncToken) + 1)

    def to_dict(self):
        return {
            "Id": self.Id,
            "TotalAmt": self.TotalAmt,
            "Line": self.Line,
            "SyncToken": self.SyncToken,
            "PrivateNote": self.PrivateNote,
        }


def _svc(monkeypatch):
    _FakePayment.reset()
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(QBOService, "_get_company", lambda self, cid: object())
    monkeypatch.setattr(QBOService, "_get_client", lambda self, c: object())
    monkeypatch.setattr("app.services.qbo_service.Payment", _FakePayment)
    return svc


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_voiding_zeroes_the_payment_and_reopens_nothing_silently(monkeypatch):
    svc = _svc(monkeypatch)

    result = _run(svc.void_payment(company_id=5, entity_id=404))

    assert _FakePayment.calls.count("void") == 1
    assert _FakePayment.fetched_ids == [404, 404], "fetch, then re-read the same id"
    assert result["TotalAmt"] == 0.0
    assert result["already_voided"] is False


def test_an_unknown_payment_is_a_404_and_nothing_is_voided(monkeypatch):
    svc = _svc(monkeypatch)
    _FakePayment.existing = False

    with pytest.raises(QboNotFound) as caught:
        _run(svc.void_payment(company_id=5, entity_id=999999))

    assert caught.value.status_code == 404
    assert "Payment 999999 not found" == caught.value.detail
    assert "void" not in _FakePayment.calls


def test_voiding_an_already_voided_payment_is_a_no_op(monkeypatch):
    svc = _svc(monkeypatch)
    _FakePayment._instance.TotalAmt = 0.0
    _FakePayment._instance.Line = []

    result = _run(svc.void_payment(company_id=2, entity_id=270))

    assert result["already_voided"] is True
    assert "void" not in _FakePayment.calls


def test_a_live_zero_total_credit_link_payment_is_still_voided(monkeypatch):
    """FOR-138 holds QBO-made zero-total payments linking a CreditMemo to an
    Invoice. Reading them as already voided would answer 200 and do nothing."""
    svc = _svc(monkeypatch)
    p = _FakePayment._instance
    p.TotalAmt = 0.0
    p.Line = [
        {"Amount": 25.0, "LinkedTxn": [{"TxnId": "1", "TxnType": "Invoice"}]},
        {"Amount": 25.0, "LinkedTxn": [{"TxnId": "2", "TxnType": "CreditMemo"}]},
    ]

    result = _run(svc.void_payment(company_id=1, entity_id=942))

    assert "void" in _FakePayment.calls
    assert result["already_voided"] is False


def test_the_void_is_not_retried_after_a_transient_fault(monkeypatch):
    svc = _svc(monkeypatch)
    calls = {"n": 0}
    real_get = _FakePayment.get.__func__

    def _flaky_get(cls, entity_id, qb=None):
        calls["n"] += 1
        if calls["n"] == 2:  # the re-read, after the void has fired
            raise SevereException("QB Severe Exception", error_code=10000)
        return real_get(cls, entity_id, qb=qb)

    monkeypatch.setattr(_FakePayment, "get", classmethod(_flaky_get))

    with pytest.raises(SevereException):
        _run(svc.void_payment(company_id=5, entity_id=404))

    assert _FakePayment.calls.count("void") == 1


def test_a_610_after_the_void_is_not_reported_as_not_found(monkeypatch):
    svc = _svc(monkeypatch)
    seen = {"n": 0}
    real_get = _FakePayment.get.__func__

    def _vanishing_get(cls, entity_id, qb=None):
        seen["n"] += 1
        if seen["n"] == 2:
            raise ObjectNotFoundException("gone", error_code=610)
        return real_get(cls, entity_id, qb=qb)

    monkeypatch.setattr(_FakePayment, "get", classmethod(_vanishing_get))

    with pytest.raises(ObjectNotFoundException) as caught:
        _run(svc.void_payment(company_id=5, entity_id=404))

    assert "void" in _FakePayment.calls
    assert not isinstance(caught.value, QboNotFound)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _client(service):
    app = FastAPI()
    app.include_router(payments.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[payments._get_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_exists_and_is_a_post():
    paths = {
        (r.path, tuple(sorted(r.methods)))
        for r in payments.router.routes
        if hasattr(r, "methods")
    }
    assert ("/payments/{entity_id}/void", ("POST",)) in paths


def test_the_route_is_behind_the_api_key():
    assert verify_api_key in [d.dependency for d in payments.router.dependencies]


def test_the_route_passes_company_and_id_and_returns_the_body():
    seen = {}

    class _Ok:
        async def void_payment(self, company_id, entity_id):
            seen.update(company_id=company_id, entity_id=entity_id)
            return {"Id": "404", "TotalAmt": 0.0, "already_voided": False}

    res = _client(_Ok()).post("/payments/404/void", params={"company_id": 5})

    assert res.status_code == 200
    assert res.json() == {"Id": "404", "TotalAmt": 0.0, "already_voided": False}
    assert seen == {"company_id": 5, "entity_id": 404}


def test_a_404_from_the_service_reaches_the_caller_as_404():
    class _Missing:
        async def void_payment(self, *a, **k):
            raise QboNotFound("Payment 999999 not found")

    res = _client(_Missing()).post("/payments/999999/void", params={"company_id": 5})

    assert res.status_code == 404
    assert res.json()["detail"] == "Payment 999999 not found"


def test_a_server_side_type_error_is_a_logged_500_not_a_payload_400(caplog):
    class _Broken:
        async def void_payment(self, *a, **k):
            raise TypeError("'NoneType' object is not subscriptable")

    with caplog.at_level(logging.ERROR, logger="app.routers._qbo_write"):
        res = _client(_Broken()).post("/payments/404/void", params={"company_id": 5})

    assert res.status_code == 500
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and any(r.exc_info for r in errors)
