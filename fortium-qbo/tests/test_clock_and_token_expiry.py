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


# ---------------------------------------------------------------------------
# Expiries Intuit stated, rather than expiries we assumed (#34)
# ---------------------------------------------------------------------------
#
# Five call sites wrote `utcnow() + timedelta(hours=1)` and
# `utcnow() + timedelta(days=100)` while the token response that had just
# arrived carried both real lifetimes. Those constants are Intuit's documented
# defaults, so the stored value was usually right by coincidence — and nothing
# here would have noticed the day it stopped being.
#
# The access-token expiry is what the scheduler refreshes against. Storing one
# longer than the truth means requests failing on an expired token the service
# believes is live, and the failure surfaces as a QuickBooks 401 rather than as
# anything pointing at this.

from app.utils.token_status import (
    FALLBACK_ACCESS_TOKEN_LIFETIME,
    FALLBACK_REFRESH_TOKEN_LIFETIME,
    token_expiries,
)


class _AuthClient:
    """An intuitlib AuthClient after a token call, as send_request leaves it.

    `intuitlib.utils.send_request` does `set_attributes(obj, response.json())`
    on any 200 with a body, and that copies EVERY key of the token response
    onto the client — which is why these two attributes are readable at all.
    """

    def __init__(self, expires_in=3600, x_refresh_token_expires_in=8726400):
        self.expires_in = expires_in
        self.x_refresh_token_expires_in = x_refresh_token_expires_in


def _minutes(delta):
    return round(delta.total_seconds() / 60)


def test_the_stored_expiry_tracks_what_intuit_said_not_the_constant():
    """The test that fails against the code this replaces.

    A 30-minute access token is the case the constants get wrong in the
    dangerous direction: the old code stored 60 minutes, so for half an hour
    the service believed a dead token was live.
    """
    before = utcnow()
    access, refresh = token_expiries(_AuthClient(expires_in=1800))

    assert 29 <= _minutes(access - before) <= 31, access
    assert _minutes(access - before) != 60, "stored the constant, not Intuit's value"


def test_a_longer_lived_token_is_not_truncated_to_the_constant():
    """The other direction: an expiry shorter than the truth refreshes early.

    Harmless for correctness and not free — every premature refresh spends an
    Intuit rate-limit slot and rotates a refresh token that had not expired.
    """
    before = utcnow()
    access, _ = token_expiries(_AuthClient(expires_in=7200))

    assert 119 <= _minutes(access - before) <= 121


def test_the_refresh_token_expiry_comes_from_intuit_too():
    before = utcnow()
    _, refresh = token_expiries(_AuthClient(x_refresh_token_expires_in=60 * 60 * 24 * 45))

    assert 44 <= (refresh - before).days <= 45


@pytest.mark.parametrize("value", ["3600", 3600])
def test_a_string_of_seconds_is_the_same_fact_as_a_number(value):
    """Intuit sends these as JSON numbers and has been seen sending strings.

    A type check would have taken the fallback on the string and looked exactly
    like the bug this replaces: a plausible expiry, silently not Intuit's.
    """
    before = utcnow()
    access, _ = token_expiries(_AuthClient(expires_in=value))

    assert 59 <= _minutes(access - before) <= 61


@pytest.mark.parametrize(
    "missing", [None], ids=["absent"]
)
def test_an_absent_value_falls_back_to_the_documented_default(missing):
    before = utcnow()
    access, refresh = token_expiries(
        _AuthClient(expires_in=missing, x_refresh_token_expires_in=missing)
    )

    assert _minutes(access - before) == _minutes(FALLBACK_ACCESS_TOKEN_LIFETIME)
    assert (refresh - before).days == FALLBACK_REFRESH_TOKEN_LIFETIME.days


@pytest.mark.parametrize("bad", [0, -1, "", "soon", [], {}], ids=
                         ["zero", "negative", "empty", "words", "list", "dict"])
def test_a_value_that_would_store_a_past_expiry_is_refused(bad):
    """The one guard that is not cosmetic.

    A zero or negative lifetime stores an expiry already behind us, and the
    scheduler reads a past expiry as "refresh now" — so one malformed response
    becomes a refresh attempt on every scheduler tick, against Intuit's rate
    limits, for as long as the response keeps coming back malformed.
    """
    before = utcnow()
    access, _ = token_expiries(_AuthClient(expires_in=bad))

    assert access > before, "stored an expiry in the past"
    assert _minutes(access - before) == _minutes(FALLBACK_ACCESS_TOKEN_LIFETIME)


def test_a_client_that_never_saw_a_token_response_still_answers():
    """`getattr(..., None)` rather than attribute access.

    An AuthClient built but never used has neither attribute set to anything
    but None, and a refresh path that raised AttributeError here would turn a
    token problem into a 500 inside the refresh handler.
    """
    class _Bare:
        pass

    before = utcnow()
    access, refresh = token_expiries(_Bare())

    assert _minutes(access - before) == _minutes(FALLBACK_ACCESS_TOKEN_LIFETIME)
    assert (refresh - before).days == FALLBACK_REFRESH_TOKEN_LIFETIME.days


def test_the_two_lifetimes_are_read_independently():
    """A single shared value would make one of the two silently wrong.

    They are different fields with different magnitudes — an hour against a
    hundred days — so crossing them is the kind of mistake that still produces
    plausible-looking rows.
    """
    before = utcnow()
    access, refresh = token_expiries(
        _AuthClient(expires_in=1800, x_refresh_token_expires_in=60 * 60 * 24 * 10)
    )

    assert 29 <= _minutes(access - before) <= 31
    assert 9 <= (refresh - before).days <= 10
