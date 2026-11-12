import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import machine_toml
import toml_config
from sorting_profile import MISC_CATEGORY, ANY_COLOR, applyDynamicColorSplit, base_part_ids


class FakeProfile:
    """The slice of a sorting profile the split needs: a routing answer plus,
    optionally, set inventories. Routes variants to their base part like the
    real router does."""

    def __init__(self, answers: dict, default: str = "misc", set_inventories: dict | None = None):
        # answers: {part_id: {color_id_or_any_color: category}}
        self.answers = answers
        self.default = default
        self.is_set_based = bool(set_inventories)
        self.set_inventories = set_inventories or {}

    def getCategoryIdForPart(self, part_id: str, color_id: str = ANY_COLOR) -> str:
        for part in (part_id, *base_part_ids(part_id)):
            by_color = self.answers.get(part) or {}
            for key in (color_id, ANY_COLOR):
                if key in by_color:
                    return by_color[key]
        return self.default


class _MachineTomlIsolated(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.path = Path(tmpdir.name) / "machine.toml"
        self.path.write_text("", encoding="utf-8")
        env = patch.dict(os.environ, {machine_toml.ENV_VAR: str(self.path)})
        env.start()
        self.addCleanup(env.stop)


class BinAssignmentConfigTests(_MachineTomlIsolated):
    def test_defaults(self) -> None:
        config = toml_config.getBinAssignmentConfig()
        self.assertEqual(
            {"allow_multiple_categories_per_bin": False, "dynamic_color_split": False}, config
        )

    def test_round_trip_both_flags_independently(self) -> None:
        toml_config.setBinAssignmentConfig({"allow_multiple_categories_per_bin": True})
        config = toml_config.getBinAssignmentConfig()
        self.assertTrue(config["allow_multiple_categories_per_bin"])
        self.assertFalse(config["dynamic_color_split"])

        toml_config.setBinAssignmentConfig({"dynamic_color_split": True})
        config = toml_config.getBinAssignmentConfig()
        self.assertTrue(config["allow_multiple_categories_per_bin"])
        self.assertTrue(config["dynamic_color_split"])

        toml_config.setBinAssignmentConfig({"allow_multiple_categories_per_bin": False})
        config = toml_config.getBinAssignmentConfig()
        self.assertFalse(config["allow_multiple_categories_per_bin"])
        self.assertTrue(config["dynamic_color_split"])
        # The written file only carries the [bins] table.
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("[bins]", text)
        self.assertIn("dynamic_color_split = true", text)


class DynamicColorSplitTests(unittest.TestCase):
    def test_plain_by_id_category_splits(self) -> None:
        profile = FakeProfile({"3001": {ANY_COLOR: "3001"}}, default="misc")
        self.assertEqual(
            "3001:15",
            applyDynamicColorSplit(profile, "3001", "3001", "15", enabled=True),
        )

    def test_disabled_leaves_everything(self) -> None:
        profile = FakeProfile({"3001": {ANY_COLOR: "3001"}})
        self.assertEqual(
            "3001", applyDynamicColorSplit(profile, "3001", "3001", "15", enabled=False)
        )

    def test_misc_never_splits(self) -> None:
        profile = FakeProfile({}, default=MISC_CATEGORY)
        self.assertEqual(
            MISC_CATEGORY,
            applyDynamicColorSplit(profile, MISC_CATEGORY, "3001", "15", enabled=True),
        )

    def test_pieces_without_a_color_pass_through(self) -> None:
        profile = FakeProfile({"3001": {ANY_COLOR: "3001"}})
        for color in (None, "", ANY_COLOR, "  "):
            self.assertEqual(
                "3001",
                applyDynamicColorSplit(profile, "3001", "3001", color, enabled=True),
                f"color {color!r}",
            )

    def test_no_part_id_passes_through(self) -> None:
        profile = FakeProfile({"3001": {ANY_COLOR: "3001"}})
        self.assertEqual(
            "3001", applyDynamicColorSplit(profile, "3001", None, "15", enabled=True)
        )

    def test_a_color_specific_profile_answer_wins(self) -> None:
        # The profile itself routes 3003 red separately ("red-bricks"); the
        # split must respect that finer answer, for the red category and for
        # the plain one the profile already handles.
        profile = FakeProfile(
            {
                "3003": {ANY_COLOR: "bricks", "5": "red-bricks"},
                "3001": {ANY_COLOR: "bricks"},
            }
        )
        self.assertEqual(
            "red-bricks",
            applyDynamicColorSplit(profile, "red-bricks", "3003", "5", enabled=True),
        )
        # An unlisted color of 3003 still routes into the plain category, and
        # the split applies there.
        self.assertEqual(
            "bricks:7", applyDynamicColorSplit(profile, "bricks", "3003", "7", enabled=True)
        )

    def test_a_by_color_fallback_profile_never_splits(self) -> None:
        # fallback_by color answers "color_5" for every part; the any-color
        # answer differs, so the guard keeps it intact.
        profile = FakeProfile({"3001": {ANY_COLOR: "misc"}}, default="color_5")
        self.assertEqual(
            "color_5",
            applyDynamicColorSplit(profile, "color_5", "3001", "5", enabled=True),
        )

    def test_kit_categories_never_split(self) -> None:
        profile = FakeProfile(
            {"3001": {ANY_COLOR: "set_60393"}}, set_inventories={"set_60393": {"set_num": "60393"}}
        )
        self.assertEqual(
            "set_60393",
            applyDynamicColorSplit(profile, "set_60393", "3001", "15", enabled=True),
        )

    def test_variant_parts_split_under_their_base_category(self) -> None:
        # 3001pb028 routed through base_part_ids lands on 3001's category and
        # splits like any other piece of it.
        profile = FakeProfile({"3001": {ANY_COLOR: "3001"}})
        self.assertEqual(
            "3001:5",
            applyDynamicColorSplit(profile, "3001", "3001pb028", "5", enabled=True),
        )


if __name__ == "__main__":
    unittest.main()
