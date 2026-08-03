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

from app.services.qbo_service import QBOService, _txn_date_clause
from app.utils.qbo_query import date_bound, id_in, string_equals

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
    with pytest.raises(TypeError):
        _txn_date_clause("2024-01-01' OR TxnDate > '1900-01-01", None)

    with pytest.raises(TypeError):
        _txn_date_clause(None, "2024-12-31' OR '1'='1")


def test_the_date_clause_still_renders_the_way_it_always_has():
    """Behaviour guard, not a defect proof — this one passes pre-fix too.

    A datetime with a time on it still renders as a bare QBO date, so the
    date-range endpoints select exactly the rows they selected before.
    """
    clause = _txn_date_clause(datetime(2024, 1, 1, 13, 45, 12), datetime(2024, 3, 31))

    assert clause == "TxnDate >= '2024-01-01' AND TxnDate <= '2024-03-31'"


def test_a_date_operator_outside_the_allowed_set_is_refused():
    with pytest.raises(ValueError):
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

    with pytest.raises(ValueError):
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
    with pytest.raises(ValueError):
        string_equals("DocNumber = '1' OR DocNumber", "x")


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
# Neither is a taint analysis. What they are is two cheap properties that
# between them cover every spelling of the original defect, with the shapes
# they do not cover written down rather than assumed away.
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
        return f"{kind}, bound to {node.id!r}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, _FORMATTING_OPS):
        operands = _operands(node)
        inherited = next(
            (kind for kind in (_formatting_kind(o, bindings) for o in operands) if kind),
            None,
        )
        if inherited:
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

    assert _offenders_in_tree(tree, _query_clause_offenders), (
        f"a clause built by {shape} passed the guard"
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


REINTRODUCED_IN_A_NEW_MODULE = '''
"""A new service module, written next year, that does not use the helper."""

from quickbooks.objects.invoice import Invoice


def lookup_clause(doc_number):
    return f"DocNumber = '{doc_number}'"
'''

REINTRODUCED_BY_CONCATENATION = '''
from quickbooks.objects.invoice import Invoice


def lookup_clause(doc_number):
    return "DocNumber = '" + doc_number + "'"
'''


@pytest.mark.parametrize(
    "source", [REINTRODUCED_IN_A_NEW_MODULE, REINTRODUCED_BY_CONCATENATION]
)
def test_the_interpolation_guard_reads_more_than_one_file(tmp_path, source):
    """The defect does not have to come back to the file it left.

    This guard used to read ``services/qbo_service.py`` and nothing else, so a
    new module was free to build its clauses the old way.
    """
    _plant(tmp_path, "new_service.py", source)

    offenders = _scan(
        tmp_path, _interpolated_literal_offenders, files=_query_path_files(tmp_path)
    )

    assert offenders, "a clause built in a new module was not read at all"


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
