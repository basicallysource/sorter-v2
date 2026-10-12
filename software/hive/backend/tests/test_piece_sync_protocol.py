"""The sorter -> Hive piece sync protocol: sync_seq watermarks, the machine
operator's verdict on the record, the piece_corrections stream of older
sorters, machine predictions, per-row skips, Hive's own Brickognize feedback
state, and the verdict views."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_prediction import MachinePiecePrediction
from app.models.machine_piece_rejection_reason import MachinePieceRejectionReason
from app.models.machine_sync_state import MachineSyncState
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_part_label import PiecePartLabel
from app.models.user import User
from app.routers import machine_sync
from app.routers import piece_color_labels as labeling_router
from tests.conftest import TestingSessionLocal

BASE = 1_760_000_000.0


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(client, token: str, path: str, records: list) -> dict:
    resp = client.post(f"/api/machine/sync/{path}", headers=_bearer(token), json={"records": records})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(client, token: str) -> dict:
    return client.get("/api/machine/sync/state", headers=_bearer(token)).json()


def _piece(piece_uuid: str) -> MachinePiece:
    s: Session = TestingSessionLocal()
    try:
        return s.query(MachinePiece).filter_by(piece_uuid=piece_uuid).one()
    finally:
        s.close()


def _reasons(piece_uuid: str) -> list[str]:
    s: Session = TestingSessionLocal()
    try:
        return sorted(r.reason for r in s.query(MachinePieceRejectionReason).filter_by(piece_uuid=piece_uuid))
    finally:
        s.close()


def _record(piece_uuid: str, local_id: int, sync_seq: int | None = None, **fields) -> dict:
    rec = {
        "piece_uuid": piece_uuid, "local_id": local_id, "seen_at": BASE, "recorded_at": BASE + 1,
        "classification_status": "classified", "part_id": "3001", "color_id": "11",
        "brickognize_listing_id": "L-1", "brickognize_item_rank": 0, "brickognize_item_type": "part",
        "brickognize_color_rank": 0,
    }
    if sync_seq is not None:
        rec.update({
            "sync_seq": sync_seq, "part_correct": None, "color_corrected_id": None,
            "part_feedback_submitted": False, "color_feedback_submitted": False,
            "correction_updated_at": None, "rejection_reasons": [],
        })
    rec.update(fields)
    return rec


def test_state_lists_every_data_type(client, machine_token):
    assert set(_state(client, machine_token)) == {
        "piece_records", "piece_images", "channel_crops", "piece_corrections",
        "piece_predictions", "control_data_segments", "samples",
    }


def test_records_watermark_by_sync_seq_when_present(client, machine_token):
    out = _post(client, machine_token, "piece-records", [_record("a", 5, sync_seq=100), _record("b", 6, sync_seq=101)])
    assert out == {"max_local_id": 101, "upserted": 2, "skipped": 0}
    # An older sorter's record (no sync_seq) moves it by local_id; max-based.
    assert _post(client, machine_token, "piece-records", [_record("c", 7)])["max_local_id"] == 101
    assert _piece("a").local_id == 5


def test_a_record_with_sync_seq_carries_the_operators_whole_verdict(client, machine_token):
    _post(client, machine_token, "piece-records", [_record(
        "v", 1, sync_seq=10, part_correct=False, color_corrected_id="85", part_feedback_submitted=True,
        correction_updated_at=BASE + 50, rejection_reasons=["blurry", "not_lego"],
    )])
    piece = _piece("v")
    assert (piece.part_correct, piece.color_corrected_id, piece.part_feedback_submitted) == (False, "85", True)
    assert _reasons("v") == ["blurry", "not_lego"]

    # The operator changes their mind: the verdict is overwritten, a sent flag
    # stays sent, and the reasons are replaced.
    _post(client, machine_token, "piece-records", [_record(
        "v", 1, sync_seq=11, part_correct=None, color_corrected_id="86", part_feedback_submitted=False,
        rejection_reasons=["blurry"],
    )])
    piece = _piece("v")
    assert (piece.part_correct, piece.color_corrected_id, piece.part_feedback_submitted) == (None, "86", True)
    assert _reasons("v") == ["blurry"]

    # An older sorter's record of the same piece leaves the verdict alone.
    _post(client, machine_token, "piece-records", [_record("v", 1, bin_x=4)])
    piece = _piece("v")
    assert (piece.color_corrected_id, piece.bin_x) == ("86", 4)
    assert _reasons("v") == ["blurry"]

    _post(client, machine_token, "piece-records", [_record("v", 1, sync_seq=12, rejection_reasons=[])])
    assert _reasons("v") == []


def test_a_correction_before_its_record_is_kept(client, machine_token):
    out = _post(client, machine_token, "piece-corrections", [{
        "piece_uuid": "early", "local_id": 3, "part_correct": False, "color_corrected_id": "7",
        "part_feedback_submitted": True, "updated_at": BASE, "rejection_reasons": ["no_piece"],
    }])
    assert out == {"max_local_id": 3, "upserted": 1, "skipped": 0}
    stub = _piece("early")
    assert (stub.part_correct, stub.color_corrected_id, stub.local_id) == (False, "7", 0)
    # The record arrives later and fills the row in; the verdict stays, and
    # the row counts as new from now (workers key on created_at).
    _post(client, machine_token, "piece-records", [_record("early", 40)])
    piece = _piece("early")
    assert (piece.local_id, piece.part_id, piece.part_correct, piece.color_corrected_id) == (40, "3001", False, "7")
    assert piece.created_at > stub.created_at
    _post(client, machine_token, "piece-records", [_record("early", 40, bin_x=2)])
    assert _piece("early").created_at == piece.created_at
    assert _reasons("early") == ["no_piece"]


def test_rejection_reasons_are_idempotent(client, machine_token):
    # The journal can hold two snapshots of one piece in one batch. This used to
    # fail on uq_machine_piece_rejection_reasons_piece_reason and was retried
    # forever, stalling the machine's sync.
    _post(client, machine_token, "piece-records", [_record("r", 1)])
    batch = [
        {"piece_uuid": "r", "local_id": 1, "updated_at": BASE, "rejection_reasons": ["blurry", "not_lego"]},
        {"piece_uuid": "r", "local_id": 2, "updated_at": BASE + 1, "rejection_reasons": ["blurry", "blurry"]},
    ]
    assert _post(client, machine_token, "piece-corrections", batch)["max_local_id"] == 2
    assert _post(client, machine_token, "piece-corrections", batch)["max_local_id"] == 2
    assert _reasons("r") == ["blurry"]
    # None: the sorter predates the field; leave the reasons alone.
    _post(client, machine_token, "piece-corrections", [{"piece_uuid": "r", "local_id": 3, "part_correct": True}])
    assert _reasons("r") == ["blurry"]
    assert _piece("r").part_correct is True


def test_bad_rows_are_skipped_and_the_watermark_still_moves(client, machine_token):
    out = _post(client, machine_token, "piece-records", [
        _record("good-1", 1, sync_seq=20),
        {"local_id": 2, "sync_seq": 21, "part_id": "3001"},  # no piece_uuid
        _record("good-2", 3, sync_seq=22, bin_x="not a number"),
        "not even an object",
        _record("good-3", 4, sync_seq=23),
    ])
    assert out == {"max_local_id": 23, "upserted": 2, "skipped": 3}
    assert _piece("good-3").local_id == 4

    out = _post(client, machine_token, "piece-predictions", [
        {"local_id": 9, "piece_uuid": "p", "request": "combined", "provider": "brickognize", "kind": "color",
         "rank": "first", "value_id": "11"},
    ])
    assert out == {"max_local_id": 9, "upserted": 0, "skipped": 1}


def test_a_row_the_database_refuses_is_skipped_alone(db, test_machine):
    machine = db.query(Machine).filter(Machine.id == UUID(test_machine["id"])).one()
    written: list[str] = []

    def write(rows):
        if "bad" in rows:
            db.add(MachineSyncState(machine_id=machine.id, data_type="x", max_local_id=1, updated_at=datetime.now(timezone.utc)))
            db.flush()
            raise IntegrityError("refused", None, Exception("refused"))
        written.extend(rows)

    skipped = machine_sync._write_rows(db, write, ["ok-1", "bad", "ok-2"], machine, "test")
    assert skipped == 1
    assert written == ["ok-1", "ok-2"]
    # The refused row's partial write went with its savepoint.
    assert db.query(MachineSyncState).filter_by(data_type="x").count() == 0


def test_images_watermark_by_sync_seq(client, machine_token):
    import json

    for meta in (
        {"piece_uuid": "img", "seq": 0, "local_id": 7, "sync_seq": 300, "used": True},
        {"piece_uuid": "img", "seq": 1, "local_id": 8},
    ):
        resp = client.post(
            "/api/machine/sync/piece-image", headers=_bearer(machine_token), data={"metadata": json.dumps(meta)},
        )
        assert resp.status_code == 200, resp.text
    assert _state(client, machine_token)["piece_images"]["max_local_id"] == 300


def _prediction(local_id: int, piece_uuid: str, request: str, kind: str, rank: int, value_id: str, **fields) -> dict:
    row = {
        "local_id": local_id, "piece_uuid": piece_uuid, "request": request, "provider": "brickognize",
        "model": None, "kind": kind, "rank": rank, "value_id": value_id, "value_name": None,
        "score": 0.5, "applied": False, "created_at": BASE,
    }
    row.update(fields)
    return row


@pytest.fixture()
def catalog(monkeypatch: pytest.MonkeyPatch):
    service = SimpleNamespace(part_summary=lambda part_num: None)
    monkeypatch.setattr(labeling_router, "get_profile_catalog_service", lambda: service)
    return service


def test_predictions_sync_and_show_on_the_piece(client, machine_token, test_machine, catalog):
    _post(client, machine_token, "piece-records", [_record("pp", 1, sync_seq=1)])
    rows = [
        _prediction(1, "pp", "combined", "color", 0, "11", score=0.7, applied=True),
        _prediction(2, "pp", "combined", "color", 1, "85", score=0.2),
        _prediction(3, "pp", "hosted", "color", 0, "11", provider="hive_basically", model="sha", score=0.9),
        _prediction(4, "pp", "combined", "part", 0, "3001", score=0.95, applied=True),
    ]
    assert _post(client, machine_token, "piece-predictions", rows) == {"max_local_id": 4, "upserted": 4, "skipped": 0}
    assert _post(client, machine_token, "piece-predictions", rows)["upserted"] == 4  # a re-send upserts in place
    s: Session = TestingSessionLocal()
    try:
        assert s.query(MachinePiecePrediction).count() == 4
    finally:
        s.close()
    assert _state(client, machine_token)["piece_predictions"]["max_local_id"] == 4

    detail = client.get(f"/api/labeling/piece/{test_machine['id']}/pp")
    assert detail.status_code == 200, detail.text
    preds = detail.json()["machine_predictions"]
    assert [(p["kind"], p["request"], p["rank"], p["value_id"], p["applied"]) for p in preds] == [
        ("color", "combined", 0, "11", True),
        ("color", "combined", 1, "85", False),
        ("color", "hosted", 0, "11", False),
        ("part", "combined", 0, "3001", True),
    ]
    assert preds[2]["provider"] == "hive_basically" and preds[2]["model"] == "sha"


def test_hive_feedback_lives_on_the_labelers_rows_not_the_machines(
    client, machine_token, test_machine, auth_headers, catalog, monkeypatch
):
    sent: list[tuple] = []
    monkeypatch.setattr(labeling_router, "submit_part_feedback", lambda **kw: sent.append(("part", kw["is_correct"])))
    monkeypatch.setattr(labeling_router, "submit_color_feedback", lambda **kw: sent.append(("color", kw["is_correct"])))
    # The machine operator already said the colour is 85.
    _post(client, machine_token, "piece-records", [_record("fb", 1, sync_seq=1, color_corrected_id="85")])

    url = f"/api/labeling/piece/{test_machine['id']}/fb/brickognize-feedback"
    resp = client.post(url, json={"part_correct": False, "color_corrected_id": 5}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["part_submitted"], body["color_submitted"]) == (True, True)
    assert body["correction"] == {
        "correctable": True, "part_correct": False, "color_corrected_id": "5",
        "part_feedback_submitted": True, "color_feedback_submitted": True,
    }
    assert sent == [("part", False), ("color", False)]

    piece = _piece("fb")
    assert (piece.part_correct, piece.color_corrected_id) == (None, "85")
    assert (piece.part_feedback_submitted, piece.color_feedback_submitted) == (False, False)
    s: Session = TestingSessionLocal()
    try:
        part = s.query(PiecePartLabel).filter_by(piece_uuid="fb").one()
        color = s.query(PieceColorLabel).filter_by(piece_uuid="fb").one()
        assert (part.part_correct, part.part_num, part.brickognize_feedback_at is not None) == (False, None, True)
        assert (color.color_id, color.brickognize_feedback_at is not None) == (5, True)
    finally:
        s.close()

    # Brickognize hears about a piece once: a second verdict is saved, not sent.
    resp = client.post(url, json={"part_correct": True}, headers=auth_headers)
    assert resp.json()["part_submitted"] is False
    assert sent == [("part", False), ("color", False)]
    s = TestingSessionLocal()
    try:
        part = s.query(PiecePartLabel).filter_by(piece_uuid="fb").one()
        assert (part.part_correct, part.part_num) == (True, "3001")
    finally:
        s.close()

    # The machine's own verdict syncing later never touches the labeler's.
    _post(client, machine_token, "piece-records", [_record("fb", 1, sync_seq=2, part_correct=True, color_corrected_id="11")])
    detail = client.get(f"/api/labeling/piece/{test_machine['id']}/fb").json()
    assert detail["correction"]["part_correct"] is True
    assert detail["correction"]["color_corrected_id"] == "5"


def test_feedback_the_machine_already_sent_is_not_sent_again(
    client, machine_token, test_machine, auth_headers, catalog, monkeypatch
):
    sent: list = []
    monkeypatch.setattr(labeling_router, "submit_part_feedback", lambda **kw: sent.append(kw))
    _post(client, machine_token, "piece-records", [_record("ms", 1, sync_seq=1, part_feedback_submitted=True)])
    resp = client.post(
        f"/api/labeling/piece/{test_machine['id']}/ms/brickognize-feedback",
        json={"part_correct": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["part_submitted"] is False and sent == []


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "8a9445c627d2_machine_predictions_and_verdicts.py"
    spec = importlib.util.spec_from_file_location("verdicts_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_verdict_views_list_every_verdict_with_its_source(client, db, machine_token, test_machine, test_user):
    migration = _migration()
    _drop_views(db)
    db.execute(text(migration.PIECE_COLOR_VERDICTS_SQL))
    db.execute(text(migration.PIECE_PART_VERDICTS_SQL))
    db.commit()
    try:
        _check_verdict_views(client, db, machine_token, test_machine, test_user)
    finally:
        _drop_views(db)


def _drop_views(db: Session) -> None:
    for view in ("piece_color_verdicts", "piece_part_verdicts"):
        db.execute(text(f"DROP VIEW IF EXISTS {view}"))
    db.commit()


def _check_verdict_views(client, db, machine_token, test_machine, test_user) -> None:
    _post(client, machine_token, "piece-records", [
        _record("x", 1, sync_seq=1, color_corrected_id="85", part_correct=False, correction_updated_at=BASE),
        _record("y", 2, sync_seq=2),
    ])
    user = db.query(User).filter(User.email == test_user["email"]).one()
    machine_id = UUID(test_machine["id"])
    db.add(PieceColorLabel(machine_id=machine_id, piece_uuid="x", labeler_id=user.id, color_id=86))
    db.add(PieceColorLabel(machine_id=machine_id, piece_uuid="y", labeler_id=user.id, color_id=None, cant_tell=True))
    db.add(PiecePartLabel(machine_id=machine_id, piece_uuid="y", labeler_id=user.id, part_num="3001"))
    db.commit()

    colors = db.execute(text(
        "SELECT source, piece_uuid, color_id, cant_tell, machine_color_id FROM piece_color_verdicts "
        "ORDER BY piece_uuid, source"
    )).all()
    assert [(r[0], r[1], r[2], bool(r[3]), r[4]) for r in colors] == [
        ("hive", "x", "86", False, "11"),
        ("machine", "x", "85", False, "11"),
        ("hive", "y", None, True, "11"),
    ]
    parts = db.execute(text(
        "SELECT source, piece_uuid, part_num, part_correct, machine_part_id FROM piece_part_verdicts "
        "ORDER BY piece_uuid, source"
    )).all()
    assert [(r[0], r[1], r[2], None if r[3] is None else bool(r[3]), r[4]) for r in parts] == [
        ("machine", "x", None, False, "3001"),
        ("hive", "y", "3001", True, "3001"),
    ]
    owner = db.execute(text("SELECT verdict_by FROM piece_color_verdicts WHERE source = 'machine'")).scalar()
    assert UUID(str(owner)) == user.id
