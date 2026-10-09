"""The camera video websocket: each view's frames are encoded once for every
page that watches it, a page that falls behind skips frames, and what is drawn
over a frame comes beside it as data, never in its pixels."""

from __future__ import annotations

import asyncio
import json
import struct
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers import camera_feeds

ORIGIN = {"origin": "http://localhost:5173"}
C2 = "role/c_channel_2"
C3 = "role/c_channel_3"


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake cameras: both roles configured, and every render a new 64x48 frame
    whose capture time counts up. Returns the role of each render, in order."""
    rendered: list[str] = []

    def newest(feed: camera_feeds._RoleFeed) -> camera_feeds._Shot:
        rendered.append(feed.role)
        return camera_feeds._Shot(np.full((48, 64, 3), len(rendered) % 256, np.uint8), float(len(rendered)))

    monkeypatch.setattr(camera_feeds, "_feeds", {})
    monkeypatch.setattr(camera_feeds, "dashboard_crop_spec", lambda role, width, height: None)
    monkeypatch.setattr(camera_feeds, "PREVIEW_MAX_FPS", 100.0)
    monkeypatch.setattr(camera_feeds, "KEEPALIVE_S", 0.05)
    monkeypatch.setattr(camera_feeds._RoleFeed, "_newest", newest)
    monkeypatch.setattr(camera_feeds.machine_toml, "read", lambda: {"cameras": {"c_channel_2": 0, "c_channel_3": 1}})
    return rendered


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(camera_feeds.router)
    return TestClient(app)


def _unpack(data: bytes) -> tuple[str, float, bytes]:
    (length,) = struct.unpack_from("<H", data)
    (ts,) = struct.unpack_from("<d", data, 2 + length)
    return data[2 : 2 + length].decode(), ts, data[10 + length :]


def _receive(ws) -> tuple[str, float, bytes] | dict:
    """The next frame as (view, capture time, JPEG), or the next note, passing
    over keepalives."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        message = ws.receive()
        assert message["type"] == "websocket.send", message
        if message.get("bytes") is not None:
            return _unpack(message["bytes"])
        note = json.loads(message["text"])
        if note:
            return note
    raise AssertionError("only keepalives for 5 s")


def _next(ws) -> tuple[str, float, bytes] | dict:
    """The next frame or error note, passing over layouts and detections."""
    while True:
        message = _receive(ws)
        if not (isinstance(message, dict) and ("layout" in message or "detections" in message)):
            return message


def _wait_until(check, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_view_gets_its_frames_until_the_page_goes_away(renders: list[str]) -> None:
    with _client() as client:
        with client.websocket_connect("/ws/video", headers=ORIGIN) as ws:
            ws.send_json({"views": [C2]})
            view, ts, jpeg = _next(ws)
            later = _next(ws)
        feed = camera_feeds._feeds[("role", "c_channel_2")]
        _wait_until(lambda: feed.producer.done())
    assert view == C2 and later[0] == C2
    assert later[1] > ts >= 1.0
    assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape == (48, 64, 3)
    assert feed.watchers == [] and feed.latest is None


def test_a_view_let_go_of_gets_no_more_frames(renders: list[str]) -> None:
    with _client() as client, client.websocket_connect("/ws/video", headers=ORIGIN) as ws:
        ws.send_json({"views": [C2]})
        assert _next(ws)[0] == C2
        ws.send_json({"views": ["role/nope"]})
        # Frames sent before the change arrive first; after its note, none.
        while not isinstance(message := _next(ws), dict):
            assert message[0] == C2
        assert message == {"view": "role/nope", "error": "Unknown camera role 'nope'"}
        ws.send_json({"views": [C3]})
        assert [_next(ws)[0] for _ in range(3)] == [C3, C3, C3]
        feed = camera_feeds._feeds[("role", "c_channel_2")]
        _wait_until(lambda: feed.producer.done())
        assert feed.watchers == []


def test_two_pages_on_one_view_share_each_encoded_frame(renders: list[str]) -> None:
    with _client() as client:
        with client.websocket_connect("/ws/video", headers=ORIGIN) as first, client.websocket_connect(
            "/ws/video", headers=ORIGIN
        ) as second:
            first.send_json({"views": [C2]})
            second.send_json({"views": [C2]})
            later = {ts: jpeg for _, ts, jpeg in (_next(second) for _ in range(5))}
            earlier: dict[float, bytes] = {}
            while max(earlier, default=0.0) < max(later):
                _, ts, jpeg = _next(first)
                earlier[ts] = jpeg
        feed = camera_feeds._feeds[("role", "c_channel_2")]
        _wait_until(lambda: feed.producer.done())
    shared = earlier.keys() & later.keys()
    assert shared
    assert all(earlier[ts] == later[ts] for ts in shared)
    # One render for each frame published, not one for each page.
    assert len(camera_feeds._feeds) == 1
    assert len(renders) <= feed.seq + 1


def test_a_view_that_cannot_be_served_gets_one_error(renders: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(camera_feeds.machine_toml, "read", lambda: {"cameras": {"c_channel_3": 1}})
    with _client() as client, client.websocket_connect("/ws/video", headers=ORIGIN) as ws:
        ws.send_json({"views": ["role/nope", C2, "bogus"]})
        notes = [_next(ws) for _ in range(3)]
    assert notes == [
        {"view": "role/nope", "error": "Unknown camera role 'nope'"},
        {"view": C2, "error": "Camera role 'c_channel_2' not configured"},
        {"view": "bogus", "error": "Unknown view 'bogus'"},
    ]
    assert renders == []


class _StuckSocket:
    """A page that takes no frame until it is released. Its notes (the
    layout before the first frame) go through."""

    client = None

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.released = asyncio.Event()

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)
        await self.released.wait()

    async def send_text(self, text: str) -> None:
        pass


def test_a_page_that_takes_nothing_skips_frames_instead_of_queueing_them(
    renders: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(camera_feeds, "KEEPALIVE_S", 10.0)

    async def run() -> tuple[list[float], int]:
        socket = _StuckSocket()
        viewer = camera_feeds._Viewer(socket)
        writer = asyncio.ensure_future(viewer.write())
        await viewer.show(json.dumps({"views": [C2]}))
        feed = viewer.views[C2]
        while not socket.sent:
            await asyncio.sleep(0.01)
        # One view, so a frame's capture time is its number.
        while feed.seq < _unpack(socket.sent[0])[1] + 10:
            await asyncio.sleep(0.01)
        stuck_for = feed.seq
        socket.released.set()
        while len(socket.sent) < 2:
            await asyncio.sleep(0.01)
        writer.cancel()
        feed.unwatch(viewer.wake)
        await feed.producer
        return [_unpack(data)[1] for data in socket.sent[:2]], stuck_for

    (first, second), stuck_for = asyncio.run(run())
    # The first frame, then the newest one once the page took it: the frames
    # made meanwhile were never sent.
    assert second >= stuck_for >= first + 10


def test_a_thumbnail_lets_go_of_its_camera_once_a_role_claims_it(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCap:
        released = False

        def isOpened(self) -> bool:
            return True

        def read(self):
            return True, np.zeros((480, 640, 3), np.uint8)

        def release(self) -> None:
            FakeCap.released = True

    role_device = SimpleNamespace(latest_frame=SimpleNamespace(raw=np.zeros((720, 1280, 3), np.uint8), timestamp=5.0))
    claims = iter([None, None, role_device])
    monkeypatch.setattr(camera_feeds, "_device_capturing_index", lambda index: next(claims))
    monkeypatch.setattr(camera_feeds, "_open_camera_for_preview", lambda index: FakeCap())
    feed = camera_feeds._IndexFeed(2)
    assert feed._render() is not None and feed._render() is not None
    assert not FakeCap.released
    ts, jpeg, boxes, layout = feed._render()
    assert FakeCap.released and feed.cap is None and ts == 5.0 and boxes is None and layout is None
    assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape == (240, 426, 3)


def test_a_frame_comes_after_its_layout_and_detections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Perception's frames bring their boxes, in 0..1 of the frame, just before
    them; the layout comes before the first frame and again when perception's
    zones or the saved zones change, never baked into the pixels."""
    channels = [SimpleNamespace(name="first"), SimpleNamespace(name="second")]
    shots: list[camera_feeds._Shot] = []
    revision = [0]

    def newest(feed: camera_feeds._RoleFeed) -> camera_feeds._Shot:
        n = len(shots) + 1
        cycle = {
            "detections": [SimpleNamespace(bbox=(16, 12, 32, 24), in_primary=True, secondary_zone_ids=(), sv_bt_track_id=7)],
            "on_channel_bboxes": [(16, 12, 32, 24)],
        }
        shots.append(camera_feeds._Shot(np.zeros((48, 64, 3), np.uint8), float(n), channels[n >= 4], cycle))
        return shots[-1]

    monkeypatch.setattr(camera_feeds, "_feeds", {})
    monkeypatch.setattr(camera_feeds, "PREVIEW_MAX_FPS", 100.0)
    monkeypatch.setattr(camera_feeds._RoleFeed, "_newest", newest)
    monkeypatch.setattr(camera_feeds.machine_toml, "read", lambda: {"cameras": {"c_channel_2": 0}})
    monkeypatch.setattr(camera_feeds, "channel_polygons_revision", lambda: revision[0])
    monkeypatch.setattr(camera_feeds, "feedZoneShapes", lambda channel, width: {"of": channel.name, "saved": revision[0]})
    monkeypatch.setattr(
        camera_feeds,
        "dashboard_crop_spec",
        lambda role, width, height: {"polygons": [np.array([[0, 0], [32, 0], [32, 48]])], "rotation_deg": 90.0},
    )
    with _client() as client, client.websocket_connect("/ws/video", headers=ORIGIN) as ws:
        ws.send_json({"views": [C2]})
        messages = [_receive(ws) for _ in range(3)]
        layouts = []
        deadline = time.monotonic() + 5.0
        while len(layouts) < 2:
            assert time.monotonic() < deadline, f"layouts so far: {layouts}"
            message = _receive(ws)
            if isinstance(message, dict) and "layout" in message:
                layouts.append(message)
                if len(layouts) == 1:
                    revision[0] = 1
    assert messages[0] == {
        "layout": C2,
        "zones": {"of": "first", "saved": 0},
        "crop": {"polygons": [[0.0, 0.0, 0.5, 0.0, 0.5, 1.0]], "rotation": 90.0},
    }
    assert messages[1] == {
        "detections": C2,
        "ts": 1.0,
        "boxes": [{"kind": "piece", "box": [0.25, 0.25, 0.5, 0.5], "id": 7}],
    }
    assert messages[2][:2] == (C2, 1.0)
    assert [layout["zones"] for layout in layouts] == [{"of": "second", "saved": 0}, {"of": "second", "saved": 1}]


def test_a_role_shows_the_camera_while_perception_is_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = SimpleNamespace(name="c2")
    perceived = SimpleNamespace(bgr=np.zeros((4, 4, 3), np.uint8), timestamp=10.0)
    camera = SimpleNamespace(raw=np.ones((4, 4, 3), np.uint8), timestamp=10.5)
    perception = SimpleNamespace(
        channel_id_for_role=lambda role: 2,
        feed_cycle=lambda channel_id: ({"frame": perceived}, channel),
        channel_def=lambda channel_id: channel,
    )
    monkeypatch.setattr(camera_feeds.shared_state, "gc_ref", SimpleNamespace(perception_service=perception))
    monkeypatch.setattr(
        camera_feeds.shared_state,
        "camera_service",
        SimpleNamespace(get_feed=lambda role: SimpleNamespace(get_frame=lambda annotated: camera)),
    )
    feed = camera_feeds._RoleFeed("c_channel_2")
    shot = feed._newest()
    assert shot.ts == 10.0 and shot.cycle is not None and shot.channel is channel
    camera.timestamp = 11.5
    shot = feed._newest()
    assert shot.ts == 11.5 and shot.cycle is None and shot.channel is channel
