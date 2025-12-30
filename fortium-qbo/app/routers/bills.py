"""Bill endpoints using QBO SDK."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(prefix="/bills", tags=["bills"])


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_bills(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all bills."""
    try:
        return await qbo.get_bills(
            company_id=company_id,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{bill_id}", response_model=dict[str, Any])
async def get_bill(
    bill_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific bill by ID."""
    try:
        bill = await qbo.get_bill_by_id(company_id, bill_id)
        if not bill:
            raise HTTPException(status_code=404, detail="Bill not found")
        return bill
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
