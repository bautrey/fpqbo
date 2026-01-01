"""Companies API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import verify_api_key, RequireApiKey
from app.models import ApiKey
from app.models.qbo_company import QboCompany

router = APIRouter(
    prefix="/companies",
    tags=["companies"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/")
async def list_companies(
    api_key: RequireApiKey,
    db: Session = Depends(get_db),
):
    """
    Get company information for the authenticated API key.

    Returns the company associated with this API key.
    """
    company = db.query(QboCompany).filter(
        QboCompany.id == api_key.company_id
    ).first()

    if not company:
        return {"companies": []}

    return {
        "companies": [
            {
                "id": company.id,
                "code": company.code,
                "name": company.name,
                "region": company.region,
                "realm_id": company.realm_id,
                "token_status": company.token_status,
            }
        ]
    }


@router.get("/me")
async def get_my_company(
    api_key: RequireApiKey,
    db: Session = Depends(get_db),
):
    """
    Get the company associated with this API key.

    Shorthand for /companies/ when you only need the single company.
    """
    company = db.query(QboCompany).filter(
        QboCompany.id == api_key.company_id
    ).first()

    if not company:
        return None

    return {
        "id": company.id,
        "code": company.code,
        "name": company.name,
        "region": company.region,
        "realm_id": company.realm_id,
        "token_status": company.token_status,
    }
