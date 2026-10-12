"""Which pieces had the colour reference palette in view, and the frame showing it.

Some machines carry a colour reference palette at the edge of the
classification camera's view (agent-docs/jobs.md, ``swatch_find``). A piece is
taken to have it in view when one of its machine's classification frames from
within ``WINDOW`` of the piece's arrival was called palette-in-view by the
swatch model the samples filter reads (``swatch_jobs.palette_filter_model_sha256``:
the active model, else the one changed last). The frame shown for a piece is
the latest such frame at or before its arrival, else the first one after it.

Frames are read through ``ix_sample_swatch_runs_palette_frames`` (model,
machine, frame time; palette-in-view runs only): one piece's frame is a LIMIT 1
probe on it, and the frames near a stretch of a machine's pieces are one range
read. The piece grid never comes here: it reads ``labeling_queue.has_palette``,
which the labeling-queue worker keeps with ``with_palette``.
"""

from __future__ import annotations

import bisect
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, true
from sqlalchemy.orm import Session

from app.models.machine_piece import MachinePiece
from app.models.sample import Sample
from app.models.sample_swatch import SampleSwatchRun
from app.models.user import User
from app.services.access_window import sample_access_visible
from app.services.storage_backend import get_backend
from app.services.swatch_jobs import frame_time, palette_filter_model_sha256, serialize_run

# How far from a piece a frame may be and still say the palette was in view
# for it. A sorting machine takes a classification frame at least hourly (the
# sample collector's slowest rate), so two hours either side always holds one.
WINDOW = timedelta(hours=2)
_RANGES_PER_READ = 100

__all__ = ["WINDOW", "model_sha256", "with_palette", "nearest_frame", "frame_for_piece", "place_runs"]

model_sha256 = palette_filter_model_sha256


def _utc(dt: datetime) -> datetime:
    # SQLite (the tests) hands datetimes back naive; every stored time is UTC.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _palette_frames(sha: str, machine_id: Any) -> tuple:
    # The index's leading columns and its predicate, in the same form.
    return (
        SampleSwatchRun.model_sha256 == sha,
        SampleSwatchRun.machine_id == machine_id,
        SampleSwatchRun.palette_present == true(),
    )


def with_palette(db: Session, sha: str | None, machine_id: Any, arrivals: dict[str, datetime]) -> set[str]:
    """The pieces of one machine (piece_uuid -> arrival) with a palette frame
    within WINDOW of their arrival.

    The pieces are grouped into runs whose windows touch (a sorting session is
    one run), and the frame times of up to _RANGES_PER_READ runs are read in
    one query, each run a range on the index; every frame near a piece lies in
    its run's range, so the list answers each piece exactly."""
    if sha is None or not arrivals:
        return set()
    ordered = sorted(((puid, _utc(at)) for puid, at in arrivals.items()), key=lambda kv: kv[1])
    runs: list[list[tuple[str, datetime]]] = [[ordered[0]]]
    for item in ordered[1:]:
        if item[1] - runs[-1][-1][1] > 2 * WINDOW:
            runs.append([item])
        else:
            runs[-1].append(item)

    reach = WINDOW.total_seconds()
    found: set[str] = set()
    for i in range(0, len(runs), _RANGES_PER_READ):
        chunk = runs[i : i + _RANGES_PER_READ]
        spans = [
            and_(SampleSwatchRun.frame_at >= run[0][1] - WINDOW, SampleSwatchRun.frame_at <= run[-1][1] + WINDOW)
            for run in chunk
        ]
        stamps = [
            _utc(at).timestamp()
            for (at,) in db.query(SampleSwatchRun.frame_at)
            .filter(*_palette_frames(sha, machine_id), or_(*spans))
            .order_by(SampleSwatchRun.frame_at)
        ]
        for run in chunk:
            for puid, arrival in run:
                a = arrival.timestamp()
                j = bisect.bisect_left(stamps, a - reach)
                if j < len(stamps) and stamps[j] <= a + reach:
                    found.add(puid)
    return found


def nearest_frame(db: Session, sha: str | None, machine_id: Any, at: datetime) -> SampleSwatchRun | None:
    """The run of the palette frame for something on this machine at ``at``:
    the latest within WINDOW before it, else the first within WINDOW after.
    Two LIMIT 1 probes on the index at most."""
    if sha is None:
        return None
    at = _utc(at)
    before = (
        db.query(SampleSwatchRun)
        .filter(*_palette_frames(sha, machine_id), SampleSwatchRun.frame_at <= at, SampleSwatchRun.frame_at >= at - WINDOW)
        .order_by(SampleSwatchRun.frame_at.desc())
        .first()
    )
    if before is not None:
        return before
    return (
        db.query(SampleSwatchRun)
        .filter(*_palette_frames(sha, machine_id), SampleSwatchRun.frame_at > at, SampleSwatchRun.frame_at <= at + WINDOW)
        .order_by(SampleSwatchRun.frame_at.asc())
        .first()
    )


def frame_for_piece(db: Session, user: User, piece: MachinePiece) -> dict[str, Any]:
    """What the piece panel shows of the palette: how near a frame has to be,
    and the frame (None when there is none, or the viewer may not see it)
    with its swatches and where to load it from."""
    out: dict[str, Any] = {"window_s": int(WINDOW.total_seconds()), "frame": None}
    arrival = piece.seen_at or piece.recorded_at or piece.created_at
    if arrival is None:
        return out
    run = nearest_frame(db, model_sha256(db), piece.machine_id, arrival)
    if run is None:
        return out
    sample = db.get(Sample, run.sample_id)
    if sample is None or not sample.full_frame_path or not sample_access_visible(db, user, sample):
        return out
    frame_at = _utc(run.frame_at)
    out["frame"] = {
        "sample_id": str(sample.id),
        "frame_at": frame_at.isoformat(),
        # Negative when the frame was taken before the piece arrived.
        "offset_s": round((frame_at - _utc(arrival)).total_seconds(), 1),
        # Straight from storage when Hive can sign one; else the sample's full-frame route.
        "full_frame_url": get_backend().presigned_get_url(sample.full_frame_path),
        "run": serialize_run(run),
    }
    return out


def place_runs(db: Session, since: datetime) -> list[tuple[Any, datetime]]:
    """Give the runs stored since ``since`` that have no machine or frame time
    (stored by a release that did not set them) their sample's. Returns the
    (machine, frame time) of each. Does not commit."""
    rows = (
        db.query(SampleSwatchRun.id, Sample.machine_id, Sample.captured_at, Sample.uploaded_at)
        .join(Sample, Sample.id == SampleSwatchRun.sample_id)
        .filter(SampleSwatchRun.created_at >= since, SampleSwatchRun.frame_at.is_(None))
        .all()
    )
    placed: list[tuple[Any, datetime]] = []
    for run_id, machine_id, captured_at, uploaded_at in rows:
        at = frame_time(captured_at, uploaded_at)
        db.query(SampleSwatchRun).filter(SampleSwatchRun.id == run_id).update(
            {SampleSwatchRun.machine_id: machine_id, SampleSwatchRun.frame_at: at}, synchronize_session=False
        )
        placed.append((machine_id, _utc(at)))
    return placed
