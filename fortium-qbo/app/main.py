"""fortium-qbo - FastAPI Application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan - startup and shutdown events.

    Startup:
    - Log application start
    - Placeholder for future initialization (Phase 2+)

    Shutdown:
    - Log application shutdown
    - Placeholder for future cleanup (Phase 2+)
    """
    # Startup
    logger.info("fortium-qbo starting up...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database: {settings.database_url}")

    yield

    # Shutdown
    logger.info("fortium-qbo shutting down...")


app = FastAPI(
    title="fortium-qbo",
    description="QuickBooks Online API Gateway",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}
