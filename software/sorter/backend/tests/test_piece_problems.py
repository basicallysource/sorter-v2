"""What went wrong with a piece is kept with its record: written with it, read
back in the list and on the piece's own read, and not lost to a later write that
has none (the early record the correction API makes from memory)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import piece_records
from server.routers import pieces

NOW = 1_760_000_000.0

STRAY = {
    "kind": "stray",
    "message": "It was never photographed on the way in, so nothing says what it is.",
    "at": NOW + 1.0,
    "after_s": None,
}
LOST = {
    "kind": "track_lost",
    "message": "The camera lost it 4 s after it was first seen, before it reached the classification channel.",
    "at": NOW + 4.0,
    "after_s": 4.0,
}
TIMED_OUT = {
    "kind": "timed_out",
    "message": "Never reached a bin: it went 31 s without an update while it was still being identified.",
    "at": NOW + 36.0,
    "after_s": 31.0,
}


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    monkeypatch.setattr(piece_records, "_estValue", lambda gc, part_id, color_id: None)


def _record(uuid: str, **fields) -> None:
    piece_records.recordPiece(
        {
            "uuid": uuid,
            "created_at": NOW,
            "distributed_at": NOW + 1,
            "classification_status": "classified",
            **fields,
        }
    )


def _oldDatabase(path: Path) -> None:
    # A machine updated from a version that had no problems column, with a piece
    # already recorded.
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE piece_records (id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE, run_id TEXT, "
        "machine_id TEXT, seen_at REAL, recorded_at REAL, classification_status TEXT, part_id TEXT, "
        "part_name TEXT, color_id TEXT, color_name TEXT, category_id TEXT, confidence REAL, bin_x INTEGER, "
        "bin_y INTEGER, bin_z INTEGER, dead INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "INSERT INTO piece_records (uuid, seen_at, classification_status) VALUES ('before', ?, 'classified')",
        (NOW - 60,),
    )
    conn.commit()
    conn.close()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pieces.router)
    return TestClient(app)


def _problemsListed(client: TestClient) -> dict[str, list]:
    items = client.get("/api/pieces").json()["items"]
    return {item["uuid"]: item["problems"] for item in items}


def test_what_went_wrong_with_a_piece_is_kept_with_its_record(tmp_path, monkeypatch) -> None:
    _oldDatabase(tmp_path / "local_state.sqlite")
    _record("stuck", dead=True, problems=[STRAY, LOST, TIMED_OUT])
    _record("fine")
    client = _client()

    # The list and the piece's own read both carry the problems; a piece with
    # none, and one recorded before the column existed, carry an empty list.
    listed = {item["uuid"]: item["problems"] for item in piece_records.listPieces(None)["items"]}
    assert listed == {"before": [], "fine": [], "stuck": [STRAY, LOST, TIMED_OUT]}
    assert piece_records.getPieceSummaryByUuid(None, "stuck")["problems"] == [STRAY, LOST, TIMED_OUT]
    assert piece_records.getPieceSummaryByUuid(None, "fine")["problems"] == []
    assert _problemsListed(client) == listed
    assert client.get("/api/pieces/stuck").json()["summary"]["problems"] == [STRAY, LOST, TIMED_OUT]

    # The record written again without any (the early one from the correction
    # API, or a write with an empty list) keeps what was noted.
    _record("stuck", dead=True)
    _record("stuck", dead=True, problems=[])
    assert piece_records.getPieceSummaryByUuid(None, "stuck")["problems"] == [STRAY, LOST, TIMED_OUT]
    assert _problemsListed(client)["stuck"] == [STRAY, LOST, TIMED_OUT]

    # A write that has some replaces them: it carries the whole list.
    _record("stuck", dead=True, problems=[LOST, TIMED_OUT])
    assert piece_records.getPieceSummaryByUuid(None, "stuck")["problems"] == [LOST, TIMED_OUT]

    # A piece still in memory tells its own problems.
    payload = {
        "uuid": "live",
        "created_at": NOW,
        "updated_at": NOW + 5,
        "stage": "distributing",
        "classification_status": "classified",
        "problems": [LOST],
    }
    stats = SimpleNamespace(lookupKnownObject=lambda uuid: payload if uuid == "live" else None)
    monkeypatch.setattr(pieces.shared_state, "gc_ref", SimpleNamespace(runtime_stats=stats))
    monkeypatch.setattr(pieces.piece_predictions, "recent", lambda uuid: [])
    answer = client.get("/api/pieces/live").json()
    assert answer["origin"] == "memory"
    assert answer["summary"]["problems"] == [LOST]
