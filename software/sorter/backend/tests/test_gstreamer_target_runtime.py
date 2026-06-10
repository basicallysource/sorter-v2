from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np

from vision.gstreamer_target_capture import GStreamerTargetCaptureConfig, GStreamerTargetElements
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


class _FakeWritableBuffer:
    def __init__(self, size: int) -> None:
        self.data = bytearray(size)
        self.pts = 0
        self.dts = 0
        self.duration = 0

    def fill(self, offset: int, payload: bytes) -> None:
        self.data[offset:offset + len(payload)] = payload


class _FakeGstBufferFactory:
    @staticmethod
    def new_allocate(allocator, size: int, params):  # noqa: ANN001
        return _FakeWritableBuffer(size)


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


class _FakeAppSrc:
    def __init__(self) -> None:
        self.pushed = []

    def emit(self, signal: str, buffer):
        assert signal == "push-buffer"
        self.pushed.append(buffer)
        return "OK"


class _FakePipeline:
    def __init__(
        self,
        raw_sink: _FakeSink,
        h264_sink: _FakeSink | None,
        detection_sink: _FakeSink | None = None,
        h264_appsrc: _FakeAppSrc | None = None,
    ) -> None:
        self.raw_sink = raw_sink
        self.h264_sink = h264_sink
        self.detection_sink = detection_sink
        self.h264_appsrc = h264_appsrc
        self.states = []

    def get_by_name(self, name: str):
        if name == "sorter_raw_ring":
            return self.raw_sink
        if name == "sorter_h264_webrtc":
            return self.h264_sink
        if name == "sorter_yolo_reduced":
            return self.detection_sink
        if name == "sorter_h264_appsrc":
            return self.h264_appsrc
        return None

    def set_state(self, state: str):
        self.states.append(state)
        return "SUCCESS"


class _FakeGst:
    Buffer = _FakeGstBufferFactory

    class State:
        PLAYING = "PLAYING"
        NULL = "NULL"

    class StateChangeReturn:
        FAILURE = "FAILURE"

    class FlowReturn:
        OK = "OK"
        ERROR = "ERROR"

    def __init__(self, pipeline: _FakePipeline | list[_FakePipeline]) -> None:
        self.pipelines = list(pipeline) if isinstance(pipeline, list) else [pipeline]
        self.launch_pipelines = []
        self.launch_pipeline = None

    def parse_launch(self, launch_pipeline: str):
        pipeline = self.pipelines[len(self.launch_pipelines)]
        self.launch_pipelines.append(launch_pipeline)
        self.launch_pipeline = launch_pipeline
        return pipeline


class _FakeLibrgaScaler:
    def __init__(self) -> None:
        self.calls = []

    def crop_scale(
        self,
        payload: bytes,
        *,
        width: int,
        height: int,
        output_width: int,
        output_height: int,
        crop_rect,
    ) -> bytes:
        self.calls.append(
            {
                "payload_len": len(payload),
                "width": width,
                "height": height,
                "output_width": output_width,
                "output_height": output_height,
                "crop_rect": crop_rect,
            }
        )
        return bytes([128] * (output_width * output_height * 3 // 2))


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


def test_target_runtime_describe_backend_reports_scaled_h264_branch() -> None:
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(
            device_path="/dev/video3",
            width=3840,
            height=2160,
            fps=30,
            h264_width=1280,
            h264_height=720,
            elements=GStreamerTargetElements(rga_converter="rkrgaconvert"),
        )
    )

    description = runtime.describe_capture_backend()

    assert description["requested_mode"]["width"] == 3840
    assert description["hardware_scale_convert"] is True
    assert description["pipeline_contract"]["profiles"]["preview_webrtc"]["width"] == 1280
    assert description["pipeline_contract"]["profiles"]["classification_crops"]["width"] == 3840


def test_target_runtime_connects_and_exposes_reduced_detection_branch() -> None:
    raw_payload = bytes([128] * (4 * 4 * 3 // 2))
    detection_payload = bytes([128] * (2 * 2 * 3 // 2))
    h264_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    raw_sink = _FakeSink(_FakeSample(raw_payload, pts=2_000_000_000))
    h264_sink = _FakeSink(_FakeSample(h264_payload, pts=2_000_000_000))
    detection_sink = _FakeSink(_FakeSample(detection_payload, pts=2_000_000_000))
    pipeline = _FakePipeline(raw_sink, h264_sink, detection_sink)
    fake_gst = _FakeGst(pipeline)
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(
            device_path="/dev/video5",
            width=4,
            height=4,
            detection_width=2,
            detection_height=2,
            elements=GStreamerTargetElements(rga_converter="rkrgaconvert"),
        ),
        module_loader=lambda: GStreamerRuntimeModules(Gst=fake_gst, GLib=object()),
    )

    runtime.start()

    assert "new-sample" in detection_sink.callbacks
    assert detection_sink.callbacks["new-sample"](detection_sink) == "OK"
    detection_frame = runtime.latest_detection_frame()
    assert detection_frame is not None
    assert detection_frame.raw.shape == (2, 2, 3)
    assert getattr(detection_frame, "sensor_rect") == (0.0, 0.0, 4.0, 4.0)
    assert getattr(detection_frame, "sensor_size") == (4, 4)

    description = runtime.describe_capture_backend()
    assert description["detection_yolo_branch"] is True
    assert description["hardware_detection_scale_convert"] is True
    assert description["hardware_detection_crop"] is False
    assert description["hardware_scale_convert"] is True
    assert description["hardware_crop"] is False
    assert description["detection_crop_strategy"]["current_stage"] == (
        "scaled_full_frame_then_perception_crop"
    )
    assert description["detection_crop_strategy"]["software_videocrop_allowed"] is False
    assert description["detection_output_mode"] == {"width": 2, "height": 2, "fps": 30}

    runtime.stop()


def test_target_runtime_pushes_direct_librga_preview_into_appsrc_encoder() -> None:
    raw_payload = bytes([128] * (4 * 4 * 3 // 2))
    h264_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    raw_sink = _FakeSink(_FakeSample(raw_payload, pts=2_000_000_000))
    encoder_h264_sink = _FakeSink(_FakeSample(h264_payload, pts=2_000_000_000))
    appsrc = _FakeAppSrc()
    capture_pipeline = _FakePipeline(raw_sink, h264_sink=None)
    encoder_pipeline = _FakePipeline(_FakeSink(), encoder_h264_sink, h264_appsrc=appsrc)
    fake_gst = _FakeGst([capture_pipeline, encoder_pipeline])
    fake_scaler = _FakeLibrgaScaler()
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(
            device_path="/dev/video5",
            width=4,
            height=4,
            h264_width=2,
            h264_height=2,
            direct_librga_preview=True,
        ),
        module_loader=lambda: GStreamerRuntimeModules(Gst=fake_gst, GLib=object()),
        librga_scaler_factory=lambda: fake_scaler,
    )

    runtime.start()

    assert len(fake_gst.launch_pipelines) == 2
    assert "sorter_h264_queue" not in fake_gst.launch_pipelines[0]
    assert "appsrc name=sorter_h264_appsrc" in fake_gst.launch_pipelines[1]
    assert "new-sample" in raw_sink.callbacks
    assert "new-sample" in encoder_h264_sink.callbacks
    assert capture_pipeline.states == ["PLAYING"]
    assert encoder_pipeline.states == ["PLAYING"]

    assert raw_sink.callbacks["new-sample"](raw_sink) == "OK"

    assert fake_scaler.calls
    call = fake_scaler.calls[0]
    assert call["width"] == 4
    assert call["height"] == 4
    assert call["output_width"] == 2
    assert call["output_height"] == 2
    assert call["crop_rect"].as_tuple() == (0, 0, 4, 4)
    assert len(appsrc.pushed) == 1
    pushed = appsrc.pushed[0]
    assert bytes(pushed.data) == bytes([128] * (2 * 2 * 3 // 2))
    assert pushed.pts == 2_000_000_000
    assert pushed.duration == 33_333_333

    assert encoder_h264_sink.callbacks["new-sample"](encoder_h264_sink) == "OK"
    encoded = runtime._next_h264_frame_blocking()
    assert encoded.data == h264_payload
    assert encoded.pts == 180_000

    description = runtime.describe_capture_backend()
    assert description["h264_webrtc_branch"] is True
    assert description["h264_webrtc_pipeline_branch"] is False
    assert description["h264_webrtc_direct_librga"] is True
    assert description["hardware_preview_scale_convert"] is True
    assert description["hardware_preview_scale_convert_element"] == "librga_virtualaddr"
    assert description["scale_convert_element"] == "librga_virtualaddr"
    assert description["preview_input_memory"] == "virtualaddr"
    assert description["preview_zero_copy_dmabuf"] is False
    assert description["pipeline_contract"]["h264_encoder_pipeline"] is not None

    runtime.stop()
    assert capture_pipeline.states[-1] == "NULL"
    assert encoder_pipeline.states[-1] == "NULL"


def test_target_runtime_builds_direct_librga_detection_frame_from_raw_sample() -> None:
    raw_payload = bytes([128] * (4 * 4 * 3 // 2))
    h264_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    raw_sink = _FakeSink(_FakeSample(raw_payload, pts=2_000_000_000))
    h264_sink = _FakeSink(_FakeSample(h264_payload, pts=2_000_000_000))
    pipeline = _FakePipeline(raw_sink, h264_sink, detection_sink=None)
    fake_gst = _FakeGst(pipeline)
    fake_scaler = _FakeLibrgaScaler()
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(
            device_path="/dev/video5",
            width=4,
            height=4,
            detection_width=2,
            detection_height=2,
            direct_librga_detection=True,
        ),
        module_loader=lambda: GStreamerRuntimeModules(Gst=fake_gst, GLib=object()),
        librga_scaler_factory=lambda: fake_scaler,
    )

    runtime.start()

    assert fake_gst.launch_pipeline is not None
    assert "sorter_yolo_queue" not in fake_gst.launch_pipeline
    assert "new-sample" in raw_sink.callbacks
    assert runtime._detection_sink is None
    assert raw_sink.callbacks["new-sample"](raw_sink) == "OK"

    assert fake_scaler.calls
    call = fake_scaler.calls[0]
    assert call["width"] == 4
    assert call["height"] == 4
    assert call["output_width"] == 2
    assert call["output_height"] == 2
    assert call["crop_rect"].as_tuple() == (0, 0, 4, 4)
    detection_frame = runtime.latest_detection_frame()
    assert detection_frame is not None
    assert detection_frame.raw.shape == (2, 2, 3)
    assert getattr(detection_frame, "sensor_rect") == (0.0, 0.0, 4.0, 4.0)
    assert getattr(detection_frame, "sensor_size") == (4, 4)
    assert getattr(detection_frame, "scale_backend") == "librga_virtualaddr"

    description = runtime.describe_capture_backend()
    assert description["detection_yolo_branch"] is True
    assert description["detection_yolo_pipeline_branch"] is False
    assert description["detection_yolo_direct_librga"] is True
    assert description["hardware_detection_scale_convert"] is True
    assert description["hardware_preview_scale_convert"] is False
    assert description["hardware_scale_convert"] is True
    assert description["scale_convert_element"] == "librga_virtualaddr"
    assert description["software_scale_convert_fallback"] is False
    assert description["hardware_detection_crop"] is False
    assert description["hardware_detection_crop_capable"] is True
    assert description["detection_input_memory"] == "virtualaddr"
    assert description["detection_zero_copy_dmabuf"] is False

    runtime.stop()


def test_target_runtime_applies_dynamic_direct_librga_detection_crop() -> None:
    raw_payload = bytes([128] * (8 * 8 * 3 // 2))
    h264_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    raw_sink = _FakeSink(_FakeSample(raw_payload, pts=2_000_000_000))
    h264_sink = _FakeSink(_FakeSample(h264_payload, pts=2_000_000_000))
    pipeline = _FakePipeline(raw_sink, h264_sink, detection_sink=None)
    fake_gst = _FakeGst(pipeline)
    fake_scaler = _FakeLibrgaScaler()
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(
            device_path="/dev/video5",
            width=8,
            height=8,
            detection_width=2,
            detection_height=2,
            direct_librga_detection=True,
        ),
        module_loader=lambda: GStreamerRuntimeModules(Gst=fake_gst, GLib=object()),
        librga_scaler_factory=lambda: fake_scaler,
    )

    assert runtime.set_detection_crop_rect((2, 2, 6, 6)) is True
    runtime.start()

    assert raw_sink.callbacks["new-sample"](raw_sink) == "OK"

    call = fake_scaler.calls[0]
    assert call["crop_rect"].as_tuple() == (2, 2, 4, 4)
    detection_frame = runtime.latest_detection_frame()
    assert detection_frame is not None
    assert getattr(detection_frame, "sensor_rect") == (2.0, 2.0, 6.0, 6.0)
    assert getattr(detection_frame, "scale_backend") == "librga_virtualaddr"

    description = runtime.describe_capture_backend()
    assert description["hardware_detection_crop"] is True
    assert description["hardware_crop"] is True
    assert description["hardware_crop_element"] == "librga_virtualaddr"
    assert description["detection_crop_strategy"]["current_stage"] == "hardware_crop_before_yolo_scale"
    assert description["pipeline_contract"]["profiles"]["detection_yolo"]["sensor_rect"] == [2, 2, 6, 6]
    assert description["pipeline_contract"]["profiles"]["detection_yolo"]["sensor_crop_rect"] == {
        "x": 2,
        "y": 2,
        "width": 4,
        "height": 4,
    }

    runtime.stop()


def test_videoconvertscale_defaults_to_software_fallback_without_rga_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("SORTER_GSTREAMER_ENABLE_PATCHED_VIDEOCONVERTSCALE_RGA", raising=False)
    monkeypatch.delenv("GST_VIDEO_CONVERT_USE_RGA", raising=False)
    raw_payload = bytes([128] * (4 * 4 * 3 // 2))
    detection_payload = bytes([128] * (2 * 2 * 3 // 2))
    h264_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    raw_sink = _FakeSink(_FakeSample(raw_payload, pts=2_000_000_000))
    h264_sink = _FakeSink(_FakeSample(h264_payload, pts=2_000_000_000))
    detection_sink = _FakeSink(_FakeSample(detection_payload, pts=2_000_000_000))
    pipeline = _FakePipeline(raw_sink, h264_sink, detection_sink)
    fake_gst = _FakeGst(pipeline)
    runtime = GStreamerTargetCaptureRuntime(
        GStreamerTargetCaptureConfig(
            device_path="/dev/video5",
            width=4,
            height=4,
            detection_width=2,
            detection_height=2,
            elements=GStreamerTargetElements(rga_converter="videoconvertscale"),
        ),
        module_loader=lambda: GStreamerRuntimeModules(Gst=fake_gst, GLib=object()),
    )

    description = runtime.describe_capture_backend()

    assert description["detection_yolo_branch"] is True
    assert description["hardware_detection_scale_convert"] is False
    assert description["hardware_scale_convert"] is False
    assert description["hardware_scale_convert_element"] is None
    assert description["scale_convert_element"] == "videoconvertscale"
    assert description["software_scale_convert_fallback"] is True
    assert description["pipeline_contract"]["hardware_scale_convert"] is False
    assert description["pipeline_contract"]["hardware_scale_convert_element"] is None
    assert description["pipeline_contract"]["scale_convert_element"] == "videoconvertscale"
    assert description["pipeline_contract"]["software_scale_convert_fallback"] is True

    runtime.start()

    assert os.environ["GST_VIDEO_CONVERT_USE_RGA"] == "0"
    runtime.stop()
