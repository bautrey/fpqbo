"""Purchase endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.paging import (
    MAX_RESULTS_DESCRIPTION,
    OFFSET_DESCRIPTION,
    PAGING_RESPONSE_HEADERS,
    QBO_MAX_PAGE_SIZE,
    apply_paging_headers,
)
from app.utils.query_dates import parse_date_param

router = APIRouter(
    prefix="/purchases",
    tags=["purchases"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_purchases(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Filter from TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(
        None, description="Filter to TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List purchases, optionally filtered by date range.

    One page of a result set. Page with `offset`, and read `X-Has-More` /
    `X-Total-Count` to tell a partial answer from a whole one.
    """
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        page = await qbo.get_purchases(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
            max_results=max_results,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
    apply_paging_headers(response, page)
    return page.rows


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
