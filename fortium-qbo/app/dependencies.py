"""Shared dependencies for FastAPI dependency injection."""

from typing import Optional

from fastapi import Request
from sqlalchemy import select

from app.database import SessionLocal, get_db
from app.models import AdminUser
from app.services.session_service import verify_session

__all__ = ["get_db", "get_current_admin_user"]


async def get_current_admin_user(request: Request) -> Optional[AdminUser]:
    """
    Get current authenticated admin user from session cookie.

    Extracts session cookie, verifies token, and looks up user in database.
    Returns None if not authenticated or user not found.

    This dependency is for future phases when protecting admin routes.

    Args:
        request: FastAPI request object

    Returns:
        AdminUser object if authenticated and valid, None otherwise

    Example usage:
        @app.get("/admin/dashboard")
        async def dashboard(user: AdminUser = Depends(get_current_admin_user)):
            if not user:
                raise HTTPException(401, "Not authenticated")
            return {"email": user.email}
    """
    # Extract session cookie
    session_token = request.cookies.get("auth_session")
    if not session_token:
        return None

    # Verify session token
    email = verify_session(session_token)
    if not email:
        return None

    # Look up user in database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()
        return admin_user
    finally:
        db.close()
