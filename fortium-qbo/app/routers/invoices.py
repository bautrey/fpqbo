"""Invoice endpoints using QBO SDK."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service
from app.utils.paging import (
    MAX_RESULTS_DESCRIPTION,
    OFFSET_DESCRIPTION,
    PAGING_RESPONSE_HEADERS,
    QBO_MAX_PAGE_SIZE,
    apply_paging_headers,
)
from app.utils.query_dates import parse_date_param

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_invoices(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    start_date: str | None = Query(
        None, description="Filter from TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    end_date: str | None = Query(
        None, description="Filter to TxnDate (YYYY-MM-DD or ISO 8601)"
    ),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE, description=MAX_RESULTS_DESCRIPTION
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List invoices, optionally filtered by date range.

    One page of a result set. Page with `offset`, and read `X-Has-More` /
    `X-Total-Count` to tell a partial answer from a whole one.
    """
    # Parsed before the try: the catch-all below would rewrite a 422 into a 500.
    parsed_start = parse_date_param(start_date, field="start_date")
    parsed_end = parse_date_param(end_date, field="end_date")
    try:
        page = await qbo.get_invoices(
            company_id=company_id,
            start_date=parsed_start,
            end_date=parsed_end,
            max_results=max_results,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
    apply_paging_headers(response, page)
    return page.rows


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
    """Get trailing 12 months invoice summary with monthly totals.

    The aggregate is computed over every invoice in the window, not the first
    page of them. It used to read a single 1000-row page and report the sum of
    that page as `grand_total` — against a company invoicing past 1000 a year
    that is a wrong dollar figure served as a clean 200. `complete` states
    whether the walk reached the end of the result set.
    """
    end_date = datetime.utcnow()
    start_date = datetime(end_date.year - 1, end_date.month, 1)

    # Only the fetch is caught. The `except ValueError` below is the
    # unknown-company signal from the service and is answered with a 404; with
    # the aggregation inside the try, a TotalAmt QBO returned as something
    # float() will not take was also a ValueError and also became a 404 —
    # "no such company" to anything routing on the status code. The walk now
    # reaches 20,000 invoices where it used to stop at 1,000, so there are
    # twenty times as many values to trip over.
    try:
        page = await qbo.get_all_invoices(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")

    # Aggregate by month
    monthly_totals: dict[str, dict[str, Any]] = {}
    for inv in page.rows:
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
        # False when the page budget ran out before the result set did, so
        # a partial aggregate is never read as the whole year.
        "complete": not page.has_more,
        "invoices_in_window": page.total,
        "fetched_at": datetime.utcnow().isoformat(),
    }
