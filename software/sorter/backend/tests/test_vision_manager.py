from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from vision.vision_manager import VisionManager


def test_camera_overlay_start_has_no_detection_dependency():
    feed = Mock()
    capture = SimpleNamespace(getTelemetrySnapshot=lambda: {"resolution": (1280, 720)})
    cameras = SimpleNamespace(
        feeds={"c_channel_2": feed},
        get_capture_thread_for_role=lambda role: capture,
    )
    manager = VisionManager(SimpleNamespace(should_write_camera_feeds=False), cameras)

    manager.start()
    manager.start()

    assert feed.clear_overlays.call_count == 2
    overlay = feed.add_overlay.call_args.args[0]
    assert overlay.category == "telemetry"
    assert overlay.annotate(np.zeros((720, 1280, 3), dtype=np.uint8)).any()


def test_polygon_reload_reconciles_active_perception():
    perception = SimpleNamespace(request_reconcile=Mock())
    gc = SimpleNamespace(should_write_camera_feeds=False, perception_service=perception)
    manager = VisionManager(gc, None)

    manager.reloadPolygons()

    perception.request_reconcile.assert_called_once_with()


def test_recording_keeps_camera_frames_and_closes_recorder(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr("vision.vision_manager.VideoRecorder", lambda: recorder)
    frame = SimpleNamespace(raw=object(), annotated=object())
    feed = SimpleNamespace(get_frame=lambda **kwargs: frame)
    cameras = SimpleNamespace(
        active_cameras=[SimpleNamespace(value="c_channel_2")],
        get_feed=lambda role: feed,
    )
    manager = VisionManager(SimpleNamespace(should_write_camera_feeds=True), cameras)

    manager.recordFrames()
    manager.stop()

    recorder.writeFrame.assert_called_once_with("c_channel_2", frame.raw, frame.annotated)
    recorder.close.assert_called_once_with()
