"""QBO Reports endpoints (Trial Balance, Balance Sheet, P&L)."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(prefix="/reports", tags=["reports"])


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
    as_of_date: datetime | None = Query(None, description="Balance sheet date"),
    accounting_method: str = Query("Accrual", description="Accrual or Cash"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """
    Get Balance Sheet report.

    Returns QBO's standard Balance Sheet report showing assets, liabilities, and equity.
    """
    try:
        return await qbo.get_balance_sheet(
            company_id=company_id,
            as_of_date=as_of_date,
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
