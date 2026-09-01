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
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.machine_piece import MachinePiece

logger = logging.getLogger(__name__)

# The whole-table group-by behind this is one sequential scan of machine_pieces,
# which is seconds at fleet scale and grows with the fleet. Nothing downstream
# needs it fresher than this: it is a lifetime total, so a ten-minute-old answer
# differs from a live one in a digit nobody reads.
CACHE_TTL_S = 600.0

_cache: dict[str, Any] | None = None
_cache_key: tuple | None = None
_cache_at: float = 0.0
_lock = threading.Lock()


def get_fleet_mass(db: Session, machine_ids: list) -> dict[str, Any]:
    """Total mass sorted across these machines, with its coverage."""
    global _cache, _cache_key, _cache_at

    key = tuple(sorted(str(m) for m in machine_ids))
    with _lock:
        if _cache is not None and _cache_key == key and (time.monotonic() - _cache_at) < CACHE_TTL_S:
            return _cache

    # Computed outside the lock: it is a multi-second scan, and two concurrent
    # callers doing it twice is cheaper than every caller queueing behind one.
    computed = _compute(db, machine_ids)

    with _lock:
        _cache, _cache_key, _cache_at = computed, key, time.monotonic()
    return computed


def reset_cache() -> None:
    """Drop the memo. For tests, which sync pieces and re-ask within the TTL."""
    global _cache, _cache_key, _cache_at
    with _lock:
        _cache, _cache_key, _cache_at = None, None, 0.0


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
    }
