"""API key management endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import RequireAdmin, generate_api_key
from app.models import ApiKey, QboCompany
from app.utils.clock import utcnow

router = APIRouter(prefix="/admin/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    """Request body for creating an API key."""

    name: str
    company_id: int


class CreateApiKeyResponse(BaseModel):
    """Response with the new API key (only shown once)."""

    id: int
    name: str
    key_prefix: str
    api_key: str  # Full key - only returned on creation
    company_id: int
    company_name: str
    message: str = "Save this API key now. It will not be shown again."


class ApiKeyInfo(BaseModel):
    """API key info (without the actual key)."""

    id: int
    name: str
    key_prefix: str
    company_id: int
    company_name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None


@router.post("/", response_model=CreateApiKeyResponse)
async def create_api_key(
    request: CreateApiKeyRequest,
    admin: RequireAdmin,
    db: Session = Depends(get_db),
) -> CreateApiKeyResponse:
    """
    Create a new API key for a QBO company.

    Requires admin authentication.
    The full API key is only returned once - save it securely.
    """
    # Verify company exists
    company = db.execute(
        select(QboCompany).where(QboCompany.id == request.company_id)
    ).scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Generate the key
    full_key, key_hash, key_prefix = generate_api_key()

    # Create the API key record
    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=request.name,
        company_id=request.company_id,
        is_active=True,
        created_at=utcnow(),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return CreateApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        api_key=full_key,
        company_id=company.id,
        company_name=company.name,
    )


@router.get("/", response_model=list[ApiKeyInfo])
async def list_api_keys(
    admin: RequireAdmin,
    company_id: int | None = Query(None, description="Filter by company ID"),
    db: Session = Depends(get_db),
) -> list[ApiKeyInfo]:
    """
    List all API keys.

    Requires admin authentication.
    Optionally filter by company_id.
    """
    query = select(ApiKey).join(QboCompany)

    if company_id:
        query = query.where(ApiKey.company_id == company_id)

    query = query.order_by(ApiKey.created_at.desc())

    api_keys = db.execute(query).scalars().all()

    return [
        ApiKeyInfo(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            company_id=key.company_id,
            company_name=key.company.name,
            is_active=key.is_active,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
        )
        for key in api_keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: int,
    admin: RequireAdmin,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Revoke an API key.

    Requires admin authentication.
    This deactivates the key, not deletes it (for audit trail).
    """
    api_key = db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    ).scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="API key already revoked")

    api_key.is_active = False
    db.commit()

    return {
        "message": "API key revoked",
        "key_id": key_id,
        "key_prefix": api_key.key_prefix,
        "name": api_key.name,
    }


@router.post("/{key_id}/reactivate")
async def reactivate_api_key(
    key_id: int,
    admin: RequireAdmin,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Reactivate a revoked API key.

    Requires admin authentication.
    """
    api_key = db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    ).scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if api_key.is_active:
        raise HTTPException(status_code=400, detail="API key already active")

    api_key.is_active = True
    db.commit()

    return {
        "message": "API key reactivated",
        "key_id": key_id,
        "key_prefix": api_key.key_prefix,
        "name": api_key.name,
    }
