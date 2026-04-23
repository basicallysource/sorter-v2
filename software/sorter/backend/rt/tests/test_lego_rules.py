from __future__ import annotations

import json
from pathlib import Path


from rt.contracts.classification import ClassifierResult
from rt.contracts.registry import RULES_ENGINES
from rt.rules.lego_rules import LegoRulesEngine


def _result(part_id: str | None, color_id: str | None = "red") -> ClassifierResult:
    return ClassifierResult(
        part_id=part_id,
        color_id=color_id,
        category=None,
        confidence=0.9,
        algorithm="stub",
        latency_ms=5.0,
        meta={},
    )


def _write_profile(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(payload))
    return p


def _write_layout(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "layout.json"
    p.write_text(json.dumps(payload))
    return p


def test_registry_has_lego_default() -> None:
    assert "lego_default" in RULES_ENGINES.keys()


def test_matches_specific_color_rule(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path,
        {
            "part_to_category": {
                "red-3001": "bricks_2x3",
            },
            "default_category_id": "misc",
        },
    )
    layout = _write_layout(
        tmp_path,
        {
            "layers": [
                {
                    "sections": [
                        [{"category_ids": ["bricks_2x3"]}],
                    ],
                },
            ],
        },
    )
    engine = LegoRulesEngine(
        sorting_profile_path=profile,
        bin_layout_path=layout,
    )
    decision = engine.decide_bin(_result("3001", "red"), context={})
    assert decision.bin_id == "L0-S0-B0"
    assert decision.category == "bricks_2x3"
    assert decision.reason.startswith("matched_profile")


def test_any_color_fallback(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path,
        {
            "part_to_category": {
                "any_color-3001": "bricks_2x3",
            },
            "default_category_id": "misc",
        },
    )
    layout = _write_layout(
        tmp_path,
        {
            "layers": [
                {"sections": [[{"category_ids": ["bricks_2x3"]}]]},
            ],
        },
    )
    engine = LegoRulesEngine(
        sorting_profile_path=profile,
        bin_layout_path=layout,
    )
    decision = engine.decide_bin(_result("3001", "blue"), context={})
    assert decision.bin_id == "L0-S0-B0"
    assert decision.category == "bricks_2x3"


def test_unknown_part_routes_to_reject(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path, {"part_to_category": {}, "default_category_id": "misc"}
    )
    engine = LegoRulesEngine(
        sorting_profile_path=profile,
        reject_bin_id="reject",
        default_bin_id=None,
    )
    decision = engine.decide_bin(_result(None), context={})
    assert decision.bin_id == "reject"
    assert decision.reason == "unknown_part"


def test_no_match_uses_default_bin_when_configured(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path,
        {
            "part_to_category": {"any_color-3001": "bricks_2x3"},
            "default_category_id": "misc",
        },
    )
    # No layout => category->bin mapping empty => falls back to default bin.
    engine = LegoRulesEngine(
        sorting_profile_path=profile,
        default_bin_id="misc_bin",
    )
    decision = engine.decide_bin(_result("9999", "red"), context={})
    assert decision.bin_id == "misc_bin"
    assert decision.reason.startswith("no_bin_for_category")


def test_no_match_no_default_routes_to_reject(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path,
        {"part_to_category": {}, "default_category_id": "misc"},
    )
    engine = LegoRulesEngine(
        sorting_profile_path=profile,
        default_bin_id=None,
        reject_bin_id="reject",
    )
    decision = engine.decide_bin(_result("9999", "red"), context={})
    assert decision.bin_id == "reject"


def test_reload_picks_up_profile_changes(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path, {"part_to_category": {}, "default_category_id": "misc"}
    )
    layout = _write_layout(
        tmp_path,
        {"layers": [{"sections": [[{"category_ids": ["bricks_2x3"]}]]}]},
    )
    engine = LegoRulesEngine(
        sorting_profile_path=profile,
        bin_layout_path=layout,
    )
    first = engine.decide_bin(_result("3001", "red"), context={})
    assert first.bin_id != "L0-S0-B0"

    profile.write_text(
        json.dumps(
            {
                "part_to_category": {"red-3001": "bricks_2x3"},
                "default_category_id": "misc",
            }
        )
    )
    engine.reload()
    second = engine.decide_bin(_result("3001", "red"), context={})
    assert second.bin_id == "L0-S0-B0"


def test_categories_overlay_shape_supported(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path,
        {
            "part_to_category": {"any_color-3001": "bricks_2x3"},
            "default_category_id": "misc",
        },
    )
    layout = _write_layout(
        tmp_path,
        {
            "layers": [{"sections": [["medium"]]}],
            "categories": [[[["bricks_2x3"]]]],
        },
    )
    engine = LegoRulesEngine(
        sorting_profile_path=profile, bin_layout_path=layout
    )
    decision = engine.decide_bin(_result("3001", "red"), context={})
    assert decision.bin_id == "L0-S0-B0"


def test_saved_bin_categories_route_without_layout_file(tmp_path: Path, monkeypatch) -> None:
    import rt.rules.lego_rules as lego_rules

    profile = _write_profile(
        tmp_path,
        {
            "part_to_category": {"any_color-3001": "bricks_2x3"},
            "default_category_id": "misc",
        },
    )
    monkeypatch.setattr(
        lego_rules,
        "_saved_category_mapping",
        lambda _logger: {"bricks_2x3": "L0-S1-B2"},
    )

    engine = LegoRulesEngine(sorting_profile_path=profile)
    decision = engine.decide_bin(_result("3001", "red"), context={})

    assert decision.bin_id == "L0-S1-B2"


def test_missing_profile_gracefully_degrades(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.json"
    engine = LegoRulesEngine(sorting_profile_path=missing, default_bin_id="misc_bin")
    decision = engine.decide_bin(_result("3001", "red"), context={})
    # Default category, no explicit bin mapping, falls back to default bin.
    assert decision.bin_id == "misc_bin"


def test_registry_factory_builds_engine(tmp_path: Path) -> None:
    profile = _write_profile(
        tmp_path, {"part_to_category": {}, "default_category_id": "misc"}
    )
    engine = RULES_ENGINES.create(
        "lego_default",
        sorting_profile_path=profile,
    )
    assert isinstance(engine, LegoRulesEngine)
    assert engine.key == "lego_default"
