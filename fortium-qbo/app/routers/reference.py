"""Reference/config entity endpoints (CompanyCurrency, ExchangeRate, PaymentMethod, Term, TrackingClass, CustomerType)."""
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
    prefix="/reference",
    tags=["reference"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


# --- CompanyCurrency ---

@router.get(
    "/currencies",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_company_currencies(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of company currencies.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_company_currencies(
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


@router.get("/currencies/{entity_id}", response_model=dict[str, Any])
async def get_company_currency(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific company currency by ID."""
    try:
        result = await qbo.get_company_currency_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Company currency not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- ExchangeRate ---

@router.get(
    "/exchange-rates",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_exchange_rates(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List exchange rates, and say whether that is all of them.

    Not paged and cannot be: ExchangeRate is keyed by `AsOfDate` and the
    currency pair and carries no `Id`, so there is nothing stable to order
    by and an offset would return duplicates. `X-Total-Count` and
    `X-Has-More` are still sent; `X-Next-Offset` is not, because there is
    no cursor to give.

    `X-Has-More: true` means the answer stopped at `max_results` with rows
    left over, and there is no way through this API to reach them. Raising
    `max_results` is the only lever, and it caps at 1000 — which FOR-138
    already hits, so this endpoint is losing rows today.
    """
    try:
        page = await qbo.get_exchange_rates(
            company_id=company_id,
            max_results=max_results,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
    apply_paging_headers(response, page)
    return page.rows


# --- PaymentMethod ---

@router.get(
    "/payment-methods",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_payment_methods(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active payment methods"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of payment methods.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_payment_methods(
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


@router.get("/payment-methods/{entity_id}", response_model=dict[str, Any])
async def get_payment_method(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific payment method by ID."""
    try:
        result = await qbo.get_payment_method_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Payment method not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- Term ---

@router.get(
    "/terms",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_terms(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active terms"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of terms.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_terms(
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


@router.get("/terms/{entity_id}", response_model=dict[str, Any])
async def get_term(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific term by ID."""
    try:
        result = await qbo.get_term_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Term not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- TrackingClass ---

@router.get(
    "/classes",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_classes(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active classes"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of tracking classes.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_classes(
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


@router.get("/classes/{entity_id}", response_model=dict[str, Any])
async def get_class(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific tracking class by ID."""
    try:
        result = await qbo.get_class_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Class not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- CustomerType ---

@router.get(
    "/customer-types",
    response_model=list[dict[str, Any]],
    responses={200: {"headers": PAGING_RESPONSE_HEADERS}},
)
async def list_customer_types(
    response: Response,
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(
        QBO_MAX_PAGE_SIZE, ge=1, le=QBO_MAX_PAGE_SIZE,
        description=MAX_RESULTS_DESCRIPTION,
    ),
    offset: int = Query(0, ge=0, description=OFFSET_DESCRIPTION),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List one page of customer types.

    This is one page of a result set, not the whole set. Page with `offset`,
    and read `X-Has-More` / `X-Total-Count` to tell a partial answer from a
    whole one.
    """
    try:
        page = await qbo.get_customer_types(
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


@router.get("/customer-types/{entity_id}", response_model=dict[str, Any])
async def get_customer_type(
    entity_id: int,
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a specific customer type by ID."""
    try:
        result = await qbo.get_customer_type_by_id(company_id, entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Customer type not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
