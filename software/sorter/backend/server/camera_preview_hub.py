"""Fan-out JPEG preview broadcaster for modal camera-picker tiles.

The camera picker in the zone editor shows a grid of live tiles so the
operator can recognize which physical USB camera is which. ``CameraPreviewHub``
keeps exactly one ``VideoCapture`` per device index across all subscribers,
re-uses the existing camera_service capture thread when the device is already
in use for a primary role, and broadcasts JPEG bytes to each subscriber
through a small asyncio queue.

Design notes:

- Hub is a module-level singleton accessed via :func:`get_camera_preview_hub`.
- One background thread per device index. Thread starts on first subscribe,
  exits on last unsubscribe.
- Subscribers receive raw JPEG bytes over a WebSocket via
  ``/ws/camera-preview/{index}``. Each binary message is exactly one JPEG
  frame. The queue depth is ``asyncio.Queue(maxsize=2)`` — on backpressure
  the thread drops the oldest frame instead of blocking, because previews
  are latency-sensitive, not loss-sensitive.
- If the device is already owned by camera_service (primary role feed),
  we do NOT open a second capture. We encode the latest frame from the
  existing capture thread instead.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import threading
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from vision.camera_service import CameraService

logger = logging.getLogger(__name__)

# Preview frame pipeline parameters — tuned for modal tiles, not full feeds.
_PREVIEW_WIDTH = 426
_PREVIEW_HEIGHT = 240
_PREVIEW_JPEG_QUALITY = 60
_PREVIEW_FPS = 10.0
_PREVIEW_FRAME_INTERVAL_S = 1.0 / _PREVIEW_FPS

# Queue depth per subscriber: 2 frames is enough to ride over one tick of
# event-loop jitter without letting a slow websocket back up into the capture
# thread.
_SUBSCRIBER_QUEUE_MAXSIZE = 2


def _open_camera(index: int) -> cv2.VideoCapture:
    """Same ``VideoCapture`` selection as ``server.routers.cameras._open_camera``.

    Duplicated here to keep the hub independent from the router import graph
    (the router file is large and pulls vision/global deps we don't want in
    this module's import chain).
    """
    if platform.system() == "Darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


class _DeviceBroadcaster:
    """Single-device fan-out worker.

    Owns (or borrows) a capture source and pushes encoded JPEG bytes into
    every subscriber queue at ``_PREVIEW_FPS``.
    """

    def __init__(
        self,
        device_index: int,
        loop: asyncio.AbstractEventLoop,
        camera_service_getter,
    ) -> None:
        self._device_index = device_index
        self._loop = loop
        self._camera_service_getter = camera_service_getter
        self._subscribers: list[asyncio.Queue[bytes]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"CameraPreviewHub[{self._device_index}]",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        # Don't join under lock — the thread itself calls back into
        # publish_frame which takes the same lock.
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            self._started = False
            self._thread = None

    def add_subscriber(self, queue: asyncio.Queue[bytes]) -> None:
        with self._lock:
            self._subscribers.append(queue)

    def remove_subscriber(self, queue: asyncio.Queue[bytes]) -> int:
        with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass
            return len(self._subscribers)

    # ---- Capture source resolution ----

    def _borrow_camera_service_frame(self) -> np.ndarray | None:
        """Return latest raw frame from camera_service's capture thread, if any.

        When the device is owned by camera_service (primary role feed), we
        must NOT open a second VideoCapture. Instead we re-encode the last
        frame from the existing capture thread.
        """
        camera_service = self._camera_service_getter()
        if camera_service is None:
            return None
        try:
            devices = camera_service.devices
        except Exception:
            return None
        for device in devices.values():
            try:
                source = device.capture_thread.getCameraSource()
            except Exception:
                continue
            if isinstance(source, int) and source == self._device_index:
                frame = device.latest_frame
                if frame is not None and frame.raw is not None:
                    return frame.raw
                return None
        return None

    def _camera_service_owns_device(self) -> bool:
        camera_service = self._camera_service_getter()
        if camera_service is None:
            return False
        try:
            devices = camera_service.devices
        except Exception:
            return False
        for device in devices.values():
            try:
                source = device.capture_thread.getCameraSource()
            except Exception:
                continue
            if isinstance(source, int) and source == self._device_index:
                return True
        return False

    # ---- Frame publish ----

    def _publish(self, jpeg_bytes: bytes) -> None:
        """Push ``jpeg_bytes`` into every subscriber queue (drop-oldest)."""
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                self._loop.call_soon_threadsafe(
                    _offer_frame_to_queue, queue, jpeg_bytes
                )
            except RuntimeError:
                # Event loop already closed — ignore.
                pass

    # ---- Main loop ----

    def _run(self) -> None:
        try:
            self._run_impl()
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "CameraPreviewHub broadcaster crashed for device %s",
                self._device_index,
            )

    def _run_impl(self) -> None:
        cap: cv2.VideoCapture | None = None
        try:
            while not self._stop_event.is_set():
                if self.subscriber_count == 0:
                    # Last subscriber left — exit loop, caller will clear us.
                    break

                jpeg = self._next_frame(cap)
                if isinstance(jpeg, tuple):
                    cap, frame_bytes = jpeg
                else:
                    frame_bytes = jpeg

                if frame_bytes is not None:
                    self._publish(frame_bytes)
                # Pace the loop either way — a missing frame shouldn't busy-
                # loop against a dead device.
                self._stop_event.wait(_PREVIEW_FRAME_INTERVAL_S)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    def _next_frame(
        self, cap: cv2.VideoCapture | None
    ) -> tuple[cv2.VideoCapture | None, bytes | None] | bytes | None:
        """Produce the next JPEG frame, returning ``cap`` so the loop can
        lazily open the capture once camera_service releases the device.
        """
        # Prefer the camera_service frame while it owns the device.
        if self._camera_service_owns_device():
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
            raw = self._borrow_camera_service_frame()
            if raw is None:
                return cap, None
            return cap, _encode_preview(raw)

        # Not owned — open our own VideoCapture lazily.
        if cap is None:
            cap = _open_camera(self._device_index)
            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                return None, None

        ret, frame = cap.read()
        if not ret or frame is None:
            return cap, None
        return cap, _encode_preview(frame)


def _encode_preview(frame: np.ndarray) -> bytes | None:
    try:
        thumb = cv2.resize(frame, (_PREVIEW_WIDTH, _PREVIEW_HEIGHT))
        ok, buf = cv2.imencode(
            ".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, _PREVIEW_JPEG_QUALITY]
        )
    except Exception:
        return None
    if not ok:
        return None
    return bytes(buf)


def _offer_frame_to_queue(queue: asyncio.Queue[bytes], jpeg_bytes: bytes) -> None:
    """Drop-oldest enqueue. Runs on the asyncio event loop thread."""
    # Trim to make room — we only care about the freshest frame for previews.
    while queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    try:
        queue.put_nowait(jpeg_bytes)
    except asyncio.QueueFull:
        # Shouldn't happen after the trim, but stay defensive.
        pass


class CameraPreviewHub:
    """Process-wide registry of per-device preview broadcasters.

    Thread-safe. Broadcasters are reference-counted by subscriber list; the
    worker thread and any owned VideoCapture are cleaned up as soon as the
    last subscriber unsubscribes.
    """

    def __init__(self) -> None:
        self._broadcasters: dict[int, _DeviceBroadcaster] = {}
        self._lock = threading.Lock()
        # Injection hook so tests can supply a stub camera service without
        # booting the full backend.
        self._camera_service_getter = _default_camera_service_getter

    def set_camera_service_getter(self, getter) -> None:
        self._camera_service_getter = getter

    def subscribe(
        self,
        device_index: int,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> asyncio.Queue[bytes]:
        if loop is None:
            loop = asyncio.get_event_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        with self._lock:
            broadcaster = self._broadcasters.get(device_index)
            if broadcaster is None:
                broadcaster = _DeviceBroadcaster(
                    device_index=device_index,
                    loop=loop,
                    camera_service_getter=self._camera_service_getter,
                )
                self._broadcasters[device_index] = broadcaster
            broadcaster.add_subscriber(queue)
            broadcaster.start()
        return queue

    def unsubscribe(self, device_index: int, queue: asyncio.Queue[bytes]) -> None:
        broadcaster: _DeviceBroadcaster | None = None
        should_stop = False
        with self._lock:
            broadcaster = self._broadcasters.get(device_index)
            if broadcaster is None:
                return
            remaining = broadcaster.remove_subscriber(queue)
            if remaining == 0:
                self._broadcasters.pop(device_index, None)
                should_stop = True
        if should_stop and broadcaster is not None:
            broadcaster.stop()

    # ---- Test helpers ----

    def has_broadcaster(self, device_index: int) -> bool:
        with self._lock:
            return device_index in self._broadcasters

    def active_device_count(self) -> int:
        with self._lock:
            return len(self._broadcasters)

    def stop_all(self) -> None:
        with self._lock:
            broadcasters = list(self._broadcasters.values())
            self._broadcasters.clear()
        for broadcaster in broadcasters:
            broadcaster.stop()


def _default_camera_service_getter() -> Optional["CameraService"]:
    """Resolve the live ``camera_service`` from shared_state.

    Imported lazily so tests can import ``camera_preview_hub`` without
    pulling the entire backend bootstrap graph.
    """
    try:
        from server import shared_state
    except Exception:
        return None
    return getattr(shared_state, "camera_service", None)


# Process-wide singleton.
_HUB: CameraPreviewHub | None = None
_HUB_LOCK = threading.Lock()


def get_camera_preview_hub() -> CameraPreviewHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = CameraPreviewHub()
        return _HUB


def reset_camera_preview_hub_for_tests() -> None:
    """Drop the singleton between tests so state doesn't leak."""
    global _HUB
    with _HUB_LOCK:
        if _HUB is not None:
            _HUB.stop_all()
        _HUB = None
