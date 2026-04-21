"""Tests for the modal-tile CameraPreviewHub broadcaster.

Hardware is fully mocked — we stub ``cv2.VideoCapture`` so the test suite
never touches real USB devices.
"""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from server import camera_preview_hub
from server.camera_preview_hub import (
    CameraPreviewHub,
    _offer_frame_to_queue,
    reset_camera_preview_hub_for_tests,
)


# ---------------------------------------------------------------------------
# cv2.VideoCapture stub
# ---------------------------------------------------------------------------


class _FakeVideoCapture:
    """Emits a single synthetic frame forever, enough for the encoder."""

    opened = True
    instances: list["_FakeVideoCapture"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.released = False
        self._frame_counter = 0
        _FakeVideoCapture.instances.append(self)

    def isOpened(self) -> bool:  # noqa: N802 — match cv2 API
        return self.opened and not self.released

    def read(self):
        self._frame_counter += 1
        # Low-res solid-color frame — resize+imencode will accept it.
        frame = np.full((240, 426, 3), 42, dtype=np.uint8)
        return True, frame

    def release(self) -> None:
        self.released = True


def _patch_cv2_capture():
    return mock.patch.object(
        camera_preview_hub, "_open_camera", side_effect=_FakeVideoCapture
    )


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_fake_camera_service(owned_indices: list[int]):
    """Build a stub camera service whose devices claim ``owned_indices``."""
    devices: dict[str, object] = {}
    for idx in owned_indices:
        capture_thread = SimpleNamespace(getCameraSource=lambda idx=idx: idx)
        raw_frame = np.full((240, 426, 3), 17, dtype=np.uint8)
        latest_frame = SimpleNamespace(raw=raw_frame, timestamp=time.time())
        device = SimpleNamespace(
            capture_thread=capture_thread,
            latest_frame=latest_frame,
        )
        devices[f"role_{idx}"] = device
    return SimpleNamespace(devices=devices)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class CameraPreviewHubTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_camera_preview_hub_for_tests()
        _FakeVideoCapture.instances = []
        _FakeVideoCapture.opened = True

    def tearDown(self) -> None:
        reset_camera_preview_hub_for_tests()

    async def test_hub_starts_thread_on_first_subscribe(self) -> None:
        hub = CameraPreviewHub()
        hub.set_camera_service_getter(lambda: None)
        with _patch_cv2_capture():
            queue = hub.subscribe(7)
            try:
                self.assertTrue(hub.has_broadcaster(7))
                # Let the broadcaster produce at least one frame.
                frame = await asyncio.wait_for(queue.get(), timeout=2.0)
                self.assertIsInstance(frame, (bytes, bytearray))
                self.assertGreater(len(frame), 0)
                # JPEG magic bytes.
                self.assertEqual(frame[:2], b"\xff\xd8")
            finally:
                hub.unsubscribe(7, queue)

    async def test_hub_stops_thread_on_last_unsubscribe(self) -> None:
        hub = CameraPreviewHub()
        hub.set_camera_service_getter(lambda: None)
        with _patch_cv2_capture():
            q1 = hub.subscribe(3)
            q2 = hub.subscribe(3)
            try:
                # Pull one frame to confirm the thread is alive.
                await asyncio.wait_for(q1.get(), timeout=2.0)
                self.assertTrue(hub.has_broadcaster(3))
            finally:
                hub.unsubscribe(3, q1)
                # Still one subscriber — broadcaster must stay up.
                self.assertTrue(hub.has_broadcaster(3))
                hub.unsubscribe(3, q2)
            # Last subscriber gone → broadcaster removed.
            self.assertFalse(hub.has_broadcaster(3))
            self.assertEqual(0, hub.active_device_count())
            # Every VideoCapture we opened must have been released.
            for cap in _FakeVideoCapture.instances:
                self.assertTrue(cap.released, "VideoCapture was not released")

    async def test_hub_broadcasts_frames_to_multiple_subscribers(self) -> None:
        hub = CameraPreviewHub()
        hub.set_camera_service_getter(lambda: None)
        with _patch_cv2_capture():
            q1 = hub.subscribe(0)
            q2 = hub.subscribe(0)
            q3 = hub.subscribe(0)
            try:
                frame1 = await asyncio.wait_for(q1.get(), timeout=2.0)
                frame2 = await asyncio.wait_for(q2.get(), timeout=2.0)
                frame3 = await asyncio.wait_for(q3.get(), timeout=2.0)
                for frame in (frame1, frame2, frame3):
                    self.assertIsInstance(frame, (bytes, bytearray))
                    self.assertEqual(frame[:2], b"\xff\xd8")
                # Exactly one VideoCapture across three subscribers.
                self.assertEqual(1, len(_FakeVideoCapture.instances))
            finally:
                hub.unsubscribe(0, q1)
                hub.unsubscribe(0, q2)
                hub.unsubscribe(0, q3)

    async def test_hub_borrows_frame_when_device_is_vision_manager_owned(
        self,
    ) -> None:
        """If vision_manager already holds the device, the hub must NOT
        open a second VideoCapture — it re-encodes the existing raw frame.
        """
        hub = CameraPreviewHub()
        fake_service = _make_fake_camera_service(owned_indices=[5])
        hub.set_camera_service_getter(lambda: fake_service)
        with _patch_cv2_capture() as open_camera_mock:
            queue = hub.subscribe(5)
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=2.0)
                self.assertIsInstance(frame, (bytes, bytearray))
                self.assertEqual(frame[:2], b"\xff\xd8")
                # Borrowed from vision manager — never opened our own cap.
                self.assertEqual(0, open_camera_mock.call_count)
                self.assertEqual(0, len(_FakeVideoCapture.instances))
            finally:
                hub.unsubscribe(5, queue)

    async def test_queue_backpressure_drops_old_frames(self) -> None:
        """A slow consumer must not block the broadcaster thread."""
        hub = CameraPreviewHub()
        hub.set_camera_service_getter(lambda: None)
        with _patch_cv2_capture():
            queue = hub.subscribe(1)
            try:
                # Intentionally don't drain for a bit — broadcaster keeps
                # running, queue stays bounded.
                await asyncio.sleep(0.5)
                # Queue maxsize is 2 — must not exceed regardless of how
                # many frames were produced.
                self.assertLessEqual(queue.qsize(), 2)
                # Drain one; must be a valid JPEG.
                frame = await asyncio.wait_for(queue.get(), timeout=2.0)
                self.assertEqual(frame[:2], b"\xff\xd8")
            finally:
                hub.unsubscribe(1, queue)


class OfferFrameQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_offer_frame_drops_oldest_when_full(self) -> None:
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        await queue.put(b"old-a")
        await queue.put(b"old-b")
        _offer_frame_to_queue(queue, b"fresh")
        # We expect ``fresh`` at the tail and oldest evicted.
        self.assertEqual(queue.qsize(), 2)
        first = await queue.get()
        second = await queue.get()
        self.assertEqual(second, b"fresh")
        # After drop-oldest the remaining previous frame is ``old-b``.
        self.assertEqual(first, b"old-b")


if __name__ == "__main__":
    unittest.main()
