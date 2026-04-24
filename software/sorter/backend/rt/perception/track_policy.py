"""Runtime-facing interpretation of tracker reality flags.

The detector is now the primary signal. Tracker ``ghost`` / ``confirmed_real``
verdicts are still useful, but runtimes should consume them consistently:
``ghost=True`` is the only hard negative, while a stable high-confidence
detection may be acted on before rotation-window confirmation catches up.
"""

from __future__ import annotations

from typing import Any


DEFAULT_STABLE_MIN_HITS = 2
DEFAULT_STABLE_MIN_SCORE = 0.35


def is_declared_ghost(track: Any) -> bool:
    return bool(getattr(track, "ghost", False))


def is_visible_track(track: Any) -> bool:
    return not is_declared_ghost(track)


def stable_detection(
    track: Any,
    *,
    min_hits: int = DEFAULT_STABLE_MIN_HITS,
    min_score: float = DEFAULT_STABLE_MIN_SCORE,
    min_age_s: float = 0.0,
) -> bool:
    if is_declared_ghost(track):
        return False
    if bool(getattr(track, "confirmed_real", False)):
        return True
    try:
        hits = int(getattr(track, "hit_count", 0) or 0)
        score = float(getattr(track, "score", 0.0) or 0.0)
        first_seen = float(getattr(track, "first_seen_ts", 0.0) or 0.0)
        last_seen = float(getattr(track, "last_seen_ts", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    if hits < int(min_hits) or score < float(min_score):
        return False
    if float(min_age_s) <= 0.0:
        return True
    return max(0.0, last_seen - first_seen) >= float(min_age_s)


def action_track(
    track: Any,
    *,
    min_hits: int = DEFAULT_STABLE_MIN_HITS,
    min_score: float = DEFAULT_STABLE_MIN_SCORE,
) -> bool:
    return stable_detection(track, min_hits=min_hits, min_score=min_score)


def admission_basis(
    track: Any,
    *,
    min_hits: int = DEFAULT_STABLE_MIN_HITS,
    min_score: float = DEFAULT_STABLE_MIN_SCORE,
    min_age_s: float = 0.0,
) -> str:
    if is_declared_ghost(track):
        return "ghost"
    if bool(getattr(track, "confirmed_real", False)):
        return "confirmed_real"
    if stable_detection(
        track,
        min_hits=min_hits,
        min_score=min_score,
        min_age_s=min_age_s,
    ):
        return "stable_detection"
    return "pending_detection"


__all__ = [
    "DEFAULT_STABLE_MIN_HITS",
    "DEFAULT_STABLE_MIN_SCORE",
    "action_track",
    "admission_basis",
    "is_declared_ghost",
    "is_visible_track",
    "stable_detection",
]
