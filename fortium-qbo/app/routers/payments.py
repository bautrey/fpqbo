"""Payment endpoints using QBO SDK."""

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
from app.utils.query_dates import parse_date_param

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_payments(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Filter from TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(
        None, description="Filter to TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List payments, optionally filtered by date range.

    One page of a result set. Page with `offset`, and read `X-Has-More` /
    `X-Total-Count` to tell a partial answer from a whole one.
    """
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        page = await qbo.get_payments(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
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
async def create_payment(
    company_id: int = Query(..., description="QBO company ID"),
    payment_data: dict[str, Any] = Body(..., description="Payment data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Record a client payment in QBO, applied to one or more invoices.

    Always creates. 400, with nothing sent to QBO, for any field outside the
    example's (including `Id` and `SyncToken`), a missing `CustomerRef`,
    `TotalAmt` or `Line`, or a line with no `LinkedTxn`.
    `DepositToAccountRef` must be a Bank or Other Current Asset account, or
    omitted for Undeposited Funds; also accepted are `PaymentRefNum`,
    `PaymentMethodRef`, `ARAccountRef` and `ExchangeRate`. QBO's refusal text
    arrives in the 500's `detail`.

    Example body:
    {
        "CustomerRef": {"value": "1400"},
        "TotalAmt": 12500.00,
        "TxnDate": "2026-10-28",
        "DepositToAccountRef": {"value": "4"},
        "PrivateNote": "payouts:zrg-collection:abc123",
        "Line": [
            {"Amount": 12500.00, "LinkedTxn": [{"TxnId": "97001", "TxnType": "Invoice"}]}
        ]
    }
    """
    return await run_qbo_write(
        qbo.create_payment(company_id, payment_data), entity="payment"
    )


@router.post("/{entity_id}/void", response_model=dict[str, Any])
async def void_payment(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Void a customer payment, reopening the invoices it paid.

    QBO keeps the record, zeroes `TotalAmt`, empties `Line` and writes
    "Voided" into `PrivateNote`. Idempotent: a payment already voided comes
    back 200 with `already_voided: true`. 404 when no payment with that id
    exists in this company.
    """
    return await run_qbo_write(
        qbo.void_payment(company_id, entity_id),
        entity="payment void",
        # No request body: a KeyError/TypeError is our bug, a logged 500.
        has_body=False,
    )


@router.get("/{payment_id}", response_model=dict[str, Any])
async def get_payment(
    payment_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific payment by ID."""
    try:
        payment = await qbo.get_payment_by_id(company_id, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        return payment
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
