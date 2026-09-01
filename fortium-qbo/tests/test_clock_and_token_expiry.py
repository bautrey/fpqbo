"""Timezone-aware time, and the token-expiry comparisons that depend on it.

`datetime.utcnow()` returns a naive value — one carrying no tzinfo, which is
a different thing from one known to be UTC. Comparing naive against aware
raises TypeError, so the whole codebase had to stay naive together. That is
why a deprecated call sat in 28 places: none of them could move alone.

The comparisons in `_needs_refresh`, `token_status` and the refresh scheduler
decide whether a QuickBooks token gets renewed. Getting one wrong does not
raise anywhere visible; it lets a token lapse, and then every `/api/*` call
for that company fails until a human reconnects. None of them had a single
test before this change, which is the reason the deprecation was safe to
ignore for so long and would not have been safe to sweep blind.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.utils.clock import as_utc, utcnow


# ---------------------------------------------------------------------------
# The clock itself
# ---------------------------------------------------------------------------


def test_utcnow_is_aware_and_utc():
    now = utcnow()
    assert now.tzinfo is not None, "a naive value is what this module exists to stop"
    assert now.utcoffset() == timedelta(0)


def test_utcnow_can_be_compared_with_a_stored_expiry():
    """The property the old code did not have.

    `datetime.utcnow() >= <aware value>` raises TypeError. That is the failure
    this replaces, and it fires at the comparison rather than at the mistake.
    """
    stored = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert (utcnow() < stored) in (True, False)  # no TypeError

    with pytest.raises(TypeError):
        datetime(2030, 1, 1) < stored  # naive vs aware, the old shape


def test_as_utc_stamps_a_naive_value_without_shifting_it():
    naive = datetime(2026, 8, 31, 12, 0, 0)
    stamped = as_utc(naive)
    assert stamped.tzinfo == timezone.utc
    assert stamped.replace(tzinfo=None) == naive, (
        "as_utc marks the convention; it must not move the instant"
    )


def test_as_utc_is_idempotent_on_an_aware_value():
    """Why the comparison sites survive the timestamptz migration.

    Before the ALTER these columns hand back naive values; after it they hand
    back aware ones. as_utc has to be correct on both, or the code and the
    migration would have to land in the same instant.
    """
    aware = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert as_utc(aware) is aware


def test_as_utc_passes_none_through():
    """token_expires_at is nullable, and a company that never connected has
    no expiry at all."""
    assert as_utc(None) is None


def test_as_utc_does_not_reinterpret_a_non_utc_offset():
    """An aware value in another zone keeps its own instant.

    Not reachable from this schema, but the alternative — forcing UTC onto
    anything aware — would silently shift a real time by the offset.
    """
    other = datetime(2026, 8, 31, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert as_utc(other).utcoffset() == timedelta(hours=-5)


# ---------------------------------------------------------------------------
# _needs_refresh — the comparison that decides whether a token is renewed
# ---------------------------------------------------------------------------


def _svc():
    from app.services.qbo_service import QBOService

    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    return svc


class _Company:
    def __init__(self, expires_at):
        self.token_expires_at = expires_at
        self.code = "FOR-138"


@pytest.mark.parametrize("aware", [True, False], ids=["aware-column", "naive-column"])
def test_a_token_well_in_the_future_is_not_refreshed(aware):
    """Both column shapes, because the migration changes which one arrives.

    A test written against only one of them would pass before the ALTER and
    fail after it, or the reverse — and the failure mode is a TypeError on
    every request, not a wrong boolean.
    """
    future = utcnow() + timedelta(hours=2)
    expires = future if aware else future.replace(tzinfo=None)

    assert _svc()._needs_refresh(_Company(expires)) is False


@pytest.mark.parametrize("aware", [True, False], ids=["aware-column", "naive-column"])
def test_an_expired_token_is_refreshed(aware):
    past = utcnow() - timedelta(hours=1)
    expires = past if aware else past.replace(tzinfo=None)

    assert _svc()._needs_refresh(_Company(expires)) is True


@pytest.mark.parametrize("aware", [True, False], ids=["aware-column", "naive-column"])
def test_a_token_inside_the_refresh_buffer_is_refreshed(aware):
    """The buffer is the point: renew before expiry, not after it.

    TOKEN_REFRESH_BUFFER is 5 minutes, so a token expiring in 1 minute is
    already due. Letting it lapse means every request for that company fails
    until someone reconnects.
    """
    soon = utcnow() + timedelta(minutes=1)
    expires = soon if aware else soon.replace(tzinfo=None)

    assert _svc()._needs_refresh(_Company(expires)) is True


def test_a_company_with_no_expiry_is_refreshed():
    """No recorded expiry means nothing proves the token is good."""
    assert _svc()._needs_refresh(_Company(None)) is True


def test_the_comparison_does_not_raise_on_a_naive_column():
    """The regression this whole change is guarding.

    An aware `now` against a naive stored value raises TypeError inside
    `_needs_refresh`, which surfaces through the router catch-all as
    `500 QBO API error: can't compare offset-naive and offset-aware
    datetimes` — pointing whoever reads it at Intuit, for our bug.
    """
    naive = (utcnow() + timedelta(hours=2)).replace(tzinfo=None)
    try:
        _svc()._needs_refresh(_Company(naive))
    except TypeError as e:  # pragma: no cover - the failure being prevented
        pytest.fail(f"naive/aware comparison reached production code: {e}")


# ---------------------------------------------------------------------------
# token_status — what the admin UI reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("aware", [True, False], ids=["aware-column", "naive-column"])
def test_token_status_reports_an_expired_token_as_expired(aware):
    from app.utils.token_status import get_token_status

    past = utcnow() - timedelta(hours=3)
    result = get_token_status(past if aware else past.replace(tzinfo=None), "active")

    assert result.status == "expired"


@pytest.mark.parametrize("aware", [True, False], ids=["aware-column", "naive-column"])
def test_token_status_reports_a_healthy_token_as_valid(aware):
    from app.utils.token_status import get_token_status

    future = utcnow() + timedelta(hours=5)
    result = get_token_status(future if aware else future.replace(tzinfo=None), "active")

    assert result.status != "expired"


# ---------------------------------------------------------------------------
# The refresh scheduler — the one comparison Postgres used to resolve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("aware", [True, False], ids=["aware-column", "naive-column"])
def test_the_scheduler_selects_the_same_companies_either_column_type(monkeypatch, aware):
    """This comparison used to run in SQL, and that was the risk.

    Python raises TypeError on naive-vs-aware. Postgres does not — it coerces
    using the session TimeZone and returns a different set of rows, silently.
    `init_db()` only calls `create_all` and never applies Alembic, so the
    scheduler can query either column type depending on whether the migration
    has reached that database. Picking the wrong companies means a token
    quietly lapses, and then every request for that company fails until a
    human reconnects.

    So the selection moved into Python, and this asserts it is stable across
    both shapes rather than across both server settings.
    """
    import asyncio
    from types import SimpleNamespace

    from app.services import token_refresh_scheduler as mod

    def stamp(dt):
        return dt if aware else dt.replace(tzinfo=None)

    due = SimpleNamespace(
        code="DUE", token_status="active", refresh_token="r",
        token_expires_at=stamp(utcnow() + timedelta(minutes=5)),
    )
    not_due = SimpleNamespace(
        code="NOT-DUE", token_status="active", refresh_token="r",
        token_expires_at=stamp(utcnow() + timedelta(hours=6)),
    )
    never_connected = SimpleNamespace(
        code="NO-EXPIRY", token_status="active", refresh_token="r",
        token_expires_at=None,
    )

    class _Query:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [due, not_due, never_connected]

    monkeypatch.setattr(mod, "SessionLocal", lambda: SimpleNamespace(
        query=lambda *a, **k: _Query(), close=lambda: None,
    ))

    refreshed = []

    # The real call, found by reading the loop rather than guessing: the
    # scheduler does `qbo_service._refresh_token(company)`. The first version
    # of this test patched a `_refresh_company_token` that does not exist,
    # with raising=False, so the patch bound nothing, `refreshed` stayed empty
    # and every assertion below passed for free. Patch what is called, and
    # assert the positive case, or the test cannot fail.
    from app.services.qbo_service import QBOService

    monkeypatch.setattr(
        QBOService, "__init__", lambda self, db: None, raising=True
    )
    monkeypatch.setattr(
        QBOService, "_refresh_token",
        lambda self, c: refreshed.append(c.code),
        raising=True,
    )

    sched = mod.TokenRefreshScheduler.__new__(mod.TokenRefreshScheduler)
    asyncio.run(sched._refresh_expiring_tokens())

    assert "DUE" in refreshed, (
        "the company inside the refresh window was not selected"
    )
    assert "NOT-DUE" not in refreshed, "a token with six hours left was refreshed"
    assert "NO-EXPIRY" not in refreshed, (
        "a NULL expiry must stay excluded, as the SQL `<=` did"
    )
