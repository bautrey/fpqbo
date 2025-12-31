"""Account endpoints using QBO SDK."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_accounts(
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only return active accounts"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all accounts (chart of accounts)."""
    try:
        return await qbo.get_accounts(
            company_id=company_id,
            active_only=active_only,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/by-number/{account_number}", response_model=dict[str, Any])
async def get_account_by_number(
    account_number: str,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get an account by its account number."""
    try:
        account = await qbo.get_account_by_number(company_id, account_number)
        if not account:
            raise HTTPException(
                status_code=404, detail=f"Account {account_number} not found"
            )
        return account
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{account_id}", response_model=dict[str, Any])
async def get_account(
    account_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific account by ID."""
    try:
        account = await qbo.get_account_by_id(company_id, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return account
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
