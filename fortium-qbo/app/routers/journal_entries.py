"""JournalEntry endpoints."""
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
    prefix="/journal-entries",
    tags=["journal-entries"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_journal_entries(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List journal entries.

    This is one page of a result set, not the whole ledger. Page with
    `offset`, and read `X-Has-More` / `X-Total-Count` to tell a partial
    answer from a whole one.
    """
    try:
        page = await qbo.get_journal_entries(
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


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_journal_entry(
    company_id: int = Query(..., description="QBO company ID"),
    entry_data: dict[str, Any] = Body(..., description="JournalEntry data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create a journal entry in QBO.

    Example body:
    {
        "DocNumber": "WH2025",
        "TxnDate": "2026-04-01",
        "PrivateNote": "2025 State Tax Allocation - Withholding Applied",
        "Line": [
            {
                "Amount": 596114.06,
                "DetailType": "JournalEntryLineDetail",
                "Description": "WH credit",
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": "572"}
                }
            },
            {
                "Amount": 1275.15,
                "DetailType": "JournalEntryLineDetail",
                "Description": "Partner WH debit",
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "619"},
                    "Entity": {
                        "Type": "Vendor",
                        "EntityRef": {"value": "460"}
                    }
                }
            }
        ]
    }
    """
    return await run_qbo_write(
        qbo.create_journal_entry(company_id, entry_data), entity="journal entry"
    )


@router.post("/{entity_id}/void", response_model=dict[str, Any])
async def void_journal_entry(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Void a specific journal entry by ID."""
    try:
        return await qbo.void_journal_entry(company_id, entity_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_journal_entry(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific journal entry by ID."""
    try:
        result = await qbo.get_journal_entry_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
