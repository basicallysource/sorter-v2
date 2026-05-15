"""Encode-path timestamp pinning: overlays must compose on the frame the
detector ran on, not on whatever ``latest_frame`` happens to be at encode
time. Without pinning, the bbox visually leads or lags the piece because
the detection cache and the displayed frame come from different ticks."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from vision.camera_feed import CameraFeed
from vision.types import CameraFrame


def _frame(ts: float, marker: int = 0) -> CameraFrame:
    raw = np.full((4, 4, 3), marker % 256, dtype=np.uint8)
    return CameraFrame(raw=raw, annotated=None, results=[], timestamp=ts)


class _Overlay:
    """Records which frame.timestamp it was asked to annotate."""

    def __init__(self) -> None:
        self.seen_timestamps: list[float] = []

    def annotate(self, img: np.ndarray) -> np.ndarray:
        return img


class _CallbackOverlay:
    def __init__(self, sink: list[float]) -> None:
        self._sink = sink

    def annotate(self, img: np.ndarray) -> np.ndarray:
        # The image itself is opaque; we tag the frame via the marker
        # value in the raw pixel data set by ``_frame``.
        self._sink.append(float(img[0, 0, 0]))
        return img


class _Device:
    def __init__(self, latest: CameraFrame, lookup: dict[float, CameraFrame]) -> None:
        self.latest_frame = latest
        self._lookup = lookup
        self.lookup_calls: list[float] = []

    def frame_at_or_before(self, ts: float, *, tolerance_s: float = 0.5) -> CameraFrame | None:
        self.lookup_calls.append(float(ts))
        # Pretend we have a small ring buffer keyed by timestamp.
        best: CameraFrame | None = None
        best_ts = -1.0
        for buf_ts, frame in self._lookup.items():
            if buf_ts <= ts and ts - buf_ts <= tolerance_s and buf_ts > best_ts:
                best = frame
                best_ts = buf_ts
        return best


class CameraFeedPinningTests(unittest.TestCase):
    def test_get_frame_uses_pinned_timestamp_when_overlays_present(self) -> None:
        old = _frame(100.0, marker=10)
        new = _frame(100.5, marker=99)
        device = _Device(latest=new, lookup={100.0: old, 100.5: new})
        feed = CameraFeed("carousel", device, pinned_ts_provider=lambda: 100.0)
        seen: list[float] = []
        feed.add_overlay(_CallbackOverlay(seen))

        result = feed.get_frame(annotated=True)
        # Overlay was applied to the pinned (older) frame, not the latest.
        self.assertEqual([10.0], seen)
        self.assertIsNotNone(result)
        self.assertEqual(100.0, result.timestamp)
        self.assertEqual([100.0], device.lookup_calls)

    def test_get_frame_falls_back_to_latest_when_pin_returns_none(self) -> None:
        latest = _frame(100.5, marker=99)
        device = _Device(latest=latest, lookup={})
        feed = CameraFeed("carousel", device, pinned_ts_provider=lambda: None)
        seen: list[float] = []
        feed.add_overlay(_CallbackOverlay(seen))

        feed.get_frame(annotated=True)
        self.assertEqual([99.0], seen)
        self.assertEqual([], device.lookup_calls)

    def test_get_frame_skips_ring_lookup_when_pin_equals_latest(self) -> None:
        latest = _frame(100.5, marker=99)
        device = _Device(latest=latest, lookup={100.5: latest})
        feed = CameraFeed("carousel", device, pinned_ts_provider=lambda: 100.5)
        feed.add_overlay(_CallbackOverlay([]))

        feed.get_frame(annotated=True)
        # Pin matches latest → no need to walk the ring.
        self.assertEqual([], device.lookup_calls)

    def test_get_frame_uses_latest_when_ring_lookup_misses(self) -> None:
        latest = _frame(100.5, marker=99)
        # Pinning asks for 99.0 but the ring has nothing within tolerance.
        device = _Device(latest=latest, lookup={})
        feed = CameraFeed("carousel", device, pinned_ts_provider=lambda: 99.0)
        seen: list[float] = []
        feed.add_overlay(_CallbackOverlay(seen))

        result = feed.get_frame(annotated=True)
        self.assertEqual([99.0], seen)
        self.assertEqual(100.5, result.timestamp)

    def test_set_pinned_ts_provider_invalidates_annotation_cache(self) -> None:
        latest = _frame(100.5, marker=99)
        old = _frame(100.0, marker=10)
        device = _Device(latest=latest, lookup={100.0: old, 100.5: latest})
        feed = CameraFeed("carousel", device)
        seen: list[float] = []
        feed.add_overlay(_CallbackOverlay(seen))

        # No pin yet → uses latest.
        feed.get_frame(annotated=True)
        self.assertEqual([99.0], seen)

        # Install pin → cache must reset so the next call sees the older frame.
        feed.set_pinned_ts_provider(lambda: 100.0)
        feed.get_frame(annotated=True)
        self.assertEqual([99.0, 10.0], seen)


if __name__ == "__main__":
    unittest.main()
