"""A read-only API key may read its company and may not write to it.

Why this exists: until 2026-09-17 every API key was all-access within its
company. `verify_api_key` checked that the key was active and that `company_id`
matched, and never looked at the request method, so any key that could read
FOR-138 could also create journal entries and delete invoices in it. Handing a
credential to an outside consumer — a CFO's KPI site, in the case that prompted
this — meant handing over 13 write routes with it.

`can_write` closes that, and these tests are what stop it regressing quietly.

The method gate is only sound because no GET route mutates; that was measured by
AST-scanning every `@router.get` handler for calls to create_/update_/delete_/
void_/save and finding zero. `test_no_get_route_calls_a_mutating_service_method`
below keeps that true rather than leaving it as a claim in a commit message.
"""

import ast
import asyncio
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies.api_auth import verify_api_key


# ---------------------------------------------------------------------------
# Fakes, mirroring test_api_key_company_scoping.py
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, api_key):
        self._api_key = api_key

    def execute(self, *a, **k):
        return _FakeResult(self._api_key)

    def commit(self):
        pass


class _FakeRequest:
    def __init__(self, method: str = "GET"):
        self.state = SimpleNamespace()
        self.method = method


def _make_key(*, can_write: bool, company_id: int = 1):
    return SimpleNamespace(
        id=1,
        company_id=company_id,
        is_active=True,
        can_write=can_write,
        last_used_at=None,
    )


def _run(coro):
    return asyncio.run(coro)


def _verify(method: str, *, can_write: bool, company_id: int | None = 1):
    key = _make_key(can_write=can_write)
    return _run(
        verify_api_key(
            _FakeRequest(method),
            x_api_key="fqbo_x",
            company_id=company_id,
            db=_FakeDB(key),
        )
    )


# ---------------------------------------------------------------------------
# A read-only key reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_a_read_only_key_may_read(method):
    result = _verify(method, can_write=False)
    assert result.can_write is False


# ---------------------------------------------------------------------------
# A read-only key does not write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_read_only_key_is_refused_every_write_verb(method):
    with pytest.raises(HTTPException) as exc:
        _verify(method, can_write=False)
    assert exc.value.status_code == 403


def test_the_refusal_says_read_only_not_something_about_companies():
    """A caller told the wrong thing fixes the wrong thing.

    Both refusals in verify_api_key are 403, so the status code alone cannot
    tell a consumer whether to change its credential's company or stop writing.
    """
    with pytest.raises(HTTPException) as exc:
        _verify("POST", can_write=False)
    assert "read-only" in exc.value.detail.lower()
    assert "company" not in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# A writable key is unaffected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_a_writable_key_is_unaffected(method):
    result = _verify(method, can_write=True)
    assert result.can_write is True


# ---------------------------------------------------------------------------
# Ordering against the company check
# ---------------------------------------------------------------------------


def test_the_company_check_fires_before_the_write_check():
    """A key aimed at the wrong company hears about the company, not the verb.

    Both conditions are true here: read-only key, write verb, wrong company.
    Reporting "read-only" would send the caller to change its credential when
    the actual problem is that it is pointed at someone else's books.
    """
    with pytest.raises(HTTPException) as exc:
        _verify("POST", can_write=False, company_id=5)
    assert exc.value.status_code == 403
    assert "company" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# Through a real request, not just the dependency
# ---------------------------------------------------------------------------


def _client(key):
    app = FastAPI()

    @app.get("/probe")
    async def _read(api_key=Depends(verify_api_key)):
        return {"ok": True}

    @app.post("/probe")
    async def _write(api_key=Depends(verify_api_key)):
        return {"ok": True}

    app.dependency_overrides[get_db] = lambda: _FakeDB(key)
    return TestClient(app, raise_server_exceptions=False)


def test_over_http_a_read_only_key_gets_200_on_get_and_403_on_post():
    client = _client(_make_key(can_write=False))
    headers = {"X-API-Key": "fqbo_x"}
    assert client.get("/probe", params={"company_id": 1}, headers=headers).status_code == 200
    r = client.post("/probe", params={"company_id": 1}, headers=headers)
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"].lower()


def test_over_http_a_writable_key_gets_200_on_both():
    client = _client(_make_key(can_write=True))
    headers = {"X-API-Key": "fqbo_x"}
    assert client.get("/probe", params={"company_id": 1}, headers=headers).status_code == 200
    assert client.post("/probe", params={"company_id": 1}, headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# The assumption the method gate rests on
# ---------------------------------------------------------------------------


MUTATING_PREFIXES = ("create_", "update_", "delete_", "void_", "save")


def test_no_get_route_calls_a_mutating_service_method():
    """Gating writes on the HTTP verb is only correct while no GET mutates.

    If someone adds a GET handler that creates or deletes something in QBO, a
    read-only key would reach it and the whole control is void. This fails at
    that moment rather than at the moment somebody notices.

    TWO THINGS IT DOES NOT SEE, so nobody reads more into a pass than it earned:

    - It inspects ``ast.Attribute`` calls only, so a GET calling a module-level
      mutator by bare name — an imported ``create_*``, or ``run_qbo_write`` —
      would not trigger it.
    - It recognises a GET by the ``@router.get`` decorator, so one registered
      via ``router.api_route(..., methods=["GET"])`` would not be scanned at all.

    Both are unreachable in this tree today and were checked rather than assumed:
    ``api_route`` appears nowhere in app/routers, and a widened scan across all
    85 GET handlers finds one bare-name mutating call, ``auth.py:callback ->
    create_session``, which creates an admin login session rather than anything
    in QuickBooks and is not behind an API key at all. Widening the scan to catch
    it would make this test permanently red on a false positive, which is why it
    is documented instead of broadened.
    """
    routers = pathlib.Path(__file__).resolve().parent.parent / "app" / "routers"
    assert routers.is_dir(), routers

    offenders = []
    scanned_get_handlers = 0
    for path in sorted(routers.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [
                d.func.attr
                for d in node.decorator_list
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            ]
            if "get" not in decorators:
                continue
            scanned_get_handlers += 1
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                    if call.func.attr.startswith(MUTATING_PREFIXES):
                        offenders.append(f"{path.name}:{node.name} -> {call.func.attr}")

    # Guard the guard: a scan that silently matched nothing would pass while
    # proving nothing, which is the failure mode this whole file exists to stop.
    assert scanned_get_handlers > 50, (
        f"only {scanned_get_handlers} GET handlers found — the scan is not "
        "reaching the routers, so its empty result means nothing"
    )
    assert offenders == [], (
        "A GET route now calls a mutating service method, so gating writes on "
        "the HTTP verb no longer protects a read-only key: " + "; ".join(offenders)
    )
