"""Token status utility functions."""

from datetime import datetime, timedelta
from typing import NamedTuple


class TokenStatus(NamedTuple):
    """Token status with display information."""
    status: str       # "active", "expiring_soon", "expired", "disconnected"
    label: str        # Human-readable label
    css_class: str    # Bootstrap badge class
    expires_display: str  # Human-readable expiration


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
