"""The categories, colors and parts syncs import Rebrickable's CSV downloads.

What only Rebrickable's API gave (BrickLink IDs, years, pictures) stays on the
parts and colors that have it; a new part takes its years and a picture from
the sets it is in. A download that fails changes nothing and fails the sync."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
import requests

from app.config import settings
from app.services import profile_catalog, rebrickable_downloads
from app.services.profile_engine import db as profile_db

DOWNLOADS = {
    "part_categories": """id,name
11,Bricks
14,Plates
99,Something New
""",
    "parts": """part_num,name,part_cat_id,part_material
3001,Brick 2 x 4,11,Plastic
3020,Plate 2 x 4,14,Plastic
3062,"Brick, Round 1 x 1",11,Plastic
""",
    "colors": """id,name,rgb,is_trans,num_parts,num_sets,y1,y2
4,Red,C91A09,False,10,5,1950,2026
47,Trans-Clear,FCFCFC,True,10,5,1960,2026
""",
    "themes": "id,name,parent_id\n1,Town,\n",
    "sets": """set_num,name,year,theme_id,num_parts,img_url
1-1,Old Set,1990,1,1,
2-1,New Set,2024,1,2,
""",
    "inventories": "id,version,set_num\n1,1,1-1\n2,1,2-1\n",
    "inventory_parts": """inventory_id,part_num,color_id,quantity,is_spare,img_url
1,3062,4,1,False,https://cdn.example/3062-4.jpg
2,3062,47,1,False,
2,3001,4,1,False,https://cdn.example/3001-4.jpg
""",
}


@pytest.fixture()
def failing(monkeypatch):
    """Names whose download fails."""
    names: set[str] = set()

    def download(name: str, directory: Path) -> Path:
        if name in names:
            raise requests.HTTPError(f"503 Server Error for url: {rebrickable_downloads.DOWNLOADS_URL}/{name}.csv.gz")
        path = directory / f"{name}.csv.gz"
        with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
            f.write(DOWNLOADS[name])
        return path

    monkeypatch.setattr(rebrickable_downloads, "download", download)
    return names


@pytest.fixture()
def catalog(monkeypatch, tmp_path, failing):
    """A catalog synced from the API before: two categories, Red with its
    BrickLink ID, 3001 with its BrickLink ID, years and picture, and 3020
    under the name it had then."""
    path = str(tmp_path / "parts.db")
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", path)
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", True)
    seed = profile_db.initDb(path)
    profile_db.upsertCategories(seed, [{"id": 11, "name": "Bricks", "part_count": 1}, {"id": 14, "name": "Plates", "part_count": 1}])
    profile_db.upsertColors(
        seed,
        [{"id": 4, "name": "Red", "rgb": "C91A09", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [5], "ext_descrs": [["Red"]]}}}],
    )
    profile_db.upsertParts(
        seed,
        [
            {
                "part_num": "3001",
                "name": "Brick 2 x 4",
                "part_cat_id": 11,
                "year_from": 1958,
                "year_to": 2026,
                "part_img_url": "https://cdn.example/3001.jpg",
                "external_ids": {"BrickLink": ["3001"]},
            },
            {"part_num": "3020", "name": "Plate 2 x 4 (old name)", "part_cat_id": 14},
        ],
    )
    seed.close()
    service = profile_catalog.ProfileCatalogService(runs_syncs=True)
    yield service
    service._conn.close()


def _sync(service, *sync_types: str) -> bool:
    for sync_type in sync_types:
        assert service.start_sync(sync_type)
        if not service.wait_for_sync(poll_s=0.01):
            return False
    return True


def test_the_catalog_syncs_import_the_downloads(catalog):
    assert _sync(catalog, "sets", "categories", "colors", "parts")
    data = catalog.parts_data

    assert {cid: (c["name"], c["part_count"]) for cid, c in data.categories.items()} == {
        11: ("Bricks", 2),
        14: ("Plates", 1),
        99: ("Something New", 0),
    }

    # Red keeps its BrickLink ID; the new color has none.
    assert data.rb_to_bl_color == {4: 5}
    assert data.colors[47]["name"] == "Trans-Clear" and data.colors[47]["is_trans"] is True

    # Known parts keep what the API gave them, and take the current name.
    assert data.parts["3001"]["external_ids"]["BrickLink"] == ["3001"]
    assert (data.parts["3001"]["year_from"], data.parts["3001"]["part_img_url"]) == (1958, "https://cdn.example/3001.jpg")
    assert data.parts["3020"]["name"] == "Plate 2 x 4"
    # A new part: its years and a picture from the sets it is in.
    new = data.parts["3062"]
    assert (new["name"], new["part_cat_id"], new["year_from"], new["year_to"]) == ("Brick, Round 1 x 1", 11, 1990, 2024)
    assert new["part_img_url"] == "https://cdn.example/3062-4.jpg"
    assert new["external_ids"] == {}
    assert data.api_total_parts == 3

    # Found by search, and nothing is stale now.
    assert [p["part_num"] for p in catalog.search_parts("round 1 x 1")["results"]] == ["3062"]
    assert catalog.get_auto_sync_plan() == []


def test_a_failed_download_changes_nothing(catalog, failing):
    failing.add("parts")
    assert _sync(catalog, "parts") is False
    assert profile_db.getCatalogSyncState(catalog._conn, "parts")["status"] == "error"
    assert catalog.get_last_synced_at("parts") is None
    assert set(catalog.parts_data.parts) == {"3001", "3020"}
    assert "parts" in catalog.get_auto_sync_plan()
