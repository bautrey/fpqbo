"""Shared error-handling helper for QBO write/mutation endpoints.

Write endpoints (POST create/update, POST void, DELETE) must distinguish
*client* errors (bad request → 4xx) from *server* errors (real QBO failures →
5xx), and must log the 5xx path so genuine failures leave a breadcrumb.

``run_qbo_write`` wraps a QBO write coroutine and maps exceptions:

- ``ValueError``            → 400 (str(e))  — preserves existing behavior
                              ("company not found", disconnected, etc.)
- ``KeyError`` / ``TypeError`` → 400 — a malformed payload (e.g. a Ref missing
                              its ``value`` key) surfacing while the service
                              builds the QBO object is a *client* error, not a
                              500 "QBO API error".
- any other ``Exception``  → logged at error level (with traceback) THEN 500
                              with the existing ``f"QBO API error: {e}"`` detail.

Nothing is swallowed — every path re-raises via ``HTTPException``.
"""

import logging
from typing import Any, Awaitable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def run_qbo_write(coro: Awaitable[Any], *, entity: str) -> Any:
    """Await a QBO write coroutine, mapping exceptions to HTTP status codes.

    Args:
        coro: the awaitable QBO write call (e.g. ``qbo.create_customer(...)``).
        entity: a human label for the entity being written (e.g. ``"customer"``),
            used in the malformed-payload message.

    Returns:
        The coroutine's result unchanged on success.

    Raises:
        HTTPException: 400 for client errors (ValueError / KeyError / TypeError),
            500 for any other exception (logged with traceback first).
    """
    try:
        return await coro
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (KeyError, TypeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or missing field in {entity} payload: {e}",
        )
    except Exception as e:
        logger.error("QBO write failed for %s: %s", entity, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}")
