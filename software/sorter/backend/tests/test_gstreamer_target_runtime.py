from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from vision.gstreamer_target_capture import GStreamerTargetCaptureConfig
from vision.gstreamer_target_capture import TARGET_PIPELINE_NAME
from vision.gstreamer_target_runtime import (
    GStreamerRuntimeModules,
    GStreamerTargetCaptureRuntime,
    coerce_bgr_sample_bytes,
    coerce_nv12_sample_bytes,
    gst_pts_to_webrtc_pts,
)


class _FakeBuffer:
    def __init__(self, data: bytes, pts: int = 0) -> None:
        self.data = data
        self.pts = pts
        self.unmapped = False

    def map(self, flags):  # noqa: ANN001
        return True, SimpleNamespace(data=self.data)

    def unmap(self, map_info):  # noqa: ANN001
        self.unmapped = True


class _FakeSample:
    def __init__(self, data: bytes, pts: int = 0) -> None:
        self.buffer = _FakeBuffer(data, pts=pts)

    def get_buffer(self):
        return self.buffer


class _FakeSink:
    def __init__(self, sample: _FakeSample | None = None) -> None:
        self.sample = sample
        self.callbacks = {}

    def connect(self, signal: str, callback):
        self.callbacks[signal] = callback

    def emit(self, signal: str):
        assert signal == "pull-sample"
        return self.sample


class _FakePipeline:
    def __init__(self, raw_sink: _FakeSink, h264_sink: _FakeSink) -> None:
        self.raw_sink = raw_sink
        self.h264_sink = h264_sink
        self.states = []

    def get_by_name(self, name: str):
        if name == "sorter_raw_ring":
            return self.raw_sink
        if name == "sorter_h264_webrtc":
            return self.h264_sink
        return None

    def set_state(self, state: str):
        self.states.append(state)
        return "SUCCESS"


class _FakeGst:
    class State:
        PLAYING = "PLAYING"
        NULL = "NULL"

    class StateChangeReturn:
        FAILURE = "FAILURE"

    class FlowReturn:
        OK = "OK"
        ERROR = "ERROR"

    def __init__(self, pipeline: _FakePipeline) -> None:
        self.pipeline = pipeline
        self.launch_pipeline = None

    def parse_launch(self, launch_pipeline: str):
        self.launch_pipeline = launch_pipeline
        return self.pipeline


def test_gst_pts_to_webrtc_pts_uses_90khz_clock_and_fallback() -> None:
    assert gst_pts_to_webrtc_pts(1_000_000_000, fallback_index=9, fps=30) == 90_000
    assert gst_pts_to_webrtc_pts(None, fallback_index=3, fps=30) == 9_000


def test_coerce_bgr_sample_bytes_returns_independent_frame() -> None:
    payload = bytes(range(12))
    frame = coerce_bgr_sample_bytes(payload, width=2, height=2)

    assert frame.shape == (2, 2, 3)
    assert frame.dtype == np.uint8
    assert frame[0, 0].tolist() == [0, 1, 2]
    assert frame.flags.owndata is True


def test_coerce_nv12_sample_bytes_returns_bgr_frame() -> None:
    payload = bytes([128] * 6)
    frame = coerce_nv12_sample_bytes(payload, width=2, height=2)

    assert frame.shape == (2, 2, 3)
    assert frame.dtype == np.uint8


def test_coerce_nv12_sample_bytes_accepts_padded_height() -> None:
    payload = bytes([128] * 12)
    frame = coerce_nv12_sample_bytes(payload, width=2, height=2)

    assert frame.shape == (2, 2, 3)
    assert frame.dtype == np.uint8


def test_target_runtime_start_connects_one_pipeline_and_both_branches() -> None:
    raw_payload = bytes([128] * (2 * 2 * 3 // 2))
    h264_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    raw_sink = _FakeSink(_FakeSample(raw_payload, pts=2_000_000_000))
    h264_sink = _FakeSink(_FakeSample(h264_payload, pts=2_000_000_000))
    pipeline = _FakePipeline(raw_sink, h264_sink)
    fake_gst = _FakeGst(pipeline)
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(device_path="/dev/video5", width=2, height=2),
        module_loader=lambda: GStreamerRuntimeModules(Gst=fake_gst, GLib=object()),
    )

    runtime.start()

    assert runtime.active is True
    assert fake_gst.launch_pipeline is not None
    assert fake_gst.launch_pipeline.split().count("v4l2src") == 1
    assert "new-sample" in raw_sink.callbacks
    assert "new-sample" in h264_sink.callbacks
    assert pipeline.states == ["PLAYING"]

    assert raw_sink.callbacks["new-sample"](raw_sink) == "OK"
    assert h264_sink.callbacks["new-sample"](h264_sink) == "OK"

    assert runtime.raw_ring_depth == 1
    assert runtime.latest_raw_frame().raw.shape == (2, 2, 3)
    assert runtime.latest_raw_frame().timestamp == 2.0
    encoded = runtime._next_h264_frame_blocking()
    assert encoded.data == h264_payload
    assert encoded.pts == 180_000
    assert encoded.source_timestamp == 2.0

    runtime.stop()
    assert runtime.active is False
    assert pipeline.states[-1] == "NULL"


def test_target_runtime_describe_backend_marks_integrated_target_shape() -> None:
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(device_path="/dev/video3", width=1280, height=720, fps=30)
    )

    description = runtime.describe_capture_backend()

    assert description["implementation"] == TARGET_PIPELINE_NAME
    assert description["single_capture_owner"] is True
    assert description["raw_ring_branch"] is True
    assert description["h264_webrtc_branch"] is True
    assert description["hardware_scale_convert"] is False
    assert description["zero_copy_dmabuf"] is True
    assert description["target_compliant"] is True
    assert description["software_h264_fallback_allowed"] is False
    assert description["pipeline_contract"]["launch_pipeline"].split().count("v4l2src") == 1
