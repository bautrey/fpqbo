"""Token status utility functions."""

from datetime import datetime, timedelta
from typing import NamedTuple


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

    now = datetime.utcnow()

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

    now = datetime.utcnow()

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
