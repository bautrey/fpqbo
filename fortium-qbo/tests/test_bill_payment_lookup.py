"""Tests for `/api/bill-payments/by-bill/{bill_id}`.

The bug: the endpoint pulled the first 1000 BillPayments in the ledger and
filtered them in Python for a link back to the requested bill. 1000 rows is a
few months of a ledger that holds ~27,000, so any bill paid before that window
answered `[]` with a 200 — the same answer as a bill nobody ever paid, to a
question that is asked as "has this been paid?".

Measured against production on 2026-08-03:

    bill 64848  2024-01-31  $25,000.00  Balance 0  ->  [] (0 payments)
    bill 64689  2024-01-31  $ 6,896.78  Balance 0  ->  [] (0 payments)
    bill 93809  2026-06-15  $ 2,707.20  Balance 0  ->  1 payment

Bill 64848's own LinkedTxn names BillPayment 65852 (TxnDate 2024-03-13,
$25,000), whose LinkedTxn names bill 64848 back. The link was there the whole
time, one query away, on the bill.

So the lookup now reads the link off the bill and fetches the payments it
names: two queries, and the age of the bill stops mattering. Across twelve
bills recent enough for the old path to work, both routes returned the
identical payment, so this is the same answer where the old one worked and an
answer at all where it did not.

The assertions here are mostly about what the endpoint must never do: return
an empty array for a bill that has a payment, and go looking for it by walking
the ledger.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.exceptions import QboNotFound
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quickbooks.exceptions import ObjectNotFoundException

from app.dependencies.api_auth import verify_api_key
from app.routers import bill_payments
from app.services.qbo_service import QBOService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _linked(txn_id: str, txn_type: str = "BillPaymentCheck"):
    return SimpleNamespace(TxnId=txn_id, TxnType=txn_type, TxnLineId=0)


class _FakeBill:
    """Bill.get, with a LinkedTxn list and QuickBooks' 610 for a missing id."""

    def __init__(self, bills: dict[str, list]):
        self.bills = bills
        self.requested: list[int] = []

    def get(self, bill_id, qb=None):
        self.requested.append(bill_id)
        key = str(bill_id)
        if key not in self.bills:
            raise ObjectNotFoundException("Object Not Found", 610, None)
        return SimpleNamespace(Id=key, LinkedTxn=self.bills[key])


class _FakeBillPayment:
    """BillPayment addressed by Id, with a ledger big enough to be unwalkable.

    `all()` raises: the ledger it would return is the whole point of the bug,
    and a lookup that reaches for it is wrong however many rows it then
    filters correctly.
    """

    def __init__(self, ledger: dict[str, dict]):
        self.ledger = ledger
        self.where_calls: list[dict] = []

    def where(self, clause, order_by="", start_position="", max_results="", qb=None):
        self.where_calls.append({"clause": clause, "max_results": max_results})
        ids = [
            part.strip().strip("'")
            for part in clause.split("(", 1)[1].rstrip(")").split(",")
        ]
        return [
            SimpleNamespace(to_dict=lambda row=self.ledger[i]: row)
            for i in ids
            if i in self.ledger
        ]

    def all(self, order_by="", start_position="", max_results="", qb=None):
        raise AssertionError(
            "the by-bill lookup must not walk the BillPayment ledger"
        )


def _service(monkeypatch, bill_entity, payment_entity):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(QBOService, "_get_company", lambda self, cid: object())
    monkeypatch.setattr(QBOService, "_get_client", lambda self, company: object())
    monkeypatch.setattr("app.services.qbo_service.Bill", bill_entity)
    monkeypatch.setattr("app.services.qbo_service.BillPayment", payment_entity)
    return svc


# The production shape: an old bill whose payment is nowhere near the first
# page of the ledger, and a recent one whose payment is.
LEDGER = {
    "65852": {"Id": "65852", "TxnDate": "2024-03-13", "TotalAmt": 25000.0},
    "94628": {"Id": "94628", "TxnDate": "2026-06-30", "TotalAmt": 2707.2},
}
BILLS = {
    "64848": [_linked("65852")],
    "93809": [_linked("94628")],
    "70000": [],
}


def _lookup(monkeypatch, bill_id, bills=None, ledger=None):
    payments = _FakeBillPayment(LEDGER if ledger is None else ledger)
    svc = _service(monkeypatch, _FakeBill(BILLS if bills is None else bills), payments)
    rows = asyncio.run(svc.get_bill_payments_by_bill_id(company_id=1, bill_id=bill_id))
    return rows, payments


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_a_payment_older_than_the_first_page_is_still_found(monkeypatch):
    """Bill 64848, paid 2024-03-13, is ~28 pages deep in the live ledger.

    This is the reported defect: the endpoint answered `[]` for it in
    production while its payment sat in QuickBooks the whole time.
    """
    rows, _ = _lookup(monkeypatch, 64848)

    assert [r["Id"] for r in rows] == ["65852"]
    assert rows[0]["TotalAmt"] == 25000.0


def test_a_bill_with_a_payment_never_answers_with_an_empty_array(monkeypatch):
    """`[]` is a factual claim that a bill was never paid.

    It is the one answer this endpoint must not give when a payment exists,
    because nothing downstream can tell it apart from a real "unpaid".
    """
    for bill_id in (64848, 93809):
        rows, _ = _lookup(monkeypatch, bill_id)
        assert rows != []


def test_the_lookup_costs_two_queries_not_a_ledger_walk(monkeypatch):
    """Walking ~27,000 payments would be correct and unusable — 28 pages of
    QuickBooks round trips for something two queries answer."""
    rows, payments = _lookup(monkeypatch, 64848)

    assert len(payments.where_calls) == 1
    assert payments.where_calls[0]["clause"] == "Id in ('65852')"
    assert rows


def test_a_bill_with_no_payments_is_an_empty_array_and_no_second_query(monkeypatch):
    """The honest empty case: the bill exists, nothing paid it, and there is
    nothing to look up."""
    rows, payments = _lookup(monkeypatch, 70000)

    assert rows == []
    assert payments.where_calls == []


def test_links_that_are_not_payments_are_not_fetched_as_payments(monkeypatch):
    """A bill also links to purchase orders, vendor credits and reimburse
    charges. Only the BillPayment* types are payments."""
    bills = {
        "80000": [
            _linked("111", "PurchaseOrder"),
            _linked("222", "VendorCredit"),
            _linked("333", "ReimburseCharge"),
            _linked("65852", "BillPaymentCheck"),
        ]
    }
    rows, payments = _lookup(monkeypatch, 80000, bills=bills)

    assert payments.where_calls[0]["clause"] == "Id in ('65852')"
    assert [r["Id"] for r in rows] == ["65852"]


def test_a_credit_card_payment_link_counts_as_a_payment(monkeypatch):
    bills = {"80001": [_linked("94628", "BillPaymentCreditCard")]}
    rows, _ = _lookup(monkeypatch, 80001, bills=bills)

    assert [r["Id"] for r in rows] == ["94628"]


def test_the_same_payment_linked_twice_is_fetched_once(monkeypatch):
    bills = {"80002": [_linked("65852"), _linked("65852")]}
    rows, payments = _lookup(monkeypatch, 80002, bills=bills)

    assert payments.where_calls[0]["clause"] == "Id in ('65852')"
    assert [r["Id"] for r in rows] == ["65852"]


def test_the_payment_query_asks_for_the_full_page_ceiling(monkeypatch):
    """A bill settled in many partial payments must not be truncated by the
    100-row default QuickBooks applies when no MAXRESULTS is sent."""
    _, payments = _lookup(monkeypatch, 64848)

    assert payments.where_calls[0]["max_results"] == 1000


def test_a_bill_that_does_not_exist_is_not_a_bill_without_payments(monkeypatch):
    """QuickBooks' 610 has to stay distinguishable from "nothing paid it"."""
    payments = _FakeBillPayment(LEDGER)
    svc = _service(monkeypatch, _FakeBill(BILLS), payments)

    # QboNotFound rather than ValueError since #15: the type now carries the
    # 404 instead of the router inferring one from "any ValueError is a miss".
    with pytest.raises(QboNotFound, match="Bill not found: 99999999") as caught:
        asyncio.run(svc.get_bill_payments_by_bill_id(company_id=1, bill_id=99999999))
    assert caught.value.status_code == 404

    assert payments.where_calls == []


# ---------------------------------------------------------------------------
# Partial resolution
#
# The bill names its payments; the second query fetches them. Nothing made the
# two agree, so a payment id the bill named and QuickBooks did not return was
# dropped without a word. QBO leaves the LinkedTxn on the bill on some delete
# paths, so the ids can outlive the payments.
#
# Bill 64848 is $25,000 settled by two partial payments, $15,000 and $10,000.
# Drop one and the endpoint answers 200 with $15,000 for a bill that was paid
# in full. Drop both and it answers `[]`, which is the "paid bill reads as
# unpaid" defect this file exists to close, arriving through another door.
# ---------------------------------------------------------------------------


SPLIT_LEDGER = {
    "65852": {"Id": "65852", "TxnDate": "2024-03-13", "TotalAmt": 15000.0},
    "65853": {"Id": "65853", "TxnDate": "2024-04-10", "TotalAmt": 10000.0},
}
SPLIT_BILLS = {"64848": [_linked("65852"), _linked("65853")]}


def test_a_bill_settled_by_two_payments_returns_both_and_the_full_amount(monkeypatch):
    """Control: when every linked id resolves, both payments come back.

    The check added below must not fire on the case it is meant to let
    through — a bill paid in instalments is ordinary, not an error.
    """
    rows, payments = _lookup(monkeypatch, 64848, bills=SPLIT_BILLS, ledger=SPLIT_LEDGER)

    assert [r["Id"] for r in rows] == ["65852", "65853"]
    assert sum(r["TotalAmt"] for r in rows) == 25000.0
    assert payments.where_calls[0]["clause"] == "Id in ('65852', '65853')"


def test_one_payment_of_two_missing_is_refused_not_answered_short(monkeypatch, caplog):
    """$15,000 is a worse answer than no answer for a bill paid $25,000.

    The caller asked what paid this bill. A subset says the bill is half
    settled and carries no mark saying otherwise, so nothing downstream can
    tell it apart from the truth.
    """
    ledger = {"65852": SPLIT_LEDGER["65852"]}
    payments = _FakeBillPayment(ledger)
    svc = _service(monkeypatch, _FakeBill(SPLIT_BILLS), payments)

    with caplog.at_level(logging.ERROR, logger="app.services.qbo_service"):
        with pytest.raises(Exception) as caught:  # broad: the type is the assertion below
            asyncio.run(svc.get_bill_payments_by_bill_id(company_id=1, bill_id=64848))

    # Not a 404: `routers/bill_payments.py` maps ValueError to "Bill not found",
    # and this bill was found. Reporting a live bill as missing trades one wrong
    # answer for another.
    assert not isinstance(caught.value, (ValueError, TypeError))

    # The id that went missing has to be in the message, or the next person
    # gets "something did not resolve" and a ledger to search by hand.
    assert "65853" in str(caught.value)
    assert "64848" in str(caught.value)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "an unresolved payment id must be logged, not only raised"
    logged = " ".join(r.getMessage() for r in errors)
    assert "65853" in logged
    assert "64848" in logged


def test_no_payment_resolving_is_refused_rather_than_read_as_unpaid(monkeypatch):
    """The 0-of-1 case is byte-identical to a bill nobody ever paid.

    `[]` here would reintroduce the exact confusion this lookup was rewritten
    to remove, so the bill having named a payment has to survive as a refusal.
    """
    payments = _FakeBillPayment({})
    svc = _service(monkeypatch, _FakeBill({"64848": [_linked("65852")]}), payments)

    with pytest.raises(Exception) as caught:  # broad: the type is the assertion below
        asyncio.run(svc.get_bill_payments_by_bill_id(company_id=1, bill_id=64848))

    assert not isinstance(caught.value, (ValueError, TypeError))
    assert "65852" in str(caught.value)
    # The honest empty case still exists and still returns []; bill 70000 has
    # no links at all, so the two are told apart by the bill, not by the count.
    assert _lookup(monkeypatch, 70000)[0] == []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class _StubService:
    def __init__(self, result):
        self.result = result

    async def get_bill_payments_by_bill_id(self, company_id, bill_id):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(service):
    app = FastAPI()
    app.include_router(bill_payments.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[bill_payments._get_service] = lambda: service
    return TestClient(app)


def test_the_endpoint_returns_the_payment_for_an_old_bill():
    client = _client(_StubService([LEDGER["65852"]]))

    res = client.get("/bill-payments/by-bill/64848", params={"company_id": 1})

    assert res.status_code == 200
    assert res.json() == [LEDGER["65852"]]


def test_a_missing_bill_is_a_404_not_an_empty_list():
    # QboNotFound, not ValueError: the router no longer reads ValueError as
    # a missing record — since #15 the status travels with the type.
    client = _client(_StubService(QboNotFound("Bill not found: 99999999")))

    res = client.get("/bill-payments/by-bill/99999999", params={"company_id": 1})

    assert res.status_code == 404
    assert res.json()["detail"] == "Bill not found: 99999999"


def test_a_half_resolved_bill_is_not_served_as_a_200_or_a_404(monkeypatch):
    """Through the router, with the real service: no partial body, no 404.

    404 would say bill 64848 does not exist, and it does. Since #15 the
    not-found channel is QboNotFound rather than any ValueError, and this
    refusal is deliberately neither.
    """
    svc = _service(
        monkeypatch,
        _FakeBill(SPLIT_BILLS),
        _FakeBillPayment({"65852": SPLIT_LEDGER["65852"]}),
    )
    client = _client(svc)

    res = client.get("/bill-payments/by-bill/64848", params={"company_id": 1})

    assert res.status_code != 200, "a bill paid $25,000 must not answer $15,000"
    assert res.status_code != 404, "the bill exists; 404 would deny it"
    assert res.status_code == 500
