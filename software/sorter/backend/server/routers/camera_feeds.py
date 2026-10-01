"""The UI's live camera video: one websocket per browser tab, ``/ws/video``.

The page sends the whole set of views it shows whenever that set changes, as
text: ``{"views": ["role/c_channel_2?layer=annotated&dashboard=1", "index/3"]}``.
A role view is that camera role's preview, annotated or raw, whole or cropped
to its channel as the dashboard shows it; an index view is a thumbnail of a
camera by device index, for the camera pickers. Each frame goes out as one
binary message, ``u16 LE key length | key (UTF-8) | f64 LE capture time (s) |
JPEG``. A view that cannot be served gets one text message, ``{"view": key,
"error": "..."}``, and a socket with nothing to send for a while sends ``{}``.

Each view has one producer while anyone watches it, which renders and encodes
each new frame once for all of them. Each socket has one writer, which sends a
view's newest frame once the previous send has finished: a slow page skips
frames instead of queueing them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import struct
import time
from typing import Any, Dict
from urllib.parse import parse_qsl

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket
from starlette.concurrency import run_in_threadpool

import machine_toml
from server import shared_state
from server.routers.cameras import _camera_source_for_role, _open_camera_for_probe
from vision.camera_modes import list_v4l2_modes, preview_capture_mode
from vision.dashboard_crop import apply_dashboard_crop, dashboard_crop_spec

router = APIRouter()

logger = logging.getLogger(__name__)

# Max width of a role preview (annotated frame is downscaled to this before
# JPEG encoding). Annotation still runs at full capture resolution; this only
# shrinks the encoded-and-transmitted frame. 0 disables the resize.
PREVIEW_MAX_WIDTH = int(os.environ.get("SORTER_PREVIEW_MAX_WIDTH", "960"))

# At most this many frames a second per view, however fast perception runs:
# the budget for CPU on the machine and bandwidth to browsers.
PREVIEW_MAX_FPS = 10.0

# A socket that had nothing to send for this long sends "{}", so the page can
# tell a quiet socket from a dead one.
KEEPALIVE_S = 2.0


class _Feed:
    """One view, shared by everyone watching it. While anyone watches, a
    producer on the event loop renders and JPEG-encodes each new frame once, in
    a worker thread, and wakes each watching socket's writer."""

    quality = 55

    def __init__(self, name: str) -> None:
        self.name = name  # in the preview.<name>.* counters
        self.watchers: list[asyncio.Event] = []
        self.seq = 0
        self.latest: tuple[int, float, bytes] | None = None  # seq, capture time, JPEG
        self.last_ts: float | None = None
        self.producer: asyncio.Future | None = None

    def watch(self, wake: asyncio.Event) -> None:
        self.watchers.append(wake)
        if self.producer is None or self.producer.done():
            self.producer = asyncio.ensure_future(self._produce())

    def unwatch(self, wake: asyncio.Event) -> None:
        self.watchers.remove(wake)

    def _newest(self) -> tuple[np.ndarray, float] | None:
        """The newest source frame and its capture time. Worker thread."""
        raise NotImplementedError

    def _fit(self, frame: np.ndarray) -> np.ndarray:
        return frame

    def _release(self) -> None:
        """Let go of whatever the stopped producer held. Worker thread."""

    def _render(self) -> tuple[float, bytes] | None:
        """The newest frame's capture time and JPEG, or None when nothing is
        new. Worker thread."""
        newest = self._newest()
        if newest is None or newest[1] == self.last_ts:
            return None
        frame, ts = newest
        self.last_ts = ts
        started = time.perf_counter()
        ok, jpeg = cv2.imencode(".jpg", self._fit(frame), [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return None
        shared_state.observePerfMs(f"preview.{self.name}.frame_age_ms", (time.time() - ts) * 1000.0)
        shared_state.observePerfMs(f"preview.{self.name}.encode_ms", (time.perf_counter() - started) * 1000.0)
        shared_state.observePerfMs(f"preview.{self.name}.viewers", float(len(self.watchers)))
        return ts, jpeg.tobytes()

    async def _produce(self) -> None:
        loop = asyncio.get_running_loop()
        while self.watchers:
            started = loop.time()
            pause = 0.02  # nothing new yet
            try:
                rendered = await loop.run_in_executor(None, self._render)
            except Exception as exc:
                logger.warning(f"camera feed {self.name}: {exc}")
                rendered, pause = None, 1.0
            if rendered is not None:
                self.seq += 1
                self.latest = (self.seq, *rendered)
                for wake in self.watchers:
                    wake.set()
                pause = started + 1.0 / PREVIEW_MAX_FPS - loop.time()
            await asyncio.sleep(max(0.0, pause))
            if not self.watchers:
                self.latest = None
                # Someone may start watching meanwhile; the loop then goes on.
                await loop.run_in_executor(None, self._release)


class _RoleFeed(_Feed):
    """A camera role's preview: annotated or raw, whole or cropped to its
    channel as the dashboard shows it."""

    def __init__(self, role: str, annotated: bool, dashboard: bool) -> None:
        super().__init__(role)
        self.role = role
        self.annotated = annotated
        self.dashboard = dashboard
        # (frame size, crop spec, when computed): recomputed now and then so
        # zone edits show up in views that stay open.
        self.crop: tuple[tuple[int, int], Dict[str, Any] | None, float] | None = None

    def _newest(self) -> tuple[np.ndarray, float] | None:
        gc = shared_state.gc_ref
        ps = getattr(gc, "perception_service", None) if gc is not None else None
        channel_id = ps.channel_id_for_role(self.role) if ps is not None else None
        if self.annotated and channel_id is not None:
            # Rendered at preview width once per inference frame, shared.
            result = ps.preview_frame(channel_id, PREVIEW_MAX_WIDTH)
            if result is not None:
                return result
        # Annotations off, or perception not ready yet: raw pixels from the
        # same shared capture thread, never a VisionManager overlay.
        feed = shared_state.camera_service.get_feed(self.role) if shared_state.camera_service else None
        frame_obj = feed.get_frame(annotated=False) if feed is not None else None
        return (frame_obj.raw, frame_obj.timestamp) if frame_obj is not None else None

    def _fit(self, frame: np.ndarray) -> np.ndarray:
        if 0 < PREVIEW_MAX_WIDTH < frame.shape[1]:
            height = int(round(frame.shape[0] * PREVIEW_MAX_WIDTH / frame.shape[1]))
            frame = cv2.resize(frame, (PREVIEW_MAX_WIDTH, height), interpolation=cv2.INTER_AREA)
        if self.dashboard:
            frame_h, frame_w = frame.shape[:2]
            if self.crop is None or self.crop[0] != (frame_w, frame_h) or time.monotonic() - self.crop[2] > 5.0:
                self.crop = ((frame_w, frame_h), dashboard_crop_spec(self.role, frame_w, frame_h), time.monotonic())
            frame = apply_dashboard_crop(frame, self.crop[1])
        return frame

    def _release(self) -> None:
        self.crop = None


def _open_camera_for_preview(index: int) -> cv2.VideoCapture:
    # Thumbnails are 426 px wide: open at a small MJPEG mode rather than the
    # camera's own resolution, which is 4K on a 4K camera.
    if platform.system() != "Linux":
        return _open_camera_for_probe(index)
    mode = preview_capture_mode(list_v4l2_modes(index))
    if mode is None:
        return _open_camera_for_probe(index)
    from vision.camera import _open_capture_source

    return _open_capture_source(
        index, width=mode["width"], height=mode["height"], fps=mode["fps"], fourcc="MJPG"
    )


def _device_capturing_index(index: int):
    """Return the camera-service device already capturing ``index``, if any.

    When that index is assigned to a role, the camera service's capture thread
    already holds /dev/videoN open; opening a second VideoCapture on it fights
    the live pipeline for frames and spikes USB/CPU. Reusing the running
    capture thread avoids the duplicate open.
    """
    service = shared_state.camera_service
    if service is None:
        return None
    for device in service.devices.values():
        try:
            if device.capture_thread.getCameraSource() == index:
                return device
        except Exception:
            continue
    return None


class _IndexFeed(_Feed):
    """A picker's thumbnail of a camera by device index: from the running
    capture when a role owns that camera, else from the camera opened here,
    only while no role owns it."""

    quality = 60

    def __init__(self, index: int) -> None:
        super().__init__(f"camera_{index}")
        self.index = index
        self.cap: cv2.VideoCapture | None = None
        self.retry_at = 0.0

    def _newest(self) -> tuple[np.ndarray, float] | None:
        device = _device_capturing_index(self.index)
        if device is not None:
            # A role that claims this camera needs it more than a thumbnail does.
            self._release()
            frame_obj = device.latest_frame
            if frame_obj is None or frame_obj.raw is None:
                return None
            return frame_obj.raw, frame_obj.timestamp
        if self.cap is None:
            if time.monotonic() < self.retry_at:
                return None
            self.cap = _open_camera_for_preview(self.index)
        ok, frame = self.cap.read() if self.cap.isOpened() else (False, None)
        if not ok:
            self._release()
            self.retry_at = time.monotonic() + 2.0
            return None
        return frame, time.time()

    def _fit(self, frame: np.ndarray) -> np.ndarray:
        return cv2.resize(frame, (426, 240))

    def _release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


_feeds: Dict[tuple, _Feed] = {}


def _feed_for(key: str) -> _Feed:
    """The shared feed behind a view key. Raises ValueError saying why there
    is none. Reads machine.toml, so it runs in a worker thread."""
    path, _, query = key.partition("?")
    kind, _, name = path.partition("/")
    if kind == "index" and name.isdecimal():
        feed_key: tuple = (int(name),)
    elif kind == "role":
        try:
            source = _camera_source_for_role(machine_toml.read(), name)
        except HTTPException as exc:
            raise ValueError(exc.detail) from None
        except machine_toml.MachineTomlError as exc:
            raise ValueError(str(exc)) from None
        if source is None:
            raise ValueError(f"Camera role '{name}' not configured")
        params = dict(parse_qsl(query))
        feed_key = (name, params.get("layer", "annotated") == "annotated", params.get("dashboard") == "1")
    else:
        raise ValueError(f"Unknown view '{key}'")
    return _feeds.setdefault(feed_key, _IndexFeed(*feed_key) if kind == "index" else _RoleFeed(*feed_key))


def _frame_message(key: str, ts: float, jpeg: bytes) -> bytes:
    key_bytes = key.encode()
    return struct.pack(f"<H{len(key_bytes)}sd", len(key_bytes), key_bytes, ts) + jpeg


class _Viewer:
    """One /ws/video socket: the views its page shows, and the one writer that
    sends each view's newest frame once the previous send has finished."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.views: dict[str, _Feed] = {}
        self.sent: dict[str, int] = {}  # view -> seq of the frame last sent
        self.notes: list[str] = []  # text messages waiting for the writer
        self.wake = asyncio.Event()

    async def read(self) -> None:
        """Take each new set of views until the page goes away."""
        while True:
            message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text"):
                await self.show(message["text"])

    async def show(self, text: str) -> None:
        """Watch exactly the views in ``{"views": [...]}``."""
        try:
            wanted = json.loads(text)["views"]
        except (ValueError, KeyError, TypeError):
            return
        if not isinstance(wanted, list) or not all(isinstance(key, str) for key in wanted):
            return
        for key in [key for key in self.views if key not in wanted]:
            self.views.pop(key).unwatch(self.wake)
            self.sent.pop(key, None)
        for key in dict.fromkeys(wanted):
            if key in self.views:
                continue
            try:
                feed = await run_in_threadpool(_feed_for, key)
            except ValueError as exc:
                self.notes.append(json.dumps({"view": key, "error": str(exc)}))
                self.wake.set()
                continue
            self.views[key] = feed
            feed.watch(self.wake)
            self.wake.set()  # its newest frame, if it has one, goes out now

    async def write(self) -> None:
        """Send until the socket fails or a send takes longer than the
        slow-client limit; the page then reconnects."""
        try:
            while True:
                self.wake.clear()
                while self.notes:
                    await self._send(self.notes.pop(0))
                for key, feed in list(self.views.items()):
                    latest = feed.latest
                    if latest is None or self.sent.get(key) == latest[0] or self.views.get(key) is not feed:
                        continue
                    seq, ts, jpeg = latest
                    skipped = seq - self.sent[key] - 1 if key in self.sent else 0
                    self.sent[key] = seq
                    started = time.perf_counter()
                    await self._send(_frame_message(key, ts, jpeg))
                    shared_state.observePerfMs(f"preview.{feed.name}.send_ms", (time.perf_counter() - started) * 1000.0)
                    shared_state.observePerfMs(f"preview.{feed.name}.skipped", float(skipped))
                try:
                    await asyncio.wait_for(self.wake.wait(), KEEPALIVE_S)
                except TimeoutError:
                    self.notes.append("{}")
        except TimeoutError:
            host = self.websocket.client.host if self.websocket.client else "?"
            limit = shared_state.WS_SLOW_CLIENT_LIMIT_S
            logger.warning(f"video socket {host}: took no frame for {limit:.0f} s; closing it")
        except Exception:
            pass  # the socket is gone; the reader sees the disconnect

    async def _send(self, message: str | bytes) -> None:
        send = self.websocket.send_text if isinstance(message, str) else self.websocket.send_bytes
        await asyncio.wait_for(send(message), shared_state.WS_SLOW_CLIENT_LIMIT_S)


@router.websocket("/ws/video")
async def video_socket(websocket: WebSocket) -> None:
    if not await shared_state.acceptWebsocket(websocket):
        return
    viewer = _Viewer(websocket)
    tasks = [asyncio.ensure_future(viewer.read()), asyncio.ensure_future(viewer.write())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for feed in viewer.views.values():
            feed.unwatch(viewer.wake)
