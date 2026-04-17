"""Shared types for the feeder tracker (SORT-style Kalman + Hungarian)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TrackedPiece:
    """One live track snapshot emitted per ``Tracker.update(...)`` tick."""

    global_id: int
    source_role: str
    bbox: tuple[int, int, int, int]
    center: tuple[float, float]
    velocity_px_per_s: tuple[float, float]
    first_seen_ts: float
    origin_seen_ts: float
    last_seen_ts: float
    hit_count: int
    coasting: bool
    score: float | None
    handoff_from: str | None = None

    def to_dict(self) -> dict:
        return {
            "global_id": self.global_id,
            "source_role": self.source_role,
            "bbox": list(self.bbox),
            "center": [self.center[0], self.center[1]],
            "velocity_px_per_s": [self.velocity_px_per_s[0], self.velocity_px_per_s[1]],
            "first_seen_ts": self.first_seen_ts,
            "origin_seen_ts": self.origin_seen_ts,
            "last_seen_ts": self.last_seen_ts,
            "hit_count": self.hit_count,
            "coasting": self.coasting,
            "score": self.score,
            "handoff_from": self.handoff_from,
        }


@dataclass
class PendingHandoff:
    """A track that died inside an exit zone and is waiting for a downstream rebirth."""

    from_role: str
    global_id: int
    last_center: tuple[float, float]
    last_seen_ts: float
    expires_at: float


class Tracker(Protocol):
    """Minimal interface a per-camera tracker implementation must satisfy."""

    def update(
        self,
        bboxes: list[tuple[int, int, int, int]],
        scores: list[float],
        timestamp: float,
    ) -> list[TrackedPiece]: ...

    def reset(self) -> None: ...

    def active_tracks(self) -> list[TrackedPiece]: ...
