"""Date query-parameter parsing for the read endpoints.

Declaring a query parameter as ``datetime`` looks right and behaves badly.
FastAPI will not coerce a bare ``2024-12-31`` into a ``datetime``, so the
handler receives ``None``, the downstream ``if start_date and end_date``
never fires, and the caller gets the whole unfiltered result set back with a
200. Nothing in the response says the window was discarded.

So routers declare their date params as ``str`` and run them through
``parse_date_param``. It takes a bare date or a full ISO 8601 timestamp
(including the ``...Z`` form that ``Date.prototype.toISOString`` emits) and
rejects everything else with a 422.

Call it *outside* the router's ``try`` block. Several handlers end in a bare
``except Exception`` that rewrites anything it catches into a 500, and
``HTTPException`` is an ``Exception`` — parsing inside the block would turn
this 422 into a "QBO API error" 500.
"""

from datetime import datetime

from fastapi.exceptions import RequestValidationError

__all__ = ["parse_date_param"]


def parse_date_param(value: str | None, *, field: str) -> datetime | None:
    """Parse a date query parameter into a ``datetime``.

    Args:
        value: The raw query-string value, or None when the param was omitted.
        field: Parameter name, used in the error message.

    Returns:
        The parsed ``datetime``, or None when ``value`` is None.

    Raises:
        RequestValidationError: when the value is present but not a date.
            FastAPI renders it as a 422 in the same body shape a rejected
            ``datetime`` query param has always produced, so the error
            contract does not move underneath existing callers.
    """
    if value is None:
        return None

    text = value.strip()
    # datetime.fromisoformat only learned to read a trailing "Z" in 3.11;
    # normalising it here keeps the parse independent of the runtime version.
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise RequestValidationError(
            [
                {
                    "type": "date_parsing",
                    "loc": ("query", field),
                    "msg": (
                        "Input should be a valid date (YYYY-MM-DD) or ISO 8601 "
                        "timestamp (YYYY-MM-DDTHH:MM:SSZ)"
                    ),
                    "input": value,
                }
            ]
        ) from None
