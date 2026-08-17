"""RecurringTransaction endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/recurring-transactions",
    tags=["recurring-transactions"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_recurring_transactions(
    company_id: int = Query(..., description="QBO company ID"),
    # ge=1 for the same reason the paged endpoints have it: max_results=0 is
    # falsy in ListMixin.all's `if max_results:`, so the MAXRESULTS clause is
    # dropped and QuickBooks answers with its own default inside a 200 —
    # fewer rows than asked for, with nothing saying so.
    #
    # Fourteen other unpaged endpoints share this defect and are NOT fixed
    # here — tax.py, reference.py, items.py, employees.py, departments.py,
    # customers.py, attachments.py all still declare Query(1000, le=1000).
    # They are the #11 group and are tracked there; this one is guarded
    # because it is the endpoint this PR touches and declares safe.
    max_results: int = Query(1000, ge=1, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all recurring transactions."""
    try:
        return await qbo.get_recurring_transactions(company_id=company_id, max_results=max_results)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{entity_id}", response_model=dict[str, Any])
async def get_recurring_transaction(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific recurring transaction by ID."""
    try:
        result = await qbo.get_recurring_transaction_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Recurring transaction not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
