"""Stable identity vocabulary for physical pieces and tracker tracklets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


_UNKNOWN_TRACKER_KEY = "unknown"


def _clean(value: Any, *, fallback: str | None = None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def new_tracker_epoch() -> str:
    """Return a short opaque epoch for one tracker adapter lifetime."""

    return uuid.uuid4().hex[:12]


def new_piece_uuid() -> str:
    """Return the stable identity for one physical piece."""

    return uuid.uuid4().hex[:12]


def build_tracklet_id(
    *,
    feed_id: str,
    tracker_key: str | None,
    tracker_epoch: str,
    raw_track_id: int,
) -> str:
    """Build the qualified identity for one tracker-local track id."""

    feed = _clean(feed_id, fallback="unknown_feed") or "unknown_feed"
    tracker = _clean(tracker_key, fallback=_UNKNOWN_TRACKER_KEY) or _UNKNOWN_TRACKER_KEY
    epoch = _clean(tracker_epoch, fallback="unknown_epoch") or "unknown_epoch"
    return f"{feed}:{tracker}:{epoch}:{int(raw_track_id)}"


@dataclass(frozen=True, slots=True)
class TrackletIdentity:
    """One observation identity produced by a tracker in a specific epoch."""

    feed_id: str
    tracker_key: str
    tracker_epoch: str
    raw_track_id: int

    @property
    def tracklet_id(self) -> str:
        return build_tracklet_id(
            feed_id=self.feed_id,
            tracker_key=self.tracker_key,
            tracker_epoch=self.tracker_epoch,
            raw_track_id=self.raw_track_id,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "tracklet_id": self.tracklet_id,
            "feed_id": self.feed_id,
            "tracker_key": self.tracker_key,
            "tracker_epoch": self.tracker_epoch,
            "raw_track_id": self.raw_track_id,
        }


def tracklet_payload(
    *,
    feed_id: str,
    tracker_key: str | None,
    tracker_epoch: str,
    raw_track_id: int,
) -> dict[str, Any]:
    identity = TrackletIdentity(
        feed_id=_clean(feed_id, fallback="unknown_feed") or "unknown_feed",
        tracker_key=_clean(tracker_key, fallback=_UNKNOWN_TRACKER_KEY) or _UNKNOWN_TRACKER_KEY,
        tracker_epoch=_clean(tracker_epoch, fallback="unknown_epoch") or "unknown_epoch",
        raw_track_id=int(raw_track_id),
    )
    return identity.as_payload()


__all__ = [
    "TrackletIdentity",
    "build_tracklet_id",
    "new_piece_uuid",
    "new_tracker_epoch",
    "tracklet_payload",
]
