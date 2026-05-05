"""Tests for the JournalEntry create and void service methods."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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

    def __call__(self, obj):
        self.captured = obj
        obj.Id = "9999"
        return obj


# ---------------------------------------------------------------------------
# create_journal_entry
# ---------------------------------------------------------------------------


def test_create_journal_entry_builds_payload_with_all_fields(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.JournalEntry, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "DocNumber": "WH2025",
        "TxnDate": "2026-04-01",
        "PrivateNote": "2025 State Tax Allocation - Withholding Applied",
        "Adjustment": False,
        "CurrencyRef": {"value": "USD"},
        "Line": [
            {
                "Amount": 596114.06,
                "DetailType": "JournalEntryLineDetail",
                "Description": "WH credit aggregate",
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": "572", "name": "Withholding"},
                },
            },
            {
                "Amount": 1275.15,
                "DetailType": "JournalEntryLineDetail",
                "Description": "Partner WH debit",
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "619"},
                    "ClassRef": {"value": "5000000000000000123"},
                    "Entity": {
                        "Type": "Vendor",
                        "EntityRef": {"value": "460", "name": "Partner Doe"},
                    },
                },
            },
        ],
    }

    result = _run(svc.create_journal_entry(1, payload))

    je = sentinel.captured
    assert je is not None, "JournalEntry.save() was never called"
    assert je.DocNumber == "WH2025"
    assert je.TxnDate == "2026-04-01"
    assert je.PrivateNote == "2025 State Tax Allocation - Withholding Applied"
    assert je.Adjustment is False
    assert je.CurrencyRef.value == "USD"

    assert len(je.Line) == 2

    line0 = je.Line[0]
    assert line0.Amount == 596114.06
    assert line0.Description == "WH credit aggregate"
    assert line0.DetailType == "JournalEntryLineDetail"
    detail0 = line0.JournalEntryLineDetail
    assert detail0.PostingType == "Credit"
    assert detail0.AccountRef.value == "572"
    assert detail0.AccountRef.name == "Withholding"
    assert detail0.Entity is None

    line1 = je.Line[1]
    assert line1.Amount == 1275.15
    detail1 = line1.JournalEntryLineDetail
    assert detail1.PostingType == "Debit"
    assert detail1.AccountRef.value == "619"
    assert detail1.ClassRef.value == "5000000000000000123"
    # The Entity field is the canonical QBO nested shape:
    # Entity.Type + Entity.EntityRef (a Ref).
    assert detail1.Entity is not None
    assert detail1.Entity.Type == "Vendor"
    assert detail1.Entity.EntityRef.value == "460"
    assert detail1.Entity.EntityRef.name == "Partner Doe"

    assert result["Id"] == "9999"


def test_create_journal_entry_minimal_payload(monkeypatch):
    """Only required fields — bare Line[] with AccountRef and PostingType."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.JournalEntry, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "Line": [
            {
                "Amount": 100.00,
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "60"},
                },
            },
            {
                "Amount": 100.00,
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": "61"},
                },
            },
        ],
    }

    _run(svc.create_journal_entry(1, payload))

    je = sentinel.captured
    assert je is not None
    # Defaults from python-quickbooks model
    assert je.DocNumber == ""
    assert je.PrivateNote == ""
    assert je.CurrencyRef is None
    assert len(je.Line) == 2
    assert je.Line[0].Description is None
    assert je.Line[0].JournalEntryLineDetail.AccountRef.value == "60"
    assert je.Line[1].JournalEntryLineDetail.AccountRef.value == "61"


def test_create_journal_entry_handles_credit_and_debit_lines(monkeypatch):
    """PostingType must be set per-line for both Credit and Debit lines."""
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.JournalEntry, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "DocNumber": "TEST-CD",
        "Line": [
            {
                "Amount": 50.00,
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": "100"},
                },
            },
            {
                "Amount": 25.00,
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "200"},
                },
            },
            {
                "Amount": 25.00,
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "300"},
                },
            },
        ],
    }

    _run(svc.create_journal_entry(1, payload))

    je = sentinel.captured
    posting_types = [ln.JournalEntryLineDetail.PostingType for ln in je.Line]
    account_values = [ln.JournalEntryLineDetail.AccountRef.value for ln in je.Line]
    assert posting_types == ["Credit", "Debit", "Debit"]
    assert account_values == ["100", "200", "300"]


def test_create_journal_entry_handles_null_refs(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    sentinel = _Sentinel()
    monkeypatch.setattr(
        qbo_service_module.JournalEntry, "save",
        lambda self, qb=None: sentinel(self),
        raising=True,
    )

    payload = {
        "DocNumber": "JE-NULL",
        "CurrencyRef": None,
        "Line": [
            {
                "Amount": 10.00,
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "60"},
                    "ClassRef": None,
                    "DepartmentRef": None,
                    "TaxCodeRef": None,
                    "Entity": None,
                },
            },
        ],
    }

    _run(svc.create_journal_entry(1, payload))

    je = sentinel.captured
    assert je.CurrencyRef is None
    detail = je.Line[0].JournalEntryLineDetail
    assert detail.AccountRef.value == "60"
    assert detail.ClassRef is None
    assert detail.DepartmentRef is None
    assert detail.TaxCodeRef is None
    assert detail.Entity is None


# ---------------------------------------------------------------------------
# void_journal_entry
# ---------------------------------------------------------------------------


def test_void_journal_entry_success(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))

    captured = {}

    def _fake_post(url, data, params=None):
        captured["url"] = url
        captured["data"] = data
        captured["params"] = params
        return {"JournalEntry": {"Id": "78862", "SyncToken": "1", "void": True}}

    fake_client = SimpleNamespace(
        api_url="https://quickbooks.api.intuit.com/v3",
        company_id="9130000000000",
        post=_fake_post,
    )
    monkeypatch.setattr(svc, "_get_client", lambda _co: fake_client)

    fake_je = SimpleNamespace(Id="78862", SyncToken="0")
    monkeypatch.setattr(
        qbo_service_module.JournalEntry, "get",
        classmethod(lambda cls, _id, qb=None: fake_je),
        raising=True,
    )

    result = _run(svc.void_journal_entry(1, 78862))

    assert captured["url"] == "https://quickbooks.api.intuit.com/v3/company/9130000000000/journalentry"
    assert captured["params"] == {"operation": "update", "include": "void"}
    import json
    body = json.loads(captured["data"])
    assert body["Id"] == "78862"
    assert body["SyncToken"] == "0"
    assert body["sparse"] is True
    # Result is the JournalEntry rebuilt from the response, dict-form
    assert result["Id"] == "78862"


def test_void_journal_entry_not_found(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())

    monkeypatch.setattr(
        qbo_service_module.JournalEntry, "get",
        classmethod(lambda cls, _id, qb=None: None),
        raising=True,
    )

    with pytest.raises(ValueError, match="JournalEntry 555 not found"):
        _run(svc.void_journal_entry(1, 555))


# ---------------------------------------------------------------------------
# Router wiring (smoke tests — confirm routes exist & require auth)
# ---------------------------------------------------------------------------


def test_journal_entries_router_has_post_route():
    from app.routers import journal_entries

    methods_paths = {
        (frozenset(r.methods), r.path)
        for r in journal_entries.router.routes
        if hasattr(r, "methods")
    }
    assert (frozenset({"POST"}), "/journal-entries/") in methods_paths


def test_journal_entries_router_has_void_route():
    from app.routers import journal_entries

    methods_paths = {
        (frozenset(r.methods), r.path)
        for r in journal_entries.router.routes
        if hasattr(r, "methods")
    }
    assert (frozenset({"POST"}), "/journal-entries/{entity_id}/void") in methods_paths


def test_journal_entries_router_post_enforces_api_key_dependency():
    from app.dependencies import verify_api_key
    from app.routers import journal_entries

    dep_callables = [d.dependency for d in journal_entries.router.dependencies]
    assert verify_api_key in dep_callables


def test_journal_entries_router_void_enforces_api_key_dependency():
    from app.dependencies import verify_api_key
    from app.routers import journal_entries

    dep_callables = [d.dependency for d in journal_entries.router.dependencies]
    assert verify_api_key in dep_callables
