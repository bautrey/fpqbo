"""RecurringTransaction endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.paging import (
    MAX_RESULTS_DESCRIPTION,
    PAGING_RESPONSE_HEADERS,
    QBO_MAX_PAGE_SIZE,
    apply_paging_headers,
)

router = APIRouter(
    prefix="/recurring-transactions",
    tags=["recurring-transactions"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_recurring_transactions(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    # ge=1 for the same reason the paged endpoints have it: max_results=0 is
    # falsy in ListMixin.all's `if max_results:`, so the MAXRESULTS clause is
    # dropped and QuickBooks answers with its own default inside a 200 —
    # fewer rows than asked for, with nothing saying so.
    #
    # The fourteen other endpoints this comment used to say were unguarded
    # are guarded now: every list endpoint in the service declares
    # ge=1, le=QBO_MAX_PAGE_SIZE. That was the #11 group.
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List every recurring transaction, and say whether that is all of them.

    Not paged and cannot be (#20): rows arrive shaped `{"JournalEntry": ...}`
    with no top-level `Id`, so ordering by Id is unavailable and an offset
    would return duplicates forever. `X-Total-Count` and `X-Has-More` are
    sent; `X-Next-Offset` is not. In production the connected companies hold
    14, 0, 0 and 0 of these, so the ceiling is nowhere near.
    """
    try:
        page = await qbo.get_recurring_transactions(
            company_id=company_id,
            max_results=max_results,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
    apply_paging_headers(response, page)
    return page.rows


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_recurring_transaction(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific recurring transaction by ID."""
    try:
        result = await qbo.get_recurring_transaction_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Recurring transaction not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
