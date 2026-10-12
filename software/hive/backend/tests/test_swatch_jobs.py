"""The swatch_find job: queued on ingest and by the backfill, run through the
job queue, stored as runs and tiles with the frame's palette call, served per
sample; the samples filter on that call; and the swatch model registry.

The network is stubbed with one that marks the drawn tiles of a synthetic
3840x2160 frame, so everything around it (decoding, reading the tiles at full
resolution, ordering, storing) runs for real. A real model on a real frame
runs when HIVE_TEST_SWATCH_MODEL and HIVE_TEST_SWATCH_FRAME (a frame with the
palette in view) name the files, and HIVE_TEST_SWATCH_FRAME_WITHOUT_PALETTE
(one without) if set (none is in the repository).
"""

from __future__ import annotations

import io
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.models.job import Job
from app.models.sample import Sample
from app.models.sample_swatch import SampleSwatch, SampleSwatchRun
from app.models.swatch_model import SwatchModel
from app.models.user import User
from app.services import job_queue, swatch_jobs, swatch_models
from app.services.storage_backend import get_backend, reset_backend_for_tests
from app.services.swatch_finder import Net, SwatchFinder
from tests.conftest import TestingSessionLocal, _auth_headers

# name, BrickLink id, the sRGB the synthetic frame draws it in
PALETTE = [
    ("none", None, (0, 0, 0)),
    ("White", 1, (244, 244, 244)),
    ("Light Bluish Gray", 86, (160, 165, 169)),
    ("Dark Bluish Gray", 85, (99, 95, 98)),
    ("Black", 11, (27, 42, 52)),
    ("Red", 5, (180, 0, 0)),
    ("Blue", 7, (30, 90, 168)),
    ("Yellow", 3, (250, 200, 10)),
]
BACKGROUND = (110, 80, 140)
TILE = 120
TILES = [(3560, 400 + i * 170) for i in range(len(PALETTE) - 1)]  # top-left corners, a strip down the right edge
CAPTURED = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


RGB = {name: rgb for name, _bl, rgb in PALETTE}


def _frame(width: int = 3840, height: int = 2160, tiles: list | None = None) -> bytes:
    """A frame with tiles drawn on it: ((x, y), colour name) top-left corners,
    the palette strip down the right edge by default."""
    if tiles is None:
        tiles = list(zip(TILES, [p[0] for p in PALETTE[1:]]))
    im = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(im)
    for (x, y), name in tiles:
        draw.rectangle([x, y, x + TILE - 1, y + TILE - 1], fill=RGB[name])
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class FakeNet(Net):
    """Calls a pixel top face when it is near one of the palette's colours, and
    gives it that colour: what a trained network does on a clean frame."""

    def __init__(self) -> None:
        self.path = "fake-swatch.onnx"
        self.names = [p[0] for p in PALETTE]
        self.classes = [p[1] for p in PALETTE]

    def __call__(self, rgb):
        px = rgb.astype(np.float32)
        refs = np.array([p[2] for p in PALETTE[1:]], np.float32)
        dist = np.linalg.norm(px[:, :, None, :] - refs[None, None], axis=-1)  # H, W, colours
        surface = np.where(dist.min(-1) < 25, 0.95, 0.05)
        logits = -dist.transpose(2, 0, 1) / 5
        e = np.exp(logits - logits.max(0, keepdims=True))
        return surface, e / e.sum(0, keepdims=True)


def _fake_finder() -> SwatchFinder:
    finder = SwatchFinder.__new__(SwatchFinder)
    finder.net = FakeNet()
    return finder


@pytest.fixture(autouse=True)
def _wiring(monkeypatch, tmp_path):
    monkeypatch.setattr(job_queue, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(swatch_jobs, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(job_queue, "_worker", job_queue.JobWorker())
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "SWATCH_MODEL_DIR", str(tmp_path / "swatch_models"))
    reset_backend_for_tests()
    yield
    reset_backend_for_tests()


@pytest.fixture()
def fake_finder(monkeypatch):
    finder = _fake_finder()
    monkeypatch.setattr(swatch_models, "get_finder", lambda filename, sha256: finder)
    return finder


def _model(db, *, sha: str = "ab" * 32, name: str = "swatch-test", active: bool = True) -> SwatchModel:
    row = SwatchModel(
        filename=f"{name}.onnx", name=name, sha256=sha, colour_count=7, net_long_side=960, file_size=1, is_active=False
    )
    db.add(row)
    db.commit()
    if active:
        swatch_models.set_active(db, row.id, True)
    return row


def _sync(client, token: str, local_id: int, *, role: str = "classification_channel", captured: datetime = CAPTURED, image: bytes | None = None):
    meta = {
        "local_id": local_id,
        "source_session_id": "sess-a",
        "local_sample_id": f"s-{local_id:04d}",
        "source_role": role,
        "captured_at": captured.timestamp(),
        "capture_reason": "interval",
    }
    r = client.post(
        "/api/machine/sync/sample",
        headers={"Authorization": f"Bearer {token}"},
        data={"metadata": json.dumps(meta)},
        files={"image": ("frame.jpg", io.BytesIO(image or _frame(640, 360)), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    return r.json()["sample_id"]


def _swatch_jobs(db) -> list[Job]:
    db.expire_all()
    return db.query(Job).filter(Job.kind == swatch_jobs.KIND).all()


def _run_all() -> int:
    worker = job_queue.get_job_worker()
    n = 0
    while worker.run_once("test"):
        n += 1
    return n


def test_a_classification_sample_is_read_and_its_swatches_stored(client, db, machine_token, fake_finder):
    _model(db)
    sample_id = _sync(client, machine_token, 1, image=_frame())
    [job] = _swatch_jobs(db)
    assert job.subject == sample_id and job.status == "queued" and job.priority == 0

    assert _run_all() == 1
    [job] = _swatch_jobs(db)
    assert job.status == "done", job.error
    assert job.result["swatches"] == 7 and job.result["palette"] == 7 and job.result["flags"] == []

    r = client.get(f"/api/samples/{sample_id}/swatch-runs")
    assert r.status_code == 200, r.text
    [run] = r.json()["runs"]
    assert run["model_name"] == "swatch-test" and run["swatch_count"] == 7
    assert run["palette_present"] is True and run["palette_swatches"] == 7
    assert (run["frame_width"], run["frame_height"]) == (3840, 2160)
    assert run["seconds"] > 0
    swatches = run["swatches"]
    assert [s["colour"] for s in swatches] == [p[0] for p in PALETTE[1:]]  # top to bottom
    assert [s["bricklink_color_id"] for s in swatches] == [p[1] for p in PALETTE[1:]]
    for s, (x, y), (_name, _bl, rgb) in zip(swatches, TILES, PALETTE[1:]):
        assert s["position"] == swatches.index(s)
        assert max(abs(a - b) for a, b in zip(s["rgb"], rgb)) <= 8, (s["colour"], s["rgb"], rgb)
        assert abs(s["centre"][0] - (x + TILE / 2)) < 6 and abs(s["centre"][1] - (y + TILE / 2)) < 6
        x0, y0, x1, y1 = s["box"]
        assert x0 <= x + TILE / 2 <= x1 and y0 <= y + TILE / 2 <= y1
        assert TILE * 0.8 < s["length"] < TILE * 1.1 and TILE * 0.8 < s["width"] < TILE * 1.1
        assert s["pixels"] > 0.7 * TILE * TILE
        assert s["colour_score"] > 0.6 and s["surface_score"] > 0.9
    flags = {s["colour"]: s["flags"] for s in swatches}
    assert flags["Black"] == [] and flags["Blue"] == [] and flags["Dark Bluish Gray"] == []
    assert all(s["in_palette"] is True for s in swatches)


def _read(client, db, token: str, local_id: int, tiles: list, *, role: str = "classification_channel") -> dict:
    """Sync a frame with these tiles, run its job, and return the stored run."""
    sample_id = _sync(client, token, local_id, role=role, image=_frame(tiles=tiles))
    assert _run_all() == 1
    [run] = client.get(f"/api/samples/{sample_id}/swatch-runs").json()["runs"]
    return {"sample_id": sample_id, **run}


def test_the_frame_is_called_palette_or_not(client, db, machine_token, fake_finder):
    _model(db)
    strip = list(zip(TILES, [p[0] for p in PALETTE[1:]]))

    # The palette and a loose red piece's top far from it: the piece is a
    # swatch but not the palette's, and the palette's flags leave it out
    # (it would make "repeated_colour").
    run = _read(client, db, machine_token, 1, strip + [((1200, 900), "Red")])
    assert run["swatch_count"] == 8 and run["palette_present"] is True and run["palette_swatches"] == 7
    assert run["flags"] == []
    loose = [s for s in run["swatches"] if not s["in_palette"]]
    assert [(s["colour"], round(s["centre"][0])) for s in loose] == [("Red", 1260)]

    # Tiles touching, no gap between them: one swatch each, not one region.
    touching = [((2000, 600 + i * TILE), name) for i, name in enumerate(["White", "Black", "Red", "Blue"])]
    run = _read(client, db, machine_token, 2, touching)
    assert [s["colour"] for s in run["swatches"]] == ["White", "Black", "Red", "Blue"]
    assert run["palette_present"] is True and run["palette_swatches"] == 4

    # Three tiles, or four in three colours, are not a palette.
    for local_id, names in ((3, ["White", "Black", "Red"]), (4, ["White", "Black", "Red", "Red"])):
        run = _read(client, db, machine_token, local_id, [((3560, 400 + i * 170), n) for i, n in enumerate(names)])
        assert run["swatch_count"] == len(names)
        assert run["palette_present"] is False and run["palette_swatches"] == 0, names
        assert run["flags"] == [] and all(s["in_palette"] is False for s in run["swatches"])


def _filtered(db, value: str | None) -> set[str]:
    db.expire_all()
    query = db.query(Sample.id)
    clause = swatch_jobs.palette_filter(db, value)
    if clause is not None:
        query = query.filter(clause)
    return {str(row[0]) for row in query}


def test_the_palette_filter_keys_on_the_models_call(client, db, test_machine, machine_token, fake_finder):
    first = _model(db, sha="aa" * 32, name="swatch-v1")
    strip = list(zip(TILES, [p[0] for p in PALETTE[1:]]))
    in_view = _read(client, db, machine_token, 1, strip)["sample_id"]
    not_in_view = _read(client, db, machine_token, 2, strip[:2])["sample_id"]
    before_the_call = _read(client, db, machine_token, 3, strip)["sample_id"]
    db.query(SampleSwatchRun).filter(SampleSwatchRun.sample_id == UUID(before_the_call)).update(
        {SampleSwatchRun.palette_present: None, SampleSwatchRun.palette_swatches: None}
    )
    db.commit()
    queued = _sync(client, machine_token, 4)  # queued, not read yet
    other_camera = _sync(client, machine_token, 5, role="c_channel_2")
    everything = {in_view, not_in_view, before_the_call, queued, other_camera}

    assert _filtered(db, None) == _filtered(db, "any") == everything
    assert _filtered(db, "in_view") == {in_view}
    assert _filtered(db, "not_in_view") == {not_in_view}
    # Never the other camera's samples: the job does not read them.
    assert _filtered(db, "unchecked") == {before_the_call, queued}

    # A paused model still answers; a new model has called nothing yet.
    swatch_models.set_active(db, first.id, False)
    assert _filtered(db, "in_view") == {in_view}
    second = _model(db, sha="bb" * 32, name="swatch-v2")
    assert _filtered(db, "in_view") == _filtered(db, "not_in_view") == set()
    assert _filtered(db, "unchecked") == everything - {other_camera}

    # A run made before the call is read again by a plain backfill.
    swatch_models.set_active(db, second.id, False)
    swatch_models.set_active(db, first.id, True)
    result = swatch_jobs.backfill(db, machine_id=UUID(test_machine["id"]))
    assert (result["matched"], result["queued"], result["already_queued"]) == (2, 1, 1)


def test_only_classification_samples_are_queued_and_only_with_a_model_active(client, db, machine_token, fake_finder):
    _sync(client, machine_token, 1)  # no model yet
    model = _model(db)
    _sync(client, machine_token, 2, role="c_channel_2")
    queued = _sync(client, machine_token, 3)
    _sync(client, machine_token, 3)  # a re-send stores nothing new and queues nothing
    swatch_models.set_active(db, model.id, False)
    _sync(client, machine_token, 4)
    assert [j.subject for j in _swatch_jobs(db)] == [queued]


def test_the_same_model_replaces_its_run_and_a_new_model_adds_one(client, db, machine_token, fake_finder):
    first = _model(db, sha="aa" * 32, name="swatch-v1")
    sample_id = _sync(client, machine_token, 1, image=_frame())
    _run_all()
    assert job_queue.enqueue(db, swatch_jobs.KIND, sample_id)
    _run_all()
    db.expire_all()
    assert db.query(SampleSwatchRun).count() == 1
    assert db.query(SampleSwatch).count() == 7

    second = _model(db, sha="bb" * 32, name="swatch-v2")
    db.refresh(first)
    assert not first.is_active and second.is_active
    assert job_queue.enqueue(db, swatch_jobs.KIND, sample_id)
    _run_all()
    runs = client.get(f"/api/samples/{sample_id}/swatch-runs").json()["runs"]
    assert [r["model_name"] for r in runs] == ["swatch-v2", "swatch-v1"]


def test_what_a_job_does_when_its_sample_frame_or_model_is_gone(client, db, machine_token, fake_finder):
    model = _model(db)
    deleted = _sync(client, machine_token, 1)
    no_frame = _sync(client, machine_token, 2)
    no_model = _sync(client, machine_token, 3)

    db.query(Sample).filter(Sample.id == UUID(deleted)).delete()
    sample = db.get(Sample, UUID(no_frame))
    get_backend().delete(sample.full_frame_path)
    db.commit()
    worker = job_queue.get_job_worker()
    assert worker.run_once("t") and worker.run_once("t")
    swatch_models.set_active(db, model.id, False)
    assert worker.run_once("t")

    jobs = {j.subject: j for j in _swatch_jobs(db)}
    assert jobs[deleted].status == "failed" and jobs[deleted].attempts == 1
    assert "no longer exists" in jobs[deleted].error
    assert jobs[no_frame].status == "failed" and "missing from storage" in jobs[no_frame].error
    assert jobs[no_model].status == "done" and "skipped" in jobs[no_model].result


def test_a_model_file_that_will_not_load_is_retried(client, db, machine_token, monkeypatch):
    monkeypatch.setattr(swatch_models, "get_finder", lambda filename, sha256: None)
    _model(db)
    _sync(client, machine_token, 1)
    job_queue.get_job_worker().run_once("t")
    [job] = _swatch_jobs(db)
    assert job.status == "queued" and job.attempts == 1 and "does not load" in job.error


def test_the_samples_list_review_queue_and_batch_actions_filter_on_the_palette(client, db, machine_token, fake_finder):
    _model(db)
    strip = list(zip(TILES, [p[0] for p in PALETTE[1:]]))
    in_view = _read(client, db, machine_token, 1, strip)["sample_id"]
    not_in_view = _read(client, db, machine_token, 2, strip[:2])["sample_id"]
    unchecked = _sync(client, machine_token, 3)
    headers = _auth_headers(client)
    # The synthetic frames are dark by Hive's exposure buckets; the list hides those by default.
    shown = {"annotated": "all", "exposure": "under"}

    def listed(**params) -> set[str]:
        r = client.get("/api/samples", params={**shown, "limit": 50, **params}, headers=headers)
        assert r.status_code == 200, r.text
        return {item["id"] for item in r.json()["items"]}

    assert listed() == listed(palette="any") == {in_view, not_in_view, unchecked}
    assert listed(palette="in_view") == {in_view}
    assert listed(palette="not_in_view") == {not_in_view}
    assert listed(palette="unchecked") == {unchecked}
    assert listed(palette="in_view", needs_review="true") == {in_view}  # the review queue
    assert client.get("/api/samples", params={"palette": "sometimes"}, headers=headers).status_code == 422

    body = {**shown, "palette": "not_in_view", "dry_run": True}
    r = client.post("/api/samples/batch-delete", json=body, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["matched"] == 1


def _make_admin(db, email: str = "member@test.com") -> None:
    user = db.query(User).filter(User.email == email).first()
    user.role = "admin"
    db.commit()


def test_backfill_queues_a_machines_samples_in_range_not_yet_read(client, db, test_machine, machine_token, fake_finder):
    model = _model(db)
    ids = {
        hours: _sync(client, machine_token, i + 1, captured=CAPTURED + timedelta(hours=hours))
        for i, hours in enumerate([-48, -2, -1, 1])
    }
    other_role = _sync(client, machine_token, 9, role="c_channel_3", captured=CAPTURED - timedelta(hours=1))
    # The ingest queued the classification ones; run them, then forget one run.
    assert _run_all() == 4
    db.query(SampleSwatchRun).filter(SampleSwatchRun.sample_id == UUID(ids[-1])).delete()
    db.commit()
    _make_admin(db)
    headers = _auth_headers(client)

    body = {
        "machine_id": test_machine["id"],
        "since": (CAPTURED - timedelta(hours=24)).isoformat(),
        "until": CAPTURED.isoformat(),
    }
    r = client.post("/api/swatch-models/backfill", json=body, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"model": model.name, "matched": 1, "queued": 1, "already_queued": 0, "truncated": False}
    queued = [j for j in _swatch_jobs(db) if j.status == "queued"]
    assert [(j.subject, j.priority) for j in queued] == [(ids[-1], swatch_jobs.BACKFILL_PRIORITY)]

    # Again: the one it found is queued already. With rerun, the read ones come too.
    r = client.post("/api/swatch-models/backfill", json=body, headers=headers)
    assert r.json()["matched"] == 1 and r.json()["queued"] == 0 and r.json()["already_queued"] == 1
    r = client.post("/api/swatch-models/backfill", json={**body, "rerun": True}, headers=headers)
    assert r.json()["matched"] == 2 and r.json()["queued"] == 1
    assert other_role not in {j.subject for j in _swatch_jobs(db)}

    swatch_models.set_active(db, model.id, False)
    r = client.post("/api/swatch-models/backfill", json=body, headers=headers)
    assert r.status_code == 409


def test_backfill_and_registry_are_admin_only(client, test_machine):
    assert client.get("/api/swatch-models").status_code == 403
    r = client.post(
        "/api/swatch-models/backfill", json={"machine_id": test_machine["id"]}, headers=_auth_headers(client)
    )
    assert r.status_code == 403


def test_registry_reconciles_the_scan_folder_and_keeps_one_active(client, db, test_user, monkeypatch):
    folder = Path(settings.SWATCH_MODEL_DIR)
    folder.mkdir(parents=True)
    for name in ("a", "b", "notes"):
        (folder / f"{name}.onnx").write_bytes(name.encode())
    metas = {
        "a.onnx": {"hive.kind": "swatch_finder", "hive.name": "swatch-a", "hive.colour_names": json.dumps(["none", "White", "Black"]), "hive.net_long_side": "960"},
        "b.onnx": {"hive.kind": "swatch_finder", "hive.name": "swatch-b", "hive.colour_names": json.dumps(["none", "White"])},
    }
    monkeypatch.setattr(swatch_models, "_read_metadata", lambda path: metas.get(path.name))
    _make_admin(db)
    headers = _auth_headers(client)

    r = client.get("/api/swatch-models")
    assert r.status_code == 200, r.text
    models = {m["name"]: m for m in r.json()["models"]}
    assert set(models) == {"swatch-a", "swatch-b"}
    assert models["swatch-a"]["colour_count"] == 2 and models["swatch-a"]["net_long_side"] == 960
    assert r.json()["source_roles"] == ["classification_channel"]

    for name in ("swatch-a", "swatch-b"):
        r = client.post(f"/api/swatch-models/{models[name]['id']}/activate", headers=headers)
        assert r.status_code == 200, r.text
    active = [m["name"] for m in client.get("/api/swatch-models").json()["models"] if m["is_active"]]
    assert active == ["swatch-b"]

    (folder / "a.onnx").unlink()
    assert [m["name"] for m in client.get("/api/swatch-models").json()["models"]] == ["swatch-b"]


def test_a_members_sample_runs_are_not_served_to_other_members(client, db, machine_token, fake_finder):
    from tests.conftest import _login_user, _register_user

    _model(db)
    sample_id = _sync(client, machine_token, 1)
    _register_user(client, "other@test.com", "Password123!", "Other")
    _login_user(client, "other@test.com", "Password123!")
    assert client.get(f"/api/samples/{sample_id}/swatch-runs").status_code == 404


@pytest.mark.skipif(
    not (os.environ.get("HIVE_TEST_SWATCH_MODEL") and os.environ.get("HIVE_TEST_SWATCH_FRAME")),
    reason="set HIVE_TEST_SWATCH_MODEL (an exported swatch_finder .onnx) and HIVE_TEST_SWATCH_FRAME (a classification-camera JPEG with the palette in view)",
)
def test_a_real_model_on_a_real_frame(client, db, machine_token):
    folder = Path(settings.SWATCH_MODEL_DIR)
    folder.mkdir(parents=True)
    shutil.copy(os.environ["HIVE_TEST_SWATCH_MODEL"], folder / "swatch.onnx")
    [row] = swatch_models.reconcile(db)
    assert row.kind == "swatch_finder" and row.colour_count > 0
    swatch_models.set_active(db, row.id, True)

    frame = Path(os.environ["HIVE_TEST_SWATCH_FRAME"]).read_bytes()
    sample_id = _sync(client, machine_token, 1, image=frame)
    assert job_queue.get_job_worker().run_once("t")
    [job] = _swatch_jobs(db)
    assert job.status == "done", job.error

    finder = swatch_models.get_finder(row.filename, row.sha256)
    assert finder.net.sess.get_session_options().intra_op_num_threads == settings.SWATCH_FINDER_THREADS == 1
    [run] = client.get(f"/api/samples/{sample_id}/swatch-runs").json()["runs"]
    with Image.open(io.BytesIO(frame)) as im:
        assert (run["frame_width"], run["frame_height"]) == im.size
    assert run["swatch_count"] == len(run["swatches"]) == job.result["swatches"]
    print(f"\nreal frame: {run['swatch_count']} swatches, palette {run['palette_swatches']}, in {run['seconds']:.2f}s, flags {run['flags']}")
    assert run["palette_present"] is True and run["palette_swatches"] >= 4
    assert sum(1 for s in run["swatches"] if s["in_palette"]) == run["palette_swatches"]

    without = os.environ.get("HIVE_TEST_SWATCH_FRAME_WITHOUT_PALETTE")
    if without:
        other = _sync(client, machine_token, 2, image=Path(without).read_bytes())
        assert job_queue.get_job_worker().run_once("t")
        [run] = client.get(f"/api/samples/{other}/swatch-runs").json()["runs"]
        print(f"frame without a palette: {run['swatch_count']} swatches, palette {run['palette_swatches']}")
        assert run["palette_present"] is False and run["palette_swatches"] == 0
