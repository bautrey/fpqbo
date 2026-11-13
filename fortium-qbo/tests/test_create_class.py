"""POST /api/reference/classes creates a QuickBooks tracking class.

Classes go on transaction lines (ClassRef), which bills, journal entries and
vendor credits already pass through. This is the missing half: making the class.
The SDK's save is stubbed; the test checks the object it would send.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.exceptions import QboBadPayload
from app.services import qbo_service as qbo_service_module
from app.services.qbo_service import QBOService


def _service(monkeypatch):
    svc = QBOService.__new__(QBOService)
    svc.db = None
    svc._clients = {}
    monkeypatch.setattr(svc, "_get_company", lambda _cid: SimpleNamespace(realm_id="r1"))
    monkeypatch.setattr(svc, "_get_client", lambda _co: SimpleNamespace())
    captured = {}

    def _save(self, qb=None):
        captured["obj"] = self
        self.Id = "5000000000000123"
        return self

    monkeypatch.setattr(qbo_service_module.TrackingClass, "save", _save, raising=True)
    return svc, captured


def test_create_class_sends_name_and_parent(monkeypatch):
    svc, captured = _service(monkeypatch)
    result = asyncio.run(svc.create_class(1, {
        "Name": "Interim",
        "SubClass": True,
        "ParentRef": {"value": "5000000000000001", "name": "ZRG"},
        "Active": True,
    }))
    cls = captured["obj"]
    assert cls.Name == "Interim"
    assert cls.SubClass is True
    assert cls.ParentRef.value == "5000000000000001"
    assert cls.Active is True
    assert result["Id"] == "5000000000000123"
    sent = cls.to_dict()
    assert sent["Name"] == "Interim"
    assert sent["ParentRef"]["value"] == "5000000000000001"


def test_create_class_top_level_has_no_parent(monkeypatch):
    svc, captured = _service(monkeypatch)
    asyncio.run(svc.create_class(1, {"Name": "ZRG"}))
    cls = captured["obj"]
    assert cls.Name == "ZRG"
    assert cls.SubClass is False
    assert getattr(cls, "ParentRef", None) is None
    assert "ParentRef" not in cls.to_dict()


def test_integer_parent_id_is_sent_as_a_string(monkeypatch):
    svc, captured = _service(monkeypatch)
    asyncio.run(svc.create_class(1, {"Name": "Interim", "ParentRef": {"value": 7}}))
    assert captured["obj"].to_dict()["ParentRef"]["value"] == "7"


def test_parent_without_subclass_is_sent_as_a_subclass(monkeypatch):
    # The SDK defaults SubClass to False; a ParentRef with SubClass false is
    # not a sub-class in QBO, so naming a parent has to imply SubClass.
    svc, captured = _service(monkeypatch)
    asyncio.run(svc.create_class(1, {"Name": "Interim", "ParentRef": {"value": "7"}}))
    sent = captured["obj"].to_dict()
    assert sent["SubClass"] is True
    assert sent["ParentRef"]["value"] == "7"


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"Name": "X", "SubClasss": True}, "SubClasss"),
        ({"Name": ""}, "Name"),
        ({"Name": "   "}, "Name"),
        ({}, "Name"),
        ({"Name": 5}, "Name"),
        ({"Name": "X", "Active": "false"}, "Active"),
        ({"Name": "X", "SubClass": "true", "ParentRef": {"value": "7"}}, "SubClass"),
        ({"Name": "X", "ParentRef": "7"}, "ParentRef"),
        ({"Name": "X", "ParentRef": {"name": "ZRG"}}, "ParentRef"),
        ({"Name": "X", "ParentRef": {"value": ["7"]}}, "ParentRef"),
        ({"Name": "X", "ParentRef": {"value": True}}, "ParentRef"),
        ({"Name": "X", "ParentRef": {"value": {"id": "7"}}}, "ParentRef"),
        ({"Name": "X", "ParentRef": {"value": "  "}}, "ParentRef"),
        ({"Name": "X", "ParentRef": {"value": 7.5}}, "ParentRef"),
        ({"Name": "X", "SubClass": True}, "ParentRef"),
        ({"Name": "X", "SubClass": False, "ParentRef": {"value": "7"}}, "SubClass"),
    ],
)
def test_bad_class_body_is_refused_before_quickbooks(monkeypatch, body, fragment):
    svc, captured = _service(monkeypatch)
    with pytest.raises(QboBadPayload) as err:
        asyncio.run(svc.create_class(1, body))
    assert err.value.status_code == 400
    assert fragment in err.value.detail
    assert "obj" not in captured


def _client(fake_service):
    from fastapi import FastAPI

    from app.dependencies import verify_api_key
    from app.routers import reference

    app = FastAPI()
    app.include_router(reference.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[reference._get_service] = lambda: fake_service
    return app, TestClient(app, raise_server_exceptions=False)


def test_post_classes_returns_201_with_created_class():
    seen = {}

    async def _create(company_id, data):
        seen["company_id"] = company_id
        seen["data"] = data
        return {"Id": "5000000000000123", "Name": data["Name"]}

    app, client = _client(SimpleNamespace(create_class=_create))
    try:
        resp = client.post("/reference/classes?company_id=5", json={"Name": "ZRG"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert resp.json()["Id"] == "5000000000000123"
    assert seen == {"company_id": 5, "data": {"Name": "ZRG"}}


def test_post_classes_bad_body_is_400_not_500(monkeypatch):
    svc, _captured = _service(monkeypatch)
    app, client = _client(svc)
    try:
        resp = client.post("/reference/classes?company_id=5", json={"Name": "X", "ParentRef": "7"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "ParentRef" in resp.json()["detail"]


def test_reference_router_post_requires_api_key():
    from app.dependencies import verify_api_key
    from app.routers import reference

    assert verify_api_key in [d.dependency for d in reference.router.dependencies]


def test_reference_router_has_post_classes_route():
    from app.routers import reference

    routes = {(frozenset(r.methods), r.path) for r in reference.router.routes if hasattr(r, "methods")}
    assert (frozenset({"POST"}), "/reference/classes") in routes
