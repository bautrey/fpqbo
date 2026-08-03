"""Purchase endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.query_dates import parse_date_param

router = APIRouter(
    prefix="/purchases",
    tags=["purchases"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_purchases(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Filter from TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(
        None, description="Filter to TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List purchases, optionally filtered by date range."""
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        return await qbo.get_purchases(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_purchase(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific purchase by ID."""
    try:
        result = await qbo.get_purchase_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Purchase not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
