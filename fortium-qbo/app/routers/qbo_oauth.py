"""QBO OAuth router for QuickBooks Online connection management."""

import logging
import random
import re
import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AdminUser
from app.models.qbo_company import QboCompany
from app.services.session_service import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["qbo-oauth"])

# Note: This router has NO prefix - routes are explicit:
# - /callback (registered with Intuit as redirect URI)
# - /api/qbo/connect, /api/qbo/companies/...


def _require_auth(request: Request) -> str:
    """
    Verify admin authentication from session cookie.

    Returns email if authenticated.
    Raises RedirectResponse to /login if not authenticated.
    """
    session_token = request.cookies.get("auth_session")
    if not session_token:
        raise RedirectResponse(url="/login", status_code=302)

    email = verify_session(session_token)
    if not email:
        raise RedirectResponse(url="/login", status_code=302)

    # Verify user exists in admin_users
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            raise RedirectResponse(url="/login", status_code=302)

        return email
    finally:
        db.close()


def _get_intuit_auth_client(
    region: str = "US",
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> AuthClient | None:
    """
    Create Intuit AuthClient with credentials for the specified region.

    Args:
        region: "US" or "CA"
        access_token: Optional existing access token
        refresh_token: Optional existing refresh token

    Returns:
        AuthClient configured for the region, or None if region not configured
    """
    credentials = settings.get_qbo_credentials(region)
    if not credentials:
        logger.error(f"QBO credentials not configured for region: {region}")
        return None

    client_id, client_secret = credentials

    # Both US and Canada now use production environment
    environment = "production"

    return AuthClient(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=refresh_token,
        environment=environment,
        redirect_uri=settings.qbo_callback_url,
    )


def _error_response(message: str, status_code: int = 400) -> HTMLResponse:
    """
    Generate HTML error page for OAuth failures.

    Per stakeholder decision: HTML error pages are best practice for browser OAuth flows.
    """
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>QuickBooks Connection Error - fortium-qbo</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="row justify-content-center">
                <div class="col-md-6">
                    <div class="card border-danger">
                        <div class="card-header bg-danger text-white">
                            <h5 class="mb-0">QuickBooks Connection Error</h5>
                        </div>
                        <div class="card-body">
                            <p class="card-text">{message}</p>
                            <a href="/admin/companies" class="btn btn-primary">Back to Companies</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=status_code)


def _generate_company_code(db, company_name: str) -> str:
    """
    Generate unique company code.

    Format: First 3 chars of company name (uppercase) + "-" + 3 random digits
    Examples: "FOR-482", "TES-127", "ABC-951"

    Ensures uniqueness by checking for collisions.
    """
    # Extract first 3 alphanumeric characters
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', company_name)
    prefix = clean_name[:3].upper() if len(clean_name) >= 3 else clean_name.upper().ljust(3, 'X')

    # Try to generate unique code (max 10 attempts)
    for _ in range(10):
        suffix = f"{random.randint(0, 999):03d}"
        code = f"{prefix}-{suffix}"

        # Check for collision
        existing = db.query(QboCompany).filter(QboCompany.code == code).first()
        if not existing:
            return code

    # Fallback: use timestamp-based suffix
    import time
    suffix = str(int(time.time()))[-3:]
    return f"{prefix}-{suffix}"


async def _fetch_company_name(realm_id: str, access_token: str) -> str:
    """Fetch company name from QBO Company Info API."""
    url = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}/companyinfo/{realm_id}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                params={"minorversion": "69"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("CompanyInfo", {}).get("CompanyName", "Unknown Company")
    except Exception as e:
        logger.warning(f"Failed to fetch company info: {e}")
        return "Unknown Company"


@router.get("/api/qbo/connect")
async def qbo_connect(request: Request, region: str = "US"):
    """
    Initiate QBO OAuth flow.

    1. Verify admin authentication
    2. Validate region parameter
    3. Generate state parameter for CSRF protection
    4. Store state and region in session
    5. Redirect to Intuit OAuth consent screen

    Args:
        region: "US" or "CA" - determines which OAuth app to use

    Returns:
        302 Redirect to Intuit OAuth authorization URL
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"QBO OAuth connect initiated by {email} for region {region}")
    except RedirectResponse as redirect:
        return redirect

    # Validate region
    if region not in ("US", "CA"):
        return _error_response(f"Invalid region: {region}. Must be 'US' or 'CA'.")

    # Check QBO credentials configured for this region
    if region == "US" and not settings.qbo_us_configured:
        logger.error("QBO OAuth not configured for US")
        return _error_response(
            "QBO OAuth not configured for US. Set QBO_CLIENT_ID and QBO_CLIENT_SECRET environment variables."
        )
    elif region == "CA" and not settings.qbo_ca_configured:
        logger.error("QBO OAuth not configured for Canada")
        return _error_response(
            "QBO OAuth not configured for Canada. Set QBO_CA_CLIENT_ID and QBO_CA_CLIENT_SECRET environment variables."
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state and region in session (uses SessionMiddleware)
    request.session["qbo_oauth_state"] = state
    request.session["qbo_oauth_region"] = region

    # Build authorization URL
    auth_client = _get_intuit_auth_client(region=region)
    if not auth_client:
        return _error_response(f"Failed to create auth client for region {region}")

    auth_url = auth_client.get_authorization_url(
        scopes=[Scopes.ACCOUNTING],
        state_token=state,
    )

    logger.info(f"Redirecting to Intuit OAuth ({region}), state={state[:8]}...")

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback")  # Root level - matches Intuit registered redirect URI
async def qbo_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    realmId: str | None = None,
    error: str | None = None,
):
    """
    Handle OAuth callback from Intuit.

    1. Validate state parameter matches session (CSRF protection)
    2. Exchange authorization code for access and refresh tokens
    3. Fetch company info from QBO API
    4. Create or update qbo_companies record
    5. Redirect to admin companies page with success message

    Returns:
        302 Redirect to /admin/companies on success
        HTML error page on failure (per stakeholder decision)
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"QBO OAuth callback received for {email}")
    except RedirectResponse as redirect:
        return redirect

    # Handle OAuth error from Intuit
    if error:
        logger.error(f"QBO OAuth error from Intuit: {error}")
        return _error_response(f"QuickBooks authorization was denied: {error}")

    # Validate required parameters
    if not code:
        logger.error("Missing authorization code in callback")
        return _error_response("Authorization code missing. Please try again.")

    if not realmId:
        logger.error("Missing realmId in callback")
        return _error_response("Company ID missing. Please try again.")

    # Validate state (CSRF protection)
    stored_state = request.session.get("qbo_oauth_state")
    if not stored_state or stored_state != state:
        logger.error(f"State mismatch: stored={stored_state[:8] if stored_state else None}..., received={state[:8] if state else None}...")
        return _error_response("Invalid state parameter. Please try again.")

    # Get region from session (stored during connect)
    region = request.session.get("qbo_oauth_region", "US")

    # Clear state and region from session
    del request.session["qbo_oauth_state"]
    if "qbo_oauth_region" in request.session:
        del request.session["qbo_oauth_region"]

    try:
        # Exchange code for tokens using region-specific credentials
        auth_client = _get_intuit_auth_client(region=region)
        if not auth_client:
            logger.error(f"Failed to create auth client for region {region}")
            return _error_response(f"OAuth not configured for region {region}")

        auth_client.get_bearer_token(code, realm_id=realmId)

        access_token = auth_client.access_token
        refresh_token = auth_client.refresh_token

        if not access_token or not refresh_token:
            logger.error("Token exchange returned empty tokens")
            return _error_response("Unable to exchange authorization code. Please try again.")

        logger.info(f"Successfully exchanged code for tokens, realm={realmId}")

        # Fetch company info
        company_name = await _fetch_company_name(realmId, access_token)
        logger.info(f"Fetched company name: {company_name}")

        # Save to database
        db = SessionLocal()
        try:
            # Check for existing company
            existing = db.query(QboCompany).filter(
                QboCompany.realm_id == realmId
            ).first()

            if existing:
                # Update existing company
                existing.access_token = access_token
                existing.refresh_token = refresh_token
                existing.token_expires_at = datetime.utcnow() + timedelta(hours=1)
                existing.token_status = "active"
                existing.last_refreshed_at = datetime.utcnow()
                if company_name != "Unknown Company":
                    existing.name = company_name
                db.commit()
                logger.info(f"Updated existing QBO company: {existing.code}")
            else:
                # Create new company with region
                company_code = _generate_company_code(db, company_name)
                new_company = QboCompany(
                    name=company_name,
                    code=company_code,
                    realm_id=realmId,
                    region=region,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expires_at=datetime.utcnow() + timedelta(hours=1),
                    token_status="active",
                    last_refreshed_at=datetime.utcnow(),
                )
                db.add(new_company)
                db.commit()
                logger.info(f"Created new QBO company: {company_code}")

        except Exception as e:
            logger.error(f"Database error saving company: {e}", exc_info=True)
            db.rollback()
            return _error_response("Failed to save company. Please try again.")
        finally:
            db.close()

        # Redirect to companies page with success
        return RedirectResponse(
            url="/admin/companies?message=connected",
            status_code=302,
        )

    except Exception as e:
        logger.error(f"Token exchange error: {e}", exc_info=True)
        return _error_response("Unable to exchange authorization code. Please try again.")


@router.post("/api/qbo/companies/{company_id}/disconnect")
async def disconnect_company(request: Request, company_id: int):
    """
    Disconnect a QBO company by clearing tokens.

    1. Verify admin authentication
    2. Best-effort token revocation with Intuit (per RFC 7009)
    3. Clear tokens from database
    4. Redirect to companies page with success message

    Returns:
        302 Redirect to /admin/companies?message=disconnected
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"Disconnect company {company_id} requested by {email}")
    except RedirectResponse as redirect:
        return redirect

    db = SessionLocal()
    try:
        company = db.query(QboCompany).filter(QboCompany.id == company_id).first()

        if not company:
            logger.warning(f"Company not found for disconnect: {company_id}")
            return RedirectResponse(
                url="/admin/companies?message=error",
                status_code=302,
            )

        company_code = company.code

        # Best-effort token revocation with Intuit (per OAuth 2.0 RFC 7009)
        if company.refresh_token or company.access_token:
            try:
                # Use region-specific credentials for revocation
                credentials = settings.get_qbo_credentials(company.region)
                if credentials:
                    client_id, client_secret = credentials
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        token_to_revoke = company.refresh_token or company.access_token
                        await client.post(
                            "https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
                            data={"token": token_to_revoke},
                            auth=(client_id, client_secret),
                        )
                    logger.info(f"Revoked token with Intuit for company {company_code} (region={company.region})")
            except Exception as e:
                logger.warning(f"Failed to revoke token with Intuit (best effort): {e}")

        # Clear tokens in database
        company.access_token = None
        company.refresh_token = None
        company.token_expires_at = None
        company.token_status = "disconnected"

        db.commit()
        logger.info(f"Disconnected QBO company: {company_code}")

        return RedirectResponse(
            url="/admin/companies?message=disconnected",
            status_code=302,
        )

    except Exception as e:
        logger.error(f"Error disconnecting company: {e}", exc_info=True)
        db.rollback()
        return RedirectResponse(
            url="/admin/companies?message=error",
            status_code=302,
        )
    finally:
        db.close()


@router.post("/api/qbo/companies/{company_id}/refresh")
async def refresh_company_token(request: Request, company_id: int):
    """
    Manually refresh a QBO company's token.

    1. Verify admin authentication
    2. Call Intuit token refresh
    3. Update token status and timestamps in database
    4. Return JSON response for AJAX handling

    Returns:
        JSON with success status and message
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"Manual token refresh for company {company_id} requested by {email}")
    except RedirectResponse:
        return {"success": False, "message": "Authentication required", "reconnect_required": False}

    db = SessionLocal()
    try:
        company = db.query(QboCompany).filter(QboCompany.id == company_id).first()

        if not company:
            logger.warning(f"Company not found for refresh: {company_id}")
            return {"success": False, "message": "Company not found", "reconnect_required": False}

        if company.token_status == "disconnected" or not company.refresh_token:
            logger.warning(f"Cannot refresh disconnected company: {company.code}")
            return {
                "success": False,
                "message": "No refresh token available. Please reconnect QuickBooks.",
                "reconnect_required": True,
            }

        try:
            # Refresh token using Intuit AuthClient with region-specific credentials
            auth_client = _get_intuit_auth_client(
                region=company.region,
                access_token=company.access_token,
                refresh_token=company.refresh_token,
            )
            if not auth_client:
                return {
                    "success": False,
                    "message": f"OAuth not configured for region {company.region}",
                    "reconnect_required": True,
                }
            auth_client.refresh()

            # Update company record
            company.access_token = auth_client.access_token
            company.refresh_token = auth_client.refresh_token
            company.token_expires_at = datetime.utcnow() + timedelta(hours=1)
            company.token_status = "active"
            company.last_refreshed_at = datetime.utcnow()

            db.commit()
            logger.info(f"Manually refreshed token for company {company.code}")

            return {
                "success": True,
                "message": "Token refreshed successfully",
                "expires_at": company.token_expires_at.isoformat(),
            }

        except Exception as e:
            logger.error(f"Token refresh failed for {company.code}: {e}", exc_info=True)

            # Mark as expired if refresh fails
            company.token_status = "expired"
            db.commit()

            return {
                "success": False,
                "message": "Refresh token expired. Please reconnect QuickBooks.",
                "reconnect_required": True,
            }

    except Exception as e:
        logger.error(f"Error refreshing company token: {e}", exc_info=True)
        db.rollback()
        return {"success": False, "message": f"Error: {str(e)}", "reconnect_required": False}
    finally:
        db.close()


@router.post("/api/qbo/refresh-all")
async def refresh_all_tokens(request: Request):
    """
    Manually refresh all active QBO company tokens.

    This is useful for:
    - Recovering from token issues
    - Ensuring all tokens are fresh before maintenance
    - Testing the refresh mechanism

    Requires admin authentication.

    Returns:
        JSON with lists of refreshed, failed, and skipped companies
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"Manual refresh-all initiated by {email}")
    except RedirectResponse as redirect:
        return {"error": "Authentication required"}

    from app.services.token_refresh_scheduler import token_scheduler
    results = await token_scheduler.refresh_all_now()

    return {
        "success": True,
        "refreshed": results["refreshed"],
        "failed": results["failed"],
        "skipped": results["skipped"],
        "message": f"Refreshed {len(results['refreshed'])} tokens, {len(results['failed'])} failed",
    }
