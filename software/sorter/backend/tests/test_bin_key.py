import unittest

import bin_key
from bin_key import binKey, parseComponents, parseKey


class ParseComponentsTests(unittest.TestCase):
    def test_orders_components_and_drops_repeats(self) -> None:
        self.assertEqual(parseComponents(["color", "category", "color"]), ("category", "color"))

    def test_accepts_a_comma_separated_string(self) -> None:
        self.assertEqual(parseComponents("part, color"), ("part", "color"))

    def test_rejects_unknown_or_empty(self) -> None:
        self.assertIsNone(parseComponents(["size"]))
        self.assertIsNone(parseComponents([]))
        self.assertIsNone(parseComponents(None))

    def test_normalize_falls_back_to_category(self) -> None:
        self.assertEqual(bin_key.normalizeComponents("nonsense"), ("category",))


class BinKeyTests(unittest.TestCase):
    def test_category_only_is_the_plain_category_id(self) -> None:
        self.assertEqual(binKey(("category",), "bricks", "3001", "5"), "bricks")

    def test_part_color_and_mixes(self) -> None:
        self.assertEqual(binKey(("part",), "bricks", "3001", "5"), "part:3001")
        self.assertEqual(binKey(("color",), "bricks", "3001", "5"), "color:5")
        self.assertEqual(binKey(("category", "color"), "bricks", "3001", "5"), "category:bricks|color:5")
        self.assertEqual(binKey(("color", "part"), "bricks", "3001", "5"), "part:3001|color:5")

    def test_missing_color_is_any_color(self) -> None:
        self.assertEqual(binKey(("color",), "bricks", "3001", None), "color:any_color")

    def test_misc_stays_misc(self) -> None:
        self.assertEqual(binKey(("category", "color"), "misc", "3001", "5"), "misc")
        self.assertEqual(binKey(("part",), "bricks", None, "5"), "misc")
        self.assertEqual(binKey(("color",), "misc", "3001", "5"), "color:5")


class SharedConstantsTests(unittest.TestCase):
    def test_constants_match_the_sorting_profile(self) -> None:
        # bin_key repeats these two (importing sorting_profile would be circular).
        import sorting_profile

        self.assertEqual(bin_key.MISC_CATEGORY, sorting_profile.MISC_CATEGORY)
        self.assertEqual(bin_key.ANY_COLOR, sorting_profile.ANY_COLOR)


class ParseKeyTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        key = binKey(("category", "part", "color"), "bricks", "3001", "5")
        self.assertEqual(parseKey(key), {"category": "bricks", "part": "3001", "color": "5"})

    def test_plain_category(self) -> None:
        self.assertEqual(parseKey("bricks"), {"category": "bricks"})


if __name__ == "__main__":
    unittest.main()
