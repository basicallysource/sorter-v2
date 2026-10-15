"""Colour feedback to Brickognize is about Brickognize's own colour answer for
the request the piece took its part from. The colour the operator settles on
says whether that answer was right, whichever provider gave the piece its
colour; with the hosted colour model, Brickognize's answer comes from the
stored predictions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import classification.brickognize_feedback as brickognize_feedback
import piece_predictions
import piece_records
import server.shared_state as shared_state
from server.routers import pieces


class _Logger:
    def warning(self, *_args) -> None:
        pass

    info = debug = error = warn = warning


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    monkeypatch.setattr(piece_records, "_estValue", lambda gc, part_id, color_id: None)
    monkeypatch.setattr(
        shared_state, "gc_ref", SimpleNamespace(logger=_Logger(), runtime_stats=None, run_id=None, machine_id=None)
    )


@pytest.fixture()
def sent(monkeypatch) -> list[tuple[str, int, bool]]:
    out: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        brickognize_feedback,
        "submitColorFeedback",
        lambda **kw: out.append((kw["color_id"], kw["color_rank"], kw["is_correct"])),
    )
    return out


def _record(uuid: str, *, applied_color: str, provider: str, brickognize_color: str | None) -> None:
    piece_records.recordPiece(
        {"uuid": uuid, "classification_status": "classified", "part_id": "3003",
         "part_name": "Brick 2 x 2", "color_id": applied_color, "color_name": "X",
         "brickognize_listing_id": "listing-1",
         "brickognize_color_rank": 0 if provider == "brickognize" else None,
         "color_provider": provider},
        run_id="process",
    )
    if brickognize_color is not None:
        piece_predictions.recordPredictions(uuid, [{
            "source": piece_predictions.SOURCE_LIVE, "request": "combined", "provider": "brickognize",
            "answers": [
                {"kind": "part", "rank": 0, "value_id": "3003", "score": 0.8, "applied": True},
                {"kind": "color", "rank": 0, "value_id": brickognize_color, "score": 0.7},
                {"kind": "color", "rank": 1, "value_id": "3", "score": 0.2},
            ],
        }])


def _verdict(uuid: str, color: str):
    app = FastAPI()
    app.include_router(pieces.router)
    with TestClient(app) as client:
        resp = client.post(f"/api/pieces/{uuid}/correction", json={"color_corrected_id": color, "submit": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_ours_and_brickognize_agree_and_the_operator_confirms(sent) -> None:
    _record("a", applied_color="4", provider="hive_basically", brickognize_color="4")
    _verdict("a", "4")
    assert sent == [("4", 0, True)]


def test_ours_was_right_and_brickognize_was_wrong(sent) -> None:
    _record("b", applied_color="1", provider="hive_basically", brickognize_color="4")
    _verdict("b", "1")
    assert sent == [("4", 0, False)]


def test_brickognizes_own_colour_confirmed(sent) -> None:
    _record("c", applied_color="4", provider="brickognize", brickognize_color=None)
    _verdict("c", "4")
    assert sent == [("4", 0, True)]


def test_no_brickognize_colour_on_record_sends_nothing(sent) -> None:
    _record("d", applied_color="4", provider="hive_basically", brickognize_color=None)
    body = _verdict("d", "4")
    assert sent == []
    assert body["summary"]["color_corrected_id"] == "4"
