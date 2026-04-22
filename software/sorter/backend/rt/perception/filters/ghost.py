"""Ghost filter: drops tracks that have not been flagged confirmed_real.

Replaces the whitelist whitelist-gate that previously lived inside the
tracker with an explicit pipeline-filter stage. Pieces that demonstrated
real motion (monotonic angular progress or centroid drift) are kept;
apparatus ghosts (screws, reflections, guides) are filtered out.
"""

from __future__ import annotations

from rt.contracts.feed import FeedFrame
from rt.contracts.registry import register_filter
from rt.contracts.tracking import TrackBatch


@register_filter("ghost")
class GhostFilter:
    """Keep only tracks whose `confirmed_real` flag is True (by default)."""

    key = "ghost"

    def __init__(self, confirmed_real_only: bool = True) -> None:
        self._confirmed_only = bool(confirmed_real_only)

    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch:
        if not self._confirmed_only:
            return tracks
        kept = tuple(tr for tr in tracks.tracks if tr.confirmed_real)
        return TrackBatch(
            feed_id=tracks.feed_id,
            frame_seq=tracks.frame_seq,
            timestamp=tracks.timestamp,
            tracks=kept,
            lost_track_ids=tracks.lost_track_ids,
        )


__all__ = ["GhostFilter"]
