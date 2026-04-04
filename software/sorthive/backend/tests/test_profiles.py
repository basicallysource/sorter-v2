"""Tests for sorting profile authoring, community, and machine flows."""

from __future__ import annotations

from types import SimpleNamespace

import app.routers.profiles as profiles_router
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
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


class TestProfileAi:
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
