"""The service's errors have to say which thing went wrong.

Before this, `qbo_service` signalled every failure with `ValueError`, and
around seventy-nine router handlers answered any `ValueError` with a 404 and
the message verbatim. Three of the eleven raise sites were not missing records
at all:

    QBO credentials not configured for: US
    Token refresh failed for FOR-138. Please reconnect at /admin/companies.
    QBO company FOR-138 is disconnected. Please reconnect via /admin/companies.

All three came back as `404 not found`. A sync job or monitor routing on the
status code recorded "this company does not exist" while the truth was "our
credentials are broken and every request will fail until a human reconnects".

So these tests assert on status codes, not messages. A message nobody parses
was never the problem — the problem was the number that automation reads.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.dependencies.api_auth import verify_api_key
from app.exceptions import QboCompanyDisconnected, QboNotFound, QboUnavailable
from app.routers import vendors
from app.services.qbo_service import QBOService


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# The types themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,status",
    [
        (QboNotFound("x"), 404),
        (QboCompanyDisconnected("x"), 409),
        (QboUnavailable("x"), 503),
    ],
    ids=["not-found-404", "disconnected-409", "unavailable-503"],
)
def test_each_condition_carries_its_own_status(exc, status):
    assert exc.status_code == status


@pytest.mark.parametrize(
    "exc",
    [QboNotFound("x"), QboCompanyDisconnected("x"), QboUnavailable("x")],
    ids=["not-found", "disconnected", "unavailable"],
)
def test_none_of_them_is_a_value_error(exc):
    """The whole point. `except ValueError -> 404` must no longer catch them.

    A handler that still does that would put every one of these back to 404,
    which is the defect being removed.
    """
    assert not isinstance(exc, (ValueError, TypeError))
    assert isinstance(exc, HTTPException), (
        "must be an HTTPException or the routers' blanket `except Exception` "
        "rewraps it as a 500 before the status can matter"
    )


# ---------------------------------------------------------------------------
# What the service raises for each condition
# ---------------------------------------------------------------------------


def _svc(company=None):
    svc = QBOService.__new__(QBOService)
    svc._clients = {}

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return company

    svc.db = SimpleNamespace(query=lambda *a, **k: _Q())
    return svc


def test_an_unknown_company_code_is_a_404():
    with pytest.raises(QboNotFound) as caught:
        _svc(company=None).get_company_by_code("NOPE-000")
    assert caught.value.status_code == 404


def test_a_disconnected_company_is_not_reported_as_missing():
    """It exists. Answering 404 tells a monitor the company was deleted."""
    company = SimpleNamespace(code="FOR-138", token_status="disconnected")

    with pytest.raises(QboCompanyDisconnected) as caught:
        _svc(company=company).get_company_by_code("FOR-138")

    assert caught.value.status_code == 409
    assert caught.value.status_code != 404, "a live company must not read as absent"
    assert "reconnect" in str(caught.value.detail).lower()


def test_missing_credentials_are_not_reported_as_a_missing_company(monkeypatch):
    """The company is fine; this service is misconfigured.

    This is the case that motivated the change — a credentials outage told
    every caller the company did not exist.
    """
    svc = _svc()
    company = SimpleNamespace(
        id=1, code="FOR-138", region="US", is_sandbox=False,
        token_status="active", access_token="a", refresh_token="r",
        realm_id="1", token_expires_at=None,
    )
    # The Settings instance is a frozen pydantic model, so the module-level
    # name is replaced rather than the method patched onto it.
    monkeypatch.setattr(
        "app.services.qbo_service.settings",
        SimpleNamespace(get_qbo_credentials=lambda region, is_sandbox=False: None),
    )
    monkeypatch.setattr(QBOService, "_needs_refresh", lambda self, c: False)

    with pytest.raises(QboUnavailable) as caught:
        svc._get_client(company)

    assert caught.value.status_code == 503
    assert caught.value.status_code != 404, (
        "broken credentials must not read as a missing company"
    )


# ---------------------------------------------------------------------------
# End to end through a real handler
# ---------------------------------------------------------------------------


def _client(raiser):
    app = FastAPI()
    app.include_router(vendors.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[vendors._get_service] = lambda: raiser
    return TestClient(app, raise_server_exceptions=False)


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def __getattr__(self, name):
        async def _call(**kwargs):
            raise self.exc

        return _call


@pytest.mark.parametrize(
    "exc,status",
    [
        (QboNotFound("QBO company not found: 99"), 404),
        (QboCompanyDisconnected("FOR-138 is disconnected"), 409),
        (QboUnavailable("QBO credentials not configured for: US"), 503),
    ],
    ids=["404", "409", "503"],
)
def test_the_status_survives_the_handler(exc, status):
    """The handler's `except Exception` must not rewrap these into a 500.

    Forty-one handlers lacked the `except HTTPException: raise` guard before
    this change, so a deliberate 409 or 503 would have been reported as
    "QBO API error" with a 500.
    """
    res = _client(_Raises(exc)).get("/vendors/", params={"company_id": 1})

    assert res.status_code == status
    assert "QBO API error" not in res.json()["detail"], (
        "the catch-all relabelled a deliberate status as an Intuit fault"
    )


def test_a_real_bug_is_still_a_500_and_still_says_so():
    """Narrowing the not-found channel must not swallow genuine faults."""
    res = _client(_Raises(AttributeError("'NoneType' has no attribute 'Id'"))).get(
        "/vendors/", params={"company_id": 1}
    )

    assert res.status_code == 500
    assert res.status_code != 404, "a local bug must not read as a missing record"
