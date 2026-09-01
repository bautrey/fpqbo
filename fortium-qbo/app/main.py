"""fortium-qbo - FastAPI Application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import (
    accounts, api_keys, attachments, auth, bill_payments, bills, companies,
    company_info, credit_memos, customers, departments, deposits, employees,
    estimates, invoices, items, journal_entries, pages, payments, purchase_orders,
    purchases, qbo_oauth, recurring, reference, refund_receipts, reports,
    sales_receipts, tax, time_activities, transfers, vendor_credits, vendors,
)
from app.utils.clock import utcnow

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan - startup and shutdown events.

    Startup:
    - Log application start
    - Initialize database tables
    - Seed initial admin user if INITIAL_ADMIN_EMAIL is configured

    Shutdown:
    - Log application shutdown
    """
    # Startup
    logger.info("fortium-qbo starting up...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database: {settings.database_url}")

    # Initialize database tables
    from app.database import init_db
    init_db()
    logger.info("Database tables initialized")

    # Seed initial admin user
    if settings.initial_admin_email:
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.models import AdminUser

        db = SessionLocal()
        try:
            # Check if user already exists
            existing_user = db.execute(
                select(AdminUser).where(AdminUser.email == settings.initial_admin_email)
            ).scalar_one_or_none()

            if existing_user:
                logger.info(f"Initial admin user already exists: {settings.initial_admin_email}")
            else:
                # Create initial admin user
                admin_user = AdminUser(
                    email=settings.initial_admin_email,
                    is_super_admin=True,
                    created_at=utcnow(),
                )
                db.add(admin_user)
                db.commit()
                logger.info(f"Created initial admin user: {settings.initial_admin_email}")

        except Exception as e:
            logger.error(f"Failed to seed initial admin user: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    else:
        logger.info("No INITIAL_ADMIN_EMAIL configured, skipping admin seeding")

    # Start background token refresh scheduler
    from app.services.token_refresh_scheduler import token_scheduler
    await token_scheduler.start()

    yield

    # Shutdown
    logger.info("fortium-qbo shutting down...")
    await token_scheduler.stop()


app = FastAPI(
    title="fortium-qbo",
    description="QuickBooks Online API Gateway",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Add session middleware for OAuth state storage
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key.get_secret_value(),
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include auth and pages routers
app.include_router(auth.router)
app.include_router(pages.router)

# API key management (admin-only)
app.include_router(api_keys.router)

# Register QBO entity routers
app.include_router(companies.router, prefix="/api")
app.include_router(invoices.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(vendors.router, prefix="/api")
app.include_router(bills.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(reports.router, prefix="/api")

# New entity routers
app.include_router(bill_payments.router, prefix="/api")
app.include_router(credit_memos.router, prefix="/api")
app.include_router(deposits.router, prefix="/api")
app.include_router(estimates.router, prefix="/api")
app.include_router(journal_entries.router, prefix="/api")
app.include_router(purchases.router, prefix="/api")
app.include_router(purchase_orders.router, prefix="/api")
app.include_router(refund_receipts.router, prefix="/api")
app.include_router(sales_receipts.router, prefix="/api")
app.include_router(transfers.router, prefix="/api")
app.include_router(vendor_credits.router, prefix="/api")
app.include_router(items.router, prefix="/api")
app.include_router(employees.router, prefix="/api")
app.include_router(departments.router, prefix="/api")
app.include_router(time_activities.router, prefix="/api")
app.include_router(company_info.router, prefix="/api")
app.include_router(tax.router, prefix="/api")
app.include_router(reference.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(recurring.router, prefix="/api")

# Register QBO OAuth router (no prefix - router has /api/qbo prefix)
app.include_router(qbo_oauth.router)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}


@app.get("/api")
async def api_root() -> dict:
    """API root endpoint with available endpoints info."""
    return {
        "name": "fortium-qbo",
        "version": "0.1.0",
        "description": "QuickBooks Online API Gateway",
        "endpoints": {
            "companies": "/api/companies",
            "invoices": "/api/invoices",
            "accounts": "/api/accounts",
            "customers": "/api/customers",
            "vendors": "/api/vendors",
            "bills": "/api/bills",
            "payments": "/api/payments",
            "reports": "/api/reports",
            "bill-payments": "/api/bill-payments",
            "credit-memos": "/api/credit-memos",
            "deposits": "/api/deposits",
            "estimates": "/api/estimates",
            "journal-entries": "/api/journal-entries",
            "purchases": "/api/purchases",
            "purchase-orders": "/api/purchase-orders",
            "refund-receipts": "/api/refund-receipts",
            "sales-receipts": "/api/sales-receipts",
            "transfers": "/api/transfers",
            "vendor-credits": "/api/vendor-credits",
            "items": "/api/items",
            "employees": "/api/employees",
            "departments": "/api/departments",
            "time-activities": "/api/time-activities",
            "company-info": "/api/company/info",
            "preferences": "/api/company/preferences",
            "tax": "/api/tax",
            "reference": "/api/reference",
            "attachments": "/api/attachments",
            "recurring-transactions": "/api/recurring-transactions",
        },
        "docs": "/docs" if settings.debug else None,
    }
