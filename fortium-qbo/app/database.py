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
    # Each ALTER is spelled out whole rather than assembled from parts. An
    # f-string reaching sqlalchemy.text() is a SQL-injection taint source
    # whatever it interpolates, so building the statement here keeps every
    # character of executed SQL a literal you can read at its call site.
    # BOOLEAN NOT NULL DEFAULT false is valid on both PostgreSQL and SQLite.
    _add_column_if_missing(
        "qbo_companies",
        "is_sandbox",
        "ALTER TABLE qbo_companies ADD COLUMN is_sandbox BOOLEAN NOT NULL DEFAULT false",
    )
    _add_column_if_missing(
        "api_keys",
        "can_write",
        "ALTER TABLE api_keys ADD COLUMN can_write BOOLEAN NOT NULL DEFAULT false",
        # Runs ONLY on the boot that adds the column, never afterwards. The
        # column defaults to false, so without this every key already in use
        # would start answering 403 to its writes — the Payouts keys create
        # bill payments and vendor credits today.
        #
        # It has to sit inside the add, not beside it: this guard runs on every
        # boot, so a backfill outside that condition would re-grant write to
        # every active key on each deploy and silently undo any key an admin had
        # since made read-only.
        backfill="UPDATE api_keys SET can_write = true WHERE is_active = true",
    )


def _add_column_if_missing(
    table: str, column: str, add_column_sql: str, backfill: str | None = None
) -> None:
    """Run ``add_column_sql`` when ``table.column`` is absent, seeding existing rows.

    ``table`` and ``column`` are what this function INSPECTS; ``add_column_sql``
    is the complete statement it EXECUTES. They are separate parameters rather
    than one assembled string so that no SQL is built here — see the note at the
    call sites.

    ``backfill`` executes in the same transaction as the ALTER and only on the
    boot that performs it, so it describes the state existing rows should start
    in rather than a state this function keeps re-asserting.
    """
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    if column in {col["name"] for col in inspector.get_columns(table)}:
        return

    try:
        with engine.begin() as conn:
            conn.execute(text(add_column_sql))
            if backfill:
                conn.execute(text(backfill))
        logger.info("Added missing column %s.%s", table, column)
    except (OperationalError, ProgrammingError):
        # Another instance may add the column concurrently on first deploy
        # (Postgres -> DuplicateColumn/ProgrammingError, SQLite ->
        # OperationalError). Re-check rather than crash the boot; only
        # re-raise if the column is genuinely still missing.
        columns_after = {col["name"] for col in inspect(engine).get_columns(table)}
        if column in columns_after:
            logger.info("%s.%s was added concurrently; continuing", table, column)
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
