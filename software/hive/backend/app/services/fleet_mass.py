"""How much the fleet has sorted, by mass.

The piece counter answers "how many"; this answers "how much", which is the
number people actually have intuition for — nobody knows whether 4 million
pieces is a lot, and everybody knows what a tonne is.

**It is a join across two databases and cannot be done in SQL.** The piece
histogram lives in Postgres (`machine_pieces`) and the weights live in the
parts catalog, which is a separate SQLite file (`parts.db`, see
`services/profile_engine/db.py`). So: one grouped scan in Postgres, one batched
weight lookup in SQLite, multiplied in Python.

**Coverage is part of the answer, not a footnote.** A piece contributes mass
only if it was identified AND its part has a weight on file, and neither is
guaranteed — an unidentified piece has no part id at all, and plenty of catalog
entries have no weight. Reporting only the sum would understate the truth by
however much is missing and would silently drift as coverage changed. So the
payload carries the measured sum, how many pieces are behind it, and an
estimate that extends the mean matched piece over the unmatched remainder.
A consumer says "at least X" from the first or "about Y" from the second, and
`coverage` is what tells it which claim it can defend.

In practice the two halves of the shortfall are nothing like equal, and a
consumer choosing between the two figures should know which one it is bounded
by. Almost every identified piece gets a weight; what is missing is pieces the
machine never identified at all. So `known_grams` is not "the conservative
measurement" — it is the mass of the identified subset, and it treats every
unidentified piece as weighing zero. Neither figure is wrong; they answer
different questions, and `coverage` is the one number that says how far apart
they can be.

**Nothing here runs on a request path.** A worker computes, `latest()` reads.
See the note above `_latest`.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.services.periodic import PeriodicWorker

logger = logging.getLogger(__name__)

# What a pass costs, and why no request may pay it. The group-by behind this is
# one sequential scan of machine_pieces — about a second at 660k rows, growing
# with the fleet — plus a batched lookup in the catalog. That is affordable on a
# clock and not on a request path: `/stats` is the most-called endpoint hive has
# and is polled whether or not anyone is looking, so a request that recomputed
# would eventually be every tenth request recomputing, and a slow fleet would be
# a slow website.
#
# So a worker computes and PUBLISHES; `latest()` reads what was published and
# never computes. A lifetime total that is half an hour stale differs from a
# live one in a digit nobody reads, which is what makes this trade free.
_latest: dict[str, Any] | None = None
_lock = threading.Lock()


def latest() -> dict[str, Any]:
    """The last published answer. Never computes.

    Before the first pass finishes this is the empty shape with a null
    `computed_at`, which is the honest thing to serve: zeroes that are labelled
    as not-yet-computed rather than a number a caller would quote.
    """
    with _lock:
        if _latest is None:
            return {**_empty(), "computed_at": None}
        return _latest


def refresh(db: Session, machine_ids: list) -> dict[str, Any]:
    """Recompute and publish. The worker's job, and what a test drives directly."""
    computed = _compute(db, machine_ids)
    computed["computed_at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        global _latest
        _latest = computed
    return computed


def reset_cache() -> None:
    """Drop what was published, so the next pass starts clean. For tests."""
    global _latest
    with _lock:
        _latest = None


def _refresh_pass() -> dict[str, Any]:
    """One pass over the whole fleet — every non-archived machine.

    The set is decided here rather than passed in because there is exactly one
    set anybody asks about, and a worker that took an argument would invite a
    second one nothing refreshes.
    """
    db = SessionLocal()
    try:
        ids = [mid for (mid,) in db.query(Machine.id).filter(Machine.archived_at.is_(None)).all()]
        answer = refresh(db, ids)
        return {
            "last_run_known_kg": answer["known_kg"],
            "last_run_coverage": answer["coverage"],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_WORKER: PeriodicWorker | None = None
_WORKER_LOCK = threading.Lock()


def get_fleet_mass_worker() -> PeriodicWorker:
    global _WORKER
    if _WORKER is None:
        with _WORKER_LOCK:
            if _WORKER is None:
                _WORKER = PeriodicWorker(
                    "fleet-mass-worker",
                    _refresh_pass,
                    # Read per pass so the cadence can be changed without a restart.
                    lambda: max(60.0, float(settings.FLEET_MASS_REFRESH_INTERVAL_MINUTES) * 60.0),
                    # Publish before the first request rather than after, so the
                    # not-yet-computed shape above is a second at boot and not a
                    # whole interval.
                    run_at_start=True,
                )
    return _WORKER


def _compute(db: Session, machine_ids: list) -> dict[str, Any]:
    if not machine_ids:
        return _empty()

    # Every piece, identified or not, so `total_pieces` is the real denominator
    # and the estimate below extrapolates over the right population.
    total_pieces = int(
        db.query(func.count())
        .select_from(MachinePiece)
        .filter(MachinePiece.machine_id.in_(machine_ids))
        .scalar()
        or 0
    )

    counts = (
        db.query(MachinePiece.part_id, func.count())
        .filter(MachinePiece.machine_id.in_(machine_ids))
        .filter(MachinePiece.part_id.isnot(None))
        .group_by(MachinePiece.part_id)
        .all()
    )
    by_part = {str(pid): int(n) for pid, n in counts}
    if not by_part:
        return _empty(total_pieces=total_pieces)

    try:
        from app.services.profile_catalog import get_profile_catalog_service

        weights = get_profile_catalog_service().batch_part_weights(list(by_part))
    except Exception:
        # A box without the catalog loaded should still answer the piece
        # question rather than 500 — mass comes back as unknown coverage.
        logger.exception("fleet mass: catalog unavailable")
        return _empty(total_pieces=total_pieces)

    grams = 0.0
    matched_pieces = 0
    for part_num, n in by_part.items():
        w = weights.get(part_num)
        if w is None:
            continue
        grams += w * n
        matched_pieces += n

    mean_g = (grams / matched_pieces) if matched_pieces else None
    estimated = (mean_g * total_pieces) if mean_g is not None else None

    return {
        "known_grams": round(grams, 1),
        "known_kg": round(grams / 1000.0, 2),
        # The pieces actually behind known_grams, and the two ways they fall
        # short: never identified, or identified as a part with no weight.
        "matched_pieces": matched_pieces,
        "total_pieces": total_pieces,
        "identified_pieces": sum(by_part.values()),
        "coverage": round(matched_pieces / total_pieces, 4) if total_pieces else 0.0,
        "mean_piece_grams": round(mean_g, 3) if mean_g is not None else None,
        # The mean matched piece extended over every piece. Sound only if the
        # unmatched pieces resemble the matched ones; they skew small and odd
        # (that is partly WHY they are unmatched), so read it as an upper-ish
        # estimate rather than a measurement.
        "estimated_total_grams": round(estimated, 1) if estimated is not None else None,
        "estimated_total_kg": round(estimated / 1000.0, 2) if estimated is not None else None,
        "distinct_parts": len(by_part),
        "distinct_parts_weighed": sum(1 for p in by_part if p in weights),
    }


def _empty(total_pieces: int = 0) -> dict[str, Any]:
    return {
        "known_grams": 0.0,
        "known_kg": 0.0,
        "matched_pieces": 0,
        "total_pieces": total_pieces,
        "identified_pieces": 0,
        "coverage": 0.0,
        "mean_piece_grams": None,
        "estimated_total_grams": None,
        "estimated_total_kg": None,
        "distinct_parts": 0,
        "distinct_parts_weighed": 0,
        "computed_at": None,
    }


__all__ = [
    "latest",
    "refresh",
    "reset_cache",
    "get_fleet_mass_worker",
]
