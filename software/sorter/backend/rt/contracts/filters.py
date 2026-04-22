from __future__ import annotations

from typing import Protocol

from .feed import FeedFrame
from .tracking import TrackBatch


class Filter(Protocol):
    """Post-tracking filter: prunes or annotates tracks."""

    key: str

    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch: ...


class FilterChain:
    """Ordered composition of filters. Built from config, immutable."""

    def __init__(self, filters: tuple[Filter, ...]) -> None:
        self._filters = filters

    def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch:
        for f in self._filters:
            tracks = f.apply(tracks, frame)
        return tracks

    @property
    def filters(self) -> tuple[Filter, ...]:
        return self._filters
