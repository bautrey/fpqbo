"""Admin User model for Google OAuth authentication."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AdminUser(Base):
    """
    AdminUser model for Google OAuth authenticated administrators.

    Stores admin user information for access to admin UI.
    No relationships - standalone table.
    """

    __tablename__ = "admin_users"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # User identification
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    # Permissions
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"<AdminUser(id={self.id}, email={self.email})>"
