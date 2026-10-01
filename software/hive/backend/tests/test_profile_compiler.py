"""The profile compiler: what each rule takes, the program a sorter runs, and
the flat map older sorters get, which must route every piece the same way."""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from app.services.profile_engine.compiler import (
    FEATURE_COLOR_FALLBACK,
    CatalogIndex,
    Router,
    compile_document,
    expand_legacy,
    rule_matches,
)
from tests import legacy_rule_engine
from app.services.profile_engine.sorting_profile import SortingProfile as LegacyDocument

# Rebrickable color -> BrickLink color, as the catalog maps them.
RB_TO_BL = {0: 11, 4: 5, 1: 7, 14: 3, 47: 12, 15: 1}
COLORS = {
    0: {"name": "Black", "rgb": "05131D"},
    4: {"name": "Red", "rgb": "C91A09"},
    1: {"name": "Blue", "rgb": "0055BF"},
    14: {"name": "Yellow", "rgb": "F2CD37"},
    47: {"name": "Trans-Clear", "rgb": "FCFCFC"},
    15: {"name": "White", "rgb": "FFFFFF"},
}
BL_CATEGORIES = {
    5: {"category_id": 5, "category_name": "Brick"},
    26: {"category_id": 26, "category_name": "Plate"},
    37: {"category_id": 37, "category_name": "Tile"},
    39: {"category_id": 39, "category_name": "Tile, Decorated"},
}
RB_CATEGORIES = {11: {"name": "Bricks"}, 14: {"name": "Plates"}, 19: {"name": "Tiles"}}


def _part(part_num, name, rb_cat, bl_ids, bl_cat, *, sold=0, weight=1.0):
    items = {
        bl_id: {
            "catalog": {"data": {"name": name, "category_id": bl_cat, "weight": f"{weight:.2f}"}},
            "price_guide": {"ord_used": {"avg": 0.05, "qty": sold, "lots": 1}},
        }
        for bl_id in bl_ids
    }
    return {
        "part_num": part_num,
        "name": name,
        "part_cat_id": rb_cat,
        "part_img_url": f"https://img.example/{part_num}.png",
        "external_ids": {"BrickLink": list(bl_ids)} if bl_ids else {},
        **({"bricklink_data": {"primary_item_no": bl_ids[0], "items": items}} if bl_ids else {}),
    }


def _parts_data():
    parts = {
        "3001": _part("3001", "Brick 2 x 4", 11, ["3001"], 5, sold=9000),
        "3003": _part("3003", "Brick 2 x 2", 11, ["3003"], 5, sold=7000),
        "3004": _part("3004", "Brick 1 x 2", 11, ["3004", "3004old"], 5, sold=500),
        "3020": _part("3020", "Plate 2 x 4", 14, ["3020"], 26, sold=3000),
        "3022": _part("3022", "Plate 2 x 2", 14, ["3022"], 26, sold=2000),
        "3068b": _part("3068", "Tile 2 x 2", 19, ["3068b"], 37, sold=4000),
        "3068bpr0001": _part("3068bpr0001", "Tile 2 x 2 with print", 19, ["3068bpb001"], 39, sold=10),
        "no-bl-part": _part("no-bl-part", "Mystery Part", 19, [], None),
    }
    # the key the old engine files a part under is the dict key's own part_num
    for key, part in parts.items():
        part["part_num"] = key
    return SimpleNamespace(
        parts=parts,
        categories=RB_CATEGORIES,
        bricklink_categories=BL_CATEGORIES,
        colors={rb: {**color, "external_ids": {"BrickLink": {"ext_ids": [RB_TO_BL[rb]]}}} for rb, color in COLORS.items()},
        rb_to_bl_color=dict(RB_TO_BL),
        generation=1,
    )


@pytest.fixture()
def index() -> CatalogIndex:
    return CatalogIndex(_parts_data())


def _rule(rule_id, name, *conditions, match_mode="all", children=None, **extra):
    return {
        "id": rule_id,
        "name": name,
        "match_mode": match_mode,
        "conditions": [
            {"id": f"{rule_id}-c{i}", "field": field, "op": op, "value": value}
            for i, (field, op, value) in enumerate(conditions)
        ],
        "children": children or [],
        **extra,
    }


def _doc(*rules, fallback=None, default="misc"):
    return {"name": "Test", "rules": list(rules), "fallback_mode": fallback or {}, "default_category_id": default}


def _lookup(part_to_category, default, part, color):
    return part_to_category.get(f"{color}-{part}", part_to_category.get(f"any_color-{part}", default))


def _every_piece(index):
    colors = [None, *[str(bl) for bl in RB_TO_BL.values()], "999"]
    parts = sorted({key for keys in index.keys for key in keys}) + ["not-in-catalog"]
    return list(itertools.product(parts, colors))


def _assert_legacy_routes_like_program(compiled, index):
    legacy = expand_legacy(compiled.artifact, index)
    router = Router(compiled.artifact["program"])
    default = compiled.artifact["default_category_id"]
    for part, color in _every_piece(index):
        if part == "not-in-catalog":
            continue
        want, _ = router.route(part, color)
        got = _lookup(legacy["part_to_category"], default, part, color or "any_color")
        assert got == want, (part, color, got, want)
    return legacy


def _legacy_compile(document, index_parts_data):
    profile = LegacyDocument()
    profile.rules = document["rules"]
    profile.default_category_id = document.get("default_category_id", "misc")
    profile.fallback_mode = document.get("fallback_mode") or {}
    legacy_rule_engine.clearCache()
    return legacy_rule_engine.generateProfile(
        profile,
        index_parts_data.parts,
        index_parts_data.categories,
        index_parts_data.bricklink_categories,
        fallback_mode=profile.fallback_mode,
        rb_to_bl_color=index_parts_data.rb_to_bl_color,
    )["part_to_category"]


class TestConditionValues:
    def test_a_bricklink_id_given_as_a_number_still_matches(self, index):
        compiled = compile_document(_doc(_rule("r1", "2 x 4", ("bricklink_id", "eq", 3001))), index)
        assert compiled.problems == []
        assert Router(compiled.artifact["program"]).route("3001", "5") == ("r1", "rule")
        assert compiled.artifact["categories"]["r1"]["part_count"] == 1

    def test_a_part_number_given_as_a_number_still_matches(self, index):
        compiled = compile_document(_doc(_rule("r1", "2 x 2", ("part_num", "in", [3003, "3020"]))), index)
        router = Router(compiled.artifact["program"])
        assert router.route("3003", None)[0] == "r1"
        assert router.route("3020", None)[0] == "r1"
        assert router.route("3001", None)[0] == "misc"

    def test_any_bricklink_alias_matches(self, index):
        compiled = compile_document(_doc(_rule("r1", "1 x 2", ("bricklink_id", "eq", "3004old"))), index)
        router = Router(compiled.artifact["program"])
        assert router.route("3004", None)[0] == "r1"
        assert router.route("3004old", None)[0] == "r1"

    def test_a_category_id_given_as_text_matches(self, index):
        compiled = compile_document(_doc(_rule("r1", "Plates", ("bl_category_id", "in", "26"))), index)
        assert compiled.artifact["categories"]["r1"]["part_count"] == 2

    def test_an_unknown_field_is_a_problem_and_takes_nothing(self, index):
        compiled = compile_document(_doc(_rule("r1", "Broken", ("shoe_size", "eq", 9))), index)
        assert [problem.rule_id for problem in compiled.problems] == ["r1"]
        assert compiled.artifact["program"]["rules"] == []

    def test_an_operator_the_field_does_not_take_is_a_problem(self, index):
        compiled = compile_document(_doc(_rule("r1", "Broken", ("bl_catalog_weight", "contains", "2"))), index)
        assert "does not take" in compiled.problems[0].message


class TestProgram:
    def test_a_color_only_rule_is_one_entry_not_one_per_part(self, index):
        compiled = compile_document(_doc(_rule("clear", "Transparent", ("color_id", "in", [47]))), index)
        assert compiled.artifact["program"]["rules"] == [{"category": "clear", "parts": None, "colors": ["12"]}]
        router = Router(compiled.artifact["program"])
        assert router.route("3001", "12")[0] == "clear"
        assert router.route("3001", "5")[0] == "misc"
        # a trans piece the catalog does not know still goes by its color
        assert router.route("not-in-catalog", "12")[0] == "clear"

    def test_first_rule_wins(self, index):
        compiled = compile_document(
            _doc(
                _rule("red", "Red bricks", ("bl_category_id", "eq", 5), ("color_id", "eq", 4)),
                _rule("bricks", "Bricks", ("bl_category_id", "eq", 5)),
                _rule("red-any", "Red", ("color_id", "eq", 4)),
            ),
            index,
        )
        router = Router(compiled.artifact["program"])
        assert router.route("3001", "5")[0] == "red"
        assert router.route("3001", "7")[0] == "bricks"
        assert router.route("3020", "5")[0] == "red-any"
        assert router.route("3020", "7")[0] == "misc"

    def test_any_mode_with_a_color_means_either(self, index):
        compiled = compile_document(
            _doc(_rule("r1", "Tiles or red", ("bl_category_id", "eq", 37), ("color_id", "eq", 4), match_mode="any")),
            index,
        )
        router = Router(compiled.artifact["program"])
        assert router.route("3068b", "7")[0] == "r1"  # a tile, not red
        assert router.route("3001", "5")[0] == "r1"  # red, not a tile
        assert router.route("3001", "7")[0] == "misc"

    def test_a_color_that_is_not_excluded(self, index):
        compiled = compile_document(_doc(_rule("r1", "Not black bricks", ("bl_category_id", "eq", 5), ("color_id", "neq", 0))), index)
        router = Router(compiled.artifact["program"])
        assert router.route("3001", "5")[0] == "r1"
        assert router.route("3001", "11")[0] == "misc"

    def test_children_narrow_their_parent(self, index):
        parent = _rule(
            "p",
            "Small bricks",
            ("bl_category_id", "eq", 5),
            children=[_rule("c1", "2 x 2", ("name", "contains", "2 x 2")), _rule("c2", "1 x 2", ("name", "contains", "1 x 2"))],
        )
        parent["children"][0]["match_mode"] = "all"
        parent["match_mode"] = "all"
        # children combine with the parent's own conditions by its mode: all of them
        compiled = compile_document(_doc(parent), index)
        assert compiled.artifact["program"]["rules"] == []
        parent["children"] = [
            _rule("g", "Either size", match_mode="any", children=parent["children"]),
        ]
        compiled = compile_document(_doc(parent), index)
        router = Router(compiled.artifact["program"])
        assert router.route("3003", None)[0] == "p"
        assert router.route("3004", None)[0] == "p"
        assert router.route("3001", None)[0] == "misc"

    def test_a_rule_without_conditions_takes_nothing_and_says_so(self, index):
        compiled = compile_document(_doc(_rule("empty", "New bin")), index)
        assert compiled.artifact["program"]["rules"] == []
        assert any(w["rule_id"] == "empty" for w in compiled.warnings)

    def test_rules_after_a_catch_all_are_flagged(self, index):
        compiled = compile_document(
            _doc(_rule("all", "Everything", ("year_from", "gte", 0), match_mode="any"), _rule("late", "Late", ("color_id", "eq", 4))),
            index,
        )
        # year_from is unknown for these parts, so nothing is caught; use a real catch-all
        compiled = compile_document(
            _doc(_rule("all", "Every color", ("color_id", "neq", 999)), _rule("late", "Late", ("color_id", "eq", 4))),
            index,
        )
        assert any(w["rule_id"] == "late" and "Nothing reaches" in w["message"] for w in compiled.warnings)

    def test_stats_add_up(self, index):
        compiled = compile_document(_doc(_rule("r1", "Bricks", ("bl_category_id", "eq", 5))), index)
        stats = compiled.stats
        assert stats["matched"] + stats["unmatched"] == stats["total_parts"]
        assert stats["matched"] == 3


class TestFallback:
    def test_bricklink_categories(self, index):
        compiled = compile_document(_doc(fallback={"bricklink_categories": True}), index)
        router = Router(compiled.artifact["program"])
        assert router.route("3001", "5") == ("bl_5", "fallback")
        assert router.route("3068bpb001", None) == ("bl_39", "fallback")
        assert router.route("no-bl-part", None) == ("misc", "default")
        assert compiled.artifact["categories"]["bl_5"]["name"] == "Brick"
        assert compiled.requires == []
        _assert_legacy_routes_like_program(compiled, index)

    def test_by_color_needs_a_sorter_that_can(self, index):
        compiled = compile_document(_doc(_rule("tiles", "Tiles", ("bl_category_id", "eq", 37)), fallback={"by_color": True}), index)
        router = Router(compiled.artifact["program"])
        assert router.route("3068b", "5")[0] == "tiles"
        assert router.route("3001", "5") == ("color_5", "fallback")
        assert router.route("3001", None) == ("misc", "default")
        assert compiled.requires == [FEATURE_COLOR_FALLBACK]
        assert compiled.artifact["categories"]["color_5"]["name"] == "Red"


class TestKits:
    def _inventory(self, *lines):
        return {
            "rule_id": "kit",
            "set_num": "kit:1",
            "name": "Order 42",
            "set_source": "custom",
            "parts": [
                {"part_num": part, "rb_part_num": part, "color_id": color, "quantity": qty, "part_name": part, "img_url": None}
                for part, color, qty in lines
            ],
        }

    def test_a_kit_takes_its_parts_in_its_colors(self, index):
        doc = _doc({"id": "kit", "name": "Order 42", "rule_type": "kit", "kit_id": "k1"}, _rule("bricks", "Bricks", ("bl_category_id", "eq", 5)))
        compiled = compile_document(doc, index, {"kit": self._inventory(("3001", 5, 2), ("3020", -1, 1))})
        router = Router(compiled.artifact["program"])
        assert router.route("3001", "5") == ("kit", "kit")
        assert router.route("3001", "7") == ("bricks", "rule")
        assert router.route("3020", "7") == ("kit", "kit")
        assert compiled.artifact["set_inventories"]["kit"]["parts"][0]["quantity"] == 2
        assert compiled.artifact["profile_type"] == "set"
        assert any("no color" in w["message"] for w in compiled.warnings)

    def test_a_full_kit_passes_pieces_to_the_next_rule(self, index):
        doc = _doc({"id": "kit", "name": "Order 42", "rule_type": "kit"}, _rule("bricks", "Bricks", ("bl_category_id", "eq", 5)))
        compiled = compile_document(doc, index, {"kit": self._inventory(("3001", 5, 2))})
        router = Router(compiled.artifact["program"])
        assert router.route("3001", "5", kit_is_full=lambda category, part, color: True) == ("bricks", "rule")

    def test_a_kit_below_a_rule_that_takes_its_parts_is_flagged(self, index):
        doc = _doc(_rule("bricks", "Bricks", ("bl_category_id", "eq", 5)), {"id": "kit", "name": "Order 42", "rule_type": "kit"})
        compiled = compile_document(doc, index, {"kit": self._inventory(("3001", 5, 2))})
        assert any(w["rule_id"] == "kit" and "rules above it" in w["message"] for w in compiled.warnings)

    def test_a_kit_without_parts_is_flagged(self, index):
        compiled = compile_document(_doc({"id": "kit", "name": "Empty", "rule_type": "kit"}), index, {})
        assert compiled.artifact["program"]["rules"] == []
        assert any("no parts" in w["message"] for w in compiled.warnings)


class TestLegacyMap:
    DOCS = [
        _doc(_rule("bricks", "Bricks", ("bl_category_id", "eq", 5))),
        _doc(
            _rule("clear", "Transparent", ("color_id", "in", [47])),
            _rule("bricks", "Bricks", ("category_id", "eq", 11)),
            _rule("plates", "Plates", ("name", "contains", "plate")),
        ),
        _doc(
            _rule("red-bricks", "Red bricks", ("bl_category_id", "eq", 5), ("color_id", "eq", 4)),
            _rule("bricks", "Bricks", ("bl_category_id", "eq", 5)),
            _rule("blue", "Blue things", ("color_id", "in", [1, 14])),
            fallback={"bricklink_categories": True},
        ),
        _doc(
            _rule("light", "Light", ("bl_catalog_weight", "lte", 0.5)),
            _rule("popular", "Popular", ("bl_price_qty", "gte", 3000)),
            fallback={"rebrickable_categories": True},
            default="leftovers",
        ),
    ]

    @pytest.mark.parametrize("document", DOCS)
    def test_the_flat_map_routes_like_the_program(self, index, document):
        _assert_legacy_routes_like_program(compile_document(document, index), index)

    @pytest.mark.parametrize("document", DOCS)
    def test_the_flat_map_routes_like_the_old_compiler(self, index, document):
        # The old compiler filed a part under its first BrickLink ID only; the
        # new one files every alias, so compare on the IDs both know.
        parts_data = _parts_data()
        old = _legacy_compile(document, parts_data)
        new = expand_legacy(compile_document(document, index).artifact, index)["part_to_category"]
        default = document["default_category_id"]
        for part, color in _every_piece(index):
            if part in ("3004old", "not-in-catalog"):
                continue
            color_key = color or "any_color"
            assert _lookup(new, default, part, color_key) == _lookup(old, default, part, color_key), (part, color)

    def test_parts_left_to_the_default_are_left_out(self, index):
        legacy = expand_legacy(compile_document(_doc(_rule("bricks", "Bricks", ("bl_category_id", "eq", 5))), index).artifact, index)
        assert set(legacy["part_to_category"].values()) == {"bricks"}
        assert "program" not in legacy
        assert legacy["schema_version"] == 1


class TestRuleMatches:
    def test_most_sold_first(self, index):
        rules = [_rule("bricks", "Bricks", ("bl_category_id", "eq", 5))]
        result = rule_matches(rules, "bricks", index)
        assert [item["part_num"] for item in result["items"]] == ["3001", "3003", "3004"]
        assert result["total"] == 3
        assert result["colors"] is None

    def test_search_within_matches(self, index):
        rules = [_rule("bricks", "Bricks", ("bl_category_id", "eq", 5))]
        result = rule_matches(rules, "bricks", index, q="2 x 2")
        assert [item["part_num"] for item in result["items"]] == ["3003"]

    def test_a_child_is_matched_inside_its_parent(self, index):
        rules = [_rule("p", "Bricks", ("bl_category_id", "eq", 5), children=[_rule("c", "Small", ("name", "contains", "2 x 2"))])]
        assert rule_matches(rules, "c", index)["total"] == 1
        # on its own, "2 x 2" also takes the 2 x 2 plate and tiles
        assert rule_matches(rules, "c", index, standalone=True)["total"] == 4

    def test_a_color_limit_counts_the_parts_known_in_those_colors_like_the_bin(self):
        index = CatalogIndex(_parts_data())
        # BrickLink's red is 5; only two of the three bricks are known in it
        index.set_known_colors([("3001", 5), ("3003", 5), ("3020", 5)])
        rules = [_rule("red", "Red bricks", ("bl_category_id", "eq", 5), ("color_id", "eq", 4))]
        result = rule_matches(rules, "red", index)
        assert [item["part_num"] for item in result["items"]] == ["3001", "3003"]
        assert compile_document(_doc(*rules), index).artifact["categories"]["red"]["part_count"] == result["total"]


class TestWarningCodes:
    def test_a_rule_that_matches_no_part_says_so(self, index):
        compiled = compile_document(_doc(_rule("none", "Nothing", ("name", "contains", "no such part"))), index)
        assert [(w["code"], w["message"]) for w in compiled.warnings if w["rule_id"] == "none"] == [
            ("matches_nothing", "No part in the catalog matches this rule.")
        ]

    def test_a_rule_whose_parts_all_go_above_it_says_that_instead(self, index):
        compiled = compile_document(
            _doc(
                _rule("bricks", "Bricks", ("bl_category_id", "eq", 5)),
                _rule("small", "Small bricks", ("bl_category_id", "eq", 5), ("name", "contains", "2 x 2")),
            ),
            index,
        )
        assert [w["code"] for w in compiled.warnings if w["rule_id"] == "small"] == ["taken_above"]

    def test_an_unfinished_rule_is_told_apart_by_its_code(self, index):
        compiled = compile_document(_doc(_rule("empty", "Empty"), _rule("half", "Half", ("bl_category_id", "in", []))), index)
        codes = {w["rule_id"]: w["code"] for w in compiled.warnings}
        assert codes == {"empty": "no_conditions", "half": "condition_incomplete"}


class TestYesNoFields:
    @staticmethod
    def _index():
        data = _parts_data()
        data.parts["3004"]["bricklink_data"]["items"]["3004"]["catalog"]["data"]["is_obsolete"] = True
        data.parts["3003"]["bricklink_data"]["items"]["3003"]["catalog"]["data"]["is_obsolete"] = False
        return CatalogIndex(data)

    @pytest.mark.parametrize("value", [True, 1, "1", "yes", "true"])
    def test_yes_is_read_however_it_is_written(self, value):
        compiled = compile_document(_doc(_rule("old", "Obsolete", ("bl_catalog_is_obsolete", "eq", value))), self._index())
        category = compiled.artifact["categories"]["old"]
        assert category["part_count"] == 1
        assert category["conditions"]["items"][0]["values"] == [{"value": 1, "label": "Yes"}]

    def test_no_takes_the_parts_known_not_to_be(self):
        compiled = compile_document(_doc(_rule("current", "Current", ("bl_catalog_is_obsolete", "eq", False))), self._index())
        assert [s["part_num"] for s in compiled.artifact["categories"]["current"]["samples"]] == ["3003"]

    def test_anything_else_is_a_problem(self, index):
        compiled = compile_document(_doc(_rule("old", "Obsolete", ("bl_catalog_is_obsolete", "eq", "maybe"))), index)
        assert any("is not true or false" in problem.message for problem in compiled.problems)


class TestDisplay:
    def test_conditions_are_named(self, index):
        compiled = compile_document(
            _doc(_rule("r1", "Decorated tiles", ("bl_category_id", "in", [39, 37]), ("color_id", "eq", 4))),
            index,
        )
        conditions = compiled.artifact["categories"]["r1"]["conditions"]["items"]
        assert conditions[0]["field_label"] == "BrickLink category"
        assert conditions[0]["op_label"] == "is one of"
        assert [value["label"] for value in conditions[0]["values"]] == ["Tile, Decorated", "Tile"]
        assert conditions[1]["values"][0] == {"value": 4, "label": "Red", "rgb": "C91A09", "bricklink_id": "5"}

    def test_a_rule_without_a_picture_shows_its_best_known_part(self, index):
        compiled = compile_document(_doc(_rule("r1", "Bricks", ("bl_category_id", "eq", 5))), index)
        category = compiled.artifact["categories"]["r1"]
        assert category["image_url"] == "https://img.example/3001.png"
        assert category["image_source"] == "part"

    def test_a_rule_picture_wins(self, index):
        rule = _rule("r1", "Bricks", ("bl_category_id", "eq", 5), image_url="https://hive.example/rule.png")
        category = compile_document(_doc(rule), index).artifact["categories"]["r1"]
        assert category["image_url"] == "https://hive.example/rule.png"
        assert category["image_source"] == "rule"


class TestKnownColors:
    def test_a_color_bin_counts_the_parts_known_in_its_colors(self):
        index = CatalogIndex(_parts_data())
        index.set_known_colors([("3001", 12), ("3068b", 12), ("3001", 5)])
        compiled = compile_document(_doc(_rule("clear", "Transparent", ("color_id", "in", [47]))), index)
        clear = compiled.artifact["categories"]["clear"]
        assert clear["part_count"] == 2
        assert clear["any_part"] is True
        assert [sample["part_num"] for sample in clear["samples"]] == ["3001", "3068b"]
        # what the sorter runs is unchanged: any part in the color
        assert Router(compiled.artifact["program"]).route("3003", "12")[0] == "clear"

    def test_without_color_data_every_part_counts(self, index):
        index.set_known_colors([])
        compiled = compile_document(_doc(_rule("clear", "Transparent", ("color_id", "in", [47]))), index)
        assert compiled.artifact["categories"]["clear"]["part_count"] == index.size


def test_a_condition_with_nothing_chosen_shows_no_values(index):
    compiled = compile_document(_doc(_rule("r1", "Unfinished", ("bl_category_id", "in", []))), index)
    items = compiled.artifact["categories"]["r1"]["conditions"]["items"]
    assert items[0]["invalid"] is True
    assert items[0]["values"] == []


def test_the_catalog_service_is_built_once_when_asked_for_together(monkeypatch):
    import threading
    import time

    import app.services.profile_catalog as profile_catalog

    built = []

    class Slow:
        def __init__(self):
            built.append(1)
            time.sleep(0.05)

    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(profile_catalog, "ProfileCatalogService", Slow)
    threads = [threading.Thread(target=profile_catalog.get_profile_catalog_service) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(built) == 1


def test_a_bin_limited_to_colors_shows_its_parts_in_them(index):
    compiled = compile_document(
        _doc(_rule("red", "Red bricks", ("bl_category_id", "eq", 5), ("color_id", "in", [4, 1]))), index
    )
    sample = compiled.artifact["categories"]["red"]["samples"][0]
    # the first color the rule names, rendered; the catalog's photo if there is no render
    assert sample["img_url"] == "https://cdn.rebrickable.com/media/parts/ldraw/4/3001.png"
    assert sample["fallback_img_url"] == "https://img.example/3001.png"
    assert sample["color_name"] == "Red"
    assert compiled.artifact["categories"]["red"]["image_fallback_url"] == "https://img.example/3001.png"
