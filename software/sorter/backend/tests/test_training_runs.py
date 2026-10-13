from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
import hive_metadata_cache
import piece_predictions
import piece_records
import training_runs
from server import hive_sync
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


class _Clock:
    def __init__(self) -> None:
        self.now = time.time() - 10_000

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    c = _Clock()
    with patch.object(training_runs.time, "time", c):
        yield c


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


def test_a_run_lasts_until_it_is_ended_and_a_color_change_starts_a_segment(clock) -> None:
    t0 = clock.now
    training_runs.setConfig(enabled=True, color_ids=["5"])
    _record("before", t0 - 5)
    run = training_runs.startRun()
    _record("red", t0 + 1)
    clock.now = t0 + 10
    training_runs.setConfig(color_ids=["11"])  # mid-run: the next segment
    _record("left-over", t0 + 9)  # seen before the change, recorded after it
    _record("black", t0 + 12)
    clock.now = t0 + 20
    training_runs.endRun(run["id"])
    _record("after", t0 + 25)

    run = training_runs.getRun(run["id"])
    assert (run["started_at"], run["ended_at"], run["collecting"]) == (t0, t0 + 20, False)
    assert run["color_ids"] == ["5", "11"]
    red, black = run["segments"]
    assert (red["color_ids"], red["started_at"], red["ended_at"], red["pieces"]) == (["5"], t0, t0 + 10, 2)
    assert (black["color_ids"], black["started_at"], black["ended_at"], black["pieces"]) == (["11"], t0 + 10, t0 + 20, 1)
    assert (run["pieces"], run["labeled"]) == (3, 3)
    assert _row("red")["training_color_id"] == "5" and _row("red")["training_label_source"] == "run"
    assert _row("left-over")["training_color_id"] == "5"
    assert (_row("black")["training_color_id"], _row("black")["training_segment_id"]) == ("11", black["id"])
    assert _row("before")["training_run_id"] is None
    assert _row("after")["training_run_id"] is None


def test_starting_needs_training_mode_a_color_and_no_open_run(clock) -> None:
    with pytest.raises(training_runs.TrainingError) as off:
        training_runs.startRun()
    assert off.value.status == 400
    training_runs.setConfig(enabled=True)
    with pytest.raises(training_runs.TrainingError) as no_color:
        training_runs.startRun()
    assert no_color.value.status == 400
    training_runs.setConfig(color_ids=["5"])
    run = training_runs.startRun()
    with pytest.raises(training_runs.TrainingError) as twice:
        training_runs.startRun()
    assert twice.value.status == 409
    with pytest.raises(training_runs.TrainingError):
        training_runs.setConfig(color_ids=[])  # end the run instead
    assert training_runs.openRun()["id"] == run["id"]

    # Turning training mode off ends the run.
    clock.now += 5
    training_runs.setConfig(enabled=False)
    assert training_runs.openRun() is None
    assert training_runs.getRun(run["id"])["ended_at"] == clock.now


def test_several_colors_label_by_prediction_then_by_the_nearest(clock) -> None:
    hive_metadata_cache.put_cached_palette(PALETTE)
    t0 = clock.now
    training_runs.setConfig(enabled=True, color_ids=["5", "1"])
    training_runs.startRun()
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


def test_excluding_resends_the_piece_and_a_label_survives_the_distribution_write(clock) -> None:
    t0 = clock.now
    training_runs.setConfig(enabled=True, color_ids=["5"])
    run = training_runs.startRun()
    _record("a", t0 + 1, color_id="5")
    _record("b", t0 + 2, color_id="11")
    seq_before = _row("b")["sync_seq"]

    piece = training_runs.setPieceExcluded("b", True)
    assert piece is not None and piece["training_excluded"] and piece["segment_id"]
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


def test_a_run_from_before_segments_becomes_one_segment(clock) -> None:
    t0 = clock.now
    _record("x", t0 - 100)  # makes the tables
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO training_runs (uuid, mode, color_ids, started_at, ended_at, updated_at, sync_seq) "
            "VALUES ('old', 'color', '[\"115\"]', ?, ?, ?, 1)",
            (t0, t0 + 50, t0 + 50),
        )
        conn.execute("UPDATE piece_records SET training_run_id = 'old', training_color_id = '115' WHERE uuid = 'x'")
        conn.commit()
    db._prepared.clear()  # the next process
    run = training_runs.getRun("old")
    [segment] = run["segments"]
    assert (segment["color_ids"], segment["started_at"], segment["ended_at"]) == (["115"], t0, t0 + 50)
    assert _row("x")["training_segment_id"] == segment["id"]


class _FakeClient:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.records: list[dict] = []

    def pushTrainingRuns(self, runs: list[dict]) -> int:
        self.runs.extend(runs)
        return max(r["sync_seq"] for r in runs)

    def pushPieceRecords(self, records: list[dict]) -> int:
        self.records.extend(records)
        return max(r["sync_seq"] for r in records)


def test_runs_and_labels_go_to_hive(clock) -> None:
    t0 = clock.now
    training_runs.setConfig(enabled=True, color_ids=["5"])
    run = training_runs.startRun()
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
    [segment] = sent_run["segments"]
    assert (segment["color_ids"], segment["started_at"], segment["ended_at"]) == (["5"], t0, None)
    [record] = client.records
    assert (record["training_run_uuid"], record["training_segment_uuid"]) == (run["id"], segment["segment_uuid"])
    assert (record["training_color_id"], record["training_label_source"], record["training_excluded"]) == ("5", "run", False)
    assert not syncer._drainTrainingRuns()
    training_runs.setConfig(color_ids=["11"])  # a new segment resends the run
    assert syncer._drainTrainingRuns() and len(client.runs[-1]["segments"]) == 2
    assert hive_sync.TELEMETRY_FIELD[hive_sync.DATA_TYPE_TRAINING_RUNS] == "piece_metadata"


def test_the_api() -> None:
    hive_metadata_cache.put_cached_palette(PALETTE)
    app = FastAPI()
    app.include_router(training_router.router)
    client = TestClient(app)

    assert client.post("/api/training/runs").status_code == 400  # training mode is off
    body = client.post("/api/training/config", json={"enabled": True, "color_ids": ["5"]}).json()
    assert body["config"]["colors"] == [{"id": "5", "name": "Red", "rgb": "C91A09"}]
    assert body["current_run"] is None
    assert client.post("/api/training/config", json={"color_ids": ["x"]}).status_code == 400

    started = client.post("/api/training/runs").json()["current_run"]
    assert started["segments"][0]["colors"][0]["name"] == "Red"
    assert client.post("/api/training/runs").status_code == 409
    _record("a", time.time() + 1)
    page = client.get(f"/api/training/runs/{started['id']}").json()
    assert page["total"] == 1
    assert page["pieces"][0]["training_color_name"] == "Red"
    assert page["pieces"][0]["segment_id"] == started["segments"][0]["id"]
    assert page["pieces"][0]["image_id"] is None
    assert client.post("/api/training/pieces/a", json={"excluded": True}).json()["training_excluded"]
    assert client.patch(f"/api/training/runs/{started['id']}", json={"excluded": True}).json()["excluded"]

    switched = client.post("/api/training/config", json={"color_ids": ["11"]}).json()["current_run"]
    assert [s["colors"][0]["name"] for s in switched["segments"]] == ["Red", "Black"]
    ended = client.post(f"/api/training/runs/{started['id']}/end").json()
    assert ended["current_run"] is None and ended["runs"][0]["ended_at"] is not None
    assert client.get("/api/training/runs/nope").status_code == 404
    assert client.post("/api/training/runs/nope/end").status_code == 404


def test_a_fixed_bin_holds_every_piece_while_training_mode_is_on() -> None:
    from subsystems.distribution.chute import BinAddress
    from subsystems.distribution.positioning import Positioning

    def layout(bins: int) -> SimpleNamespace:
        section = SimpleNamespace(enabled=True, bins=[SimpleNamespace() for _ in range(bins)])
        return SimpleNamespace(layers=[SimpleNamespace(enabled=True, sections=[section, section])])

    warnings: list[str] = []
    positioning = SimpleNamespace(
        layout=layout(3),
        chute=SimpleNamespace(isBinReachable=lambda address: True),
        _isLayerUsable=lambda layer_index: True,
        logger=SimpleNamespace(warning=warnings.append),
    )
    pick = lambda: Positioning._trainingBinAddress(positioning)  # noqa: E731

    training_runs.setConfig(enabled=True, bin={"layer": 0, "section": 1, "bin": 2})
    assert training_runs.getConfig()["bin"] == {"layer": 0, "section": 1, "bin": 2}
    assert pick() == BinAddress(0, 1, 2)

    positioning.layout = layout(2)  # that bin is gone: route by the profile
    assert pick() is None and pick() is None
    assert len(warnings) == 1

    training_runs.setConfig(enabled=False)
    assert training_runs.fixedBin() is None
    training_runs.setConfig(enabled=True, bin=None)
    assert training_runs.fixedBin() is None
    with pytest.raises(training_runs.TrainingError):
        training_runs.setConfig(bin={"layer": -1, "section": 0, "bin": 0})


def test_the_api_sets_and_clears_the_bin() -> None:
    app = FastAPI()
    app.include_router(training_router.router)
    client = TestClient(app)

    body = client.post("/api/training/config", json={"bin": {"layer": 2, "section": 5, "bin": 1}}).json()
    assert body["config"]["bin"] == {"layer": 2, "section": 5, "bin": 1}
    kept = client.post("/api/training/config", json={"enabled": True}).json()
    assert kept["config"]["bin"] == {"layer": 2, "section": 5, "bin": 1}
    assert client.post("/api/training/config", json={"bin": None}).json()["config"]["bin"] is None
