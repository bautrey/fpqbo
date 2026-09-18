"""Token status utility functions."""

import logging
from datetime import datetime, timedelta
from app.utils.clock import as_utc, utcnow
from typing import NamedTuple

logger = logging.getLogger(__name__)

# What to assume when Intuit does not tell us. These are Intuit's documented
# defaults and were, until #34, the only values this service ever stored —
# every token row's expiry was one of these two regardless of what the token
# response said.
FALLBACK_ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
FALLBACK_REFRESH_TOKEN_LIFETIME = timedelta(days=100)


class TokenStatus(NamedTuple):
    """Token status with display information."""
    status: str       # "active", "expiring_soon", "expired", "disconnected"
    label: str        # Human-readable label
    css_class: str    # Bootstrap badge class
    expires_display: str  # Human-readable expiration


class RefreshTokenStatus(NamedTuple):
    """Refresh token status with display information."""
    refresh_status: str          # "healthy", "warning", "critical", "expired", "unknown"
    refresh_expires_display: str  # Human-readable expiration (e.g., "Expires in 99d")
    refresh_css_class: str       # Bootstrap badge class


def _lifetime(raw, fallback: timedelta, label: str) -> timedelta:
    """One lifetime from Intuit's response, or the fallback.

    Falls back on anything that is not a positive whole number of seconds.
    The guard matters in one direction more than the other: a zero or negative
    value would store an expiry already in the past, and the scheduler treats a
    past expiry as "refresh now", so one malformed response would turn into a
    refresh on every scheduler tick against Intuit's rate limits. A value that
    is merely wrong-but-positive is no worse than the constant it replaces.

    `int()` rather than a type check because Intuit sends these as JSON numbers
    and has been observed sending them as strings; both are the same fact.
    """
    if raw is None:
        return fallback
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Intuit sent a %s of %r, which is not a number of seconds; "
            "falling back to %s", label, raw, fallback
        )
        return fallback
    if seconds <= 0:
        logger.warning(
            "Intuit sent a %s of %d seconds; falling back to %s rather than "
            "storing an expiry in the past", label, seconds, fallback
        )
        return fallback
    return timedelta(seconds=seconds)


def token_expiries(auth_client) -> tuple[datetime, datetime]:
    """When the access and refresh tokens actually expire, per Intuit.

    Every token response carries `expires_in` and `x_refresh_token_expires_in`,
    and `intuitlib.utils.send_request` copies every key of that response onto
    the `AuthClient` before returning — so after a successful `.refresh()` or
    `.get_bearer_token()` both values are sitting on the client and this reads
    them rather than assuming.

    Before #34 the service wrote `+1 hour` and `+100 days` at five call sites.
    Those are Intuit's documented defaults, so the stored expiry was usually
    right by coincidence; it stopped being right whenever Intuit issued a token
    with a different lifetime, and nothing in the service would have noticed.
    The access-token expiry is what the scheduler refreshes against, so a
    stored value longer than the real one means requests failing on an expired
    token that the service believes is live.

    Returns a `(token_expires_at, refresh_token_expires_at)` pair, both aware
    UTC, measured from now.
    """
    now = utcnow()
    access = _lifetime(
        getattr(auth_client, "expires_in", None),
        FALLBACK_ACCESS_TOKEN_LIFETIME,
        "expires_in",
    )
    refresh = _lifetime(
        getattr(auth_client, "x_refresh_token_expires_in", None),
        FALLBACK_REFRESH_TOKEN_LIFETIME,
        "x_refresh_token_expires_in",
    )
    return now + access, now + refresh


def get_token_status(
    token_expires_at: datetime | None,
    token_status_db: str | None = None,
) -> TokenStatus:
    """
    Calculate token status for display.

    Args:
        token_expires_at: Token expiration timestamp
        token_status_db: Status from database ("active", "disconnected", etc.)

    Returns:
        TokenStatus with status, label, CSS class, and expiration display
    """
    # Check for disconnected
    if token_status_db == "disconnected" or token_expires_at is None:
        return TokenStatus(
            status="disconnected",
            label="Disconnected",
            css_class="bg-secondary",
            expires_display="Not connected",
        )

    now = utcnow()
    token_expires_at = as_utc(token_expires_at)

    # Check if expired
    if token_expires_at <= now:
        delta = now - token_expires_at
        expires_display = _format_time_ago(delta)
        return TokenStatus(
            status="expired",
            label="Expired",
            css_class="bg-danger",
            expires_display=f"Expired {expires_display}",
        )

    # Calculate time until expiration
    delta = token_expires_at - now

    # Check if expiring soon (within 30 minutes)
    if delta <= timedelta(minutes=30):
        expires_display = _format_time_remaining(delta)
        return TokenStatus(
            status="expiring_soon",
            label="Expiring Soon",
            css_class="bg-warning text-dark",
            expires_display=f"Expires in {expires_display}",
        )

    # Active
    expires_display = _format_time_remaining(delta)
    return TokenStatus(
        status="active",
        label="Active",
        css_class="bg-success",
        expires_display=f"Expires in {expires_display}",
    )


def get_refresh_token_status(
    refresh_token_expires_at: datetime | None,
    token_status_db: str | None = None,
) -> RefreshTokenStatus:
    """
    Calculate refresh token status for display.

    Args:
        refresh_token_expires_at: Refresh token expiration timestamp
        token_status_db: Status from database ("active", "disconnected", etc.)

    Returns:
        RefreshTokenStatus with status, display text, and CSS class
    """
    if token_status_db == "disconnected" or refresh_token_expires_at is None:
        return RefreshTokenStatus(
            refresh_status="unknown",
            refresh_expires_display="Unknown",
            refresh_css_class="bg-secondary",
        )

    now = utcnow()
    refresh_token_expires_at = as_utc(refresh_token_expires_at)

    # Check if expired
    if refresh_token_expires_at <= now:
        delta = now - refresh_token_expires_at
        days = delta.days
        return RefreshTokenStatus(
            refresh_status="expired",
            refresh_expires_display=f"Expired {days}d ago",
            refresh_css_class="bg-danger",
        )

    # Calculate days remaining
    delta = refresh_token_expires_at - now
    days = delta.days

    if days > 30:
        return RefreshTokenStatus(
            refresh_status="healthy",
            refresh_expires_display=f"Expires in {days}d",
            refresh_css_class="bg-success",
        )
    elif days >= 7:
        return RefreshTokenStatus(
            refresh_status="warning",
            refresh_expires_display=f"Expires in {days}d",
            refresh_css_class="bg-warning text-dark",
        )
    else:
        return RefreshTokenStatus(
            refresh_status="critical",
            refresh_expires_display=f"Expires in {days}d",
            refresh_css_class="bg-danger",
        )


def _format_time_remaining(delta: timedelta) -> str:
    """Format time remaining as human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds} seconds"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours} hour{'s' if hours != 1 else ''}"


def _format_time_ago(delta: timedelta) -> str:
    """Format time ago as human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return "just now"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = total_seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
