"""BoxMot ByteTrack runtime adapter.

ByteTrack is the production primary tracker for the C-channel perception
pipeline. It is deliberately wrapped in the same sorter-native contract as
``botsort_reid``: downstream runtimes still receive polar geometry, local
tracklet IDs, rotation-window real/ghost verdicts, and stable lifecycle reset
semantics. Appearance stays out of the primary path; ReID is supplied by the
``botsort_reid`` shadow tracker and merged one layer above.
"""

from __future__ import annotations

from typing import Any, Callable

from rt.contracts.registry import register_tracker

from .boxmot_reid import BotSortReIDTracker


@register_tracker("boxmot_bytetrack")
class BoxMotByteTrackTracker(BotSortReIDTracker):
    """BoxMot ByteTrack wrapped as a sorter-native ``Tracker``."""

    key = "boxmot_bytetrack"

    def __init__(
        self,
        *,
        polar_center: tuple[float, float] | None = None,
        polar_radius_range: tuple[float, float] | None = None,
        detection_score_threshold: float = 0.0,
        min_conf: float = 0.1,
        track_thresh: float = 0.6,
        match_thresh: float = 0.9,
        track_buffer: int = 30,
        frame_rate: int = 10,
        core_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._min_conf = float(min_conf)
        self._track_thresh = float(track_thresh)
        super().__init__(
            polar_center=polar_center,
            polar_radius_range=polar_radius_range,
            detection_score_threshold=detection_score_threshold,
            track_high_thresh=track_thresh,
            track_low_thresh=min_conf,
            new_track_thresh=track_thresh,
            track_buffer=track_buffer,
            match_thresh=match_thresh,
            frame_rate=frame_rate,
            with_reid=False,
            core_factory=core_factory,
        )

    def _default_core_factory(self) -> Any:
        try:
            from boxmot.trackers.bytetrack.bytetrack import ByteTrack
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "boxmot_bytetrack requires boxmot; install it or pick another "
                "tracker key"
            ) from exc
        return ByteTrack(
            min_conf=self._min_conf,
            track_thresh=self._track_thresh,
            match_thresh=self._match_thresh,
            track_buffer=self._track_buffer,
            frame_rate=self._frame_rate,
        )


__all__ = ["BoxMotByteTrackTracker"]
