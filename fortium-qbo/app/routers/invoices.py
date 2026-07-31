"""Invoice endpoints using QBO SDK."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.query_dates import parse_date_param

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/", response_model=list[dict[str, Any]])
async def list_invoices(
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Filter from TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(
        None, description="Filter to TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List invoices, optionally filtered by date range."""
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        return await qbo.get_invoices(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
            max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/by-doc-number/{doc_number}", response_model=dict[str, Any])
async def get_invoice_by_doc_number(
    doc_number: str,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific invoice by DocNumber (e.g., "10044")."""
    try:
        invoice = await qbo.get_invoice_by_doc_number(company_id, doc_number)
        if not invoice:
            raise HTTPException(status_code=404, detail=f"Invoice with DocNumber '{doc_number}' not found")
        return invoice
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.delete("/{invoice_id}", response_model=dict[str, Any])
async def delete_invoice(
    invoice_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Delete a specific invoice by ID."""
    try:
        return await qbo.delete_invoice(company_id, invoice_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/{invoice_id}", response_model=dict[str, Any])
async def get_invoice(
    invoice_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific invoice by internal QBO ID."""
    try:
        invoice = await qbo.get_invoice_by_id(company_id, invoice_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return invoice
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/trailing-12m/summary")
async def get_trailing_12m_summary(
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get trailing 12 months invoice summary with monthly totals."""
    try:
        end_date = datetime.utcnow()
        start_date = datetime(end_date.year - 1, end_date.month, 1)

        invoices = await qbo.get_invoices(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            max_results=1000,
        )

        # Aggregate by month
        monthly_totals: dict[str, dict[str, Any]] = {}
        for inv in invoices:
            txn_date = inv.get("TxnDate", "")
            if txn_date:
                month_key = txn_date[:7]  # YYYY-MM
                if month_key not in monthly_totals:
                    monthly_totals[month_key] = {"total": 0.0, "count": 0}
                monthly_totals[month_key]["total"] += float(inv.get("TotalAmt", 0))
                monthly_totals[month_key]["count"] += 1

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "monthly_totals": dict(sorted(monthly_totals.items())),
            "grand_total": sum(m["total"] for m in monthly_totals.values()),
            "total_invoices": sum(m["count"] for m in monthly_totals.values()),
            "fetched_at": datetime.utcnow().isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
