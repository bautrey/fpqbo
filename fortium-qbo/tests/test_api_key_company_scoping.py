"""Tests for per-company API-key scoping in verify_api_key.

An API key is bound to one company; it must not be able to read or write
another company by passing a different ``company_id`` query param (prevents
cross-company / prod<->sandbox access). Hermetic: the DB lookup and Request
are stubbed, so no network or real database is touched.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.dependencies.api_auth import verify_api_key


def _run(coro):
    return asyncio.run(coro)


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


class _FakeRequest:
    def __init__(self, query: dict):
        self.query_params = query
        self.state = SimpleNamespace()


def _make_key(company_id: int = 1):
    return SimpleNamespace(
        id=1, company_id=company_id, is_active=True, last_used_at=None
    )


def test_allows_matching_company():
    key = _make_key(company_id=1)
    req = _FakeRequest({"company_id": "1"})
    result = _run(verify_api_key(req, x_api_key="fqbo_test", db=_FakeDB(key)))
    assert result is key


def test_rejects_cross_company_access():
    """US key (company 1) requesting company 5 (sandbox) -> 403."""
    key = _make_key(company_id=1)
    req = _FakeRequest({"company_id": "5"})
    with pytest.raises(HTTPException) as exc:
        _run(verify_api_key(req, x_api_key="fqbo_test", db=_FakeDB(key)))
    assert exc.value.status_code == 403


def test_allows_when_no_company_id():
    """Endpoints without company_id (e.g. /api/companies/) are not blocked."""
    key = _make_key(company_id=1)
    req = _FakeRequest({})
    result = _run(verify_api_key(req, x_api_key="fqbo_test", db=_FakeDB(key)))
    assert result is key


def test_non_integer_company_id_falls_through():
    """A non-numeric company_id is left for the endpoint's own 422 validation."""
    key = _make_key(company_id=1)
    req = _FakeRequest({"company_id": "abc"})
    # Should not raise 403 here; verify_api_key returns the key and FastAPI's
    # int query validation will reject "abc" downstream.
    result = _run(verify_api_key(req, x_api_key="fqbo_test", db=_FakeDB(key)))
    assert result is key


def test_missing_api_key_header_401():
    key = _make_key(company_id=1)
    req = _FakeRequest({"company_id": "1"})
    with pytest.raises(HTTPException) as exc:
        _run(verify_api_key(req, x_api_key=None, db=_FakeDB(key)))
    assert exc.value.status_code == 401


def test_invalid_api_key_401():
    req = _FakeRequest({"company_id": "1"})
    with pytest.raises(HTTPException) as exc:
        _run(verify_api_key(req, x_api_key="fqbo_bad", db=_FakeDB(None)))
    assert exc.value.status_code == 401
