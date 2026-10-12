"""The ``swatch_find`` job: find the colour reference palette's tiles in a
classification-camera sample and store each one's reading.

Queued for every new classification-camera sample while a swatch model is
active (``enqueue_for_new_sample``, called by the sample ingest route), and for
existing samples by an admin backfill (``backfill``). The handler reads the
sample's full frame from storage, runs the active model's finder on it (one
frame in memory, onnxruntime on ``SWATCH_FINDER_THREADS``), and writes one
``sample_swatch_runs`` row (with the frame's call: is the palette in view) and
a ``sample_swatches`` row per tile.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, false, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.config import settings
from app.database import SessionLocal
from app.models.sample import Sample
from app.models.sample_swatch import SampleSwatch, SampleSwatchRun
from app.models.swatch_model import SwatchModel
from app.services import job_queue, swatch_models
from app.services.job_queue import JobContext, PermanentJobError
from app.services.storage_backend import get_backend

logger = logging.getLogger(__name__)

KIND = "swatch_find"
# Live samples go ahead of a backfill.
BACKFILL_PRIORITY = -10
BACKFILL_MAX = 50_000


def enqueue_for_new_sample(db: Session, sample_id: UUID, source_role: str | None) -> None:
    """Queue a swatch_find for a sample that just arrived, if it is from the
    classification camera and a swatch model is active. Never raises: the
    upload that called it has already been stored."""
    if source_role not in settings.SWATCH_FIND_SOURCE_ROLES:
        return
    try:
        if swatch_models.has_active(db):
            job_queue.enqueue(db, KIND, str(sample_id))
    except Exception:
        db.rollback()
        logger.exception("could not queue swatch_find for sample %s", sample_id)


def backfill(
    db: Session,
    *,
    machine_id: UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    source_roles: list[str] | None = None,
    rerun: bool = False,
    limit: int = BACKFILL_MAX,
) -> dict[str, Any]:
    """Queue swatch_find for a machine's existing classification-camera samples
    captured in [since, until), newest first. Samples the active model has
    already read are left out unless ``rerun`` (a run made before the finder
    called the palette does not count as read); ones already queued are not
    queued twice. Call with a model active."""
    active = swatch_models.get_active(db)
    if active is None:
        raise ValueError("No swatch model is active.")
    roles = list(source_roles or settings.SWATCH_FIND_SOURCE_ROLES)
    when = func.coalesce(Sample.captured_at, Sample.uploaded_at)
    query = select(Sample.id).where(
        Sample.machine_id == machine_id,
        Sample.source_role.in_(roles),
        Sample.full_frame_path.isnot(None),
        Sample.archived_at.is_(None),
    )
    if since is not None:
        query = query.where(when >= since)
    if until is not None:
        query = query.where(when < until)
    if not rerun:
        query = query.where(
            ~exists().where(
                SampleSwatchRun.sample_id == Sample.id,
                SampleSwatchRun.model_sha256 == active.sha256,
                SampleSwatchRun.palette_present.isnot(None),
            )
        )
    limit = max(1, min(int(limit), BACKFILL_MAX))
    sample_ids = [str(row[0]) for row in db.execute(query.order_by(when.desc()).limit(limit))]
    queued = job_queue.enqueue_many(db, KIND, sample_ids, priority=BACKFILL_PRIORITY)
    return {
        "model": active.name,
        "matched": len(sample_ids),
        "queued": queued,
        "already_queued": len(sample_ids) - queued,
        "truncated": len(sample_ids) >= limit,
    }


# The samples filter "palette": is the colour reference palette in view in a
# sample's frame, as one swatch model called it.
PALETTE_FILTER_VALUES = ("in_view", "not_in_view", "unchecked")


def palette_filter_model_sha256(db: Session) -> str | None:
    """The swatch model the palette filter reads: the active one, else the one
    changed last, so a paused model's calls still filter. None with no models."""
    row = (
        db.query(SwatchModel.sha256)
        .order_by(SwatchModel.is_active.desc(), SwatchModel.updated_at.desc())
        .first()
    )
    return row[0] if row else None


def palette_filter(db: Session, value: str | None) -> ColumnElement[bool] | None:
    """A where-clause on ``Sample`` for the palette filter; None for any (or a
    value it does not know).

    - ``in_view`` / ``not_in_view``: the filter model's run on the sample
      called the palette in view, or not.
    - ``unchecked``: a sample the swatch_find job reads (classification camera,
      with a full frame) that the model has not called yet, a run made before
      the finder made the call included. What a backfill would queue.

    One correlated EXISTS against sample_swatch_runs, which Postgres runs as a
    semi- or anti-join on ``ix_sample_swatch_runs_model_palette`` (model,
    call, sample) or the (sample, model) unique index: nothing per row.
    """
    if value not in PALETTE_FILTER_VALUES:
        return None
    sha = palette_filter_model_sha256(db)
    if value == "unchecked":
        eligible = Sample.source_role.in_(list(settings.SWATCH_FIND_SOURCE_ROLES)) & Sample.full_frame_path.isnot(None)
        if sha is None:
            return eligible
        called = exists().where(
            SampleSwatchRun.sample_id == Sample.id,
            SampleSwatchRun.model_sha256 == sha,
            SampleSwatchRun.palette_present.isnot(None),
        )
        return eligible & ~called
    if sha is None:
        return false()
    return exists().where(
        SampleSwatchRun.sample_id == Sample.id,
        SampleSwatchRun.model_sha256 == sha,
        # "= true", not "IS TRUE": only an equality can use the index.
        SampleSwatchRun.palette_present == (value == "in_view"),
    )


def handle_swatch_find(job: JobContext) -> dict[str, Any]:
    try:
        sample_id = UUID(str(job.subject))
    except ValueError as exc:
        raise PermanentJobError(f"Not a sample id: {job.subject!r}") from exc

    db = SessionLocal()
    try:
        sample = db.get(Sample, sample_id)
        if sample is None:
            raise PermanentJobError("The sample no longer exists.")
        frame_path = sample.full_frame_path
        model = swatch_models.get_active(db)
        if model is None:
            return {"skipped": "No swatch model is active."}
        model_id, model_name, model_file, model_sha = model.id, model.name, model.filename, model.sha256
    finally:
        db.close()
    if not frame_path:
        return {"skipped": "The sample has no full frame."}

    finder = swatch_models.get_finder(model_file, model_sha)
    if finder is None:
        # The file may come back (a copy in progress): retried with a backoff.
        raise RuntimeError(f"Swatch model {model_file} is missing from the model folder or does not load.")

    try:
        frame = get_backend().read_bytes(frame_path)
    except FileNotFoundError as exc:
        raise PermanentJobError("The sample's frame is missing from storage.") from exc

    started = time.perf_counter()
    found = finder.find(frame)
    seconds = round(time.perf_counter() - started, 3)
    del frame

    db = SessionLocal()
    try:
        if db.get(Sample, sample_id) is None:
            raise PermanentJobError("The sample was deleted while it was being read.")
        run = store_run(
            db,
            sample_id=sample_id,
            model_id=model_id,
            model_name=model_name,
            model_sha256=model_sha,
            found=found,
            bricklink_id=finder.net.bricklink_id,
            seconds=seconds,
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()
    return {
        "run_id": str(run_id),
        "model": model_name,
        "swatches": len(found.swatches),
        "palette": len(found.palette),
        "flags": list(found.flags),
        "seconds": seconds,
    }


def store_run(
    db: Session,
    *,
    sample_id: UUID,
    model_id: UUID | None,
    model_name: str,
    model_sha256: str,
    found: Any,
    bricklink_id: Any,
    seconds: float,
) -> SampleSwatchRun:
    """Write one run and its tiles, replacing an earlier run of the same model
    file on this sample. Does not commit."""
    previous = (
        db.query(SampleSwatchRun)
        .filter(SampleSwatchRun.sample_id == sample_id, SampleSwatchRun.model_sha256 == model_sha256)
        .all()
    )
    for row in previous:
        db.delete(row)
    if previous:
        db.flush()
    in_palette = set(found.palette)
    run = SampleSwatchRun(
        sample_id=sample_id,
        model_id=model_id,
        model_name=model_name,
        model_sha256=model_sha256,
        frame_width=int(found.width),
        frame_height=int(found.height),
        swatch_count=len(found.swatches),
        palette_present=bool(in_palette),
        palette_swatches=len(in_palette),
        flags=list(found.flags),
        seconds=float(seconds),
    )
    for position, s in enumerate(found.swatches):
        run.swatches.append(
            SampleSwatch(
                position=position,
                colour=s.colour,
                bricklink_color_id=bricklink_id(s.colour),
                colour_score=float(s.colour_score),
                surface_score=float(s.surface_score),
                pixels=int(s.pixels),
                median_r=float(s.rgb[0]),
                median_g=float(s.rgb[1]),
                median_b=float(s.rgb[2]),
                std_r=float(s.rgb_std[0]),
                std_g=float(s.rgb_std[1]),
                std_b=float(s.rgb_std[2]),
                clipped=float(s.clipped),
                centre_x=float(s.centre[0]),
                centre_y=float(s.centre[1]),
                box_x0=int(s.box[0]),
                box_y0=int(s.box[1]),
                box_x1=int(s.box[2]),
                box_y1=int(s.box[3]),
                length=float(s.length),
                width=float(s.width),
                flags=list(s.flags),
                in_palette=position in in_palette,
            )
        )
    db.add(run)
    db.flush()
    return run


def serialize_run(run: SampleSwatchRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "model_id": str(run.model_id) if run.model_id else None,
        "model_name": run.model_name,
        "model_sha256": run.model_sha256,
        "frame_width": run.frame_width,
        "frame_height": run.frame_height,
        "swatch_count": run.swatch_count,
        "palette_present": run.palette_present,
        "palette_swatches": run.palette_swatches,
        "flags": list(run.flags or []),
        "seconds": run.seconds,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "swatches": [
            {
                "position": s.position,
                "colour": s.colour,
                "bricklink_color_id": s.bricklink_color_id,
                "colour_score": s.colour_score,
                "surface_score": s.surface_score,
                "pixels": s.pixels,
                "rgb": [s.median_r, s.median_g, s.median_b],
                "rgb_std": [s.std_r, s.std_g, s.std_b],
                "clipped": s.clipped,
                "centre": [s.centre_x, s.centre_y],
                "box": [s.box_x0, s.box_y0, s.box_x1, s.box_y1],
                "length": s.length,
                "width": s.width,
                "flags": list(s.flags or []),
                "in_palette": s.in_palette,
            }
            for s in run.swatches
        ],
    }


def runs_for_sample(db: Session, sample_id: UUID) -> list[SampleSwatchRun]:
    return (
        db.query(SampleSwatchRun)
        .filter(SampleSwatchRun.sample_id == sample_id)
        .order_by(SampleSwatchRun.created_at.desc())
        .all()
    )


# A 3840x2160 frame takes a second or two on one thread; a lease of ten
# minutes leaves room for a slow box without letting a dead worker's job
# wait long.
job_queue.register_handler(KIND, handle_swatch_find, max_attempts=3, lease_s=600, backoff_s=60)
