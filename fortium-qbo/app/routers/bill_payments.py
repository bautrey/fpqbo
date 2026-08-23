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


@router.post("/{entity_id}/void", response_model=dict[str, Any])
async def void_bill_payment(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Void a bill payment, e.g. when the underlying transfer was cancelled.

    QBO keeps the record and zeroes `TotalAmt`, which reopens the bill the
    payment was closing. That is the point: a payment that never happened
    should not leave a bill looking settled.

    Idempotent. A payment already voided comes back 200 with
    `already_voided: true` rather than an error, because the caller is a
    reconciler that re-runs over the same set.

    Wrapped in `run_qbo_write`, which the older void and delete endpoints are
    not. Their carve-out exists because the helper maps `ValueError` to 400
    and not-found used to be a `ValueError`, so wrapping them would have
    turned a 404 into a 400. Since #15 not-found is `QboNotFound`, an
    `HTTPException` the helper re-raises untouched — and the helper logs its
    500s with a traceback, which a hand-rolled clause here would not.
    """
    return await run_qbo_write(
        qbo.void_bill_payment(company_id, entity_id),
        entity="bill payment void",
        # No request body, so a KeyError/TypeError here cannot be the
        # caller's malformed payload — it is a bug in ours, and must be a
        # logged 500 rather than an unlogged 400 the caller cannot act on.
        has_body=False,
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
