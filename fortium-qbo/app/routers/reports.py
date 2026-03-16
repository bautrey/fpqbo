"""QBO Reports endpoints (Trial Balance, Balance Sheet, P&L)."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

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
    start_date: datetime | None = Query(None, description="Report start date"),
    end_date: datetime | None = Query(None, description="Report end date"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Trial Balance report.

    Returns QBO's standard Trial Balance report with all account balances.
    """
    try:
        return await qbo.get_trial_balance(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            accounting_method=accounting_method,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/balance-sheet", response_model=dict[str, Any])
async def get_balance_sheet(
    company_id: int = Query(..., description="QBO company ID"),
    as_of_date: str | None = Query(None, description="Balance sheet date (YYYY-MM-DD)"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Balance Sheet report.

    Returns QBO's standard Balance Sheet report showing assets, liabilities, and equity.
    """
    try:
        # Parse string date to datetime for the service
        parsed_date = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else None
        return await qbo.get_balance_sheet(
            company_id=company_id,
            as_of_date=parsed_date,
            accounting_method=accounting_method,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/profit-and-loss", response_model=dict[str, Any])
async def get_profit_and_loss(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: datetime = Query(..., description="Report start date"),
    end_date: datetime = Query(..., description="Report end date"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Profit & Loss (Income Statement) report.

    Returns QBO's standard P&L report showing income, expenses, and net profit/loss.
    """
    try:
        return await qbo.get_profit_and_loss(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            accounting_method=accounting_method,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/general-ledger", response_model=dict[str, Any])
async def get_general_ledger(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    account: str | None = Query(None, description="Comma-separated account IDs to filter"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get General Ledger report.

    Returns all transactions grouped by account within a date range.
    Use `account` param to filter to specific accounts (comma-separated QBO account IDs).
    """
    try:
        return await qbo.get_general_ledger(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            account=account,
            accounting_method=accounting_method,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
