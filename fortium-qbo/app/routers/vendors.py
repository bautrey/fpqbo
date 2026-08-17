"""Vendor endpoints using QBO SDK."""

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
    prefix="/vendors",
    tags=["vendors"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_vendors(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only return active vendors"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List vendors.

    This is one page of a result set. Page with `offset`, and read
    `X-Has-More` / `X-Total-Count` to tell a partial answer from a whole one.
    """
    try:
        page = await qbo.get_vendors(
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
async def create_vendor(
    company_id: int = Query(..., description="QBO company ID"),
    vendor_data: dict[str, Any] = Body(..., description="Vendor data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create a vendor in QBO.

    Example body:
    {
        "DisplayName": "Office Supplies Inc",
        "CompanyName": "Office Supplies Inc.",
        "GivenName": "Jane",
        "FamilyName": "Smith",
        "PrimaryEmailAddr": {"Address": "jane@officesupplies.com"},
        "PrimaryPhone": {"FreeFormNumber": "555-987-6543"},
        "BillAddr": {
            "Line1": "456 Oak Ave",
            "City": "Austin",
            "CountrySubDivisionCode": "TX",
            "PostalCode": "73301",
            "Country": "US"
        },
        "TermRef": {"value": "3"},
        "CurrencyRef": {"value": "USD", "name": "United States Dollar"},
        "TaxIdentifier": "12-3456789",
        "AcctNum": "VENDOR-001",
        "PrintOnCheckName": "Office Supplies Inc.",
        "Active": true,
        "Notes": "Preferred vendor"
    }
    """
    return await run_qbo_write(
        qbo.create_vendor(company_id, vendor_data), entity="vendor"
    )


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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
