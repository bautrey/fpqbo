"""Customer endpoints using QBO SDK."""

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
    prefix="/customers",
    tags=["customers"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_customers(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only return active customers"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of customers.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_customers(
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
async def create_customer(
    company_id: int = Query(..., description="QBO company ID"),
    customer_data: dict[str, Any] = Body(..., description="Customer data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create a customer in QBO.

    Example body:
    {
        "DisplayName": "Acme Corp",
        "CompanyName": "Acme Corporation",
        "GivenName": "John",
        "FamilyName": "Doe",
        "PrimaryEmailAddr": {"Address": "john@acme.com"},
        "PrimaryPhone": {"FreeFormNumber": "555-123-4567"},
        "BillAddr": {
            "Line1": "123 Main St",
            "City": "San Francisco",
            "CountrySubDivisionCode": "CA",
            "PostalCode": "94105",
            "Country": "US"
        },
        "SalesTermRef": {"value": "3"},
        "CurrencyRef": {"value": "USD", "name": "United States Dollar"},
        "Notes": "Important customer",
        "Taxable": true,
        "Active": true
    }
    """
    return await run_qbo_write(
        qbo.create_customer(company_id, customer_data), entity="customer"
    )


@router.get("/{customer_id}", response_model=dict[str, Any])
async def get_customer(
    customer_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific customer by ID."""
    try:
        customer = await qbo.get_customer_by_id(company_id, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
