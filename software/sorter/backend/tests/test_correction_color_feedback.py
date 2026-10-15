"""Confirming or correcting a piece's colour tells Brickognize only about a
colour Brickognize gave. A colour from the hosted colour model is not its
answer, so nothing is sent there; the verdict is still kept on the piece."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import classification.brickognize_feedback as brickognize_feedback
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


def _sent(monkeypatch) -> list[dict]:
    sent: list[dict] = []
    monkeypatch.setattr(brickognize_feedback, "submitColorFeedback", lambda **kw: sent.append(kw))
    return sent


def _record(uuid: str, color_provider: str) -> None:
    piece_records.recordPiece(
        {"uuid": uuid, "classification_status": "classified", "part_id": "3003",
         "part_name": "Brick 2 x 2", "color_id": "4", "color_name": "Orange",
         "brickognize_listing_id": "listing-1", "brickognize_color_rank": 0,
         "color_provider": color_provider},
        run_id="process",
    )


def _confirm(uuid: str):
    app = FastAPI()
    app.include_router(pieces.router)
    with TestClient(app) as client:
        return client.post(f"/api/pieces/{uuid}/correction", json={"color_corrected_id": "4", "submit": True})


def test_confirming_our_models_colour_sends_nothing_to_brickognize(monkeypatch) -> None:
    sent = _sent(monkeypatch)
    _record("ours", "hive_basically")
    resp = _confirm("ours")
    assert resp.status_code == 200, resp.text
    assert sent == []
    assert resp.json()["color_submitted"] is False
    assert resp.json()["summary"]["color_corrected_id"] == "4"


def test_confirming_brickognizes_colour_still_tells_brickognize(monkeypatch) -> None:
    sent = _sent(monkeypatch)
    _record("theirs", "brickognize")
    resp = _confirm("theirs")
    assert resp.status_code == 200, resp.text
    assert [(s["color_id"], s["is_correct"]) for s in sent] == [("4", True)]
