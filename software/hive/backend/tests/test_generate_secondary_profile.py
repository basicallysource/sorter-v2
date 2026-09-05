"""Tests for scripts/generate_secondary_profile.py on a tiny Rebrickable fixture."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.profile import SortingProfileVersionCreateRequest
from app.services.profile_engine.rule_engine import generateProfile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "rebrickable_mini"

EXPECTED_RULE_IDS = [
    "printed", "minifig-heads", "minifig-torsos", "minifig-legs", "minifig-accessories",
    "animals-plants", "windows-doors-panels", "transparent", "metallic", "wheels-tyres",
    "technic-special", "rare", "high-value",
]


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_secondary_profile", BACKEND_ROOT / "scripts" / "generate_secondary_profile.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> dict:
    gen = _load_generator()
    out = tmp_path_factory.mktemp("secondary") / "profile.json"
    assert gen.main([str(FIXTURE_DIR), "--out", str(out), "--rare-max-sets", "3"]) == 0
    return {
        "payload": json.loads(out.read_text(encoding="utf-8")),
        "summary": out.with_suffix(".md").read_text(encoding="utf-8"),
    }


def _rule(payload: dict, rule_id: str) -> dict:
    return next(r for r in payload["rules"] if r["id"] == rule_id)


def _condition(rule: dict, field: str) -> dict:
    return next(c for c in rule["conditions"] if c["field"] == field)


def test_payload_matches_version_create_schema(generated):
    payload = generated["payload"]
    parsed = SortingProfileVersionCreateRequest.model_validate(payload)
    assert parsed.name == "Seltenes und Besonderes"
    assert parsed.default_category_id == "misc"
    assert [r.id for r in parsed.rules] == EXPECTED_RULE_IDS
    assert all(r.rule_type == "filter" and not r.disabled for r in parsed.rules)
    assert parsed.publish is True


def test_every_rule_is_secondary_with_unique_condition_ids(generated):
    payload = generated["payload"]
    seen: set[str] = set()

    def walk(rule: dict) -> None:
        assert rule["role"] == "secondary"
        for cond in rule["conditions"]:
            assert cond["id"] not in seen
            seen.add(cond["id"])
        for child in rule["children"]:
            walk(child)

    for rule in payload["rules"]:
        walk(rule)
    assert seen


def test_rare_list_excludes_claimed_common_and_non_piece_parts(generated):
    rare = _condition(_rule(generated["payload"], "rare"), "part_num")
    assert rare["op"] == "in"
    # 3001/3005 ship in 1-2 sets (their transparent/chrome colours are claimed per colour only),
    # 3703 and 9999x are plain rare parts. 3020 is in 3 sets, 3626c is a minifig head,
    # 12345 is a sticker sheet, 77777 only appears in a version-2 inventory.
    assert rare["value"] == ["3001", "3005", "3703", "9999x"]


def test_colour_rules_are_scoped_to_parts_seen_in_those_colours(generated):
    payload = generated["payload"]
    transparent = _rule(payload, "transparent")
    assert _condition(transparent, "part_num")["value"] == ["3001"]
    assert _condition(transparent, "color_id")["value"] == [47]
    metallic = _rule(payload, "metallic")
    assert _condition(metallic, "part_num")["value"] == ["3005"]
    assert _condition(metallic, "color_id")["value"] == [383]


def test_rule_engine_assigns_fixture_parts_in_priority_order(generated):
    payload = generated["payload"]
    parts = {}
    with open(FIXTURE_DIR / "parts.csv", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            part_num, name, cat_id, _ = line.rstrip("\n").split(",")
            parts[part_num] = {"part_num": part_num, "name": name, "part_cat_id": int(cat_id), "external_ids": {}}
    categories = {8: {"id": 8, "name": "Technic Bricks"}, 11: {"id": 11, "name": "Bricks"}}
    sp = SimpleNamespace(rules=payload["rules"], default_category_id=payload["default_category_id"],
                         fallback_mode=payload["fallback_mode"])
    mapping = generateProfile(sp, parts, categories=categories)["part_to_category"]
    assert mapping["any_color-3626cpr0001"] == "printed"
    assert mapping["any_color-3626c"] == "minifig-heads"
    assert mapping["any_color-973c01"] == "minifig-torsos"
    assert mapping["47-3001"] == "transparent"
    assert mapping["any_color-3001"] == "rare"
    assert mapping["383-3005"] == "metallic"
    assert mapping["any_color-3648"] == "technic-special"
    assert mapping["any_color-731c05"] == "technic-special"
    assert mapping["any_color-3020"] == "misc"
    assert mapping["any_color-12345"] == "misc"


def test_summary_lists_every_rule_and_the_gaps(generated):
    summary = generated["summary"]
    for rule in generated["payload"]["rules"]:
        assert f"`{rule['id']}`" in summary
    assert "## Not expressible in the rule engine" in summary
    assert "| n/a |" in summary  # high-value has no CSV-side count
