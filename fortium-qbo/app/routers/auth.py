"""Authentication router for Google OAuth flow."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AdminUser
from app.services.oauth_service import get_oauth_client
from app.services.session_service import create_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """
    Initiate Google OAuth flow.

    Redirects user to Google OAuth consent screen with:
    - State parameter for CSRF protection (Authlib automatic)
    - Redirect URI: {base_url}/auth/callback
    - Scopes: openid email profile

    Returns:
        Redirect to Google OAuth authorization URL
    """
    oauth = get_oauth_client()
    redirect_uri = f"{settings.base_url}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """
    Handle OAuth callback from Google.

    Validation flow:
    1. Exchange authorization code for access token (Authlib validates state)
    2. Validate email domain matches settings.google_allowed_domain
    3. Check if user exists in admin_users table
    4. Create session cookie with signed token
    5. Update last_login_at timestamp
    6. Redirect to / (home page)

    Error handling:
    - Domain mismatch: 400 Bad Request with error message
    - Allowlist failure: 403 Forbidden with error message
    - OAuth error: 400 Bad Request with error message

    Returns:
        Redirect to / with session cookie on success
        HTML error page on failure
    """
    oauth = get_oauth_client()

    try:
        # Exchange authorization code for access token (validates state)
        token = await oauth.google.authorize_access_token(request)

        # Get user info from ID token
        user_info = token.get("userinfo")
        if not user_info:
            logger.error("No userinfo in OAuth token")
            return _error_response(
                "Authentication failed. Please try again or contact your administrator.",
                400
            )

        email = user_info.get("email")
        if not email:
            logger.error("No email in userinfo")
            return _error_response(
                "Authentication failed. Please try again or contact your administrator.",
                400
            )

        logger.info(f"OAuth callback received for email: {email}")

        # Validate domain
        domain = email.split("@")[-1]
        if domain != settings.google_allowed_domain:
            logger.warning(f"Domain validation failed for {email}: {domain} != {settings.google_allowed_domain}")
            return _error_response(
                f"Authentication failed. Only @{settings.google_allowed_domain} emails are allowed.",
                400
            )

        # Check allowlist (admin_users table)
        db = SessionLocal()
        try:
            admin_user = db.execute(
                select(AdminUser).where(AdminUser.email == email)
            ).scalar_one_or_none()

            if not admin_user:
                logger.warning(f"Allowlist validation failed for {email}: user not in admin_users table")
                return _error_response(
                    "User not authorized. Please contact your administrator for access.",
                    403
                )

            # Update last_login_at
            admin_user.last_login_at = datetime.utcnow()
            db.commit()
            logger.info(f"Updated last_login_at for {email}")

        finally:
            db.close()

        # Create session cookie
        session_token = create_session(email)
        logger.info(f"Session created for {email}")

        # Redirect to home with session cookie
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="auth_session",
            value=session_token,
            max_age=settings.session_max_age_seconds,
            httponly=True,
            secure=not settings.debug,  # HTTPS only in production
            samesite="lax",
            path="/",
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback error: {e}", exc_info=True)
        return _error_response(
            "Authentication failed. Please try again or contact your administrator.",
            400
        )


@router.get("/logout")
async def logout():
    """
    Logout user by clearing session cookie.

    Returns:
        Redirect to /login with cleared session cookie
    """
    response = RedirectResponse(url="/login", status_code=302)
    response.set_cookie(
        key="auth_session",
        value="",
        max_age=0,
        path="/",
    )
    logger.info("User logged out")
    return response


def _error_response(message: str, status_code: int):
    """
    Generate HTML error page.

    Args:
        message: Error message to display
        status_code: HTTP status code

    Returns:
        HTMLResponse with error message
    """
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Authentication Error - fortium-qbo</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="row justify-content-center">
                <div class="col-md-6">
                    <div class="card border-danger">
                        <div class="card-header bg-danger text-white">
                            <h5 class="mb-0">Authentication Error</h5>
                        </div>
                        <div class="card-body">
                            <p class="card-text">{message}</p>
                            <a href="/login" class="btn btn-primary">Back to Login</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=html, status_code=status_code)
