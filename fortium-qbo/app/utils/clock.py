"""Timezone-aware UTC, and a way to compare against what the database holds.

`datetime.utcnow()` is deprecated from Python 3.12 and returns a naive value —
one carrying no tzinfo at all, which is a different thing from one known to be
UTC. Comparing a naive datetime against an aware one raises `TypeError`, so a
codebase that mixes them fails at the comparison rather than at the mistake.

This service runs on the seam. The Docker image is Python 3.11 where the call
is silent; CI runs 3.13 where it emits a DeprecationWarning on every test run.
Neither is wrong today, and both stop being true on a base-image bump.

Two functions, because the codebase does two different things with time:

`utcnow()` is what to call instead of `datetime.utcnow()`. It returns an aware
value, which is what makes an accidental naive/aware comparison raise at the
point of the error rather than silently comparing a UTC instant against a
local one.

`as_utc()` is for reading a datetime back out of the database. Those columns
are migrating to `timestamptz` in this change, after which psycopg2 hands
back aware values and `as_utc` is a no-op on them. It stays because it makes
the comparison sites correct on BOTH sides of that migration — the code can
deploy before or after the ALTER runs without a window where a naive value
meets an aware one.

The database's session TimeZone is UTC (checked against the live instance),
so a naive value crossing the boundary in either direction resolves to UTC
rather than to whatever the server happens to be set to. That is what makes
the ordering a non-issue rather than a race.
"""

from datetime import datetime, timezone

__all__ = ["as_utc", "utcnow"]


def utcnow() -> datetime:
    """The current UTC time, timezone-aware.

    Replaces `datetime.utcnow()`, whose result is naive and therefore cannot
    be safely compared with anything that knows its own zone.
    """
    return datetime.now(timezone.utc)



def as_utc(value: datetime | None) -> datetime | None:
    """Mark a naive datetime as UTC; pass through aware ones and None.

    For values read out of the database, where the column is naive and the
    convention is UTC. This is where the convention becomes explicit.

    Idempotent on aware input, which is the property that matters: it means
    the comparison sites keep working unchanged if those columns are ever
    migrated to `timestamptz` and start arriving aware on their own.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)
