"""CompanyInfo and Preferences endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import verify_api_key
from app.services.qbo_service import QBOService, get_qbo_service

router = APIRouter(
    prefix="/company",
    tags=["company"],
    dependencies=[Depends(verify_api_key)],
)


def _get_service(db: Session = Depends(get_db)) -> QBOService:
    return get_qbo_service(db)


@router.get("/info", response_model=dict[str, Any])
async def get_company_info(
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get company info."""
    try:
        result = await qbo.get_company_info(company_id)
        if not result:
            raise HTTPException(status_code=404, detail="Company info not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")


@router.get("/preferences", response_model=dict[str, Any])
async def get_preferences(
    company_id: int = Query(..., description="QBO company ID"),
    qbo: QBOService = Depends(_get_service),
) -> dict[str, Any]:
    """Get company preferences."""
    try:
        result = await qbo.get_preferences(company_id)
        if not result:
            raise HTTPException(status_code=404, detail="Preferences not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
