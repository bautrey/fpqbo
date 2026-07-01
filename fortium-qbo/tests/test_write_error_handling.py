"""Tests for the shared QBO write error-handling helper (``run_qbo_write``).

Issue #6: write endpoints must distinguish client (4xx) from server (5xx)
errors and log the 5xx path. These exercise the helper directly with tiny
coroutines — fast, no network — asserting the exception -> status-code mapping
and that genuine 500s are logged at error level.
"""

import asyncio
import logging

import pytest
from fastapi import HTTPException

from app.routers._qbo_write import run_qbo_write


def _run(coro):
    return asyncio.run(coro)


async def _raise(exc):
    raise exc


async def _return(value):
    return value


def test_value_error_maps_to_400():
    with pytest.raises(HTTPException) as exc:
        _run(run_qbo_write(_raise(ValueError("company not found")), entity="customer"))
    assert exc.value.status_code == 400
    assert exc.value.detail == "company not found"


def test_key_error_maps_to_400_not_500():
    with pytest.raises(HTTPException) as exc:
        _run(run_qbo_write(_raise(KeyError("value")), entity="bill"))
    assert exc.value.status_code == 400
    assert "bill" in exc.value.detail


def test_type_error_maps_to_400():
    with pytest.raises(HTTPException) as exc:
        _run(
            run_qbo_write(
                _raise(TypeError("'NoneType' object is not subscriptable")),
                entity="journal entry",
            )
        )
    assert exc.value.status_code == 400
    assert "journal entry" in exc.value.detail


def test_generic_exception_maps_to_500_and_logs(caplog):
    with caplog.at_level(logging.ERROR, logger="app.routers._qbo_write"):
        with pytest.raises(HTTPException) as exc:
            _run(
                run_qbo_write(_raise(Exception("QBO down")), entity="vendor")
            )
    assert exc.value.status_code == 500
    assert exc.value.detail == "QBO API error: QBO down"
    # A genuine 500 must leave a server-side breadcrumb.
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "generic exception did not log at ERROR level"
    assert "vendor" in error_records[0].getMessage()


def test_success_returns_value_unchanged():
    result = _run(run_qbo_write(_return({"Id": "42"}), entity="account"))
    assert result == {"Id": "42"}
