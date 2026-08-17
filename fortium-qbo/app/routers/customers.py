"""Customer endpoints using QBO SDK."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.routers._qbo_write import run_qbo_write
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/customers",
    tags=["customers"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_customers(
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only return active customers"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all customers."""
    try:
        return await qbo.get_customers(
            company_id=company_id,
            active_only=active_only,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
