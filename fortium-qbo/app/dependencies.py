"""Shared dependencies for FastAPI dependency injection."""

from app.database import get_db

__all__ = ["get_db"]
