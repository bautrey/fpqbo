"""Result paging for the transaction list endpoints.

A list response was a bare JSON array capped at QBO's 1000-row ``MAXRESULTS``
ceiling with nothing in it saying so. Against the live ledger (2026-08-03)
``/api/bills/`` answered 1000 rows for no filter, 1000 rows for the whole of
2024, and 314 rows for January 2024 — while 2024 alone holds 4,170 bills and
the ledger holds roughly 27,000. Every caller asking a broad question got a
200 describing something other than what it asked for. That is the same
defect class as the date params that were dropped in silence: the response
was wrong and looked right.

Two things fix it, and both are needed:

``offset``
    QBO pages with ``STARTPOSITION``/``MAXRESULTS`` and will not return more
    than 1000 rows for one query, so completeness cannot come from a bigger
    ``max_results`` — it has to come from a cursor. ``offset`` is 0-based on
    the wire and translated to QBO's 1-based ``STARTPOSITION`` in the
    service.

Paging headers
    A caller must be able to tell a partial answer from a whole one without
    guessing. ``X-Has-More`` states it outright, ``X-Total-Count`` gives the
    number of rows the query matches in QBO so an assembled set can be
    checked against the ledger, and ``X-Next-Offset`` says where to resume.

The body shape deliberately does not move. The gbrain ``spend`` and ``qbo``
adapters parse these endpoints as arrays and refuse a non-array body outright
rather than risk reading a truncated page as a whole one, so wrapping the
rows in an envelope would break every existing consumer. The paging facts
ride on headers, which existing consumers ignore and new ones can read.
"""

from dataclasses import dataclass, field
from typing import Any

from fastapi import Response

__all__ = [
    "PAGING_RESPONSE_HEADERS",
    "PagedResult",
    "QBO_MAX_PAGE_SIZE",
    "apply_paging_headers",
]

# QBO's query API will not return more than 1000 rows for a single query
# regardless of the MAXRESULTS asked for. It is the page size, not a policy
# choice, which is why `max_results` is bounded by it rather than by a number
# picked here.
QBO_MAX_PAGE_SIZE = 1000

HEADER_TOTAL_COUNT = "X-Total-Count"
HEADER_RESULT_OFFSET = "X-Result-Offset"
HEADER_RESULT_COUNT = "X-Result-Count"
HEADER_HAS_MORE = "X-Has-More"
HEADER_NEXT_OFFSET = "X-Next-Offset"


@dataclass(frozen=True)
class PagedResult:
    """One page of a QBO list query, plus what a caller needs to page on.

    Attributes:
        rows: The rows in this page.
        offset: 0-based offset of the first row in ``rows``.
        total: How many rows the query matches in QBO — not how many are in
            ``rows``. None only when QBO answered the COUNT query without a
            ``totalCount``, which leaves the size of the result set genuinely
            unknown; ``has_more`` is True in that case so an unknown can never
            be read as complete.
        has_more: True when rows exist past this page.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    offset: int = 0
    total: int | None = None
    has_more: bool = False

    @property
    def next_offset(self) -> int | None:
        """Offset to request for the following page, or None at the end."""
        return self.offset + len(self.rows) if self.has_more else None


def apply_paging_headers(response: Response, page: PagedResult) -> None:
    """Write the paging facts of ``page`` onto ``response``.

    ``X-Has-More`` is always written, including the ``false`` case. A caller
    that has to distinguish "complete" from "this server does not tell me"
    cannot do it from an absent header, and the whole point here is that a
    partial answer is never mistaken for a whole one.
    """
    response.headers[HEADER_RESULT_OFFSET] = str(page.offset)
    response.headers[HEADER_RESULT_COUNT] = str(len(page.rows))
    response.headers[HEADER_HAS_MORE] = "true" if page.has_more else "false"
    if page.total is not None:
        response.headers[HEADER_TOTAL_COUNT] = str(page.total)
    if page.next_offset is not None:
        response.headers[HEADER_NEXT_OFFSET] = str(page.next_offset)


# Advertised in the OpenAPI schema: a header a caller cannot discover is a
# header a caller will not read, which would leave truncation as silent as it
# was before.
PAGING_RESPONSE_HEADERS: dict[str, dict[str, Any]] = {
    HEADER_TOTAL_COUNT: {
        "description": (
            "Rows matching this query in QuickBooks, across all pages. Absent "
            "only when QuickBooks did not answer the count, in which case "
            "X-Has-More is true because completeness is unknown."
        ),
        "schema": {"type": "integer"},
    },
    HEADER_RESULT_OFFSET: {
        "description": "0-based offset of the first row in this response.",
        "schema": {"type": "integer"},
    },
    HEADER_RESULT_COUNT: {
        "description": "Number of rows in this response.",
        "schema": {"type": "integer"},
    },
    HEADER_HAS_MORE: {
        "description": (
            "'true' when rows matching this query exist past this page. Always "
            "present, including when it is 'false'."
        ),
        "schema": {"type": "string", "enum": ["true", "false"]},
    },
    HEADER_NEXT_OFFSET: {
        "description": (
            "Value to send as `offset` for the next page. Absent on the last "
            "page."
        ),
        "schema": {"type": "integer"},
    },
}

OFFSET_DESCRIPTION = (
    "0-based offset into the result set. QuickBooks returns at most "
    f"{QBO_MAX_PAGE_SIZE} rows per query, so page with this rather than "
    "raising max_results. See the X-Has-More / X-Next-Offset response headers."
)

MAX_RESULTS_DESCRIPTION = (
    f"Rows to return, up to QuickBooks' per-query ceiling of {QBO_MAX_PAGE_SIZE}. "
    "A full page does not mean the result set ended — read X-Has-More."
)
