from __future__ import annotations

from types import SimpleNamespace
import time

import numpy as np
import pytest

from server import shared_state
from server.routers import cameras
from vision.types import CameraFrame


def _frame(
    *,
    ts: float | None = None,
    raw_value: int = 1,
    uncorrected_value: int | None = 2,
) -> CameraFrame:
    raw = np.full((4, 5, 3), raw_value, dtype=np.uint8)
    uncorrected = (
        np.full((4, 5, 3), uncorrected_value, dtype=np.uint8)
        if uncorrected_value is not None
        else None
    )
    return CameraFrame(
        raw=raw,
        annotated=None,
        results=[],
        timestamp=time.time() if ts is None else ts,
        uncorrected_raw=uncorrected,
    )


class _Capture:
    def __init__(self, source: int, frame: CameraFrame) -> None:
        self._source = source
        self.latest_frame = frame

    def getCameraSource(self) -> int:
        return self._source


class _Feed:
    def __init__(self, capture: _Capture) -> None:
        self.device = SimpleNamespace(capture_thread=capture)
        self.calls: list[tuple[bool, bool]] = []

    def get_frame(self, annotated: bool = True, color_correct: bool = True) -> CameraFrame:
        self.calls.append((annotated, color_correct))
        return self.device.capture_thread.latest_frame


class _CameraService:
    def __init__(self, role: str, feed: _Feed, capture: _Capture) -> None:
        self.role = role
        self.feed = feed
        self.capture = capture

    def get_feed(self, role: str):
        return self.feed if role == self.role else None

    def get_capture_thread_for_role(self, role: str):
        return self.capture if role == self.role else None


@pytest.fixture(autouse=True)
def _reset_camera_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_state, "camera_service", None)
    monkeypatch.setattr(shared_state, "vision_manager", None)


def test_calibration_capture_prefers_uncorrected_running_service_frame() -> None:
    capture = _Capture(5, _frame(raw_value=7, uncorrected_value=11))
    feed = _Feed(capture)
    shared_state.camera_service = _CameraService("c_channel_2", feed, capture)

    result = cameras._grab_running_capture_frame_entry(
        "c_channel_2",
        5,
        after_timestamp=time.time() - 1.0,
        prefer_uncorrected=True,
    )

    assert result is not None
    frame, timestamp = result
    assert timestamp > 0.0
    assert int(frame[0, 0, 0]) == 11
    assert feed.calls == [(False, False)]


def test_live_frame_helper_keeps_raw_frame_semantics() -> None:
    capture = _Capture(5, _frame(raw_value=7, uncorrected_value=11))
    feed = _Feed(capture)
    shared_state.camera_service = _CameraService("c_channel_2", feed, capture)

    frame = cameras._grab_live_frame("c_channel_2", after_timestamp=time.time() - 1.0)

    assert frame is not None
    assert int(frame[0, 0, 0]) == 7


def test_capture_frame_for_calibration_uses_running_capture_without_opening_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _Capture(5, _frame(raw_value=7, uncorrected_value=11))
    feed = _Feed(capture)
    shared_state.camera_service = _CameraService("c_channel_2", feed, capture)

    import vision.camera as camera_module

    def fail_open(*_args, **_kwargs):
        raise AssertionError("calibration opened a second capture")

    monkeypatch.setattr(camera_module, "_open_capture_source", fail_open)

    frame = cameras._capture_frame_for_calibration(
        "c_channel_2",
        5,
        after_timestamp=time.time() - 1.0,
    )

    assert frame is not None
    assert int(frame[0, 0, 0]) == 11


def test_capture_frame_for_calibration_refuses_second_capture_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SORTER_ALLOW_CALIBRATION_SECOND_CAPTURE", raising=False)
    monkeypatch.setattr(cameras.platform, "system", lambda: "Linux")

    import vision.camera as camera_module

    def fail_open(*_args, **_kwargs):
        raise AssertionError("calibration opened a second capture")

    monkeypatch.setattr(camera_module, "_open_capture_source", fail_open)

    frame = cameras._capture_frame_for_calibration(
        "c_channel_2",
        5,
        after_timestamp=time.time() - 1.0,
    )

    assert frame is None


def test_running_capture_frame_rejects_source_mismatch() -> None:
    capture = _Capture(7, _frame(raw_value=7, uncorrected_value=11))
    feed = _Feed(capture)
    shared_state.camera_service = _CameraService("c_channel_2", feed, capture)

    result = cameras._grab_running_capture_frame_entry(
        "c_channel_2",
        5,
        after_timestamp=time.time() - 1.0,
        timeout=0.0,
        allow_stale=True,
        prefer_uncorrected=True,
    )

    assert result is None


def test_dashboard_crop_metadata_serializes_masked_viewport() -> None:
    polygon = np.array(
        [[10.2, 20.6], [70.0, 25.0], [65.4, 90.9], [12.0, 80.0]],
        dtype=np.float32,
    )

    payload = cameras._dashboard_crop_metadata_from_spec(
        {"kind": "bbox_masked", "polygons": [polygon], "rotation_deg": 17.25},
        200,
        120,
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["kind"] == "bbox_masked"
    assert payload["input_frame"] == {"width": 200, "height": 120}
    assert payload["viewport"]["bbox"] == [10, 20, 70, 91]
    assert payload["viewport"]["width"] == 60
    assert payload["viewport"]["height"] == 71
    assert payload["rotation_deg"] == 17.25
    assert payload["polygons"][0][0] == [10.2, 20.6]
