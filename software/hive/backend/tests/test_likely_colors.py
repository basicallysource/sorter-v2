"""The likely-colors ranking: the pure ranker on fixed colors, the one labelable
palette, and the people and machine routes over a real catalog in a temp
parts.db (sale data from its cached price guide, or a stubbed live call)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.config import settings
from app.services import bricklink, color_rank, likely_colors
from app.services import profile_catalog as pc
from app.services.profile_engine import db as profile_db

ORANGE = {"id": 4, "name": "Orange", "rgb": "FE8A18", "is_trans": False}
DARK_ORANGE = {"id": 68, "name": "Dark Orange", "rgb": "A95500", "is_trans": False}
RED = {"id": 5, "name": "Red", "rgb": "C91A09", "is_trans": False}
YELLOW = {"id": 3, "name": "Yellow", "rgb": "F2CD37", "is_trans": False}
TRANS_ORANGE = {"id": 98, "name": "Trans-Orange", "rgb": "F08F1C", "is_trans": True}
LIGHT_GRAY = {"id": 9, "name": "Light Gray", "rgb": "9BA19D", "is_trans": False}
LBG = {"id": 86, "name": "Light Bluish Gray", "rgb": "A0A5A9", "is_trans": False}
DBG = {"id": 85, "name": "Dark Bluish Gray", "rgb": "6C6E68", "is_trans": False}
BLACK = {"id": 11, "name": "Black", "rgb": "05131D", "is_trans": False}
PALETTE = [ORANGE, DARK_ORANGE, RED, YELLOW, TRANS_ORANGE, LIGHT_GRAY, LBG, DBG, BLACK]


def _names(ranked):
    return [c["color_name"] for c in ranked]


class TestRanker:
    def test_a_confident_prediction_comes_first(self):
        ranked = color_rank.rank_colors(PALETTE, [(4, 0.9)])
        assert ranked[0]["color_name"] == "Orange"
        assert ranked[0]["predicted"] is True
        assert ranked[0]["predicted_score"] == 0.9
        assert ranked[0]["distance"] == 0.0
        assert [c["rank"] for c in ranked] == list(range(1, len(PALETTE) + 1))

    def test_a_shade_of_the_same_hue_beats_another_hue_as_far_away(self):
        """Dark Orange and Red are about as far from Orange in Lab; the hue term
        puts the darker orange first. Trans-Orange is near in rgb but another
        finish, so it is pushed back."""
        ranked = color_rank.rank_colors(PALETTE, [(4, 0.9)])
        order = _names(ranked)
        assert order.index("Dark Orange") < order.index("Red")
        dark_orange = ranked[order.index("Dark Orange")]
        red = ranked[order.index("Red")]
        assert dark_orange["hue_diff"] < 5 < red["hue_diff"]
        trans = ranked[order.index("Trans-Orange")]
        assert trans["distance"] >= color_rank.FINISH_PENALTY

    def test_grays_have_no_hue_to_compare(self):
        ranked = color_rank.rank_colors(PALETTE, [(9, 0.75)])
        lbg = next(c for c in ranked if c["color_id"] == 86)
        assert lbg["hue_diff"] is None

    def test_popularity_reorders_near_colors_but_never_zeroes_one(self):
        """Predicted Light Gray, but the part sells mostly in Light Bluish Gray, a
        hair away: the common one comes first. A color nobody sells keeps a floor."""
        quantities = {86: {"qty": 800_000, "lots": 4000}, 9: {"qty": 30_000, "lots": 200}, 11: {"qty": 900_000, "lots": 4000}}
        ranked = color_rank.rank_colors(PALETTE, [(9, 0.75)], quantities=quantities, complete=True)
        assert _names(ranked)[:2] == ["Light Bluish Gray", "Light Gray"]
        light_gray = ranked[1]
        assert light_gray["qty"] == 30_000 and light_gray["lots"] == 200
        assert light_gray["share"] == round(30_000 / 1_730_000, 4)
        unsold = next(c for c in ranked if c["color_id"] == 98)
        assert unsold["qty"] == 0 and unsold["known_in"] is False
        assert unsold["likelihood"] == color_rank.FLOOR_UNKNOWN
        assert unsold["score"] > 0

        alone = color_rank.rank_colors(PALETTE, [(9, 0.75)])
        assert alone[0]["color_name"] == "Light Gray"
        assert all(c["likelihood"] == 1.0 and c["qty"] is None for c in alone)

    def test_partial_sale_data_says_less_about_an_absent_color(self):
        quantities = {86: {"qty": 1000}}
        complete = color_rank.rank_colors(PALETTE, [(4, 0.9)], quantities=quantities, complete=True)
        partial = color_rank.rank_colors(PALETTE, [(4, 0.9)], quantities=quantities, complete=False)
        orange_complete = next(c for c in complete if c["color_id"] == 4)
        orange_partial = next(c for c in partial if c["color_id"] == 4)
        assert orange_complete["likelihood"] == color_rank.FLOOR_UNKNOWN
        assert orange_partial["likelihood"] == color_rank.FLOOR_PARTIAL_UNKNOWN
        assert partial[0]["color_name"] == "Orange"

    def test_partial_data_for_a_part_sold_in_many_colors_reads_as_complete(self):
        """A 2 x 2 brick predicted Orange: the cache has it for sale in every color
        here but Trans-Orange, so Dark Orange (a common neighbour) comes before
        Trans-Orange (a near color nobody sells it in)."""
        quantities = {
            4: {"qty": 300_000}, 68: {"qty": 230_000}, 5: {"qty": 900_000}, 3: {"qty": 700_000},
            9: {"qty": 40_000}, 86: {"qty": 800_000}, 85: {"qty": 500_000}, 11: {"qty": 900_000},
        }
        assert len(quantities) == color_rank.INFORMATIVE_COLORS
        ranked = color_rank.rank_colors(PALETTE, [(4, 0.79)], quantities=quantities, complete=False)
        names = _names(ranked)
        assert names[0] == "Orange"
        assert names.index("Dark Orange") < names.index("Trans-Orange")
        trans = next(c for c in ranked if c["color_id"] == 98)
        assert trans["likelihood"] == color_rank.FLOOR_UNKNOWN

    def test_the_catalog_list_lifts_a_color_with_no_sales(self):
        ranked = color_rank.rank_colors(
            PALETTE, [(4, 0.9)], quantities={86: {"qty": 1000}}, complete=True, known_in=[68]
        )
        dark_orange = next(c for c in ranked if c["color_id"] == 68)
        assert dark_orange["known_in"] is True
        assert dark_orange["likelihood"] == color_rank.FLOOR_KNOWN

    def test_without_predictions_the_order_is_the_sales(self):
        quantities = {11: {"qty": 900}, 5: {"qty": 400}, 3: {"qty": 100}}
        ranked = color_rank.rank_colors(PALETTE, [], quantities=quantities, complete=True)
        assert _names(ranked)[:3] == ["Black", "Red", "Yellow"]
        assert all(c["closeness"] == 1.0 for c in ranked)

    def test_scores_split_between_predictions_and_merge_per_color(self):
        ranked = color_rank.rank_colors(PALETTE, [(5, 0.5), (4, 0.3), (5, 0.4), (3, None)])
        red = next(c for c in ranked if c["color_id"] == 5)
        yellow = next(c for c in ranked if c["color_id"] == 3)
        assert red["predicted_score"] == 0.5
        assert yellow["predicted"] is True and yellow["predicted_score"] is None
        assert {c["color_name"] for c in ranked[:3]} == {"Red", "Orange", "Yellow"}
        assert all(c["closeness"] <= 1.0 for c in ranked)

    def test_a_predicted_color_outside_the_palette_still_counts(self):
        modulex_orange = {"id": 123, "name": "Mx Orange", "rgb": "F7AD63", "is_trans": False}
        ranked = color_rank.rank_colors(PALETTE, [(123, 0.9)], lookup={123: modulex_orange})
        assert ranked[0]["color_name"] in {"Orange", "Yellow"}
        assert 123 not in {c["color_id"] for c in ranked}

    def test_parse_and_format_predictions(self):
        assert color_rank.parse_predictions("11:0.82, 86:0.1,5,x:1,7:abc,8:2,9:-1") == [
            (11, 0.82),
            (86, 0.1),
            (5, None),
            (8, 1.0),
        ]
        assert color_rank.parse_predictions(None) == []
        assert color_rank.format_predictions([(11, 0.82), ("5", None)]) == "11:0.82,5"

    def test_the_sorter_copy_is_the_same_file(self):
        """The sorter ranks with the same module when Hive is unreachable."""
        here = Path(color_rank.__file__)
        sorter_copy = here.parents[4] / "sorter" / "backend" / "color_rank.py"
        if not sorter_copy.exists():
            pytest.skip("the sorter backend is not beside this checkout")
        assert sorter_copy.read_bytes() == here.read_bytes()


# Rebrickable colors with their BrickLink ids, as parts.db holds them.
RB_COLORS = [
    {"id": 4, "name": "Red", "rgb": "C91A09", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [5], "ext_descrs": [["Red"]]}}},
    {"id": 25, "name": "Orange", "rgb": "FE8A18", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [4], "ext_descrs": [["Orange"]]}}},
    {"id": 484, "name": "Dark Orange", "rgb": "A95500", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [68], "ext_descrs": [["Dark Orange"]]}}},
    {"id": 14, "name": "Yellow", "rgb": "F2CD37", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [3], "ext_descrs": [["Yellow"]]}}},
    {"id": 0, "name": "Black", "rgb": "05131D", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [11], "ext_descrs": [["Black"]]}}},
    {"id": 1000, "name": "Mx Orange", "rgb": "F7AD63", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [123], "ext_descrs": [["Mx Orange"]]}}},
    {"id": 1001, "name": "Fabuland Orange", "rgb": "EF9121", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [160], "ext_descrs": [["Fabuland Orange"]]}}},
    {"id": 9999, "name": "[No Color/Any Color]", "rgb": "05131D", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [0], "ext_descrs": [["(Not Applicable)"]]}}},
]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(tmp_path / "parts.db"))
    monkeypatch.setattr(pc, "_catalog_service", None)
    svc = pc.get_profile_catalog_service()
    svc._config = dataclasses.replace(svc._config, bla_api_key="")
    conn = svc._conn
    profile_db.upsertColors(conn, RB_COLORS)
    profile_db.upsertCategories(conn, [{"id": 1, "name": "Bricks"}])
    profile_db.upsertParts(conn, [{"part_num": "3003", "name": "Brick 2 x 2", "part_cat_id": 1, "external_ids": {"BrickLink": ["3003"]}}])
    conn.execute("INSERT INTO bricklink_items (item_no, part_num, name) VALUES ('3003', '3003', 'Brick 2 x 2')")
    # price_guides stores the API's own field names, so pieces for sale are in *_lots.
    for color_id, pieces in ((5, 9000), (11, 6000), (3, 1000)):
        conn.execute(
            "INSERT INTO price_guides (item_no, bl_color_id, inv_new_lots, inv_new_qty) VALUES ('3003', ?, ?, 40)",
            (color_id, pieces),
        )
    conn.execute("INSERT INTO bricklink_item_colors (item_no, bl_color_id) VALUES ('3003', 68)")
    conn.commit()
    profile_db.reloadPartsData(conn, svc._parts_data)
    yield svc
    monkeypatch.setattr(pc, "_catalog_service", None)


class TestService:
    def test_one_labelable_palette(self, catalog):
        ids = {c["id"] for c in likely_colors.labelable_palette()}
        assert ids == {3, 4, 5, 11, 68}

    def test_cached_sale_data_and_catalog_colors(self, catalog):
        result = likely_colors.likely_colors("3003", [(4, 0.9)])
        assert result["source"] == "cache" and result["item_no"] == "3003"
        assert result["total_qty"] == 16000
        by_id = {c["color_id"]: c for c in result["colors"]}
        assert set(by_id) == {3, 4, 5, 11, 68}
        assert result["colors"][0]["color_id"] == 4
        assert by_id[5]["qty"] == 9000 and by_id[5]["lots"] == 40
        assert by_id[68]["known_in"] is True and by_id[68]["qty"] == 0
        assert by_id[4]["likelihood"] == color_rank.FLOOR_PARTIAL_UNKNOWN

    def test_live_sale_data_covers_the_palette(self, catalog, monkeypatch):
        catalog._config = dataclasses.replace(catalog._config, bla_api_key="test-key")
        calls = []

        def fake_live(api_key, item_no, color_ids, item_type="PART", now=None):
            calls.append((item_no, tuple(color_ids)))
            sold = {4: 5000, 5: 20000}
            return {cid: {"qty": sold.get(cid, 0), "qty_new": sold.get(cid, 0), "qty_used": 0, "lots": 10 if cid in sold else 0} for cid in color_ids}

        monkeypatch.setattr(bricklink, "fetch_color_quantities", fake_live)
        result = likely_colors.likely_colors("3003", [(4, 0.9)])
        assert result["source"] == "live"
        assert calls and calls[0][0] == "3003"
        orange = next(c for c in result["colors"] if c["color_id"] == 4)
        yellow = next(c for c in result["colors"] if c["color_id"] == 3)
        assert orange["qty"] == 5000 and result["colors"][0]["color_id"] == 4
        assert yellow["qty"] == 0 and yellow["likelihood"] == color_rank.FLOOR_UNKNOWN

    def test_an_unknown_part_ranks_by_color_alone(self, catalog):
        result = likely_colors.likely_colors("nope", [(4, 0.9)])
        assert result["source"] == "none" and result["item_no"] is None
        assert all(c["likelihood"] == 1.0 for c in result["colors"])
        none = likely_colors.likely_colors(None, [(4, 0.9)], limit=2)
        assert len(none["colors"]) == 2 and none["colors"][0]["color_id"] == 4


class TestRoutes:
    def test_people_get_the_ranking(self, client, test_user, catalog):
        resp = client.get("/api/labeling/likely-colors", params={"part_id": "3003", "predictions": "4:0.9,68:0.05"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["predictions"] == [{"color_id": 4, "score": 0.9}, {"color_id": 68, "score": 0.05}]
        assert body["colors"][0]["color_id"] == 4
        assert {"closeness", "likelihood", "distance", "hue_diff", "qty", "lots", "share", "known_in"} <= set(body["colors"][0])

    def test_people_must_sign_in(self, client, catalog):
        assert client.get("/api/labeling/likely-colors").status_code == 401

    def test_the_labeling_palette_is_the_labelable_one(self, client, test_user, catalog):
        resp = client.get("/api/labeling/colors")
        assert resp.status_code == 200
        assert {c["id"] for c in resp.json()["results"]} == {3, 4, 5, 11, 68}

    def test_machines_get_the_same_ranking(self, client, catalog, machine_token):
        headers = {"Authorization": f"Bearer {machine_token}"}
        resp = client.get("/api/machine/parts/3003/likely-colors", params={"predictions": "4:0.9"}, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["colors"][0]["color_id"] == 4
        assert resp.json() == client.get(
            "/api/labeling/likely-colors", params={"part_id": "3003", "predictions": "4:0.9"}
        ).json()
        palette = client.get("/api/machine/bricklink-colors", headers=headers).json()["results"]
        assert {c["id"] for c in palette} == {3, 4, 5, 11, 68}

    def test_machines_need_their_token(self, client, catalog):
        resp = client.get("/api/machine/parts/3003/likely-colors", headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401
