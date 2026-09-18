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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.delete("/{entity_id}", response_model=dict[str, Any])
async def delete_vendor_credit(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Delete a vendor credit in QBO.

    Mirrors `DELETE /api/bills/{bill_id}`, which existed while this did not —
    so a credit could be created and read and never removed (#35).

    **There is no void for this entity.** QuickBooks offers void for invoices,
    payments, bill payments and sales receipts; a vendor credit can only be
    deleted. A credit inside a closed period therefore cannot be neutralised
    through this API at all — QuickBooks refuses, and the refusal text is the
    answer. It arrives in the 500's `detail`, carrying QuickBooks' own error
    code and message, because that is the part worth reading:

        QBO API error: QB Exception 6240: <message>
        <detail>

    Note the exact prefix. The SDK maps 2000-4999 to ValidationException and
    renders those as "QB Validation Exception", but 6240 falls past that range
    into the bare QuickbooksException, which renders "QB Exception". A log rule
    or client matching the Validation form never fires on a closed period.

    Returns QuickBooks' delete response whole — typically
    `{"VendorCredit": {...}, "time": "..."}`. The entity is at
    `["VendorCredit"]`; nothing QuickBooks sent is stripped on the way out.
    404 when no credit with that id exists in this company.
    """
    return await run_qbo_write(
        qbo.delete_vendor_credit(company_id, entity_id),
        entity="vendor credit",
        has_body=False,
    )
