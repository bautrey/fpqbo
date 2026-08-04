"""Tests for QBO query injection on the read endpoints (issue #2).

The endpoints took a caller-supplied value and interpolated it straight into
a QBO query with an f-string:

    Invoice.where(f"DocNumber = '{doc_number}'", qb=client)

QBO's query language is SQL-shaped, so a value carrying a single quote ends
the literal and everything after it becomes clause. ``GET
/api/invoices/by-doc-number/10044'%20OR%20DocNumber%20LIKE%20'%25`` asked
QuickBooks for every invoice in the company and got a 200 with one of them.

That is why nothing here asserts on a status code. The pre-fix query was well
formed and the pre-fix response was a valid 200 — the defect is entirely in
which rows the query selects, so the assertions are on the query string the
service handed to the SDK.

``_decode_literal`` is the shape of the assertion. It walks the clause the
way a QBO parser would, honouring backslash escapes, and reports what landed
inside the quotes and what landed outside. A value is contained when the
whole of it decodes back out of the literal and the trailing remainder is
empty. Anything else — a payload that leaked into clause position, a
backslash that ate the closing quote — shows up as a mismatch or an
unterminated literal rather than as a subtle difference in a magic string.
"""

import ast
import asyncio
import pathlib
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.api_auth import verify_api_key
from app.routers import bill_payments
from app.services.qbo_service import QBOService, _active_clause, _txn_date_clause
from app.utils.qbo_query import (
    QboQueryError,
    boolean_equals,
    date_bound,
    id_in,
    string_equals,
)

# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

# Ends the literal and appends a filter that matches every row. The pre-fix
# service turned this into: DocNumber = '10044' OR DocNumber LIKE '%'
BREAK_OUT = "10044' OR DocNumber LIKE '%"

# The textbook always-true tail.
OR_ALWAYS_TRUE = "x' OR '1'='1"

# A trailing backslash. The SDK's own build_where_clause escapes the quote but
# not the backslash, so this one survives that helper too: the backslash eats
# the closing quote and the literal runs on into whatever follows.
TRAILING_BACKSLASH = "10044\\"

# Not an attack. Real QuickBooks data has apostrophes in it, and a fix that
# rejects or mangles this one has replaced an injection with a wrong answer.
LEGITIMATE_APOSTROPHE = "O'Brien-1"


def _decode_literal(clause: str) -> tuple[str, str, str]:
    """Split ``Field op 'literal'`` into (head, decoded literal, trailing).

    Reads the clause as QBO would: a single quote opens the literal, a
    backslash escapes the character after it, the next unescaped quote closes
    it. Raises when the literal never closes.
    """
    head, quote, rest = clause.partition("'")
    if not quote:
        raise AssertionError(f"no string literal in clause: {clause!r}")

    decoded: list[str] = []
    index = 0
    while index < len(rest):
        char = rest[index]
        if char == "\\":
            if index + 1 >= len(rest):
                raise AssertionError(f"clause ends inside an escape: {clause!r}")
            decoded.append(rest[index + 1])
            index += 2
            continue
        if char == "'":
            return head, "".join(decoded), rest[index + 1 :]
        decoded.append(char)
        index += 1
    raise AssertionError(f"unterminated string literal: {clause!r}")


def assert_contained(clause: str, *, head: str, value: str) -> None:
    """Assert the whole of ``value`` sits inside the literal and nothing else does."""
    actual_head, decoded, trailing = _decode_literal(clause)
    assert actual_head == head, f"clause left of the literal moved: {clause!r}"
    assert decoded == value, f"value did not survive the round trip: {clause!r}"
    assert trailing == "", f"payload escaped into clause position: {clause!r}"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingEntity:
    """Stands in for an SDK entity, recording the clause it was queried with."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.clauses: list[str] = []

    def where(self, clause, order_by="", start_position="", max_results="", qb=None):
        self.clauses.append(clause)
        return [SimpleNamespace(to_dict=lambda row=r: row) for r in self.rows]


def _service(monkeypatch, **entities):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(QBOService, "_get_company", lambda self, cid: object())
    monkeypatch.setattr(QBOService, "_get_client", lambda self, company: object())
    for name, entity in entities.items():
        monkeypatch.setattr(f"app.services.qbo_service.{name}", entity)
    return svc


def _invoice_lookup(monkeypatch, doc_number, rows=()):
    entity = _RecordingEntity(rows)
    svc = _service(monkeypatch, Invoice=entity)
    result = asyncio.run(svc.get_invoice_by_doc_number(company_id=1, doc_number=doc_number))
    return entity.clauses[0], result


def _account_lookup(monkeypatch, account_number, rows=()):
    entity = _RecordingEntity(rows)
    svc = _service(monkeypatch, Account=entity)
    result = asyncio.run(
        svc.get_account_by_number(company_id=1, account_number=account_number)
    )
    return entity.clauses[0], result


# ---------------------------------------------------------------------------
# /api/invoices/by-doc-number/{doc_number} — the reported site
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [BREAK_OUT, OR_ALWAYS_TRUE, TRAILING_BACKSLASH])
def test_a_doc_number_payload_cannot_reach_clause_position(monkeypatch, payload):
    """The whole path param has to stay a value.

    Pre-fix, BREAK_OUT produced ``DocNumber = '10044' OR DocNumber LIKE '%'``
    — a query that selects the entire invoice list.
    """
    clause, _ = _invoice_lookup(monkeypatch, payload)

    assert_contained(clause, head="DocNumber = ", value=payload)


def test_the_injected_doc_number_renders_as_one_escaped_equality(monkeypatch):
    """The exact string, spelled out, for the payload from the issue.

    ``assert_contained`` proves the payload cannot reach clause position.
    This proves the clause that replaced it is still a single DocNumber
    equality — a fix that dropped the filter would also contain the payload,
    and would be the same wrong answer by another route.

        pre-fix:  DocNumber = '10044' OR DocNumber LIKE '%'
        post-fix: DocNumber = '10044\\' OR DocNumber LIKE \\'%'
    """
    clause, _ = _invoice_lookup(monkeypatch, BREAK_OUT)

    assert clause == r"DocNumber = '10044\' OR DocNumber LIKE \'%'"


def test_a_doc_number_with_an_apostrophe_still_finds_its_invoice(monkeypatch):
    """Escaping must not cost the legitimate case.

    Pre-fix this one broke too — ``DocNumber = 'O'Brien-1'`` is a malformed
    query, so a real document number with an apostrophe in it never resolved.
    """
    row = {"Id": "1", "DocNumber": LEGITIMATE_APOSTROPHE}
    clause, result = _invoice_lookup(monkeypatch, LEGITIMATE_APOSTROPHE, rows=[row])

    assert_contained(clause, head="DocNumber = ", value=LEGITIMATE_APOSTROPHE)
    assert result == row


# ---------------------------------------------------------------------------
# /api/accounts/by-number/{account_number} — the same defect, second site
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [BREAK_OUT, OR_ALWAYS_TRUE, TRAILING_BACKSLASH])
def test_an_account_number_payload_cannot_reach_clause_position(monkeypatch, payload):
    """Not named in the issue, same construction, same exposure."""
    clause, _ = _account_lookup(monkeypatch, payload)

    assert_contained(clause, head="AcctNum = ", value=payload)


def test_an_account_number_with_an_apostrophe_still_finds_its_account(monkeypatch):
    row = {"Id": "9", "AcctNum": LEGITIMATE_APOSTROPHE}
    clause, result = _account_lookup(monkeypatch, LEGITIMATE_APOSTROPHE, rows=[row])

    assert_contained(clause, head="AcctNum = ", value=LEGITIMATE_APOSTROPHE)
    assert result == row


# ---------------------------------------------------------------------------
# Date bounds — validated as dates, not escaped as text
# ---------------------------------------------------------------------------


def test_a_date_bound_that_is_not_a_date_is_refused_by_type(monkeypatch):
    """The date path is closed by the type, not by escaping.

    Routers parse these params with ``parse_date_param`` and hand down a
    ``datetime``. ``date_bound`` refuses anything else outright, so a string
    bound cannot reach the query even if a future caller passes one straight
    through.
    """
    with pytest.raises(QboQueryError):
        _txn_date_clause("2024-01-01' OR TxnDate > '1900-01-01", None)

    with pytest.raises(QboQueryError):
        _txn_date_clause(None, "2024-12-31' OR '1'='1")


def test_the_date_clause_still_renders_the_way_it_always_has():
    """Behaviour guard, not a defect proof — this one passes pre-fix too.

    A datetime with a time on it still renders as a bare QBO date, so the
    date-range endpoints select exactly the rows they selected before.
    """
    clause = _txn_date_clause(datetime(2024, 1, 1, 13, 45, 12), datetime(2024, 3, 31))

    assert clause == "TxnDate >= '2024-01-01' AND TxnDate <= '2024-03-31'"


def test_a_date_operator_outside_the_allowed_set_is_refused():
    with pytest.raises(QboQueryError):
        date_bound("TxnDate", ">= '1900-01-01' OR TxnDate <", datetime(2024, 1, 1))


class _HostileDate(date):
    """A date that passes ``isinstance`` and renders as a clause."""

    def isoformat(self):
        return "2024-01-01' OR TxnDate > '1900-01-01"


class _HostileDatetime(datetime):
    def isoformat(self, *args, **kwargs):
        return "2024-03-31' OR TxnDate > '1900-01-01"


@pytest.mark.parametrize(
    "value, expected",
    [
        (_HostileDate(2024, 1, 1), "TxnDate >= '2024-01-01'"),
        (_HostileDatetime(2024, 3, 31, 13, 45), "TxnDate >= '2024-03-31'"),
    ],
)
def test_a_date_subclass_does_not_get_to_choose_the_text_in_the_query(value, expected):
    """``isinstance(value, date)`` is a check on the type, not on the text.

    A subclass satisfies it and then answers ``isoformat`` with anything it
    likes. Nothing reaches ``date_bound`` with an overridden ``isoformat``
    today — the routers parse with ``parse_date_param`` and hand down a
    ``datetime`` — so this is the type check being made to mean what the
    module says it means, ahead of the caller that would otherwise find out
    the hard way.
    """
    assert date_bound("TxnDate", ">=", value) == expected


# ---------------------------------------------------------------------------
# Entity ids — validated as digits
# ---------------------------------------------------------------------------


class _FakeBillWithLinkedId:
    def __init__(self, txn_id):
        self.txn_id = txn_id

    def get(self, bill_id, qb=None):
        return SimpleNamespace(
            Id=str(bill_id),
            LinkedTxn=[SimpleNamespace(TxnType="BillPaymentCheck", TxnId=self.txn_id)],
        )


def test_a_linked_txn_id_that_is_not_digits_never_reaches_the_query(monkeypatch):
    """The id list is built from QBO's own LinkedTxn, and is checked anyway.

    ``build_choose_clause`` — the SDK helper this replaced — escapes a quote
    but not a backslash, so ``65852\\`` produced ``Id in ('65852\\')``: an
    unterminated literal that runs on into whatever the SDK appends next.
    """
    payments = _RecordingEntity()
    svc = _service(
        monkeypatch, Bill=_FakeBillWithLinkedId(TRAILING_BACKSLASH), BillPayment=payments
    )

    with pytest.raises(QboQueryError):
        asyncio.run(svc.get_bill_payments_by_bill_id(company_id=1, bill_id=64848))

    assert payments.clauses == [], "no query should have been issued at all"


def test_numeric_ids_keep_the_clause_shape_the_lookup_already_used():
    assert id_in("Id", ["65852"]) == "Id in ('65852')"
    assert id_in("Id", ["65852", "94628"]) == "Id in ('65852', '94628')"


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_string_equals_escapes_the_backslash_before_the_quote():
    """Order matters. Escaping the quote first would then double the
    backslashes it just introduced and corrupt the value."""
    assert string_equals("DocNumber", "a\\'b") == "DocNumber = 'a\\\\\\'b'"
    assert _decode_literal(string_equals("DocNumber", "a\\'b"))[1] == "a\\'b"


def test_a_caller_supplied_field_name_is_refused():
    """The helper is only a gate if the left-hand side is a field name too."""
    with pytest.raises(QboQueryError):
        string_equals("DocNumber = '1' OR DocNumber", "x")


def test_a_boolean_renders_unquoted():
    """QBO's `true` is a boolean; `'true'` is a string that matches nothing.

    A quoted literal here would not error — it would return an empty result
    set for every active vendor in the file, which is the failure mode this
    module exists to keep out of the query.
    """
    assert boolean_equals("Active", True) == "Active = true"
    assert boolean_equals("Active", False) == "Active = false"


@pytest.mark.parametrize(
    "payload", ["true", "false", "", 1, 0, None, [], "Active = true OR 1=1"]
)
def test_a_boolean_that_is_not_a_bool_is_refused_by_type(payload):
    """Truthiness is not the test. `if value` would read the string "false"
    as true and build `Active = true` from it — a clause that answers a
    different question than the caller asked, with a 200."""
    with pytest.raises(QboQueryError):
        boolean_equals("Active", payload)


def test_the_active_clause_is_the_filter_it_replaced():
    """`Entity.filter(Active=True)` became a where-clause so the read could
    page. The clause has to mean the same thing the filter did."""
    assert _active_clause(True) == "Active = true"
    assert _active_clause(False) is None


# ---------------------------------------------------------------------------
# What the gate says when it refuses
#
# Every refusal above is a programmer error — field names and operators are
# module constants at the call sites, and the ids come from QBO's own
# LinkedTxn. What matters is that none of them can be read as an answer about
# the data, which is what a ValueError would have made them.
# ---------------------------------------------------------------------------

REFUSALS = {
    "field name": lambda: string_equals("DocNumber = '1' OR DocNumber", "x"),
    "date operator": lambda: date_bound("TxnDate", "LIKE", datetime(2024, 1, 1)),
    "date type": lambda: date_bound("TxnDate", ">=", "2024-01-01"),
    "entity id": lambda: id_in("Id", ["65852", "not-an-id"]),
    "empty id list": lambda: id_in("Id", []),
}


@pytest.mark.parametrize("refusal", sorted(REFUSALS))
def test_a_query_that_cannot_be_built_is_never_the_not_found_signal(refusal):
    """`ValueError` means "no such record" in this service.

    ``qbo_service`` raises it for "QBO company not found" and "Bill not
    found", and about thirty router handlers answer it with a 404 and the
    message verbatim. Raised from here, a bad field name would answer ``404
    {"detail": "Not a QBO field name: ..."}``, and a caller routing on the
    status code — a sync job, another service — would write down that the
    record does not exist. That is this PR's own defect class moved into the
    error channel: a confident wrong answer wearing the shape of a normal
    negative result.

    ``TypeError`` is no better on the other side: it lands in the routers'
    blanket ``except Exception`` as ``500 "QBO API error: ..."``, which sends
    whoever reads that line to Intuit's status page for a local type error.
    """
    with pytest.raises(QboQueryError) as raised:
        REFUSALS[refusal]()

    assert not isinstance(raised.value, (ValueError, TypeError)), (
        "a 404 handler or a QBO-fault handler would catch this"
    )
    assert "QBO query construction bug" in str(raised.value), (
        "the message has to survive a rewrap as 'QBO API error: ...'"
    )


class _ServiceThatCannotBuildItsQuery:
    """A service whose clause builder refuses what it was handed."""

    async def get_bill_payments_by_bill_id(self, company_id, bill_id):
        return id_in("Id", [f"65852{TRAILING_BACKSLASH}"])


def test_a_query_that_cannot_be_built_is_not_answered_as_a_missing_bill():
    """The same thing again, at the status code a caller actually sees.

    ``/bill-payments/by-bill/{bill_id}`` answers "has this bill been paid?".
    Its handler turns a ValueError into a 404 with the message verbatim,
    byte-identical in shape to "Bill not found" — so a refusal from the clause
    builder used to answer "no such bill" about a bill that exists and may
    well have been paid.
    """
    app = FastAPI()
    app.include_router(bill_payments.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[bill_payments._get_service] = (
        lambda: _ServiceThatCannotBuildItsQuery()
    )
    client = TestClient(app)

    res = client.get("/bill-payments/by-bill/64848", params={"company_id": 1})

    assert res.status_code != 404, "a construction bug read as a missing record"
    assert res.status_code == 500
    assert "QBO query construction bug" in res.json()["detail"]


# ---------------------------------------------------------------------------
# The recurrence guards
#
# Two AST walks over the app tree, with different blind spots on purpose.
#
# The call-site guard knows what a clause is *for* — it only looks at the
# arguments of a query call — and has to work to find out where the string
# came from. The interpolation guard knows how a string is *built* and does
# not care what it is for, so it sees helpers that hand their result back to
# a caller in another function, and pays for that with a narrower file set.
#
# Neither is a taint analysis, and neither can carry "every spelling" — the
# interpolation guard shipped without a `.format()` arm, and a `.format()`
# helper in qbo_service.py reintroduced issue #2 in full with both guards
# green. What they are is two cheap properties, and what they still miss is
# written down here rather than assumed away:
#
#   - a template that is not a string literal in the source. The
#     interpolation guard reads the quote out of the source text, so
#     `TEMPLATE.format(doc)` with the template a module constant is past what
#     it can see. The call-site guard still catches that one when it reaches a
#     query call, because it recognises `.format()` by the call rather than by
#     the quote.
#   - a clause assembled by a function instead of by formatting syntax —
#     `"'".join(parts)` is the one to watch. Neither guard has an arm for it:
#     no literal for the interpolation guard to read the quote out of, and
#     nothing in the call-site guard's list of formatting operations either.
#   - a module that imports neither the SDK nor the clause helpers, builds
#     clause text, and hands it to a caller in another module. The
#     interpolation guard does not read that file (the file set is pinned, and
#     argued for, in
#     `test_the_interpolation_guard_reads_only_the_modules_that_can_query_qbo`)
#     and the call-site guard reads it but finds no query call to hang it on.
#   - THIS FILE'S OWN SUBJECT, `app/utils/qbo_query.py`, is the live instance of
#     the bullet above and deserves naming rather than deduction. It is excluded
#     from the interpolation guard's file set on purpose, and it contains no
#     query call for the call-site guard, so a clause helper added there is
#     unguarded by both. A `.format()` builder planted in it leaves the whole
#     suite green, and its caller in qbo_service.py is then indistinguishable
#     from a legitimate `string_equals(...)`. Since this is the file where the
#     next clause helper naturally gets added, that is the most likely way
#     issue #2 comes back. Every builder here must go through `string_equals` /
#     `id_in` / `date_bound`; a new one that formats its own clause has no
#     guard behind it and needs its own test.
#   - a binding that is not a plain local name. The call-site guard tracks
#     `clause = ...`, not `self.clause = ...`; the interpolation guard covers
#     the attribute case instead, since it never asks where the string went.
# ---------------------------------------------------------------------------

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "app"

# The SDK builds its own clauses by string formatting, and escapes a quote but
# not a backslash. Importing these back into the service would reopen the hole
# the helper closes.
FORBIDDEN_SDK_HELPERS = {"build_where_clause", "build_choose_clause"}

QUERY_METHODS = {"where", "count", "filter", "choose", "query"}

# Both `+` and `%` build a string out of a constant and a value. `*` and the
# rest cannot, so they are arithmetic and are left alone.
_FORMATTING_OPS = (ast.Add, ast.Mod)

# A local bound to a string that nothing has formatted yet. Tracked because
# `clause = "DocNumber = '"` followed by `clause += doc` is the same defect
# spelled across two statements.
_UNFORMATTED = "string constant"

# A description composes — `concatenation of a <kind>`, `<kind>, bound to
# 'clause'` — and the binding pass below runs to a fixpoint, re-deriving
# `clause += value` from the kind the previous pass stored. Uncapped, that
# grows a wrapper per pass, and the `+=` shape reported itself as a
# "concatenation of a concatenation of a concatenation of a ..., bound to
# 'clause', bound to 'clause', ...". Two levels name the formatting and where
# it was bound; past that the file and the line are buried in the noise.
_MAX_KIND_NESTING = 2


def _nesting(kind: str) -> int:
    """How many times a description has been wrapped around another."""
    return kind.count(" of a ") + kind.count(", bound to ")


def _operands(node):
    """Flatten a chain of ``+``/``%`` into the operands it joins.

    ``"DocNumber = '" + doc + "'"`` parses as ``BinOp(BinOp(str, doc), str)``,
    so a check that reads ``node.left`` finds a BinOp there, not a constant,
    and falls through. That is not a corner case: it is the plainest way to
    write the defect, and it is why this returns a flat list instead.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, _FORMATTING_OPS):
        return _operands(node.left) + _operands(node.right)
    return [node]


def _constant_text(node) -> str | None:
    """The text of ``node`` when it is a string constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_unformatted_string(node, bindings) -> bool:
    """True for a string constant, or a name holding one."""
    if _constant_text(node) is not None:
        return True
    return isinstance(node, ast.Name) and bindings.get(node.id) == _UNFORMATTED


def _formatting_kind(node, bindings) -> str | None:
    """Name the formatting that builds ``node``, or None when nothing does.

    ``bindings`` maps names bound earlier in this scope, or in an enclosing
    one, to the kind of string they hold — without it, a clause built into a
    local one line above the query call is invisible.
    """
    if isinstance(node, ast.JoinedStr):
        return "f-string"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"format", "format_map"}
    ):
        return ".format()"
    if isinstance(node, ast.Name):
        kind = bindings.get(node.id)
        if kind is None or kind == _UNFORMATTED:
            return None
        if _nesting(kind) >= _MAX_KIND_NESTING:
            return kind
        return f"{kind}, bound to {node.id!r}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, _FORMATTING_OPS):
        operands = _operands(node)
        inherited = next(
            (kind for kind in (_formatting_kind(o, bindings) for o in operands) if kind),
            None,
        )
        if inherited:
            if _nesting(inherited) >= _MAX_KIND_NESTING:
                return inherited
            return f"concatenation of a {inherited}"
        text = [o for o in operands if _is_unformatted_string(o, bindings)]
        values = [o for o in operands if not _is_unformatted_string(o, bindings)]
        # Text joined to something that is not text. `offset + 1` has no text
        # in it and is arithmetic; `"a" + "b"` has no value in it and is one
        # constant written twice.
        if text and values:
            return "% / + concatenation"
    return None


def _binding_kind(value, bindings) -> str | None:
    """What a name bound to ``value`` would be holding."""
    kind = _formatting_kind(value, bindings)
    if kind:
        return kind
    return _UNFORMATTED if _is_unformatted_string(value, bindings) else None


def _assignments(node):
    """Yield (name, value) for every binding of a plain local name."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id, node.value
    elif isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.value is not None:
            yield node.target.id, node.value
    elif isinstance(node, ast.NamedExpr):
        if isinstance(node.target, ast.Name):
            yield node.target.id, node.value
    elif isinstance(node, ast.AugAssign):
        if isinstance(node.target, ast.Name):
            # `clause += value` binds what `clause = clause + value` would.
            yield (
                node.target.id,
                ast.BinOp(
                    left=ast.Name(id=node.target.id, ctx=ast.Load()),
                    op=node.op,
                    right=node.value,
                ),
            )


_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

# The binding pass is flow-insensitive and visits statements in whatever order
# the walk produces, so `a = f"..."` may be seen after `b = a`. Repeating it
# until it stops changing settles those chains; four passes is well past what
# any of them need and keeps a pathological file from looping.
_BINDING_PASSES = 4


def _split_scope(scope):
    """Split ``scope`` into (its own nodes, the scopes nested directly in it)."""
    body = scope.body if isinstance(scope.body, list) else [scope.body]
    own, nested, stack = [], [], list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPE_NODES):
            nested.append(node)
            continue
        own.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return own, nested


def _bindings_in(nodes, inherited):
    bindings = dict(inherited)
    for _ in range(_BINDING_PASSES):
        before = dict(bindings)
        for node in nodes:
            for name, value in _assignments(node):
                kind = _binding_kind(value, bindings)
                if kind is None:
                    continue
                # A name that has held a formatted string once keeps that
                # mark. Letting a later plain assignment clear it would make
                # the answer depend on the order the walk happened to visit
                # the statements in, and `clause = "DocNumber = '"` followed
                # by `clause += doc` reads in exactly the order that clears it.
                held = bindings.get(name)
                if kind == _UNFORMATTED and held not in (None, _UNFORMATTED):
                    continue
                bindings[name] = kind
        if bindings == before:
            break
    return bindings


def _query_clause_offenders(scope, inherited=None):
    """Yield (lineno, how) for every query call handed a formatted clause."""
    own, nested = _split_scope(scope)
    bindings = _bindings_in(own, inherited or {})
    for node in own:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in QUERY_METHODS:
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            how = _formatting_kind(arg, bindings)
            if how:
                yield node.lineno, how
    for child in nested:
        # A nested def reads the enclosing locals, and that is exactly the
        # shape the service uses: the clause is built, then a closure hands it
        # to the SDK inside `_to_thread_with_retry`.
        yield from _query_clause_offenders(child, bindings)


def _offenders_in_tree(tree, finder):
    return sorted(set(finder(tree)))


def _scan(root, finder, files=None):
    """Run ``finder`` over ``files`` (default: every .py under ``root``)."""
    offenders = []
    for path in sorted(root.rglob("*.py") if files is None else files):
        tree = ast.parse(path.read_text(), filename=str(path))
        for lineno, how in _offenders_in_tree(tree, finder):
            offenders.append(f"{path.relative_to(root.parent)}:{lineno} ({how})")
    return offenders


def test_no_query_clause_anywhere_in_the_app_is_built_by_string_formatting():
    """The recurrence guard.

    A sprinkled ``.replace("'", "\\'")`` at each call site is one forgotten
    endpoint away from being back where we started, so the property under
    test is that no query clause is formatted at its call site at all —
    every one of them goes through app.utils.qbo_query.
    """
    offenders = _scan(APP_ROOT, _query_clause_offenders)

    assert offenders == [], "query clauses built by string formatting: " + ", ".join(
        offenders
    )


# ---------------------------------------------------------------------------
# The call-site guard, against the shapes it has to catch
#
# These are fixtures rather than files under app/ because a file under app/ is
# a file someone can import. They are parsed by the same function that reads
# the real tree, so the guard cannot be narrowed without one of them going
# green.
# ---------------------------------------------------------------------------

VIOLATING_CALL_SITES = {
    "f-string": """
Invoice.where(f"DocNumber = '{doc}'", qb=client)
""",
    "keyword f-string": """
Invoice.where(clause=f"DocNumber = '{doc}'", qb=client)
""",
    ".format()": """
Invoice.where("DocNumber = '{}'".format(doc), qb=client)
""",
    "% formatting": """
Invoice.where("DocNumber = '%s'" % doc, qb=client)
""",
    # The reviewer's probe. The old guard read `arg.left` and found a BinOp
    # rather than a constant here, so this passed it.
    "concatenation of three operands": """
def _new_lookup_clause(entity, client, doc_number):
    return entity.where("DocNumber = '" + doc_number + "'", qb=client)
""",
    "concatenation of two operands": """
Invoice.where("DocNumber = '" + doc, qb=client)
""",
    # The shape of the original `_txn_date_clause` defect: formatted into a
    # local, then handed over. The old guard looked at the call site only.
    "assign then pass": """
clause = f"DocNumber = '{doc}'"
Invoice.where(clause, qb=client)
""",
    "assign then pass, concatenated": """
def lookup(doc):
    clause = "DocNumber = '" + doc + "'"
    return Invoice.where(clause, qb=client)
""",
    "built up in place": """
def lookup(doc):
    clause = "DocNumber = '"
    clause += doc + "'"
    return Invoice.where(clause, qb=client)
""",
    "passed through a second local": """
def lookup(doc):
    built = f"DocNumber = '{doc}'"
    clause = built
    return Invoice.where(clause, qb=client)
""",
    # The service builds its clause and then hands it to the SDK from inside a
    # closure, so the guard has to follow a name into a nested def.
    "used from a closure": """
def lookup(doc):
    clause = f"DocNumber = '{doc}'"

    def _fetch():
        return Invoice.where(clause, qb=client)

    return _fetch()
""",
}

CLEAN_CALL_SITES = {
    "the helper": """
Invoice.where(string_equals("DocNumber", doc), qb=client)
""",
    # `start_position=offset + 1` is arithmetic in a query call's keyword. A
    # guard that flags it is a guard someone deletes.
    "arithmetic in a keyword": """
entity.where(
    clause or "",
    order_by=QBO_PAGE_ORDER_BY,
    start_position=offset + 1,
    max_results=limit,
    qb=client,
)
""",
    "sqlalchemy": """
db.query(QboCompany).filter(QboCompany.id == company_id).first()
""",
    "a formatted string that is not the clause": """
def lookup(doc):
    message = f"Invoice '{doc}' not found"
    rows = Invoice.where(string_equals("DocNumber", doc), qb=client)
    if not rows:
        raise ValueError(message)
    return rows[0]
""",
    "two constants": """
Invoice.where("DocNumber = '1'" " AND Balance > '0'", qb=client)
""",
}


@pytest.mark.parametrize("shape", sorted(VIOLATING_CALL_SITES))
def test_the_call_site_guard_catches_every_way_of_formatting_a_clause(shape):
    tree = ast.parse(VIOLATING_CALL_SITES[shape])

    offenders = _offenders_in_tree(tree, _query_clause_offenders)

    assert offenders, f"a clause built by {shape} passed the guard"
    for _, how in offenders:
        # The file and the line are what a failure is read for. A description
        # that nests once per binding pass buries them, and this guard's whole
        # bet is that it is not annoying enough to be deleted.
        assert _nesting(how) <= _MAX_KIND_NESTING, (
            f"the description of {shape} nests without limit: {how}"
        )


@pytest.mark.parametrize("shape", sorted(CLEAN_CALL_SITES))
def test_the_call_site_guard_leaves_the_legitimate_shapes_alone(shape):
    """False positives are how a guard gets deleted."""
    tree = ast.parse(CLEAN_CALL_SITES[shape])

    assert _offenders_in_tree(tree, _query_clause_offenders) == [], (
        f"the guard flagged {shape}"
    )


# ---------------------------------------------------------------------------
# The interpolation guard — every module that can build a QBO query
# ---------------------------------------------------------------------------

# A module that imports the SDK can hand a string to QBO; a module that
# imports the clause helpers is on the same path by construction. This is the
# capability, not a list of file names, so a new service module is covered the
# day it is written.
_QUERY_PATH_IMPORTS = ("quickbooks", "app.utils.qbo_query")


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def _is_on_the_query_path(tree) -> bool:
    return any(
        name == root or name.startswith(f"{root}.")
        for name in _imported_modules(tree)
        for root in _QUERY_PATH_IMPORTS
    )


def _query_path_files(root):
    """The modules under ``root`` that can put a string into a QBO query.

    ``app/utils/qbo_query.py`` is excluded: quoting values is the one thing it
    exists to do, and its literals are covered by the unit tests above. It is
    the sanitiser, so it is the one file the taint check must not read.
    """
    builder = root / "utils" / "qbo_query.py"
    for path in sorted(root.rglob("*.py")):
        if path == builder:
            continue
        if _is_on_the_query_path(ast.parse(path.read_text(), filename=str(path))):
            yield path


def _interpolated_literal_offenders(tree):
    """Yield (lineno, how) for a value formatted into a quoted literal.

    The clause is a value's only container. A string built by putting
    something between two ``'`` is either a QBO literal or it is a sentence
    that reads like one, and on the query path the difference is not worth
    guessing at.

    One arm per way of writing it: the f-string, ``+``/``%``, and
    ``.format()``. The last one is here because it is what the SDK's own
    ``build_where_clause`` builds clauses with, so it is the spelling the next
    person copies — and it is the arm this guard shipped without.

    All three read the quote out of the source, so all three stop where the
    template is not a literal. ``TEMPLATE.format(doc)`` is past this one and
    is caught by the call-site guard, which recognises ``.format()`` by the
    call. ``"'".join(parts)`` is past both, and is written down as such in the
    comment above.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            has_value = any(isinstance(p, ast.FormattedValue) for p in node.values)
            text = "".join(
                p.value for p in node.values if isinstance(p, ast.Constant)
            )
            if has_value and "'" in text:
                yield node.lineno, "f-string into a quoted literal"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, _FORMATTING_OPS):
            operands = _operands(node)
            text = [t for t in map(_constant_text, operands) if t is not None]
            values = [o for o in operands if _constant_text(o) is None]
            if text and values and any("'" in t for t in text):
                yield node.lineno, "concatenation into a quoted literal"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"format", "format_map"}
        ):
            template = _constant_text(node.func.value)
            # The quote has to be in the template. `"{0}/company/{1}/bill"
            # .format(...)` builds a url, and joining two finished clauses
            # with `"{} AND {}"` puts no quote of its own into either.
            if (
                template is not None
                and (node.args or node.keywords)
                and "'" in template
            ):
                yield node.lineno, ".format() into a quoted literal"


def test_no_module_on_the_query_path_interpolates_into_a_quoted_literal():
    """The second guard, and the one that carries the shapes the first cannot.

    ``_txn_date_clause`` builds its clause and returns it — the call-site
    guard follows a name within a function and into the closures inside it,
    but not out through a return into another module. This one does not care
    who the caller is: on the query path, a value between two quotes is a
    clause being built by hand, wherever it happens.
    """
    offenders = _scan(
        APP_ROOT, _interpolated_literal_offenders, files=_query_path_files(APP_ROOT)
    )

    assert offenders == [], "values interpolated into quoted literals: " + ", ".join(
        offenders
    )


def _plant(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    return path


REINTRODUCED_IN_A_NEW_MODULE = {
    "f-string": '''
"""A new service module, written next year, that does not use the helper."""

from quickbooks.objects.invoice import Invoice


def lookup_clause(doc_number):
    return f"DocNumber = '{doc_number}'"
''',
    "concatenation": '''
from quickbooks.objects.invoice import Invoice


def lookup_clause(doc_number):
    return "DocNumber = '" + doc_number + "'"
''',
    # The shape that got past both guards. `.format()` is what the SDK's own
    # helpers build clauses with, so it is the spelling someone reaches for
    # after reading them — and it is issue #2 exactly: a caller sending
    # `10044' OR DocNumber LIKE '%` gets the whole invoice list with a 200.
    ".format()": '''
from quickbooks.objects.invoice import Invoice


def lookup_clause(doc_number):
    return "DocNumber = '{}'".format(doc_number)
''',
    ".format_map()": '''
from quickbooks.objects.invoice import Invoice


def lookup_clause(doc_number):
    return "DocNumber = '{doc}'".format_map({"doc": doc_number})
''',
    # The same miss one spelling further out: built into an attribute in one
    # method, queried in another. Plain local names are the only bindings the
    # call-site guard tracks, so `self.clause` is out of its reach at both
    # ends — which is why this arm cannot depend on where the string goes.
    ".format() into an attribute": '''
from quickbooks.objects.invoice import Invoice


class Lookup:
    def build(self, doc_number):
        self.clause = "DocNumber = '{}'".format(doc_number)

    def run(self, client):
        return Invoice.where(self.clause, qb=client)
''',
}

# Formatting is not the defect; formatting *into a quoted literal* is. These
# are on the query path, they format, and they must stay clean.
NOT_A_CLAUSE_ON_THE_QUERY_PATH = {
    # The only two `.format()` calls the service has today
    # (qbo_service.py:1079 and :1577) build a REST url. No quote in the
    # template means no literal to break out of.
    "a url built by .format()": '''
from quickbooks.objects.bill import Bill


def bill_url(client):
    return "{0}/company/{1}/bill".format(client.api_url, client.company_id)
''',
    # Joining finished clauses. The quotes are already in the values, put
    # there by the helper; the template holds an operator and nothing else.
    "clauses joined by .format()": '''
from app.utils.qbo_query import date_bound, string_equals


def combined(doc, start):
    return "{} AND {}".format(
        string_equals("DocNumber", doc), date_bound("TxnDate", ">=", start)
    )
''',
}


@pytest.mark.parametrize("shape", sorted(REINTRODUCED_IN_A_NEW_MODULE))
def test_the_interpolation_guard_catches_every_spelling_in_a_new_module(
    tmp_path, shape
):
    """The defect does not have to come back to the file, or the syntax, it left.

    This guard used to read ``services/qbo_service.py`` and nothing else, so a
    new module was free to build its clauses the old way. These modules are
    planted whole and scanned by the same function that reads the real tree,
    so the guard cannot be narrowed on either axis without one going green.
    """
    _plant(tmp_path, "new_service.py", REINTRODUCED_IN_A_NEW_MODULE[shape])

    offenders = _scan(
        tmp_path, _interpolated_literal_offenders, files=_query_path_files(tmp_path)
    )

    assert offenders, f"a clause built by {shape} in a new module was not flagged"


@pytest.mark.parametrize("shape", sorted(NOT_A_CLAUSE_ON_THE_QUERY_PATH))
def test_the_interpolation_guard_leaves_the_formatting_that_is_not_a_clause_alone(
    tmp_path, shape
):
    """False positives are how a guard gets deleted — the second guard too."""
    _plant(tmp_path, "new_service.py", NOT_A_CLAUSE_ON_THE_QUERY_PATH[shape])

    offenders = _scan(
        tmp_path, _interpolated_literal_offenders, files=_query_path_files(tmp_path)
    )

    assert offenders == [], f"the guard flagged {shape}"


def test_the_interpolation_guard_reads_only_the_modules_that_can_query_qbo():
    """The boundary, pinned deliberately.

    Run over every file under app/, this guard flags four legitimate strings —
    ``Invoice with DocNumber '{doc_number}' not found``, ``Must be 'US' or
    'CA'``, a sentence containing ``QuickBooks'``, and the helper module's own
    literals. None is a query. A guard that reports those is a guard that gets
    deleted the third time it fails a build, so it reads the modules that
    import the SDK or the clause helpers, and no others.

    The cost is written down rather than assumed: a module that builds clause
    text and imports neither is not read here, and is caught only if it hands
    the result to a query call in the same function, where the call-site guard
    can see it.
    """
    scanned = set(_query_path_files(APP_ROOT))

    assert APP_ROOT / "services" / "qbo_service.py" in scanned
    assert APP_ROOT / "utils" / "qbo_query.py" not in scanned
    assert APP_ROOT / "routers" / "invoices.py" not in scanned


def test_the_service_does_not_reach_for_the_sdk_clause_builders():
    tree = ast.parse((APP_ROOT / "services" / "qbo_service.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert imported & FORBIDDEN_SDK_HELPERS == set()
