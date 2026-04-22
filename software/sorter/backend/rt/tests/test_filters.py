from __future__ import annotations

import numpy as np

import rt.perception  # noqa: F401 - trigger filter registration
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import FILTERS
from rt.contracts.tracking import Track, TrackBatch
from rt.perception.filters.ghost import GhostFilter
from rt.perception.filters.size import SizeFilter


def _frame() -> FeedFrame:
    return FeedFrame(
        feed_id="f",
        camera_id="c",
        raw=np.zeros((4, 4, 3), dtype=np.uint8),
        gray=None,
        timestamp=1.0,
        monotonic_ts=1.0,
        frame_seq=1,
    )


def _track(
    tid: int,
    bbox: tuple[int, int, int, int],
    confirmed_real: bool = True,
) -> Track:
    return Track(
        track_id=tid,
        global_id=tid,
        piece_uuid=None,
        bbox_xyxy=bbox,
        score=0.9,
        confirmed_real=confirmed_real,
        angle_rad=None,
        radius_px=None,
        hit_count=5,
        first_seen_ts=1.0,
        last_seen_ts=1.0,
    )


def _batch(tracks: tuple[Track, ...]) -> TrackBatch:
    return TrackBatch(
        feed_id="f",
        frame_seq=1,
        timestamp=1.0,
        tracks=tracks,
        lost_track_ids=(),
    )


def test_filters_registered_in_registry() -> None:
    assert "size" in FILTERS.keys()
    assert "ghost" in FILTERS.keys()


def test_size_filter_drops_too_small() -> None:
    f = SizeFilter(min_area_px=100)
    tracks = (
        _track(1, (0, 0, 5, 5)),       # 25 px < 100
        _track(2, (0, 0, 20, 20)),     # 400 px >= 100
    )
    out = f.apply(_batch(tracks), _frame())
    assert [t.track_id for t in out.tracks] == [2]


def test_size_filter_drops_too_large() -> None:
    f = SizeFilter(min_area_px=10, max_area_px=200)
    tracks = (
        _track(1, (0, 0, 10, 10)),    # 100 px: in band
        _track(2, (0, 0, 30, 30)),    # 900 px: too large
        _track(3, (0, 0, 2, 2)),      # 4 px: too small
    )
    out = f.apply(_batch(tracks), _frame())
    assert [t.track_id for t in out.tracks] == [1]


def test_ghost_filter_keeps_only_confirmed() -> None:
    f = GhostFilter(confirmed_real_only=True)
    tracks = (
        _track(1, (0, 0, 10, 10), confirmed_real=True),
        _track(2, (0, 0, 10, 10), confirmed_real=False),
    )
    out = f.apply(_batch(tracks), _frame())
    assert [t.track_id for t in out.tracks] == [1]


def test_ghost_filter_disabled_passes_everything() -> None:
    f = GhostFilter(confirmed_real_only=False)
    tracks = (
        _track(1, (0, 0, 10, 10), confirmed_real=False),
        _track(2, (0, 0, 10, 10), confirmed_real=False),
    )
    out = f.apply(_batch(tracks), _frame())
    assert len(out.tracks) == 2
