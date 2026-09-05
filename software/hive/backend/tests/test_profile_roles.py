"""Rule roles and instance-backed set rules: validation, compile passthrough, AI output shape."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.routers.profiles as profiles_router
import app.routers.set_instances as set_instances_router
from app.errors import APIError
from app.services.profile_ai import _validate_proposal, apply_profile_ai_proposal
from app.services.profile_catalog import ProfileCatalogService
from tests.conftest import _auth_headers, _login_user, _register_user
from tests.test_profiles import _DummyCatalogService, _create_profile, _sample_rule, _set_rule
from tests.test_set_instances import SHUTTLE, _DummySetCatalog, _create_instance


class _Catalog(_DummySetCatalog, _DummyCatalogService):
    """Compiles profiles like the profile tests and expands sets like the set instance tests."""

    def __init__(self) -> None:
        _DummySetCatalog.__init__(self, {"10283-1": SHUTTLE})
        _DummyCatalogService.__init__(self, {"10283-1": [(p["part_num"], p["color_id"], p["quantity"]) for p in SHUTTLE["parts"]]})


@pytest.fixture()
def catalog(monkeypatch: pytest.MonkeyPatch) -> _Catalog:
    catalog = _Catalog()
    monkeypatch.setattr(profiles_router, "get_profile_catalog_service", lambda: catalog)
    monkeypatch.setattr(set_instances_router, "get_profile_catalog_service", lambda: catalog)
    return catalog


def _save(client: TestClient, auth_headers: dict[str, str], profile_id: str, rules: list[dict]) -> object:
    return client.post(
        f"/api/profiles/{profile_id}/versions",
        json={"name": "Roles", "description": "", "default_category_id": "misc", "rules": rules, "fallback_mode": {}},
        headers=auth_headers,
    )


class TestRuleSave:
    def test_role_and_binding_round_trip_into_artifact_and_summary(
        self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog
    ) -> None:
        instance = _create_instance(client, auth_headers)
        profile = _create_profile(client, auth_headers)
        bricks = {**_sample_rule("bricks", "Bricks"), "role": "primary"}
        shuttle = {**_set_rule("shuttle", "Shuttle", "10283-1"), "set_instance_id": instance["id"]}
        plates = _sample_rule("plates", "Plates")

        response = _save(client, auth_headers, profile["id"], [bricks, shuttle, plates])
        assert response.status_code in (200, 201), response.text
        version = response.json()
        by_id = {rule["id"]: rule for rule in version["rules"]}
        assert by_id["bricks"]["role"] == "primary"
        assert by_id["shuttle"]["set_instance_id"] == instance["id"]
        assert by_id["shuttle"]["role"] is None  # absent stays absent: the default is the reader's
        assert by_id["plates"]["role"] is None
        assert [(r["name"], r["role"], r["set_instance_id"]) for r in version["rules_summary"]] == [
            ("Bricks", "primary", None),
            ("Shuttle", "primary", instance["id"]),
            ("Plates", "secondary", None),
        ]

        artifact = client.get(f"/api/profiles/{profile['id']}/versions/{version['id']}/artifact").json()["artifact"]
        artifact_rules = {rule["id"]: rule for rule in artifact["rules"]}
        assert artifact_rules["bricks"]["role"] == "primary"
        assert artifact_rules["shuttle"]["set_instance_id"] == instance["id"]

    def test_invalid_role_is_rejected(self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog) -> None:
        profile = _create_profile(client, auth_headers)
        response = _save(client, auth_headers, profile["id"], [{**_sample_rule("bricks", "Bricks"), "role": "tertiary"}])
        assert response.status_code == 422

    def test_binding_must_be_owned_by_profile_owner(
        self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog
    ) -> None:
        profile = _create_profile(client, auth_headers)
        rule = {**_set_rule("shuttle", "Shuttle", "10283-1"), "set_instance_id": str(uuid4())}
        response = _save(client, auth_headers, profile["id"], [rule])
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "PROFILE_RULE_INSTANCE_UNKNOWN"

        client.post("/api/auth/logout", headers=_auth_headers(client))
        _register_user(client, "other@test.com", "Password123!", "Other")
        _login_user(client, "other@test.com", "Password123!")
        other_headers = _auth_headers(client)
        foreign = _create_instance(client, other_headers)
        other_profile = _create_profile(client, other_headers)
        assert _save(client, other_headers, other_profile["id"], [{**rule, "set_instance_id": foreign["id"]}]).status_code in (200, 201)

        client.post("/api/auth/logout", headers=other_headers)
        _login_user(client, "member@test.com", "Password123!")
        response = _save(client, _auth_headers(client), profile["id"], [{**rule, "set_instance_id": foreign["id"]}])
        assert response.status_code == 400
        assert response.json()["code"] == "PROFILE_RULE_INSTANCE_UNKNOWN"

    def test_binding_must_match_set_and_rule_type(
        self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog
    ) -> None:
        instance = _create_instance(client, auth_headers)
        profile = _create_profile(client, auth_headers)

        mismatch = {**_set_rule("other", "Other set", "75192-1"), "set_instance_id": instance["id"]}
        response = _save(client, auth_headers, profile["id"], [mismatch])
        assert response.status_code == 400
        assert response.json()["code"] == "PROFILE_RULE_INSTANCE_SET_MISMATCH"

        filter_rule = {**_sample_rule("bricks", "Bricks"), "set_instance_id": instance["id"]}
        response = _save(client, auth_headers, profile["id"], [filter_rule])
        assert response.status_code == 400
        assert response.json()["code"] == "PROFILE_RULE_INSTANCE_INVALID"

    def test_fork_by_another_user_drops_bindings_but_keeps_roles(
        self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog
    ) -> None:
        instance = _create_instance(client, auth_headers)
        profile = _create_profile(client, auth_headers, visibility="public")
        rules = [
            {**_set_rule("shuttle", "Shuttle", "10283-1"), "set_instance_id": instance["id"], "role": "primary"},
            {**_sample_rule("bricks", "Bricks"), "role": "primary"},
        ]
        version = _save(client, auth_headers, profile["id"], rules).json()
        client.post(f"/api/profiles/{profile['id']}/versions/{version['id']}/publish", headers=auth_headers)

        client.post("/api/auth/logout", headers=_auth_headers(client))
        _register_user(client, "forker@test.com", "Password123!", "Forker")
        _login_user(client, "forker@test.com", "Password123!")
        response = client.post(f"/api/profiles/{profile['id']}/fork", json={}, headers=_auth_headers(client))
        assert response.status_code in (200, 201), response.text
        forked = {rule["id"]: rule for rule in response.json()["current_version"]["rules"]}
        assert forked["shuttle"]["set_instance_id"] is None
        assert forked["shuttle"]["role"] == "primary"
        assert forked["bricks"]["role"] == "primary"


class TestCompilePassthrough:
    def test_real_compiler_keeps_role_and_binding_verbatim(self) -> None:
        instance_id = str(uuid4())
        document = {
            "id": "p1",
            "name": "Roles",
            "rules": [
                {**_sample_rule("bricks", "Bricks"), "role": "primary"},
                {**_set_rule("shuttle", "Shuttle", "10283-1"), "set_instance_id": instance_id},
                {"id": "child-parent", "name": "Parent", "role": "secondary", "conditions": [], "children": [
                    {"id": "child", "name": "Child", "conditions": [], "set_instance_id": None},
                ]},
            ],
        }
        artifact = ProfileCatalogService().compile_document(document)["artifact"]
        rules = {rule["id"]: rule for rule in artifact["rules"]}
        assert rules["bricks"]["role"] == "primary"
        assert "role" not in rules["shuttle"]
        assert rules["shuttle"]["set_instance_id"] == instance_id
        assert rules["child-parent"]["children"][0]["set_instance_id"] is None


class TestAiOutputShape:
    def test_validate_rejects_unknown_role(self) -> None:
        with pytest.raises(APIError) as excinfo:
            _validate_proposal({"summary": "x", "proposals": [{"action": "create", "name": "A", "match_mode": "all", "conditions": [], "role": "tertiary"}]})
        assert excinfo.value.error_code == "AI_ROLE_INVALID"
        _validate_proposal({"summary": "x", "proposals": [{"action": "create_set", "set_num": "10283-1", "role": "secondary"}]})

    def test_apply_binds_set_rules_and_carries_roles(self) -> None:
        bound: list[tuple[str, bool]] = []

        def bind(set_num: str, include_spares: bool) -> str:
            bound.append((set_num, include_spares))
            return "inst-1"

        rules = apply_profile_ai_proposal(
            rules=[_sample_rule("bricks", "Bricks")],
            selected_rule_id=None,
            proposal={
                "proposals": [
                    {"action": "create_set", "set_num": "10283-1", "name": "Shuttle", "include_spares": True, "set_meta": {"name": "Shuttle"}},
                    {"action": "create_set", "set_num": "75192-1", "name": "Falcon", "role": "secondary"},
                    {"action": "create", "name": "Minifigs", "match_mode": "any", "conditions": [], "role": "primary"},
                    {"action": "create", "name": "Plates", "match_mode": "all", "conditions": []},
                    {"action": "edit", "target_rule_id": "bricks", "name": "Bricks", "match_mode": "all", "conditions": [], "role": "primary"},
                ]
            },
            bind_set_instance=bind,
        )
        by_name = {rule["name"]: rule for rule in rules}
        assert bound == [("10283-1", True), ("75192-1", False)]
        assert (by_name["Shuttle"]["role"], by_name["Shuttle"]["set_instance_id"]) == ("primary", "inst-1")
        assert by_name["Falcon"]["role"] == "secondary"
        assert by_name["Minifigs"]["role"] == "primary"
        assert "role" not in by_name["Plates"]
        assert by_name["Bricks"]["role"] == "primary"

        unbound = apply_profile_ai_proposal(
            rules=[], selected_rule_id=None,
            proposal={"proposals": [{"action": "create_set", "set_num": "10283-1", "name": "Shuttle"}]},
        )
        assert unbound[0]["set_instance_id"] is None

    def test_apply_route_reuses_open_copy_or_creates_one(
        self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile = _create_profile(client, auth_headers)
        version_id = profile["current_version"]["id"]
        monkeypatch.setattr(
            profiles_router,
            "generate_profile_ai_proposal",
            lambda **kwargs: SimpleNamespace(
                content="Added the shuttle.",
                model="test",
                usage=None,
                tool_trace=[],
                proposal={"summary": "Add", "proposals": [{"action": "create_set", "set_num": "10283-1", "name": "Shuttle", "set_meta": {"name": "Shuttle"}}]},
                owned_sets=kwargs["owned_sets"],
            ),
        )

        def chat_and_apply() -> dict:
            message = client.post(f"/api/profiles/{profile['id']}/ai/messages", json={"message": "add the shuttle", "version_id": version_id}, headers=auth_headers)
            assert message.status_code == 200, message.text
            applied = client.post(f"/api/profiles/{profile['id']}/ai/messages/{message.json()['id']}/apply", json={"change_note": "ai"}, headers=auth_headers)
            assert applied.status_code == 200, applied.text
            return applied.json()

        # No copy yet: applying creates one and binds the rule to it.
        version = chat_and_apply()
        instances = client.get("/api/set-instances").json()
        assert len(instances) == 1
        assert instances[0]["set_num"] == "10283-1"
        shuttle = next(rule for rule in version["rules"] if rule["rule_type"] == "set")
        assert shuttle["set_instance_id"] == instances[0]["id"]
        assert shuttle["role"] == "primary"

        # A second profile for the same set binds to the existing open copy instead of adding another.
        other = _create_profile(client, auth_headers, name="Second")
        profile, version_id = other, other["current_version"]["id"]
        version = chat_and_apply()
        assert len(client.get("/api/set-instances").json()) == 1
        assert next(rule for rule in version["rules"] if rule["rule_type"] == "set")["set_instance_id"] == instances[0]["id"]

    def test_prompt_gets_the_users_copies(
        self, client: TestClient, auth_headers: dict[str, str], catalog: _Catalog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _create_instance(client, auth_headers, label="Shuttle, Kiste Keller")
        profile = _create_profile(client, auth_headers)
        captured: dict[str, object] = {}

        def fake_generate(**kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(content="ok", model="test", usage=None, tool_trace=[], proposal=None)

        monkeypatch.setattr(profiles_router, "generate_profile_ai_proposal", fake_generate)
        response = client.post(f"/api/profiles/{profile['id']}/ai/messages", json={"message": "hi", "version_id": profile["current_version"]["id"]}, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert captured["owned_sets"] == [{"set_num": "10283-1", "label": "Shuttle, Kiste Keller", "status": "open"}]
