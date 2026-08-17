"""BillPayment endpoints."""
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
    prefix="/bill-payments",
    tags=["bill-payments"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_bill_payments(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List bill payments.

    This is one page of a result set, not the whole ledger. Page with
    `offset`, and read `X-Has-More` / `X-Total-Count` to tell a partial
    answer from a whole one.
    """
    try:
        page = await qbo.get_bill_payments(
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
    except HTTPException:
        raise
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

    Applying a VendorCredit to a Bill:
    Set TotalAmt = Bill.TotalAmt - VendorCredit.TotalAmt (the net cash leaving
    the bank). Provide a single Line entry whose LinkedTxn array contains both
    the Bill and the VendorCredit; QBO links them and zeroes the credit balance.

    Example (Bill 789 = $1000, VendorCredit 999 = $250, net check = $750):
    {
        "PayType": "Check",
        "VendorRef": {"value": "123"},
        "TotalAmt": 750.00,
        "CheckPayment": {"BankAccountRef": {"value": "456"}},
        "APAccountRef": {"value": "81"},
        "Line": [{
            "Amount": 750.00,
            "LinkedTxn": [
                {"TxnId": "789", "TxnType": "Bill"},
                {"TxnId": "999", "TxnType": "VendorCredit"}
            ]
        }]
    }

    This works because the LinkedTxn array is passed straight through to QBO;
    no special handling is needed in this endpoint.
    """
    return await run_qbo_write(
        qbo.create_bill_payment(company_id, payment_data), entity="bill payment"
    )


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
