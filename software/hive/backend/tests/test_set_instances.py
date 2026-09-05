"""Set instances: service, router, machine sync routing and the data migration."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

import pytest
import requests
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.routers.profiles as profiles_router
import app.routers.set_instances as set_instances_router
from app.errors import APIError
from app.models.machine_profile_assignment import MachineProfileAssignment
from app.models.machine_set_progress import MachineSetProgress
from app.models.set_instance import SetInstance, SetInstanceProgress
from app.models.sorting_profile import SortingProfile
from app.models.sorting_profile_version import SortingProfileVersion
from app.models.user import User
from app.services import set_instances as service
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
        assert len(client.get("/api/set-instances?include_archived=true").json()) == 1

    def test_instances_are_owner_gated(self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog) -> None:
        created = _create_instance(client, auth_headers)
        _register_user(client, "other@test.com", "password123", "Other")
        _login_user(client, "other@test.com", "password123")
        other_headers = _auth_headers(client)
        assert client.get("/api/set-instances").json() == []
        assert client.get(f"/api/set-instances/{created['id']}").status_code == 404
        assert client.patch(f"/api/set-instances/{created['id']}", json={"label": "x"}, headers=other_headers).status_code == 404
        assert client.get(f"/api/set-instances/{uuid4()}/wanted-list.xml").status_code == 404

    def test_unknown_set_and_empty_label_are_rejected(self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog) -> None:
        response = client.post("/api/set-instances", json={"set_num": "0000-1"}, headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["code"] == "SET_NOT_FOUND"
        created = _create_instance(client, auth_headers)
        response = client.patch(f"/api/set-instances/{created['id']}", json={"label": "   "}, headers=auth_headers)
        assert response.status_code == 400


def _assigned_machine(client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, rules: list[dict]) -> tuple[dict, dict]:
    """A machine with an activated set-based profile; returns (machine headers, version)."""
    monkeypatch.setattr(
        profiles_router,
        "get_profile_catalog_service",
        lambda: _DummyCatalogService({"10283-1": [("3001", 1, 2), ("3002", 11, 1)], "75192-1": [("3004", 4, 3)]}),
    )
    machine = client.post("/api/machines", json={"name": "Sorter", "description": ""}, headers=auth_headers).json()
    machine_headers = {"Authorization": f"Bearer {machine['raw_token']}"}
    profile = _create_profile(client, auth_headers, name="Sets")
    version = _create_version(client, auth_headers, profile["id"], name="Sets", rules=rules)
    assert client.put("/api/machine/profile-assignment", json={"profile_id": profile["id"], "version_id": version["id"]}, headers=machine_headers).status_code == 200
    assert client.post("/api/machine/profile-activation", json={"version_id": version["id"], "artifact_hash": version["compiled_hash"]}, headers=machine_headers).status_code == 200
    return machine_headers, version


def _item(set_num: str, part_num: str, color_id: int, found: int, instance_id: str | None = None) -> dict:
    return {"set_num": set_num, "part_num": part_num, "color_id": color_id, "quantity_needed": 0, "quantity_found": found, "set_instance_id": instance_id}


class TestMachineSync:
    def test_tagged_items_land_on_the_instance_and_untagged_sets_stay_legacy(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        machine_headers, version = _assigned_machine(
            client, auth_headers, monkeypatch, [_set_rule("shuttle", "Shuttle", "10283-1"), _set_rule("falcon", "Falcon", "75192-1")]
        )
        instance = _create_instance(client, auth_headers, label="Shuttle A")

        response = client.post(
            "/api/machine/set-progress",
            json={
                "version_id": version["id"],
                "artifact_hash": version["compiled_hash"],
                "items": [
                    _item("10283-1", "3001", 1, 5, instance["id"]),
                    _item("10283-1", "3002", 11, 1, instance["id"]),
                    _item("75192-1", "3004", 4, 2),
                ],
            },
            headers=machine_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True, "updated": 3, "deleted": 0}

        rows = {(r.part_num, r.color_id): r.quantity_found for r in db.query(SetInstanceProgress).filter(SetInstanceProgress.set_instance_id == UUID(instance["id"]))}
        assert rows == {("3001", 1): 2, ("3002", 11): 1}  # clamped to needed
        legacy = db.query(MachineSetProgress).all()
        assert [(r.set_num, r.part_num, r.quantity_found) for r in legacy] == [("75192-1", "3004", 2)]

        detail = client.get(f"/api/set-instances/{instance['id']}").json()
        assert detail["status"] == "complete"
        assert detail["pct"] == 100.0

    def test_untagged_snapshot_must_still_be_complete(
        self, client: TestClient, auth_headers: dict[str, str], set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        machine_headers, version = _assigned_machine(client, auth_headers, monkeypatch, [_set_rule("shuttle", "Shuttle", "10283-1")])
        response = client.post(
            "/api/machine/set-progress",
            json={"version_id": version["id"], "artifact_hash": version["compiled_hash"], "items": [_item("10283-1", "3001", 1, 1)]},
            headers=machine_headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "SET_PROGRESS_SNAPSHOT_INCOMPLETE"

    def test_foreign_or_unknown_instance_and_unknown_part_are_rejected(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, set_catalog: _DummySetCatalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        machine_headers, version = _assigned_machine(client, auth_headers, monkeypatch, [_set_rule("shuttle", "Shuttle", "10283-1")])
        instance = _create_instance(client, auth_headers)
        other = User(email="other@test.com", password_hash="x", display_name="Other")
        db.add(other)
        db.commit()
        foreign = SetInstance(user_id=other.id, set_num="10283-1", label="Theirs")
        db.add(foreign)
        db.commit()

        def report(items: list[dict]) -> requests.Response:
            return client.post(
                "/api/machine/set-progress",
                json={"version_id": version["id"], "artifact_hash": version["compiled_hash"], "items": items},
                headers=machine_headers,
            )

        response = report([_item("10283-1", "3001", 1, 1, str(foreign.id))])
        assert response.status_code == 400
        assert response.json()["code"] == "SET_PROGRESS_INSTANCE_UNKNOWN"
        response = report([_item("10283-1", "3001", 1, 1, str(uuid4()))])
        assert response.json()["code"] == "SET_PROGRESS_INSTANCE_UNKNOWN"
        response = report([_item("10283-1", "9999", 1, 1, instance["id"])])
        assert response.status_code == 400
        assert response.json()["code"] == "SET_PROGRESS_ITEM_UNKNOWN"
        assert db.query(SetInstanceProgress).filter(SetInstanceProgress.quantity_found > 0).count() == 0


def _load_migration():
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "f0e1d2c3b4a5_set_instances.py"
    spec = importlib.util.spec_from_file_location("migration_set_instances", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestDataMigration:
    def test_assignment_rows_move_to_the_instance_named_by_the_rule(self, db: Session, test_user: dict, test_machine: dict) -> None:
        migration = _load_migration()
        user = db.query(User).filter(User.email == test_user["email"]).one()
        instance = SetInstance(user_id=user.id, set_num="10283-1", label="Shuttle")
        db.add(instance)
        db.flush()
        db.add(SetInstanceProgress(set_instance_id=instance.id, part_num="3001", color_id=1, quantity_needed=2, quantity_found=0))
        profile = SortingProfile(owner_id=user.id, name="Sets")
        db.add(profile)
        db.flush()
        rules = [
            {"id": "shuttle", "rule_type": "set", "set_num": "10283-1", "set_instance_id": str(instance.id), "children": []},
            {"id": "group", "rule_type": "filter", "children": [{"id": "falcon", "rule_type": "set", "set_num": "75192-1"}]},
        ]
        version = SortingProfileVersion(profile_id=profile.id, version_number=1, name="Sets", rules_json=rules, fallback_mode_json={}, compiled_artifact_json={}, compiled_hash="h")
        db.add(version)
        db.flush()
        assignment = MachineProfileAssignment(machine_id=UUID(test_machine["id"]), profile_id=profile.id, active_version_id=version.id)
        db.add(assignment)
        db.flush()
        now = datetime.now(timezone.utc)
        for set_num, part_num, color_id, found in [("10283-1", "3001", 1, 2), ("10283-1", "3002", 11, 1), ("75192-1", "3004", 4, 3)]:
            db.add(MachineSetProgress(machine_id=assignment.machine_id, assignment_id=assignment.id, set_num=set_num, part_num=part_num, color_id=color_id, quantity_needed=3, quantity_found=found, updated_at=now))
        db.commit()

        assert migration._instance_bound_sets(rules) == {"10283-1": str(instance.id)}

        connection = db.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration._migrate_assignment_progress()
        db.commit()

        moved = {(r.part_num, r.color_id): (r.quantity_needed, r.quantity_found) for r in db.query(SetInstanceProgress).filter(SetInstanceProgress.set_instance_id == instance.id)}
        assert moved == {("3001", 1): (3, 2), ("3002", 11): (3, 1)}
        assert [(r.set_num, r.part_num) for r in db.query(MachineSetProgress).all()] == [("75192-1", "3004")]
