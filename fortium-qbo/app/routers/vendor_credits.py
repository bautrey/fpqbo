"""VendorCredit endpoints."""
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.routers._qbo_write import run_qbo_write
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/vendor-credits",
    tags=["vendor-credits"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_vendor_credits(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all vendor credits."""
    try:
        return await qbo.get_vendor_credits(company_id=company_id, max_results=max_results)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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
