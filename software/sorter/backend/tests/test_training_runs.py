from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
import hive_metadata_cache
import piece_predictions
import piece_records
import training_runs
from defs.sorter_controller import SorterLifecycle
from server import hive_sync, shared_state
from server.routers import training as training_router

PALETTE = [
    {"id": 1, "name": "White", "rgb": "FFFFFF", "is_trans": False},
    {"id": 4, "name": "Orange", "rgb": "FE8A18", "is_trans": False},
    {"id": 5, "name": "Red", "rgb": "C91A09", "is_trans": False},
    {"id": 11, "name": "Black", "rgb": "212121", "is_trans": False},
]


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))


def _record(piece_uuid: str, seen_at: float, color_id: str = "11") -> None:
    piece_records.recordPiece(
        {
            "uuid": piece_uuid,
            "classification_status": "classified",
            "created_at": seen_at,
            "color_id": color_id,
            "color_name": "Black",
        },
        run_id="process",
    )


def _row(piece_uuid: str) -> dict:
    with db.connect() as conn:
        return dict(conn.execute("SELECT * FROM piece_records WHERE uuid = ?", (piece_uuid,)).fetchone())


def _startRun(color_ids: list[str], at: float) -> dict:
    training_runs.setConfig(enabled=True, color_ids=color_ids, running=False)
    training_runs.reconcile(True, at)
    run = training_runs.openRun()
    assert run is not None
    return run


def test_a_run_holds_the_pieces_seen_while_the_machine_ran() -> None:
    t0 = time.time() - 1000
    training_runs.setConfig(enabled=True, color_ids=["5"], running=False)
    assert training_runs.openRun() is None
    _record("before", t0 - 5)
    training_runs.reconcile(True, t0)
    _record("during", t0 + 1)
    training_runs.reconcile(False, t0 + 10)
    # Seen during the run, distributed after it ended.
    _record("in-flight", t0 + 5)
    _record("after", t0 + 20)

    [run] = training_runs.listRuns()
    assert (run["started_at"], run["ended_at"], run["collecting"]) == (t0, t0 + 10, False)
    assert (run["pieces"], run["labeled"], run["excluded_pieces"]) == (2, 2, 0)
    assert _row("during")["training_color_id"] == "5"
    assert _row("during")["training_label_source"] == "run"
    assert _row("in-flight")["training_run_id"] == run["id"]
    assert _row("before")["training_run_id"] is None
    assert _row("after")["training_run_id"] is None


def test_resuming_starts_a_new_run_and_colours_lock_while_one_collects() -> None:
    t0 = time.time() - 1000
    first = _startRun(["5"], t0)
    with pytest.raises(training_runs.TrainingError) as refused:
        training_runs.setConfig(color_ids=["11"], running=True)
    assert refused.value.status == 409
    training_runs.reconcile(True, t0 + 1)  # still running: no second run
    assert [r["id"] for r in training_runs.listRuns()] == [first["id"]]

    training_runs.reconcile(False, t0 + 10)
    training_runs.reconcile(True, t0 + 20)
    second = training_runs.openRun()
    assert second is not None and second["id"] != first["id"]

    # Turning training mode off ends the run at once.
    training_runs.setConfig(enabled=False, running=True)
    assert training_runs.openRun() is None
    assert training_runs.getRun(second["id"])["ended_at"] is not None


def test_several_colours_label_by_prediction_then_by_the_nearest() -> None:
    hive_metadata_cache.put_cached_palette(PALETTE)
    t0 = time.time() - 1000
    _startRun(["5", "1"], t0)
    piece_predictions.recordPredictions("predicted", [
        {"request": "combined", "provider": "brickognize", "model": None, "kind": "color", "rank": rank,
         "value_id": value, "value_name": None, "score": score, "applied": True, "created_at": t0}
        for rank, (value, score) in enumerate([("11", 0.6), ("1", 0.3)])
    ])
    _record("predicted", t0 + 1, color_id="11")
    _record("orange", t0 + 2, color_id="4")
    _record("unknown", t0 + 3, color_id="999")

    assert (_row("predicted")["training_color_id"], _row("predicted")["training_label_source"]) == ("1", "prediction")
    assert (_row("orange")["training_color_id"], _row("orange")["training_label_source"]) == ("5", "nearest")
    assert _row("unknown")["training_color_id"] is None
    assert training_runs.openRun()["labeled"] == 2


def test_excluding_resends_the_piece_and_a_label_survives_the_distribution_write() -> None:
    t0 = time.time() - 1000
    run = _startRun(["5"], t0)
    _record("a", t0 + 1, color_id="5")
    _record("b", t0 + 2, color_id="11")
    seq_before = _row("b")["sync_seq"]

    piece = training_runs.setPieceExcluded("b", True)
    assert piece is not None and piece["training_excluded"]
    assert _row("b")["sync_seq"] > seq_before
    _record("b", t0 + 2, color_id="11")  # distributed again later
    assert (_row("b")["training_excluded"], _row("b")["training_run_id"]) == (1, run["id"])

    counts = training_runs.getRun(run["id"])
    assert (counts["pieces"], counts["labeled"], counts["excluded_pieces"]) == (2, 1, 1)
    assert [p["uuid"] for p in training_runs.listRunPieces(run["id"], filter_name="excluded")[0]] == ["b"]
    assert training_runs.listRunPieces(run["id"], filter_name="disagree")[0] == []
    training_runs.setPieceExcluded("b", False)
    assert [p["uuid"] for p in training_runs.listRunPieces(run["id"], filter_name="disagree")[0]] == ["b"]
    assert training_runs.setPieceExcluded("not-in-a-run", True) is None

    run_seq = training_runs.listRunsAfter(0, 10)[0]["sync_seq"]
    assert training_runs.setRunExcluded(run["id"], True)["excluded"]
    assert training_runs.listRunsAfter(run_seq, 10)[0]["excluded"] is True


def test_a_run_left_open_by_a_crash_ends_at_its_last_piece() -> None:
    t0 = time.time() - 1000
    run = _startRun(["5"], t0)
    _record("last", t0 + 7)
    db._prepared.discard((db.local_state_db_path(), training_runs._createTables))
    assert training_runs.getRun(run["id"])["ended_at"] == t0 + 7


class _FakeClient:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.records: list[dict] = []

    def getSyncState(self) -> dict:
        return {}

    def pushTrainingRuns(self, runs: list[dict]) -> int:
        self.runs.extend(runs)
        return max(r["sync_seq"] for r in runs)

    def pushPieceRecords(self, records: list[dict]) -> int:
        self.records.extend(records)
        return max(r["sync_seq"] for r in records)

    def pushPiecePredictions(self, records: list[dict]) -> int:
        return max(r["local_id"] for r in records)


def test_runs_and_labels_go_to_hive(monkeypatch) -> None:
    t0 = time.time() - 1000
    run = _startRun(["5"], t0)
    _record("a", t0 + 1)
    client = _FakeClient()
    syncer = hive_sync._TargetSyncer.__new__(hive_sync._TargetSyncer)
    syncer._client = client
    syncer._gate = hive_sync._ConcurrencyGate(1, 1, lambda: False)
    syncer._wm = {t: 0 for t in hive_sync.DATA_TYPES}
    syncer._stop = threading.Event()

    assert syncer._drainTrainingRuns() and syncer._drainRecords()
    [sent_run] = client.runs
    assert (sent_run["run_uuid"], sent_run["color_ids"], sent_run["ended_at"]) == (run["id"], ["5"], None)
    [record] = client.records
    assert (record["training_run_uuid"], record["training_color_id"]) == (run["id"], "5")
    assert (record["training_label_source"], record["training_excluded"]) == ("run", False)
    assert not syncer._drainTrainingRuns()
    assert hive_sync.TELEMETRY_FIELD[hive_sync.DATA_TYPE_TRAINING_RUNS] == "piece_metadata"


def test_the_api(monkeypatch) -> None:
    hive_metadata_cache.put_cached_palette(PALETTE)
    app = FastAPI()
    app.include_router(training_router.router)
    client = TestClient(app)
    controller = SimpleNamespace(state=SorterLifecycle.PAUSED)
    monkeypatch.setattr(shared_state, "controller_ref", controller)

    body = client.post("/api/training/config", json={"enabled": True, "color_ids": ["5"]}).json()
    assert body["config"]["colors"] == [{"id": "5", "name": "Red", "rgb": "C91A09"}]
    assert body["current_run"] is None
    assert client.post("/api/training/config", json={"color_ids": ["x"]}).status_code == 400

    controller.state = SorterLifecycle.RUNNING
    training_runs.reconcile(True, time.time() - 60)
    run_id = client.get("/api/training").json()["current_run"]["id"]
    refused = client.post("/api/training/config", json={"color_ids": ["11"]})
    assert refused.status_code == 409 and "Pause" in refused.json()["detail"]

    _record("a", time.time() - 30)
    page = client.get(f"/api/training/runs/{run_id}").json()
    assert page["total"] == 1
    assert page["pieces"][0]["training_color_name"] == "Red"
    assert page["pieces"][0]["image_id"] is None
    assert client.post("/api/training/pieces/a", json={"excluded": True}).json()["training_excluded"]
    assert client.patch(f"/api/training/runs/{run_id}", json={"excluded": True}).json()["excluded"]
    assert client.get("/api/training/runs/nope").status_code == 404
