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


def test_target_capture_contract_can_scale_h264_preview_with_rga() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        fps=30,
        h264_width=1280,
        h264_height=720,
        elements=GStreamerTargetElements(rga_converter="rkrgaconvert"),
    )
    launch = contract["launch_pipeline"]

    assert "image/jpeg,width=3840,height=2160,framerate=30/1" in launch
    assert "rkrgaconvert ! video/x-raw,format=NV12,width=1280,height=720" in launch
    assert contract["hardware_scale_convert"] is True
    assert contract["profiles"]["capture"]["width"] == 3840
    assert contract["profiles"]["classification_crops"]["width"] == 3840
    assert contract["profiles"]["preview_webrtc"]["width"] == 1280
    h264_branch = next(item for item in contract["branches"] if item["name"] == "h264_webrtc")
    assert h264_branch["input_width"] == 3840
    assert h264_branch["output_width"] == 1280
    assert h264_branch["hardware_scale_convert"] is True


def test_target_capture_contract_can_scale_h264_preview_with_direct_librga_appsrc() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        fps=30,
        h264_width=1280,
        h264_height=720,
        direct_librga_preview=True,
    )
    launch = contract["launch_pipeline"]
    encoder_launch = contract["h264_encoder_pipeline"]

    assert contract["topology"]["h264_webrtc_branch"] is True
    assert contract["topology"]["h264_webrtc_pipeline_branch"] is False
    assert contract["topology"]["h264_webrtc_direct_librga"] is True
    assert "sorter_h264_queue" not in launch
    assert "appsink name=sorter_h264_webrtc" not in launch
    assert encoder_launch is not None
    assert "appsrc name=sorter_h264_appsrc" in encoder_launch
    assert "video/x-raw,format=NV12,width=1280,height=720,framerate=30/1" in encoder_launch
    assert "mpph264enc name=sorter_h264_encoder" in encoder_launch
    assert "appsink name=sorter_h264_webrtc" in encoder_launch
    assert contract["required_gstreamer_elements"]["appsrc"] == "appsrc"
    assert contract["hardware_scale_convert"] is True
    assert contract["hardware_scale_convert_element"] == "librga_virtualaddr"
    assert contract["scale_convert_element"] == "librga_virtualaddr"
    assert contract["profiles"]["preview_webrtc"]["source"] == "direct_librga_scale_to_appsrc_mpp_h264"
    assert contract["profiles"]["preview_webrtc"]["direct_librga"] is True
    assert contract["profiles"]["preview_webrtc"]["pipeline_branch"] is False
    assert contract["profiles"]["preview_webrtc"]["zero_copy_dmabuf"] is False
    h264_branch = next(item for item in contract["branches"] if item["name"] == "h264_webrtc")
    assert h264_branch["source"] == "direct_librga_scale_to_appsrc_mpp_h264"
    assert h264_branch["direct_librga"] is True
    assert h264_branch["pipeline_branch"] is False
    assert h264_branch["scale_convert_element"] == "librga_virtualaddr"


def test_target_capture_contract_can_add_reduced_yolo_detection_branch_with_rga() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        fps=30,
        h264_width=1280,
        h264_height=720,
        detection_width=640,
        detection_height=360,
        elements=GStreamerTargetElements(rga_converter="rkrgaconvert"),
    )
    launch = contract["launch_pipeline"]

    assert contract["topology"]["detection_yolo_branch"] is True
    assert "sorter_capture_tee. ! queue name=sorter_yolo_queue" in launch
    assert "video/x-raw,format=NV12,width=640,height=360" in launch
    assert "appsink name=sorter_yolo_reduced" in launch
    assert contract["profiles"]["detection_yolo"]["source"] == "dedicated_rga_scaled_full_frame_branch"
    assert contract["profiles"]["detection_yolo"]["width"] == 640
    assert contract["profiles"]["detection_yolo"]["sensor_rect"] == [0, 0, 3840, 2160]
    assert contract["profiles"]["detection_yolo"]["hardware_crop"] is False
    assert contract["profiles"]["detection_yolo"]["crop_strategy"]["target_stage"] == (
        "detection_yolo_branch_before_scale"
    )
    assert contract["profiles"]["detection_yolo"]["crop_strategy"]["current_stage"] == (
        "scaled_full_frame_then_perception_crop"
    )
    assert contract["profiles"]["detection_yolo"]["crop_strategy"]["software_videocrop_allowed"] is False
    assert contract["profiles"]["classification_crops"]["width"] == 3840
    assert contract["hardware_crop"] is False
    assert contract["detection_crop_strategy"]["active_media_pipeline_crop"] is False
    detection_branch = next(item for item in contract["branches"] if item["name"] == "detection_yolo")
    assert detection_branch["input_width"] == 3840
    assert detection_branch["output_width"] == 640
    assert detection_branch["hardware_scale_convert"] is True
    assert detection_branch["hardware_crop"] is False
    assert detection_branch["sensor_rect"] == [0, 0, 3840, 2160]
    assert detection_branch["crop_strategy"]["fallback_crop_stage"] == (
        "perception_numpy_slice_after_hardware_scaled_full_frame"
    )


def test_target_capture_contract_can_use_direct_librga_detection_without_pipeline_branch() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        fps=30,
        detection_width=640,
        detection_height=360,
        direct_librga_detection=True,
    )
    launch = contract["launch_pipeline"]

    assert contract["topology"]["detection_yolo_branch"] is True
    assert contract["topology"]["detection_yolo_pipeline_branch"] is False
    assert contract["topology"]["detection_yolo_direct_librga"] is True
    assert "sorter_yolo_queue" not in launch
    assert "appsink name=sorter_yolo_reduced" not in launch
    assert "librga_virtualaddr" not in launch
    assert "rockchip_rga_convert" not in contract["required_gstreamer_elements"]
    assert contract["hardware_scale_convert"] is True
    assert contract["hardware_detection_scale_convert"] is True
    assert contract["hardware_scale_convert_element"] == "librga_virtualaddr"
    assert contract["scale_convert_element"] == "librga_virtualaddr"
    assert contract["software_scale_convert_fallback"] is False
    assert contract["hardware_crop"] is False
    assert contract["hardware_detection_crop"] is False
    assert contract["hardware_detection_crop_capable"] is True
    assert contract["profiles"]["detection_yolo"]["source"] == "direct_librga_scale_from_raw_nv12_sample"
    assert contract["profiles"]["detection_yolo"]["pipeline_branch"] is False
    assert contract["profiles"]["detection_yolo"]["direct_librga"] is True
    assert contract["profiles"]["detection_yolo"]["scale_convert_element"] == "librga_virtualaddr"
    assert contract["profiles"]["detection_yolo"]["sensor_rect"] == [0, 0, 3840, 2160]
    detection_branch = next(item for item in contract["branches"] if item["name"] == "detection_yolo")
    assert detection_branch["sink"] is None
    assert detection_branch["pipeline_branch"] is False
    assert detection_branch["direct_librga"] is True
    assert detection_branch["hardware_crop_capable"] is True
    assert contract["profiles"]["classification_crops"]["width"] == 3840


def test_target_capture_contract_can_describe_direct_librga_detection_crop() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        fps=30,
        detection_width=640,
        detection_height=360,
        direct_librga_detection=True,
        detection_crop_x=960,
        detection_crop_y=540,
        detection_crop_width=1920,
        detection_crop_height=1080,
    )

    assert contract["hardware_crop"] is True
    assert contract["hardware_crop_element"] == "librga_virtualaddr"
    assert contract["profiles"]["detection_yolo"]["source"] == "direct_librga_crop_scale_from_raw_nv12_sample"
    assert contract["profiles"]["detection_yolo"]["sensor_rect"] == [960, 540, 2880, 1620]
    assert contract["profiles"]["detection_yolo"]["sensor_crop_rect"] == {
        "x": 960,
        "y": 540,
        "width": 1920,
        "height": 1080,
    }
    assert contract["detection_crop_strategy"]["current_stage"] == "hardware_crop_before_yolo_scale"
    assert contract["detection_crop_strategy"]["active_media_pipeline_crop"] is True


def test_target_capture_contract_uses_videoconvertscale_as_software_fallback_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SORTER_GSTREAMER_ENABLE_PATCHED_VIDEOCONVERTSCALE_RGA", raising=False)
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=1280,
        height=720,
        fps=30,
        detection_width=640,
        detection_height=360,
        elements=GStreamerTargetElements(rga_converter="videoconvertscale"),
    )
    launch = contract["launch_pipeline"]

    assert "sorter_yolo_queue" in launch
    assert "videoconvertscale ! video/x-raw,format=NV12,width=640,height=360" in launch
    assert "sorter_h264_queue leaky=downstream max-size-buffers=4 max-size-time=0 max-size-bytes=0 ! mpph264enc" in launch
    assert contract["scale_convert_element"] == "videoconvertscale"
    assert contract["software_scale_convert_fallback"] is True
    assert contract["hardware_scale_convert_element"] is None
    assert contract["hardware_scale_convert"] is False
    assert contract["profiles"]["detection_yolo"]["source"] == "dedicated_scaled_full_frame_branch"
    assert contract["profiles"]["detection_yolo"]["scale_convert_element"] == "videoconvertscale"
    assert contract["profiles"]["detection_yolo"]["hardware_scale_convert"] is False
    assert contract["profiles"]["detection_yolo"]["software_scale_convert_fallback"] is True


def test_target_capture_contract_can_opt_into_patched_videoconvertscale_rga(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SORTER_GSTREAMER_ENABLE_PATCHED_VIDEOCONVERTSCALE_RGA", "1")
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=1280,
        height=720,
        fps=30,
        detection_width=640,
        detection_height=360,
        elements=GStreamerTargetElements(rga_converter="videoconvertscale"),
    )

    assert contract["scale_convert_element"] == "videoconvertscale"
    assert contract["software_scale_convert_fallback"] is False
    assert contract["hardware_scale_convert"] is True
    assert contract["hardware_scale_convert_element"] == "videoconvertscale"
    assert contract["profiles"]["detection_yolo"]["source"] == "dedicated_rga_scaled_full_frame_branch"
    assert contract["profiles"]["detection_yolo"]["hardware_scale_convert"] is True


def test_target_capture_contract_rejects_scaled_h264_without_hardware_converter() -> None:
    with pytest.raises(ValueError, match="Scaled H.264 output requires a hardware converter"):
        build_gstreamer_target_capture_contract(
            device_path="/dev/video3",
            width=3840,
            height=2160,
            h264_width=1280,
            h264_height=720,
        )


def test_target_capture_contract_allows_scaled_h264_with_direct_librga_preview() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        h264_width=1280,
        h264_height=720,
        direct_librga_preview=True,
    )

    assert contract["profiles"]["preview_webrtc"]["direct_librga"] is True


def test_target_capture_contract_rejects_reduced_detection_without_hardware_converter() -> None:
    with pytest.raises(ValueError, match="Reduced detection output requires a hardware converter"):
        build_gstreamer_target_capture_contract(
            device_path="/dev/video3",
            width=3840,
            height=2160,
            detection_width=640,
            detection_height=360,
        )


def test_target_capture_contract_allows_reduced_detection_with_direct_librga() -> None:
    contract = build_gstreamer_target_capture_contract(
        device_path="/dev/video3",
        width=3840,
        height=2160,
        detection_width=640,
        detection_height=360,
        direct_librga_detection=True,
    )

    assert contract["profiles"]["detection_yolo"]["direct_librga"] is True


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
