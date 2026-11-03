"""Tests for POST /api/payments/ — recording a client Payment against an Invoice."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.exceptions import QboBadPayload
from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService


def _run(coro):
    return asyncio.run(coro)


def _make_service():
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    return svc


class _Sentinel:
    def __init__(self):
        self.captured = None
        self.calls = 0

    def __call__(self, obj):
        self.calls += 1
        self.captured = obj
        # What save() saw: the SDK updates instead of creating when Id is set.
        self.id_at_save = obj.Id
        self.sync_token_at_save = getattr(obj, "SyncToken", None)
        obj.Id = "9999"
        return obj


def _stub(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())
    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.Payment, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )
    return svc, sentinel


PAYOUTS_BODY = {
    "CustomerRef": {"value": "1400", "name": "ZRG - CalPoly"},
    "TotalAmt": 12500.00,
    "TxnDate": "2026-10-28",
    "DepositToAccountRef": {"value": "4"},
    "PrivateNote": "payouts:zrg-collection:abc123",
    "Line": [
        {"Amount": 12500.00, "LinkedTxn": [{"TxnId": "97001", "TxnType": "Invoice"}]}
    ],
}


def test_create_payment_carries_every_field_payouts_sends(monkeypatch):
    svc, sentinel = _stub(monkeypatch)

    result = _run(svc.create_payment(1, PAYOUTS_BODY))

    p = sentinel.captured
    assert p is not None, "Payment.save() was never called"
    assert p.CustomerRef.value == "1400"
    assert p.CustomerRef.name == "ZRG - CalPoly"
    assert p.TotalAmt == 12500.00
    assert p.TxnDate == "2026-10-28"
    assert p.DepositToAccountRef.value == "4"
    assert p.PrivateNote == "payouts:zrg-collection:abc123"
    assert len(p.Line) == 1
    assert p.Line[0].Amount == 12500.00
    assert len(p.Line[0].LinkedTxn) == 1
    assert p.Line[0].LinkedTxn[0].TxnId == "97001"
    assert p.Line[0].LinkedTxn[0].TxnType == "Invoice"
    assert result["Id"] == "9999"


@pytest.mark.parametrize("key", ["Id", "SyncToken"])
def test_create_payment_never_turns_into_an_update(monkeypatch, key):
    """The SDK's save() UPDATES when Id is set. A body carrying Id or
    SyncToken is refused, so a create can never overwrite an existing payment."""
    svc, sentinel = _stub(monkeypatch)

    with pytest.raises(QboBadPayload, match=key):
        _run(svc.create_payment(1, {**PAYOUTS_BODY, key: "84286"}))
    assert sentinel.calls == 0


def test_create_payment_optional_refs(monkeypatch):
    svc, sentinel = _stub(monkeypatch)

    _run(svc.create_payment(1, {
        **PAYOUTS_BODY,
        "PaymentRefNum": "WIRE-778",
        "PaymentMethodRef": {"value": "3"},
        "ARAccountRef": {"value": "84"},
        "ExchangeRate": 1.37,
    }))

    p = sentinel.captured
    assert p.PaymentRefNum == "WIRE-778"
    assert p.PaymentMethodRef.value == "3"
    assert p.ARAccountRef.value == "84"
    assert p.ExchangeRate == 1.37


def test_create_payment_minimal_body_leaves_refs_unset(monkeypatch):
    svc, sentinel = _stub(monkeypatch)

    _run(svc.create_payment(1, {
        "CustomerRef": {"value": "1"},
        "TotalAmt": 5,
        "Line": [{"Amount": 5, "LinkedTxn": [{"TxnId": "13", "TxnType": "Invoice"}]}],
    }))

    p = sentinel.captured
    assert p.DepositToAccountRef is None
    assert p.PaymentMethodRef is None
    assert len(p.Line) == 1


@pytest.mark.parametrize("bad_key", ["DepositToAcountRef", "CurrencyRef", "TaxExemptionRef"])
def test_create_payment_rejects_a_field_it_would_drop(monkeypatch, bad_key):
    """A misspelled DepositToAccountRef would otherwise be dropped and the
    payment land in Undeposited Funds behind a 201."""
    svc, sentinel = _stub(monkeypatch)

    with pytest.raises(QboBadPayload, match=bad_key):
        _run(svc.create_payment(1, {**PAYOUTS_BODY, bad_key: {"value": "35"}}))
    assert sentinel.calls == 0


@pytest.mark.parametrize("missing", ["CustomerRef", "TotalAmt", "Line"])
def test_create_payment_requires_customer_amount_and_lines(monkeypatch, missing):
    svc, sentinel = _stub(monkeypatch)
    body = {k: v for k, v in PAYOUTS_BODY.items() if k != missing}

    with pytest.raises(QboBadPayload, match=missing):
        _run(svc.create_payment(1, body))
    assert sentinel.calls == 0


@pytest.mark.parametrize("lines", [
    [],
    [{"Amount": 12500.00}],
    [{"Amount": 12500.00, "LinkedTxn": []}],
])
def test_create_payment_refuses_a_payment_applied_to_no_invoice(monkeypatch, lines):
    """Without a LinkedTxn QBO books an unapplied credit on the customer, and
    the invoice the caller meant to pay stays open."""
    svc, sentinel = _stub(monkeypatch)

    # An empty Line[] is refused as missing; a line without links names LinkedTxn.
    with pytest.raises(QboBadPayload, match="requires: Line|LinkedTxn"):
        _run(svc.create_payment(1, {**PAYOUTS_BODY, "Line": lines}))
    assert sentinel.calls == 0


def test_post_payments_answers_400_for_a_dropped_field():
    from app.services.qbo_service import QBOService as _Real

    svc = _Real.__new__(_Real)
    svc.db = None
    svc._clients = {}
    svc._get_company = lambda _cid: SimpleNamespace(realm_id="r1")
    svc._get_client = lambda _co: SimpleNamespace()

    app, client = _client(svc)
    try:
        resp = client.post("/payments/?company_id=1", json={**PAYOUTS_BODY, "DepositToAcountRef": {"value": "35"}})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "DepositToAcountRef" in resp.json()["detail"]


def test_create_payment_is_never_retried(monkeypatch):
    """A create is not idempotent: one POST, one save, even on failure."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())
    calls = []

    def _boom(self, qb=None):
        calls.append(1)
        raise qbo_service_module.QuickbooksException("boom", error_code=10000)

    monkeypatch.setattr(qbo_service_module.Payment, "save", _boom, raising=True)

    try:
        _run(svc.create_payment(1, PAYOUTS_BODY))
    except Exception:
        pass
    assert calls == [1]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _client(fake_service):
    from fastapi import FastAPI

    from app.dependencies import verify_api_key
    from app.routers import payments

    app = FastAPI()
    app.include_router(payments.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[payments._get_service] = lambda: fake_service
    return app, TestClient(app, raise_server_exceptions=False)


def test_post_payments_returns_201_with_created_payment():
    seen = {}

    async def _create(company_id, data):
        seen["company_id"] = company_id
        seen["data"] = data
        return {"Id": "97600", "MetaData": {"CreateTime": "2026-11-02T09:00:00-08:00"}}

    app, client = _client(SimpleNamespace(create_payment=_create))
    try:
        resp = client.post("/payments/?company_id=1", json=PAYOUTS_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert resp.json()["Id"] == "97600"
    assert resp.json()["MetaData"]["CreateTime"] == "2026-11-02T09:00:00-08:00"
    assert seen["company_id"] == 1
    assert seen["data"] == PAYOUTS_BODY


def test_post_payments_passes_quickbooks_refusal_text_through():
    async def _create(company_id, data):
        raise qbo_service_module.QuickbooksException(
            "Invalid account type", error_code=6000, detail="Deposit To account must be Bank or Other Current Asset"
        )

    app, client = _client(SimpleNamespace(create_payment=_create))
    try:
        resp = client.post("/payments/?company_id=1", json=PAYOUTS_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    assert "Invalid account type" in resp.json()["detail"]
    assert "Deposit To account must be Bank or Other Current Asset" in resp.json()["detail"]


def test_payments_router_post_requires_api_key():
    from app.dependencies import verify_api_key
    from app.routers import payments

    assert verify_api_key in [d.dependency for d in payments.router.dependencies]
