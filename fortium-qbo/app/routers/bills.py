"""Bill endpoints using QBO SDK."""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from quickbooks.exceptions import ValidationException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.routers._qbo_write import run_qbo_write
from app.services.qbo_service import QBOService, get_qbo_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/bills",
    tags=["bills"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_bills(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all bills."""
    try:
        return await qbo.get_bills(
            company_id=company_id,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_bill(
    company_id: int = Query(..., description="QBO company ID"),
    bill_data: dict[str, Any] = Body(..., description="Bill data"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Create a bill in QBO.

    Example body:
    {
        "VendorRef": {"value": "123"},
        "TxnDate": "2026-04-30",
        "DueDate": "2026-05-30",
        "DocNumber": "INV-001-456-Doe",
        "PrivateNote": "Optional memo",
        "APAccountRef": {"value": "81"},
        "Line": [
            {
                "Amount": 1000.00,
                "Description": "Consulting services",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "60"},
                    "ClassRef": {"value": "5000000000000123456"},
                    "CustomerRef": {"value": "42"}
                }
            }
        ]
    }
    """
    return await run_qbo_write(
        qbo.create_bill(company_id, bill_data), entity="bill"
    )


@router.post("/{bill_id}", response_model=dict[str, Any])
async def update_bill(
    bill_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    sparse_payload: dict[str, Any] = Body(
        ...,
        description="Sparse update fields (must include SyncToken). "
                    "Id and sparse:true are injected server-side.",
    ),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Sparse-update a bill in QBO.

    Performs a sparse update via QBO's
    ``POST /v3/company/{realm}/bill?operation=update`` endpoint. The server
    injects ``Id`` and ``sparse: true`` into the payload — the client only
    needs to supply ``SyncToken`` plus whichever fields it wants to change
    (``Line``, ``TxnDate``, ``DueDate``, ``PrivateNote``, etc).

    Returns the updated Bill object from QBO.

    Errors:
    - 409 when QBO reports a SyncToken mismatch (error code 5310)
    - 500 for other QBO errors
    """
    logger.info(f"Updating bill {bill_id} for company_id={company_id}")
    try:
        return await qbo.update_bill(company_id, bill_id, sparse_payload)
    except ValidationException as e:
        if getattr(e, "error_code", 0) == 5310:
            raise HTTPException(
                status_code=409,
                detail=f"SyncToken mismatch: {e.message}. {e.detail}".strip(),
            )
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (KeyError, TypeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or missing field in bill payload: {e}",
        ) from e
    except Exception as e:
        logger.error("QBO write failed for bill: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}") from e


@router.delete("/{bill_id}", response_model=dict[str, Any])
async def delete_bill(
    bill_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Delete a specific bill by ID."""
    try:
        return await qbo.delete_bill(company_id, bill_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{bill_id}", response_model=dict[str, Any])
async def get_bill(
    bill_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific bill by ID."""
    try:
        bill = await qbo.get_bill_by_id(company_id, bill_id)
        if not bill:
            raise HTTPException(status_code=404, detail="Bill not found")
        return bill
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
