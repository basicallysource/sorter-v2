"""Tests for CaptureThread's 90-frame ring buffer used by drop-zone burst."""

import time
import unittest

import numpy as np

from irl.config import mkCameraConfig
from vision.camera import CaptureThread
from vision.types import CameraFrame


def _make_frame(marker: int) -> CameraFrame:
    # 4x4 single-pixel marker is cheap to build and keeps the ordering check trivial.
    raw = np.full((4, 4, 3), marker % 256, dtype=np.uint8)
    return CameraFrame(raw=raw, annotated=None, results=[], timestamp=time.time() + marker * 1e-3)


class CameraRingBufferTests(unittest.TestCase):
    def test_ring_buffer_caps_at_90_when_overfilled(self) -> None:
        capture = CaptureThread("test_cam", mkCameraConfig(device_index=-1))
        for i in range(100):
            capture._ring_buffer.append(_make_frame(i))
        self.assertEqual(90, len(capture._ring_buffer))
        # Oldest 10 were evicted — remaining frames start at marker 10.
        self.assertEqual(10, int(capture._ring_buffer[0].raw[0, 0, 0]))
        self.assertEqual(99, int(capture._ring_buffer[-1].raw[0, 0, 0]))

    def test_drain_ring_buffer_returns_chronological_slice(self) -> None:
        capture = CaptureThread("test_cam", mkCameraConfig(device_index=-1))
        for i in range(100):
            capture._ring_buffer.append(_make_frame(i))

        drained = capture.drain_ring_buffer(30)
        self.assertEqual(30, len(drained))
        markers = [int(f.raw[0, 0, 0]) for f in drained]
        # Should be the 30 most recent (markers 70..99) in chronological order.
        self.assertEqual(list(range(70, 100)), markers)
        # Non-destructive — the buffer still holds the same frames.
        self.assertEqual(90, len(capture._ring_buffer))

    def test_drain_returns_all_when_buffer_smaller_than_request(self) -> None:
        capture = CaptureThread("test_cam", mkCameraConfig(device_index=-1))
        for i in range(5):
            capture._ring_buffer.append(_make_frame(i))
        drained = capture.drain_ring_buffer(30)
        self.assertEqual(5, len(drained))
        self.assertEqual([0, 1, 2, 3, 4], [int(f.raw[0, 0, 0]) for f in drained])

    def test_drain_with_zero_or_negative_request_returns_empty(self) -> None:
        capture = CaptureThread("test_cam", mkCameraConfig(device_index=-1))
        capture._ring_buffer.append(_make_frame(0))
        self.assertEqual([], capture.drain_ring_buffer(0))
        self.assertEqual([], capture.drain_ring_buffer(-5))


if __name__ == "__main__":
    unittest.main()
