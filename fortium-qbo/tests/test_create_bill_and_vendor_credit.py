"""Tests for the new Bill and VendorCredit create service methods.

These tests stub out the QBO SDK's network-touching surface (the per-class
``.save`` method and the ``QBOService._get_company`` / ``_get_client`` helpers)
and verify that the constructed QBO domain object carries exactly the fields
we expect from the request payload.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def _make_service():
    """Build a QBOService whose company/client lookups are no-ops."""
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
        # Mimic what python-quickbooks's save() returns (the saved object with
        # an Id assigned by QBO).
        obj.Id = "9999"
        return obj


# ---------------------------------------------------------------------------
# create_bill
# ---------------------------------------------------------------------------


def test_create_bill_builds_payload_with_all_fields(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()

    def _fake_save(self, qb=None):
        return sentinel(self)

    monkeypatch.setattr(qbo_service_module.Bill, "save", _fake_save, raising=True)

    payload = {
        "VendorRef": {"value": "123", "name": "Acme"},
        "TxnDate": "2026-04-30",
        "DueDate": "2026-05-30",
        "DocNumber": "INV-001-456-Doe",
        "PrivateNote": "Memo here",
        "APAccountRef": {"value": "81"},
        "Line": [
            {
                "Amount": 1000.00,
                "Description": "Consulting",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "60"},
                    "ClassRef": {"value": "5000000000000123456"},
                    "CustomerRef": {"value": "42"},
                },
            },
            {
                "Amount": 250.50,
                "Description": "Reimbursable expenses",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "61"},
                },
            },
        ],
    }

    result = _run(svc.create_bill(1, payload))

    bill = sentinel.captured
    assert bill is not None, "Bill.save() was never called"
    assert bill.TxnDate == "2026-04-30"
    assert bill.DueDate == "2026-05-30"
    assert bill.DocNumber == "INV-001-456-Doe"
    assert bill.PrivateNote == "Memo here"
    assert bill.VendorRef.value == "123"
    assert bill.VendorRef.name == "Acme"
    assert bill.APAccountRef.value == "81"

    assert len(bill.Line) == 2
    line0 = bill.Line[0]
    assert line0.Amount == 1000.00
    assert line0.Description == "Consulting"
    assert line0.DetailType == "AccountBasedExpenseLineDetail"
    detail0 = line0.AccountBasedExpenseLineDetail
    assert detail0.AccountRef.value == "60"
    assert detail0.ClassRef.value == "5000000000000123456"
    assert detail0.CustomerRef.value == "42"

    line1 = bill.Line[1]
    assert line1.Amount == 250.50
    assert line1.AccountBasedExpenseLineDetail.AccountRef.value == "61"
    # Optional refs not provided -> stay None
    assert line1.AccountBasedExpenseLineDetail.ClassRef is None
    assert line1.AccountBasedExpenseLineDetail.CustomerRef is None

    # The result is the dict form of the saved Bill (with Id set by save())
    assert result["Id"] == "9999"


def test_create_bill_minimal_payload(monkeypatch):
    """Only required fields — no APAccountRef, no Description on lines."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.Bill, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "VendorRef": {"value": "123"},
        "TxnDate": "2026-04-30",
        "DueDate": "2026-05-30",
        "DocNumber": "DOC-1",
        "Line": [
            {
                "Amount": 500.00,
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "60"}},
            },
        ],
    }

    _run(svc.create_bill(1, payload))

    bill = sentinel.captured
    assert bill.VendorRef.value == "123"
    assert bill.APAccountRef is None
    assert len(bill.Line) == 1
    assert bill.Line[0].Description is None
    assert bill.Line[0].AccountBasedExpenseLineDetail.AccountRef.value == "60"


# ---------------------------------------------------------------------------
# create_vendor_credit
# ---------------------------------------------------------------------------


def test_create_vendor_credit_builds_payload_with_all_fields(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.VendorCredit, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "VendorRef": {"value": "123", "name": "Acme"},
        "TxnDate": "2026-04-30",
        "DocNumber": "VC-001",
        "PrivateNote": "Refund for overbilling",
        "TotalAmt": 250.00,
        "APAccountRef": {"value": "81"},
        "Line": [
            {
                "Amount": 250.00,
                "Description": "Credit memo",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "60"},
                    "ClassRef": {"value": "5000000000000123456"},
                },
            },
        ],
    }

    result = _run(svc.create_vendor_credit(2, payload))

    vc = sentinel.captured
    assert vc is not None, "VendorCredit.save() was never called"
    assert vc.TxnDate == "2026-04-30"
    assert vc.DocNumber == "VC-001"
    assert vc.PrivateNote == "Refund for overbilling"
    assert vc.TotalAmt == 250.00
    assert vc.VendorRef.value == "123"
    assert vc.APAccountRef.value == "81"

    assert len(vc.Line) == 1
    line = vc.Line[0]
    assert line.Amount == 250.00
    assert line.Description == "Credit memo"
    assert line.DetailType == "AccountBasedExpenseLineDetail"
    detail = line.AccountBasedExpenseLineDetail
    assert detail.AccountRef.value == "60"
    assert detail.ClassRef.value == "5000000000000123456"
    assert detail.CustomerRef is None

    assert result["Id"] == "9999"


def test_create_vendor_credit_omits_optional_ap_account(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.VendorCredit, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "VendorRef": {"value": "123"},
        "TxnDate": "2026-04-30",
        "DocNumber": "VC-002",
        "TotalAmt": 100.00,
        "Line": [
            {
                "Amount": 100.00,
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "60"}},
            },
        ],
    }

    _run(svc.create_vendor_credit(2, payload))

    vc = sentinel.captured
    # APAccountRef isn't set in VendorCredit.__init__, so when omitted it
    # simply doesn't exist on the object (won't be serialized to QBO).
    assert not hasattr(vc, "APAccountRef")
    assert vc.PrivateNote == ""  # default from python-quickbooks model
    assert len(vc.Line) == 1


# ---------------------------------------------------------------------------
# Router wiring (smoke tests — confirm routes exist & require auth)
# ---------------------------------------------------------------------------


def test_create_bill_payment_handles_null_refs(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.BillPayment, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "VendorRef": {"value": "1047"},
        "TxnDate": "2026-05-02",
        "PrivateNote": "Apply VC 91653 to Bill 90458",
        "TotalAmt": 0,
        "PayType": "Check",
        "CheckPayment": {"PrintStatus": "NotSet", "BankAccountRef": None},
        "APAccountRef": None,
        "DepartmentRef": None,
        "CurrencyRef": {"value": "USD"},
        "Line": [
            {"Amount": 95.76, "LinkedTxn": [{"TxnId": "90458", "TxnType": "Bill", "TxnLineId": 0}]},
            {"Amount": 95.76, "LinkedTxn": [{"TxnId": "91653", "TxnType": "VendorCredit", "TxnLineId": 0}]},
        ],
    }

    _run(svc.create_bill_payment(1, payload))

    bp = sentinel.captured
    assert bp is not None, "BillPayment.save() was never called"
    # VendorRef was provided -> populated
    assert bp.VendorRef is not None
    assert bp.VendorRef.value == "1047"
    # Null-valued refs are silently skipped, not crashed on
    assert bp.APAccountRef is None
    assert bp.DepartmentRef is None
    # CheckPayment object is built (PayType=Check + dict present), but its
    # BankAccountRef stays None because the payload sent null.
    assert bp.CheckPayment is not None
    assert bp.CheckPayment.BankAccountRef is None
    assert bp.CheckPayment.PrintStatus == "NotSet"
    assert len(bp.Line) == 2


def test_create_bill_payment_omits_check_payment_when_null(monkeypatch):
    """PayType=Check but the whole CheckPayment block is null -> skip it."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.BillPayment, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "VendorRef": {"value": "1047"},
        "TotalAmt": 0,
        "PayType": "Check",
        "CheckPayment": None,
        "Line": [],
    }

    _run(svc.create_bill_payment(1, payload))

    bp = sentinel.captured
    assert bp.CheckPayment is None


def test_bills_router_has_post_route():
    from app.routers import bills

    methods_paths = {
        (frozenset(r.methods), r.path)
        for r in bills.router.routes
        if hasattr(r, "methods")
    }
    assert (frozenset({"POST"}), "/bills/") in methods_paths


def test_vendor_credits_router_has_post_route():
    from app.routers import vendor_credits

    methods_paths = {
        (frozenset(r.methods), r.path)
        for r in vendor_credits.router.routes
        if hasattr(r, "methods")
    }
    assert (frozenset({"POST"}), "/vendor-credits/") in methods_paths


def test_bills_router_enforces_api_key_dependency():
    from app.dependencies import verify_api_key
    from app.routers import bills

    dep_callables = [d.dependency for d in bills.router.dependencies]
    assert verify_api_key in dep_callables


def test_vendor_credits_router_enforces_api_key_dependency():
    from app.dependencies import verify_api_key
    from app.routers import vendor_credits

    dep_callables = [d.dependency for d in vendor_credits.router.dependencies]
    assert verify_api_key in dep_callables
