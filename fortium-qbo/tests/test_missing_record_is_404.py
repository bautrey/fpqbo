"""A record that does not exist is a 404, on every by-id read (#37).

Every `GET /api/*/{id}` used to answer 500 with QuickBooks' raw error text for
a record that simply is not there. `ReadMixin.get()` raises rather than
returning a falsy object, nothing caught it, and so the `if not result:` guard
in each router was unreachable and the 404 it raises never fired.

n8n hit this building a validator for PartnerConnect's QBO links: a typo'd id
pages an operator as though the API were down, which is a worse failure than
the typo.

**QuickBooks answers with at least three different errors for the same
condition**, and that is the fact these tests exist to pin. Measured against
production on 2026-09-23, id 999999 across all 31 by-id endpoints:

    610  ObjectNotFoundException   28 endpoints
    2010 ValidationException        2 — customers and vendors
    2500 ValidationException        1 — tax agencies

The first cut of this fix hardcoded 610 and 2010 off a 22-endpoint
measurement and applied it to 31. Review caught the gap; the remaining nine
were measured and tax agencies answered with a third code, which would have
left /api/tax/agencies/{id} still returning 500. Enumerating codes is
whack-a-mole, so the helper catches the CLASS: on a by-id GET the id is the
only caller-supplied property, so a validation failure about the REQUEST is
about the id.

**One code in that band is not about the request, and it is the dangerous
one.** `3001 ThrottleExceeded` is QuickBooks saying the client has called too
often, and it arrives as the same ValidationException. Caught by class it
becomes "this record does not exist" — a definite answer about a record the
service never looked at, produced exactly when the service is under load. It
is excluded, and both the exclusion and the constant behind it are pinned
below.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quickbooks.exceptions import (
    ObjectNotFoundException,
    QuickbooksException,
    ValidationException,
)

from app.dependencies.api_auth import verify_api_key
from app.exceptions import QboNotFound
from app.routers import customers as customers_router
from app.services import qbo_service as mod
from app.services.qbo_service import QBOService


# What QuickBooks actually returns, per the measurement above.
NOT_FOUND_610 = ObjectNotFoundException(
    "Object Not Found : Something you're trying to use has been made inactive.",
    error_code=610,
    detail="",
)
# Customers and vendors. Note the message never says "not found" — QuickBooks
# calls a nonexistent id an invalid property.
INVALID_PROPERTY_2010 = ValidationException(
    "Request has invalid or unsupported property",
    error_code=2010,
    detail="Request has invalid or unsupported property",
)
# Tax agencies. The third code, and the one that proved enumerating them fails.
INVALID_REFERENCE_2500 = ValidationException(
    "Invalid Reference Id",
    error_code=2500,
    detail="Invalid Reference Id : TaxAgency element id 999999 not found",
)
# Rate limiting. Same class, same band, and NOT about the request — QuickBooks
# answers HTTP 429 with code 3001 when the client has made too many calls.
THROTTLE_EXCEEDED_3001 = ValidationException(
    "ThrottleExceeded",
    error_code=3001,
    detail="",
)


class _Entity:
    """Stands in for a python-quickbooks entity class."""

    def __init__(self, raises=None, row=None):
        self._raises = raises
        self._row = row
        self.requested_ids = []

    def get(self, entity_id, qb=None):
        self.requested_ids.append(entity_id)
        if self._raises is not None:
            raise self._raises
        return self._row


class _Row:
    def to_dict(self):
        return {"Id": "1397", "DisplayName": "Sendero Consulting"}


def _service(monkeypatch, entity):
    svc = QBOService.__new__(QBOService)
    monkeypatch.setattr(svc, "_get_company", lambda cid: SimpleNamespace(id=cid), raising=False)
    monkeypatch.setattr(svc, "_get_client", lambda company: object(), raising=False)

    async def _no_retry(fn, op=None):
        return fn()

    monkeypatch.setattr(svc, "_to_thread_with_retry", _no_retry, raising=False)
    return svc


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# All three of QuickBooks' not-found shapes become a 404
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raised,label",
    [
        (NOT_FOUND_610, "610-object-not-found"),
        (INVALID_PROPERTY_2010, "2010-invalid-property"),
        (INVALID_REFERENCE_2500, "2500-invalid-reference"),
    ],
    ids=["610", "2010", "2500"],
)
def test_a_missing_record_is_qbo_not_found(monkeypatch, raised, label):
    """The whole of #37. Before the fix both of these escaped as a 500."""
    entity = _Entity(raises=raised)
    svc = _service(monkeypatch, entity)

    with pytest.raises(QboNotFound) as exc:
        _run(svc._fetch_by_id(entity, 999999, client=object(), op="t", label="Customer"))

    assert exc.value.status_code == 404
    assert "999999" in str(exc.value.detail)
    assert "Customer" in str(exc.value.detail)


def test_catching_only_object_not_found_would_leave_three_endpoints_at_500(monkeypatch):
    """Customers, vendors and tax agencies do not raise ObjectNotFoundException.

    This is the test that fails if somebody later "simplifies" the helper down
    to a single `except ObjectNotFoundException`, which is the obvious-looking
    cleanup and was the first cut of this very fix.
    """
    entity = _Entity(raises=INVALID_PROPERTY_2010)
    svc = _service(monkeypatch, entity)

    with pytest.raises(QboNotFound):
        _run(svc._fetch_by_id(entity, 999999, client=object(), op="t", label="Customer"))


# ---------------------------------------------------------------------------
# What survives into the 404, and what must NOT be swallowed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raised,must_appear",
    [
        (NOT_FOUND_610, "Object Not Found"),
        (INVALID_PROPERTY_2010, "invalid or unsupported property"),
        (INVALID_REFERENCE_2500, "Invalid Reference Id"),
    ],
    ids=["610", "2010", "2500"],
)
def test_quickbooks_own_words_survive_into_the_404(monkeypatch, raised, must_appear):
    """The caller has to be able to tell WHY, not just that it failed.

    Parametrized over all three on purpose. The 610 arm shipped dropping
    QuickBooks' text while the validation arm kept it, so the docstring's claim
    held for the three validation endpoints and failed for the twenty-eight
    that answer 610 — and no test saw it, because the only case asserted here
    was 2500. CodeRabbit caught it.

    610's text is not boilerplate everywhere either: tax codes and tax rates
    answer "Object Not Found : TaxCode" and "Object Not Found : TaxRate".
    """
    entity = _Entity(raises=raised)
    svc = _service(monkeypatch, entity)

    with pytest.raises(QboNotFound) as exc:
        _run(svc._fetch_by_id(entity, 999999, client=object(), op="t", label="Thing"))

    detail = str(exc.value.detail)
    assert "999999" in detail
    assert must_appear in detail, f"QuickBooks' own text was dropped: {detail}"


def test_a_throttled_read_is_never_reported_as_a_missing_record(monkeypatch):
    """The hole in the structural argument, found by CodeRabbit on pass 2.

    3001 ThrottleExceeded is a ValidationException like 2010 and 2500, and it
    sits in the same 2000-4999 band, but it is not a complaint about the
    request — it is a complaint about how many requests have been made. A
    class-wide catch turns it into "this record does not exist", which is a
    definite answer about a record the service never managed to look at, at
    exactly the moment it is under load.

    The caller this PR was opened for is a link validator. Under throttling it
    would have retired live QuickBooks customers as missing.
    """
    entity = _Entity(raises=THROTTLE_EXCEEDED_3001)
    svc = _service(monkeypatch, entity)

    with pytest.raises(ValidationException) as exc:
        _run(svc._fetch_by_id(entity, 1397, client=object(), op="t", label="Customer"))

    assert exc.value.error_code == 3001
    assert not isinstance(exc.value, QboNotFound)


def test_the_throttle_code_the_helper_excludes_is_the_documented_one():
    """Stops the test above passing against a constant that drifted.

    If QBO_THROTTLE_EXCEEDED were edited to some code QuickBooks never sends,
    the exclusion would stop working and the test above would still be green
    against whatever the constant now said.
    """
    assert mod.QBO_THROTTLE_EXCEEDED == 3001
    assert THROTTLE_EXCEEDED_3001.error_code == mod.QBO_THROTTLE_EXCEEDED
    # And it has to be inside the band that renders as ValidationException,
    # or the exclusion is guarding an arm the exception never reaches.
    assert 2000 <= mod.QBO_THROTTLE_EXCEEDED <= 4999


def test_an_unrelated_quickbooks_failure_still_propagates(monkeypatch):
    """A transport or server fault is not a 404 either."""
    entity = _Entity(raises=QuickbooksException("upstream exploded", error_code=10000, detail=""))
    svc = _service(monkeypatch, entity)

    with pytest.raises(QuickbooksException) as exc:
        _run(svc._fetch_by_id(entity, 42, client=object(), op="t", label="Bill"))

    assert exc.value.error_code == 10000


# ---------------------------------------------------------------------------
# The happy path still works, and asks for the id the caller named
# ---------------------------------------------------------------------------


def test_an_existing_record_comes_back_and_the_right_id_was_requested(monkeypatch):
    entity = _Entity(row=_Row())
    svc = _service(monkeypatch, entity)

    result = _run(svc._fetch_by_id(entity, 1397, client=object(), op="t", label="Customer"))

    assert result.to_dict()["Id"] == "1397"
    assert entity.requested_ids == [1397]


# ---------------------------------------------------------------------------
# End to end: the status code a consumer actually sees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raised", [NOT_FOUND_610, INVALID_PROPERTY_2010], ids=["610", "2010"]
)
def test_the_router_answers_404_rather_than_500(raised):
    """n8n's case. A typo'd id must not look like an outage.

    QboNotFound subclasses HTTPException and every router reached through
    QBOService re-raises HTTPException first, so this needed no router change —
    which is exactly the thing worth pinning, because it is invisible in the
    diff.
    """

    async def _raise(company_id, customer_id):
        raise QboNotFound(f"Customer {customer_id} not found")

    app = FastAPI()
    app.include_router(customers_router.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[customers_router._get_service] = lambda: SimpleNamespace(
        get_customer_by_id=_raise
    )
    client = TestClient(app, raise_server_exceptions=False)

    res = client.get("/customers/999999", params={"company_id": 1})

    assert res.status_code == 404, f"got {res.status_code}: {res.text[:120]}"
    assert "999999" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Every by-id method goes through the helper
# ---------------------------------------------------------------------------


def test_no_by_id_method_still_reads_without_the_not_found_mapping():
    """A source guard, because there are 31 of them and one helper.

    The failure this prevents is a new by-id method written to the old
    template — `_to_thread_with_retry(_fetch, ...)` with no except — which
    would silently reintroduce the 500 for that one entity. That is how the
    service came to have 31 of them.
    """
    import pathlib
    import re

    src = pathlib.Path(mod.__file__).read_text()
    offenders = []
    for m in re.finditer(r"    async def (get_\w+_by_id)\(", src):
        name = m.group(1)
        body = src[m.start() : src.index("\n    async def ", m.end() + 1)]
        if "_fetch_by_id(" not in body:
            offenders.append(name)

    assert not offenders, (
        "by-id reads not going through _fetch_by_id, so a missing record there "
        "is still a 500: " + ", ".join(offenders)
    )


def test_the_guard_can_see_the_methods_it_is_guarding():
    """Stops the guard above going vacuous if the pattern ever stops matching."""
    import pathlib
    import re

    src = pathlib.Path(mod.__file__).read_text()
    found = re.findall(r"    async def (get_\w+_by_id)\(", src)
    assert len(found) >= 25, f"only found {len(found)} by-id methods — check the pattern"
    assert "get_customer_by_id" in found
    assert "get_vendor_by_id" in found
