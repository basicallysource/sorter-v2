from __future__ import annotations

import pytest

from vision.gstreamer_target_capture import (
    TARGET_PIPELINE_NAME,
    GStreamerTargetElements,
    build_gstreamer_target_capture_contract,
)


def test_target_capture_contract_builds_single_v4l2_tee_pipeline() -> None:
    contract = build_gstreamer_target_capture_contract(device_path="/dev/video5")
    launch = contract["launch_pipeline"]
    tokens = launch.split()

    assert contract["name"] == TARGET_PIPELINE_NAME
    assert tokens.count("v4l2src") == 1
    assert launch.count("device=/dev/video5") == 1
    assert "tee name=sorter_capture_tee" in launch
    assert "sorter_capture_tee. ! queue name=sorter_raw_queue" in launch
    assert "sorter_capture_tee. ! queue name=sorter_h264_queue" in launch
    assert "appsink name=sorter_raw_ring" in launch
    assert "appsink name=sorter_h264_webrtc" in launch
    assert "video/x-raw,format=NV12" in launch
    assert "mppjpegdec format=NV12" in launch
    assert "video/x-h264,stream-format=byte-stream,alignment=au" in launch


def test_target_capture_contract_requires_hardware_rockchip_elements() -> None:
    contract = build_gstreamer_target_capture_contract(device_path="/dev/video3")

    assert contract["topology"]["single_capture_pipeline"] is True
    assert contract["topology"]["raw_ring_branch"] is True
    assert contract["topology"]["h264_webrtc_branch"] is True
    assert contract["zero_copy_dmabuf"] is True
    assert contract["hardware_scale_convert"] is False
    assert contract["software_h264_fallback_allowed"] is False
    assert contract["required_gstreamer_elements"] == {
        "v4l2src": "v4l2src",
        "appsink": "appsink",
        "jpegparse": "jpegparse",
        "mppjpegdec": "mppjpegdec",
        "rockchip_mpp_h264_encoder": "mpph264enc",
        "h264parse": "h264parse",
    }
    assert {"/dev/mpp_service", "/dev/rga", "/dev/dma_heap"} == set(
        contract["required_device_nodes"]
    )


def test_target_capture_contract_forbids_software_encoder_or_converter() -> None:
    with pytest.raises(ValueError, match="Software H.264 encoder"):
        build_gstreamer_target_capture_contract(
            device_path="/dev/video5",
            elements=GStreamerTargetElements(h264_encoder="x264enc"),
        )

    with pytest.raises(ValueError, match="Software scale/convert"):
        build_gstreamer_target_capture_contract(
            device_path="/dev/video5",
            elements=GStreamerTargetElements(rga_converter="videoconvert"),
        )

    with pytest.raises(ValueError, match="Software JPEG decoder"):
        build_gstreamer_target_capture_contract(
            device_path="/dev/video5",
            elements=GStreamerTargetElements(jpeg_decoder="jpegdec"),
        )


def test_target_capture_contract_rejects_abstract_or_invalid_sources() -> None:
    with pytest.raises(ValueError, match="/dev/videoN"):
        build_gstreamer_target_capture_contract(device_path="/dev/videoN")

    with pytest.raises(ValueError, match="Unsupported target input fourcc"):
        build_gstreamer_target_capture_contract(device_path="/dev/video5", input_fourcc="H264")


def test_target_capture_contract_supports_raw_yuyv_without_mjpeg_decoder_chain() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video5",
        input_fourcc="YUYV",
        elements=GStreamerTargetElements(rga_converter="rkrgaconvert"),
    )
    launch = contract["launch_pipeline"]

    assert "video/x-raw,format=YUY2" in launch
    assert "jpegparse" not in launch
    assert "mppjpegdec" not in launch
    assert contract["hardware_decode"] is False
