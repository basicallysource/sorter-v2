"""Every colour model's answer for a piece: the color_model_run job, the
backfill that queues it, and the answers it keeps. The network and storage are
stubbed; the crop choice, batching, storing and queueing run for real.

The grid's sorts by a model's confidence: test_labeling_queue.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pytest

from app.models.color_model import ColorModel
from app.models.job import Job
from app.models.labeling_queue import LabelingQueueEntry
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_piece_prediction import MachinePiecePrediction
from app.models.piece_model_output import PieceModelColor
from app.models.user import User
from app.services import color_model_runs, color_predictor, job_queue
from tests.conftest import TestingSessionLocal, _auth_headers

OLD = "a" * 64
NEW = "b" * 64
CLASSES = [5, 7, 11, 1]
NOW = datetime.now(timezone.utc)


@pytest.fixture()
def models(db, monkeypatch):
    """Two registered models, the newer one active; a fake network that reads
    each crop's colour from its bytes (b"5", b"7", ...), and storage that
    hands back the crop's key's last part as its bytes."""
    db.add(ColorModel(filename="colorpred-v1.onnx", name="colorpred-v1", sha256=OLD, created_at=NOW - timedelta(days=30)))
    db.add(ColorModel(filename="colorpred-v3.onnx", name="colorpred-v3", sha256=NEW, is_active=True, created_at=NOW))
    db.commit()
    loads: list[str] = []

    def fake_load(filename, threads=2, low_memory=False):
        sha = NEW if "v3" in filename else OLD
        loads.append(sha)
        return SimpleNamespace(class_ids=CLASSES, sha=sha)

    def fake_probabilities(loaded, blobs, channels):
        votes = np.full(len(CLASSES), 0.01)
        for blob in blobs:
            votes[CLASSES.index(int(blob))] += 1.0
        # The older model is less sure of everything.
        if loaded.sha == OLD:
            votes += 0.5
        return votes / votes.sum()

    monkeypatch.setattr(job_queue, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(color_model_runs, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(job_queue, "_worker", job_queue.JobWorker())
    monkeypatch.setattr(color_predictor, "load_file", fake_load)
    monkeypatch.setattr(color_model_runs, "_slot", None)
    monkeypatch.setattr(color_predictor, "class_probabilities", fake_probabilities)
    monkeypatch.setattr(color_model_runs, "read_many", lambda keys: {k: k.rsplit("/", 1)[-1].encode() for k in keys})
    monkeypatch.setattr(color_model_runs, "_palette", lambda: {5: {"id": 5, "name": "Red", "rgb": "C91A09"}})
    return SimpleNamespace(loads=loads)


def _piece(db, machine_id: UUID, puid: str, crops: list[tuple], *, palette: bool = False, minutes: int = 0) -> None:
    """A queued piece with crops whose bytes say their colour: (colour, used)
    on C4, or (colour, used, channel)."""
    db.add(MachinePiece(machine_id=machine_id, piece_uuid=puid, local_id=1, seen_at=NOW - timedelta(minutes=minutes)))
    for seq, (color, used, *channel) in enumerate(crops):
        db.add(
            MachinePieceImage(
                machine_id=machine_id, piece_uuid=puid, seq=seq, local_id=seq, channel=channel[0] if channel else 4,
                used=used, image_key=f"{machine_id}/{puid}/{seq}/{color}",
            )
        )
    db.add(
        LabelingQueueEntry(
            machine_id=machine_id, piece_uuid=puid, arrival_at=NOW - timedelta(minutes=minutes), has_palette=palette
        )
    )
    db.commit()


def _answers(db) -> dict[tuple[str, str], PieceModelColor]:
    db.expire_all()
    return {(r.piece_uuid, r.model_sha256): r for r in db.query(PieceModelColor)}


def _run_all() -> int:
    worker = job_queue.get_job_worker()
    n = 0
    while worker.run_once("test"):
        n += 1
    return n


def test_a_batch_keeps_each_models_answer_from_the_pieces_chosen_crops(db, test_machine, models):
    machine_id = UUID(test_machine["id"])
    # The machine used one crop, an empty frame (white); every C4 crop is read,
    # so the three red ones decide. The C3 crop is not the colour camera's.
    _piece(db, machine_id, "a", [("1", True), ("5", False), ("5", False), ("5", False), ("7", False, 3)])
    # Eight at most, used or not.
    _piece(db, machine_id, "b", [("7", False)] * 9 + [("5", True)])
    db.add(MachinePiece(machine_id=machine_id, piece_uuid="no-crops", local_id=2))
    db.commit()

    out = color_model_runs.run_batch(db, NEW, machine_id, ["a", "b", "no-crops", "gone"])
    assert out == {"model": "colorpred-v3", "pieces": 4, "answered": 2}
    answers = _answers(db)
    a = answers[("a", NEW)]
    assert (a.color_id, a.model_name, a.seqs) == (5, "colorpred-v3", [0, 1, 2, 3])
    assert a.confidence == pytest.approx(3.01 / 4.04)
    assert [t["color_id"] for t in a.top][:1] == [5] and len(a.top) == 3
    b = answers[("b", NEW)]
    assert (b.color_id, b.seqs) == (7, [0, 1, 2, 3, 4, 5, 6, 7])

    # Another model's answer sits beside it; running a model again replaces its own.
    color_model_runs.run_batch(db, OLD, machine_id, ["a"])
    color_model_runs.run_batch(db, NEW, machine_id, ["a"])
    answers = _answers(db)
    assert set(answers) == {("a", NEW), ("b", NEW), ("a", OLD)}
    assert answers[("a", OLD)].confidence < answers[("a", NEW)].confidence


def test_backfill_queues_each_models_batches_and_skips_what_is_answered(client, db, test_machine, models):
    machine_id = UUID(test_machine["id"])
    for i in range(25):
        _piece(db, machine_id, f"p{i:02d}", [("5", True)], palette=i < 22, minutes=i)

    out = color_model_runs.backfill(db, machine_id=machine_id, with_palette=True)
    assert out["pieces"] == 22 and not out["truncated"]
    assert [(m["name"], m["pieces"], m["jobs"]) for m in out["models"]] == [("colorpred-v3", 22, 2), ("colorpred-v1", 22, 2)]
    jobs = db.query(Job).filter(Job.kind == color_model_runs.KIND).order_by(Job.created_at).all()
    assert [len(j.payload["pieces"]) for j in jobs] == [20, 2, 20, 2]
    assert {j.priority for j in jobs} == {color_model_runs.BACKFILL_PRIORITY}
    # Queued again before they ran: the same batches are not queued twice.
    assert [m["jobs"] for m in color_model_runs.backfill(db, machine_id=machine_id, with_palette=True)["models"]] == [0, 0]

    assert _run_all() == 4
    assert len(_answers(db)) == 44
    # One model's batches run together: each model is loaded once.
    assert models.loads == [NEW, OLD]

    # Every piece now: only the three the models have not answered are queued.
    out = color_model_runs.backfill(db, machine_id=machine_id, model_sha256s=[OLD])
    assert [(m["name"], m["pieces"], m["jobs"]) for m in out["models"]] == [("colorpred-v1", 3, 1)]
    out = color_model_runs.backfill(db, machine_id=machine_id, model_sha256s=[NEW], rerun=True)
    assert out["models"][0]["pieces"] == 25
    with pytest.raises(ValueError):
        color_model_runs.backfill(db, machine_id=machine_id, model_sha256s=["c" * 64])


def test_a_model_gone_from_the_registry_fails_its_jobs_for_good(db, test_machine, models):
    machine_id = UUID(test_machine["id"])
    _piece(db, machine_id, "a", [("5", True)])
    color_model_runs.backfill(db, machine_id=machine_id, model_sha256s=[OLD])
    db.query(ColorModel).filter(ColorModel.sha256 == OLD).delete()
    db.commit()
    _run_all()
    db.expire_all()
    [job] = db.query(Job).filter(Job.kind == color_model_runs.KIND).all()
    assert job.status == "failed" and job.attempts == 1


def test_the_backfill_endpoint_is_for_admins(client, db, test_machine, models, monkeypatch):
    monkeypatch.setattr(color_predictor, "reconcile", lambda db: [])
    machine_id = UUID(test_machine["id"])
    _piece(db, machine_id, "a", [("5", True)], palette=True)
    body = {"machine_id": test_machine["id"], "with_palette": True}
    assert client.post("/api/color-models/backfill", json=body, headers=_auth_headers(client)).status_code == 403
    db.query(User).filter(User.email == "member@test.com").update({"role": "admin"})
    db.commit()
    r = client.post("/api/color-models/backfill", json=body, headers=_auth_headers(client))
    assert r.status_code == 200, r.text
    assert r.json()["pieces"] == 1 and [m["jobs"] for m in r.json()["models"]] == [1, 1]
    r = client.post("/api/color-models/backfill", json={**body, "models": ["c" * 64]}, headers=_auth_headers(client))
    assert r.status_code == 400


def test_the_piece_panel_lists_every_models_answer(client, db, test_machine, models):
    machine_id = UUID(test_machine["id"])
    _piece(db, machine_id, "a", [("5", True)])
    color_model_runs.run_batch(db, OLD, machine_id, ["a"])
    color_model_runs.run_batch(db, NEW, machine_id, ["a"])
    # A model whose file was removed keeps its answers, under the name it had.
    db.add(PieceModelColor(machine_id=machine_id, piece_uuid="a", model_sha256="d" * 64, model_name="colorpred-v0",
                           color_id=5, confidence=0.4, top=[], seqs=[0]))
    db.commit()
    body = client.get(f"/api/labeling/piece/{machine_id}/a").json()
    answers = body["model_answers"]
    assert [(a["model_name"], a["is_active"]) for a in answers] == [
        ("colorpred-v3", True), ("colorpred-v1", False), ("colorpred-v0", False),
    ]
    assert answers[0]["color_name"] == "Red" and answers[0]["confidence"] > answers[1]["confidence"]
    # The colour the sorter applied is named after whoever answered it.
    assert body["prediction"]["color_provider_label"] == "Brickognize"
    db.query(MachinePiece).filter_by(piece_uuid="a").update({"color_provider": "hive_basically"})
    db.add(MachinePiecePrediction(machine_id=machine_id, piece_uuid="a", local_id=1, request="hosted",
                                  provider="hive_basically", model=NEW, kind="color", rank=0, value_id="5", applied=True,
                                  created_at=NOW))
    db.commit()
    body = client.get(f"/api/labeling/piece/{machine_id}/a").json()
    assert body["prediction"]["color_provider_label"] == "colorpred-v3"
    assert body["machine_predictions"][0]["model_name"] == "colorpred-v3"
    assert client.get("/api/labeling/color-models").json()["models"][0] == {
        "sha256": NEW, "name": "colorpred-v3", "filename": "colorpred-v3.onnx", "is_active": True,
    }


def test_agreeing_labels_each_piece_with_the_models_colour(client, db, test_machine, models, monkeypatch):
    from app.models.machine import Machine
    from app.models.piece_color_label import PieceColorLabel
    from app.services import likely_colors

    monkeypatch.setattr(likely_colors, "labelable_palette", lambda: [{"id": 5}, {"id": 7}])
    machine_id = UUID(test_machine["id"])
    me = db.query(User).filter(User.email == "member@test.com").one()
    other = User(email="other@test.com", display_name="Other", role="member")
    db.add(other)
    db.commit()
    theirs = Machine(owner_id=other.id, token_hash="h-theirs", token_prefix="theirs", name="theirs")
    db.add(theirs)
    db.commit()
    _piece(db, machine_id, "red", [("5", True)])
    _piece(db, machine_id, "blue", [("7", True)])
    _piece(db, machine_id, "black", [("11", True)])  # not a labelable colour here
    _piece(db, machine_id, "unread", [("5", True)])
    _piece(db, theirs.id, "theirs", [("5", True)])
    color_model_runs.run_batch(db, NEW, machine_id, ["red", "blue", "black"])
    color_model_runs.run_batch(db, NEW, theirs.id, ["theirs"])
    # My earlier "can't tell" on the blue one is replaced.
    db.add(PieceColorLabel(machine_id=machine_id, piece_uuid="blue", labeler_id=me.id, color_id=None, cant_tell=True))
    db.commit()

    pieces = [{"machine_id": str(machine_id), "piece_uuid": p} for p in ("red", "blue", "black", "unread", "red")]
    pieces.append({"machine_id": str(theirs.id), "piece_uuid": "theirs"})
    r = client.post("/api/labeling/agree", json={"model_sha256": NEW, "pieces": pieces}, headers=_auth_headers(client))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["labeled"], body["created"], body["skipped"]) == (2, 1, 3)
    assert {(x["piece_uuid"], x["color_id"], x["created"]) for x in body["labels"]} == {("red", 5, True), ("blue", 7, False)}
    db.expire_all()
    labels = {(l.piece_uuid, l.color_id, bool(l.cant_tell)) for l in db.query(PieceColorLabel).filter_by(labeler_id=me.id)}
    assert labels == {("red", 5, False), ("blue", 7, False)}

    too_many = [{"machine_id": str(machine_id), "piece_uuid": f"p{i}"} for i in range(501)]
    r = client.post("/api/labeling/agree", json={"model_sha256": NEW, "pieces": too_many}, headers=_auth_headers(client))
    assert r.status_code == 422


def test_the_worker_reads_the_palette_without_loading_the_catalog(monkeypatch):
    # piece_warm runs colour guesses in the worker process, which may never load
    # the parts catalog: the palette comes from the lookup that reads parts.db.
    from app import roles
    from app.services import profile_catalog

    class _Lookup:
        def list_bricklink_colors(self):
            return [{"id": 5, "name": "Red", "rgb": "#C91A09"}]

    monkeypatch.setattr(roles, "role", lambda: "worker")
    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(profile_catalog, "_catalog_lookup", _Lookup())
    assert color_predictor._palette()[5]["name"] == "Red"
    assert profile_catalog._catalog_service is None


def test_the_worker_names_a_pixel_colour_without_loading_the_catalog(monkeypatch):
    # The pixel guess (piece_warm, in the worker) names its colour from the
    # labelable palette, which comes from the same lookup.
    from app import roles
    from app.services import pixel_color, profile_catalog

    class _Lookup:
        def list_bricklink_colors(self):
            return [{"id": 5, "name": "Red", "rgb": "#C91A09"}, {"id": 11, "name": "Black", "rgb": "#05131D"}]

    monkeypatch.setattr(roles, "role", lambda: "worker")
    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(profile_catalog, "_catalog_lookup", _Lookup())
    pixel_color._palette.cache_clear()
    try:
        assert pixel_color._nearest_color((190, 30, 20))["color_name"] == "Red"
        assert profile_catalog._catalog_service is None
    finally:
        pixel_color._palette.cache_clear()
