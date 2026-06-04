from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from vision.gstreamer_target_capture import build_gstreamer_target_capture_contract


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_gstreamer_target_capture_pipeline.py"
SPEC = importlib.util.spec_from_file_location("probe_gstreamer_target_capture_pipeline", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _payload(
    *,
    integrated: bool = True,
    target_candidate_available: bool = True,
    forbidden_target: bool = False,
    capture_instances: int = 1,
    source_exists: bool = True,
    missing_element: str | None = None,
    missing_node: str | None = None,
) -> dict:
    elements = {
        "v4l2src": True,
        "appsink": True,
        "jpegparse": True,
        "mppjpegdec": True,
        "rockchip_mpp_h264_encoder": True,
        "h264parse": True,
    }
    nodes = {
        "/dev/mpp_service": True,
        "/dev/rga": True,
        "/dev/dma_heap": True,
    }
    if missing_element is not None:
        elements[missing_element] = False
    if missing_node is not None:
        nodes[missing_node] = False
    pipeline_impl = probe.TARGET_PIPELINE_NAME if integrated else "staging_bgr24_cpu_pipe_to_h264_rkmpp"
    target_contract = build_gstreamer_target_capture_contract(device_path="/dev/video5")
    return {
        "ok": True,
        "roles": {
            "c_channel_2": {
                "physical_source": "video:5",
            }
        },
        "capabilities": {
            "source_pipeline": {
                "implementation": pipeline_impl,
                "target_capture_backend_integrated": integrated,
                "target_compliant": integrated and target_candidate_available,
                "zero_copy_dmabuf": integrated,
                "hardware_scale_convert_in_source": integrated,
                "candidates": [
                    {
                        "name": "shared_feed_bgr24_to_ffmpeg_rkmpp",
                        "role": "current_staging",
                        "available": True,
                        "target_compliant": False,
                        "opens_capture_device": False,
                        "raw_ring_branch": True,
                        "software_h264_fallback_allowed": False,
                    },
                    {
                        "name": probe.FORBIDDEN_DIRECT_PIPELINE_NAME,
                        "role": "forbidden_even_if_available",
                        "available": True,
                        "target_compliant": forbidden_target,
                        "opens_capture_device": True,
                        "violates_single_capture": True,
                        "raw_ring_branch": False,
                        "software_h264_fallback_allowed": False,
                    },
                    {
                        "name": probe.TARGET_PIPELINE_NAME,
                        "role": "target_candidate",
                        "available": target_candidate_available,
                        "target_compliant": integrated and target_candidate_available,
                        "opens_capture_device": True,
                        "single_capture_pipeline": True,
                        "raw_ring_branch": True,
                        "h264_webrtc_branch": True,
                        "software_h264_fallback_allowed": False,
                        "pipeline_contract": target_contract,
                        "runtime_module_implemented": True,
                        "runtime_importable": True,
                        "runtime": {
                            "implemented": True,
                            "runtime_importable": True,
                            "software_h264_fallback_allowed": False,
                        },
                        "required_gstreamer_elements": elements,
                        "required_device_nodes": nodes,
                    },
                ],
            }
        },
        "physical_sources": [
            {
                "source": "video:5",
                "roles": ["c_channel_2", "feeder"],
                "source_exists": source_exists,
                "capture_instances": capture_instances,
                "capture_backend": {
                    "implementation": probe.TARGET_PIPELINE_NAME if integrated else "opencv_v4l2_raw_ring",
                    "single_capture_owner": True,
                    "raw_ring_branch": True,
                    "h264_webrtc_branch": integrated,
                    "hardware_scale_convert": integrated,
                    "zero_copy_dmabuf": integrated,
                    "target_compliant": integrated,
                },
                "target_capture_pipeline_contract": target_contract,
            }
        ],
    }


def test_target_capture_pipeline_accepts_integrated_gstreamer_tee_backend() -> None:
    result = probe.evaluate_target_capture_pipeline(
        payload=_payload(),
        roles=["c_channel_2"],
    )

    assert result["ok"] is True
    assert result["missing"] == []
    assert result["results"][0]["capture_backend"]["implementation"] == probe.TARGET_PIPELINE_NAME


def test_target_capture_pipeline_rejects_current_opencv_raw_ring_backend() -> None:
    result = probe.evaluate_target_capture_pipeline(
        payload=_payload(integrated=False),
        roles=["c_channel_2"],
    )

    assert result["ok"] is False
    assert any("not using the integrated target capture backend" in item for item in result["missing"])
    assert any("opencv_v4l2_raw_ring" in item for item in result["missing"])
    assert any("does not expose the H.264 WebRTC branch" in item for item in result["missing"])


def test_target_capture_pipeline_rejects_missing_target_gstreamer_element_and_node() -> None:
    result = probe.evaluate_target_capture_pipeline(
        payload=_payload(
            target_candidate_available=False,
            missing_element="rockchip_mpp_h264_encoder",
            missing_node="/dev/rga",
        ),
        roles=["c_channel_2"],
    )

    assert result["ok"] is False
    assert any("Target source-pipeline candidate" in item for item in result["missing"])
    assert any("rockchip_mpp_h264_encoder" in item for item in result["missing"])
    assert any("/dev/rga" in item for item in result["missing"])


def test_target_capture_pipeline_rejects_direct_ffmpeg_candidate_becoming_compliant() -> None:
    result = probe.evaluate_target_capture_pipeline(
        payload=_payload(forbidden_target=True),
        roles=["c_channel_2"],
    )

    assert result["ok"] is False
    assert any("Forbidden direct ffmpeg candidate is target-compliant" in item for item in result["missing"])


def test_target_capture_pipeline_rejects_missing_runtime_module() -> None:
    payload = _payload()
    target = next(
        item
        for item in payload["capabilities"]["source_pipeline"]["candidates"]
        if item["name"] == probe.TARGET_PIPELINE_NAME
    )
    target["runtime_module_implemented"] = False
    target["runtime_importable"] = False
    target["runtime"] = {"reason": "missing gi"}

    result = probe.evaluate_target_capture_pipeline(
        payload=payload,
        roles=["c_channel_2"],
    )

    assert result["ok"] is False
    assert any("runtime module is not implemented" in item for item in result["missing"])
    assert any("runtime module is not importable" in item for item in result["missing"])


def test_target_capture_pipeline_rejects_duplicate_capture_instances() -> None:
    result = probe.evaluate_target_capture_pipeline(
        payload=_payload(capture_instances=2),
        roles=["c_channel_2"],
    )

    assert result["ok"] is False
    assert any("Capture instances" in item for item in result["missing"])
