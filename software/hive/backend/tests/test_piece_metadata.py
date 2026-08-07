from __future__ import annotations

from pathlib import Path

import pytest

from app.services.profile_engine import db as profile_db


CATEGORIES = [{"id": 1, "name": "Bricks"}]
PARTS = [
    {"part_num": "3001", "name": "Brick 2 x 4", "part_cat_id": 1, "external_ids": {"BrickLink": ["3001"]}},
]


def _insert_bl_item(conn, item_no, part_num, name, **kw):
    conn.execute(
        "INSERT INTO bricklink_items (item_no, part_num, name, category_id, weight, "
        "year_released, is_obsolete, dim_x_studs, dim_y_studs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_no, part_num, name, kw.get("category_id"), kw.get("weight"),
            kw.get("year_released"), kw.get("is_obsolete", 0),
            kw.get("dim_x_studs"), kw.get("dim_y_studs"),
        ),
    )


def _insert_price(conn, item_no, bl_color_id, rb_color_id, **cols):
    fields = ["item_no", "bl_color_id", "rb_color_id"]
    values = [item_no, bl_color_id, rb_color_id]
    for k, v in cols.items():
        fields.append(k)
        values.append(v)
    placeholders = ", ".join(["?"] * len(values))
    conn.execute(
        f"INSERT INTO price_guides ({', '.join(fields)}) VALUES ({placeholders})", values
    )


@pytest.fixture
def catalog(tmp_path: Path):
    conn = profile_db.initDb(str(tmp_path / "parts.db"))
    profile_db.upsertCategories(conn, CATEGORIES)
    profile_db.upsertParts(conn, PARTS)
    # upsertParts already derives part_bricklink_ids from external_ids; ensure the
    # primary flag is set.
    conn.execute(
        "INSERT OR REPLACE INTO part_bricklink_ids (part_num, item_no, is_primary) VALUES (?, ?, ?)",
        ("3001", "3001", 1),
    )
    _insert_bl_item(conn, "3001", "3001", "Brick 2 x 4", weight=2.5, dim_x_studs=4, dim_y_studs=2, year_released=1979)
    # A printed variant with a BrickLink item but no price of its own.
    _insert_bl_item(conn, "3001pb01", "3001", "Brick 2 x 4 with Print")

    # Black (bl 11) — cheaper listings but the preferred ord_new sold average.
    _insert_price(conn, "3001", 11, 0, ord_new_wavg=1.50, inv_new_avg=2.00, inv_new_qty=100, inv_new_lots=3)
    # Red (bl 5) — the most-liquid color (highest qty), used when no color given.
    _insert_price(conn, "3001", 5, 4, ord_new_wavg=1.20, inv_new_qty=500, inv_new_lots=9)
    conn.commit()
    yield conn
    conn.close()


class TestPieceMetadata:
    def test_flattened_shape_and_color_specific_price(self, catalog):
        md = profile_db.pieceMetadata(catalog, "3001", 11)
        assert md is not None
        assert md["source"] == "hive"
        assert md["part_num"] == "3001"
        assert md["name"] == "Brick 2 x 4"
        assert md["category"] == "Bricks"
        assert md["price_currency"] == "USD"
        assert md["bricklink"]["item_no"] == "3001"
        assert md["bricklink"]["dim_x_studs"] == 4
        assert "dimensions" in md and isinstance(md["dimensions"], dict)

    def test_moving_avg_prefers_sold_new_over_listings(self, catalog):
        # ord_new wavg (1.50) beats inv_new avg (2.00) despite the higher number.
        md = profile_db.pieceMetadata(catalog, "3001", 11)
        assert md["moving_avg_price"] == 1.50
        assert md["price_color_specific"] is True

    def test_no_color_picks_most_liquid(self, catalog):
        md = profile_db.pieceMetadata(catalog, "3001", None)
        assert md["moving_avg_price"] == 1.20  # Red, highest qty
        assert md["price_color_specific"] is False

    def test_base_mold_price_fallback_for_printed_part(self, catalog):
        md = profile_db.pieceMetadata(catalog, "3001pb01", 11)
        assert md is not None
        assert md["price_from_base_mold"] == "3001"
        assert md["moving_avg_price"] == 1.50
        assert md["price_color_specific"] is False  # base-mold price isn't color-specific

    def test_unknown_part_returns_none(self, catalog):
        assert profile_db.pieceMetadata(catalog, "zzzznotapart", None) is None

    def test_batch_moving_avg(self, catalog):
        rows = profile_db.batchPieceMovingAvg(
            catalog,
            [
                {"part_num": "3001", "color_id": 11},
                {"part_num": "3001", "color_id": None},
                {"part_num": "zzzznotapart", "color_id": None},
            ],
        )
        assert [r["moving_avg_price"] for r in rows] == [1.50, 1.20, None]
