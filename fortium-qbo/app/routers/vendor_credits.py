"""VendorCredit endpoints."""
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
    prefix="/vendor-credits",
    tags=["vendor-credits"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_vendor_credits(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List vendor credits.

    This is one page of a result set, not the whole ledger. Page with
    `offset`, and read `X-Has-More` / `X-Total-Count` to tell a partial
    answer from a whole one.
    """
    try:
        page = await qbo.get_vendor_credits(
            company_id=company_id,
            max_results=max_results,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
    apply_paging_headers(response, page)
    return page.rows


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_vendor_credit(
    company_id: int = Query(..., description="QBO company ID"),
    credit_data: dict[str, Any] = Body(..., description="VendorCredit data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create a vendor credit in QBO.

    Example body:
    {
        "VendorRef": {"value": "123"},
        "TxnDate": "2026-04-30",
        "DocNumber": "VC-001",
        "PrivateNote": "Refund for overbilling",
        "TotalAmt": 250.00,
        "APAccountRef": {"value": "81"},
        "Line": [
            {
                "Amount": 250.00,
                "Description": "Credit memo",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "60"},
                    "ClassRef": {"value": "5000000000000123456"}
                }
            }
        ]
    }
    """
    return await run_qbo_write(
        qbo.create_vendor_credit(company_id, credit_data), entity="vendor credit"
    )


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_vendor_credit(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific vendor credit by ID."""
    try:
        result = await qbo.get_vendor_credit_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Vendor credit not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
