"""Tax entity endpoints (TaxAgency, TaxCode, TaxRate)."""
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

router = APIRouter(
    prefix="/tax",
    tags=["tax"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


# --- TaxAgency ---

@router.get(
    "/agencies",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_tax_agencies(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of tax agencies.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_tax_agencies(
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


@router.get("/agencies/{entity_id}", response_model=dict[str, Any])
async def get_tax_agency(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific tax agency by ID."""
    try:
        result = await qbo.get_tax_agency_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Tax agency not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- TaxCode ---

@router.get(
    "/codes",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_tax_codes(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of tax codes.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_tax_codes(
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


@router.get("/codes/{entity_id}", response_model=dict[str, Any])
async def get_tax_code(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific tax code by ID."""
    try:
        result = await qbo.get_tax_code_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Tax code not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- TaxRate ---

@router.get(
    "/rates",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_tax_rates(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of tax rates.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_tax_rates(
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


@router.get("/rates/{entity_id}", response_model=dict[str, Any])
async def get_tax_rate(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific tax rate by ID."""
    try:
        result = await qbo.get_tax_rate_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Tax rate not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
