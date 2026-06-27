"""Tests for per-company API-key scoping in verify_api_key.

An API key is bound to one company; it must not read or write another company
by passing a different ``company_id`` (prevents cross-company / prod<->sandbox
access).

The important cases are the *integration* tests: they drive ``verify_api_key``
through the real FastAPI/pydantic query coercion and assert the crafted bypass
vectors (" 2", "+2", "2\\n", ...) cannot reach a foreign company. A previous
fix gated on ``str.isdigit()`` — stricter than pydantic's int coercion — so
those vectors skipped the check yet still resolved the target company; unit
tests that passed clean strings missed it entirely.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies.api_auth import verify_api_key


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    """Returns the given ApiKey for any query; no-op commit."""

    def __init__(self, api_key):
        self._api_key = api_key

    def execute(self, *a, **k):
        return _FakeResult(self._api_key)

    def commit(self):
        pass


def _make_key(company_id: int = 1):
    return SimpleNamespace(
        id=1, company_id=company_id, is_active=True, last_used_at=None
    )


# ---------------------------------------------------------------------------
# Unit tests — the comparison logic (company_id already coerced to int)
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


class _FakeRequest:
    def __init__(self):
        self.state = SimpleNamespace()


def test_unit_allows_matching_company():
    key = _make_key(company_id=1)
    result = _run(
        verify_api_key(_FakeRequest(), x_api_key="fqbo_x", company_id=1, db=_FakeDB(key))
    )
    assert result is key


def test_unit_blocks_mismatched_company():
    key = _make_key(company_id=1)
    with pytest.raises(HTTPException) as exc:
        _run(
            verify_api_key(
                _FakeRequest(), x_api_key="fqbo_x", company_id=5, db=_FakeDB(key)
            )
        )
    assert exc.value.status_code == 403


def test_unit_allows_when_no_company_id():
    key = _make_key(company_id=1)
    result = _run(
        verify_api_key(_FakeRequest(), x_api_key="fqbo_x", company_id=None, db=_FakeDB(key))
    )
    assert result is key


def test_unit_missing_api_key_header_401():
    key = _make_key(company_id=1)
    with pytest.raises(HTTPException) as exc:
        _run(
            verify_api_key(
                _FakeRequest(), x_api_key=None, company_id=1, db=_FakeDB(key)
            )
        )
    assert exc.value.status_code == 401


def test_unit_invalid_api_key_401():
    with pytest.raises(HTTPException) as exc:
        _run(
            verify_api_key(
                _FakeRequest(), x_api_key="fqbo_bad", company_id=1, db=_FakeDB(None)
            )
        )
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Integration tests — real FastAPI coercion (the bypass-resistant part)
# ---------------------------------------------------------------------------


def _client(key_company_id: int = 1) -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def probe(company_id: int = Query(...), key=Depends(verify_api_key)):
        # Reaching here means scoping allowed the call through.
        return {"company_id": company_id, "key_company": key.company_id}

    def _override_db():
        yield _FakeDB(_make_key(company_id=key_company_id))

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


_HEADERS = {"X-API-Key": "fqbo_test"}


def test_integration_matching_company_allowed():
    r = _client(key_company_id=1).get("/probe", params={"company_id": "1"}, headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["company_id"] == 1


def test_integration_clean_cross_company_blocked():
    r = _client(key_company_id=1).get("/probe", params={"company_id": "5"}, headers=_HEADERS)
    assert r.status_code == 403


# The exact vectors the reviewers reproduced as bypasses under isdigit(). Each
# must NOT reach the foreign company: either 403 (coerced to the int and blocked)
# or 422 (rejected by coercion) — never 200.
@pytest.mark.parametrize(
    "raw",
    [" 2", "2 ", "+2", "2\n", "\t2", " 5 ", "+5"],
)
def test_integration_crafted_company_id_cannot_bypass(raw):
    r = _client(key_company_id=1).get("/probe", params={"company_id": raw}, headers=_HEADERS)
    assert r.status_code != 200, (
        f"company_id={raw!r} reached a foreign company (status 200) — IDOR bypass!"
    )
    assert r.status_code in (403, 422), f"unexpected status {r.status_code} for {raw!r}"


def test_integration_non_integer_rejected():
    r = _client(key_company_id=1).get("/probe", params={"company_id": "abc"}, headers=_HEADERS)
    assert r.status_code == 422


def test_integration_missing_api_key_401():
    r = _client(key_company_id=1).get("/probe", params={"company_id": "1"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Regression guard — keep the scoping convention enforceable as routes are added
# ---------------------------------------------------------------------------
#
# The company-scoping check lives in verify_api_key and reads company_id from
# the *query* param. Two invariants must hold for every api-key data endpoint,
# or a future route could silently escape scoping:
#   1. it actually depends on verify_api_key, and
#   2. it selects the company via the query param (never a path param, which the
#      scoping check does not read).
# Admin OAuth-management routes (/api/qbo/*) are session-authed, not api-key
# scoped, and are intentionally allowed to manage any company — excluded here.


def _uses_verify_api_key(dependant) -> bool:
    if dependant is None:
        return False
    if getattr(dependant, "call", None) is verify_api_key:
        return True
    return any(_uses_verify_api_key(d) for d in getattr(dependant, "dependencies", []))


def _load_app(monkeypatch):
    """Import the full app, resolving app.main's CWD-relative StaticFiles mount.

    ``app.main`` mounts ``StaticFiles(directory="static")`` relative to the CWD
    (fine under the Docker WORKDIR /app, but not pytest's CWD). chdir to the
    package dir so the import works wherever pytest runs from.
    """
    import os

    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.chdir(pkg_dir)
    from app.main import app

    return app


def test_every_api_key_data_route_is_company_scoped(monkeypatch):
    app = _load_app(monkeypatch)

    data_routes = [
        r
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/")
        and not r.path.startswith("/api/qbo/")
    ]
    assert data_routes, "expected /api/* data routes"

    for r in data_routes:
        assert _uses_verify_api_key(getattr(r, "dependant", None)), (
            f"{sorted(r.methods)} {r.path} is an unscoped data endpoint — it must "
            f"depend on verify_api_key (which enforces company scoping)."
        )


def test_no_api_key_route_selects_company_via_path_param(monkeypatch):
    """A company_id path param would bypass the query-based scoping check."""
    app = _load_app(monkeypatch)

    for r in app.routes:
        if not getattr(r, "path", "").startswith("/api/"):
            continue
        if not _uses_verify_api_key(getattr(r, "dependant", None)):
            continue
        path_param_names = {p.name for p in r.dependant.path_params}
        assert "company_id" not in path_param_names, (
            f"{sorted(r.methods)} {r.path} takes company_id as a PATH param; the "
            f"scoping check reads it from the query, so this would bypass it."
        )
