"""The service-to-service parts catalog: the scope split, and the batch shape.

The catalog here is a REAL ProfileCatalogService over a temp parts.db rather
than a stub, so these exercise the same id-resolution the machines use — the
BrickLink-vs-Rebrickable fallback is the part most likely to break and a fake
would not have it.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import profile_catalog as pc
from app.services.profile_engine import db as profile_db

CATEGORIES = [{"id": 1, "name": "Bricks"}, {"id": 2, "name": "Plates"}]
PARTS = [
    {"part_num": "3001", "name": "Brick 2 x 4", "part_cat_id": 1,
     "external_ids": {"BrickLink": ["3001"]}},
    {"part_num": "3020", "name": "Plate 2 x 4", "part_cat_id": 2,
     "external_ids": {"BrickLink": ["3020"]}},
    # The base mold behind the printed item below. Rebrickable carries the mold;
    # the print exists only as a BrickLink item number.
    {"part_num": "973", "name": "Torso", "part_cat_id": 1, "external_ids": {}},
    # No BrickLink mapping at all, so no weight — the coverage case.
    {"part_num": "99999", "name": "Mystery Thing", "part_cat_id": 1, "external_ids": {}},
]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A live catalog service backed by a seeded temp parts.db."""
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(tmp_path / "parts.db"))
    monkeypatch.setattr(pc, "_catalog_service", None)
    svc = pc.get_profile_catalog_service()
    conn = svc._conn

    profile_db.upsertCategories(conn, CATEGORIES)
    profile_db.upsertParts(conn, PARTS)
    for part_num, item_no in (("3001", "3001"), ("3020", "3020")):
        conn.execute(
            "INSERT OR REPLACE INTO part_bricklink_ids (part_num, item_no, is_primary) "
            "VALUES (?, ?, 1)",
            (part_num, item_no),
        )
    conn.execute(
        "INSERT INTO bricklink_items (item_no, part_num, name, weight, dim_x_studs, "
        "dim_y_studs, year_released) VALUES ('3001', '3001', 'Brick 2 x 4', 2.5, 4, 2, 1979)"
    )
    conn.execute(
        "INSERT INTO bricklink_items (item_no, part_num, name, weight, dim_x_studs, "
        "dim_y_studs, year_released) VALUES ('3020', '3020', 'Plate 2 x 4', 1.2, 4, 2, 1979)"
    )
    # A BrickLink-only id: no Rebrickable part row, which is how printed parts
    # and minifigs arrive off a machine.
    conn.execute(
        "INSERT INTO bricklink_items (item_no, part_num, name, weight) "
        "VALUES ('973pb1234', '973', 'Torso with Print', 1.9)"
    )
    conn.execute(
        "INSERT INTO price_guides (item_no, bl_color_id, rb_color_id, ord_new_wavg, "
        "inv_new_qty, inv_new_lots) VALUES ('3001', 5, 4, 1.20, 500, 9)"
    )
    profile_db.upsertPartGeometry(
        conn, "3001",
        {"ldraw_id": "3001", "geometry_source": "direct", "bbox_x_mm": 31.8,
         "bbox_y_mm": 15.8, "bbox_z_mm": 11.4, "max_extent_mm": 35.5, "volume_mm3": 4200.0},
        "2026-01-01T00:00:00Z",
    )
    conn.commit()
    profile_db.reloadPartsData(conn, svc._parts_data)
    yield svc


def _admin_login(client, db):
    """Register an admin and leave the client logged in AS THEM.

    A function and not a fixture on purpose. Every login mutates the one
    TestClient cookie jar, so a fixture that logs in is order-dependent on any
    other fixture that also logs in — `test_machine` registers its own owner and
    would silently leave a member holding the session. Called explicitly, the
    order is on the page.
    """
    from app.models.user import User
    from tests.conftest import _auth_headers, _login_user, _register_user

    _register_user(client, "catalog-admin@test.com", "Password123!", "Catalog Admin")
    _login_user(client, "catalog-admin@test.com", "Password123!")
    user = db.query(User).filter(User.email == "catalog-admin@test.com").first()
    user.role = "admin"
    db.commit()
    _login_user(client, "catalog-admin@test.com", "Password123!")
    return _auth_headers(client)


def _mint(client, headers, scopes, machine_ids=None):
    payload = {"name": "catalog-key", "scopes": scopes}
    if machine_ids is not None:
        payload["machine_ids"] = machine_ids
    r = client.post("/api/auth/api-keys", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["raw_token"]


class TestCatalogAuth:
    def test_no_key_is_refused(self, client, catalog):
        assert client.get("/api/public/parts/3001").status_code == 401

    def test_the_legacy_shared_secret_does_not_open_the_catalog(
        self, client, catalog, monkeypatch
    ):
        """The stats secret predates every scope and must not stand in for one."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "legacy-secret")
        r = client.get("/api/public/parts/3001", headers={"X-Stats-Key": "legacy-secret"})
        assert r.status_code == 401

    def test_a_stats_key_cannot_read_the_catalog(self, client, db, catalog):
        headers = _admin_login(client, db)
        token = _mint(client, headers, ["stats:read"])
        r = client.get("/api/public/parts/3001", headers=_bearer(token))
        assert r.status_code == 403
        assert "parts:read" in r.json()["error"]

    def test_machine_scoped_key_is_refused(self, client, db, catalog, test_machine):
        """A key narrowed to one machine is strictly less powerful than its
        owner, and the catalog is not per-machine data for it to narrow."""
        import uuid

        from app.models.machine import Machine
        from app.models.user import User

        headers = _admin_login(client, db)
        # Minting a machine-scoped key validates the ids against machines the
        # creator owns, so the admin has to own this one for the test to reach
        # the guard under test rather than stopping at that check.
        admin = db.query(User).filter(User.email == "catalog-admin@test.com").first()
        machine = db.query(Machine).filter(Machine.id == uuid.UUID(test_machine["id"])).first()
        machine.owner_id = admin.id
        db.commit()

        token = _mint(client, headers, ["parts:read"], machine_ids=[test_machine["id"]])
        r = client.get("/api/public/parts/3001", headers=_bearer(token))
        assert r.status_code == 403


class TestPartsRead:
    @pytest.fixture
    def token(self, client, db):
        return _mint(client, _admin_login(client, db), ["parts:read"])

    def test_serves_identity_weight_and_ldraw_dimensions(self, client, catalog, token):
        r = client.get("/api/public/parts/3001", headers=_bearer(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["part_num"] == "3001"
        assert body["name"] == "Brick 2 x 4"
        assert body["category"] == "Bricks"
        assert body["bricklink"]["weight_g"] == 2.5
        assert body["dimensions"]["bbox_x_mm"] == 31.8
        assert body["dimensions"]["source"] == "ldraw_direct"
        assert body["dimensions"]["confidence"] == "exact"

    def test_resolves_a_bricklink_only_id(self, client, catalog, token):
        """A machine predicts printed parts in BrickLink ids; they must resolve."""
        r = client.get("/api/public/parts/973pb1234", headers=_bearer(token))
        assert r.status_code == 200, r.text
        assert r.json()["bricklink"]["weight_g"] == 1.9

    def test_unknown_part_is_404(self, client, catalog, token):
        assert client.get("/api/public/parts/nope-not-real", headers=_bearer(token)).status_code == 404

    def test_prices_are_absent_without_the_price_scope(self, client, catalog, token):
        body = client.get("/api/public/parts/3001?color_id=5", headers=_bearer(token)).json()
        for field in ("price", "moving_avg_price", "price_currency", "price_updated_at"):
            assert field not in body, f"{field} leaked to a key without parts:prices"

    def test_prices_appear_with_the_price_scope(self, client, db, catalog):
        token = _mint(client, _admin_login(client, db), ["parts:read", "parts:prices"])
        body = client.get("/api/public/parts/3001?color_id=5", headers=_bearer(token)).json()
        assert body["moving_avg_price"] == 1.20

    def test_search_and_colors_and_categories(self, client, catalog, token):
        r = client.get("/api/public/parts/search?q=brick", headers=_bearer(token))
        assert r.status_code == 200, r.text
        assert any(p["part_num"] == "3001" for p in r.json()["results"])

        assert client.get("/api/public/colors", headers=_bearer(token)).status_code == 200
        cats = client.get("/api/public/categories", headers=_bearer(token))
        assert cats.status_code == 200
        assert any(c["name"] == "Bricks" for c in cats.json()["categories"])


class TestPartsBatch:
    @pytest.fixture
    def token(self, client, db):
        return _mint(client, _admin_login(client, db), ["parts:read"])

    def test_answers_in_request_order_with_one_entry_per_id(self, client, catalog, token):
        r = client.post(
            "/api/public/parts/batch",
            headers=_bearer(token),
            json={"parts": [{"part_num": "3020"}, {"part_num": "3001"}, {"part_num": "3020"}]},
        )
        assert r.status_code == 200, r.text
        parts = r.json()["parts"]
        assert [p["part_num"] for p in parts] == ["3020", "3001", "3020"]
        assert r.json()["count"] == 3

    def test_an_unknown_id_holds_its_place(self, client, catalog, token):
        """A caller doing arithmetic needs the answer to line up with the ask."""
        r = client.post(
            "/api/public/parts/batch",
            headers=_bearer(token),
            json={"parts": [{"part_num": "3001"}, {"part_num": "ghost"}, {"part_num": "3020"}]},
        )
        parts = r.json()["parts"]
        assert len(parts) == 3
        assert parts[1] == {"part_num": "ghost", "found": False}
        assert parts[0]["found"] is True

    def test_batch_respects_the_price_scope(self, client, catalog, token):
        r = client.post(
            "/api/public/parts/batch",
            headers=_bearer(token),
            json={"parts": [{"part_num": "3001", "color_id": 5}]},
        )
        assert r.json()["prices_included"] is False
        assert "moving_avg_price" not in r.json()["parts"][0]

    def test_over_the_cap_is_refused(self, client, catalog, token):
        from app.routers.public_catalog import MAX_BATCH

        r = client.post(
            "/api/public/parts/batch",
            headers=_bearer(token),
            json={"parts": [{"part_num": "3001"}] * (MAX_BATCH + 1)},
        )
        assert r.status_code == 422


class TestBatchPartWeights:
    """The lookup behind the fleet mass rollup."""

    def test_maps_both_id_spaces_and_omits_the_unweighed(self, catalog):
        weights = catalog.batch_part_weights(["3001", "3020", "973pb1234", "99999", "ghost"])
        assert weights["3001"] == 2.5
        assert weights["3020"] == 1.2
        # BrickLink-only id resolves through the direct fallback.
        assert weights["973pb1234"] == 1.9
        # A part with no weight on file is ABSENT, not present as None, so a
        # caller can tell "nothing recorded" from "weighs zero".
        assert "99999" not in weights
        assert "ghost" not in weights

    def test_empty_input(self, catalog):
        assert catalog.batch_part_weights([]) == {}


class TestFleetMass:
    """The weight rollup: the two-database join, and honest coverage.

    Lives here rather than beside the other fleet tests because the half most
    likely to be wrong is the catalog half — the piece scan is a group-by.
    """

    def _sync(self, client, machine_token, records):
        r = client.post(
            "/api/machine/sync/piece-records",
            headers=_bearer(machine_token),
            json={"records": records},
        )
        assert r.status_code == 200, r.text

    def _mass(self, client, db, catalog, machine_token, records):
        import time

        from app.services import fleet_mass

        fleet_mass.reset_cache()
        self._sync(client, machine_token, [
            {"piece_uuid": f"p{i}", "local_id": i + 1, "seen_at": time.time() - 60,
             "classification_status": "classified", **rec}
            for i, rec in enumerate(records)
        ])
        token = _mint(client, _admin_login(client, db), ["stats:read"])
        r = client.get("/api/public/fleet/mass", headers=_bearer(token))
        assert r.status_code == 200, r.text
        return r.json()

    def test_sums_catalog_weights_over_the_piece_histogram(
        self, client, db, catalog, machine_token
    ):
        # 3 × 2.5g + 2 × 1.2g = 9.9g
        body = self._mass(client, db, catalog, machine_token, [
            {"part_id": "3001", "color_id": "5"},
            {"part_id": "3001", "color_id": "5"},
            {"part_id": "3001", "color_id": "11"},
            {"part_id": "3020", "color_id": "5"},
            {"part_id": "3020", "color_id": "5"},
        ])
        assert body["known_grams"] == 9.9
        assert body["matched_pieces"] == 5
        assert body["total_pieces"] == 5
        assert body["coverage"] == 1.0
        assert body["distinct_parts"] == 2

    def test_coverage_reports_what_could_not_be_weighed(
        self, client, db, catalog, machine_token
    ):
        """A piece with no part id, and a part with no weight, both count
        against coverage — the estimate is what extends over them."""
        body = self._mass(client, db, catalog, machine_token, [
            {"part_id": "3001", "color_id": "5"},   # 2.5g, weighed
            {"part_id": "99999", "color_id": "5"},  # in the catalog, no weight
            {"color_id": "5"},                      # never identified at all
        ])
        assert body["known_grams"] == 2.5
        assert body["matched_pieces"] == 1
        assert body["total_pieces"] == 3
        assert body["identified_pieces"] == 2
        assert body["coverage"] == pytest.approx(1 / 3, abs=1e-4)
        assert body["mean_piece_grams"] == 2.5
        # The mean matched piece extended over every piece, including the two
        # that could not be weighed.
        assert body["estimated_total_grams"] == 7.5

    def test_requires_the_stats_scope(self, client, db, catalog, monkeypatch):
        """Mass is an aggregate, so it sits in the anonymous tier with /stats —
        same scope, and the same legacy secret, until that secret is deleted."""
        monkeypatch.setattr(settings, "PUBLIC_STATS_API_KEY", "legacy-secret")
        assert client.get("/api/public/fleet/mass").status_code == 401
        assert client.get(
            "/api/public/fleet/mass", headers={"X-Stats-Key": "legacy-secret"}
        ).status_code == 200

        token = _mint(client, _admin_login(client, db), ["parts:read"])
        r = client.get("/api/public/fleet/mass", headers=_bearer(token))
        assert r.status_code == 403
