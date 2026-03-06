"""BillPayment endpoints."""
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/bill-payments",
    tags=["bill-payments"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_bill_payments(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all bill payments."""
    try:
        return await qbo.get_bill_payments(company_id=company_id, max_results=max_results)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/by-bill/{bill_id}", response_model=list[dict[str, Any]])
async def get_bill_payments_by_bill(
    bill_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """Get bill payments linked to a specific bill."""
    try:
        return await qbo.get_bill_payments_by_bill_id(company_id, bill_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_bill_payment(
    company_id: int = Query(..., description="QBO company ID"),
    payment_data: dict[str, Any] = Body(..., description="BillPayment data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create a bill payment in QBO.

    Example body:
    {
        "PayType": "Check",
        "VendorRef": {"value": "123"},
        "TotalAmt": 1234.56,
        "CheckPayment": {"BankAccountRef": {"value": "456"}},
        "Line": [{"Amount": 1234.56, "LinkedTxn": [{"TxnId": "789", "TxnType": "Bill"}]}],
        "APAccountRef": {"value": "81"}
    }
    """
    try:
        return await qbo.create_bill_payment(company_id, payment_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_bill_payment(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific bill payment by ID."""
    try:
        result = await qbo.get_bill_payment_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Bill payment not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
