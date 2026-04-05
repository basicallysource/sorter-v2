"""Tests for sorting profile authoring, community, and machine flows."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import app.routers.profiles as profiles_router
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.machine_profile_assignment import MachineProfileAssignment
from app.models.machine_set_progress import MachineSetProgress
from app.models.sorting_profile_ai_message import SortingProfileAiMessage
from app.models.user import User
from app.services.profile_ai import AiProposalResult
from tests.conftest import _auth_headers, _login_user, _register_user


def _sample_rule(rule_id: str, name: str, field: str = "part_num", op: str = "contains", value: str = "300") -> dict:
    return {
        "id": rule_id,
        "name": name,
        "match_mode": "all",
        "conditions": [
            {
                "id": f"{rule_id}-cond",
                "field": field,
                "op": op,
                "value": value,
            }
        ],
        "children": [],
        "disabled": False,
    }


def _set_rule(rule_id: str, name: str, set_num: str) -> dict:
    return {
        "id": rule_id,
        "rule_type": "set",
        "name": name,
        "match_mode": "all",
        "conditions": [],
        "children": [],
        "disabled": False,
        "set_num": set_num,
        "include_spares": False,
        "set_meta": {"name": name},
    }


class _DummyCatalogService:
    def __init__(self, part_defs_by_set: dict[str, list[tuple[str, int, int]]]) -> None:
        self._part_defs_by_set = part_defs_by_set

    def compile_document(self, document: dict[str, object]) -> dict[str, object]:
        rules = document.get("rules") if isinstance(document, dict) else []
        fallback_mode = document.get("fallback_mode") if isinstance(document, dict) else {}
        if not isinstance(rules, list):
            rules = []
        if not isinstance(fallback_mode, dict):
            fallback_mode = {}

        categories: dict[str, dict[str, str]] = {}
        part_to_category: dict[str, str] = {}
        set_inventories: dict[str, dict[str, object]] = {}

        for raw_rule in rules:
            if not isinstance(raw_rule, dict):
                continue
            rule_id = str(raw_rule.get("id") or "")
            if not rule_id:
                continue
            rule_name = str(raw_rule.get("name") or rule_id)
            categories[rule_id] = {"name": rule_name}
            if raw_rule.get("rule_type") != "set":
                continue

            set_num = str(raw_rule.get("set_num") or f"custom:{rule_id}")
            if raw_rule.get("set_source") == "custom" or raw_rule.get("custom_parts"):
                raw_custom_parts = raw_rule.get("custom_parts")
                if not isinstance(raw_custom_parts, list):
                    raw_custom_parts = []
                parts = [
                    {
                        "part_num": str(part.get("part_num") or ""),
                        "color_id": int(part.get("color_id") if part.get("color_id") is not None else -1),
                        "quantity": int(part.get("quantity") or 0),
                        "part_name": part.get("part_name"),
                        "color_name": part.get("color_name"),
                    }
                    for part in raw_custom_parts
                    if isinstance(part, dict) and part.get("part_num")
                ]
            else:
                if not set_num:
                    continue
                part_defs = self._part_defs_by_set.get(set_num, [])
                parts = [
                    {"part_num": part_num, "color_id": color_id, "quantity": quantity}
                    for part_num, color_id, quantity in part_defs
                ]
            set_inventories[rule_id] = {
                "rule_id": rule_id,
                "set_num": set_num,
                "name": str(raw_rule.get("name") or set_num),
                "set_source": raw_rule.get("set_source") or ("custom" if raw_rule.get("custom_parts") else "rebrickable"),
                "parts": parts,
            }
            for part in parts:
                color_key = "any_color" if int(part["color_id"]) == -1 else str(part["color_id"])
                key = f"{color_key}-{part['part_num']}"
                part_to_category.setdefault(key, rule_id)

        artifact: dict[str, object] = {
            "schema_version": 1,
            "id": str(document.get("id") or ""),
            "name": str(document.get("name") or "Test Profile"),
            "description": document.get("description"),
            "profile_type": "set" if set_inventories else "rule",
            "default_category_id": str(document.get("default_category_id") or "misc"),
            "fallback_mode": fallback_mode,
            "rules": rules,
            "categories": categories,
            "part_to_category": part_to_category,
            "stats": {
                "total_parts": len(part_to_category),
                "matched": len(part_to_category),
                "unmatched": 0,
                "per_category": {},
            },
        }
        if set_inventories:
            artifact["set_inventories"] = set_inventories

        artifact_hash = hashlib.sha256(json.dumps(artifact, sort_keys=True, default=str).encode()).hexdigest()
        artifact["artifact_hash"] = artifact_hash
        return {
            "artifact": artifact,
            "artifact_hash": artifact_hash,
            "stats": artifact["stats"],
            "compiled_part_count": len(part_to_category),
            "coverage_ratio": 1.0 if part_to_category else None,
        }


def _create_profile(client: TestClient, auth_headers: dict[str, str], **overrides: object) -> dict:
    payload = {
        "name": "Starter Profile",
        "description": "A profile for tests",
        "visibility": "private",
        "tags": ["starter"],
        **overrides,
    }
    response = client.post("/api/profiles", json=payload, headers=auth_headers)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_version(
    client: TestClient,
    auth_headers: dict[str, str],
    profile_id: str,
    *,
    name: str,
    version_label: str | None = None,
    change_note: str | None = None,
    publish: bool = False,
    rules: list[dict] | None = None,
) -> dict:
    response = client.post(
        f"/api/profiles/{profile_id}/versions",
        json={
            "name": name,
            "description": "Version description",
            "default_category_id": "misc",
            "rules": rules or [_sample_rule("bricks", "Bricks")],
            "fallback_mode": {
                "rebrickable_categories": False,
                "bricklink_categories": False,
                "by_color": False,
            },
            "change_note": change_note,
            "label": version_label,
            "publish": publish,
        },
        headers=auth_headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


class TestProfileSettings:
    def test_update_profile_ai_settings_encrypts_key(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, test_user: dict
    ) -> None:
        response = client.patch(
            "/api/auth/me",
            json={
                "openrouter_api_key": "or-test-key",
                "preferred_ai_model": "anthropic/claude-sonnet-4.6",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["openrouter_configured"] is True
        assert data["preferred_ai_model"] == "anthropic/claude-sonnet-4.6"

        user = db.query(User).filter(User.email == "member@test.com").first()
        assert user is not None
        assert user.openrouter_api_key_encrypted
        assert user.openrouter_api_key_encrypted != "or-test-key"
        assert user.preferred_ai_model == "anthropic/claude-sonnet-4.6"

        clear_response = client.patch(
            "/api/auth/me",
            json={"clear_openrouter_api_key": True},
            headers=auth_headers,
        )
        assert clear_response.status_code == 200, clear_response.text
        assert clear_response.json()["openrouter_configured"] is False

    def test_create_version_accepts_custom_set_rules(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: object
    ) -> None:
        monkeypatch.setattr(
            profiles_router,
            "get_profile_catalog_service",
            lambda: _DummyCatalogService({}),
        )

        profile = _create_profile(client, auth_headers, name="Custom Orders")
        version = _create_version(
            client,
            auth_headers,
            profile["id"],
            name="Custom Orders",
            rules=[
                {
                    "id": "custom-order",
                    "rule_type": "set",
                    "set_source": "custom",
                    "name": "Customer Order",
                    "set_num": "custom:order-1",
                    "include_spares": False,
                    "set_meta": {"name": "Customer Order", "year": None, "num_parts": 30, "img_url": None},
                    "custom_parts": [
                        {
                            "part_num": "2780",
                            "part_name": "Pin",
                            "color_id": -1,
                            "color_name": "Any color",
                            "quantity": 20,
                        },
                        {
                            "part_num": "32054",
                            "part_name": "Axle",
                            "color_id": 5,
                            "color_name": "Red",
                            "quantity": 10,
                        },
                    ],
                    "match_mode": "all",
                    "conditions": [],
                    "children": [],
                    "disabled": False,
                }
            ],
        )

        assert version["rules_summary"][0]["set_source"] == "custom"

        detail_response = client.get(f"/api/profiles/{profile['id']}", headers=auth_headers)
        assert detail_response.status_code == 200, detail_response.text
        current_rule = detail_response.json()["current_version"]["rules"][0]
        assert current_rule["set_source"] == "custom"
        assert current_rule["custom_parts"][0]["part_num"] == "2780"


class TestPublicProfiles:
    def test_discover_and_detail_hide_unpublished_versions(
        self, client: TestClient, auth_headers: dict[str, str], test_user: dict
    ) -> None:
        profile = _create_profile(client, auth_headers, visibility="public")
        profile_id = profile["id"]

        published_version = _create_version(
            client,
            auth_headers,
            profile_id,
            name="Starter Profile",
            version_label="stable",
            change_note="First public version",
            publish=True,
        )
        _create_version(
            client,
            auth_headers,
            profile_id,
            name="Starter Profile",
            version_label="draft-next",
            change_note="Draft follow-up",
            publish=False,
            rules=[_sample_rule("plates", "Plates", value="302")],
        )

        logout_response = client.post("/api/auth/logout", headers=_auth_headers(client))
        assert logout_response.status_code == 200

        _register_user(client, "viewer@test.com", "Password123!", "Viewer")
        _login_user(client, "viewer@test.com", "Password123!")

        discover_response = client.get("/api/profiles?scope=discover")
        assert discover_response.status_code == 200, discover_response.text
        discover_items = discover_response.json()
        discovered = next(item for item in discover_items if item["id"] == profile_id)
        assert discovered["latest_version_number"] == 3
        assert discovered["latest_published_version_number"] == 2
        assert discovered["latest_version"]["version_number"] == published_version["version_number"]
        assert discovered["latest_published_version"]["version_number"] == published_version["version_number"]

        detail_response = client.get(f"/api/profiles/{profile_id}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["current_version"]["version_number"] == published_version["version_number"]
        assert len(detail["versions"]) == 1
        assert detail["versions"][0]["version_number"] == published_version["version_number"]


class TestCommunityAndMachineFlows:
    def test_library_fork_assignment_and_machine_token_endpoints(
        self, client: TestClient, auth_headers: dict[str, str], test_user: dict
    ) -> None:
        owner_profile = _create_profile(client, auth_headers, visibility="public", name="Community Profile")
        profile_id = owner_profile["id"]
        published_version = _create_version(
            client,
            auth_headers,
            profile_id,
            name="Community Profile",
            version_label="stable",
            change_note="Published for the community",
            publish=True,
        )

        logout_response = client.post("/api/auth/logout", headers=_auth_headers(client))
        assert logout_response.status_code == 200

        _register_user(client, "collector@test.com", "Password123!", "Collector")
        _login_user(client, "collector@test.com", "Password123!")
        collector_headers = _auth_headers(client)

        machine_response = client.post(
            "/api/machines",
            json={"name": "Collector Sorter", "description": "Community test machine"},
            headers=collector_headers,
        )
        assert machine_response.status_code in (200, 201), machine_response.text
        machine = machine_response.json()
        machine_token = machine["raw_token"]

        save_response = client.post(
            f"/api/profiles/{profile_id}/library",
            headers=collector_headers,
        )
        assert save_response.status_code == 200, save_response.text

        fork_response = client.post(
            f"/api/profiles/{profile_id}/fork",
            json={"name": "Community Profile Fork", "add_to_library": True},
            headers=collector_headers,
        )
        assert fork_response.status_code in (200, 201), fork_response.text
        fork = fork_response.json()
        assert fork["is_owner"] is True
        assert fork["source"]["profile_id"] == profile_id

        assignment_response = client.put(
            f"/api/machines/{machine['id']}/profile-assignment",
            json={"profile_id": profile_id, "version_id": published_version["id"]},
            headers=collector_headers,
        )
        assert assignment_response.status_code == 200, assignment_response.text
        assignment = assignment_response.json()
        assert assignment["desired_version"]["id"] == published_version["id"]
        assert assignment["profile"]["id"] == profile_id

        owned_assignment_response = client.get(
            f"/api/machines/{machine['id']}/profile-assignment",
            headers=collector_headers,
        )
        assert owned_assignment_response.status_code == 200
        assert owned_assignment_response.json()["desired_version"]["version_number"] == published_version["version_number"]

        machine_headers = {"Authorization": f"Bearer {machine_token}"}

        machine_library_response = client.get("/api/machine/profiles/library", headers=machine_headers)
        assert machine_library_response.status_code == 200, machine_library_response.text
        machine_library = machine_library_response.json()
        assert machine_library["assignment"]["desired_version"]["id"] == published_version["id"]
        assert any(item["id"] == profile_id for item in machine_library["profiles"])

        machine_detail_response = client.get(
            f"/api/machine/profiles/{profile_id}",
            headers=machine_headers,
        )
        assert machine_detail_response.status_code == 200, machine_detail_response.text
        machine_detail = machine_detail_response.json()
        assert machine_detail["current_version"]["version_number"] == published_version["version_number"]
        assert len(machine_detail["versions"]) == 1

        artifact_response = client.get(
            f"/api/machine/profiles/versions/{published_version['id']}/artifact",
            headers=machine_headers,
        )
        assert artifact_response.status_code == 200, artifact_response.text
        artifact = artifact_response.json()["artifact"]
        assert artifact["default_category_id"] == "misc"
        assert artifact["artifact_hash"]

        activation_response = client.post(
            "/api/machine/profile-activation",
            json={
                "version_id": published_version["id"],
                "artifact_hash": artifact["artifact_hash"],
            },
            headers=machine_headers,
        )
        assert activation_response.status_code == 200, activation_response.text
        activated_assignment = activation_response.json()
        assert activated_assignment["active_version"]["version_number"] == published_version["version_number"]
        assert activated_assignment["artifact_hash"] == artifact["artifact_hash"]


class TestSetProgressHardening:
    def test_reassigning_machine_clears_activation_state_and_stale_progress(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, test_user: dict, monkeypatch: object
    ) -> None:
        monkeypatch.setattr(
            profiles_router,
            "get_profile_catalog_service",
            lambda: _DummyCatalogService(
                {
                    "11111-1": [("3001", 5, 2)],
                    "22222-1": [("3002", 7, 1)],
                }
            ),
        )

        machine_response = client.post(
            "/api/machines",
            json={"name": "Set Tracker", "description": "Tracks set progress"},
            headers=auth_headers,
        )
        assert machine_response.status_code in (200, 201), machine_response.text
        machine = machine_response.json()
        machine_headers = {"Authorization": f"Bearer {machine['raw_token']}"}

        profile_a = _create_profile(client, auth_headers, name="Set Profile A")
        version_a = _create_version(
            client,
            auth_headers,
            profile_a["id"],
            name="Set Profile A",
            rules=[_set_rule("set-a", "Set A", "11111-1")],
        )

        profile_b = _create_profile(client, auth_headers, name="Set Profile B")
        version_b = _create_version(
            client,
            auth_headers,
            profile_b["id"],
            name="Set Profile B",
            rules=[_set_rule("set-b", "Set B", "22222-1")],
        )

        assignment_response = client.put(
            f"/api/machines/{machine['id']}/profile-assignment",
            json={"profile_id": profile_a["id"], "version_id": version_a["id"]},
            headers=auth_headers,
        )
        assert assignment_response.status_code == 200, assignment_response.text

        activation_response = client.post(
            "/api/machine/profile-activation",
            json={"version_id": version_a["id"], "artifact_hash": version_a["compiled_hash"]},
            headers=machine_headers,
        )
        assert activation_response.status_code == 200, activation_response.text

        progress_response = client.post(
            "/api/machine/set-progress",
            json={
                "version_id": version_a["id"],
                "artifact_hash": version_a["compiled_hash"],
                "items": [
                    {
                        "set_num": "11111-1",
                        "part_num": "3001",
                        "color_id": 5,
                        "quantity_needed": 999,
                        "quantity_found": 1,
                    }
                ],
            },
            headers=machine_headers,
        )
        assert progress_response.status_code == 200, progress_response.text

        reassign_response = client.put(
            f"/api/machines/{machine['id']}/profile-assignment",
            json={"profile_id": profile_b["id"], "version_id": version_b["id"]},
            headers=auth_headers,
        )
        assert reassign_response.status_code == 200, reassign_response.text
        reassign_data = reassign_response.json()
        assert reassign_data["desired_version"]["id"] == version_b["id"]
        assert reassign_data["active_version"] is None
        assert reassign_data["artifact_hash"] is None
        assert reassign_data["last_synced_at"] is None
        assert reassign_data["last_activated_at"] is None

        assignment = db.query(MachineProfileAssignment).filter(
            MachineProfileAssignment.machine_id == UUID(machine["id"])
        ).first()
        assert assignment is not None
        assert assignment.active_version_id is None
        assert assignment.artifact_hash is None
        assert assignment.last_synced_at is None
        assert assignment.last_activated_at is None
        assert db.query(MachineSetProgress).filter(MachineSetProgress.assignment_id == assignment.id).count() == 0

        profile_progress_response = client.get(
            f"/api/profiles/{profile_b['id']}/set-progress",
            headers=auth_headers,
        )
        assert profile_progress_response.status_code == 200, profile_progress_response.text
        machines = profile_progress_response.json()["machines"]
        assert len(machines) == 1
        assert machines[0]["overall_found"] == 0
        assert [item["set_num"] for item in machines[0]["sets"]] == ["22222-1"]

    def test_set_progress_requires_full_snapshot_for_assigned_artifact(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, test_user: dict, monkeypatch: object
    ) -> None:
        monkeypatch.setattr(
            profiles_router,
            "get_profile_catalog_service",
            lambda: _DummyCatalogService(
                {
                    "33333-1": [("3001", 5, 2), ("3002", 7, 1)],
                }
            ),
        )

        machine_response = client.post(
            "/api/machines",
            json={"name": "Strict Tracker", "description": "Validates snapshots"},
            headers=auth_headers,
        )
        assert machine_response.status_code in (200, 201), machine_response.text
        machine = machine_response.json()
        machine_headers = {"Authorization": f"Bearer {machine['raw_token']}"}

        profile = _create_profile(client, auth_headers, name="Strict Set Profile")
        version = _create_version(
            client,
            auth_headers,
            profile["id"],
            name="Strict Set Profile",
            rules=[_set_rule("set-strict", "Strict Set", "33333-1")],
        )

        assignment_response = client.put(
            f"/api/machines/{machine['id']}/profile-assignment",
            json={"profile_id": profile["id"], "version_id": version["id"]},
            headers=auth_headers,
        )
        assert assignment_response.status_code == 200, assignment_response.text

        incomplete_response = client.post(
            "/api/machine/set-progress",
            json={
                "version_id": version["id"],
                "artifact_hash": version["compiled_hash"],
                "items": [
                    {
                        "set_num": "33333-1",
                        "part_num": "3001",
                        "color_id": 5,
                        "quantity_needed": 2,
                        "quantity_found": 1,
                    }
                ],
            },
            headers=machine_headers,
        )
        assert incomplete_response.status_code == 400, incomplete_response.text
        assert incomplete_response.json()["code"] == "SET_PROGRESS_SNAPSHOT_INCOMPLETE"

        unknown_item_response = client.post(
            "/api/machine/set-progress",
            json={
                "version_id": version["id"],
                "artifact_hash": version["compiled_hash"],
                "items": [
                    {
                        "set_num": "33333-1",
                        "part_num": "3001",
                        "color_id": 5,
                        "quantity_needed": 2,
                        "quantity_found": 1,
                    },
                    {
                        "set_num": "33333-1",
                        "part_num": "9999",
                        "color_id": 5,
                        "quantity_needed": 1,
                        "quantity_found": 1,
                    },
                ],
            },
            headers=machine_headers,
        )
        assert unknown_item_response.status_code == 400, unknown_item_response.text
        assert unknown_item_response.json()["code"] == "SET_PROGRESS_ITEM_UNKNOWN"

        valid_response = client.post(
            "/api/machine/set-progress",
            json={
                "version_id": version["id"],
                "artifact_hash": version["compiled_hash"],
                "items": [
                    {
                        "set_num": "33333-1",
                        "part_num": "3001",
                        "color_id": 5,
                        "quantity_needed": 999,
                        "quantity_found": 1,
                    },
                    {
                        "set_num": "33333-1",
                        "part_num": "3002",
                        "color_id": 7,
                        "quantity_needed": 999,
                        "quantity_found": 1,
                    },
                ],
            },
            headers=machine_headers,
        )
        assert valid_response.status_code == 200, valid_response.text
        assert db.query(MachineSetProgress).count() == 2


class TestProfileAi:
    def test_ai_message_includes_previous_conversation_context(
        self, client: TestClient, auth_headers: dict[str, str], test_user: dict, db: Session, monkeypatch: object
    ) -> None:
        profile = _create_profile(client, auth_headers, visibility="private", name="AI Context Profile")
        profile_id = profile["id"]
        version_id = profile["current_version"]["id"]

        user = db.query(User).filter(User.email == "member@test.com").first()
        assert user is not None

        db.add(
            SortingProfileAiMessage(
                profile_id=UUID(profile_id),
                user_id=user.id,
                version_id=UUID(version_id),
                role="user",
                content="What Creator sets were there in 2024?",
            )
        )
        db.add(
            SortingProfileAiMessage(
                profile_id=UUID(profile_id),
                user_id=user.id,
                version_id=UUID(version_id),
                role="assistant",
                content="In 2024 there were 20 Creator sets. I showed the full list.",
            )
        )
        db.commit()

        captured: dict[str, object] = {}

        def fake_generate(**kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(
                content="I can add those sets.",
                model="anthropic/claude-sonnet-4.6",
                usage=None,
                tool_trace=[],
                proposal=None,
            )

        monkeypatch.setattr(profiles_router, "generate_profile_ai_proposal", fake_generate)

        ai_response = client.post(
            f"/api/profiles/{profile_id}/ai/messages",
            json={
                "message": "Then let's add those too.",
                "version_id": version_id,
            },
            headers=auth_headers,
        )
        assert ai_response.status_code == 200, ai_response.text

        assert captured["conversation_history"] == [
            {"role": "user", "content": "What Creator sets were there in 2024?"},
            {"role": "assistant", "content": "In 2024 there were 20 Creator sets. I showed the full list."},
        ]

    def test_ai_stream_includes_previous_conversation_context(
        self, client: TestClient, auth_headers: dict[str, str], test_user: dict, db: Session, monkeypatch: object
    ) -> None:
        profile = _create_profile(client, auth_headers, visibility="private", name="AI Stream Context Profile")
        profile_id = profile["id"]
        version_id = profile["current_version"]["id"]

        user = db.query(User).filter(User.email == "member@test.com").first()
        assert user is not None

        db.add(
            SortingProfileAiMessage(
                profile_id=UUID(profile_id),
                user_id=user.id,
                version_id=UUID(version_id),
                role="user",
                content="Add the Minecraft sets from 2024.",
            )
        )
        db.add(
            SortingProfileAiMessage(
                profile_id=UUID(profile_id),
                user_id=user.id,
                version_id=UUID(version_id),
                role="assistant",
                content="I found 12 and can add them once you confirm.",
            )
        )
        db.commit()

        captured: dict[str, object] = {}

        def fake_generate_streaming(**kwargs: object):
            captured.update(kwargs)
            yield AiProposalResult(
                content="I can add those 12 sets now.",
                proposal=None,
                model="anthropic/claude-sonnet-4.6",
                usage=None,
                tool_trace=[],
            )

        monkeypatch.setattr(profiles_router, "generate_profile_ai_proposal_streaming", fake_generate_streaming)

        response = client.post(
            f"/api/profiles/{profile_id}/ai/messages/stream",
            json={
                "message": "Please go ahead.",
                "version_id": version_id,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert "I can add those 12 sets now." in response.text

        assert captured["conversation_history"] == [
            {"role": "user", "content": "Add the Minecraft sets from 2024."},
            {"role": "assistant", "content": "I found 12 and can add them once you confirm."},
        ]

    def test_ai_message_and_apply_create_new_version(
        self, client: TestClient, auth_headers: dict[str, str], test_user: dict, monkeypatch: object
    ) -> None:
        profile = _create_profile(client, auth_headers, visibility="private", name="AI Profile")
        profile_id = profile["id"]
        version_id = profile["current_version"]["id"]

        monkeypatch.setattr(
            profiles_router,
            "generate_profile_ai_proposal",
            lambda **_: SimpleNamespace(
                content="I grouped classic bricks into a single category.",
                model="anthropic/claude-sonnet-4.6",
                usage={"input_tokens": 10, "output_tokens": 20},
                tool_trace=[],
                proposal={
                    "summary": "Create a brick category",
                    "proposals": [
                        {
                            "action": "create",
                            "parent_id": None,
                            "position": 0,
                            "name": "Bricks",
                            "match_mode": "all",
                            "conditions": [
                                {"field": "part_num", "op": "contains", "value": "300"}
                            ],
                        }
                    ],
                },
            ),
        )
        monkeypatch.setattr(
            profiles_router,
            "apply_profile_ai_proposal",
            lambda **_: [_sample_rule("ai-bricks", "Bricks from AI", value="300")],
        )

        ai_response = client.post(
            f"/api/profiles/{profile_id}/ai/messages",
            json={
                "message": "Create a simple bricks category.",
                "version_id": version_id,
            },
            headers=auth_headers,
        )
        assert ai_response.status_code == 200, ai_response.text
        ai_message = ai_response.json()
        assert ai_message["role"] == "assistant"
        assert ai_message["proposal"]["summary"] == "Create a brick category"

        apply_response = client.post(
            f"/api/profiles/{profile_id}/ai/messages/{ai_message['id']}/apply",
            json={"change_note": "Applied AI suggestion"},
            headers=auth_headers,
        )
        assert apply_response.status_code == 200, apply_response.text
        version = apply_response.json()
        assert version["version_number"] == 2
        assert version["name"] == "AI Profile"
