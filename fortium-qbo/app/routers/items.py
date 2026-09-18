"""Item endpoints."""
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.routers._qbo_write import run_qbo_write
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.paging import (
    MAX_RESULTS_DESCRIPTION,
    OFFSET_DESCRIPTION,
    PAGING_RESPONSE_HEADERS,
    QBO_MAX_PAGE_SIZE,
    apply_paging_headers,
)

router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_items(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active items"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of items.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_items(
            company_id=company_id,
            active_only=active_only,
            max_results=max_results,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
    apply_paging_headers(response, page)
    return page.rows


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_item(
    company_id: int = Query(..., description="QBO company ID"),
    item_data: dict[str, Any] = Body(..., description="Item data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create an item (product/service) in QBO.

    Account Refs must point at accounts in the target company — a production
    account Id won't exist in the sandbox, so resolve the sandbox account Id
    (via GET /api/accounts/) before creating.

    Example body:
    {
        "Name": "Administrative and Technology Fee",
        "Type": "Service",
        "Description": "Administrative and Technology Fee",
        "IncomeAccountRef": {"value": "42", "name": "Administrative and Technology Fee"},
        "Taxable": false,
        "Active": true
    }
    """
    return await run_qbo_write(
        qbo.create_item(company_id, item_data), entity="item"
    )


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_item(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific item by ID."""
    try:
        result = await qbo.get_item_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Item not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
