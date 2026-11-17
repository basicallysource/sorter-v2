"""Part sizes measured from LDraw, and found by the number a sorter sends.

A sorter predicts BrickLink numbers (3040, 4073), while the catalog's parts are
Rebrickable's (3040b, 6141). The geometry pass gives every BrickLink number a
row of its own, from the parts it maps to, so the lookup by that number finds
a size instead of none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.profile_engine import db as profile_db
from app.services.profile_engine import ldraw_geometry as lg


def _box(x: float, y: float, z: float) -> str:
    # Two triangles at opposite corners are enough to span the bounding box.
    return (
        f"3 16 0 0 0 {x} 0 0 0 {y} 0\n"
        f"3 16 {x} {y} {z} 0 {y} {z} {x} 0 {z}\n"
    )


def _write(root: Path, rel: str, body: str) -> None:
    path = root / "ldraw" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


@pytest.fixture
def library(tmp_path: Path) -> str:
    # 1 LDU = 0.4 mm: 40 x 28 x 20 LDU is 16 x 11.2 x 8 mm, a 2 x 1 slope.
    _write(tmp_path, "p/slopebox.dat", "0 a primitive\n" + _box(40, 28, 20))
    _write(tmp_path, "parts/3040b.dat", "0 Slope 45 2 x 1\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 slopebox.dat\n")
    _write(tmp_path, "parts/4287a.dat", "0 Inverted slope, shorter\n" + _box(55, 28, 20))
    _write(tmp_path, "parts/4287c.dat", "0 Inverted slope\n" + _box(60, 28, 20))
    _write(tmp_path, "parts/6141.dat", "0 Plate round 1 x 1\n" + _box(20, 12, 20))
    _write(tmp_path, "parts/3069.dat", "0 ~Moved to 3069b\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 3069b.dat\n")
    _write(tmp_path, "parts/3069b.dat", "0 Tile 1 x 2\n" + _box(40, 8, 20))
    return str(tmp_path / "ldraw")


@pytest.fixture
def catalog(tmp_path: Path):
    conn = profile_db.initDb(str(tmp_path / "parts.db"))
    profile_db.upsertCategories(conn, [{"id": 1, "name": "Bricks"}])
    profile_db.upsertParts(conn, [
        {"part_num": "3040b", "name": "Slope 45 2 x 1", "part_cat_id": 1,
         "external_ids": {"BrickLink": ["3040"], "LDraw": ["3040b"]}},
        {"part_num": "4287a", "name": "Slope Inverted 3 x 1", "part_cat_id": 1,
         "external_ids": {"BrickLink": ["4287"]}},
        {"part_num": "4287c", "name": "Slope Inverted 3 x 1", "part_cat_id": 1,
         "external_ids": {"BrickLink": ["4287"]}},
        {"part_num": "6141", "name": "Plate Round 1 x 1", "part_cat_id": 1,
         "external_ids": {"BrickLink": ["4073"], "LDraw": ["4073", "6141"]}},
        {"part_num": "99999", "name": "A part LDraw does not have", "part_cat_id": 1,
         "external_ids": {"BrickLink": ["99999old"]}},
        {"part_num": "3069b", "name": "Tile 1 x 2", "part_cat_id": 1,
         "external_ids": {"BrickLink": ["3069"]}},
    ])
    for item_no, part_num, name, dims in [
        ("3040", "3040b", "Slope 45 2 x 1", (2, 1)),
        ("4287", "4287c", "Slope, Inverted 33 3 x 1", (3, 1)),
        ("4073", "6141", "Plate, Round 1 x 1", (1, 1)),
        ("99999old", "99999", "Some cloth", (4, 3)),
        ("3069", "3069b", "Tile 1 x 2", (1, 2)),
    ]:
        conn.execute(
            "INSERT INTO bricklink_items (item_no, part_num, name, dim_x_studs, dim_y_studs) "
            "VALUES (?, ?, ?, ?, ?)",
            (item_no, part_num, name, dims[0], dims[1]),
        )
    conn.commit()
    yield conn
    conn.close()


def _measure(catalog, library):
    return lg.computeAllGeometry(catalog, library, profile_db.upsertPartGeometry, "2026-01-01T00:00:00Z")


def test_a_bricklink_number_gets_the_size_of_its_rebrickable_part(catalog, library):
    result = _measure(catalog, library)
    assert result["stopped"] is False
    assert result["bricklink"] == 4  # 3040, 4287, 4073, 3069; 99999old has no model

    dims = profile_db.pieceMetadata(catalog, "3040", None)["dimensions"]
    assert (dims["bbox_x_mm"], dims["bbox_y_mm"], dims["bbox_z_mm"]) == (16.0, 11.2, 8.0)
    assert dims["source"] == "ldraw_bricklink"
    assert dims["confidence"] == "exact"
    assert dims["physical_parent_part_num"] == "3040b"
    # The Rebrickable number itself is unchanged.
    assert profile_db.resolvePartDimensions(catalog, "3040b")["source"] == "ldraw_direct"

    dims = profile_db.resolvePartDimensions(catalog, "4073")
    assert dims["physical_parent_part_num"] == "6141"
    assert dims["bbox_x_mm"] == 8.0


def test_a_number_for_several_parts_takes_the_largest(catalog, library):
    _measure(catalog, library)
    dims = profile_db.resolvePartDimensions(catalog, "4287")
    assert dims["bbox_x_mm"] == 24.0  # 4287c's 60 LDU, not 4287a's 55
    assert dims["physical_parent_part_num"] == "4287c"


def test_a_bricklink_number_without_a_model_still_has_its_footprint(catalog, library):
    _measure(catalog, library)
    dims = profile_db.resolvePartDimensions(catalog, "99999old")
    assert dims["source"] == "studs_footprint"
    assert (dims["bbox_x_mm"], dims["bbox_y_mm"], dims["bbox_z_mm"]) == (32.0, 24.0, None)


def test_the_admin_count_is_of_rebrickable_parts(catalog, library):
    _measure(catalog, library)
    overview = profile_db.adminCatalogOverview(catalog)
    assert overview["coverage"]["parts_with_ldraw_geometry"] == 5  # all but 99999


def test_an_unknown_number_is_still_unknown(catalog, library):
    _measure(catalog, library)
    assert profile_db.pieceMetadata(catalog, "nosuchpart", None) is None
