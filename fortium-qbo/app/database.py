"""Database configuration with SQLAlchemy."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


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
    """Create all database tables."""
    # Import models to ensure they're registered with Base
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


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
