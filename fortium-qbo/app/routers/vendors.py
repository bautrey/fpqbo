"""Vendor endpoints using QBO SDK."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_vendors(
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only return active vendors"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all vendors."""
    try:
        return await qbo.get_vendors(
            company_id=company_id,
            active_only=active_only,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{vendor_id}", response_model=dict[str, Any])
async def get_vendor(
    vendor_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific vendor by ID."""
    try:
        vendor = await qbo.get_vendor_by_id(company_id, vendor_id)
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return vendor
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
