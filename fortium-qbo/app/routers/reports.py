"""QBO Reports endpoints (Trial Balance, Balance Sheet, P&L)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.query_dates import parse_date_param

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/trial-balance", response_model=dict[str, Any])
async def get_trial_balance(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Report start date (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(
        None, description="Report end date (YYYY-MM-DD or ISO 8601)"
    ),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Trial Balance report.

    Returns QBO's standard Trial Balance report with all account balances.
    """
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        return await qbo.get_trial_balance(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
            accounting_method=accounting_method,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/balance-sheet", response_model=dict[str, Any])
async def get_balance_sheet(
    company_id: int = Query(..., description="QBO company ID"),
    as_of_date: str | None = Query(
        None, description="Balance sheet date (YYYY-MM-DD or ISO 8601)"
    ),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Balance Sheet report.

    Returns QBO's standard Balance Sheet report showing assets, liabilities, and equity.
    """
    # Parsed before the try: this used to run inside it, where a bad date raised
    # ValueError and came back out as a 404 "company not found"-shaped error.
    parsed_date = parse_date_param(as_of_date, field="as_of_date")
    try:
        return await qbo.get_balance_sheet(
            company_id=company_id,
            as_of_date=parsed_date,
            accounting_method=accounting_method,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/profit-and-loss", response_model=dict[str, Any])
async def get_profit_and_loss(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str = Query(..., description="Report start date (YYYY-MM-DD or ISO 8601)"),
    end_date: str = Query(..., description="Report end date (YYYY-MM-DD or ISO 8601)"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Profit & Loss (Income Statement) report.

    Returns QBO's standard P&L report showing income, expenses, and net profit/loss.

    Both dates are required — the report is meaningless without a window.
    """
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        return await qbo.get_profit_and_loss(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
            accounting_method=accounting_method,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/general-ledger", response_model=dict[str, Any])
async def get_general_ledger(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Start date (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD or ISO 8601)"),
    account: str | None = Query(None, description="Comma-separated account IDs to filter"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get General Ledger report.

    Returns all transactions grouped by account within a date range.
    Use `account` param to filter to specific accounts (comma-separated QBO account IDs).
    """
    # This endpoint forwards its dates to QBO as strings. Parse and re-emit them
    # in the format QBO wants, so an ISO timestamp works here too and a bad date
    # is a 422 from us rather than an opaque 500 relayed from Intuit.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        return await qbo.get_general_ledger(
            company_id=company_id,
            start_date=parsed_start.strftime("%Y-%m-%d") if parsed_start else None,
            end_date=parsed_end.strftime("%Y-%m-%d") if parsed_end else None,
            account=account,
            accounting_method=accounting_method,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
