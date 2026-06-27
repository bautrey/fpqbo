"""Tests for the Account and Item create service methods + routes.

Stub the QBO SDK's network surface (the per-class ``.save`` and the
``_get_company`` / ``_get_client`` helpers) and verify the constructed QBO
domain object carries exactly the fields from the request payload.
"""

import asyncio
from types import SimpleNamespace

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
    """Captures the QBO domain object passed to ``.save()``."""

    def __init__(self):
        self.captured = None

    def __call__(self, obj):
        self.captured = obj
        obj.Id = "9999"
        return obj


# ---------------------------------------------------------------------------
# create_account
# ---------------------------------------------------------------------------


def test_create_account_builds_payload_with_all_fields(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.Account, "save", lambda self, qb=None: sentinel(self), raising=True
    )

    payload = {
        "Name": "Administrative and Technology Fee",
        "AccountType": "Income",
        "AccountSubType": "ServiceFeeIncome",
        "AcctNum": "400100",
        "Description": "Fees billed to clients",
        "Classification": "Revenue",
        "Active": True,
        "SubAccount": False,
        "CurrencyRef": {"value": "USD", "name": "United States Dollar"},
        "ParentRef": {"value": "90"},
    }

    result = _run(svc.create_account(1, payload))

    acct = sentinel.captured
    assert acct is not None, "Account.save() was never called"
    assert acct.Name == "Administrative and Technology Fee"
    assert acct.AccountType == "Income"
    assert acct.AccountSubType == "ServiceFeeIncome"
    assert acct.AcctNum == "400100"
    assert acct.Description == "Fees billed to clients"
    assert acct.Classification == "Revenue"
    assert acct.Active is True
    assert acct.SubAccount is False
    assert acct.CurrencyRef.value == "USD"
    assert acct.CurrencyRef.name == "United States Dollar"
    assert acct.ParentRef.value == "90"
    assert result["Id"] == "9999"


def test_create_account_minimal_payload(monkeypatch):
    """Only the required Name + AccountType; optional refs stay unset."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.Account, "save", lambda self, qb=None: sentinel(self), raising=True
    )

    result = _run(svc.create_account(1, {"Name": "Cash on Hand", "AccountType": "Bank"}))

    acct = sentinel.captured
    assert acct.Name == "Cash on Hand"
    assert acct.AccountType == "Bank"
    assert acct.CurrencyRef is None
    assert acct.ParentRef is None
    assert result["Id"] == "9999"


# ---------------------------------------------------------------------------
# create_item
# ---------------------------------------------------------------------------


def test_create_item_builds_payload_with_all_fields(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.Item, "save", lambda self, qb=None: sentinel(self), raising=True
    )

    payload = {
        "Name": "Consulting",
        "Type": "Service",
        "Description": "Consulting services",
        "PurchaseDesc": "Consulting cost",
        "Sku": "CONSULT-1",
        "UnitPrice": 150.0,
        "PurchaseCost": 0,
        "Taxable": False,
        "Active": True,
        "TrackQtyOnHand": False,
        "IncomeAccountRef": {"value": "42", "name": "Consulting Income"},
        "ExpenseAccountRef": {"value": "60"},
    }

    result = _run(svc.create_item(1, payload))

    item = sentinel.captured
    assert item is not None, "Item.save() was never called"
    assert item.Name == "Consulting"
    assert item.Type == "Service"
    assert item.Description == "Consulting services"
    assert item.PurchaseDesc == "Consulting cost"
    assert item.Sku == "CONSULT-1"
    assert item.UnitPrice == 150.0
    assert item.PurchaseCost == 0
    assert item.Taxable is False
    assert item.Active is True
    assert item.TrackQtyOnHand is False
    assert item.IncomeAccountRef.value == "42"
    assert item.IncomeAccountRef.name == "Consulting Income"
    assert item.ExpenseAccountRef.value == "60"
    # Optional refs not provided stay None
    assert item.AssetAccountRef is None
    assert item.ParentRef is None
    assert result["Id"] == "9999"


def test_create_item_minimal_payload(monkeypatch):
    """A Service item needs only Name, Type, and an income account."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.Item, "save", lambda self, qb=None: sentinel(self), raising=True
    )

    payload = {
        "Name": "Bad Debt",
        "Type": "Service",
        "IncomeAccountRef": {"value": "37"},
    }
    result = _run(svc.create_item(1, payload))

    item = sentinel.captured
    assert item.Name == "Bad Debt"
    assert item.Type == "Service"
    assert item.IncomeAccountRef.value == "37"
    assert item.ExpenseAccountRef is None
    assert item.AssetAccountRef is None
    assert result["Id"] == "9999"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_accounts_router_has_post_route():
    from app.routers import accounts

    methods_paths = {
        (frozenset(r.methods), r.path)
        for r in accounts.router.routes
        if hasattr(r, "methods")
    }
    assert (frozenset({"POST"}), "/accounts/") in methods_paths


def test_items_router_has_post_route():
    from app.routers import items

    methods_paths = {
        (frozenset(r.methods), r.path)
        for r in items.router.routes
        if hasattr(r, "methods")
    }
    assert (frozenset({"POST"}), "/items/") in methods_paths
