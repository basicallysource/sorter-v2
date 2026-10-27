"""LEGO sets from Rebrickable's CSV downloads: the "sets" catalog sync imports
them into parts.db, and set search, a set's inventory and a kit from a set
are served from those tables."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routers.kits as kits_router
import app.routers.profiles as profiles_router
import app.services.profile_display as profile_display
from app.config import settings
from app.services import profile_catalog, rebrickable_downloads
from app.services.profile_engine import db as profile_db

# The downloads as Rebrickable writes them: its own columns, in its own order
# (with columns Hive does not import), booleans spelled True and False.
DOWNLOADS = {
    "themes": """id,name,parent_id
50,Town,
104,Town Plan,50
372,Town Plan,365
158,Star Wars,
""",
    "sets": """set_num,name,year,theme_id,num_parts,img_url
10184-1,Town Plan,2008,104,4,https://cdn.example/sets/10184-1.jpg
810-2,Town Plan - Continental European,1961,372,756,
5007329-1,Town Plan,2022,104,0,
75192-1,Millennium Falcon,2017,158,7541,https://cdn.example/sets/75192-1.jpg
""",
    "inventories": """id,version,set_num
7,1,10184-1
8,2,10184-1
9,1,fig-000001
10,1,75192-1
""",
    "inventory_parts": """inventory_id,part_num,color_id,quantity,is_spare,img_url
7,3001,4,2,False,https://cdn.example/parts/3001-4.jpg
7,3001,4,1,False,
7,3020,1,1,False,
7,3020,1,1,True,
8,3001,4,99,False,
9,973c01,4,1,False,
10,3001,4,5,False,
""",
}


@pytest.fixture()
def downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve DOWNLOADS from files instead of Rebrickable's server."""
    fetched: list[str] = []

    def download(name: str, directory: Path) -> Path:
        fetched.append(name)
        path = directory / f"{name}.csv.gz"
        with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
            f.write(DOWNLOADS[name])
        return path

    monkeypatch.setattr(rebrickable_downloads, "download", download)
    return fetched


@pytest.fixture()
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, downloads: list[str]) -> profile_catalog.ProfileCatalogService:
    """A catalog service over a parts.db that knows two parts and two colors,
    with the sets synced into it."""
    path = str(tmp_path / "parts.db")
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", path)
    seed = profile_db.initDb(path)
    profile_db.upsertCategories(seed, [{"id": 11, "name": "Bricks"}])
    profile_db.upsertColors(seed, [{"id": 1, "name": "Blue", "rgb": "0055BF"}, {"id": 4, "name": "Red", "rgb": "C91A09"}])
    profile_db.upsertParts(
        seed,
        [
            {"part_num": "3001", "name": "Brick 2 x 4", "part_cat_id": 11},
            {"part_num": "3020", "name": "Plate 2 x 4", "part_cat_id": 11},
        ],
    )
    seed.close()
    service = profile_catalog.ProfileCatalogService(runs_syncs=True)
    assert service.start_sync("sets")
    assert service.wait_for_sync(poll_s=0.05), service.status()["error"]
    for module in (profiles_router, kits_router, profile_display):
        monkeypatch.setattr(module, "get_profile_catalog_service", lambda: service)
    yield service
    service._conn.close()


def test_the_sets_sync_imports_the_downloads(catalog, downloads) -> None:
    assert downloads == ["themes", "sets", "inventories", "inventory_parts"]
    sets = catalog.status()["types"]["sets"]
    assert sets["status"] == "completed"
    assert sets["cached_count"] == 4
    assert sets["last_synced_at"]
    # A new sync replaces the tables rather than adding to them.
    assert catalog.start_sync("sets")
    assert catalog.wait_for_sync(poll_s=0.05)
    assert catalog.set_count() == 4
    assert catalog.admin_overview()["tables"]["rebrickable_inventory_parts"] == 7


def test_set_search(catalog) -> None:
    # A theme's name finds the sets in it (both "Town Plan" themes), newest
    # first; a set with no parts is left out.
    assert [s["set_num"] for s in catalog.search_sets("town plan")] == ["10184-1", "810-2"]
    assert catalog.search_sets("town plan")[0] == {
        "set_num": "10184-1",
        "name": "Town Plan",
        "year": 2008,
        "num_parts": 4,
        "img_url": "https://cdn.example/sets/10184-1.jpg",
    }
    # A theme takes in its sub-themes: Town Plan (104) is in Town (50).
    assert [s["set_num"] for s in catalog.search_sets("town")] == ["10184-1"]
    # A year in the query filters by year.
    assert [s["set_num"] for s in catalog.search_sets("town plan 1961")] == ["810-2"]
    # Words that name no theme match set names, and a number matches set numbers.
    assert [s["set_num"] for s in catalog.search_sets("falcon millennium")] == ["75192-1"]
    assert [s["set_num"] for s in catalog.search_sets("75192")] == ["75192-1"]
    assert catalog.search_sets("no such set") == []


def test_a_sets_inventory(catalog) -> None:
    found = catalog.get_set_inventory("10184-1")
    assert found["set"]["name"] == "Town Plan"
    # The first inventory version only, the minifigure's parts not at all,
    # spares flagged, names from the parts catalog.
    assert [(p["part_num"], p["color_id"], p["quantity"], p["is_spare"]) for p in found["inventory"]] == [
        ("3001", 4, 2, False),
        ("3001", 4, 1, False),
        ("3020", 1, 1, False),
        ("3020", 1, 1, True),
    ]
    first = found["inventory"][0]
    assert first["part_name"] == "Brick 2 x 4"
    assert first["color_name"] == "Red"
    assert first["color_rgb"] == "C91A09"
    assert first["part_img_url"] == "https://cdn.example/parts/3001-4.jpg"


def test_the_set_endpoints(client: TestClient, auth_headers: dict[str, str], catalog) -> None:
    search = client.get("/api/profile-catalog/search-sets", params={"q": "town plan"}, headers=auth_headers)
    assert search.status_code == 200, search.text
    assert [s["set_num"] for s in search.json()["results"]] == ["10184-1", "810-2"]

    detail = client.get("/api/profile-catalog/sets/10184-1", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["inventory"]) == 4
    assert client.get("/api/profile-catalog/sets/404-1", headers=auth_headers).status_code == 404

    without_spares = client.post("/api/kits/from-set", json={"set_num": "10184-1"}, headers=auth_headers)
    assert without_spares.status_code == 200, without_spares.text
    kit = without_spares.json()
    assert kit["source"] == "set"
    assert kit["set_meta"]["name"] == "Town Plan"
    assert kit["total_quantity"] == 4

    with_spares = client.post("/api/kits/from-set", json={"set_num": "10184-1", "include_spares": True}, headers=auth_headers)
    assert with_spares.json()["total_quantity"] == 5


def test_set_search_says_when_the_sets_are_not_imported(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(tmp_path / "empty.db"))
    service = profile_catalog.ProfileCatalogService(runs_syncs=False)
    monkeypatch.setattr(profiles_router, "get_profile_catalog_service", lambda: service)
    response = client.get("/api/profile-catalog/search-sets", params={"q": "town plan"}, headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["code"] == "SET_SEARCH_UNAVAILABLE"
    service._conn.close()
