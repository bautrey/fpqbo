"""Background token refresh scheduler.

Proactively refreshes QBO tokens before they expire so API clients
never encounter expired tokens.

QBO access tokens expire after 1 hour. We refresh every 45 minutes
to maintain a 15-minute buffer.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.qbo_company import QboCompany
from app.services.qbo_service import QBOService
from app.utils.clock import utcnow

logger = logging.getLogger(__name__)

# Refresh tokens that expire within this time
REFRESH_THRESHOLD = timedelta(minutes=20)

# How often to check for tokens needing refresh
CHECK_INTERVAL_SECONDS = 45 * 60  # 45 minutes


class TokenRefreshScheduler:
    """Background scheduler for proactive token refresh."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """Start the background refresh task."""
        if self._running:
            logger.warning("Token refresh scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info("Token refresh scheduler started")

    async def stop(self):
        """Stop the background refresh task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Token refresh scheduler stopped")

    async def _refresh_loop(self):
        """Main loop that periodically refreshes tokens."""
        # Initial delay to let the app start up
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._refresh_expiring_tokens()
            except Exception as e:
                logger.error(f"Error in token refresh loop: {e}")

            # Wait for next check interval
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _refresh_expiring_tokens(self):
        """Refresh all tokens that are expiring soon."""
        db = SessionLocal()
        try:
            # Find companies with tokens expiring within threshold
            threshold = utcnow() + REFRESH_THRESHOLD
            companies = db.query(QboCompany).filter(
                QboCompany.token_status == "active",
                QboCompany.token_expires_at <= threshold,
                QboCompany.refresh_token.isnot(None),
            ).all()

            if not companies:
                logger.debug("No tokens need refresh")
                return

            logger.info(f"Found {len(companies)} tokens to refresh proactively")

            # Refresh each company's token
            qbo_service = QBOService(db)
            for company in companies:
                try:
                    qbo_service._refresh_token(company)
                    logger.info(f"Proactively refreshed token for {company.code}")
                except Exception as e:
                    logger.error(f"Failed to refresh token for {company.code}: {e}")

        finally:
            db.close()

    async def refresh_all_now(self) -> dict:
        """Manually refresh all active tokens immediately.

        Returns:
            Dict with refresh results
        """
        db = SessionLocal()
        results = {"refreshed": [], "failed": [], "skipped": []}

        try:
            companies = db.query(QboCompany).filter(
                QboCompany.token_status.in_(["active", "refresh_failed"]),
                QboCompany.refresh_token.isnot(None),
            ).all()

            qbo_service = QBOService(db)
            for company in companies:
                try:
                    qbo_service._refresh_token(company)
                    results["refreshed"].append(company.code)
                    logger.info(f"Manually refreshed token for {company.code}")
                except Exception as e:
                    results["failed"].append({"code": company.code, "error": str(e)})
                    logger.error(f"Failed to refresh token for {company.code}: {e}")

            # Find disconnected companies
            disconnected = db.query(QboCompany).filter(
                QboCompany.token_status == "disconnected"
            ).all()
            results["skipped"] = [c.code for c in disconnected]

        finally:
            db.close()

        return results


# Global scheduler instance
token_scheduler = TokenRefreshScheduler()
