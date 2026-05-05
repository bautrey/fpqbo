"""JournalEntry endpoints."""
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/journal-entries",
    tags=["journal-entries"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_journal_entries(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all journal entries."""
    try:
        return await qbo.get_journal_entries(company_id=company_id, max_results=max_results)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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
    try:
        return await qbo.create_journal_entry(company_id, entry_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.post("/{entity_id}/void", response_model=dict[str, Any])
async def void_journal_entry(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Void a specific journal entry by ID."""
    try:
        return await qbo.void_journal_entry(company_id, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
