"""Request Log model for API gateway audit trail."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.clock import utcnow

if TYPE_CHECKING:
    from app.models.api_key import ApiKey


class RequestLog(Base):
    """
    RequestLog model for API gateway request audit trail.

    Logs all requests to the gateway for monitoring and debugging.
    Related to ApiKey (many-to-one, nullable for unauthenticated requests).
    """

    __tablename__ = "request_log"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Foreign key to ApiKey (nullable - may not have valid API key)
    api_key_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("api_keys.id"), nullable=True
    )

    # Request details
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamp (indexed for time-based queries)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), 
        nullable=False, default=utcnow, index=True
    )

    # Relationships
    api_key: Mapped[Optional["ApiKey"]] = relationship(
        "ApiKey",
        foreign_keys=[api_key_id],
        back_populates="request_logs",
    )

    def __repr__(self) -> str:
        return f"<RequestLog(id={self.id}, endpoint={self.endpoint}, status={self.status_code})>"
