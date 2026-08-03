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
from datetime import datetime
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


APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "app"

# The SDK builds its own clauses by string formatting, and escapes a quote but
# not a backslash. Importing these back into the service would reopen the hole
# the helper closes.
FORBIDDEN_SDK_HELPERS = {"build_where_clause", "build_choose_clause"}

QUERY_METHODS = {"where", "count", "filter", "choose", "query"}


def _formatted_string_nodes(tree):
    """Yield (node, arg) for every query call whose clause is built by formatting."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in QUERY_METHODS:
            continue
        args = list(node.args) + [kw.value for kw in node.keywords]
        for arg in args:
            if isinstance(arg, ast.JoinedStr):
                yield node, "f-string"
            elif isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Mod, ast.Add)):
                if isinstance(arg.left, (ast.Constant, ast.JoinedStr)):
                    yield node, "% / + concatenation"
            elif (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "format"
            ):
                yield node, ".format()"


def test_no_query_clause_anywhere_in_the_app_is_built_by_string_formatting():
    """The recurrence guard.

    A sprinkled ``.replace("'", "\\'")`` at each call site is one forgotten
    endpoint away from being back where we started, so the property under
    test is that no query clause is formatted at its call site at all —
    every one of them goes through app.utils.qbo_query.
    """
    offenders = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node, how in _formatted_string_nodes(tree):
            offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{node.lineno} ({how})")

    assert offenders == [], "query clauses built by string formatting: " + ", ".join(
        offenders
    )


def test_the_qbo_date_clause_does_not_interpolate_into_a_quoted_literal():
    """``_txn_date_clause`` builds into a local, so the AST walk above cannot
    see it. Its source is checked directly instead."""
    source = (APP_ROOT / "services" / "qbo_service.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        rendered = "".join(
            part.value for part in node.values if isinstance(part, ast.Constant)
        )
        assert "'" not in rendered, (
            f"qbo_service.py:{node.lineno} interpolates into a quoted literal"
        )


def test_the_service_does_not_reach_for_the_sdk_clause_builders():
    tree = ast.parse((APP_ROOT / "services" / "qbo_service.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert imported & FORBIDDEN_SDK_HELPERS == set()
