"""FastAPI test-client coverage for rt.shadow.api.

We build a minimal ``FastAPI`` app with only the shadow router mounted so
we don't pull in the full backend import graph. The router reads state
via a bridge-import of ``backend.server.shared_state``; we manipulate
those module-level dicts directly for each test.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from rt.shadow.api import router  # noqa: E402
from rt.shadow.iou import RollingIouTracker  # noqa: E402


@dataclass
class _FakeTrack:
    track_id: int
    global_id: int | None
    piece_uuid: str | None
    bbox_xyxy: tuple[int, int, int, int]
    score: float
    confirmed_real: bool
    angle_rad: float | None
    radius_px: float | None
    hit_count: int
    first_seen_ts: float
    last_seen_ts: float


@dataclass
class _FakeBatch:
    feed_id: str
    frame_seq: int
    timestamp: float
    tracks: tuple[_FakeTrack, ...]
    lost_track_ids: tuple[int, ...]


class _FakeRunner:
    def __init__(self, batch: _FakeBatch | None, *, running: bool = True) -> None:
        self._batch = batch
        self._running = running
        self._name = "FakeRunner[c2]"

    def latest_tracks(self) -> _FakeBatch | None:
        return self._batch


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/rt/shadow")
    return TestClient(app)


@pytest.fixture
def shared_state_module():
    """Isolate shared_state mutations between tests."""
    from server import shared_state

    # Snapshot + restore.
    original_runners = dict(shared_state.shadow_runners)
    original_iou = dict(shared_state.shadow_iou)
    original_bus = shared_state.shadow_bus
    yield shared_state
    shared_state.shadow_runners.clear()
    shared_state.shadow_runners.update(original_runners)
    shared_state.shadow_iou.clear()
    shared_state.shadow_iou.update(original_iou)
    shared_state.shadow_bus = original_bus


def test_status_disabled_by_default(
    client: TestClient, shared_state_module
) -> None:
    shared_state_module.shadow_runners.clear()
    shared_state_module.shadow_iou.clear()
    resp = client.get("/api/rt/shadow/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {"enabled": False, "roles": []}


def test_status_reports_active_role(
    client: TestClient, shared_state_module
) -> None:
    batch = _FakeBatch(
        feed_id="shadow_c2",
        frame_seq=42,
        timestamp=12.5,
        tracks=(
            _FakeTrack(
                track_id=1,
                global_id=1,
                piece_uuid=None,
                bbox_xyxy=(0, 0, 20, 20),
                score=0.9,
                confirmed_real=True,
                angle_rad=None,
                radius_px=None,
                hit_count=5,
                first_seen_ts=10.0,
                last_seen_ts=12.5,
            ),
        ),
        lost_track_ids=(),
    )
    runner = _FakeRunner(batch)
    iou = RollingIouTracker(window_sec=10.0)
    shared_state_module.shadow_runners["c2"] = runner
    shared_state_module.shadow_iou["c2"] = iou

    resp = client.get("/api/rt/shadow/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["enabled"] is True
    assert len(payload["roles"]) == 1
    role_payload = payload["roles"][0]
    assert role_payload["role"] == "c2"
    assert role_payload["health"]["running"] is True
    assert role_payload["health"]["latest"]["track_count"] == 1
    assert role_payload["iou"]["window_sec"] == pytest.approx(10.0)


def test_tracks_missing_role_returns_empty_shape(
    client: TestClient, shared_state_module
) -> None:
    shared_state_module.shadow_runners.clear()
    resp = client.get("/api/rt/shadow/tracks/c2")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["role"] == "c2"
    assert payload["available"] is False
    assert payload["tracks"] == []
    assert payload["lost_track_ids"] == []


def test_tracks_serializes_batch(
    client: TestClient, shared_state_module
) -> None:
    track = _FakeTrack(
        track_id=7,
        global_id=7,
        piece_uuid="abc-123",
        bbox_xyxy=(5, 5, 25, 25),
        score=0.5,
        confirmed_real=False,
        angle_rad=1.23,
        radius_px=100.0,
        hit_count=2,
        first_seen_ts=1.0,
        last_seen_ts=1.5,
    )
    batch = _FakeBatch(
        feed_id="shadow_c2",
        frame_seq=9,
        timestamp=1.5,
        tracks=(track,),
        lost_track_ids=(3, 4),
    )
    runner = _FakeRunner(batch)
    shared_state_module.shadow_runners["c2"] = runner
    shared_state_module.shadow_iou["c2"] = RollingIouTracker(window_sec=5.0)

    resp = client.get("/api/rt/shadow/tracks/c2")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["available"] is True
    assert payload["feed_id"] == "shadow_c2"
    assert payload["frame_seq"] == 9
    assert payload["tracks"][0]["track_id"] == 7
    assert payload["tracks"][0]["piece_uuid"] == "abc-123"
    assert payload["tracks"][0]["bbox_xyxy"] == [5, 5, 25, 25]
    assert payload["tracks"][0]["confirmed_real"] is False
    assert payload["tracks"][0]["angle_rad"] == pytest.approx(1.23)
    assert payload["lost_track_ids"] == [3, 4]
