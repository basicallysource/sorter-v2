from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import numpy as np

import vision.media_plane as media_plane
from vision.media_plane import (
    _describe_v4l2_m2m_device,
    _select_production_hardware_path,
    describe_feed_metadata,
    describe_media_plane,
    evaluate_transport_gates,
    probe_media_capabilities,
)
from vision.h264_webrtc_bridge import EncodedH264Frame
from vision.webrtc_transport import (
    CameraWebRtcSessionRegistry,
    WebRtcTransportError,
    _send_camera_metadata_loop,
)
from vision.overlays.region import ChannelRegionOverlay
from vision.types import CameraFrame


def _frame(ts: float = 100.0) -> CameraFrame:
    return CameraFrame(
        raw=np.zeros((8, 12, 3), dtype=np.uint8),
        annotated=None,
        results=[],
        timestamp=ts,
    )


_DEFAULT_FRAME = object()


def _device(
    source: int,
    *,
    ring_depth: int = 7,
    ts: float = 100.0,
    latest_frame: CameraFrame | None | object = _DEFAULT_FRAME,
    capture_backend: dict | None = None,
):
    latest = _frame(ts) if latest_frame is _DEFAULT_FRAME else latest_frame
    def _capture_backend() -> dict:
        if capture_backend is not None:
            return dict(capture_backend)
        return {
            "implementation": "opencv_v4l2_raw_ring",
            "source": source,
            "single_capture_owner": True,
            "raw_ring_branch": True,
            "h264_webrtc_branch": False,
            "hardware_scale_convert": False,
            "zero_copy_dmabuf": False,
            "target_compliant": False,
        }

    return SimpleNamespace(
        config=SimpleNamespace(url=None, device_index=source),
        latest_frame=latest,
        ring_buffer_depth=ring_depth,
        describe_capture_backend=_capture_backend,
    )


def _feed(device, health: str = "online"):
    return SimpleNamespace(device=device, health=SimpleNamespace(value=health))


def test_video_handle_summary_aggregates_by_device_and_process() -> None:
    summary = media_plane._summarize_video_handle_entries(
        [
            {"path": "/dev/video5", "pid": 100, "fd": "8", "command": "backend"},
            {"path": "/dev/video5", "pid": 100, "fd": "9", "command": "backend"},
            {"path": "/dev/video5", "pid": 200, "fd": "11", "command": "ffmpeg"},
            {"path": "/dev/video3", "pid": 100, "fd": "10", "command": "backend"},
        ],
        permission_denied=2,
        scan_errors=1,
    )

    assert summary["available"] is True
    assert summary["total_handles"] == 4
    assert summary["total_processes"] == 2
    assert summary["permission_denied"] == 2
    assert summary["scan_errors"] == 1
    assert summary["paths"]["/dev/video5"]["handle_count"] == 3
    assert summary["paths"]["/dev/video5"]["process_count"] == 2
    assert summary["paths"]["/dev/video5"]["processes"][0]["pid"] == 100
    assert summary["paths"]["/dev/video5"]["processes"][0]["fd_count"] == 2
    assert summary["paths"]["/dev/video3"]["handle_count"] == 1


def test_media_plane_attaches_os_handle_audit_to_video_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        media_plane,
        "probe_media_capabilities",
        lambda: {
            "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
            "devices": {"video": ["/dev/video5"]},
            "selected_encoder_path": None,
        },
    )
    monkeypatch.setattr(
        media_plane,
        "_scan_video_open_handles",
        lambda: media_plane._summarize_video_handle_entries(
            [
                {"path": "/dev/video5", "pid": 100, "fd": "8", "command": "backend"},
                {"path": "/dev/video5", "pid": 100, "fd": "9", "command": "backend"},
            ]
        ),
    )
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})

    payload = describe_media_plane(service)
    source = payload["physical_sources"][0]

    assert payload["capabilities"]["devices"]["video_open_handles"]["total_handles"] == 2
    assert source["source"] == "video:5"
    assert source["os_handle_audit"]["expected_device_path"] == "/dev/video5"
    assert source["os_handle_audit"]["handle_count"] == 2
    assert source["os_handle_audit"]["process_count"] == 1
    assert source["os_handle_audit"]["processes"][0]["command"] == "backend"


class _StaticHardwareH264Source:
    def __init__(self) -> None:
        self.calls = 0
        self.stop_calls = 0

    async def recv_encoded_h264(self):
        self.calls += 1
        return EncodedH264Frame(data=b"\x00\x00\x00\x01\x65\x88\x84", pts=self.calls * 3000)

    async def stop(self) -> None:
        self.stop_calls += 1


class _FakeMetadataChannel:
    def __init__(self) -> None:
        self.readyState = "open"
        self.sent: list[str] = []

    def send(self, payload: str) -> None:
        self.sent.append(payload)
        if len(self.sent) >= 2:
            self.readyState = "closed"


class _MetadataFeed:
    def __init__(self, device) -> None:
        self.role = "c_channel_2"
        self.device = device

    def describe_overlays(self, exclude_categories=None):
        overlays = [
            {
                "type": "track_bbox",
                "category": "detections",
                "bbox": [np.int64(1), np.int64(2), np.int64(3), np.int64(4)],
            },
            {
                "type": "channel_regions",
                "category": "regions",
                "poly_key": "second_channel",
            },
        ]
        if exclude_categories:
            overlays = [
                item for item in overlays
                if item.get("category") not in exclude_categories
            ]
        return overlays


class _RegionProvider:
    def describeOverlayMetadata(self, poly_key=None):
        return [
            {
                "type": "channel_regions",
                "category": "regions",
                "poly_key": poly_key,
                "polygon": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
            }
        ]


def test_media_plane_reports_inactive_without_camera_service() -> None:
    payload = describe_media_plane(None)

    assert payload["ok"] is True
    assert payload["active"] is False
    assert payload["target"]["transport"] == "webrtc"
    assert payload["target"]["video_codec"] == "h264"
    assert payload["encoder_sessions"] == []
    assert payload["invariants"]["single_capture_per_physical_source"] is True


def test_media_plane_aliases_multiple_roles_to_one_capture_instance() -> None:
    device = _device(3, ring_depth=42)
    service = SimpleNamespace(
        feeds={
            "c_channel_3": _feed(device),
            "carousel": _feed(device),
        }
    )

    payload = describe_media_plane(service)

    assert payload["active"] is True
    assert payload["invariants"]["single_capture_per_physical_source"] is True
    assert len(payload["physical_sources"]) == 1
    source = payload["physical_sources"][0]
    assert source["source"] == "video:3"
    assert source["roles"] == ["c_channel_3", "carousel"]
    assert source["capture_instances"] == 1
    assert source["encoder_instances_target"] == 1
    assert source["ring_buffer_depth"] == 42
    assert source["latest_frame"]["width"] == 12
    assert source["latest_frame"]["height"] == 8
    contract = source["target_capture_pipeline_contract"]
    assert contract["name"] == "gstreamer_v4l2_tee_mpp_h264"
    assert contract["device_path"] == "/dev/video3"
    assert contract["capture"]["width"] == 12
    assert contract["capture"]["height"] == 8
    assert contract["topology"]["single_capture_pipeline"] is True
    assert contract["topology"]["raw_ring_branch"] is True
    assert contract["topology"]["h264_webrtc_branch"] is True
    assert contract["launch_pipeline"].split().count("v4l2src") == 1
    assert "sorter_capture_tee. ! queue name=sorter_raw_queue" in contract["launch_pipeline"]
    assert "sorter_capture_tee. ! queue name=sorter_h264_queue" in contract["launch_pipeline"]
    assert source["capture_backend"]["implementation"] in {
        "opencv_v4l2_raw_ring",
        "opencv_avfoundation_raw_ring",
        "opencv_raw_ring",
        "opencv_url_raw_ring",
    }
    assert source["capture_backend"]["single_capture_owner"] is True
    assert source["capture_backend"]["raw_ring_branch"] is True
    assert source["capture_backend"]["h264_webrtc_branch"] is False
    assert source["capture_backend"]["target_compliant"] is False
    assert payload["invariants"]["target_capture_backend_integrated"] is False
    assert len(payload["encoder_sessions"]) == 1
    session = payload["encoder_sessions"][0]
    assert session["session_key"] == "video:3"
    assert session["physical_source"] == "video:3"
    assert session["roles"] == ["c_channel_3", "carousel"]
    assert session["codec"] == "h264"
    assert session["transport_target"] == "webrtc_media_track"
    assert session["encoder_instances_target"] == 1
    assert session["status"] in {"planned_ready", "blocked_missing_hardware_h264_path"}
    assert session["shares_capture_thread"] is True


def test_media_plane_marks_active_high_res_capture_as_needing_hardware_scale(monkeypatch) -> None:
    monkeypatch.setattr(
        media_plane,
        "probe_media_capabilities",
        lambda: {
            "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
            "python_webrtc": {"ready": True},
            "ffmpeg": {
                "rkmpp_h264_encoder": True,
                "rkmpp_h264_runtime_ready": True,
                "rkrga_filters": True,
                "rkrga_runtime_ready": True,
                "rkrga_crop_filter": True,
                "rkrga_crop_runtime_ready": True,
            },
            "selected_encoder_path": {
                "name": "gstreamer_rockchip_mpp",
                "available": True,
                "hardware": True,
                "target_compliant": True,
                "production_ready": True,
            },
            "webrtc_hardware_bridge": {
                "implemented": True,
                "source_factory_registered": True,
            },
            "devices": {
                "video": ["/dev/video5"],
                "known_rockchip_accelerators": {
                    "/dev/mpp_service": True,
                    "/dev/rga": True,
                    "/dev/dma_heap": True,
                    "/dev/dri/renderD128": True,
                },
                "v4l2_m2m": {"h264_encoder_ready": False},
            },
            "source_pipeline": {
                "target_capture_backend_required": True,
                "hardware_crop_in_source": False,
                "rkrga_crop_filter_advertised": True,
                "rkrga_crop_runtime_ready": True,
                "rkrga_crop_path": "ffmpeg_vpp_rkrga",
                "candidates": [
                    {
                        "name": "gstreamer_v4l2_tee_mpp_h264",
                        "available": True,
                    }
                ],
            },
            "ready_for_hardware_webrtc": True,
        },
    )
    monkeypatch.setattr(
        media_plane,
        "_scan_video_open_handles",
        lambda: media_plane._summarize_video_handle_entries([]),
    )
    backend = {
        "implementation": "gstreamer_v4l2_tee_mpp_h264",
        "source": "/dev/video5",
        "requested_mode": {"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"},
        "single_capture_owner": True,
        "raw_ring_branch": True,
        "h264_webrtc_branch": True,
        "hardware_scale_convert": False,
        "zero_copy_dmabuf": True,
        "target_compliant": True,
    }
    service = SimpleNamespace(feeds={"classification_channel": _feed(_device(5, capture_backend=backend))})

    payload = describe_media_plane(service)
    source_pipeline = payload["capabilities"]["source_pipeline"]
    evaluation = evaluate_transport_gates(payload)

    assert payload["physical_sources"][0]["capture_profile"]["exceeds_preview_budget"] is True
    assert source_pipeline["active_high_res_sources"] == ["video:5"]
    assert source_pipeline["active_high_res_capture_requires_scale"] is True
    assert source_pipeline["active_high_res_scale_ready"] is False
    assert source_pipeline["hardware_crop_in_source"] is False
    assert source_pipeline["rkrga_crop_runtime_ready"] is True
    assert source_pipeline["rkrga_crop_path"] == "ffmpeg_vpp_rkrga"
    strategy = source_pipeline["detection_crop_strategy"]
    assert strategy["target_stage"] == "detection_yolo_branch_before_scale"
    assert strategy["current_stage"] == "scaled_full_frame_then_perception_crop"
    assert strategy["active_media_pipeline_crop"] is False
    assert strategy["hardware_crop_runtime_available"] is True
    assert strategy["hardware_crop_runtime_path"] == "ffmpeg_vpp_rkrga"
    assert strategy["software_videocrop_allowed"] is False
    assert evaluation["gates"]["active_high_res_capture_requires_scale"] is True
    assert evaluation["gates"]["active_high_res_scale_ready"] is False
    assert evaluation["gates"]["hardware_crop_source_pipeline"] is False
    assert evaluation["gates"]["ffmpeg_rkrga_crop_runtime"] is True
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert any(
        "Active high-res camera capture exceeds the preview budget" in item
        for item in evaluation["blockers"]
    )


def test_media_plane_does_not_treat_direct_librga_detection_as_preview_scale(monkeypatch) -> None:
    monkeypatch.setattr(
        media_plane,
        "probe_media_capabilities",
        lambda: {
            "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
            "python_webrtc": {"ready": True},
            "ffmpeg": {"rkrga_crop_runtime_ready": True},
            "selected_encoder_path": {
                "name": "gstreamer_rockchip_mpp",
                "available": True,
                "hardware": True,
                "target_compliant": True,
                "production_ready": True,
            },
            "webrtc_hardware_bridge": {
                "implemented": True,
                "source_factory_registered": True,
            },
            "devices": {
                "video": ["/dev/video5"],
                "known_rockchip_accelerators": {
                    "/dev/mpp_service": True,
                    "/dev/rga": True,
                    "/dev/dma_heap": True,
                },
            },
            "source_pipeline": {
                "target_capture_backend_required": True,
                "candidates": [
                    {
                        "name": "gstreamer_v4l2_tee_mpp_h264",
                        "available": True,
                    }
                ],
            },
            "ready_for_hardware_webrtc": True,
        },
    )
    monkeypatch.setattr(
        media_plane,
        "_scan_video_open_handles",
        lambda: media_plane._summarize_video_handle_entries([]),
    )
    backend = {
        "implementation": "gstreamer_v4l2_tee_mpp_h264",
        "source": "/dev/video5",
        "requested_mode": {"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"},
        "single_capture_owner": True,
        "raw_ring_branch": True,
        "h264_webrtc_branch": True,
        "hardware_scale_convert": True,
        "hardware_preview_scale_convert": False,
        "hardware_detection_scale_convert": True,
        "hardware_detection_crop_capable": True,
        "zero_copy_dmabuf": True,
        "target_compliant": True,
    }
    service = SimpleNamespace(feeds={"classification_channel": _feed(_device(5, capture_backend=backend))})

    payload = describe_media_plane(service)
    source_pipeline = payload["capabilities"]["source_pipeline"]
    evaluation = evaluate_transport_gates(payload)

    assert source_pipeline["hardware_scale_convert_in_source"] is True
    assert source_pipeline["hardware_preview_scale_convert_in_source"] is False
    assert source_pipeline["hardware_detection_scale_convert_in_source"] is True
    assert source_pipeline["active_high_res_capture_requires_scale"] is True
    assert source_pipeline["active_high_res_scale_ready"] is False
    assert evaluation["gates"]["active_high_res_scale_ready"] is False


def test_transport_gate_keeps_720p_capture_valid_without_hardware_scale() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)
    payload["capabilities"]["source_pipeline"]["hardware_scale_convert_in_source"] = False
    payload["capabilities"]["source_pipeline"]["active_high_res_capture_requires_scale"] = False
    payload["capabilities"]["source_pipeline"]["active_high_res_scale_ready"] = True

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["hardware_scale_convert_source_pipeline"] is False
    assert evaluation["gates"]["active_high_res_capture_requires_scale"] is False
    assert evaluation["gates"]["active_high_res_scale_ready"] is True
    assert evaluation["gates"]["target_architecture_compliant"] is True


def test_unassigned_roles_do_not_fail_capture_and_backend_invariants(monkeypatch) -> None:
    """Regression: the invariant comprehensions used the leaked `source` loop
    variable instead of item["source"], so the "unassigned" exemption applied
    to the wrong entry. Two unassigned roles then failed
    single_capture_per_physical_source and every WebRTC offer was 409'd."""
    monkeypatch.setattr(
        media_plane,
        "probe_media_capabilities",
        lambda: {
            "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
            "devices": {"video": ["/dev/video4"]},
            "selected_encoder_path": None,
        },
    )
    service = SimpleNamespace(
        feeds={
            # Two roles without a configured camera → one "unassigned" pseudo
            # source with two capture instances. Sorts before "video:4", which
            # is exactly the layout that triggered the leaked-variable bug.
            "classification_top": _feed(_device(None, latest_frame=None)),
            "feeder": _feed(_device(None, latest_frame=None)),
            "c_channel_2": _feed(_device(4)),
        }
    )

    payload = describe_media_plane(service)

    by_source = {item["source"]: item for item in payload["physical_sources"]}
    assert by_source["unassigned"]["capture_instances"] == 2
    assert payload["invariants"]["single_capture_per_physical_source"] is True
    assert payload["invariants"]["assigned_physical_sources_exist"] is True


def test_media_plane_flags_assigned_video_source_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        media_plane,
        "probe_media_capabilities",
        lambda: {
            "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
            "devices": {"video": ["/dev/video3", "/dev/video5"]},
            "selected_encoder_path": None,
        },
    )
    service = SimpleNamespace(
        feeds={
            "carousel": _feed(_device(7, ring_depth=0, latest_frame=None)),
        }
    )

    payload = describe_media_plane(service)
    source = payload["physical_sources"][0]

    assert source["source"] == "video:7"
    assert source["source_exists"] is False
    assert source["source_presence"] == "missing"
    assert source["expected_device_path"] == "/dev/video7"
    assert source["target_capture_pipeline_contract"]["device_path"] == "/dev/video7"
    assert payload["invariants"]["assigned_physical_sources_exist"] is False


def test_media_plane_flags_duplicate_capture_instances_for_same_source() -> None:
    service = SimpleNamespace(
        feeds={
            "c_channel_2": _feed(_device(5)),
            "feeder": _feed(_device(5)),
        }
    )

    payload = describe_media_plane(service)

    assert payload["invariants"]["single_capture_per_physical_source"] is False
    assert len(payload["physical_sources"]) == 1
    assert payload["physical_sources"][0]["source"] == "video:5"
    assert payload["physical_sources"][0]["capture_instances"] == 2
    assert payload["encoder_sessions"][0]["shares_capture_thread"] is False


def test_media_plane_reports_legacy_mjpeg_per_client_encode_clients() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})

    payload = describe_media_plane(
        service,
        legacy_mjpeg_streams={
            "live-c2": {
                "role": "c_channel_2",
                "physical_source": "video:5",
                "stack": "camera_service_live",
                "layer": "raw",
                "active_clients": 2,
                "per_client_encode": True,
            },
            "closed": {
                "role": "c_channel_2",
                "physical_source": "video:5",
                "stack": "camera_service_live",
                "active_clients": 0,
            },
        },
    )

    legacy = payload["legacy_transports"]["mjpeg"]
    assert legacy["active_clients"] == 2
    assert legacy["per_client_encode"] is True
    assert legacy["per_client_encode_active"] is True
    assert legacy["target_replacement"] == "webrtc_media_track"
    assert legacy["migration_status"] == "legacy_not_target"
    assert len(legacy["streams"]) == 1
    assert legacy["streams"][0]["role"] == "c_channel_2"
    assert legacy["streams"][0]["physical_source"] == "video:5"


def test_media_capability_probe_classifies_encoder_paths() -> None:
    payload = probe_media_capabilities()

    assert payload["target"]["encoder"] == "rockchip_mpp"
    assert payload["source_pipeline"]["implementation"] in {
        None,
        "staging_bgr24_cpu_pipe_to_h264_rkmpp",
        "gstreamer_v4l2_mpp_tee_h264",
    }
    assert payload["source_pipeline"]["target_compliant"] is False
    candidates = {
        item["name"]: item
        for item in payload["source_pipeline"].get("candidates", [])
    }
    assert {
        "shared_feed_bgr24_to_ffmpeg_rkmpp",
        "forbidden_ffmpeg_v4l2_direct_to_rkmpp",
        "ffmpeg_v4l2_single_capture_split_rkmpp_rkrga",
        "in_process_librga_virtualaddr_scale_crop",
        "gstreamer_v4l2_tee_mpp_h264",
    } <= set(candidates)
    assert candidates["shared_feed_bgr24_to_ffmpeg_rkmpp"]["opens_capture_device"] is False
    assert candidates["shared_feed_bgr24_to_ffmpeg_rkmpp"]["raw_ring_branch"] is True
    assert candidates["shared_feed_bgr24_to_ffmpeg_rkmpp"]["target_compliant"] is False
    assert candidates["forbidden_ffmpeg_v4l2_direct_to_rkmpp"]["opens_capture_device"] is True
    assert candidates["forbidden_ffmpeg_v4l2_direct_to_rkmpp"]["violates_single_capture"] is True
    assert candidates["forbidden_ffmpeg_v4l2_direct_to_rkmpp"]["target_compliant"] is False
    ffmpeg_single_capture = candidates["ffmpeg_v4l2_single_capture_split_rkmpp_rkrga"]
    assert ffmpeg_single_capture["role"] == "alternate_target_candidate"
    assert ffmpeg_single_capture["single_capture_pipeline"] is True
    assert ffmpeg_single_capture["violates_single_capture"] is False
    assert ffmpeg_single_capture["raw_ring_branch"] is True
    assert ffmpeg_single_capture["h264_webrtc_branch"] is True
    assert ffmpeg_single_capture["detection_yolo_branch"] is True
    assert ffmpeg_single_capture["implementation_registered"] is False
    assert ffmpeg_single_capture["target_compliant"] is False
    librga_candidate = candidates["in_process_librga_virtualaddr_scale_crop"]
    assert librga_candidate["role"] == "next_runtime_step"
    assert librga_candidate["opens_capture_device"] is False
    assert librga_candidate["input_from_single_capture_feed"] is True
    assert librga_candidate["detection_yolo_branch"] is True
    assert librga_candidate["zero_copy_dmabuf"] is False
    assert librga_candidate["target_compliant"] is False
    target_candidate = candidates["gstreamer_v4l2_tee_mpp_h264"]
    assert target_candidate["role"] == "target_candidate"
    assert target_candidate["single_capture_pipeline"] is True
    assert target_candidate["capture_backend_integration_required"] is True
    assert target_candidate["web_rtc_factory_only"] is False
    assert target_candidate["raw_ring_branch"] is True
    assert target_candidate["h264_webrtc_branch"] is True
    assert target_candidate["target_compliant"] is False
    assert target_candidate["software_h264_fallback_allowed"] is False
    assert target_candidate["pipeline_contract"]["name"] == "gstreamer_v4l2_tee_mpp_h264"
    assert target_candidate["pipeline_contract"]["launch_pipeline"].split().count("v4l2src") == 1
    assert target_candidate["pipeline_contract"]["topology"]["single_capture_pipeline"] is True
    assert target_candidate["runtime_module_implemented"] is True
    assert "runtime_importable" in target_candidate
    assert target_candidate["runtime"]["implementation"] == "gstreamer_v4l2_tee_mpp_h264"
    assert target_candidate["required_launch_elements"]["rockchip_mpp_h264_encoder"] == "mpph264enc"
    assert set(target_candidate["required_gstreamer_elements"]) >= {
        "v4l2src",
        "appsink",
        "jpegparse",
        "mppjpegdec",
        "rockchip_mpp_h264_encoder",
        "h264parse",
    }
    assert payload["webrtc_hardware_bridge"]["uses_pre_encoded_packets"] is True
    assert payload["webrtc_hardware_bridge"]["raw_frame_input_allowed"] is False
    assert payload["webrtc_hardware_bridge"]["software_h264_fallback_allowed"] is False
    assert payload["gstreamer_target_runtime"]["implemented"] is True
    assert payload["gstreamer_target_runtime"]["software_h264_fallback_allowed"] is False
    recommendation = payload["source_pipeline"]["recommended_next_hardware_path"]
    assert recommendation["name"] in {
        "gstreamer_explicit_rga_transform",
        "in_process_librga_virtualaddr_scale_crop",
    }
    assert recommendation["target_backend"] == "gstreamer_v4l2_tee_mpp_h264"
    assert "remaining_for_full_target" in recommendation
    assert "ffmpeg_alternative_blockers" in recommendation
    assert "librga" in payload
    path_names = {path["name"] for path in payload["encoder_paths"]}
    assert {
        "gstreamer_rockchip_mpp",
        "ffmpeg_rkmpp",
        "rockchip_mpp_demo",
        "v4l2_m2m_h264",
        "gstreamer_software_h264",
    } <= path_names
    for path in payload["encoder_paths"]:
        if path["name"] == "gstreamer_software_h264":
            assert path["target_compliant"] is False
            assert path["hardware"] is False
        if path["name"] == "rockchip_mpp_demo":
            assert path["production_ready"] is False


def test_production_encoder_selection_requires_webrtc_source_factory() -> None:
    gstreamer_ready = {
        "name": "gstreamer_rockchip_mpp",
        "available": True,
        "hardware": True,
        "target_compliant": True,
        "production_ready": True,
        "webrtc_source_supported": False,
    }
    ffmpeg_ready = {
        "name": "ffmpeg_rkmpp",
        "available": True,
        "hardware": True,
        "target_compliant": True,
        "production_ready": True,
        "webrtc_source_supported": True,
    }

    assert _select_production_hardware_path([gstreamer_ready]) is None
    assert _select_production_hardware_path([gstreamer_ready, ffmpeg_ready]) == ffmpeg_ready


def test_v4l2_m2m_probe_distinguishes_jpeg_only_rk3588_encoder() -> None:
    all_output = """
Driver Info:
        Driver name      : hantro-vpu
        Card type        : rockchip,rk3588-vepu121-enc
        Bus info         : platform:fdba0000.video-codec
        Capabilities     : 0x84204000
                Video Memory-to-Memory Multiplanar
Entity Info:
        Name             : rockchip,rk3588-vepu121-enc-source
Format Video Capture Multiplanar:
        Pixel Format      : 'JPEG' (JFIF JPEG)
Format Video Output Multiplanar:
        Pixel Format      : 'YM12' (Planar YUV 4:2:0 (N-C))
"""
    capture_formats = """
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture Multiplanar

        [0]: 'JPEG' (JFIF JPEG, compressed)
"""
    output_formats = """
ioctl: VIDIOC_ENUM_FMT
        Type: Video Output Multiplanar

        [0]: 'YM12' (Planar YUV 4:2:0 (N-C))
        [1]: 'NM12' (Y/UV 4:2:0 (N-C))
"""

    payload = _describe_v4l2_m2m_device(
        "/dev/video1",
        all_output,
        capture_formats,
        output_formats,
    )

    assert payload["role"] == "encoder"
    assert payload["supports_jpeg_encode"] is True
    assert payload["supports_raw_yuv_input"] is True
    assert payload["supports_h264_encode"] is False
    assert payload["production_h264_candidate"] is False
    assert payload["current_capture_format"]["fourcc"] == "JPEG"
    assert "JPEG-only" in payload["reason"]


def test_feed_metadata_reports_frame_sync_and_json_safe_overlays() -> None:
    feed = _MetadataFeed(_device(5, ring_depth=13, ts=123.4))

    payload = describe_feed_metadata(
        "c_channel_2",
        feed,
        requested_role="c_channel_2",
        config_role="c_channel_2",
        physical_source="video:5",
        crop={
            "available": True,
            "kind": "bbox_masked",
            "viewport": {"x": 10, "y": 20, "width": 100, "height": 80},
        },
    )

    assert payload["ok"] is True
    assert payload["message_type"] == "camera.feed_metadata"
    assert payload["schema_version"] == 1
    assert payload["physical_source"] == "video:5"
    assert payload["frame"]["timestamp"] == 123.4
    assert payload["frame"]["width"] == 12
    assert payload["coordinate_space"]["name"] == "sensor_frame"
    assert payload["coordinate_space"]["width"] == 12
    assert payload["coordinate_space"]["height"] == 8
    assert payload["coordinate_space"]["overlays"] == "sensor_frame"
    assert payload["transport_frame"] is None
    assert payload["inference_frame"] is None
    assert payload["ring_buffer_depth"] == 13
    assert payload["control_plane"]["payload_contains_pixels"] is False
    assert payload["control_plane"]["browser_side_render_target"] is True
    assert payload["control_plane"]["data_channel"] == {
        "label": "camera-metadata",
        "ordered": False,
        "max_retransmits": 0,
        "message_type": "camera.feed_metadata",
        "schema_version": 1,
    }
    assert payload["crop"]["available"] is True
    assert payload["crop"]["viewport"]["width"] == 100
    assert payload["overlays"][0]["bbox"] == [1, 2, 3, 4]
    assert payload["overlay_count"] == 2


def test_feed_metadata_declares_scaled_transport_and_inference_frames() -> None:
    sensor_frame = CameraFrame(
        raw=np.zeros((2160, 3840, 3), dtype=np.uint8),
        annotated=None,
        results=[],
        timestamp=200.0,
    )
    feed = _MetadataFeed(
        _device(
            0,
            latest_frame=sensor_frame,
            capture_backend={
                "implementation": "gstreamer_v4l2_tee_mpp_h264",
                "requested_mode": {
                    "width": 3840,
                    "height": 2160,
                    "fps": 30,
                    "fourcc": "MJPG",
                },
                "h264_output_mode": {"width": 1280, "height": 720, "fps": 30},
                "detection_output_mode": {"width": 640, "height": 360, "fps": 30},
                "hardware_scale_convert": True,
            },
        )
    )

    payload = describe_feed_metadata(
        "classification_channel",
        feed,
        requested_role="classification_channel",
        config_role="carousel",
        physical_source="video:0",
        crop={
            "available": True,
            "kind": "bbox_masked",
            "input_frame": {"width": 3840, "height": 2160},
            "viewport": {"x": 960, "y": 540, "width": 1280, "height": 720},
            "output_frame": {"width": 1280, "height": 720},
        },
    )

    assert payload["frame"]["width"] == 3840
    assert payload["frame"]["height"] == 2160
    assert payload["transport_frame"] == {"width": 1280, "height": 720, "fps": 30}
    assert payload["inference_frame"] == {"width": 640, "height": 360, "fps": 30}
    assert payload["coordinate_space"]["name"] == "sensor_frame"
    assert payload["coordinate_space"]["overlays"] == "sensor_frame"
    assert payload["coordinate_space"]["crop"] == "sensor_frame"
    assert payload["coordinate_space"]["transport"] == {
        "kind": "scaled_full_frame",
        "source_rect": {"x": 0, "y": 0, "width": 3840, "height": 2160},
        "output_frame": {"width": 1280, "height": 720, "fps": 30},
    }
    assert payload["coordinate_space"]["inference"] == {
        "kind": "scaled_full_frame",
        "source_rect": {"x": 0, "y": 0, "width": 3840, "height": 2160},
        "output_frame": {"width": 640, "height": 360, "fps": 30},
    }
    assert payload["crop"]["input_frame"] == {"width": 3840, "height": 2160}
    assert payload["crop"]["viewport"]["x"] == 960
    assert payload["overlays"][0]["bbox"] == [1, 2, 3, 4]


def test_feed_metadata_honors_region_filter() -> None:
    feed = _MetadataFeed(_device(5))

    payload = describe_feed_metadata(
        "c_channel_2",
        feed,
        exclude_categories=frozenset({"regions"}),
    )

    assert payload["overlay_count"] == 1
    assert payload["overlays"] == [
        {
            "type": "track_bbox",
            "category": "detections",
            "bbox": [1, 2, 3, 4],
        }
    ]


def test_channel_region_overlay_emits_polygon_metadata_for_browser_rendering() -> None:
    overlay = ChannelRegionOverlay(_RegionProvider(), "second_channel")

    metadata = overlay.metadata()

    assert metadata == [
        {
            "type": "channel_regions",
            "category": "regions",
            "poly_key": "second_channel",
            "polygon": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
        }
    ]


def test_webrtc_metadata_data_channel_stream_sends_only_new_frame_payloads() -> None:
    async def run() -> None:
        channel = _FakeMetadataChannel()
        timestamps = iter([10.0, 10.0, 11.0])

        def provider(role: str) -> dict:
            return {
                "ok": True,
                "role": role,
                "message_type": "camera.feed_metadata",
                "frame": {"timestamp": next(timestamps), "width": 12, "height": 8},
                "overlays": [],
                "control_plane": {"payload_contains_pixels": False},
            }

        await _send_camera_metadata_loop(
            role="c_channel_2",
            channel=channel,
            metadata_provider=provider,
            interval_s=0.001,
        )

        assert len(channel.sent) == 2
        first = json.loads(channel.sent[0])
        second = json.loads(channel.sent[1])
        assert first["message_type"] == "camera.feed_metadata"
        assert first["role"] == "c_channel_2"
        assert first["frame"]["timestamp"] == 10.0
        assert second["frame"]["timestamp"] == 11.0
        assert first["control_plane"]["payload_contains_pixels"] is False

    asyncio.run(run())


def _blocked_media_plane_payload(service) -> dict:
    payload = describe_media_plane(service)
    payload["capabilities"] = {
        "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
        "python_webrtc": {"ready": True, "aiortc": True, "av": True},
        "ffmpeg": {
            "rkmpp_h264_encoder": True,
            "rkmpp_h264_runtime_ready": False,
            "rkrga_filters": True,
            "rkrga_runtime_ready": False,
            "rkrga_crop_filter": True,
            "rkrga_crop_runtime_ready": False,
        },
        "source_pipeline": {
            "implementation": "staging_bgr24_cpu_pipe_to_h264_rkmpp",
            "zero_copy_dmabuf": False,
            "hardware_scale_convert_in_source": False,
            "hardware_crop_in_source": False,
            "target_compliant": False,
            "reason": "staging source pipeline",
        },
        "devices": {
            "known_rockchip_accelerators": {
                "/dev/mpp_service": False,
                "/dev/mpp-service": False,
                "/dev/rga": False,
                "/dev/dma_heap": False,
                "/dev/dri/renderD128": True,
            },
            "v4l2_m2m": {"h264_encoder_ready": False},
        },
        "encoder_paths": [
            {
                "name": "ffmpeg_rkmpp",
                "available": True,
                "hardware": True,
                "target_compliant": True,
                "production_ready": False,
                "reason": "runtime failed",
            },
            {
                "name": "gstreamer_software_h264",
                "available": True,
                "hardware": False,
                "target_compliant": False,
                "production_ready": False,
                "reason": "software fallback excluded",
            },
        ],
        "selected_encoder_path": None,
        "ready_for_hardware_webrtc": False,
    }
    return payload


def _hardware_ready_media_plane_payload(
    service,
    *,
    legacy_mjpeg_streams=None,
    bridge_implemented: bool = False,
) -> dict:
    payload = describe_media_plane(service, legacy_mjpeg_streams=legacy_mjpeg_streams)
    payload["invariants"]["assigned_physical_sources_exist"] = True
    payload["invariants"]["target_capture_backend_integrated"] = True
    for source in payload.get("physical_sources", []):
        source["source_exists"] = True
        source["source_presence"] = "present"
        if isinstance(source.get("capture_backend"), dict):
            source["capture_backend"]["target_compliant"] = True
            source["capture_backend"]["implementation"] = "gstreamer_v4l2_tee_mpp_h264"
    selected_encoder_path = {
        "name": "ffmpeg_rkmpp",
        "available": True,
        "hardware": True,
        "target_compliant": True,
        "production_ready": True,
        "command": "/usr/local/bin/ffmpeg-rockchip -c:v h264_rkmpp ...",
        "reason": "runtime probe passed",
    }
    payload["capabilities"] = {
        "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
        "python_webrtc": {"ready": True, "aiortc": True, "av": True},
        "ffmpeg": {
            "rkmpp_h264_encoder": True,
            "rkmpp_h264_runtime_ready": True,
            "rkrga_filters": True,
            "rkrga_runtime_ready": True,
            "rkrga_crop_filter": True,
            "rkrga_crop_runtime_ready": True,
        },
        "source_pipeline": {
            "implementation": "dmabuf_rga_h264_rkmpp",
            "zero_copy_dmabuf": True,
            "hardware_scale_convert_in_source": True,
            "hardware_crop_in_source": False,
            "target_compliant": True,
            "reason": "test target source pipeline",
        },
        "webrtc_hardware_bridge": {
            "implemented": bridge_implemented,
            "source_factory_registered": True,
            "runtime_hardware_encoder_ready": True,
            "encoded_frame_input": "h264_annex_b_or_avcc",
            "media_track": "aiortc.VideoStreamTrack",
            "reason": "test bridge",
        },
        "devices": {
            "known_rockchip_accelerators": {
                "/dev/mpp_service": True,
                "/dev/mpp-service": False,
                "/dev/rga": True,
                "/dev/dma_heap": True,
                "/dev/dri/renderD128": True,
            },
            "v4l2_m2m": {"h264_encoder_ready": False},
        },
        "encoder_paths": [selected_encoder_path],
        "selected_encoder_path": selected_encoder_path,
        "ready_for_hardware_webrtc": True,
    }
    return payload


def test_transport_gate_evaluation_rejects_software_h264_fallback() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _blocked_media_plane_payload(service)

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["python_webrtc"] is True
    assert evaluation["gates"]["target_ready"] is False
    assert evaluation["gates"]["production_hardware_encoder"] is False
    assert (
        "No production H.264 hardware encoder path with a WebRTC source factory is selected."
        in evaluation["blockers"]
    )
    assert evaluation["encoder_paths"]["gstreamer_software_h264"]["target_compliant"] is False


def test_transport_gate_separates_hardware_ready_from_legacy_mjpeg_compliance() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(
        service,
        bridge_implemented=True,
        legacy_mjpeg_streams={
            "live-c2": {
                "role": "c_channel_2",
                "physical_source": "video:5",
                "stack": "camera_service_live",
                "active_clients": 1,
            },
        },
    )

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["legacy_mjpeg_clients_absent"] is False
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert evaluation["legacy_mjpeg_active_clients"] == 1
    assert evaluation["migration_warnings"] == [
        "Legacy per-client MJPEG transport is active (1 client)."
    ]
    assert not any("Legacy" in blocker for blocker in evaluation["blockers"])


def test_transport_gate_requires_encoded_frame_webrtc_bridge_after_hardware_ready() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=False)

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["legacy_mjpeg_clients_absent"] is True
    assert evaluation["gates"]["webrtc_hardware_bridge_implemented"] is False
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert (
        "Hardware H.264 WebRTC encoded-frame bridge is not implemented."
        in evaluation["blockers"]
    )


def test_transport_gate_requires_hardware_source_factory_after_hardware_ready() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=False)
    payload["capabilities"]["webrtc_hardware_bridge"]["source_factory_registered"] = False

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["hardware_h264_source_factory_registered"] is False
    assert evaluation["gates"]["webrtc_hardware_bridge_implemented"] is False
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert (
        "Hardware H.264 source factory is not registered "
        "(set SORTER_CAMERA_CAPTURE_BACKEND=gstreamer_mpp or SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC=1)."
        in evaluation["blockers"]
    )


def test_transport_gate_accepts_full_architecture_when_hardware_bridge_and_no_legacy() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["hardware_h264_source_factory_registered"] is True
    assert evaluation["gates"]["webrtc_hardware_bridge_implemented"] is True
    assert evaluation["gates"]["source_pipeline_target_compliant"] is True
    assert evaluation["gates"]["hardware_scale_convert_source_pipeline"] is True
    assert evaluation["gates"]["hardware_crop_source_pipeline"] is False
    assert evaluation["gates"]["ffmpeg_rkrga_crop_runtime"] is True
    assert evaluation["gates"]["legacy_mjpeg_clients_absent"] is True
    assert evaluation["gates"]["target_architecture_compliant"] is True
    assert evaluation["blockers"] == []
    assert evaluation["migration_warnings"] == []


def test_transport_gate_requires_integrated_capture_backend() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)
    payload["invariants"]["target_capture_backend_integrated"] = False
    for source in payload.get("physical_sources", []):
        source["capture_backend"] = {
            "implementation": "opencv_v4l2_raw_ring",
            "single_capture_owner": True,
            "raw_ring_branch": True,
            "h264_webrtc_branch": False,
            "target_compliant": False,
        }

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["target_capture_backend_integrated"] is False
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert (
        "Active camera capture backend is not the integrated v4l2src/MPP tee raw-ring/H.264 target."
        in evaluation["blockers"]
    )


def test_transport_gate_rejects_staging_bgr_pipe_source_pipeline() -> None:
    service = SimpleNamespace(feeds={"c_channel_2": _feed(_device(5))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)
    payload["capabilities"]["source_pipeline"] = {
        "implementation": "staging_bgr24_cpu_pipe_to_h264_rkmpp",
        "zero_copy_dmabuf": False,
        "hardware_scale_convert_in_source": False,
        "target_compliant": False,
        "reason": "staging source pipeline",
    }

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["source_pipeline_target_compliant"] is False
    assert evaluation["gates"]["hardware_scale_convert_source_pipeline"] is False
    assert evaluation["gates"]["zero_copy_source_pipeline"] is False
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert "staging source pipeline" in evaluation["blockers"]


def test_media_plane_reports_active_videoconvertscale_software_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        media_plane,
        "probe_media_capabilities",
        lambda: {
            "target": {"transport": "webrtc", "video_codec": "h264", "encoder": "rockchip_mpp"},
            "python_webrtc": {"ready": True, "aiortc": True, "av": True},
            "ffmpeg": {"rkrga_crop_runtime_ready": True},
            "source_pipeline": {
                "target_capture_backend_required": True,
                "candidates": [
                    {
                        "name": "gstreamer_v4l2_tee_mpp_h264",
                        "available": True,
                    }
                ],
                "zero_copy_dmabuf": False,
                "hardware_scale_convert_in_source": False,
                "hardware_crop_in_source": False,
                "target_compliant": False,
            },
            "webrtc_hardware_bridge": {
                "implemented": True,
                "source_factory_registered": True,
                "runtime_hardware_encoder_ready": True,
            },
            "selected_encoder_path": {"hardware": True, "target_compliant": True},
            "ready_for_hardware_webrtc": True,
        },
    )
    monkeypatch.setattr(
        media_plane,
        "_scan_video_open_handles",
        lambda: media_plane._summarize_video_handle_entries([]),
    )
    capture_backend = {
        "implementation": "gstreamer_v4l2_tee_mpp_h264",
        "target_compliant": True,
        "single_capture_owner": True,
        "raw_ring_branch": True,
        "h264_webrtc_branch": True,
        "hardware_scale_convert": False,
        "hardware_scale_convert_element": None,
        "scale_convert_element": "videoconvertscale",
        "software_scale_convert_fallback": True,
        "hardware_crop": False,
        "hardware_crop_element": None,
        "zero_copy_dmabuf": True,
    }
    service = SimpleNamespace(
        feeds={"c_channel_2": _feed(_device(5, capture_backend=capture_backend))}
    )

    payload = describe_media_plane(service)
    source_pipeline = payload["capabilities"]["source_pipeline"]

    assert source_pipeline["target_compliant"] is True
    assert source_pipeline["zero_copy_dmabuf"] is True
    assert source_pipeline["hardware_scale_convert_in_source"] is False
    assert source_pipeline["hardware_scale_convert_element"] is None
    assert source_pipeline["scale_convert_element"] == "videoconvertscale"
    assert source_pipeline["software_scale_convert_fallback"] is True
    assert "software fallback" in source_pipeline["reason"]


def test_transport_gate_requires_assigned_camera_sources_to_exist() -> None:
    service = SimpleNamespace(feeds={"carousel": _feed(_device(7))})
    payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)
    payload["physical_sources"][0]["source_exists"] = False
    payload["physical_sources"][0]["source_presence"] = "missing"
    payload["invariants"]["assigned_physical_sources_exist"] = False

    evaluation = evaluate_transport_gates(payload)

    assert evaluation["gates"]["target_ready"] is True
    assert evaluation["gates"]["assigned_camera_sources_exist"] is False
    assert evaluation["gates"]["target_architecture_compliant"] is False
    assert "Assigned camera source is missing on this host: video:7." in evaluation["blockers"]


def test_webrtc_session_registry_deduplicates_aliases_by_physical_source() -> None:
    device = _device(5, ring_depth=13)
    service = SimpleNamespace(
        feeds={
            "c_channel_2": _feed(device),
            "feeder": _feed(device),
        }
    )
    registry = CameraWebRtcSessionRegistry()

    payload = registry.describe(
        service,
        media_plane_payload=_blocked_media_plane_payload(service),
    )

    assert payload["target"]["transport"] == "webrtc"
    assert payload["target_ready"] is False
    assert payload["target_architecture_compliant"] is False
    assert payload["control_plane"]["software_h264_fallback_allowed"] is False
    assert payload["control_plane"]["metadata_data_channel"]["label"] == "camera-metadata"
    assert payload["control_plane"]["metadata_data_channel"]["max_retransmits"] == 0
    assert payload["runtime"]["physical_source_count"] == 1
    assert payload["runtime"]["active_peer_count"] == 0
    assert payload["runtime"]["active_encoder_instances"] == 0
    assert payload["runtime"]["active_view_to_encoder_ratio"] is None
    assert payload["runtime"]["encoder_scaling_model"] == "per_physical_source"
    assert payload["runtime_invariants"]["one_media_session_per_physical_source"] is True
    assert payload["runtime_invariants"]["one_active_encoder_per_physical_source"] is True
    assert payload["runtime_invariants"]["encoder_count_does_not_scale_with_views"] is True
    assert payload["runtime_invariants"]["multi_view_sources_share_one_encoder"] is True
    assert payload["runtime_invariants"]["metadata_payloads_are_pixel_free"] is True
    assert payload["runtime_invariants"]["software_h264_fallback_forbidden"] is True
    assert len(payload["sessions"]) == 1
    session = payload["sessions"][0]
    assert session["physical_source"] == "video:5"
    assert session["roles"] == ["c_channel_2", "feeder"]
    assert session["encoder_instances_active"] == 0
    assert session["state"] == "blocked_missing_hardware_h264_path"


def test_webrtc_session_registry_distinguishes_ready_hardware_from_missing_bridge() -> None:
    device = _device(5)
    service = SimpleNamespace(feeds={"c_channel_2": _feed(device)})
    registry = CameraWebRtcSessionRegistry()

    payload = registry.describe(
        service,
        media_plane_payload=_hardware_ready_media_plane_payload(
            service,
            bridge_implemented=False,
        ),
    )

    assert payload["target_ready"] is True
    assert payload["target_architecture_compliant"] is False
    assert payload["gates"]["webrtc_hardware_bridge_implemented"] is False
    assert len(payload["sessions"]) == 1
    assert payload["sessions"][0]["state"] == "blocked_missing_webrtc_hardware_bridge"


def test_webrtc_session_registry_marks_staging_source_pipeline_noncompliant() -> None:
    device = _device(5)
    service = SimpleNamespace(feeds={"c_channel_2": _feed(device)})
    registry = CameraWebRtcSessionRegistry()
    media_payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)
    media_payload["capabilities"]["source_pipeline"] = {
        "implementation": "staging_bgr24_cpu_pipe_to_h264_rkmpp",
        "zero_copy_dmabuf": False,
        "hardware_scale_convert_in_source": False,
        "target_compliant": False,
        "reason": "staging source pipeline",
    }

    payload = registry.describe(service, media_plane_payload=media_payload)

    assert payload["target_ready"] is True
    assert payload["target_architecture_compliant"] is False
    assert payload["gates"]["source_pipeline_target_compliant"] is False
    assert payload["sessions"][0]["state"] == "blocked_target_architecture_noncompliant"


def test_webrtc_offer_creates_h264_answer_from_registered_hardware_source() -> None:
    async def run() -> None:
        from aiortc import RTCPeerConnection

        device = _device(5)
        feed = _feed(device)
        service = SimpleNamespace(
            feeds={"c_channel_2": feed},
            get_feed=lambda role: {"c_channel_2": feed}.get(role),
        )
        sources: dict[str, _StaticHardwareH264Source] = {}

        def source_factory(**kwargs):
            source = _StaticHardwareH264Source()
            sources[kwargs["physical_source"]] = source
            return source

        registry = CameraWebRtcSessionRegistry(hardware_source_factory=source_factory)
        client = RTCPeerConnection()
        client.addTransceiver("video", direction="recvonly")
        offer = await client.createOffer()
        await client.setLocalDescription(offer)
        try:
            answer = await registry.prepare_offer(
                "c_channel_2",
                sdp=client.localDescription.sdp,
                offer_type=client.localDescription.type,
                camera_service=service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )
            assert answer["ok"] is True
            assert answer["type"] == "answer"
            assert answer["video_codec"] == "h264"
            assert answer["software_h264_fallback_allowed"] is False
            assert "H264" in answer["sdp"]
            assert "VP8" not in answer["sdp"]
            assert answer["session"]["active_peer_count"] == 1
            assert answer["session"]["encoder_instances_active"] == 1
            assert sorted(sources) == ["video:5"]
        finally:
            await client.close()

    asyncio.run(run())


def test_webrtc_offer_refuses_staging_source_pipeline_even_when_encoder_is_ready() -> None:
    device = _device(5)
    feed = _feed(device)
    service = SimpleNamespace(
        feeds={"c_channel_2": feed},
        get_feed=lambda role: {"c_channel_2": feed}.get(role),
    )
    media_payload = _hardware_ready_media_plane_payload(service, bridge_implemented=True)
    media_payload["capabilities"]["source_pipeline"] = {
        "implementation": "staging_bgr24_cpu_pipe_to_h264_rkmpp",
        "zero_copy_dmabuf": False,
        "hardware_scale_convert_in_source": False,
        "target_compliant": False,
        "reason": "staging source pipeline",
    }
    registry = CameraWebRtcSessionRegistry(
        hardware_source_factory=lambda **_kwargs: _StaticHardwareH264Source()
    )

    try:
        asyncio.run(
            registry.prepare_offer(
                "c_channel_2",
                sdp="v=0\n",
                offer_type="offer",
                camera_service=service,
                media_plane_payload=media_payload,
            )
        )
    except WebRtcTransportError as exc:
        assert exc.status_code == 409
        detail = exc.to_http_detail()
        assert detail["code"] == "hardware_webrtc_transport_noncompliant"
        assert detail["physical_source"] == "video:5"
        assert detail["session"]["state"] == "blocked_target_architecture_noncompliant"
        assert detail["gates"]["target_ready"] is True
        assert detail["gates"]["source_pipeline_target_compliant"] is False
        assert "staging source pipeline" in detail["blockers"]
    else:
        raise AssertionError("offer should not negotiate through the staging source pipeline")


def test_webrtc_offers_for_alias_roles_share_one_hardware_source_and_encoder() -> None:
    async def run() -> None:
        from aiortc import RTCPeerConnection

        device = _device(5)
        c2_feed = _feed(device)
        feeder_feed = _feed(device)
        service = SimpleNamespace(
            feeds={"c_channel_2": c2_feed, "feeder": feeder_feed},
            get_feed=lambda role: {"c_channel_2": c2_feed, "feeder": feeder_feed}.get(role),
        )
        created_sources: list[_StaticHardwareH264Source] = []

        def source_factory(**kwargs):
            source = _StaticHardwareH264Source()
            created_sources.append(source)
            return source

        registry = CameraWebRtcSessionRegistry(hardware_source_factory=source_factory)
        clients: list[RTCPeerConnection] = []

        async def negotiate(role: str):
            client = RTCPeerConnection()
            clients.append(client)
            client.addTransceiver("video", direction="recvonly")
            offer = await client.createOffer()
            await client.setLocalDescription(offer)
            return await registry.prepare_offer(
                role,
                sdp=client.localDescription.sdp,
                offer_type=client.localDescription.type,
                camera_service=service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )

        try:
            first = await negotiate("c_channel_2")
            second = await negotiate("feeder")
            described = registry.describe(
                service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )
            session = described["sessions"][0]

            assert first["physical_source"] == "video:5"
            assert second["physical_source"] == "video:5"
            assert len(created_sources) == 1
            assert first["session"]["encoder_instances_active"] == 1
            assert second["session"]["active_peer_count"] == 2
            assert second["session"]["encoder_instances_active"] == 1
            assert described["runtime"]["active_peer_count"] == 2
            assert described["runtime"]["active_hardware_source_count"] == 1
            assert described["runtime"]["active_hardware_sources"] == ["video:5"]
            assert described["runtime"]["fanout_subscriber_count_by_source"] == {"video:5": 2}
            assert described["runtime"]["active_hardware_source_details"]["video:5"] == {
                "fanout": True,
                "fanout_subscriber_count": 2,
                "upstream_source_type": "_StaticHardwareH264Source",
            }
            assert described["runtime"]["active_encoder_instances"] == 1
            assert described["runtime"]["active_encoder_instances_by_source"] == {"video:5": 1}
            assert described["runtime"]["active_view_to_encoder_ratio"] == 2.0
            assert described["runtime"]["encoder_scaling_model"] == "per_physical_source"
            assert described["runtime"]["max_active_peers_per_source"] == 2
            assert described["runtime"]["max_active_encoder_instances_per_source"] == 1
            assert described["runtime"]["sources_with_multi_view_peers"] == ["video:5"]
            assert described["runtime_invariants"]["one_media_session_per_physical_source"] is True
            assert described["runtime_invariants"]["one_active_hardware_source_per_physical_source"] is True
            assert described["runtime_invariants"]["one_active_encoder_per_physical_source"] is True
            assert described["runtime_invariants"]["encoder_count_does_not_scale_with_views"] is True
            assert described["runtime_invariants"]["multi_view_sources_share_one_encoder"] is True
            assert described["runtime_invariants"]["fanout_subscribers_match_active_peers"] is True
            assert described["runtime_invariants"]["active_peers_have_encoder"] is True
            assert described["runtime_invariants"]["metadata_payloads_are_pixel_free"] is True
            assert described["runtime_invariants"]["software_h264_fallback_forbidden"] is True
            assert session["active_peer_count"] == 2
            assert session["encoder_instances_active"] == 1
            assert session["state"] == "answer_created"
        finally:
            for client in clients:
                await client.close()
            await registry.aclose()

    asyncio.run(run())


def test_webrtc_runtime_invariants_mark_corrupt_multi_encoder_session_noncompliant() -> None:
    async def run() -> None:
        from aiortc import RTCPeerConnection

        device = _device(5)
        feed = _feed(device)
        service = SimpleNamespace(
            feeds={"c_channel_2": feed},
            get_feed=lambda role: {"c_channel_2": feed}.get(role),
        )

        registry = CameraWebRtcSessionRegistry(
            hardware_source_factory=lambda **_kwargs: _StaticHardwareH264Source()
        )
        client = RTCPeerConnection()
        client.addTransceiver("video", direction="recvonly")
        offer = await client.createOffer()
        await client.setLocalDescription(offer)
        try:
            await registry.prepare_offer(
                "c_channel_2",
                sdp=client.localDescription.sdp,
                offer_type=client.localDescription.type,
                camera_service=service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )
            registry._sessions["video:5"].encoder_instances_active = 2

            described = registry.describe(
                service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )

            assert described["runtime"]["active_encoder_instances"] == 2
            assert described["runtime"]["active_view_to_encoder_ratio"] == 0.5
            assert described["runtime"]["encoder_scaling_model"] == "per_view_or_invalid"
            assert described["runtime"]["max_active_encoder_instances_per_source"] == 2
            assert described["runtime_invariants"]["one_active_encoder_per_physical_source"] is False
            assert described["runtime_invariants"]["encoder_count_does_not_scale_with_views"] is False
            assert described["target_architecture_compliant"] is False
        finally:
            await client.close()
            await registry.aclose()

    asyncio.run(run())


def test_webrtc_shared_source_stops_only_after_last_peer_drops() -> None:
    async def run() -> None:
        from aiortc import RTCPeerConnection

        device = _device(5)
        c2_feed = _feed(device)
        feeder_feed = _feed(device)
        service = SimpleNamespace(
            feeds={"c_channel_2": c2_feed, "feeder": feeder_feed},
            get_feed=lambda role: {"c_channel_2": c2_feed, "feeder": feeder_feed}.get(role),
        )
        created_sources: list[_StaticHardwareH264Source] = []

        def source_factory(**kwargs):
            source = _StaticHardwareH264Source()
            created_sources.append(source)
            return source

        registry = CameraWebRtcSessionRegistry(hardware_source_factory=source_factory)
        clients: list[RTCPeerConnection] = []
        server_peers: list[RTCPeerConnection] = []

        async def negotiate(role: str):
            client = RTCPeerConnection()
            clients.append(client)
            client.addTransceiver("video", direction="recvonly")
            offer = await client.createOffer()
            await client.setLocalDescription(offer)
            return await registry.prepare_offer(
                role,
                sdp=client.localDescription.sdp,
                offer_type=client.localDescription.type,
                camera_service=service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )

        try:
            await negotiate("c_channel_2")
            await negotiate("feeder")
            source = created_sources[0]
            server_peers = list(registry._peers_by_source["video:5"])

            await registry._drop_peer("video:5", server_peers[0])
            first_drop = registry.describe(
                service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )["sessions"][0]

            assert first_drop["active_peer_count"] == 1
            assert first_drop["encoder_instances_active"] == 1
            assert first_drop["state"] == "answer_created"
            assert registry._hardware_sources["video:5"].source is source
            assert source.stop_calls == 0

            await registry._drop_peer("video:5", server_peers[1])
            second_drop = registry.describe(
                service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )["sessions"][0]

            assert second_drop["active_peer_count"] == 0
            assert second_drop["encoder_instances_active"] == 0
            assert second_drop["state"] == "ready_for_offer"
            assert "video:5" not in registry._hardware_sources
            assert source.stop_calls == 1
        finally:
            for peer in server_peers:
                await peer.close()
            for client in clients:
                await client.close()
            await registry.aclose()

    asyncio.run(run())


def test_webrtc_concurrent_offers_create_only_one_hardware_source() -> None:
    async def run() -> None:
        from aiortc import RTCPeerConnection

        device = _device(5)
        c2_feed = _feed(device)
        feeder_feed = _feed(device)
        service = SimpleNamespace(
            feeds={"c_channel_2": c2_feed, "feeder": feeder_feed},
            get_feed=lambda role: {"c_channel_2": c2_feed, "feeder": feeder_feed}.get(role),
        )
        created_sources: list[_StaticHardwareH264Source] = []
        factory_started = asyncio.Event()
        release_factory = asyncio.Event()

        async def source_factory(**kwargs):
            source = _StaticHardwareH264Source()
            created_sources.append(source)
            factory_started.set()
            await release_factory.wait()
            return source

        registry = CameraWebRtcSessionRegistry(hardware_source_factory=source_factory)
        clients: list[RTCPeerConnection] = []

        async def negotiate(role: str):
            client = RTCPeerConnection()
            clients.append(client)
            client.addTransceiver("video", direction="recvonly")
            offer = await client.createOffer()
            await client.setLocalDescription(offer)
            return await registry.prepare_offer(
                role,
                sdp=client.localDescription.sdp,
                offer_type=client.localDescription.type,
                camera_service=service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )

        first_task = asyncio.create_task(negotiate("c_channel_2"))
        await factory_started.wait()
        second_task = asyncio.create_task(negotiate("feeder"))
        await asyncio.sleep(0)
        release_factory.set()

        try:
            first, second = await asyncio.gather(first_task, second_task)
            described = registry.describe(
                service,
                media_plane_payload=_hardware_ready_media_plane_payload(
                    service,
                    bridge_implemented=True,
                ),
            )
            session = described["sessions"][0]

            assert first["physical_source"] == "video:5"
            assert second["physical_source"] == "video:5"
            assert len(created_sources) == 1
            assert session["active_peer_count"] == 2
            assert session["encoder_instances_active"] == 1
        finally:
            for client in clients:
                await client.close()
            await registry.aclose()

    asyncio.run(run())


def test_webrtc_offer_refuses_until_hardware_h264_gate_is_ready() -> None:
    device = _device(5)
    service = SimpleNamespace(
        feeds={
            "c_channel_2": _feed(device),
            "feeder": _feed(device),
        },
        get_feed=lambda role: {"c_channel_2": _feed(device), "feeder": _feed(device)}.get(role),
    )
    registry = CameraWebRtcSessionRegistry()

    try:
        asyncio.run(
            registry.prepare_offer(
                "c_channel_2",
                sdp="v=0\n",
                offer_type="offer",
                camera_service=service,
                media_plane_payload=_blocked_media_plane_payload(service),
            )
        )
    except WebRtcTransportError as exc:
        assert exc.status_code == 503
        detail = exc.to_http_detail()
        assert detail["code"] == "hardware_webrtc_transport_unavailable"
        assert detail["physical_source"] == "video:5"
        assert detail["metadata_data_channel"]["label"] == "camera-metadata"
        assert detail["session"]["encoder_instances_active"] == 0
        assert detail["gates"]["target_ready"] is False
    else:
        raise AssertionError("offer should not negotiate without hardware H.264")
