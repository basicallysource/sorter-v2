"""Smoke tests for the rt-ported detection endpoints in server/routers/detection.py.

These bypass the full FastAPI app and exercise the router helpers directly,
injecting a fake rt runtime handle + camera service into ``shared_state`` so
the detect/current + baseline endpoints can be verified without loading the
full app (which would pull hardware + ONNX).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi import HTTPException

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from rt.contracts.detection import Detection, DetectionBatch  # noqa: E402
from rt.contracts.feed import FeedFrame, RectZone  # noqa: E402
from server import shared_state  # noqa: E402
from server.routers import detection as detection_router  # noqa: E402


class _FakeFeed:
    def __init__(self, feed_id: str, raw: np.ndarray) -> None:
        self.feed_id = feed_id
        self._raw = raw

    def latest(self) -> FeedFrame | None:
        if self._raw is None:
            return None
        return FeedFrame(
            feed_id=self.feed_id,
            camera_id="fake",
            raw=self._raw,
            gray=None,
            timestamp=0.0,
            monotonic_ts=0.0,
            frame_seq=1,
        )


class _FakeDetector:
    """Returns a fixed detection at the centre of every crop."""

    def __init__(self, key: str = "hive:c-channel-yolo11n-320", found: bool = True) -> None:
        self.key = key
        self._found = found

    def detect(self, frame: FeedFrame, zone: Any) -> DetectionBatch:
        if not self._found:
            return DetectionBatch(
                feed_id=frame.feed_id,
                frame_seq=frame.frame_seq,
                timestamp=frame.timestamp,
                detections=(),
                algorithm=self.key,
                latency_ms=0.1,
            )
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=(
                Detection(bbox_xyxy=(10, 20, 110, 140), score=0.91, class_id=None, mask=None, meta={}),
            ),
            algorithm=self.key,
            latency_ms=1.0,
        )


class _FakePipeline:
    def __init__(self, feed: _FakeFeed, zone: Any, detector: _FakeDetector) -> None:
        self.feed = feed
        self.zone = zone
        self.detector = detector


class _FakeRunner:
    def __init__(self, pipeline: _FakePipeline) -> None:
        self._pipeline = pipeline


class _FakeRtHandle:
    def __init__(self, runners: list[_FakeRunner]) -> None:
        self.perception_runners = runners


@pytest.fixture
def _fake_rt(monkeypatch: pytest.MonkeyPatch) -> _FakeRtHandle:
    raw = np.zeros((480, 640, 3), dtype=np.uint8)
    zone = RectZone(x=0, y=0, w=640, h=480)
    runners = [
        _FakeRunner(_FakePipeline(_FakeFeed(f"{role}_feed", raw), zone, _FakeDetector()))
        for role in ("c2", "c3", "c4")
    ]
    handle = _FakeRtHandle(runners)
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)
    return handle


# ---------------------------------------------------------------------------
# Baseline endpoints: 501
# ---------------------------------------------------------------------------


def test_classification_baseline_capture_returns_501() -> None:
    with pytest.raises(HTTPException) as exc_info:
        detection_router.capture_classification_baseline()
    assert exc_info.value.status_code == 501
    assert "baseline-free" in exc_info.value.detail.lower()


def test_carousel_baseline_capture_returns_501() -> None:
    with pytest.raises(HTTPException) as exc_info:
        detection_router.capture_carousel_detection_baseline()
    assert exc_info.value.status_code == 501


# ---------------------------------------------------------------------------
# Feeder detect: rt-runtime path
# ---------------------------------------------------------------------------


def test_feeder_detect_returns_rt_payload_shape(_fake_rt: _FakeRtHandle) -> None:
    payload = detection_router.debug_feeder_detection("c_channel_2")
    assert payload["ok"] is True
    assert payload["found"] is True
    assert payload["bbox"] == [10, 20, 110, 140]
    assert payload["candidate_bboxes"] == [[10, 20, 110, 140]]
    assert payload["candidate_previews"]
    assert payload["candidate_previews"][0] is not None
    assert base64.b64decode(payload["candidate_previews"][0])[:3] == b"\xff\xd8\xff"
    assert payload["bbox_count"] == 1
    assert payload["score"] == pytest.approx(0.91)
    assert payload["algorithm"].startswith("hive:")
    assert payload["frame_resolution"] == [640, 480]
    assert payload["zone_bbox"] == [0, 0, 640, 480]
    assert "zone_preview" not in payload
    # _finalize_aux_detection_debug_payload normalises + always sets ok
    assert payload["normalized_bbox"] is not None
    assert payload["normalized_zone_bbox"] == [0.0, 0.0, 1.0, 1.0]
    assert payload["camera"] == "c_channel_2"
    # saved_to_library may be False if the classification training manager
    # cannot write to the local filesystem during tests, but the key must
    # exist so the frontend can reason about it.
    assert "saved_to_library" in payload


def test_feeder_detect_no_runner_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_state, "rt_handle", None, raising=False)
    payload = detection_router.debug_feeder_detection("c_channel_2")
    assert payload["ok"] is True
    assert payload["found"] is False
    assert payload["bbox"] is None
    assert payload["candidate_bboxes"] == []
    assert payload["candidate_previews"] == []
    assert "not available" in payload["message"].lower()


def test_feeder_detect_rejects_unknown_role() -> None:
    with pytest.raises(HTTPException) as exc_info:
        detection_router.debug_feeder_detection("bogus_role")
    assert exc_info.value.status_code == 400


def test_sample_storage_image_serves_primary_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    training_root = tmp_path / "classification_training"
    session_dir = training_root / "session-a"
    image_path = session_dir / "dataset" / "images" / "sample-a.jpg"
    metadata_path = session_dir / "metadata" / "sample-a.json"
    image_path.parent.mkdir(parents=True)
    metadata_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    metadata_path.write_text(json.dumps({"input_image": str(image_path)}))
    monkeypatch.setattr(detection_router, "TRAINING_ROOT", training_root)

    response = detection_router.get_sample_storage_image("session-a", "sample-a")

    assert response.path == str(image_path)
    assert response.media_type == "image/jpeg"


# ---------------------------------------------------------------------------
# Carousel / classification-channel detect
# ---------------------------------------------------------------------------


def test_carousel_detect_returns_rt_payload(_fake_rt: _FakeRtHandle) -> None:
    payload = detection_router.debug_carousel_detection()
    assert payload["ok"] is True
    assert payload["found"] is True
    assert payload["bbox"] == [10, 20, 110, 140]
    assert payload["candidate_previews"]
    assert payload["candidate_previews"][0] is not None
    assert base64.b64decode(payload["candidate_previews"][0])[:3] == b"\xff\xd8\xff"
    assert payload["frame_resolution"] == [640, 480]
    assert "zone_preview" not in payload
