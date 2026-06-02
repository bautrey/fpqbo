"""Pages router for HTML template rendering."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AdminUser, ApiKey
from app.models.qbo_company import QboCompany
from app.services.session_service import verify_session
from app.utils.token_status import get_refresh_token_status, get_token_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pages"])

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
async def login_page(request: Request):
    """
    Render login page with Google Sign-In button.

    Public endpoint - no authentication required.

    Returns:
        HTML login page template
    """
    return templates.TemplateResponse(request, "login.html")


@router.get("/")
async def home_page(request: Request):
    """
    Render authenticated home page.

    Checks for valid session cookie:
    - If authenticated: Show home page with user email
    - If not authenticated: Redirect to /login

    Returns:
        HTML home page if authenticated
        Redirect to /login if not authenticated
    """
    # Check for session cookie
    session_token = request.cookies.get("auth_session")

    if not session_token:
        logger.info("No session cookie, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Verify session
    email = verify_session(session_token)

    if not email:
        logger.info("Invalid session token, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Get user from database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            logger.warning(f"Session valid but user not in database: {email}")
            return RedirectResponse(url="/login", status_code=302)

        # Render home page with user context
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "user": admin_user,
            }
        )

    finally:
        db.close()


@router.get("/admin/companies")
async def companies_page(request: Request, message: str | None = None):
    """
    Render QBO companies management page.

    Requires authenticated admin session.
    Shows list of connected QBO companies with status.

    Query params:
        message: Flash message type ("connected", "disconnected", "refreshed", "refresh_failed")

    Returns:
        HTML companies page if authenticated
        Redirect to /login if not authenticated
    """
    # Check for session cookie
    session_token = request.cookies.get("auth_session")

    if not session_token:
        logger.info("No session cookie, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Verify session
    email = verify_session(session_token)

    if not email:
        logger.info("Invalid session token, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Get user and companies from database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            logger.warning(f"Session valid but user not in database: {email}")
            return RedirectResponse(url="/login", status_code=302)

        # Fetch all QBO companies
        companies = db.query(QboCompany).order_by(QboCompany.name).all()

        # Add token status info to each company for template
        for company in companies:
            company.token_status_info = get_token_status(
                company.token_expires_at,
                company.token_status,
            )
            company.refresh_token_status_info = get_refresh_token_status(
                company.refresh_token_expires_at,
                company.token_status,
            )

        # Render companies page
        return templates.TemplateResponse(
            request,
            "admin/companies.html",
            {
                "user": admin_user,
                "companies": companies,
                "message": message,
                "qbo_configured": settings.qbo_configured,
                "qbo_us_configured": settings.qbo_us_configured,
                "qbo_ca_configured": settings.qbo_ca_configured,
            }
        )

    finally:
        db.close()


@router.get("/admin/api-keys")
async def api_keys_page(request: Request, message: str | None = None):
    """
    Render API keys management page.

    Requires authenticated admin session.
    Shows list of API keys with status and actions.

    Query params:
        message: Flash message type ("created", "revoked", "reactivated")

    Returns:
        HTML API keys page if authenticated
        Redirect to /login if not authenticated
    """
    # Check for session cookie
    session_token = request.cookies.get("auth_session")

    if not session_token:
        logger.info("No session cookie, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Verify session
    email = verify_session(session_token)

    if not email:
        logger.info("Invalid session token, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Get user, companies, and API keys from database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            logger.warning(f"Session valid but user not in database: {email}")
            return RedirectResponse(url="/login", status_code=302)

        # Fetch all companies (for the create modal)
        companies = db.query(QboCompany).order_by(QboCompany.name).all()

        # Fetch all API keys with their companies
        api_keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()

        # Render API keys page
        return templates.TemplateResponse(
            request,
            "admin/api_keys.html",
            {
                "user": admin_user,
                "companies": companies,
                "api_keys": api_keys,
                "message": message,
            }
        )

    finally:
        db.close()
