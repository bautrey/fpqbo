"""POST /api/reference/classes creates a QuickBooks tracking class.

Classes go on transaction lines (ClassRef), which bills, journal entries and
vendor credits already pass through. This is the missing half: making the class.
The SDK's save is stubbed; the test checks the object it would send.
"""

import asyncio
from types import SimpleNamespace

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


def test_reference_router_has_post_classes_route():
    from app.routers import reference

    routes = {(frozenset(r.methods), r.path) for r in reference.router.routes if hasattr(r, "methods")}
    assert (frozenset({"POST"}), "/reference/classes") in routes
