"""Shared error-handling helper for QBO create/update write endpoints.

Body-taking POST create/update endpoints must distinguish *client* errors (bad
request → 4xx) from *server* errors (real QBO failures → 5xx), and must log the
5xx path so genuine failures leave a breadcrumb.

Scope note, now partly historical: the older not-found-semantic endpoints
(POST void, DELETE) do NOT use this helper, because they map a missing entity
to 404 and the uniform ValueError→400 below would have clobbered it. That
hazard ended with #15 — not-found is `QboNotFound`, an `HTTPException` the
guard re-raises untouched — so those endpoints could adopt this helper and
would gain the 500 logging by doing so. They have not been converted; new
ones (`POST /bill-payments/{id}/void`) use it.

Since #15 the service signals its own conditions with typed exceptions —
``QboNotFound`` (404), ``QboCompanyDisconnected`` (409), ``QboUnavailable``
(503) — which are ``HTTPException`` subclasses and therefore pass through the
guard below untouched. **This changed the status of the write endpoints**: an
unknown or disconnected company on a POST used to answer 400 via the
``ValueError`` branch, and now answers 404 or 409, matching what the same
company already returned on a GET. That verb-dependent split was the second
half of the same defect — one missing record, two status codes, decided by
the HTTP method.

``run_qbo_write`` wraps a QBO write coroutine and maps exceptions:

- ``HTTPException``         → re-raised unchanged, which is what carries the
                              typed service exceptions and any status an
                              endpoint chose deliberately.
- ``ValueError``            → 400 (str(e)) — now only payload problems, since
                              the service no longer raises ValueError at all.
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


async def run_qbo_write(
    coro: Awaitable[Any], *, entity: str, has_body: bool = True
) -> Any:
    """Await a QBO write coroutine, mapping exceptions to HTTP status codes.

    Args:
        coro: the awaitable QBO write call (e.g. ``qbo.create_customer(...)``).
        entity: a human label for the entity being written (e.g. ``"customer"``),
            used in the malformed-payload message.
        has_body: whether the endpoint accepts a request body. Pass ``False``
            for a write driven only by path and query params (e.g. a void).
            The ``KeyError``/``TypeError`` -> 400 branch exists to blame a
            malformed payload; with no payload to blame, those can only be a
            server-side bug and must reach the logged 500 instead. Answering
            400 there tells a caller its request was wrong when the request
            was fine, and — since that branch does not log — leaves no trace
            of the actual fault.

    Returns:
        The coroutine's result unchanged on success.

    Raises:
        HTTPException: 400 for client errors (ValueError / KeyError / TypeError),
            500 for any other exception (logged with traceback first).
    """
    try:
        return await coro
    except HTTPException:
        # A specific HTTP error already chosen by the endpoint/service (404, 409,
        # ...) must pass through unchanged — the catch-all below would otherwise
        # mask it as a 500. (HTTPException is a subclass of Exception.)
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (KeyError, TypeError) as e:
        if not has_body:
            # No payload exists to be malformed, so this is ours. Fall through
            # to the catch-all, which logs.
            logger.error("QBO write failed for %s: %s", entity, e, exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"QBO API error: {e}"
            ) from e
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or missing field in {entity} payload: {e}",
        ) from e
    except Exception as e:
        logger.error("QBO write failed for %s: %s", entity, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"QBO API error: {e}") from e
