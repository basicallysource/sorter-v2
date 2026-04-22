"""Tests for BurstFrameStore + VisionManager.captureBurst wiring."""

from __future__ import annotations

import sys
import time
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

# Break the subsystems ↔ vision import cycle the same way
# test_vision_manager_feeder_dynamic does: stub the modules that would
# otherwise pull VisionManager back in during initial import.
_analysis_stub = types.ModuleType("subsystems.feeder.analysis")
_analysis_stub.parseSavedChannelArcZones = lambda *args, **kwargs: None
_analysis_stub.zoneSectionsForChannel = lambda *args, **kwargs: (set(), set())
_feeder_stub = types.ModuleType("subsystems.feeder")
_feeder_stub.analysis = _analysis_stub
_subsystems_stub = types.ModuleType("subsystems")
_subsystems_stub.feeder = _feeder_stub
sys.modules.setdefault("subsystems", _subsystems_stub)
sys.modules.setdefault("subsystems.feeder", _feeder_stub)
sys.modules.setdefault("subsystems.feeder.analysis", _analysis_stub)

from vision.burst_store import BurstFrameStore
from vision.types import CameraFrame


def _synthetic_frame(marker: int) -> CameraFrame:
    raw = np.full((8, 8, 3), marker % 256, dtype=np.uint8)
    return CameraFrame(raw=raw, annotated=None, results=[], timestamp=time.time() + marker * 1e-4)


class BurstFrameStoreTests(unittest.TestCase):
    def test_store_and_get_roundtrip(self) -> None:
        store = BurstFrameStore(max_pieces=3)
        frames = [{"role": "c_channel_3", "captured_ts": 1.0, "jpeg_b64": "a"}]
        store.store(42, frames)
        self.assertEqual(frames, store.get(42))
        self.assertIn(42, store)

    def test_store_appends_to_existing_entry(self) -> None:
        store = BurstFrameStore(max_pieces=3)
        store.store(1, [{"role": "c_channel_3", "captured_ts": 1.0, "jpeg_b64": "pre"}])
        store.store(1, [{"role": "carousel", "captured_ts": 2.0, "jpeg_b64": "post"}])
        merged = store.get(1)
        self.assertEqual(2, len(merged))
        self.assertEqual("pre", merged[0]["jpeg_b64"])
        self.assertEqual("post", merged[1]["jpeg_b64"])

    def test_capacity_enforced_with_lru_eviction(self) -> None:
        store = BurstFrameStore(max_pieces=50)
        for i in range(60):
            store.store(i, [{"role": "c_channel_3", "captured_ts": float(i), "jpeg_b64": f"f{i}"}])

        self.assertEqual(50, len(store))
        # Oldest 10 evicted.
        for i in range(10):
            self.assertIsNone(store.get(i))
        for i in range(10, 60):
            self.assertIsNotNone(store.get(i))

    def test_get_unknown_id_returns_none(self) -> None:
        store = BurstFrameStore(max_pieces=5)
        self.assertIsNone(store.get(999))

    def test_get_returns_shallow_copy(self) -> None:
        store = BurstFrameStore(max_pieces=5)
        store.store(7, [{"role": "c_channel_3", "captured_ts": 0.0, "jpeg_b64": "a"}])
        snapshot = store.get(7)
        snapshot.append({"role": "carousel", "captured_ts": 1.0, "jpeg_b64": "bad"})
        # Mutation of the returned list must not leak back into the store.
        self.assertEqual(1, len(store.get(7)))


class VisionManagerBurstCaptureTests(unittest.TestCase):
    """captureBurst drains the ring buffers of each CaptureThread immediately."""

    def _build_fake_manager(self):
        """Build a minimal object exposing just what captureBurst needs.

        We avoid instantiating the full VisionManager (heavy imports, DB
        state). Instead we import the class, bind the methods we want to test,
        and stub out the attributes they touch.
        """
        from vision.vision_manager import VisionManager

        fake = SimpleNamespace()
        fake._burst_store = BurstFrameStore(max_pieces=10)
        fake._burst_timers = {}
        fake._burst_lock = __import__("threading").Lock()
        fake._BURST_MAX_EDGE_PX = VisionManager._BURST_MAX_EDGE_PX
        fake._BURST_JPEG_QUALITY = VisionManager._BURST_JPEG_QUALITY
        fake.gc = SimpleNamespace(logger=SimpleNamespace(
            warning=lambda *a, **k: None, info=lambda *a, **k: None
        ))
        # Bind instance methods
        fake._encodeBurstFrame = VisionManager._encodeBurstFrame.__get__(fake)
        fake._burstCaptureThreadsByRole = VisionManager._burstCaptureThreadsByRole.__get__(fake)
        fake._drainBurstFrames = VisionManager._drainBurstFrames.__get__(fake)
        fake.captureBurst = VisionManager.captureBurst.__get__(fake)
        fake._finalizeBurst = VisionManager._finalizeBurst.__get__(fake)
        fake.getBurstFrames = VisionManager.getBurstFrames.__get__(fake)
        return fake

    def test_capture_burst_stores_pre_event_frames_immediately(self) -> None:
        fake = self._build_fake_manager()

        c3 = MagicMock()
        c3.drain_ring_buffer.return_value = [_synthetic_frame(i) for i in range(5)]
        carousel = MagicMock()
        carousel.drain_ring_buffer.return_value = [_synthetic_frame(100 + i) for i in range(3)]
        fake._c_channel_3_capture = c3
        fake._carousel_capture = carousel

        fake.captureBurst(777, pre_count=5, post_count=0, post_window_s=0.0)

        stored = fake.getBurstFrames(777)
        self.assertIsNotNone(stored)
        # 5 from c3 + 3 from carousel = 8 total, merged and chronologically sorted.
        self.assertEqual(8, len(stored))
        # Each frame has the required shape.
        for frame in stored:
            self.assertIn(frame["role"], {"c_channel_3", "carousel"})
            self.assertIsInstance(frame["jpeg_b64"], str)
            self.assertTrue(len(frame["jpeg_b64"]) > 0)
            self.assertIsInstance(frame["captured_ts"], float)
        # Sorted by captured_ts ascending.
        timestamps = [f["captured_ts"] for f in stored]
        self.assertEqual(sorted(timestamps), timestamps)
        # Drain was called with the requested count.
        c3.drain_ring_buffer.assert_called_once_with(5)
        carousel.drain_ring_buffer.assert_called_once_with(5)

    def test_capture_burst_tolerates_missing_capture_threads(self) -> None:
        fake = self._build_fake_manager()
        fake._c_channel_3_capture = None
        fake._carousel_capture = None
        # Must not raise.
        fake.captureBurst(9, pre_count=5, post_count=0, post_window_s=0.0)
        self.assertIsNone(fake.getBurstFrames(9))

    def test_finalize_burst_appends_post_event_frames(self) -> None:
        fake = self._build_fake_manager()

        c3 = MagicMock()
        c3.drain_ring_buffer.return_value = [_synthetic_frame(i) for i in range(2)]
        carousel = MagicMock()
        carousel.drain_ring_buffer.return_value = [_synthetic_frame(50 + i) for i in range(2)]
        fake._c_channel_3_capture = c3
        fake._carousel_capture = carousel

        fake.captureBurst(123, pre_count=2, post_count=0, post_window_s=0.0)
        self.assertEqual(4, len(fake.getBurstFrames(123)))

        # Simulate the timer callback firing with new post-event frames.
        c3.drain_ring_buffer.return_value = [_synthetic_frame(200 + i) for i in range(2)]
        carousel.drain_ring_buffer.return_value = [_synthetic_frame(300 + i) for i in range(2)]
        fake._finalizeBurst(123, post_count=2)

        merged = fake.getBurstFrames(123)
        self.assertEqual(8, len(merged))


if __name__ == "__main__":
    unittest.main()
