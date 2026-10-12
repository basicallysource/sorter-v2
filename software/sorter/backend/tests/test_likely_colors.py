"""The likely colors behind "No, pick the color": asked of Hive and kept
briefly, ranked by color alone over the saved palette when Hive cannot answer,
and the palette itself kept for a machine that boots without Hive."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import color_rank
import hive_metadata
import piece_records
import server.shared_state as shared_state
from server.hive_models import HiveError
from server.routers import pieces

PALETTE = [
    {"id": 4, "name": "Orange", "rgb": "FE8A18", "is_trans": False},
    {"id": 68, "name": "Dark Orange", "rgb": "A95500", "is_trans": False},
    {"id": 5, "name": "Red", "rgb": "C91A09", "is_trans": False},
    {"id": 11, "name": "Black", "rgb": "05131D", "is_trans": False},
]


class _Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def warn(self, msg: str) -> None:
        self.lines.append(msg)

    warning = warn


class _Hive:
    """A Hive that answers, or fails like an unreachable one."""

    def __init__(self, up: bool = True) -> None:
        self.up = up
        self.likely_calls: list[tuple[str, str | None]] = []
        self.palette_calls = 0

    def list_bricklink_colors(self):
        self.palette_calls += 1
        if not self.up:
            raise ConnectionError("unreachable")
        return {"results": PALETTE}

    def likely_colors(self, part_num, predictions=None):
        self.likely_calls.append((part_num, predictions))
        if not self.up:
            raise HiveError(502, "bad gateway")
        ranked = color_rank.rank_colors(PALETTE, color_rank.parse_predictions(predictions))
        return {"part_id": part_num, "item_no": part_num, "source": "live", "updated_at": None,
                "total_qty": 10, "predictions": [], "colors": ranked}


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    monkeypatch.setattr(hive_metadata, "_bricklink_colors_cache", None)
    monkeypatch.setattr(hive_metadata, "_bricklink_colors_from_hive", False)
    monkeypatch.setattr(hive_metadata, "_bricklink_colors_tried_at", 0.0)
    monkeypatch.setattr(hive_metadata, "_likely_cache", {})
    monkeypatch.setattr(piece_records, "_estValue", lambda gc, part_id, color_id: None)
    gc = SimpleNamespace(logger=_Logger(), runtime_stats=None, run_id=None, machine_id=None)
    monkeypatch.setattr(shared_state, "gc_ref", gc)
    return gc


def _use(monkeypatch, hive):
    monkeypatch.setattr(hive_metadata, "_client", lambda: hive)


def _record(uuid: str, color_id: str, confidence: float | None = 0.8) -> None:
    piece_records.recordPiece(
        {"uuid": uuid, "classification_status": "classified", "part_id": "3003",
         "part_name": "Brick 2 x 2", "color_id": color_id, "color_name": "Orange",
         "color_confidence": confidence, "brickognize_listing_id": "listing-1"},
        run_id="process",
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pieces.router)
    return TestClient(app)


def test_the_ranker_is_the_same_file_as_hives():
    here = Path(color_rank.__file__).resolve()
    hive_copy = here.parents[2] / "hive" / "backend" / "app" / "services" / "color_rank.py"
    if not hive_copy.exists():
        pytest.skip("the Hive backend is not beside this checkout")
    assert hive_copy.read_bytes() == here.read_bytes()


def test_hive_ranks_the_piece_and_the_answer_is_kept(monkeypatch):
    hive = _Hive()
    _use(monkeypatch, hive)
    _record("p1", "4", 0.8)
    with _client() as client:
        first = client.get("/api/pieces/p1/likely-colors")
        again = client.get("/api/pieces/p1/likely-colors")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["fallback"] is None and body["source"] == "live"
    assert body["colors"][0]["color_id"] == 4
    assert again.json() == body
    assert hive.likely_calls == [("3003", "4:0.8")]


def test_every_requests_colors_are_the_predictions_at_their_best_score(monkeypatch):
    import piece_predictions

    hive = _Hive()
    _use(monkeypatch, hive)
    _record("p2", "4", 0.6)
    piece_predictions.recordPredictions("p2", [
        {"request": "single_burst", "provider": "brickognize", "kind": "color", "rank": 0,
         "value_id": "5", "value_name": "Red", "score": 0.9, "applied": False},
        {"request": "combined", "provider": "brickognize", "kind": "color", "rank": 1,
         "value_id": "68", "value_name": "Dark Orange", "score": 0.3, "applied": False},
        {"request": "combined", "provider": "brickognize", "kind": "color", "rank": 0,
         "value_id": "4", "value_name": "Orange", "score": 0.6, "applied": True},
        {"request": "single_burst", "provider": "brickognize", "kind": "color", "rank": 1,
         "value_id": "4", "value_name": "Orange", "score": 0.05, "applied": False},
        {"request": "combined", "provider": "brickognize", "kind": "part", "rank": 0,
         "value_id": "3003", "value_name": "Brick 2 x 2", "score": 0.8, "applied": True},
    ])
    with _client() as client:
        response = client.get("/api/pieces/p2/likely-colors")
    assert response.status_code == 200, response.text
    # Every request's colors, each at its best score, best first; no parts.
    assert hive.likely_calls == [("3003", "5:0.9,4:0.6,68:0.3")]


def test_hive_down_ranks_by_color_alone_over_the_saved_palette(monkeypatch, _state):
    _use(monkeypatch, _Hive(up=True))
    assert hive_metadata.listBrickLinkColors(_state) == PALETTE

    # A fresh process with Hive gone: the palette comes from the database.
    monkeypatch.setattr(hive_metadata, "_bricklink_colors_cache", None)
    down = _Hive(up=False)
    _use(monkeypatch, down)
    _record("p2", "4", 0.9)
    with _client() as client:
        resp = client.get("/api/pieces/p2/likely-colors")
        colors = client.get("/api/pieces/colors")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallback"] == "hive_unreachable"
    assert body["source"] == "none"
    assert [c["color_id"] for c in body["colors"]][:2] == [4, 68]
    assert all(c["qty"] is None for c in body["colors"])
    assert [c["id"] for c in colors.json()["results"]] == [4, 68, 5, 11]
    assert down.likely_calls == [("3003", "4:0.9")]


def test_a_hive_without_the_ranking_says_so(monkeypatch):
    class _OldHive(_Hive):
        def likely_colors(self, part_num, predictions=None):
            raise HiveError(404, "Not Found")

    _use(monkeypatch, _OldHive())
    _record("p5", "4", 0.9)
    with _client() as client:
        body = client.get("/api/pieces/p5/likely-colors").json()
    assert body["fallback"] == "hive_too_old"
    assert body["colors"][0]["color_id"] == 4


def test_no_hive_and_no_saved_palette_is_empty_not_an_error(monkeypatch):
    _use(monkeypatch, None)
    _record("p3", "4")
    with _client() as client:
        resp = client.get("/api/pieces/p3/likely-colors")
    assert resp.status_code == 200
    assert resp.json()["fallback"] == "no_hive" and resp.json()["colors"] == []


def test_a_palette_from_the_database_is_retried_against_hive_later(monkeypatch, _state):
    _use(monkeypatch, _Hive(up=True))
    hive_metadata.listBrickLinkColors(_state)
    monkeypatch.setattr(hive_metadata, "_bricklink_colors_cache", None)
    down = _Hive(up=False)
    _use(monkeypatch, down)
    assert hive_metadata.listBrickLinkColors(_state) == PALETTE
    assert hive_metadata.listBrickLinkColors(_state) == PALETTE
    assert down.palette_calls == 1
    monkeypatch.setattr(hive_metadata, "_bricklink_colors_tried_at", 0.0)
    back = _Hive(up=True)
    _use(monkeypatch, back)
    hive_metadata.listBrickLinkColors(_state)
    hive_metadata.listBrickLinkColors(_state)
    assert back.palette_calls == 1


def test_no_color_predicted_is_no_prediction_and_cannot_be_confirmed(monkeypatch):
    hive = _Hive()
    _use(monkeypatch, hive)
    _record("p4", "any_color", None)
    with _client() as client:
        resp = client.get("/api/pieces/p4/likely-colors")
        confirm = client.post("/api/pieces/p4/correction", json={"color_corrected_id": "any_color", "submit": False})
        real = client.post("/api/pieces/p4/correction", json={"color_corrected_id": "5", "submit": False})
    assert resp.status_code == 200
    assert hive.likely_calls == [("3003", None)]
    assert confirm.status_code == 400
    assert real.status_code == 200, real.text
    assert real.json()["summary"]["color_corrected_id"] == "5"


def test_an_unknown_piece_is_not_found(monkeypatch):
    _use(monkeypatch, _Hive())
    with _client() as client:
        assert client.get("/api/pieces/nope/likely-colors").status_code == 404
