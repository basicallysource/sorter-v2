"""Size-based track filter: keeps tracks whose bbox area is within bounds."""

from __future__ import annotations

from rt.contracts.feed import FeedFrame
from rt.contracts.registry import register_filter
from rt.contracts.tracking import TrackBatch


@register_filter("size")
class SizeFilter:
    """Drop tracks whose bbox area is outside [min_area_px, max_area_px]."""

    key = "size"

    def __init__(self, min_area_px: int, max_area_px: int | None = None) -> None:
        self._min = int(min_area_px)
        self._max: int | None = int(max_area_px) if max_area_px else None

    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch:
        kept = []
        for tr in tracks.tracks:
            x1, y1, x2, y2 = tr.bbox_xyxy
            area = max(0, x2 - x1) * max(0, y2 - y1)
            if area < self._min:
                continue
            if self._max is not None and area > self._max:
                continue
            kept.append(tr)
        return TrackBatch(
            feed_id=tracks.feed_id,
            frame_seq=tracks.frame_seq,
            timestamp=tracks.timestamp,
            tracks=tuple(kept),
            lost_track_ids=tracks.lost_track_ids,
        )


__all__ = ["SizeFilter"]
