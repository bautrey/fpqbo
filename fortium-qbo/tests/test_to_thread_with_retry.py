"""Tests for QBOService._to_thread_with_retry transient-fault handling.

Hermetic: no QBO creds or network. The retry helper runs `fn` via
asyncio.to_thread, so we mock at the `fn` boundary (a plain callable that
raises/returns) and patch asyncio.sleep to keep the test instant.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services.qbo_service import QBOService, _is_transient_qbo_error
from quickbooks.exceptions import (
    AuthorizationException,
    SevereException,
    ValidationException,
)


def _run(coro):
    return asyncio.run(coro)


def _make_service():
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    return svc


class _FailNTimesThenSucceed:
    """Callable that raises `exc` the first `n` calls, then returns `result`."""

    def __init__(self, exc, n, result="ok"):
        self.exc = exc
        self.n = n
        self.result = result
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.n:
            raise self.exc
        return self.result


class _AlwaysFail:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise self.exc


def test_retries_severe_exception_twice_then_succeeds(monkeypatch):
    """SevereException raised twice, then success -> 3rd call returns value."""
    svc = _make_service()
    fn = _FailNTimesThenSucceed(
        SevereException("QB Severe Exception", error_code=10000), n=2, result="invoices"
    )

    sleeps = []

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    result = _run(svc._to_thread_with_retry(fn, op="get_invoices"))

    assert result == "invoices"
    assert fn.calls == 3, "expected 3 attempts (1 + 2 retries)"
    assert sleeps == [1, 2], "expected 1s then 2s backoff between retries"


def test_authorization_exception_raises_immediately_no_retry(monkeypatch):
    """Deterministic auth fault must raise on the first attempt, no retry."""
    svc = _make_service()
    fn = _AlwaysFail(AuthorizationException("auth failed", error_code=401))

    async def _fake_sleep(secs):  # pragma: no cover - must never be called
        raise AssertionError("sleep should not be called for deterministic fault")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(AuthorizationException):
        _run(svc._to_thread_with_retry(fn, op="get_customers"))

    assert fn.calls == 1, "deterministic fault must not be retried"


def test_validation_exception_raises_immediately_no_retry(monkeypatch):
    """4xx validation fault (2000-4999) is deterministic -> no retry."""
    svc = _make_service()
    fn = _AlwaysFail(ValidationException("bad query", error_code=4000))

    async def _fake_sleep(secs):  # pragma: no cover
        raise AssertionError("sleep should not be called")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(ValidationException):
        _run(svc._to_thread_with_retry(fn, op="get_vendors"))

    assert fn.calls == 1


def test_value_error_raises_immediately_no_retry(monkeypatch):
    """ValueError (e.g. bad company/query) must surface fast, no retry."""
    svc = _make_service()
    fn = _AlwaysFail(ValueError("QBO company not found"))

    async def _fake_sleep(secs):  # pragma: no cover
        raise AssertionError("sleep should not be called")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(ValueError):
        _run(svc._to_thread_with_retry(fn, op="get_accounts"))

    assert fn.calls == 1


def test_severe_exception_every_time_reraises_after_three_attempts(monkeypatch):
    """Persistent transient fault: re-raise original exc after 3 attempts."""
    svc = _make_service()
    exc = SevereException("QB Severe Exception", error_code=10000)
    fn = _AlwaysFail(exc)

    sleeps = []

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(SevereException) as excinfo:
        _run(svc._to_thread_with_retry(fn, op="get_bills"))

    assert excinfo.value is exc, "must re-raise the original exception, not a wrapper"
    assert fn.calls == 3, "expected exactly 3 attempts before giving up"
    assert sleeps == [1, 2], "expected backoff after attempts 1 and 2 only"


# ---------------------------------------------------------------------------
# Report path (direct httpx API) transient-fault coverage
# ---------------------------------------------------------------------------


def _httpx_status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://sandbox-quickbooks.api.intuit.com/x")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


def test_is_transient_classifies_httpx_5xx_but_not_4xx():
    """Report 5xx (httpx.HTTPStatusError) is transient; 4xx is deterministic."""
    assert _is_transient_qbo_error(_httpx_status_error(503)) is True
    assert _is_transient_qbo_error(_httpx_status_error(500)) is True
    assert _is_transient_qbo_error(_httpx_status_error(404)) is False
    assert _is_transient_qbo_error(_httpx_status_error(400)) is False


class _ScriptedResponse:
    """Minimal stand-in for httpx.Response with scripted status/payload."""

    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _httpx_status_error(self.status_code)

    def json(self):
        return self._payload


def _patch_async_client(monkeypatch, scripted, state):
    """Patch httpx.AsyncClient so successive .get() calls return scripted[i]."""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            resp = scripted[state["i"]]
            state["i"] += 1
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def test_fetch_report_retries_transient_5xx_then_succeeds(monkeypatch):
    """A report 5xx is retried; the next-attempt 200 payload is returned."""
    svc = _make_service()
    monkeypatch.setattr(QBOService, "_needs_refresh", lambda self, c: False)

    state = {"i": 0}
    _patch_async_client(
        monkeypatch,
        [_ScriptedResponse(503), _ScriptedResponse(200, {"Rows": "ok"})],
        state,
    )

    sleeps = []

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    company = SimpleNamespace(is_sandbox=False, realm_id="123", access_token="tok")
    result = _run(svc._fetch_report(company, "TrialBalance", {}))

    assert result == {"Rows": "ok"}
    assert state["i"] == 2, "expected one retry (2 GETs)"
    assert sleeps == [1], "expected a single 1s backoff before the retry"


def test_fetch_report_4xx_raises_immediately_no_retry(monkeypatch):
    """A report 4xx is deterministic — surface immediately, no retry."""
    svc = _make_service()
    monkeypatch.setattr(QBOService, "_needs_refresh", lambda self, c: False)

    state = {"i": 0}
    _patch_async_client(monkeypatch, [_ScriptedResponse(400)], state)

    async def _fake_sleep(secs):  # pragma: no cover - must never be called
        raise AssertionError("sleep should not be called for a report 4xx")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    company = SimpleNamespace(is_sandbox=False, realm_id="123", access_token="tok")
    with pytest.raises(httpx.HTTPStatusError):
        _run(svc._fetch_report(company, "TrialBalance", {}))

    assert state["i"] == 1, "deterministic report 4xx must not be retried"
