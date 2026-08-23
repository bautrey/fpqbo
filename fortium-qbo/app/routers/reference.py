"""Reference/config entity endpoints (CompanyCurrency, ExchangeRate, PaymentMethod, Term, TrackingClass, CustomerType)."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/reference",
    tags=["reference"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


# --- CompanyCurrency ---

@router.get("/currencies", response_model=list[dict[str, Any]])
async def list_company_currencies(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all company currencies."""
    try:
        return await qbo.get_company_currencies(company_id=company_id, max_results=max_results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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

@router.get("/exchange-rates", response_model=list[dict[str, Any]])
async def list_exchange_rates(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all exchange rates."""
    try:
        return await qbo.get_exchange_rates(company_id=company_id, max_results=max_results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


# --- PaymentMethod ---

@router.get("/payment-methods", response_model=list[dict[str, Any]])
async def list_payment_methods(
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active payment methods"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all payment methods."""
    try:
        return await qbo.get_payment_methods(company_id=company_id, active_only=active_only, max_results=max_results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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

@router.get("/terms", response_model=list[dict[str, Any]])
async def list_terms(
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active terms"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all terms."""
    try:
        return await qbo.get_terms(company_id=company_id, active_only=active_only, max_results=max_results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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

@router.get("/classes", response_model=list[dict[str, Any]])
async def list_classes(
    company_id: int = Query(..., description="QBO company ID"),
    active_only: bool = Query(True, description="Only active classes"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all tracking classes."""
    try:
        return await qbo.get_classes(company_id=company_id, active_only=active_only, max_results=max_results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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

@router.get("/customer-types", response_model=list[dict[str, Any]])
async def list_customer_types(
    company_id: int = Query(..., description="QBO company ID"),
    max_results: int = Query(1000, le=1000, description="Max results"),
    qbo: QBOService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all customer types."""
    try:
        return await qbo.get_customer_types(company_id=company_id, max_results=max_results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


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
