"""Which pieces had the colour reference palette in view: the frames found by
machine and time, ``labeling_queue.has_palette`` kept by the worker (new
pieces, new frames, a new swatch model, runs stored without a frame time), the
grid's palette filter in every sort, and the frame the piece panel shows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.models.labeling_queue import LabelingQueueEntry
from app.models.sample import Sample
from app.models.sample_swatch import SampleSwatchRun
from app.models.swatch_model import SwatchModel
from app.models.upload_session import UploadSession
from app.routers import piece_color_labels as labeling_router
from app.services import labeling_queue, piece_palette, rate_limit, swatch_jobs, swatch_models
from tests.test_labeling_queue import NOW, SORTS, _expected, _walk, fleet  # noqa: F401  (fleet is a fixture)

BASE = NOW - timedelta(hours=6)  # the fleet's first arrival

# The palette's tiles as a finder reads them: (colour, BrickLink id, median RGB).
TILES = [("White", 1, (239, 233, 204)), ("Black", 11, (31, 33, 36)), ("Red", 5, (184, 0, 26)), ("Blue", 7, (41, 75, 189))]


def _model(db: Session, sha: str, name: str) -> SwatchModel:
    row = SwatchModel(filename=f"{name}.onnx", name=name, sha256=sha, colour_count=7, net_long_side=960, file_size=1)
    db.add(row)
    db.commit()
    swatch_models.set_active(db, row.id, True)
    return row


_samples = iter(range(1, 10_000))


def _frame(db: Session, machine_id: UUID, at: datetime, *, palette: bool, sha: str) -> UUID:
    """A classification sample taken at ``at`` and a swatch run of model ``sha`` on it."""
    session = db.query(UploadSession).filter(UploadSession.machine_id == machine_id).first()
    if session is None:
        session = UploadSession(machine_id=machine_id, source_session_id=f"s-{machine_id}", name="s")
        db.add(session)
        db.flush()
    n = next(_samples)
    sample = Sample(
        machine_id=machine_id,
        upload_session_id=session.id,
        local_sample_id=f"frame-{n}",
        source_role="classification_channel",
        captured_at=at,
        image_path=f"{machine_id}/{n}.jpg",
        full_frame_path=f"{machine_id}/{n}-full.jpg",
    )
    db.add(sample)
    db.flush()
    swatches = [
        SimpleNamespace(
            colour=name,
            colour_score=0.9,
            surface_score=0.95,
            pixels=12000,
            rgb=rgb,
            rgb_std=(1.0, 2.0, 1.0),
            clipped=0.0,
            centre=(3600.0, 400.0 + 170 * i),
            box=(3560, 340 + 170 * i, 3680, 460 + 170 * i),
            length=120.0,
            width=118.0,
            flags=[],
        )
        for i, (name, _bl, rgb) in enumerate(TILES)
    ]
    found = SimpleNamespace(
        width=3840, height=2160, swatches=swatches, palette=list(range(len(TILES))) if palette else [], flags=[]
    )
    ids = {name: bl for name, bl, _rgb in TILES}
    swatch_jobs.store_run(
        db,
        sample_id=sample.id,
        model_id=None,
        model_name="swatch-test",
        model_sha256=sha,
        found=found,
        bricklink_id=ids.get,
        seconds=1.0,
    )
    db.commit()
    return sample.id


def _with_palette(db: Session) -> set[str]:
    db.expire_all()
    return {e.piece_uuid for e in db.query(LabelingQueueEntry).filter(LabelingQueueEntry.has_palette.is_(True))}


A, B = "aa" * 32, "bb" * 32


@pytest.fixture()
def palette(db, fleet):
    """Frames on two of the three machines, read by model A after the queue
    was filled: m1 has two palette frames 106 and 110 minutes before its first
    piece (so its pieces in the first 14 minutes have one within two hours)
    and a frame without the palette nearer; m3 one palette frame after all its
    pieces; m2 only a frame another model read."""
    _model(db, A, "swatch-a")
    labeling_queue.run_pass(db)  # the filter's model changed: a full pass, nothing near a frame yet
    frames = {
        "f1": _frame(db, fleet["m1"], BASE - timedelta(minutes=110), palette=True, sha=A),
        "f2": _frame(db, fleet["m1"], BASE - timedelta(minutes=106), palette=True, sha=A),
        "n1": _frame(db, fleet["m1"], BASE - timedelta(minutes=100), palette=False, sha=A),
        "f3": _frame(db, fleet["m3"], BASE + timedelta(minutes=30), palette=True, sha=A),
        "other_model": _frame(db, fleet["m2"], BASE + timedelta(minutes=5), palette=True, sha=B),
    }
    return frames


EXPECTED = {"p00", "p02", "p04", "p06"} | {f"q{j:02d}" for j in range(6)}


def test_frames_stored_after_the_pieces_mark_them_on_the_next_pass(db, fleet, palette):
    assert _with_palette(db) == set()
    detail = labeling_queue.run_pass(db)
    assert detail["mode"] == "incremental"
    assert _with_palette(db) == EXPECTED
    # The full pass works it out the same way.
    labeling_queue.run_pass(db, now=datetime.now(timezone.utc) + timedelta(days=2))
    assert _with_palette(db) == EXPECTED


def test_runs_record_their_machine_and_frame_time(db, fleet, palette):
    run = db.query(SampleSwatchRun).filter(SampleSwatchRun.sample_id == palette["f3"]).one()
    assert run.machine_id == fleet["m3"]
    assert run.frame_at.replace(tzinfo=timezone.utc) == BASE + timedelta(minutes=30)


def test_a_run_stored_without_a_frame_time_is_placed_and_counted(db, fleet, palette):
    """A run the previous release stored during a deploy has no machine or
    frame time; the next pass gives it its sample's and counts it."""
    labeling_queue.run_pass(db)
    late = _frame(db, fleet["m2"], BASE + timedelta(minutes=20), palette=True, sha=A)
    db.query(SampleSwatchRun).filter(SampleSwatchRun.sample_id == late).update(
        {SampleSwatchRun.machine_id: None, SampleSwatchRun.frame_at: None}
    )
    db.commit()
    labeling_queue.run_pass(db)
    run = db.query(SampleSwatchRun).filter(SampleSwatchRun.sample_id == late).one()
    assert run.machine_id == fleet["m2"]
    m2 = {s["puid"] for s in fleet["spec"] if s["machine"] == fleet["m2"]}
    assert _with_palette(db) == EXPECTED | m2


def test_a_new_swatch_model_works_it_out_again(db, fleet, palette):
    labeling_queue.run_pass(db)
    second = _model(db, B, "swatch-b")  # the active model now; it read only m2's frame
    assert labeling_queue.run_pass(db)["mode"] == "reconcile"
    assert _with_palette(db) == {s["puid"] for s in fleet["spec"] if s["machine"] == fleet["m2"]}
    swatch_models.set_active(db, second.id, False)
    first = db.query(SwatchModel).filter(SwatchModel.sha256 == A).one()
    swatch_models.set_active(db, first.id, True)
    labeling_queue.run_pass(db)
    assert _with_palette(db) == EXPECTED


def test_the_palette_filter_keeps_every_sort_order_and_the_machine_filter(client, db, fleet, palette, monkeypatch):
    """Every sort, every page, every machine filter: the palette pieces only,
    in the order the sort gives without the filter."""
    labeling_queue.run_pass(db)
    rare = {"5", "86"}
    monkeypatch.setattr(labeling_router, "_rare_candidate_color_ids", lambda *a: rare)
    # Many pages in one test: past a member's request rate.
    monkeypatch.setitem(rate_limit.LIMITS["labeling_list"], "member", None)
    for sort in SORTS + ["rare_color"]:
        for chosen in (None, [fleet["m1"]], [fleet["m1"], fleet["m2"]]):
            got = _walk(client, sort, 3, machines=chosen, with_palette="true")
            expected = [p for p in _expected(db, fleet, sort, machine_id=chosen, rare=rare) if p in EXPECTED]
            assert got == expected, (sort, chosen)
            assert got, (sort, chosen)  # every case has palette pieces to show


def test_cards_carry_the_palette(client, db, fleet, palette):
    labeling_queue.run_pass(db)
    items = client.get("/api/labeling/pieces", params={"sort": "recent", "limit": 200}).json()["items"]
    assert {it["piece_uuid"] for it in items if it["has_palette"]} == EXPECTED


def test_the_panel_shows_the_latest_palette_frame_before_the_piece_else_the_first_after(client, db, fleet, palette):
    def frame(machine, puid):
        r = client.get(f"/api/labeling/piece/{machine}/{puid}")
        assert r.status_code == 200, r.text
        body = r.json()["palette"]
        assert body["window_s"] == 7200
        return body["frame"]

    before = frame(fleet["m1"], "p00")
    assert before["sample_id"] == str(palette["f2"])  # the latest before it, not f1 nor the frame without the palette
    assert before["offset_s"] == -106 * 60
    run = before["run"]
    assert run["palette_present"] is True
    assert [(s["colour"], s["bricklink_color_id"], s["rgb"]) for s in run["swatches"]] == [
        (name, bl, list(rgb)) for name, bl, rgb in TILES
    ]
    assert before["full_frame_url"] is None  # local storage: the sample's full-frame route

    after = frame(fleet["m3"], "q00")
    assert after["sample_id"] == str(palette["f3"]) and after["offset_s"] == 29 * 60

    assert frame(fleet["m1"], "p08") is None  # 122 minutes from the nearest
    assert frame(fleet["m2"], "p01") is None  # only another model's frame


def test_the_lookups_read_one_model_one_machine_and_the_window(db, fleet, palette):
    m1 = fleet["m1"]
    at = BASE + timedelta(minutes=14)
    assert piece_palette.nearest_frame(db, A, m1, at).sample_id == palette["f2"]
    assert piece_palette.nearest_frame(db, B, m1, at) is None
    assert piece_palette.nearest_frame(db, None, m1, at) is None
    assert piece_palette.nearest_frame(db, A, m1, BASE + timedelta(minutes=15)) is None
    arrivals = {"in": at, "out": BASE + timedelta(minutes=15), "far": BASE - timedelta(days=3)}
    assert piece_palette.with_palette(db, A, m1, arrivals) == {"in"}
