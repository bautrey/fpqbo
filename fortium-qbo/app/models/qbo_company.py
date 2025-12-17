"""QBO Company model for QuickBooks Online company credentials."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.api_key import ApiKey


class QboCompany(Base):
    """
    QboCompany model representing QuickBooks Online company credentials.

    Stores OAuth tokens and company metadata for QBO API access.
    Related to ApiKey (one-to-many).
    """

    __tablename__ = "qbo_companies"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Company identification
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(
        String(10), unique=True, nullable=False, index=True
    )
    realm_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # OAuth tokens
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    token_status: Mapped[str] = mapped_column(String(20), default="active")
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey",
        back_populates="company",
        foreign_keys="ApiKey.company_id",
    )

    def __repr__(self) -> str:
        return f"<QboCompany(id={self.id}, code={self.code}, name={self.name})>"
