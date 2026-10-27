"""Training runs from sorters: the training fields on piece records, the
training_runs sync, the counts kept on each run, the labeling-queue flag the
sync keeps, the piece panel's run and the machine page's list.

How the piece grid orders training-labelled pieces: test_labeling_queue.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.models.labeling_queue import LabelingQueueEntry
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_training_run import MachineTrainingRun
from app.models.user import User
from app.services import training_runs
from tests.conftest import TestingSessionLocal

BASE = 1_760_000_000.0
COLORS = {
    "5": {"id": 5, "name": "Red", "rgb": "C91A09"},
    "7": {"id": 7, "name": "Blue", "rgb": "0055BF"},
    "11": {"id": 11, "name": "Black", "rgb": "05131D"},
}


@pytest.fixture(autouse=True)
def _palette(monkeypatch):
    monkeypatch.setattr(training_runs, "palette", lambda: COLORS)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(client, token: str, path: str, records: list) -> dict:
    resp = client.post(f"/api/machine/sync/{path}", headers=_bearer(token), json={"records": records})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _record(piece_uuid: str, seq: int, run: str | None = "run-a", color: str | None = "5", **fields) -> dict:
    rec = {
        "piece_uuid": piece_uuid, "local_id": seq, "sync_seq": seq, "seen_at": BASE + seq,
        "recorded_at": BASE + seq + 1, "classification_status": "classified", "part_id": "3001", "color_id": "11",
        "training_run_uuid": run, "training_segment_uuid": f"{run}-seg-1" if run else None,
        "training_color_id": color if run else None,
        "training_label_source": "run" if run and color else None, "training_excluded": False,
        "training_updated_at": BASE + seq + 2 if run else None,
    }
    rec.update(fields)
    return rec


def _run(run_uuid: str, seq: int, **fields) -> dict:
    row = {
        "run_uuid": run_uuid, "sync_seq": seq, "mode": "color", "color_ids": ["5"], "started_at": BASE,
        "ended_at": None, "excluded": False, "updated_at": BASE,
        "segments": [{"segment_uuid": f"{run_uuid}-seg-1", "color_ids": ["5"], "started_at": BASE, "ended_at": None}],
    }
    row.update(fields)
    return row


def _runs() -> dict[str, tuple]:
    s: Session = TestingSessionLocal()
    try:
        return {
            r.run_uuid: (r.piece_count, r.labeled_count, r.excluded_count, bool(r.excluded))
            for r in s.query(MachineTrainingRun)
        }
    finally:
        s.close()


def _piece(piece_uuid: str) -> MachinePiece:
    s: Session = TestingSessionLocal()
    try:
        return s.query(MachinePiece).filter_by(piece_uuid=piece_uuid).one()
    finally:
        s.close()


# --- Sync -------------------------------------------------------------------------------


def test_records_carry_the_training_fields_and_older_sorters_still_sync(client, machine_token):
    _post(client, machine_token, "piece-records", [
        _record("a", 1, training_label_source="prediction"),
        # A sorter without training mode sends none of them.
        {"piece_uuid": "old", "local_id": 2, "sync_seq": 2, "seen_at": BASE, "part_id": "3001"},
    ])
    a = _piece("a")
    assert (a.training_run_uuid, a.training_segment_uuid, a.training_color_id, a.training_label_source) == (
        "run-a", "run-a-seg-1", "5", "prediction",
    )
    assert a.training_excluded is False
    assert a.training_updated_at is not None
    old = _piece("old")
    assert (old.training_run_uuid, old.training_color_id, old.training_excluded) == (None, None, False)
    # The sorter owns them: the next record overwrites them.
    _post(client, machine_token, "piece-records", [_record("a", 3, training_excluded=True)])
    assert _piece("a").training_excluded is True


def test_training_runs_sync_by_sync_seq(client, machine_token):
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["training_runs"] == {"max_local_id": 0}
    two_segments = [
        {"segment_uuid": "s1", "color_ids": ["5"], "started_at": BASE, "ended_at": BASE + 300},
        {"segment_uuid": "s2", "color_ids": ["7"], "started_at": BASE + 300, "ended_at": None},
    ]
    out = _post(client, machine_token, "training-runs", [
        _run("run-a", 4),
        # The same run twice in a batch: the later one wins.
        _run("run-a", 6, ended_at=BASE + 600, color_ids=["5", "7"], segments=two_segments),
        # A bad row is skipped and the watermark still moves past it.
        {"run_uuid": "bad", "sync_seq": 9, "mode": "color"},
    ])
    assert out == {"max_local_id": 9, "upserted": 2, "skipped": 1}
    s: Session = TestingSessionLocal()
    try:
        run = s.query(MachineTrainingRun).one()
        assert run.color_ids == ["5", "7"] and run.ended_at is not None and run.mode == "color"
        assert [(seg["segment_uuid"], seg["color_ids"], seg["ended_at"] is None) for seg in run.segments] == [
            ("s1", ["5"], False), ("s2", ["7"], True),
        ]
    finally:
        s.close()
    # A re-send upserts in place, segments too; the watermark never goes back.
    assert _post(client, machine_token, "training-runs", [_run("run-a", 6, excluded=True)])["max_local_id"] == 9
    assert _runs()["run-a"][3] is True
    # A sorter from before runs had segments sends none.
    legacy = {k: v for k, v in _run("run-b", 10).items() if k != "segments"}
    assert _post(client, machine_token, "training-runs", [legacy])["upserted"] == 1
    s = TestingSessionLocal()
    try:
        segments = {r.run_uuid: r.segments for r in s.query(MachineTrainingRun)}
        assert [seg["segment_uuid"] for seg in segments["run-a"]] == ["run-a-seg-1"] and segments["run-b"] == []
    finally:
        s.close()
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert state["training_runs"] == {"max_local_id": 10}


def test_run_counts_are_kept_whichever_arrives_first(client, machine_token):
    # Pieces before their run: the run's first sync counts them.
    _post(client, machine_token, "piece-records", [
        _record("a", 1), _record("b", 2), _record("c", 3, color=None), _record("d", 4, training_excluded=True),
    ])
    _post(client, machine_token, "training-runs", [_run("run-a", 5)])
    assert _runs()["run-a"] == (4, 2, 1, False)
    # Pieces after it: each batch recounts the runs it touches.
    _post(client, machine_token, "piece-records", [_record("e", 6), _record("a", 7, training_excluded=True)])
    assert _runs()["run-a"] == (5, 2, 2, False)
    # A piece that leaves a run is taken off that run's counts.
    _post(client, machine_token, "training-runs", [_run("run-b", 8)])
    _post(client, machine_token, "piece-records", [_record("e", 9, run="run-b")])
    assert _runs() == {"run-a": (4, 1, 2, False), "run-b": (1, 1, 0, False)}


def test_the_sync_keeps_a_queued_pieces_flag(client, db, machine_token, test_machine):
    machine_id = UUID(test_machine["id"])
    _post(client, machine_token, "piece-records", [_record("a", 1, run=None), _record("b", 2)])
    for puid in ("a", "b"):
        db.add(LabelingQueueEntry(machine_id=machine_id, piece_uuid=puid, arrival_at=datetime.now(timezone.utc)))
    db.commit()

    def flagged() -> set[str]:
        db.expire_all()
        return {e.piece_uuid for e in db.query(LabelingQueueEntry).filter(LabelingQueueEntry.has_training_label.is_(True))}

    _post(client, machine_token, "piece-records", [_record("a", 3), _record("b", 4)])
    assert flagged() == {"a", "b"}
    _post(client, machine_token, "piece-records", [_record("b", 5, training_excluded=True)])
    assert flagged() == {"a"}
    _post(client, machine_token, "training-runs", [_run("run-a", 6, excluded=True)])
    assert flagged() == set()
    _post(client, machine_token, "training-runs", [_run("run-a", 7)])
    assert flagged() == {"a"}
    _post(client, machine_token, "piece-records", [_record("a", 8, run=None)])
    assert flagged() == set()


# --- The piece panel and the machine page --------------------------------------------------


def test_the_piece_panel_shows_its_run(client, machine_token, test_machine):
    segments = [
        {"segment_uuid": "s1", "color_ids": ["11"], "started_at": BASE, "ended_at": BASE + 300},
        {"segment_uuid": "s2", "color_ids": ["5", "7"], "started_at": BASE + 300, "ended_at": BASE + 600},
    ]
    _post(client, machine_token, "training-runs", [
        _run("run-a", 1, color_ids=["11", "5", "7"], ended_at=BASE + 600, segments=segments),
    ])
    _post(client, machine_token, "piece-records", [
        _record("a", 2, color="7", training_label_source="prediction", training_segment_uuid="s2"),
        _record("plain", 3, run=None),
        _record("no-segment", 4, training_segment_uuid=None),
    ])
    body = client.get(f"/api/labeling/piece/{test_machine['id']}/a").json()
    run = body["training_run"]
    assert run["run_uuid"] == "run-a" and run["mode"] == "color"
    assert run["color_ids"] == ["11", "5", "7"]
    assert [c["name"] for c in run["colors"]] == ["Black", "Red", "Blue"]
    # The piece's own segment: the colours being fed when it was seen.
    assert run["segment"]["segment_uuid"] == "s2"
    assert [c["name"] for c in run["segment"]["colors"]] == ["Red", "Blue"]
    assert run["segment"]["started_at"].startswith(datetime.fromtimestamp(BASE + 300, timezone.utc).isoformat()[:19])
    assert (run["color_id"], run["color_name"], run["label_source"]) == ("7", "Blue", "prediction")
    assert (run["excluded"], run["run_excluded"], run["counts"]) == (False, False, True)
    assert run["started_at"] and run["ended_at"]
    assert client.get(f"/api/labeling/piece/{test_machine['id']}/plain").json()["training_run"] is None
    assert client.get(f"/api/labeling/piece/{test_machine['id']}/no-segment").json()["training_run"]["segment"] is None


def test_the_machine_page_lists_runs_newest_first(client, db, machine_token, test_machine):
    _post(client, machine_token, "training-runs", [
        _run(f"run-{i}", i + 1, started_at=BASE + i * 3600, ended_at=BASE + i * 3600 + 600) for i in range(5)
    ])
    _post(client, machine_token, "piece-records", [_record("a", 10, run="run-4"), _record("b", 11, run="run-4")])
    url = f"/api/machines/{test_machine['id']}/training-runs"
    seen, cursor = [], None
    for _ in range(5):
        body = client.get(url, params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen.extend(body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert [r["run_uuid"] for r in seen] == [f"run-{i}" for i in range(4, -1, -1)]
    newest = seen[0]
    assert (newest["pieces"], newest["labeled"], newest["excluded_pieces"]) == (2, 2, 0)
    assert newest["colors"] == [{"id": "5", "name": "Red", "rgb": "C91A09"}]
    assert client.get(url, params={"cursor": "nonsense"}).status_code == 400

    # The owner's and admins' only.
    other = User(email="someone@test.com", display_name="Someone", role="member")
    db.add(other)
    db.commit()
    machine = db.get(Machine, UUID(test_machine["id"]))
    machine.owner_id = other.id
    db.commit()
    assert client.get(url).status_code == 404
