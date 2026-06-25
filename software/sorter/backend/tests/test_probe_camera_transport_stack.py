from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_camera_transport_stack.py"
SPEC = importlib.util.spec_from_file_location("probe_camera_transport_stack", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _report(*, target_ready: bool, compliant: bool) -> dict:
    return {
        "evaluation": {
            "gates": {
                "target_ready": target_ready,
                "target_architecture_compliant": compliant,
            },
            "legacy_mjpeg_active_clients": 1 if target_ready and not compliant else 0,
            "migration_warnings": (
                ["Legacy per-client MJPEG transport is active (1 client)."]
                if target_ready and not compliant
                else []
            ),
            "blockers": [],
        }
    }


def test_probe_exit_gate_requires_target_architecture_compliance_by_default() -> None:
    report = _report(target_ready=True, compliant=False)

    assert probe._exit_gate(report) is False
    assert probe._exit_gate(report, readiness_only=True) is True


def test_probe_exit_gate_passes_when_full_target_architecture_is_compliant() -> None:
    report = _report(target_ready=True, compliant=True)

    assert probe._exit_gate(report) is True
    assert probe._exit_gate(report, readiness_only=True) is True


def test_probe_text_report_surfaces_legacy_mjpeg_migration_warning(capsys) -> None:
    report = {
        "source": "backend",
        "host": {
            "os_release": {"PRETTY_NAME": "Ubuntu test"},
            "kernel": "6.1",
            "machine": "aarch64",
            "euid": 1000,
            "sorteros_image_contract": None,
        },
        "media_plane": {
            "capabilities": {
                "encoder_paths": [],
                "webrtc_hardware_bridge": {
                    "implemented": False,
                    "packet_track_available": True,
                    "h264_packetizer_available": True,
                    "integrated_with_hardware_encoder": False,
                    "source_factory": "ffmpeg_rkmpp",
                    "source_factory_registered": False,
                    "runtime_hardware_encoder_ready": False,
                    "raw_frame_input_allowed": False,
                    "software_h264_fallback_allowed": False,
                    "reason": "Packet bridge exists, but no live hardware encoder source is integrated yet.",
                },
                "source_pipeline": {
                    "implementation": "staging_bgr24_cpu_pipe_to_h264_rkmpp",
                    "input_memory": "cpu_bgr24_frames_from_camera_feed",
                    "zero_copy_dmabuf": False,
                    "hardware_scale_convert_in_source": False,
                    "hardware_crop_in_source": False,
                    "rkrga_filters_advertised": True,
                    "rkrga_runtime_ready": False,
                    "rkrga_crop_filter_advertised": True,
                    "rkrga_crop_runtime_ready": True,
                    "rkrga_crop_path": "ffmpeg_vpp_rkrga",
                    "direct_librga_runtime_ready": True,
                    "direct_librga_path": "librga_virtualaddr",
                    "detection_crop_strategy": {
                        "target_stage": "detection_yolo_branch_before_scale",
                        "current_stage": "scaled_full_frame_then_perception_crop",
                        "active_media_pipeline_crop": False,
                        "hardware_crop_element": None,
                        "hardware_crop_runtime_available": True,
                        "hardware_crop_runtime_path": "ffmpeg_vpp_rkrga",
                        "software_videocrop_allowed": False,
                        "reason": "RGA crop runtime exists, but active source graph does not crop.",
                    },
                    "target_capture_backend_integrated": False,
                    "target_compliant": False,
                    "reason": "staging source pipeline",
                    "candidates": [
                        {
                            "name": "shared_feed_bgr24_to_ffmpeg_rkmpp",
                            "role": "current_staging",
                            "available": True,
                            "opens_capture_device": False,
                            "target_compliant": False,
                            "reason": "staging source pipeline",
                        },
                        {
                            "name": "forbidden_ffmpeg_v4l2_direct_to_rkmpp",
                            "role": "forbidden_even_if_available",
                            "available": True,
                            "opens_capture_device": True,
                            "violates_single_capture": True,
                            "target_compliant": False,
                            "reason": "Would let ffmpeg open /dev/videoN directly.",
                        },
                    ],
                },
            }
        },
        **_report(target_ready=True, compliant=False),
    }

    probe._print_text_report(report)

    output = capsys.readouterr().out
    assert "target_architecture_compliant: False" in output
    assert "legacy_mjpeg_active_clients: 1" in output
    assert "WebRTC Hardware Bridge" in output
    assert "packet_track_available: True" in output
    assert "source_factory: ffmpeg_rkmpp" in output
    assert "source_factory_registered: False" in output
    assert "runtime_hardware_encoder_ready: False" in output
    assert "raw_frame_input_allowed: False" in output
    assert "Source Pipeline" in output
    assert "implementation: staging_bgr24_cpu_pipe_to_h264_rkmpp" in output
    assert "zero_copy_dmabuf: False" in output
    assert "hardware_scale_convert_in_source: False" in output
    assert "hardware_crop_in_source: False" in output
    assert "rkrga_crop_filter_advertised: True" in output
    assert "rkrga_crop_runtime_ready: True" in output
    assert "rkrga_crop_path: ffmpeg_vpp_rkrga" in output
    assert "direct_librga_runtime_ready: True" in output
    assert "direct_librga_path: librga_virtualaddr" in output
    assert "detection_crop_strategy:" in output
    assert "target_stage: detection_yolo_branch_before_scale" in output
    assert "current_stage: scaled_full_frame_then_perception_crop" in output
    assert "active_media_pipeline_crop: False" in output
    assert "hardware_crop_runtime_available: True" in output
    assert "software_videocrop_allowed: False" in output
    assert "target_capture_backend_integrated: False" in output
    assert "target_compliant: False" in output
    assert "candidates:" in output
    assert "shared_feed_bgr24_to_ffmpeg_rkmpp" in output
    assert "forbidden_ffmpeg_v4l2_direct_to_rkmpp" in output
    assert "violates_single_capture: True" in output
    assert "Migration Warnings" in output
    assert "Legacy per-client MJPEG transport is active (1 client)." in output


def test_probe_loads_sorteros_image_contract(tmp_path) -> None:
    contract_path = tmp_path / "camera-transport-target.json"
    contract_path.write_text(
        json.dumps(
            {
                "profile": "rk3588-rockchip-mpp-h264-webrtc",
                "backend_env": {
                    "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
                    "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
                    "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
                },
            }
        )
    )

    payload = probe._sorteros_image_contract(contract_path)

    assert payload["profile"] == "rk3588-rockchip-mpp-h264-webrtc"
    assert payload["backend_env"]["SORTER_CAMERA_CAPTURE_BACKEND"] == "gstreamer_mpp"
    assert payload["backend_env"]["SORTER_ENABLE_GSTREAMER_MPP_CAPTURE"] == "1"
    assert payload["backend_env"]["SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC"] == "1"


def test_probe_loads_sorteros_camera_transport_firstboot_status(tmp_path) -> None:
    status_path = tmp_path / "camera-transport-status.json"
    status_path.write_text(
        json.dumps(
            {
                "profile": "rk3588-rockchip-mpp-h264-webrtc",
                "ok": False,
                "missing_device_nodes": ["/dev/mpp_service"],
            }
        )
    )

    payload = probe._sorteros_camera_transport_status(status_path)

    assert payload["profile"] == "rk3588-rockchip-mpp-h264-webrtc"
    assert payload["ok"] is False
    assert payload["missing_device_nodes"] == ["/dev/mpp_service"]


def test_probe_text_report_surfaces_sorteros_image_contract(capsys) -> None:
    report = {
        "source": "backend",
        "host": {
            "os_release": {"PRETTY_NAME": "Ubuntu test"},
            "kernel": "6.1",
            "machine": "aarch64",
            "euid": 1000,
            "sorteros_image_contract": {
                "profile": "rk3588-rockchip-mpp-h264-webrtc",
                "image_version": "test-transport",
                "branch": "sorthive",
                "required_machine": "aarch64",
                "required_kernel_release_patterns": ["^6\\.1\\."],
                "backend_env": {
                    "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
                    "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
                    "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
                },
                "required_device_nodes": ["/dev/mpp_service", "/dev/rga"],
                "acceptance_probe_commands": [
                    "probe_camera_transport_stack.py",
                    "probe_webrtc_view_scaling.py --views 3",
                ],
            },
        },
        "media_plane": {
            "capabilities": {"encoder_paths": []},
            "physical_sources": [
                {
                    "source": "video:5",
                    "roles": ["c_channel_2", "feeder"],
                    "capture_instances": 1,
                    "ring_buffer_depth": 90,
                    "latest_frame": {"timestamp": 100.0},
                }
            ],
        },
        **_report(target_ready=False, compliant=False),
    }

    probe._print_text_report(report)

    output = capsys.readouterr().out
    assert "SorterOS Image Contract" in output
    assert "profile: rk3588-rockchip-mpp-h264-webrtc" in output
    assert "required_machine: aarch64" in output
    assert "required_kernel_release_patterns: ^6\\.1\\." in output
    assert "backend_env: SORTER_CAMERA_CAPTURE_BACKEND, SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC, SORTER_ENABLE_GSTREAMER_MPP_CAPTURE" in output
    assert "/dev/mpp_service" in output
    assert "acceptance_probe_commands:" in output
    assert "probe_webrtc_view_scaling.py --views 3" in output


def test_probe_text_report_surfaces_firstboot_camera_transport_status(capsys) -> None:
    report = {
        "source": "backend",
        "host": {
            "os_release": {"PRETTY_NAME": "Ubuntu test"},
            "kernel": "6.1",
            "machine": "aarch64",
            "euid": 1000,
            "sorteros_image_contract": None,
            "sorteros_camera_transport_status": {
                "profile": "rk3588-rockchip-mpp-h264-webrtc",
                "ok": False,
                "target_ready": False,
                "target_architecture_compliant": False,
                "platform": {"kernel_release": "6.13.0", "machine": "aarch64"},
                "missing_kernel_release_patterns": ["^6\\.1\\."],
                "missing_device_nodes": ["/dev/mpp_service"],
                "missing_packages": ["rockchip-multimedia-config"],
                "missing_runtime_gates": ["ffmpeg_rkmpp_runtime"],
            },
        },
        "media_plane": {
            "capabilities": {"encoder_paths": []},
            "physical_sources": [
                {
                    "source": "video:5",
                    "roles": ["c_channel_2", "feeder"],
                    "capture_instances": 1,
                    "ring_buffer_depth": 90,
                    "latest_frame": {"timestamp": 100.0},
                }
            ],
        },
        **_report(target_ready=False, compliant=False),
    }

    probe._print_text_report(report)

    output = capsys.readouterr().out
    assert "SorterOS Camera Transport Firstboot Status" in output
    assert "ok: False" in output
    assert "kernel_release: 6.13.0" in output
    assert "machine: aarch64" in output
    assert "^6\\.1\\." in output
    assert "/dev/mpp_service" in output
    assert "rockchip-multimedia-config" in output
    assert "ffmpeg_rkmpp_runtime" in output


def test_probe_text_report_surfaces_webrtc_runtime_summary(capsys) -> None:
    report = {
        "source": "backend",
        "host": {
            "os_release": {"PRETTY_NAME": "Ubuntu test"},
            "kernel": "6.1",
            "machine": "aarch64",
            "euid": 1000,
            "sorteros_image_contract": None,
            "sorteros_camera_transport_status": None,
        },
        "media_plane": {
            "capabilities": {"encoder_paths": []},
            "physical_sources": [
                {
                    "source": "video:5",
                    "roles": ["c_channel_2", "feeder"],
                    "capture_instances": 1,
                    "ring_buffer_depth": 90,
                    "latest_frame": {"timestamp": 100.0},
                }
            ],
        },
        "webrtc_sessions": {
            "target_ready": True,
            "target_architecture_compliant": True,
            "runtime": {
                "active_peer_count": 2,
                "active_hardware_source_count": 1,
                "active_encoder_instances": 1,
                "active_view_to_encoder_ratio": 2.0,
                "encoder_scaling_model": "per_physical_source",
                "active_hardware_sources": ["video:5"],
                "process_resource": {
                    "process_cpu_seconds": 12.5,
                    "max_rss_kb": 123456,
                },
            },
            "runtime_invariants": {
                "one_media_session_per_physical_source": True,
                "one_active_encoder_per_physical_source": True,
                "encoder_count_does_not_scale_with_views": True,
                "multi_view_sources_share_one_encoder": True,
                "active_peers_have_encoder": True,
                "metadata_payloads_are_pixel_free": True,
                "software_h264_fallback_forbidden": True,
            },
        },
        **_report(target_ready=True, compliant=True),
    }

    probe._print_text_report(report)

    output = capsys.readouterr().out
    assert "WebRTC Runtime" in output
    assert "active_peer_count: 2" in output
    assert "active_hardware_source_count: 1" in output
    assert "active_encoder_instances: 1" in output
    assert "active_view_to_encoder_ratio: 2.0" in output
    assert "encoder_scaling_model: per_physical_source" in output
    assert "process_resource: cpu_s=12.5 rss_kb=123456" in output
    assert "active_hardware_sources: video:5" in output
    assert "OK one_active_encoder_per_physical_source" in output
    assert "OK encoder_count_does_not_scale_with_views" in output
    assert "OK metadata_payloads_are_pixel_free" in output
    assert "video:5 roles=['c_channel_2', 'feeder'] captures=1 ring=90" in output
    assert "latest=True" in output
