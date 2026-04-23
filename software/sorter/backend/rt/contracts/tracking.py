from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .detection import DetectionBatch
from .feed import FeedFrame


@dataclass(frozen=True, slots=True)
class Track:
    """A tracked piece with stable IDs and temporal state.

    ``confirmed_real`` and ``ghost`` are tri-state together:
    - ``confirmed_real=True``  → tracker has seen motion during a known
      rotation window; this is a real piece.
    - ``ghost=True``           → tracker has accumulated enough
      rotation-windowed evidence of non-motion; safe to drop.
    - both ``False``           → pending judgment (no or too few
      rotation-windowed samples yet); pass through.
    """

    track_id: int
    global_id: int | None
    piece_uuid: str | None
    bbox_xyxy: tuple[int, int, int, int]
    score: float
    confirmed_real: bool
    angle_rad: float | None
    radius_px: float | None
    hit_count: int
    first_seen_ts: float
    last_seen_ts: float
    ghost: bool = False


@dataclass(frozen=True, slots=True)
class TrackBatch:
    """Output of a Tracker for one tick on one feed."""

    feed_id: str
    frame_seq: int
    timestamp: float
    tracks: tuple[Track, ...]
    lost_track_ids: tuple[int, ...]


class Tracker(Protocol):
    """Per-feed tracker strategy mapping DetectionBatch → TrackBatch over time."""

    key: str

    def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch: ...

    def live_global_ids(self) -> set[int]: ...

    def reset(self) -> None: ...
