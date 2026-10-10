"""The UI's live camera video: one websocket per browser tab, ``/ws/video``.

The page sends the whole set of views it shows whenever that set changes, as
text: ``{"views": ["role/c_channel_2", "index/3"]}``. A role view is that camera
role's picture; an index view is a thumbnail of a camera by device index, for
the camera pickers.

Each frame goes out as one binary message, ``u16 LE key length | key (UTF-8) |
f64 LE capture time (s) | JPEG``. The picture is only pixels. What is drawn over
it travels as data beside it, and the page draws it, so a layer can be shown or
hidden without a new stream and is never out of date in the picture itself:

- ``{"layout": key, "zones": {...} | null, "crop": {...} | null}`` comes before
  a role view's first frame and again before the first frame after its zones
  change: the zones perception worked with, as shapes, and how the dashboard
  crops the camera to its channel. Coordinates are 0..1 across and down.
- ``{"detections": key, "ts": t, "boxes": [...]}`` comes just before a frame
  perception inferred on, with what it found there. A frame with none is the
  camera's own, from before perception started or while it is behind.

A view that cannot be served gets one text message, ``{"view": key, "error":
"..."}``, and a socket with nothing to send for a while sends ``{}``.

Each view has one producer while anyone watches it, which encodes each new
frame once for all of them. Each socket has one writer, which sends a view's
newest frame once the previous send has finished: a slow page skips frames
instead of queueing them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import struct
import time
from dataclasses import dataclass
from typing import Any, Dict

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket
from starlette.concurrency import run_in_threadpool

import machine_toml
from local_state import channel_polygons_revision
from perception.overlay import feedZoneShapes
from server import shared_state
from server.routers.cameras import _camera_source_for_role, _open_camera_for_probe
from vision.camera_modes import list_v4l2_modes, preview_capture_mode
from vision.dashboard_crop import dashboard_crop_spec

router = APIRouter()

logger = logging.getLogger(__name__)

# Max width of a role's picture: frames are downscaled to this before JPEG
# encoding, and its zones are traced at this size. 0 disables the resize.
PREVIEW_MAX_WIDTH = int(os.environ.get("SORTER_PREVIEW_MAX_WIDTH", "960"))

# At most this many frames a second per view, however fast perception runs:
# the budget for CPU on the machine and bandwidth to browsers.
PREVIEW_MAX_FPS = 10.0

# A socket that had nothing to send for this long sends "{}", so the page can
# tell a quiet socket from a dead one.
KEEPALIVE_S = 2.0

# A role shows the frames perception inferred on, with what it found, unless
# its newest is this far behind the camera's: then the camera's own, so a
# stalled perception never freezes the picture.
PERCEPTION_BEHIND_S = 1.0


@dataclass(frozen=True)
class _Shot:
    """A source frame and what goes with it. ``channel`` is the perception
    channel whose zones belong to it; ``cycle`` is perception's inference on
    this very frame, when it came from perception."""

    image: np.ndarray
    ts: float
    channel: Any = None
    cycle: dict | None = None


@dataclass(frozen=True)
class _Frame:
    """An encoded frame as the writers send it: ``boxes`` when perception
    inferred on it, and the layout it is drawn with, as ``(seq, layout)``."""

    seq: int
    ts: float
    jpeg: bytes
    boxes: list | None
    layout: tuple[int, dict] | None


class _Feed:
    """One view, shared by everyone watching it. While anyone watches, a
    producer on the event loop encodes each new frame once, in a worker
    thread, and wakes each watching socket's writer."""

    quality = 55

    def __init__(self, name: str) -> None:
        self.name = name  # in the preview.<name>.* counters
        self.watchers: list[asyncio.Event] = []
        self.seq = 0
        self.latest: _Frame | None = None
        self.last_ts: float | None = None
        self.producer: asyncio.Future | None = None

    def watch(self, wake: asyncio.Event) -> None:
        self.watchers.append(wake)
        if self.producer is None or self.producer.done():
            self.producer = asyncio.ensure_future(self._produce())

    def unwatch(self, wake: asyncio.Event) -> None:
        self.watchers.remove(wake)

    def _newest(self) -> _Shot | None:
        """The newest source frame. Worker thread."""
        raise NotImplementedError

    def _fit(self, frame: np.ndarray) -> np.ndarray:
        return frame

    def _boxes(self, shot: _Shot) -> list | None:
        return None

    def _layout(self, shot: _Shot) -> tuple[int, dict] | None:
        return None

    def _release(self) -> None:
        """Let go of whatever the stopped producer held. Worker thread."""

    def _render(self) -> tuple[float, bytes, list | None, tuple[int, dict] | None] | None:
        """The newest frame encoded, with what is drawn over it, or None when
        nothing is new. Worker thread."""
        shot = self._newest()
        # Never back in time, as when perception catches up with the camera
        # frames shown meanwhile; a clock set back resets.
        if shot is None or (self.last_ts is not None and 0.0 <= self.last_ts - shot.ts < 5.0):
            return None
        self.last_ts = shot.ts
        started = time.perf_counter()
        ok, jpeg = cv2.imencode(".jpg", self._fit(shot.image), [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return None
        shared_state.observePerfMs(f"preview.{self.name}.frame_age_ms", (time.time() - shot.ts) * 1000.0)
        shared_state.observePerfMs(f"preview.{self.name}.encode_ms", (time.perf_counter() - started) * 1000.0)
        shared_state.observePerfMs(f"preview.{self.name}.viewers", float(len(self.watchers)))
        return shot.ts, jpeg.tobytes(), self._boxes(shot), self._layout(shot)

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
                self.latest = _Frame(self.seq, *rendered)
                for wake in self.watchers:
                    wake.set()
                pause = started + 1.0 / PREVIEW_MAX_FPS - loop.time()
            await asyncio.sleep(max(0.0, pause))
            if not self.watchers:
                self.latest = None
                # Someone may start watching meanwhile; the loop then goes on.
                await loop.run_in_executor(None, self._release)


def _flat(points: Any, width: float, height: float) -> list[float]:
    """Points in frame pixels as a flat ``[x0, y0, x1, y1, ...]`` in 0..1."""
    out: list[float] = []
    for x, y in np.asarray(points, dtype=np.float64).reshape(-1, 2):
        out += [round(float(x) / width, 4), round(float(y) / height, 4)]
    return out


class _RoleFeed(_Feed):
    """A camera role's picture: the frames perception inferred on, with what
    it found and the zones it worked with, or the camera's own frames while
    perception has none."""

    def __init__(self, role: str) -> None:
        super().__init__(role)
        self.role = role
        # What the current layout was built from: (channel, zones revision,
        # frame size), and the layout.
        self.layout_for: tuple | None = None
        self.layout: tuple[int, dict] | None = None

    def _newest(self) -> _Shot | None:
        gc = shared_state.gc_ref
        ps = getattr(gc, "perception_service", None) if gc is not None else None
        channel_id = ps.channel_id_for_role(self.role) if ps is not None else None
        feed = shared_state.camera_service.get_feed(self.role) if shared_state.camera_service else None
        camera = feed.get_frame(annotated=False) if feed is not None else None
        cycle = ps.feed_cycle(channel_id) if channel_id is not None else None
        if cycle is not None:
            debug, channel = cycle
            frame = debug["frame"]
            if camera is None or camera.timestamp - float(frame.timestamp) < PERCEPTION_BEHIND_S:
                return _Shot(frame.bgr, float(frame.timestamp), channel, debug)
        if camera is None:
            return None
        channel = ps.channel_def(channel_id) if channel_id is not None else None
        return _Shot(camera.raw, camera.timestamp, channel)

    def _fit(self, frame: np.ndarray) -> np.ndarray:
        if 0 < PREVIEW_MAX_WIDTH < frame.shape[1]:
            height = int(round(frame.shape[0] * PREVIEW_MAX_WIDTH / frame.shape[1]))
            frame = cv2.resize(frame, (PREVIEW_MAX_WIDTH, height), interpolation=cv2.INTER_AREA)
        return frame

    def _boxes(self, shot: _Shot) -> list | None:
        """What perception found on this frame, as the operating feed shows it:
        the pieces on the channel (with their track ids), on C4 the merged
        boxes it acts on, and pieces seen in a foreign zone or past the exit."""
        cycle = shot.cycle
        if cycle is None:
            return None
        height, width = shot.image.shape[:2]

        def box(kind: str, bbox: Any, track_id: Any = None) -> dict:
            out: dict[str, Any] = {"kind": kind, "box": _flat(np.asarray(bbox[:4]), width, height)}
            if track_id is not None:
                out["id"] = int(track_id)
            return out

        detections = cycle.get("detections") or []
        track_ids = {
            tuple(int(v) for v in d.bbox[:4]): d.sv_bt_track_id
            for d in detections
            if d.sv_bt_track_id is not None
        }
        boxes = []
        for d in detections:
            if d.in_primary:
                continue
            if d.secondary_zone_ids:
                boxes.append(box("seen", d.bbox))
            if getattr(d, "in_margin", False):
                boxes.append(box("margin", d.bbox))
        # Originals (what the model drew); on C4 the merged boxes go over them.
        for b in cycle.get("pre_merge_bboxes") or cycle.get("on_channel_bboxes") or []:
            boxes.append(box("piece", b, track_ids.get(tuple(int(v) for v in b[:4]))))
        merged_ids = cycle.get("merged_track_ids") or []
        for i, b in enumerate(cycle.get("merged_bboxes") or []):
            boxes.append(box("merged", b, merged_ids[i] if i < len(merged_ids) else None))
        return boxes

    def _layout(self, shot: _Shot) -> tuple[int, dict] | None:
        """The layout this frame is drawn with, built again only when the
        channel perception works with, the saved zones or the frame size
        change."""
        height, width = shot.image.shape[:2]
        built_for = (shot.channel, channel_polygons_revision(), (width, height))
        last = self.layout_for
        if last is None or last[0] is not built_for[0] or last[1:] != built_for[1:]:
            crop = dashboard_crop_spec(self.role, width, height)
            layout = {
                "zones": feedZoneShapes(shot.channel, PREVIEW_MAX_WIDTH) if shot.channel is not None else None,
                "crop": {
                    "polygons": [_flat(polygon, width, height) for polygon in crop["polygons"]],
                    "rotation": float(crop["rotation_deg"]),
                }
                if crop
                else None,
            }
            self.layout = ((self.layout[0] + 1) if self.layout else 1, layout)
            self.layout_for = built_for
        return self.layout

    def _release(self) -> None:
        self.layout_for = None


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

    def _newest(self) -> _Shot | None:
        device = _device_capturing_index(self.index)
        if device is not None:
            # A role that claims this camera needs it more than a thumbnail does.
            self._release()
            frame_obj = device.latest_frame
            if frame_obj is None or frame_obj.raw is None:
                return None
            return _Shot(frame_obj.raw, frame_obj.timestamp)
        if self.cap is None:
            if time.monotonic() < self.retry_at:
                return None
            self.cap = _open_camera_for_preview(self.index)
        ok, frame = self.cap.read() if self.cap.isOpened() else (False, None)
        if not ok:
            self._release()
            self.retry_at = time.monotonic() + 2.0
            return None
        return _Shot(frame, time.time())

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
    path, _, _query = key.partition("?")  # a tab from before layouts asks with ?layer=…
    kind, _, name = path.partition("/")
    if kind == "index" and name.isdecimal():
        feed_key: tuple = ("index", int(name))
    elif kind == "role":
        try:
            source = _camera_source_for_role(machine_toml.read(), name)
        except HTTPException as exc:
            raise ValueError(exc.detail) from None
        except machine_toml.MachineTomlError as exc:
            raise ValueError(str(exc)) from None
        if source is None:
            raise ValueError(f"Camera role '{name}' not configured")
        feed_key = ("role", name)
    else:
        raise ValueError(f"Unknown view '{key}'")
    feed = _feeds.get(feed_key)
    if feed is None:
        feed = _feeds[feed_key] = _IndexFeed(feed_key[1]) if kind == "index" else _RoleFeed(feed_key[1])
    return feed


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
        self.sent_layout: dict[str, int] = {}  # view -> seq of the layout last sent
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
            self.sent_layout.pop(key, None)
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
                    frame = feed.latest
                    if frame is None or self.sent.get(key) == frame.seq or self.views.get(key) is not feed:
                        continue
                    skipped = frame.seq - self.sent[key] - 1 if key in self.sent else 0
                    self.sent[key] = frame.seq
                    started = time.perf_counter()
                    if frame.layout is not None and self.sent_layout.get(key) != frame.layout[0]:
                        self.sent_layout[key] = frame.layout[0]
                        await self._send(json.dumps({"layout": key, **frame.layout[1]}))
                    if frame.boxes is not None:
                        await self._send(json.dumps({"detections": key, "ts": frame.ts, "boxes": frame.boxes}))
                    await self._send(_frame_message(key, frame.ts, frame.jpeg))
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
