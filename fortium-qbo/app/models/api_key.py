"""API Key model for gateway authentication."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.qbo_company import QboCompany
    from app.models.request_log import RequestLog


class ApiKey(Base):
    """
    ApiKey model for API gateway authentication.

    Stores hashed API keys for n8n workflow authentication.
    Related to QboCompany (many-to-one) and RequestLog (one-to-many).
    """

    __tablename__ = "api_keys"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Key data (hashed)
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Foreign key to QboCompany
    company_id: Mapped[int] = mapped_column(
        ForeignKey("qbo_companies.id"), nullable=False
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    company: Mapped["QboCompany"] = relationship(
        "QboCompany",
        foreign_keys=[company_id],
        back_populates="api_keys",
    )
    request_logs: Mapped[list["RequestLog"]] = relationship(
        "RequestLog",
        back_populates="api_key",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix={self.key_prefix}, name={self.name})>"
