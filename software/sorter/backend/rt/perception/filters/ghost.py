"""Ghost filter: drops tracks the tracker has declared ghosts.

The tracker judges ghost vs. real only on samples observed during known
rotation windows (pulses on C2/C3, carousel moves on C4). That gives a
tri-state per track:

- ``confirmed_real=True``  — moved with the rotation → keep
- ``ghost=True``           — stayed put through the rotation → drop
- both ``False``           — pending, not yet judged → keep

This filter drops only the explicitly-declared ghosts. Pending tracks
stay in the batch so the downstream runtime can still act on a newly
dropped piece before motion has been observed for it.
"""

from __future__ import annotations

from rt.contracts.feed import FeedFrame
from rt.contracts.registry import register_filter
from rt.contracts.tracking import TrackBatch


@register_filter("ghost")
class GhostFilter:
    """Drop tracks whose ``ghost`` flag has been set by the tracker."""

    key = "ghost"

    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch:
        kept = tuple(tr for tr in tracks.tracks if not tr.ghost)
        return TrackBatch(
            feed_id=tracks.feed_id,
            frame_seq=tracks.frame_seq,
            timestamp=tracks.timestamp,
            tracks=kept,
            lost_track_ids=tracks.lost_track_ids,
        )


__all__ = ["GhostFilter"]
