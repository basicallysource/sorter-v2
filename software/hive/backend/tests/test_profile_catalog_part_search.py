from __future__ import annotations

from pathlib import Path

import pytest

from app.services.profile_engine import db as profile_db


CATEGORIES = [
    {"id": 1, "name": "Bricks"},
    {"id": 2, "name": "Plates"},
    {"id": 3, "name": "Bricks Sloped"},
    {"id": 4, "name": "Technic Axles"},
]

PARTS = [
    {"part_num": "3001", "name": "Brick 2 x 4", "part_cat_id": 1, "external_ids": {"BrickLink": ["3001"]}},
    {"part_num": "3001c", "name": "Brick 2 x 4 without Bottom Tubes", "part_cat_id": 1},
    {"part_num": "3001pr0001", "name": "Brick 2 x 4 with Smile Print", "part_cat_id": 1},
    {"part_num": "3004", "name": "Brick 1 x 2", "part_cat_id": 1, "external_ids": {"BrickLink": ["3004"]}},
    {"part_num": "30041", "name": "Plate Special 6 x 8 Trap Door Frame", "part_cat_id": 2},
    {"part_num": "3023", "name": "Plate 1 x 2", "part_cat_id": 2, "external_ids": {"BrickLink": ["3023"]}},
    {"part_num": "3020", "name": "Plate 2 x 4", "part_cat_id": 2},
    {"part_num": "3040b", "name": "Slope 45° 2 x 1 with Bottom Pin", "part_cat_id": 3},
    {"part_num": "3665", "name": "Slope Inverted 45° 2 x 1", "part_cat_id": 3},
    {"part_num": "4519", "name": "Technic Axle 3", "part_cat_id": 4},
    {"part_num": "50450", "name": "Technic Axle 32", "part_cat_id": 4},
    {"part_num": "dupupn0025", "name": "Duplo Brick 2 x 4", "part_cat_id": 1},
]

# 3001 is stocked in far more colors than the parts it competes with, which is
# what should float it above them when neither is an exact name match.
COLOR_COUNTS = {"3001": 60, "3004": 55, "3023": 50}


@pytest.fixture
def catalog(tmp_path: Path):
    conn = profile_db.initDb(str(tmp_path / "parts.db"))
    profile_db.upsertCategories(conn, CATEGORIES)
    profile_db.upsertParts(conn, PARTS)
    for item_no, count in COLOR_COUNTS.items():
        conn.executemany(
            "INSERT OR REPLACE INTO bricklink_item_colors (item_no, bl_color_id) VALUES (?, ?)",
            [(item_no, color_id) for color_id in range(count)],
        )
    conn.commit()
    profile_db.rebuildPartSearch(conn)
    yield conn
    conn.close()


def partNums(conn, query, **kwargs):
    results, _ = profile_db.searchParts(conn, query, **kwargs)
    return [r["part_num"] for r in results]


class TestPartSearch:
    def test_compact_dimensions_match_spaced_catalog_names(self, catalog):
        assert partNums(catalog, "brick 2x4")[0] == "3001"

    def test_word_order_does_not_matter(self, catalog):
        assert partNums(catalog, "2x4 brick")[0] == "3001"
        assert partNums(catalog, "brick 2x4")[0] == "3001"

    def test_dimensions_match_either_way_round(self, catalog):
        # The catalog writes this footprint as "2 x 1" for slopes only.
        assert "3040b" in partNums(catalog, "slope 1x2")
        assert "3040b" in partNums(catalog, "slope 2x1")

    def test_exact_part_number_ranks_first(self, catalog):
        assert partNums(catalog, "3004")[0] == "3004"

    def test_partial_word_still_matches(self, catalog):
        assert partNums(catalog, "bric 2x4")[0] == "3001"

    def test_printed_variants_rank_below_the_plain_mold(self, catalog):
        found = partNums(catalog, "brick 2x4")
        assert found.index("3001") < found.index("3001pr0001")

    def test_bare_number_does_not_prefix_match_other_numbers(self, catalog):
        found = partNums(catalog, "technic axle 3")
        assert found[0] == "4519"
        assert "50450" not in found

    def test_off_system_lines_rank_below_system_parts(self, catalog):
        found = partNums(catalog, "brick 2x4")
        assert found.index("3001") < found.index("dupupn0025")

    def test_every_token_must_match(self, catalog):
        assert partNums(catalog, "plate 2x4") == ["3020"]

    def test_no_match_returns_nothing(self, catalog):
        assert partNums(catalog, "zzzznotapart") == []

    def test_blank_query_without_category_returns_nothing(self, catalog):
        results, total = profile_db.searchParts(catalog, "   ")
        assert results == []
        assert total == 0

    def test_category_browse_without_a_query(self, catalog):
        found = partNums(catalog, "", cat_filter=3)
        assert sorted(found) == ["3040b", "3665"]

    def test_category_filter_narrows_a_query(self, catalog):
        assert partNums(catalog, "2x4", cat_filter=2) == ["3020"]

    def test_total_counts_every_match_not_just_the_page(self, catalog):
        results, total = profile_db.searchParts(catalog, "brick 2x4", limit=1)
        assert len(results) == 1
        assert total > 1

    def test_index_refreshes_when_the_catalog_reloads(self, catalog):
        profile_db.upsertParts(catalog, [{"part_num": "99999", "name": "Wedge Plate 2 x 4", "part_cat_id": 2}])
        catalog.commit()
        profile_db.reloadPartsData(catalog, profile_db.PartsData())
        assert partNums(catalog, "wedge plate 2x4") == ["99999"]
