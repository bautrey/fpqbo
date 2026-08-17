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
    "QboQueryError",
    "boolean_equals",
    "date_bound",
    "escape_string_literal",
    "id_in",
    "string_equals",
    "string_literal",
]


class QboQueryError(Exception):
    """A QBO query clause could not be built from what the caller passed.

    Deliberately not a ``ValueError``. When this class was written, ``ValueError``
    was the record-not-found signal throughout the service — ``qbo_service``
    raised it for "QBO company not found" and "Bill not found", and around
    eighty router handlers turned it verbatim into a 404. A bad field name
    raised as a ``ValueError`` would have answered ``404 {"detail": "Not a QBO
    field name: 'Doc Number'"}``, and anything routing on the status code would
    record "this record does not exist" and move on.

    That channel is gone as of #15: not-found is now ``QboNotFound`` in
    ``app/exceptions.py``, no ``raise ValueError`` remains in ``qbo_service``,
    and the ``except ValueError -> 404`` clauses were removed. So the original
    hazard no longer exists — but staying outside the ``ValueError``/``TypeError``
    hierarchy is still correct, and for a reason that outlives it: a query this
    module refuses to build is a programmer error, and the only honest answer
    is a 500. Being catchable as a ``ValueError`` would invite exactly the
    reclassification that took eighty handlers to undo.

    None of the conditions raised here is a caller-data condition. Field names
    and operators are module constants at every call site, and the ids come
    from QBO's own LinkedTxn. They are all programmer errors, so the honest
    answer is a 500 that says so, which is what an exception outside the
    ValueError/TypeError hierarchy gets.

    The message is stamped rather than left to each raise site, so it stays
    legible after a router's blanket ``except Exception`` rewraps it as "QBO
    API error: ..." and sends the next reader looking at Intuit.
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"QBO query construction bug: {message}")


# Field names are compile-time constants at every call site today. Checking
# them anyway is what lets this module be the whole answer: an endpoint added
# later that passes a caller-supplied field name gets a QboQueryError instead
# of a clause with a value welded into the left-hand side.
_FIELD_NAME = re.compile(r"\A[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*\Z")

# QBO entity ids are numeric strings. Anything else is not an id.
_ENTITY_ID = re.compile(r"\A[0-9]+\Z")

DATE_OPERATORS = frozenset({"=", "<", "<=", ">", ">="})


def _checked_field(field: str) -> str:
    """Return ``field`` if it names a QBO field, else raise."""
    if not isinstance(field, str) or not _FIELD_NAME.match(field):
        raise QboQueryError(f"Not a QBO field name: {field!r}")
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


def boolean_equals(field: str, value: bool) -> str:
    """Build ``Active = true`` for a QBO boolean field.

    QBO spells booleans as bare ``true``/``false``, unquoted — a quoted
    ``'true'`` is a string literal and the comparison silently matches nothing.

    ``bool`` is checked rather than coerced. Every Python object has a truth
    value, so ``if value`` would accept the string ``"false"`` and build
    ``Active = true`` from it, which is the "confident wrong answer" this
    module exists to prevent. ``isinstance(True, int)`` also holds, so the
    check is on ``bool`` specifically and ``1`` is refused too.
    """
    if not isinstance(value, bool):
        raise QboQueryError(
            f"{field!r} must be a bool, got {type(value).__name__}: {value!r}"
        )
    return f"{_checked_field(field)} = {'true' if value else 'false'}"


def date_bound(field: str, operator: str, value: date | datetime) -> str:
    """Build a date comparison such as ``TxnDate >= '2024-01-01'``.

    ``value`` must already be a ``date``/``datetime``; a string is refused
    rather than escaped, so the only text that reaches the query is
    ``date.isoformat`` output. ``isoformat`` rather than ``strftime`` because
    ``%Y`` is not zero-padded consistently across platforms.

    The bound is rebuilt as a plain ``date`` rather than used as it arrived.
    ``isinstance(value, date)`` admits a subclass, and a subclass may define
    ``isoformat``, so the type check on its own proves the year, month and day
    are numbers and proves nothing at all about the text they render as. The
    ``datetime`` branch already had this — ``value.date()`` returns a ``date``,
    not whatever subclass it was called on — and the other branch now matches
    it. Nothing reaches here with an overridden ``isoformat`` today, since the
    routers parse with ``parse_date_param`` and get a ``datetime`` back, but
    the rule of the module is that the text in the query comes from a type we
    picked, and reading three integers is what makes that true here.
    """
    if operator not in DATE_OPERATORS:
        raise QboQueryError(f"Not a date comparison operator: {operator!r}")
    if not isinstance(value, date):
        raise QboQueryError(
            f"{field} bound must be a date or datetime, got {type(value).__name__}"
        )
    day = date(value.year, value.month, value.day)
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
            raise QboQueryError(f"Not a QBO entity id for {field}: {text!r}")
        checked.append(f"'{text}'")
    if not checked:
        raise QboQueryError(f"No ids to match on {field}")
    return f"{_checked_field(field)} in ({', '.join(checked)})"
