"""Vendor endpoints using QBO SDK."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.routers._qbo_write import request_id_header, run_qbo_write
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


@router.get("/lookup", response_model=list[dict[str, Any]])
async def lookup_vendors(
    company_id: int = Query(..., description="QBO company ID"),
    display_name: str | None = Query(None, description="Exact DisplayName"),
    email: str | None = Query(
        None, description="PrimaryEmailAddr, matched case-insensitively"
    ),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """Find vendors, active and inactive, by exact display name and/or email.

    At least one of `display_name` and `email` is required. When both are
    given a vendor must match both. 503 when the vendor list is too large to
    search completely, rather than a "no match" that may be wrong.
    """
    if display_name is None and email is None:
        raise HTTPException(
            status_code=400, detail="Provide display_name, email, or both."
        )
    # A blank email would match every vendor that has none, so a blank value
    # is refused rather than treated as a search.
    if any(v is not None and not v.strip() for v in (display_name, email)):
        raise HTTPException(
            status_code=400, detail="display_name and email cannot be blank."
        )
    try:
        return await qbo.lookup_vendors(
            company_id, display_name=display_name, email=email
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_vendor(
    company_id: int = Query(..., description="QBO company ID"),
    vendor_data: dict[str, Any] = Body(..., description="Vendor data"),
    request_id: str | None = Depends(request_id_header),
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
        qbo.create_vendor(company_id, vendor_data, request_id=request_id),
        entity="vendor",
    )


@router.post("/{vendor_id}/activate", response_model=dict[str, Any])
async def activate_vendor(
    vendor_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Make a vendor active. Returns it unchanged if it already is.

    409 on a SyncToken conflict (retry), 400 when QuickBooks refuses, for
    example a DisplayName now taken by an active vendor.
    """
    return await run_qbo_write(
        qbo.set_vendor_active(company_id, vendor_id, True),
        entity="vendor",
        has_body=False,
    )


@router.post("/{vendor_id}/deactivate", response_model=dict[str, Any])
async def deactivate_vendor(
    vendor_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Make a vendor inactive. Returns it unchanged if it already is.

    409 on a SyncToken conflict (retry), 400 when QuickBooks refuses.
    """
    return await run_qbo_write(
        qbo.set_vendor_active(company_id, vendor_id, False),
        entity="vendor",
        has_body=False,
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
