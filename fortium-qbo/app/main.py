"""fortium-qbo - FastAPI Application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import accounts, bills, customers, invoices, payments, reports, vendors

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan - startup and shutdown events.

    Startup:
    - Log application start
    - Initialize database connection

    Shutdown:
    - Log application shutdown
    - Cleanup resources
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

# Register QBO entity routers
app.include_router(invoices.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(vendors.router, prefix="/api")
app.include_router(bills.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(reports.router, prefix="/api")


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}


@app.get("/")
async def root() -> dict:
    """Root endpoint with API info."""
    return {
        "name": "fortium-qbo",
        "version": "0.1.0",
        "description": "QuickBooks Online API Gateway",
        "endpoints": {
            "invoices": "/api/invoices",
            "accounts": "/api/accounts",
            "customers": "/api/customers",
            "vendors": "/api/vendors",
            "bills": "/api/bills",
            "payments": "/api/payments",
            "reports": "/api/reports",
        },
        "docs": "/docs" if settings.debug else None,
    }
