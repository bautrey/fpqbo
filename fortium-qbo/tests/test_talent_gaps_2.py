"""Talent gaps round 2: vendor-credit doc_number filter, Vendor1099, QBO refusals as 4xx.

Plan: docs/plans/2026-11-25-talent-gaps-2.md. Every QuickBooks touch point is
stubbed; nothing here reaches the network.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from quickbooks.exceptions import (
    AuthorizationException,
    GeneralException,
    ObjectNotFoundException,
    QuickbooksException,
    SevereException,
    UnsupportedException,
    ValidationException,
)

from app.dependencies import verify_api_key
from app.exceptions import QboUnavailable
from app.routers import vendor_credits
from app.routers._qbo_write import run_qbo_write
from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService
from app.utils.paging import PagedResult


def _service(monkeypatch):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    client = SimpleNamespace(api_url="https://qbo.test/v3", company_id="r1")
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1", code="X"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: client)
    return svc


# ---------------------------------------------------------------------------
# 1. doc_number filter on the vendor-credit list
# ---------------------------------------------------------------------------


def _capture_clause(monkeypatch, svc):
    seen = {}

    async def _page(entity, *, client, clause, offset, limit, op):
        seen["clause"] = clause
        return PagedResult(rows=[], offset=offset, total=0, has_more=False)

    monkeypatch.setattr(svc, "_fetch_page", _page)
    return seen


def test_doc_number_clause_is_built_escaped(monkeypatch):
    svc = _service(monkeypatch)
    seen = _capture_clause(monkeypatch, svc)
    asyncio.run(svc.get_vendor_credits(1, doc_number="VC-O'Brien"))
    assert seen["clause"] == "DocNumber = 'VC-O\\'Brien'"


def test_no_doc_number_leaves_the_clause_unchanged(monkeypatch):
    svc = _service(monkeypatch)
    seen = _capture_clause(monkeypatch, svc)
    asyncio.run(svc.get_vendor_credits(1))
    assert seen["clause"] is None


def _vc_client(fake):
    app = FastAPI()
    app.include_router(vendor_credits.router, prefix="/api")
    app.dependency_overrides[vendor_credits._get_service] = lambda: fake
    app.dependency_overrides[verify_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("blank", ["", " ", "   "])
def test_blank_doc_number_is_400_with_no_qbo_call(blank):
    called = []

    async def _get(**kw):
        called.append(kw)
        return PagedResult(rows=[], offset=0, total=0, has_more=False)

    client = _vc_client(SimpleNamespace(get_vendor_credits=_get))
    resp = client.get("/api/vendor-credits/", params={"company_id": 1, "doc_number": blank})
    assert resp.status_code == 400
    assert called == []


def test_doc_number_reaches_the_service_stripped_of_nothing_else():
    seen = {}

    async def _get(**kw):
        seen.update(kw)
        return PagedResult(rows=[{"Id": "1"}], offset=0, total=1, has_more=False)

    client = _vc_client(SimpleNamespace(get_vendor_credits=_get))
    resp = client.get("/api/vendor-credits/", params={"company_id": 1, "doc_number": "VC-1"})
    assert resp.status_code == 200
    assert seen["doc_number"] == "VC-1"
    assert "X-Total-Count" in resp.headers


def test_openapi_lists_doc_number():
    client = _vc_client(SimpleNamespace())
    params = client.get("/openapi.json").json()["paths"]["/api/vendor-credits/"]["get"]["parameters"]
    assert "doc_number" in [p["name"] for p in params]


# ---------------------------------------------------------------------------
# 2. Vendor1099 passthrough
# ---------------------------------------------------------------------------


def _create_vendor_saved(monkeypatch, body):
    svc = _service(monkeypatch)
    seen = {}

    def _save(self, qb=None, request_id=None):
        seen["vendor"] = self
        self.Id = "77"
        return self

    monkeypatch.setattr(qbo_service_module.Vendor, "save", _save, raising=True)
    asyncio.run(svc.create_vendor(1, body))
    return seen["vendor"]


def test_vendor1099_true_reaches_the_saved_object(monkeypatch):
    vnd = _create_vendor_saved(monkeypatch, {"DisplayName": "Jane", "Vendor1099": True})
    assert vnd.Vendor1099 is True


def test_vendor1099_absent_keeps_the_sdk_default(monkeypatch):
    vnd = _create_vendor_saved(monkeypatch, {"DisplayName": "Jane"})
    assert vnd.Vendor1099 is qbo_service_module.Vendor().Vendor1099


# ---------------------------------------------------------------------------
# 3. QBO refusals on write routes are 4xx
# ---------------------------------------------------------------------------


def _write(exc):
    async def _raise():
        raise exc

    with pytest.raises(HTTPException) as caught:
        asyncio.run(run_qbo_write(_raise(), entity="vendor"))
    return caught.value


@pytest.mark.parametrize(
    "exc, status",
    [
        (QuickbooksException("Duplicate name", 6240, "dup detail"), 400),
        (QuickbooksException("Stale", 5010, "stale detail"), 409),
        (ValidationException("Bad field", 2020, "field detail"), 400),
        (ValidationException("Throttled", 3001, "throttle detail"), 503),
    ],
    ids=["6240-400", "5010-409", "validation-400", "3001-503"],
)
def test_qbo_refusals_map_to_the_callers_4xx(exc, status):
    err = _write(exc)
    assert err.status_code == status


def test_refusal_text_is_preserved_after_the_prefix():
    err = _write(QuickbooksException("Duplicate name", 6240, "dup detail"))
    assert err.status_code == 400
    assert err.detail.startswith("QBO refused: ")
    assert "6240" in err.detail
    assert "dup detail" in err.detail


def test_throttle_is_a_qbo_unavailable_503():
    err = _write(ValidationException("Throttled", 3001, "throttle detail"))
    assert isinstance(err, QboUnavailable)


@pytest.mark.parametrize(
    "exc",
    [
        AuthorizationException("auth", 120, "d"),
        SevereException("severe", 10000, "d"),
        UnsupportedException("unsupported", 500, "d"),
        GeneralException("general", 700, "d"),
        ObjectNotFoundException("missing", 610, "d"),
    ],
    ids=["auth", "severe", "unsupported", "general", "notfound"],
)
def test_other_sdk_subclasses_keep_the_500(exc):
    err = _write(exc)
    assert err.status_code == 500
    assert err.detail.startswith("QBO API error: ")


@pytest.mark.parametrize(
    "exc",
    [
        # client.py raises the BARE class with 10000 when QBO's answer was an
        # HTTP error or unreadable JSON: no Fault was read, so the write may
        # have booked. Answering 400 "refused" would invite a double post.
        QuickbooksException("Error returned with status code '502': ...", 10000),
        QuickbooksException("Error reading json response: <html>", 10000),
        # SDK-local errors carry the default code 0 and never reached QBO's rules.
        QuickbooksException("No session manager"),
    ],
    ids=["http-error-10000", "bad-json-10000", "local-code-0"],
)
def test_a_bare_exception_that_is_not_a_qbo_fault_keeps_the_500(exc):
    err = _write(exc)
    assert err.status_code == 500
    assert err.detail.startswith("QBO API error: ")
