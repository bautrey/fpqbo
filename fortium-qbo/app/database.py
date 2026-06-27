"""Database configuration with SQLAlchemy."""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def _get_engine_kwargs() -> dict:
    """Get database engine kwargs based on database URL."""
    if settings.database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # For Supabase Transaction pooler: use minimal local pooling
    # since Supabase handles connection pooling on their side
    return {
        "pool_pre_ping": True,  # Check connections before use
        "pool_size": 3,  # Small local pool
        "max_overflow": 2,  # Allow some overflow
        "pool_recycle": 300,  # Recycle connections every 5 min
        "pool_timeout": 30,  # Wait up to 30s for connection
    }


# Create engine
engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    **_get_engine_kwargs(),
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all database tables and apply additive column migrations."""
    # Import models to ensure they're registered with Base
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_additive_columns()


def _ensure_additive_columns() -> None:
    """Idempotently add new nullable/defaulted columns to existing tables.

    This service has no migration runner wired into deploy — startup relies on
    ``Base.metadata.create_all``, which creates missing tables but never alters
    existing ones. So a new column added to a model would be absent on the
    already-provisioned production table until a manual ALTER is run, breaking
    every query that selects it. This guard closes that gap by adding known
    additive columns when missing, before any request is served. New tables
    (fresh databases) already get the column from ``create_all``; this is a
    no-op there.

    Alembic migrations remain the source of truth for schema history; this is
    the deploy-time safety net given create_all is the only startup hook.
    """
    inspector = inspect(engine)
    if "qbo_companies" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("qbo_companies")}
    if "is_sandbox" not in existing_columns:
        # BOOLEAN NOT NULL DEFAULT false is valid on both PostgreSQL and SQLite.
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE qbo_companies "
                        "ADD COLUMN is_sandbox BOOLEAN NOT NULL DEFAULT false"
                    )
                )
            logger.info("Added missing column qbo_companies.is_sandbox")
        except (OperationalError, ProgrammingError):
            # Another instance may add the column concurrently on first deploy
            # (Postgres -> DuplicateColumn/ProgrammingError, SQLite ->
            # OperationalError). Re-check rather than crash the boot; only
            # re-raise if the column is genuinely still missing.
            columns_after = {
                col["name"] for col in inspect(engine).get_columns("qbo_companies")
            }
            if "is_sandbox" in columns_after:
                logger.info(
                    "qbo_companies.is_sandbox was added concurrently; continuing"
                )
            else:
                raise


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
