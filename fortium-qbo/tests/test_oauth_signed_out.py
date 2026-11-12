"""A signed-out request to a QBO OAuth route is sent to /login, never a 500 (#78).

`_require_auth` used to `raise RedirectResponse(...)`. A Response is not an
exception, so the raise itself threw TypeError and every caller's
`except RedirectResponse` was dead: production answered 500.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import qbo_oauth

REDIRECTING = [
    ("get", "/api/qbo/connect"),
    ("get", "/callback?error=x"),
    ("post", "/api/qbo/companies/1/disconnect"),
]
JSON_REFUSING = [
    ("post", "/api/qbo/companies/1/refresh"),
    ("post", "/api/qbo/refresh-all"),
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(qbo_oauth.router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


class _NoAdminDb:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def close(self):
        pass


@pytest.fixture(params=["no-cookie", "bad-cookie", "not-an-admin"])
def cookies(request, monkeypatch):
    if request.param == "no-cookie":
        return {}
    if request.param == "bad-cookie":
        monkeypatch.setattr(qbo_oauth, "verify_session", lambda token: None)
    else:
        monkeypatch.setattr(qbo_oauth, "verify_session", lambda token: "x@example.com")
        monkeypatch.setattr(qbo_oauth, "SessionLocal", _NoAdminDb)
    return {"auth_session": "token"}


@pytest.mark.parametrize("method,path", REDIRECTING)
def test_signed_out_is_redirected_to_login(client, cookies, method, path):
    client.cookies.update(cookies)
    response = getattr(client, method)(path)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("method,path", JSON_REFUSING)
def test_signed_out_json_routes_refuse_without_500(client, cookies, method, path):
    client.cookies.update(cookies)
    response = getattr(client, method)(path)
    assert response.status_code == 200
    body = response.json()
    assert "Authentication required" in (body.get("message") or body.get("error"))
