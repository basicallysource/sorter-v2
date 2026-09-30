"""Profiles through an API key, as an assistant uses them: keys any user can
make, rules checked before saving, where a piece would go, kits, Hive's
default profiles, and a machine's records."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.routers.kits as kits_router
import app.routers.profiles as profiles_router
import app.services.default_profiles as default_profiles
import app.services.profile_display as profile_display
from app.models.machine_piece import MachinePiece
from tests.conftest import _auth_headers, _login_user, _register_user
from tests.test_profiles import _catalog


@pytest.fixture()
def catalog(monkeypatch):
    service = _catalog({"10283-1": [("3001", 5, 4), ("3002", 7, 2)]})
    for module in (profiles_router, kits_router, default_profiles, profile_display):
        monkeypatch.setattr(module, "get_profile_catalog_service", lambda: service)
    return service


def _key(client: TestClient, headers: dict[str, str], scopes: list[str], name: str = "My assistant") -> dict[str, str]:
    response = client.post("/api/auth/api-keys", json={"name": name, "scopes": scopes}, headers=headers)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['raw_token']}"}


def _rule(rule_id: str, name: str, *conditions: tuple[str, str, object]) -> dict:
    return {
        "id": rule_id,
        "name": name,
        "conditions": [{"id": f"{rule_id}-{i}", "field": f, "op": o, "value": v} for i, (f, o, v) in enumerate(conditions)],
    }


class TestKeys:
    def test_a_member_can_make_a_profiles_key(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        _key(client, auth_headers, ["profiles:read", "profiles:write", "records:read"])

    def test_a_member_cannot_make_an_admin_key(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.post("/api/auth/api-keys", json={"name": "x", "scopes": ["fleet:read"]}, headers=auth_headers)
        assert response.status_code == 403
        assert response.json()["code"] == "API_KEY_SCOPE_ADMIN_ONLY"

    def test_a_read_key_cannot_write(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        key = _key(client, auth_headers, ["profiles:read"])
        assert client.get("/api/profiles?scope=mine", headers=key).status_code == 200
        assert client.post("/api/profiles", json={"name": "Nope"}, headers=key).status_code == 403


def test_fields_name_the_older_names_saved_rules_still_use(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/profile-catalog/fields", headers=_key(client, auth_headers, ["profiles:read"])).json()
    offered = {field["field"]: field for field in body["fields"]}
    assert "bl_catalog_category_id" not in offered
    assert body["aliases"]["bl_catalog_category_id"] == "bl_category_id"
    assert body["aliases"]["bl_price_unit_quantity"] == "bl_price_lots"
    assert offered["bl_catalog_is_obsolete"]["type"] == "bool"
    assert offered["bl_catalog_is_obsolete"]["label"] == "Obsolete"


class TestProfilesThroughAKey:
    def test_create_save_and_see_who_changed_it(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        key = _key(client, auth_headers, ["profiles:read", "profiles:write"], name="Claude")
        created = client.post(
            "/api/profiles",
            json={"name": "2 x 4s", "rules": [_rule("r1", "2 x 4 bricks", ("bricklink_id", "eq", 3001))]},
            headers=key,
        )
        assert created.status_code == 200, created.text
        profile = created.json()
        version = profile["current_version"]
        assert version["created_via"] == "api"
        assert version["created_via_key_name"] == "Claude"
        # the number 3001 was stored as the ID "3001" and matches the part
        assert version["rules"][0]["conditions"][0]["value"] == "3001"
        assert version["categories"]["r1"]["part_count"] == 1
        assert version["category_order"][0] == "r1"

        head = client.get(f"/api/profiles/{profile['id']}/head", headers=auth_headers).json()
        assert head["latest_version_number"] == 1
        assert head["created_via_key_name"] == "Claude"

        renamed = client.patch(f"/api/profiles/{profile['id']}", json={"name": "Big bricks"}, headers=key)
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Big bricks"

    def test_a_broken_rule_is_refused_with_every_problem(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        key = _key(client, auth_headers, ["profiles:read", "profiles:write"])
        profile = client.post("/api/profiles", json={"name": "P"}, headers=key).json()
        response = client.post(
            f"/api/profiles/{profile['id']}/versions",
            json={
                "name": "P",
                "rules": [
                    _rule("a", "A", ("shoe_size", "eq", 9)),
                    _rule("b", "B", ("bl_catalog_weight", "contains", "heavy")),
                    _rule("c", "C", ("name", "regex", "(")),
                ],
            },
            headers=key,
        )
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "PROFILE_RULES_INVALID"
        assert [problem["rule_id"] for problem in body["details"]] == ["a", "b", "c"]
        assert client.get(f"/api/profiles/{profile['id']}/head", headers=key).json()["latest_version_number"] == 1

    def test_preview_names_conditions_and_problems(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        response = client.post(
            "/api/profiles/preview",
            json={"rules": [_rule("red", "Red", ("color_id", "eq", 5)), _rule("bad", "Bad", ("color_id", "eq", "red"))]},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        values = preview["categories"]["red"]["conditions"]["items"][0]["values"]
        assert values[0]["label"] == "Red"
        assert values[0]["rgb"] == "C91A09"
        assert [problem["rule_id"] for problem in preview["problems"]] == ["bad"]

    def test_route_says_where_pieces_go(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        document = {
            "rules": [_rule("red", "Red bricks", ("category_id", "eq", 11), ("color_id", "eq", 5))],
            "fallback_mode": {"rebrickable_categories": True},
        }
        response = client.post(
            "/api/profiles/route",
            json={
                "document": document,
                "pieces": [
                    {"part": "3001", "color_id": 5},
                    {"part": "3001", "bricklink_color_id": 7},
                    {"part": "no-such-part"},
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [(r["category_name"], r["why"]) for r in results] == [
            ("Red bricks", "rule"),
            ("Bricks", "fallback"),
            ("Everything else", "default"),
        ]
        assert results[2]["known_part"] is False


class TestKits:
    def test_a_kit_by_bricklink_ids_collected_by_a_rule(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        kit = client.post(
            "/api/kits",
            json={
                "name": "Order 42",
                "parts": [
                    {"part": "3001", "bricklink_color_id": 5, "quantity": 3},
                    {"part": "3001", "color_id": 5, "quantity": 1},
                    {"part": "3002", "quantity": 2},
                ],
            },
            headers=auth_headers,
        )
        assert kit.status_code == 200, kit.text
        kit = kit.json()
        assert [(line["part_num"], line["color_id"], line["quantity"]) for line in kit["parts"]] == [("3001", 5, 4), ("3002", None, 2)]
        assert kit["any_color_lines"] == 1
        assert "no color" in kit["warnings"][0]

        profile = client.post(
            "/api/profiles",
            json={"name": "Orders", "rules": [{"id": "order", "rule_type": "kit", "kit_id": kit["id"], "name": "Order 42"}]},
            headers=auth_headers,
        )
        assert profile.status_code == 200, profile.text
        version = profile.json()["current_version"]
        assert version["categories"]["order"]["kind"] == "kit"
        assert version["categories"]["order"]["kit"]["total_quantity"] == 6

        in_use = client.delete(f"/api/kits/{kit['id']}", headers=auth_headers)
        assert in_use.status_code == 409
        assert client.get(f"/api/kits/{kit['id']}", headers=auth_headers).json()["used_by"][0]["name"] == "Orders"

    def test_unknown_parts_and_colors_are_refused_together(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        response = client.post(
            "/api/kits",
            json={"name": "Typo", "parts": [{"part": "nope", "quantity": 1}, {"part": "3001", "color_id": 999, "quantity": 1}]},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert len(response.json()["details"]) == 2

    def test_a_kit_from_a_set(self, client: TestClient, auth_headers: dict[str, str], catalog) -> None:
        response = client.post("/api/kits/from-set", json={"set_num": "10283-1"}, headers=auth_headers)
        assert response.status_code == 200, response.text
        kit = response.json()
        assert kit["source"] == "set"
        assert kit["total_quantity"] == 6

    def test_a_kit_rule_naming_someone_elses_private_kit_is_refused(
        self, client: TestClient, auth_headers: dict[str, str], catalog
    ) -> None:
        kit = client.post("/api/kits", json={"name": "Mine", "parts": [{"part": "3001", "quantity": 1}]}, headers=auth_headers).json()
        client.post("/api/auth/logout", headers=_auth_headers(client))
        _register_user(client, "other@test.com", "Password123!", "Other")
        _login_user(client, "other@test.com", "Password123!")
        response = client.post(
            "/api/profiles",
            json={"name": "Theirs", "rules": [{"id": "k", "rule_type": "kit", "kit_id": kit["id"], "name": "K"}]},
            headers=_auth_headers(client),
        )
        assert response.status_code == 400
        assert response.json()["details"][0]["rule_id"] == "k"


class TestDefaultProfiles:
    def test_every_machine_gets_the_defaults_it_can_run(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, machine_token: str, catalog
    ) -> None:
        assert len(default_profiles.ensure_default_profiles(db)) == 3
        # a second start with the same definitions publishes nothing new
        assert default_profiles.ensure_default_profiles(db) == []
        machine = {"Authorization": f"Bearer {machine_token}"}

        old_sorter = client.get("/api/machine/profiles/library", headers=machine).json()["profiles"]
        assert [profile["name"] for profile in old_sorter] == ["BrickLink categories"]
        assert old_sorter[0]["is_default"] is True

        new_sorter = client.get(
            "/api/machine/profiles/library?features=program,color_fallback,kit_cascade", headers=machine
        ).json()["profiles"]
        assert [profile["name"] for profile in new_sorter] == ["BrickLink categories", "Colors", "Colors and basic pieces"]

        colors = next(profile for profile in new_sorter if profile["name"] == "Colors")
        version_id = colors["latest_published_version"]["id"]
        refused = client.get(f"/api/machine/profiles/versions/{version_id}/artifact", headers=machine)
        assert refused.status_code == 409
        program = client.get(
            f"/api/machine/profiles/versions/{version_id}/artifact?format=program&features=program,color_fallback",
            headers=machine,
        )
        assert program.status_code == 200
        assert program.json()["artifact"]["program"]["fallback"] == {"by": "color"}

        bricklink = old_sorter[0]["latest_published_version"]["id"]
        gzipped = client.get(f"/api/machine/profiles/versions/{bricklink}/artifact", headers={**machine, "Accept-Encoding": "gzip"})
        assert gzipped.headers.get("content-encoding") == "gzip"
        plain = client.get(f"/api/machine/profiles/versions/{bricklink}/artifact", headers={**machine, "Accept-Encoding": "identity"})
        assert plain.headers.get("content-encoding") is None
        legacy = plain.json()["artifact"]
        assert gzipped.json()["artifact"] == legacy
        # the flat map, for a sorter from before the program (these made-up
        # parts have no BrickLink category, so it files none of them)
        assert "program" not in legacy
        assert legacy["schema_version"] == 1
        assert legacy["part_to_category"] == {}

        assign = client.put(
            "/api/machine/profile-assignment",
            json={"profile_id": old_sorter[0]["id"], "version_id": bricklink},
            headers=machine,
        )
        assert assign.status_code == 200, assign.text


class TestRecords:
    def test_only_your_own_machines(
        self, client: TestClient, auth_headers: dict[str, str], db: Session, test_machine: dict
    ) -> None:
        for local_id, part in enumerate(["3001", "3001", "3002"], start=1):
            db.add(
                MachinePiece(
                    machine_id=UUID(test_machine["id"]),
                    piece_uuid=f"piece-{local_id}",
                    local_id=local_id,
                    part_id=part,
                    part_name=f"Part {part}",
                    color_id="5",
                    color_name="Red",
                    confidence=0.9,
                )
            )
        db.commit()
        key = _key(client, auth_headers, ["records:read"])
        machines = client.get("/api/records/machines", headers=key).json()["machines"]
        assert machines == [
            {"id": test_machine["id"], "name": "Test Sorter", "last_seen_at": None, "piece_count": 3}
        ]
        parts = client.get(f"/api/records/machines/{test_machine['id']}/parts", headers=key).json()
        assert [(p["part_id"], p["count"]) for p in parts["parts"]] == [("3001", 2), ("3002", 1)]
        pieces = client.get(f"/api/records/machines/{test_machine['id']}/pieces?limit=2", headers=key).json()
        assert [p["piece_uuid"] for p in pieces["items"]] == ["piece-3", "piece-2"]
        assert pieces["next_cursor"] == 2

        client.post("/api/auth/logout", headers=_auth_headers(client))
        _register_user(client, "nosy@test.com", "Password123!", "Nosy")
        _login_user(client, "nosy@test.com", "Password123!")
        nosy = _key(client, _auth_headers(client), ["records:read"])
        assert client.get(f"/api/records/machines/{test_machine['id']}/parts", headers=nosy).status_code == 404


def test_conditions_may_leave_out_their_ids(client: TestClient, auth_headers: dict[str, str], catalog) -> None:
    # The skill's example document gives rules IDs (bins are assigned by them)
    # but not conditions; Hive makes those.
    response = client.post(
        "/api/profiles",
        json={"name": "Plain", "rules": [{"id": "b", "name": "2 x 4", "conditions": [{"field": "bricklink_id", "op": "eq", "value": "3001"}]}]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    condition = response.json()["current_version"]["rules"][0]["conditions"][0]
    assert condition["id"]


def test_the_editors_chat_can_set_a_rules_picture() -> None:
    from app.services.profile_ai import apply_profile_ai_proposal

    rules = apply_profile_ai_proposal(
        rules=[{"id": "r1", "name": "Bricks", "conditions": [{"id": "c", "field": "bl_category_id", "op": "eq", "value": 5}]}],
        selected_rule_id=None,
        proposal={
            "proposals": [
                {"action": "edit", "target_rule_id": "r1", "name": "Bricks", "match_mode": "all",
                 "conditions": [{"field": "bl_category_id", "op": "eq", "value": 5}], "image_url": "https://img.example/3001.png"},
                {"action": "create", "name": "Plates", "match_mode": "all",
                 "conditions": [{"field": "bl_category_id", "op": "eq", "value": 26}], "image_url": "https://img.example/3020.png"},
            ]
        },
    )
    assert [rule.get("image_url") for rule in rules] == ["https://img.example/3001.png", "https://img.example/3020.png"]


def test_a_version_from_before_bins_is_described_for_pages(
    client: TestClient, auth_headers: dict[str, str], db: Session, catalog
) -> None:
    from app.models.sorting_profile_version import SortingProfileVersion

    profile = client.post("/api/profiles", json={"name": "Old"}, headers=auth_headers).json()
    rules = [{"id": "r1", "name": "Bricks", "match_mode": "all", "conditions": [{"id": "c", "field": "category_id", "op": "eq", "value": 11}], "children": []}]
    # stored the way versions were before: a flat map, and bins with names only
    db.add(
        SortingProfileVersion(
            profile_id=UUID(profile["id"]),
            version_number=2,
            name="Old",
            default_category_id="misc",
            rules_json=rules,
            fallback_mode_json={},
            compiled_artifact_json={"part_to_category": {"any_color-3001": "r1"}, "categories": {"r1": {"name": "Bricks"}}},
            compiled_stats_json={"total_parts": 5, "matched": 1},
            compiled_hash="old",
            compiled_part_count=1,
        )
    )
    from app.models.sorting_profile import SortingProfile

    db.query(SortingProfile).filter(SortingProfile.id == UUID(profile["id"])).update({"latest_version_number": 2})
    db.commit()

    version = client.get(f"/api/profiles/{profile['id']}", headers=auth_headers).json()["current_version"]
    assert version["version_number"] == 2
    bricks = version["categories"]["r1"]
    assert bricks["kind"] == "rule"
    assert bricks["conditions"]["items"][0]["values"][0]["label"] == "Bricks"
    assert version["category_order"][0] == "r1"

    assert profile_display.backfill_card_bins(db) == 1
    listed = client.get("/api/profiles?scope=mine", headers=auth_headers).json()
    assert listed[0]["latest_version"]["bins"][0]["name"] == "Bricks"


def test_a_key_can_ask_who_it_is(client: TestClient, auth_headers: dict[str, str]) -> None:
    key = _key(client, auth_headers, ["profiles:read"], name="Mine")
    me = client.get("/api/agent/whoami", headers=key).json()
    assert me["key"] == {"name": "Mine", "scopes": ["profiles:read"], "machine_ids": None}
    assert me["account"]["email"] == "member@test.com"


def test_part_search_takes_a_key(client: TestClient, auth_headers: dict[str, str], catalog, monkeypatch) -> None:
    monkeypatch.setattr(catalog, "search_parts", lambda q, cat_id, limit, offset: {"results": [], "total": 0}, raising=False)
    key = _key(client, auth_headers, ["profiles:read"])
    assert client.get("/api/profile-catalog/search-parts?q=brick", headers=key).status_code == 200


def test_routing_fills_a_kit_then_passes_pieces_on(client: TestClient, auth_headers: dict[str, str], catalog) -> None:
    kit = client.post("/api/kits", json={"name": "Two red", "parts": [{"part": "3001", "color_id": 5, "quantity": 2}]}, headers=auth_headers).json()
    document = {
        "rules": [
            {"id": "kit", "rule_type": "kit", "kit_id": kit["id"], "name": "Two red"},
            {"id": "bricks", "name": "Bricks", "conditions": [{"field": "category_id", "op": "eq", "value": 11}]},
        ]
    }
    pieces = [{"part": "3001", "color_id": 5}] * 3
    results = client.post("/api/profiles/route", json={"document": document, "pieces": pieces}, headers=auth_headers).json()["results"]
    assert [(r["category_id"], r["kit_left"]) for r in results] == [("kit", 1), ("kit", 0), ("bricks", None)]
    unfilled = client.post(
        "/api/profiles/route", json={"document": document, "pieces": pieces, "fill_kits": False}, headers=auth_headers
    ).json()["results"]
    assert [r["category_id"] for r in unfilled] == ["kit", "kit", "kit"]
