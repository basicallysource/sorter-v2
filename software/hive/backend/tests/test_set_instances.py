"""Set instances: service, router and the machine sync routing."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.routers.profiles as profiles_router
import app.routers.set_instances as set_instances_router
from app.errors import APIError
from app.models.machine_set_progress import MachineSetProgress
from app.models.set_instance import SetInstance, SetInstanceProgress
from app.models.user import User
from app.services import set_instances as service
from app.services.machine_set_progress import instance_bound_sets
from tests.conftest import _auth_headers, _login_user, _register_user
from tests.test_profiles import _DummyCatalogService, _create_profile, _create_version, _set_rule

# BrickLink-keyed parts, as ProfileCatalogService.set_inventory_parts returns them.
SHUTTLE = {
    "set_num": "10283-1",
    "name": "Space Shuttle Discovery",
    "year": 2021,
    "num_parts": 3,
    "set_img_url": "https://img/10283.jpg",
    "parts": [
        {"part_num": "3001", "color_id": 1, "quantity": 2, "is_spare": False, "part_name": "Brick 2 x 4", "color_name": "White", "img_url": None},
        {"part_num": "3002", "color_id": 11, "quantity": 1, "is_spare": False, "part_name": "Brick 2 x 3", "color_name": "Black", "img_url": None},
        {"part_num": "3005", "color_id": 5, "quantity": 1, "is_spare": True, "part_name": "Brick 1 x 1", "color_name": "Red", "img_url": None},
    ],
}


class _DummySetCatalog:
    rebrickable_configured = True

    def __init__(self, sets: dict[str, dict]) -> None:
        self._sets = sets

    def cached_set(self, set_num: str) -> dict | None:
        entry = self._sets.get(set_num)
        return None if entry is None else {k: v for k, v in entry.items() if k != "parts"}

    def set_inventory_parts(self, set_num: str, *, include_spares: bool) -> tuple[dict, list[dict]]:
        entry = self._sets.get(set_num)
        if entry is None:
            raise requests.HTTPError(response=SimpleNamespace(status_code=404))
        parts = [p for p in entry["parts"] if include_spares or not p["is_spare"]]
        return self.cached_set(set_num), parts


class _UnconfiguredCatalog(_DummySetCatalog):
    """No REBRICKABLE_API_KEY: the fetch is a silent no-op and the set stays unknown."""

    rebrickable_configured = False

    def set_inventory_parts(self, set_num: str, *, include_spares: bool) -> tuple[dict, list[dict]]:
        return {}, []


@pytest.fixture()
def set_catalog(monkeypatch: pytest.MonkeyPatch) -> _DummySetCatalog:
    catalog = _DummySetCatalog({"10283-1": SHUTTLE})
    monkeypatch.setattr(set_instances_router, "get_profile_catalog_service", lambda: catalog)
    return catalog


def _create_instance(client: TestClient, auth_headers: dict[str, str], **overrides: object) -> dict:
    response = client.post("/api/set-instances", json={"set_num": "10283-1", **overrides}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestService:
    def test_create_expands_inventory_and_sums_duplicate_keys(self, db: Session, test_user: dict, set_catalog: _DummySetCatalog) -> None:
        user = db.query(User).filter(User.email == test_user["email"]).one()
        # Two Rebrickable rows that resolve to the same BrickLink part/colour become one row.
        set_catalog._sets["10283-1"] = {**SHUTTLE, "parts": SHUTTLE["parts"] + [{**SHUTTLE["parts"][0], "quantity": 3}]}
        instance = service.create_instance(db, user, set_catalog, set_num="10283-1", label=None, include_spares=False, notes="  ")
        assert instance.label == "Space Shuttle Discovery"
        assert instance.notes is None
        assert {(r.part_num, r.color_id): r.quantity_needed for r in instance.progress} == {("3001", 1): 5, ("3002", 11): 1}

    def test_create_unknown_set_is_404(self, db: Session, test_user: dict, set_catalog: _DummySetCatalog) -> None:
        user = db.query(User).filter(User.email == test_user["email"]).one()
        with pytest.raises(APIError) as excinfo:
            service.create_instance(db, user, set_catalog, set_num="0000-1", label=None, include_spares=False, notes=None)
        assert excinfo.value.status_code == 404

    def test_missing_rebrickable_key_is_not_disguised_as_404(self, db: Session, test_user: dict) -> None:
        user = db.query(User).filter(User.email == test_user["email"]).one()
        with pytest.raises(APIError) as excinfo:
            service.create_instance(db, user, _UnconfiguredCatalog({}), set_num="10283-1", label=None, include_spares=False, notes=None)
        assert excinfo.value.status_code == 503
        assert excinfo.value.error_code == "REBRICKABLE_NOT_CONFIGURED"

    def test_manual_adjust_clamps_and_flips_status(self, db: Session, test_user: dict, set_catalog: _DummySetCatalog) -> None:
        user = db.query(User).filter(User.email == test_user["email"]).one()
        instance = service.create_instance(db, user, set_catalog, set_num="10283-1", label="Kiste", include_spares=False, notes=None)
        row = service.set_part_found(db, instance, part_num="3001", color_id=1, quantity_found=99)
        assert row.quantity_found == 2
        assert instance.status == "open"
        service.set_part_found(db, instance, part_num="3002", color_id=11, quantity_found=1)
        assert instance.status == "complete"
        service.set_part_found(db, instance, part_num="3002", color_id=11, quantity_found=0)
        assert instance.status == "open"
        with pytest.raises(APIError):
            service.set_part_found(db, instance, part_num="9999", color_id=1, quantity_found=1)

    def test_wanted_list_xml_lists_only_missing(self) -> None:
        parts = [
            {"part_num": "3001", "color_id": 1, "quantity_missing": 2},
            {"part_num": "3002", "color_id": 11, "quantity_missing": 0},
        ]
        root = ET.fromstring(service.wanted_list_xml(service.missing_parts(parts)))
        items = root.findall("ITEM")
        assert root.tag == "INVENTORY"
        assert [(i.findtext("ITEMTYPE"), i.findtext("ITEMID"), i.findtext("COLOR"), i.findtext("MINQTY")) for i in items] == [("P", "3001", "1", "2")]


class TestRouter:
    def test_crud_flow(self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog) -> None:
        created = _create_instance(client, auth_headers, label="Shuttle, Kiste Keller", include_spares=True)
        assert created["label"] == "Shuttle, Kiste Keller"
        assert created["set_meta"]["name"] == "Space Shuttle Discovery"
        assert created["part_count"] == 3  # spares included
        assert created["total_needed"] == 4
        assert created["pct"] == 0.0

        listed = client.get("/api/set-instances").json()
        assert [i["id"] for i in listed] == [created["id"]]

        patched = client.patch(f"/api/set-instances/{created['id']}", json={"label": "Shuttle", "notes": "shelf 2"}, headers=auth_headers)
        assert patched.status_code == 200, patched.text
        assert patched.json()["label"] == "Shuttle"
        assert patched.json()["notes"] == "shelf 2"

        adjusted = client.put(f"/api/set-instances/{created['id']}/parts/3001/1", json={"quantity_found": 1}, headers=auth_headers)
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.json()["quantity_found"] == 1
        assert adjusted.json()["quantity_missing"] == 1
        assert adjusted.json()["part_name"] == "Brick 2 x 4"

        missing = client.get(f"/api/set-instances/{created['id']}/missing").json()
        assert [(m["part_num"], m["quantity_missing"]) for m in missing] == [("3001", 1), ("3002", 1), ("3005", 1)]

        xml = client.get(f"/api/set-instances/{created['id']}/wanted-list.xml")
        assert xml.status_code == 200
        assert xml.headers["content-type"].startswith("application/xml")
        assert 'filename="wanted-10283-1.xml"' in xml.headers["content-disposition"]
        assert len(ET.fromstring(xml.text).findall("ITEM")) == 3

        archived = client.post(f"/api/set-instances/{created['id']}/archive", headers=auth_headers)
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"
        assert client.get("/api/set-instances").json() == []
        listed = client.get("/api/set-instances?include_archived=true").json()
        # Totals come from the SQL aggregate, not from loaded rows.
        assert [(i["status"], i["part_count"], i["total_needed"], i["total_found"], i["pct"]) for i in listed] == [("archived", 3, 4, 1, 25.0)]
        assert listed[0]["progress_updated_at"] is not None

        # Status is not client-settable: PATCH ignores it; restoring goes back to what the counts say.
        patched = client.patch(f"/api/set-instances/{created['id']}", json={"status": "open"}, headers=auth_headers)
        assert patched.json()["status"] == "archived"
        restored = client.delete(f"/api/set-instances/{created['id']}/archive", headers=auth_headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "open"
        assert len(client.get("/api/set-instances").json()) == 1

    def test_instances_are_owner_gated(self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog) -> None:
        created = _create_instance(client, auth_headers)
        _register_user(client, "other@test.com", "password123", "Other")
        _login_user(client, "other@test.com", "password123")
        other_headers = _auth_headers(client)
        assert client.get("/api/set-instances").json() == []
        assert client.get(f"/api/set-instances/{created['id']}").status_code == 404
        assert client.patch(f"/api/set-instances/{created['id']}", json={"label": "x"}, headers=other_headers).status_code == 404
        assert client.delete(f"/api/set-instances/{created['id']}/archive", headers=other_headers).status_code == 404
        assert client.get(f"/api/set-instances/{uuid4()}/wanted-list.xml").status_code == 404

    def test_unknown_set_and_empty_label_are_rejected(self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog) -> None:
        response = client.post("/api/set-instances", json={"set_num": "0000-1"}, headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["code"] == "SET_NOT_FOUND"
        created = _create_instance(client, auth_headers)
        response = client.patch(f"/api/set-instances/{created['id']}", json={"label": "   "}, headers=auth_headers)
        assert response.status_code == 400


def _assigned_machine(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    rules: list[dict],
    *,
    profile: dict | None = None,
    name: str = "Sorter",
) -> dict:
    """A machine with an activated set-based profile: {headers, machine, profile, version}."""
    monkeypatch.setattr(
        profiles_router,
        "get_profile_catalog_service",
        lambda: _DummyCatalogService({"10283-1": [("3001", 1, 2), ("3002", 11, 1)], "75192-1": [("3004", 4, 3)]}),
    )
    machine = client.post("/api/machines", json={"name": name, "description": ""}, headers=auth_headers).json()
    machine_headers = {"Authorization": f"Bearer {machine['raw_token']}"}
    profile = profile or _create_profile(client, auth_headers, name="Sets")
    version = _create_version(client, auth_headers, profile["id"], name="Sets", rules=rules)
    assert client.put("/api/machine/profile-assignment", json={"profile_id": profile["id"], "version_id": version["id"]}, headers=machine_headers).status_code == 200
    assert client.post("/api/machine/profile-activation", json={"version_id": version["id"], "artifact_hash": version["compiled_hash"]}, headers=machine_headers).status_code == 200
    return {"headers": machine_headers, "machine": machine, "profile": profile, "version": version}


def _item(set_num: str, part_num: str, color_id: int, found: int, instance_id: str | None = None) -> dict:
    return {"set_num": set_num, "part_num": part_num, "color_id": color_id, "quantity_needed": 0, "quantity_found": found, "set_instance_id": instance_id}


def _report(client: TestClient, assigned: dict, items: list[dict]) -> requests.Response:
    version = assigned["version"]
    return client.post(
        "/api/machine/set-progress",
        json={"version_id": version["id"], "artifact_hash": version["compiled_hash"], "items": items},
        headers=assigned["headers"],
    )


def _found(db: Session, instance_id: str) -> dict[tuple[str, int], int]:
    return {(r.part_num, r.color_id): r.quantity_found for r in db.query(SetInstanceProgress).filter(SetInstanceProgress.set_instance_id == UUID(instance_id))}


class TestMachineSync:
    def test_tagged_items_land_on_the_instance_and_untagged_sets_stay_legacy(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = _create_instance(client, auth_headers, label="Shuttle A")
        assigned = _assigned_machine(
            client,
            auth_headers,
            monkeypatch,
            [{**_set_rule("shuttle", "Shuttle", "10283-1"), "set_instance_id": instance["id"]}, _set_rule("falcon", "Falcon", "75192-1")],
        )

        response = _report(
            client,
            assigned,
            [_item("10283-1", "3001", 1, 5, instance["id"]), _item("10283-1", "3002", 11, 1, instance["id"]), _item("75192-1", "3004", 4, 2)],
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True, "updated": 3, "deleted": 0}

        assert _found(db, instance["id"]) == {("3001", 1): 2, ("3002", 11): 1}  # clamped to needed
        legacy = db.query(MachineSetProgress).all()
        assert [(r.set_num, r.part_num, r.quantity_found) for r in legacy] == [("75192-1", "3004", 2)]

        detail = client.get(f"/api/set-instances/{instance['id']}").json()
        assert detail["status"] == "complete"
        assert detail["pct"] == 100.0

        # The machine and profile progress views read the instance for the bound set.
        machine_view = client.get(f"/api/machines/{assigned['machine']['id']}/set-progress", headers=auth_headers).json()
        assert {(p["set_num"], p["part_num"]): p["quantity_found"] for p in machine_view["progress"]} == {
            ("10283-1", "3001"): 2,
            ("10283-1", "3002"): 1,
            ("75192-1", "3004"): 2,
        }
        profile_view = client.get(f"/api/profiles/{assigned['profile']['id']}/set-progress", headers=auth_headers).json()
        assert [(s["set_num"], s["total_found"], s["pct"]) for s in profile_view["machines"][0]["sets"]] == [("10283-1", 3, 100.0), ("75192-1", 2, 66.7)]

    def test_reports_merge_as_per_machine_deltas(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_catalog._sets["10283-1"] = {**SHUTTLE, "parts": [{**SHUTTLE["parts"][0], "quantity": 10}]}
        instance = _create_instance(client, auth_headers)
        rules = [{**_set_rule("shuttle", "Shuttle", "10283-1"), "set_instance_id": instance["id"]}]
        first = _assigned_machine(client, auth_headers, monkeypatch, rules)

        assert _report(client, first, [_item("10283-1", "3001", 1, 3, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 3}

        # A manual adjustment survives the machine re-sending its unchanged count...
        assert client.put(f"/api/set-instances/{instance['id']}/parts/3001/1", json={"quantity_found": 5}, headers=auth_headers).status_code == 200
        assert _report(client, first, [_item("10283-1", "3001", 1, 3, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 5}
        # ...and only the increment since the last report is added on top.
        assert _report(client, first, [_item("10283-1", "3001", 1, 4, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 6}

        # The tracker restarted at zero (profile edit, reset): nothing is lost, new finds add up again.
        assert _report(client, first, [_item("10283-1", "3001", 1, 0, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 6}
        assert _report(client, first, [_item("10283-1", "3001", 1, 2, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 8}

        # A second machine keeps its own cursor and contributes on top of the first one's.
        second = _assigned_machine(client, auth_headers, monkeypatch, rules, profile=first["profile"], name="Sorter 2")
        assert _report(client, second, [_item("10283-1", "3001", 1, 1, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 9}
        assert _report(client, first, [_item("10283-1", "3001", 1, 2, instance["id"])]).status_code == 200
        assert _found(db, instance["id"]) == {("3001", 1): 9}

    def test_untagged_snapshot_must_still_be_complete(
        self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assigned = _assigned_machine(client, auth_headers, monkeypatch, [_set_rule("shuttle", "Shuttle", "10283-1")])
        response = _report(client, assigned, [_item("10283-1", "3001", 1, 1)])
        assert response.status_code == 400
        assert response.json()["code"] == "SET_PROGRESS_SNAPSHOT_INCOMPLETE"

    def test_foreign_or_unknown_instance_and_unknown_part_are_rejected(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assigned = _assigned_machine(client, auth_headers, monkeypatch, [_set_rule("shuttle", "Shuttle", "10283-1")])
        instance = _create_instance(client, auth_headers)
        other = User(email="other@test.com", password_hash="x", display_name="Other")
        db.add(other)
        db.commit()
        foreign = SetInstance(user_id=other.id, set_num="10283-1", label="Theirs")
        db.add(foreign)
        db.commit()

        response = _report(client, assigned, [_item("10283-1", "3001", 1, 1, str(foreign.id))])
        assert response.status_code == 400
        assert response.json()["code"] == "SET_PROGRESS_INSTANCE_UNKNOWN"
        response = _report(client, assigned, [_item("10283-1", "3001", 1, 1, str(uuid4()))])
        assert response.json()["code"] == "SET_PROGRESS_INSTANCE_UNKNOWN"
        response = _report(client, assigned, [_item("10283-1", "9999", 1, 1, instance["id"])])
        assert response.status_code == 400
        assert response.json()["code"] == "SET_PROGRESS_ITEM_UNKNOWN"
        assert db.query(SetInstanceProgress).filter(SetInstanceProgress.quantity_found > 0).count() == 0


def test_instance_bound_sets_walks_the_rule_tree() -> None:
    instance_id = uuid4()
    artifact = {
        "rules": [
            {"id": "group", "rule_type": "filter", "children": [{"id": "shuttle", "rule_type": "set", "set_num": "10283-1", "set_instance_id": str(instance_id)}]},
            {"id": "falcon", "rule_type": "set", "set_num": "75192-1"},
            {"id": "broken", "rule_type": "set", "set_num": "1-1", "set_instance_id": "not-a-uuid"},
        ]
    }
    assert instance_bound_sets(artifact) == {"10283-1": instance_id}
    assert instance_bound_sets(None) == {}
