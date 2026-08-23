"""Account endpoints using QBO SDK."""

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
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_accounts(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only return active accounts"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List the chart of accounts.

    This is one page of a result set, not the whole chart. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_accounts(
            company_id=company_id,
            active_only=active_only,
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
async def create_account(
    company_id: int = Query(..., description="QBO company ID"),
    account_data: dict[str, Any] = Body(..., description="Account data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create an account (chart-of-accounts entry) in QBO.

    Example body:
    {
        "Name": "Administrative and Technology Fee",
        "AccountType": "Income",
        "AcctNum": "400100",
        "Description": "Fees billed to clients",
        "Active": true
    }
    """
    return await run_qbo_write(
        qbo.create_account(company_id, account_data), entity="account"
    )


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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
