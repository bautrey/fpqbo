"""Tests for QBO sandbox connection support.

Verify that sandbox companies route to the Intuit "Development" credentials and
the ``sandbox`` OAuth environment (which the python-quickbooks SDK uses to pick
the sandbox API base URL), while production companies are unaffected. The Intuit
``AuthClient`` is stubbed everywhere so no network/discovery call is made.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.config import Settings


# ---------------------------------------------------------------------------
# Settings.get_qbo_credentials / qbo_sandbox_configured
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    """Build a Settings instance with required fields, overriding QBO creds."""
    base = dict(
        app_secret_key="a" * 32,
        google_client_id="gid",
        google_client_secret="gsecret",
        qbo_client_id="us-id",
        qbo_client_secret="us-secret",
    )
    base.update(overrides)
    return Settings(**base)


def test_sandbox_not_configured_by_default():
    s = _settings()
    assert s.qbo_sandbox_configured is False
    assert s.get_qbo_credentials("US", is_sandbox=True) is None


def test_sandbox_credentials_selected_when_configured():
    s = _settings(
        qbo_sandbox_client_id="sb-id",
        qbo_sandbox_client_secret="sb-secret",
    )
    assert s.qbo_sandbox_configured is True
    assert s.get_qbo_credentials("US", is_sandbox=True) == ("sb-id", "sb-secret")


def test_sandbox_ignores_region_and_uses_dev_keys():
    s = _settings(
        qbo_sandbox_client_id="sb-id",
        qbo_sandbox_client_secret="sb-secret",
    )
    # Region is irrelevant for sandbox — dev keys are returned regardless.
    assert s.get_qbo_credentials("CA", is_sandbox=True) == ("sb-id", "sb-secret")


def test_production_credentials_unaffected_by_sandbox_config():
    s = _settings(
        qbo_sandbox_client_id="sb-id",
        qbo_sandbox_client_secret="sb-secret",
    )
    # Production path still returns the US production keys.
    assert s.get_qbo_credentials("US", is_sandbox=False) == ("us-id", "us-secret")
    assert s.qbo_configured is True


# ---------------------------------------------------------------------------
# qbo_oauth._get_intuit_auth_client environment + credential routing
# ---------------------------------------------------------------------------


class _RecordingAuthClient:
    """Stub AuthClient that records the kwargs it was constructed with."""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


class _FakeSettings:
    qbo_callback_url = "https://example.test/callback"

    def __init__(self, creds: dict):
        self._creds = creds

    def get_qbo_credentials(self, region, is_sandbox=False):
        return self._creds.get("sandbox" if is_sandbox else region)


# Default credential map used by the service-layer tests.
_SVC_SETTINGS = _FakeSettings({"sandbox": ("sb-id", "sb-secret"), "US": ("us-id", "us-secret")})


def test_get_intuit_auth_client_sandbox(monkeypatch):
    from app.routers import qbo_oauth

    monkeypatch.setattr(qbo_oauth, "AuthClient", _RecordingAuthClient)
    monkeypatch.setattr(
        qbo_oauth,
        "settings",
        _FakeSettings({"sandbox": ("sb-id", "sb-secret"), "US": ("us-id", "us-secret")}),
    )

    client = qbo_oauth._get_intuit_auth_client(region="US", is_sandbox=True)

    assert client is not None
    assert _RecordingAuthClient.last_kwargs["environment"] == "sandbox"
    assert _RecordingAuthClient.last_kwargs["client_id"] == "sb-id"


def test_get_intuit_auth_client_production(monkeypatch):
    from app.routers import qbo_oauth

    monkeypatch.setattr(qbo_oauth, "AuthClient", _RecordingAuthClient)
    monkeypatch.setattr(
        qbo_oauth,
        "settings",
        _FakeSettings({"sandbox": ("sb-id", "sb-secret"), "US": ("us-id", "us-secret")}),
    )

    client = qbo_oauth._get_intuit_auth_client(region="US", is_sandbox=False)

    assert client is not None
    assert _RecordingAuthClient.last_kwargs["environment"] == "production"
    assert _RecordingAuthClient.last_kwargs["client_id"] == "us-id"


def test_get_intuit_auth_client_sandbox_unconfigured_returns_none(monkeypatch):
    from app.routers import qbo_oauth

    monkeypatch.setattr(qbo_oauth, "AuthClient", _RecordingAuthClient)
    monkeypatch.setattr(qbo_oauth, "settings", _FakeSettings({"US": ("us-id", "us-secret")}))

    assert qbo_oauth._get_intuit_auth_client(region="US", is_sandbox=True) is None


# ---------------------------------------------------------------------------
# qbo_service._get_client builds a sandbox-environment client for sandbox cos
# ---------------------------------------------------------------------------


def test_get_client_uses_sandbox_environment(monkeypatch):
    from app.services import qbo_service as m
    from app.services.qbo_service import QBOService

    recorded = {}

    class _AuthClient:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    class _QuickBooks:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(m, "AuthClient", _AuthClient)
    monkeypatch.setattr(m, "QuickBooks", _QuickBooks)
    monkeypatch.setattr(m, "settings", _SVC_SETTINGS)

    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}

    company = SimpleNamespace(
        id=1,
        token_expires_at=datetime.utcnow() + timedelta(hours=2),  # fresh: no refresh
        region="US",
        is_sandbox=True,
        access_token="access",
        refresh_token="refresh",
        realm_id="123456",
    )

    svc._get_client(company)

    assert recorded["environment"] == "sandbox"
    assert recorded["client_id"] == "sb-id"


def test_get_client_uses_production_environment(monkeypatch):
    from app.services import qbo_service as m
    from app.services.qbo_service import QBOService

    recorded = {}

    class _AuthClient:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    class _QuickBooks:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(m, "AuthClient", _AuthClient)
    monkeypatch.setattr(m, "QuickBooks", _QuickBooks)
    monkeypatch.setattr(m, "settings", _SVC_SETTINGS)

    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}

    company = SimpleNamespace(
        id=2,
        token_expires_at=datetime.utcnow() + timedelta(hours=2),
        region="US",
        is_sandbox=False,
        access_token="access",
        refresh_token="refresh",
        realm_id="654321",
    )

    svc._get_client(company)

    assert recorded["environment"] == "production"
    assert recorded["client_id"] == "us-id"
