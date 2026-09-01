"""API Key authentication dependencies."""

import hashlib
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AdminUser, ApiKey, RequestLog
from app.services.session_service import verify_session
from app.utils.clock import utcnow


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        Tuple of (full_key, key_hash, key_prefix)
    """
    # Generate a secure random key: fqbo_<32 random hex chars>
    random_part = secrets.token_hex(16)
    full_key = f"fqbo_{random_part}"
    key_hash = hash_api_key(full_key)
    key_prefix = full_key[:12]  # "fqbo_" + first 7 chars of random
    return full_key, key_hash, key_prefix


async def verify_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
    company_id: Annotated[int | None, Query()] = None,
    db: Session = Depends(get_db),
) -> ApiKey:
    """
    Verify API key from X-API-Key header.

    Returns the ApiKey object if valid.
    Raises HTTPException 401 if missing or invalid.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
        )

    # Hash the provided key and look it up
    key_hash = hash_api_key(x_api_key)
    api_key = db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    ).scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key.",
        )

    # Update last_used_at
    api_key.last_used_at = utcnow()
    db.commit()

    # Log the request (status will be updated by middleware or manually)
    request.state.api_key = api_key

    # Enforce company scoping: an API key may only act on its own company.
    # company_id is declared above as a typed query param, so FastAPI/pydantic
    # coerces it identically to the endpoints — the auth check compares exactly
    # the value the endpoint will use, so crafted forms (" 2", "+2", "2\n") can't
    # parse differently here to slip past the check. A non-integer company_id is
    # rejected (422) by that same coercion before reaching this code, and
    # endpoints without company_id pass None and are already key-scoped.
    if company_id is not None and company_id != api_key.company_id:
        raise HTTPException(
            status_code=403,
            detail="API key is not authorized for this company.",
        )

    return api_key


async def log_request(
    request: Request,
    status_code: int,
    db: Session,
) -> None:
    """Log an API request for audit trail."""
    api_key = getattr(request.state, "api_key", None)

    log = RequestLog(
        api_key_id=api_key.id if api_key else None,
        endpoint=str(request.url.path),
        method=request.method,
        status_code=status_code,
    )
    db.add(log)
    db.commit()


# Type alias for dependency injection
RequireApiKey = Annotated[ApiKey, Depends(verify_api_key)]


async def require_admin(
    auth_session: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> AdminUser:
    """
    Verify admin session from cookie.

    Returns the AdminUser object if valid.
    Raises HTTPException 401 if missing or invalid.
    """
    if not auth_session:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please log in.",
        )

    email = verify_session(auth_session)
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again.",
        )

    admin_user = db.execute(
        select(AdminUser).where(AdminUser.email == email)
    ).scalar_one_or_none()

    if not admin_user:
        raise HTTPException(
            status_code=403,
            detail="User not authorized.",
        )

    return admin_user


# Type alias for admin auth dependency
RequireAdmin = Annotated[AdminUser, Depends(require_admin)]
