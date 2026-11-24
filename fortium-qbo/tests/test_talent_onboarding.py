"""Talent onboarding endpoints: lookup, idempotent creates, activate/deactivate.

Plan: docs/plans/2026-11-24-talent-onboarding-endpoints.md. Every QuickBooks
touch point is stubbed; nothing here reaches the network.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quickbooks.exceptions import ObjectNotFoundException

from app.dependencies import verify_api_key
from app.exceptions import QboNotFound
from app.routers import accounts, vendor_credits, vendors
from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService, _active_clause
from app.utils.paging import PagedResult


def _service(monkeypatch):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    client = SimpleNamespace(api_url="https://qbo.test/v3", company_id="r1")
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1", code="X"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: client)
    return svc, client


# ---------------------------------------------------------------------------
# 0. active_only=false has to name Active, or QBO hides inactive rows
# ---------------------------------------------------------------------------


def test_active_clause_false_names_active_so_inactive_rows_come_back():
    assert _active_clause(False) == "Active IN (true, false)"


# ---------------------------------------------------------------------------
# 1. Lookup
# ---------------------------------------------------------------------------


def _vendor(vid, name, email=None, active=True):
    row = {"Id": vid, "DisplayName": name, "Active": active}
    if email is not None:
        row["PrimaryEmailAddr"] = {"Address": email}
    return row


def test_vendor_lookup_by_display_name_builds_escaped_exact_clause(monkeypatch):
    svc, _ = _service(monkeypatch)
    seen = {}

    async def _walk(entity, *, client, clause, op, **kw):
        seen["clause"] = clause
        return PagedResult(rows=[_vendor("1", "O'Brien", active=False)], offset=0, total=1, has_more=False)

    monkeypatch.setattr(svc, "_fetch_all_pages", _walk)
    rows = asyncio.run(svc.lookup_vendors(1, display_name="O'Brien"))

    assert seen["clause"] == "DisplayName = 'O\\'Brien' AND Active IN (true, false)"
    assert [r["Id"] for r in rows] == ["1"]


def test_vendor_lookup_by_email_matches_case_insensitively_across_pages_and_includes_inactive(monkeypatch):
    svc, _ = _service(monkeypatch)
    monkeypatch.setattr(qbo_service_module, "QBO_MAX_PAGE_SIZE", 2)
    pages = {
        0: [_vendor("1", "A", "a@x.com"), _vendor("2", "B", "b@x.com")],
        2: [_vendor("3", "C", "  Jane@Example.COM ", active=False), _vendor("4", "D")],
        4: [_vendor("5", "E", "jane@example.com")],
    }
    clauses = []

    async def _page(entity, *, client, clause, offset, limit, op):
        clauses.append(clause)
        return pages[offset]

    monkeypatch.setattr(svc, "_query_page", _page)
    rows = asyncio.run(svc.lookup_vendors(1, email=" JANE@example.com"))

    assert [r["Id"] for r in rows] == ["3", "5"]
    assert set(clauses) == {"Active IN (true, false)"}


def test_vendor_lookup_with_both_params_requires_both_to_match(monkeypatch):
    svc, _ = _service(monkeypatch)

    async def _walk(entity, *, client, clause, op, **kw):
        return PagedResult(
            rows=[_vendor("1", "Jane", "jane@x.com"), _vendor("2", "Jane", "other@x.com")],
            offset=0, total=2, has_more=False,
        )

    monkeypatch.setattr(svc, "_fetch_all_pages", _walk)
    rows = asyncio.run(svc.lookup_vendors(1, display_name="Jane", email="jane@x.com"))
    assert [r["Id"] for r in rows] == ["1"]


def test_vendor_lookup_truncated_walk_is_503_not_no_match(monkeypatch):
    svc, _ = _service(monkeypatch)

    async def _walk(entity, *, client, clause, op, **kw):
        return PagedResult(rows=[_vendor("1", "A", "a@x.com")], offset=0, total=None, has_more=True)

    monkeypatch.setattr(svc, "_fetch_all_pages", _walk)
    with pytest.raises(Exception) as err:
        asyncio.run(svc.lookup_vendors(1, email="nobody@x.com"))
    assert err.value.status_code == 503


def test_account_lookup_by_name_returns_every_match_with_exact_escaped_clause(monkeypatch):
    svc, _ = _service(monkeypatch)
    seen = {}
    matches = [
        {"Id": "10", "Name": "Rev's", "FullyQualifiedName": "A:Rev's", "ParentRef": {"value": "1"}},
        {"Id": "11", "Name": "Rev's", "FullyQualifiedName": "B:Rev's", "ParentRef": {"value": "2"}},
    ]

    async def _walk(entity, *, client, clause, op, **kw):
        seen["clause"] = clause
        return PagedResult(rows=matches, offset=0, total=2, has_more=False)

    monkeypatch.setattr(svc, "_fetch_all_pages", _walk)
    rows = asyncio.run(svc.lookup_accounts(1, name="Rev's"))

    assert seen["clause"] == "Name = 'Rev\\'s' AND Active IN (true, false)"
    assert rows == matches


def _lookup_client(fake):
    app = FastAPI()
    app.include_router(vendors.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[vendors._get_service] = lambda: fake
    app.dependency_overrides[accounts._get_service] = lambda: fake
    return TestClient(app, raise_server_exceptions=False)


def test_vendor_lookup_with_neither_param_is_400():
    called = []

    async def _lookup(*a, **k):
        called.append(1)
        return []

    client = _lookup_client(SimpleNamespace(lookup_vendors=_lookup))
    resp = client.get("/api/vendors/lookup?company_id=1")
    assert resp.status_code == 400
    assert called == []


@pytest.mark.parametrize("query", [
    "email=", "email=%20%20", "display_name=", "display_name=%20",
    "email=&display_name=", "display_name=%20&email=a%40b.com",
])
def test_vendor_lookup_with_a_blank_value_is_400(query):
    """A blank email would match every vendor that has no email, telling the
    caller a vendor exists when it does not."""
    called = []

    async def _lookup(*a, **k):
        called.append(1)
        return []

    client = _lookup_client(SimpleNamespace(lookup_vendors=_lookup))
    assert client.get(f"/api/vendors/lookup?company_id=1&{query}").status_code == 400
    assert called == []


@pytest.mark.parametrize("query", ["name=", "name=%20"])
def test_account_lookup_with_a_blank_name_is_400(query):
    called = []

    async def _lookup(*a, **k):
        called.append(1)
        return []

    client = _lookup_client(SimpleNamespace(lookup_accounts=_lookup))
    assert client.get(f"/api/accounts/lookup?company_id=1&{query}").status_code == 400
    assert called == []


def test_lookup_route_is_not_swallowed_by_the_id_route():
    async def _lookup_v(company_id, display_name=None, email=None):
        return [{"Id": "9", "DisplayName": display_name}]

    async def _lookup_a(company_id, name):
        return [{"Id": "8", "Name": name}]

    async def _by_id(*a, **k):
        raise AssertionError("/lookup was routed to /{id}")

    fake = SimpleNamespace(
        lookup_vendors=_lookup_v, lookup_accounts=_lookup_a,
        get_vendor_by_id=_by_id, get_account_by_id=_by_id,
    )
    client = _lookup_client(fake)

    resp = client.get("/api/vendors/lookup?company_id=1&display_name=Jane")
    assert resp.status_code == 200
    assert resp.json() == [{"Id": "9", "DisplayName": "Jane"}]

    resp = client.get("/api/accounts/lookup?company_id=1&name=Fees")
    assert resp.status_code == 200
    assert resp.json() == [{"Id": "8", "Name": "Fees"}]


def test_lookup_is_declared_before_the_id_route():
    from app.main import app

    def _index(path):
        return next(
            i for i, r in enumerate(app.routes)
            if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", ())
        )

    assert _index("/api/vendors/lookup") < _index("/api/vendors/{vendor_id}")
    assert _index("/api/accounts/lookup") < _index("/api/accounts/{account_id}")


# ---------------------------------------------------------------------------
# 2. Request-Id on creates
# ---------------------------------------------------------------------------

_CREATES = [
    ("create_vendor", "Vendor", {"DisplayName": "Jane"}),
    ("create_account", "Account", {"Name": "Fees", "AccountType": "Income"}),
    ("create_vendor_credit", "VendorCredit", {"VendorRef": {"value": "1"}, "Line": []}),
]


@pytest.mark.parametrize("method, entity, body", _CREATES)
def test_request_id_reaches_save(monkeypatch, method, entity, body):
    svc, _ = _service(monkeypatch)
    seen = {}

    def _save(self, qb=None, request_id=None):
        seen["request_id"] = request_id
        self.Id = "77"
        return self

    monkeypatch.setattr(getattr(qbo_service_module, entity), "save", _save, raising=True)
    asyncio.run(getattr(svc, method)(1, body, request_id="onboard-123_A"))
    assert seen["request_id"] == "onboard-123_A"


@pytest.mark.parametrize("method, entity, body", _CREATES)
def test_no_request_id_means_save_gets_none(monkeypatch, method, entity, body):
    svc, _ = _service(monkeypatch)
    seen = {}

    def _save(self, qb=None, request_id="unset"):
        seen["request_id"] = request_id
        self.Id = "77"
        return self

    monkeypatch.setattr(getattr(qbo_service_module, entity), "save", _save, raising=True)
    asyncio.run(getattr(svc, method)(1, body))
    assert seen["request_id"] is None


def _write_client(fake):
    app = FastAPI()
    for r in (vendors, accounts, vendor_credits):
        app.include_router(r.router, prefix="/api")
        app.dependency_overrides[r._get_service] = lambda: fake
    app.dependency_overrides[verify_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


_CREATE_ROUTES = [
    ("/api/vendors/", "create_vendor", {"DisplayName": "Jane"}),
    ("/api/accounts/", "create_account", {"Name": "Fees", "AccountType": "Income"}),
    ("/api/vendor-credits/", "create_vendor_credit", {"VendorRef": {"value": "1"}}),
]


@pytest.mark.parametrize("path, method, body", _CREATE_ROUTES)
def test_create_routes_forward_a_valid_request_id(path, method, body):
    seen = {}

    async def _create(company_id, data, request_id=None):
        seen["request_id"] = request_id
        return {"Id": "1"}

    client = _write_client(SimpleNamespace(**{method: _create}))
    resp = client.post(f"{path}?company_id=1", json=body, headers={"Request-Id": "abc-123_X"})
    assert resp.status_code == 201
    assert seen["request_id"] == "abc-123_X"


@pytest.mark.parametrize("path, method, body", _CREATE_ROUTES)
def test_create_routes_without_header_pass_none(path, method, body):
    seen = {}

    async def _create(company_id, data, request_id=None):
        seen["request_id"] = request_id
        return {"Id": "1"}

    client = _write_client(SimpleNamespace(**{method: _create}))
    assert client.post(f"{path}?company_id=1", json=body).status_code == 201
    assert seen["request_id"] is None


@pytest.mark.parametrize("bad", ["", "a" * 51, "has space", "semi;colon", "a/b"])
@pytest.mark.parametrize("path, method, body", _CREATE_ROUTES)
def test_invalid_request_id_is_400_with_no_qbo_call(path, method, body, bad):
    called = []

    async def _create(*a, **k):
        called.append(1)
        return {"Id": "1"}

    client = _write_client(SimpleNamespace(**{method: _create}))
    resp = client.post(f"{path}?company_id=1", json=body, headers={"Request-Id": bad})
    assert resp.status_code == 400
    assert called == []


def test_a_50_character_request_id_is_accepted():
    async def _create(company_id, data, request_id=None):
        return {"Id": "1"}

    client = _write_client(SimpleNamespace(create_vendor=_create))
    resp = client.post(
        "/api/vendors/?company_id=1", json={"DisplayName": "J"}, headers={"Request-Id": "a" * 50}
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 3. Activate / deactivate
# ---------------------------------------------------------------------------

_ACTIVATE = [
    ("set_vendor_active", "Vendor", "vendor"),
    ("set_account_active", "Account", "account"),
]


def _stub_get(monkeypatch, entity, record):
    seen = {"ids": []}

    def _get(cls, entity_id, qb=None):
        seen["ids"].append(entity_id)
        if record is None:
            raise ObjectNotFoundException("not found", error_code=610)
        return record

    monkeypatch.setattr(getattr(qbo_service_module, entity), "get", classmethod(_get), raising=True)
    return seen


def _record(entity, active):
    obj = getattr(qbo_service_module, entity)()
    obj.Id = "42"
    obj.SyncToken = "3"
    obj.Active = active
    return obj


@pytest.mark.parametrize("method, entity, url_tail", _ACTIVATE)
@pytest.mark.parametrize("target", [True, False])
def test_set_active_sends_sparse_body_and_returns_updated_entity(monkeypatch, method, entity, url_tail, target):
    svc, client = _service(monkeypatch)
    _stub_get(monkeypatch, entity, _record(entity, not target))
    posts = []

    def _post(url, body, params=None, request_id=None, **kw):
        posts.append((url, json.loads(body), params, request_id))
        return {entity: {"Id": "42", "SyncToken": "4", "Active": target}}

    client.post = _post
    result = asyncio.run(getattr(svc, method)(1, 42, target))

    assert len(posts) == 1
    url, body, params, rid = posts[0]
    assert url == f"https://qbo.test/v3/company/r1/{url_tail}"
    assert body == {"Id": "42", "SyncToken": "3", "sparse": True, "Active": target}
    assert params == {"operation": "update"}
    # No requestid: QBO replays the first result for a repeated id, so a
    # deactivate then activate under one id would silently do nothing.
    assert rid is None
    assert result["Active"] is target
    assert result["SyncToken"] == "4"


@pytest.mark.parametrize("method, entity, url_tail", _ACTIVATE)
@pytest.mark.parametrize("target", [True, False])
def test_set_active_already_in_state_makes_no_write(monkeypatch, method, entity, url_tail, target):
    svc, client = _service(monkeypatch)
    _stub_get(monkeypatch, entity, _record(entity, target))

    def _post(*a, **k):
        raise AssertionError("wrote when the record was already in the requested state")

    client.post = _post
    result = asyncio.run(getattr(svc, method)(1, 42, target))
    assert result["Id"] == "42"
    assert result["Active"] is target


@pytest.mark.parametrize("method, entity, url_tail", _ACTIVATE)
@pytest.mark.parametrize("exc_name, code, status", [
    # The SDK's own mapping (quickbooks/client.py handle_exceptions): 2000-4999
    # become ValidationException, 5000-9999 fall through to the bare class.
    ("QuickbooksException", 5010, 409),   # stale SyncToken
    ("QuickbooksException", 6240, 400),   # duplicate name on reactivate
    ("ValidationException", 2050, 400),
])
def test_set_active_maps_quickbooks_refusals(monkeypatch, method, entity, url_tail, exc_name, code, status):
    """A stale SyncToken is a conflict the caller can retry; any other QBO
    refusal of the update is the caller's 400. Neither is a server failure."""
    from fastapi import HTTPException
    from quickbooks import exceptions as qb_exc

    svc, client = _service(monkeypatch)
    _stub_get(monkeypatch, entity, _record(entity, True))

    def _post(*a, **k):
        raise getattr(qb_exc, exc_name)("refused", error_code=code, detail="QBO says no")

    client.post = _post
    with pytest.raises(HTTPException) as exc:
        asyncio.run(getattr(svc, method)(1, 42, False))
    assert exc.value.status_code == status
    assert "QBO says no" in exc.value.detail


@pytest.mark.parametrize("method, entity, url_tail", _ACTIVATE)
def test_set_active_does_not_turn_a_server_fault_into_a_400(monkeypatch, method, entity, url_tail):
    from quickbooks.exceptions import SevereException

    svc, client = _service(monkeypatch)
    _stub_get(monkeypatch, entity, _record(entity, True))

    def _post(*a, **k):
        raise SevereException("boom", error_code=10000)

    client.post = _post
    with pytest.raises(SevereException):
        asyncio.run(getattr(svc, method)(1, 42, False))


@pytest.mark.parametrize("method, entity, url_tail", _ACTIVATE)
def test_set_active_missing_record_is_404(monkeypatch, method, entity, url_tail):
    svc, client = _service(monkeypatch)
    _stub_get(monkeypatch, entity, None)
    client.post = lambda *a, **k: pytest.fail("wrote for a missing record")
    with pytest.raises(QboNotFound):
        asyncio.run(getattr(svc, method)(1, 42, True))


_ACTIVATE_ROUTES = [
    ("/api/vendors/7/activate", "set_vendor_active", True),
    ("/api/vendors/7/deactivate", "set_vendor_active", False),
    ("/api/accounts/7/activate", "set_account_active", True),
    ("/api/accounts/7/deactivate", "set_account_active", False),
]


@pytest.mark.parametrize("path, method, target", _ACTIVATE_ROUTES)
def test_activate_routes_call_service_with_state(path, method, target):
    seen = {}

    async def _set(company_id, entity_id, active):
        seen.update(company_id=company_id, entity_id=entity_id, active=active)
        return {"Id": "7", "Active": active}

    client = _write_client(SimpleNamespace(**{method: _set}))
    resp = client.post(f"{path}?company_id=3")
    assert resp.status_code == 200
    assert resp.json() == {"Id": "7", "Active": target}
    assert seen == {"company_id": 3, "entity_id": 7, "active": target}


@pytest.mark.parametrize("path, method, target", _ACTIVATE_ROUTES)
def test_activate_routes_missing_record_is_404(path, method, target):
    async def _set(*a, **k):
        raise QboNotFound("Vendor 7 not found")

    client = _write_client(SimpleNamespace(**{method: _set}))
    assert client.post(f"{path}?company_id=3").status_code == 404


@pytest.mark.parametrize("path, method, target", _ACTIVATE_ROUTES)
def test_a_read_only_key_is_refused_by_the_existing_write_gate(path, method, target):
    """The gate is verb-based, so these routes are covered by being POST."""
    from app.database import get_db

    key = SimpleNamespace(id=1, company_id=3, is_active=True, can_write=False, last_used_at=None)

    class _DB:
        def execute(self, *a, **k):
            return SimpleNamespace(scalar_one_or_none=lambda: key)

        def commit(self):
            pass

    app = FastAPI()
    app.include_router(vendors.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: _DB()
    resp = TestClient(app, raise_server_exceptions=False).post(
        f"{path}?company_id=3", headers={"X-API-Key": "fqbo_x"}
    )
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"].lower()
