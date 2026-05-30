"""Tests for QBOService._to_thread_with_retry transient-fault handling.

Hermetic: no QBO creds or network. The retry helper runs `fn` via
asyncio.to_thread, so we mock at the `fn` boundary (a plain callable that
raises/returns) and patch asyncio.sleep to keep the test instant.
"""

import asyncio

import pytest

from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService
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
