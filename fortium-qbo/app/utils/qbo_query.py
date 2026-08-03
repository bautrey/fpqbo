"""Literal construction for QuickBooks Online query strings.

QBO's query API takes a SQL-shaped string — ``SELECT * FROM Invoice WHERE
DocNumber = '10044'`` — and the only thing separating a value from a clause
is the pair of quotes around it. Build that string with an f-string and a
caller-supplied value ends the literal early:

    doc_number = "x' OR DocNumber LIKE '%"
    f"DocNumber = '{doc_number}'"
    -> DocNumber = 'x' OR DocNumber LIKE '%'

That query is well formed, returns a 200, and answers a different question
than the caller asked. Nothing downstream can tell the difference, which is
why the fix has to happen where the string is built.

The python-quickbooks SDK offers no parameter binding. ``ListMixin.where()``
takes a finished clause and concatenates it into a ``SELECT``; ``filter()``
and ``choose()`` route through ``utils.build_where_clause`` /
``build_choose_clause``, which interpolate with ``str.format`` and escape a
single quote but leave a backslash alone — so a value ending in ``\\`` still
escapes the closing quote and runs on. There is no bound-parameter API to
reach for, so this module is the substitute, and every QBO query clause in
the service is built here.

Escaping is the last resort, not the first. A value whose type is known gets
validated as that type and re-serialised — a date leaves as ``date.isoformat``
output, an entity id has to be digits — because a value that cannot hold a
quote cannot break out of one. ``string_equals`` is for the genuinely
free-text fields, where a customer really may be called ``O'Brien`` and
rejecting the apostrophe would be a bug of its own.

QBO escapes with a backslash: ``WHERE DisplayName = 'Jane\\'s'``. Both this
module and the SDK's own helpers use that convention. The backslash itself is
escaped first, so it cannot consume the escape that follows it.
"""

import re
from datetime import date, datetime

__all__ = [
    "DATE_OPERATORS",
    "date_bound",
    "escape_string_literal",
    "id_in",
    "string_equals",
    "string_literal",
]

# Field names are compile-time constants at every call site today. Checking
# them anyway is what lets this module be the whole answer: an endpoint added
# later that passes a caller-supplied field name gets a ValueError instead of
# a clause with a value welded into the left-hand side.
_FIELD_NAME = re.compile(r"\A[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*\Z")

# QBO entity ids are numeric strings. Anything else is not an id.
_ENTITY_ID = re.compile(r"\A[0-9]+\Z")

DATE_OPERATORS = frozenset({"=", "<", "<=", ">", ">="})


def _checked_field(field: str) -> str:
    """Return ``field`` if it names a QBO field, else raise."""
    if not isinstance(field, str) or not _FIELD_NAME.match(field):
        raise ValueError(f"Not a QBO field name: {field!r}")
    return field


def escape_string_literal(value: str) -> str:
    """Escape ``value`` for use inside a single-quoted QBO string literal.

    The backslash is escaped before the quote. Doing it the other way round
    would rewrite ``\\`` into ``\\\\`` *after* the quote escape had already
    introduced backslashes of its own, doubling them and corrupting the value.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def string_literal(value: str) -> str:
    """Render ``value`` as a quoted, escaped QBO string literal."""
    return f"'{escape_string_literal(str(value))}'"


def string_equals(field: str, value: str) -> str:
    """Build ``Field = 'value'`` with the value escaped.

    For free-text fields only — anything with a known type should use the
    validating builder for that type instead.
    """
    return f"{_checked_field(field)} = {string_literal(value)}"


def date_bound(field: str, operator: str, value: date | datetime) -> str:
    """Build a date comparison such as ``TxnDate >= '2024-01-01'``.

    ``value`` must already be a ``date``/``datetime``; a string is refused
    rather than escaped, so the only text that reaches the query is
    ``date.isoformat`` output. ``isoformat`` rather than ``strftime`` because
    ``%Y`` is not zero-padded consistently across platforms.
    """
    if operator not in DATE_OPERATORS:
        raise ValueError(f"Not a date comparison operator: {operator!r}")
    if not isinstance(value, date):
        raise TypeError(f"{field} bound must be a date or datetime, got {type(value).__name__}")
    day = value.date() if isinstance(value, datetime) else value
    return f"{_checked_field(field)} {operator} '{day.isoformat()}'"


def id_in(field: str, ids) -> str:
    """Build ``Id in ('1', '2')`` from QBO entity ids.

    Each id is checked against ``[0-9]+`` and refused otherwise. Validation
    rather than escaping because these are ids, and a value proven to be
    digits has no way to carry a quote in the first place.
    """
    checked = []
    for value in ids:
        text = str(value)
        if not _ENTITY_ID.match(text):
            raise ValueError(f"Not a QBO entity id for {field}: {text!r}")
        checked.append(f"'{text}'")
    if not checked:
        raise ValueError(f"No ids to match on {field}")
    return f"{_checked_field(field)} in ({', '.join(checked)})"
