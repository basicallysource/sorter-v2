"""GStreamer/Rockchip target capture pipeline contract.

This module does not start a camera. It describes the capture topology the
SorterOS image and backend must eventually run: one v4l2src owner per physical
camera, a tee into a raw-ring branch, and a hardware H.264 branch for WebRTC.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


TARGET_PIPELINE_NAME = "gstreamer_v4l2_tee_mpp_h264"
REQUIRED_DEVICE_NODES = ("/dev/mpp_service", "/dev/rga", "/dev/dma_heap")

_DEVICE_PATH_RE = re.compile(r"^/dev/video\d+$")
_ELEMENT_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_SOFTWARE_ENCODERS = frozenset({"x264enc", "openh264enc", "avenc_h264", "vaapih264enc"})
_SOFTWARE_CONVERTERS = frozenset({"videoconvert", "videoscale"})
_SOFTWARE_DECODERS = frozenset({"jpegdec", "avdec_mjpeg"})
_MJPEG_FOURCCS = frozenset({"MJPG", "JPEG"})
_YES_VALUES = frozenset({"1", "true", "yes", "on"})
_RAW_FOURCC_TO_GST = {
    "YUYV": "YUY2",
    "UYVY": "UYVY",
    "NV12": "NV12",
}


def patched_videoconvertscale_rga_enabled() -> bool:
    """Whether the downstream-patched videoconvertscale RGA path is opted in.

    The SorterOS Orange Pi image currently has no explicit GStreamer RGA
    transform. The patched videoconvertscale can initialize librga in small
    probes, but the live appsink graph has proven unstable. Treat it as a
    software scale/convert fallback unless the operator deliberately opts in.
    """
    return os.environ.get(
        "SORTER_GSTREAMER_ENABLE_PATCHED_VIDEOCONVERTSCALE_RGA",
        "",
    ).strip().lower() in _YES_VALUES


def scale_converter_uses_hardware(element: str | None) -> bool:
    if not element:
        return False
    if element == "videoconvertscale":
        return patched_videoconvertscale_rga_enabled()
    return True


def target_detection_crop_strategy(
    *,
    active_media_pipeline_crop: bool = False,
    hardware_crop_element: str | None = None,
    hardware_crop_runtime_available: bool | None = None,
    hardware_crop_runtime_path: str | None = None,
) -> dict[str, Any]:
    active = bool(active_media_pipeline_crop)
    if active:
        reason = (
            "The active detection branch crops the channel-mask bounding rect "
            "inside the hardware source graph before YOLO scaling."
        )
        current_stage = "hardware_crop_before_yolo_scale"
    elif hardware_crop_runtime_available:
        reason = (
            "Rockchip RGA crop is runtime-proven through FFmpeg vpp_rkrga, "
            "but the active GStreamer single-capture source graph has no "
            "proven RGA crop element. GStreamer videocrop is intentionally "
            "not used because it is a software filter."
        )
        current_stage = "scaled_full_frame_then_perception_crop"
    else:
        reason = (
            "The active detection branch scales the full sensor frame for "
            "YOLO; perception applies the channel-mask crop after the reduced "
            "frame reaches appsink/RKNN preprocessing."
        )
        current_stage = "scaled_full_frame_then_perception_crop"
    return {
        "target_stage": "detection_yolo_branch_before_scale",
        "requested_by": "perception_channel_mask_bounding_rect",
        "coordinate_space": "sensor_frame",
        "current_stage": current_stage,
        "active_media_pipeline_crop": active,
        "hardware_crop_element": hardware_crop_element if active else None,
        "hardware_crop_runtime_available": hardware_crop_runtime_available,
        "hardware_crop_runtime_path": hardware_crop_runtime_path,
        "software_videocrop_allowed": False,
        "fallback_crop_stage": "perception_numpy_slice_after_hardware_scaled_full_frame",
        "reason": reason,
    }


@dataclass(frozen=True)
class GStreamerTargetElements:
    v4l2_source: str = "v4l2src"
    queue: str = "queue"
    tee: str = "tee"
    appsrc: str = "appsrc"
    appsink: str = "appsink"
    jpeg_parser: str = "jpegparse"
    jpeg_decoder: str = "mppjpegdec"
    rga_converter: str | None = None
    h264_encoder: str = "mpph264enc"
    h264_parser: str = "h264parse"

    def validate(self) -> None:
        names = self.launch_elements()
        for role, element in names.items():
            if not _ELEMENT_NAME_RE.fullmatch(element):
                raise ValueError(f"Invalid GStreamer element for {role}: {element!r}")

        if self.h264_encoder in _SOFTWARE_ENCODERS:
            raise ValueError(f"Software H.264 encoder is forbidden: {self.h264_encoder}")
        if self.rga_converter in _SOFTWARE_CONVERTERS:
            raise ValueError(f"Software scale/convert element is forbidden: {self.rga_converter}")
        if self.jpeg_decoder in _SOFTWARE_DECODERS:
            raise ValueError(f"Software JPEG decoder is forbidden: {self.jpeg_decoder}")

    def launch_elements(self) -> dict[str, str]:
        elements = {
            "v4l2src": self.v4l2_source,
            "queue": self.queue,
            "tee": self.tee,
            "appsrc": self.appsrc,
            "appsink": self.appsink,
            "jpegparse": self.jpeg_parser,
            "mppjpegdec": self.jpeg_decoder,
            "rockchip_mpp_h264_encoder": self.h264_encoder,
            "h264parse": self.h264_parser,
        }
        if self.rga_converter:
            elements["rockchip_rga_convert"] = self.rga_converter
        return elements

    def required_gstreamer_elements(self) -> dict[str, str]:
        elements = {
            "v4l2src": self.v4l2_source,
            "appsink": self.appsink,
            "jpegparse": self.jpeg_parser,
            "mppjpegdec": self.jpeg_decoder,
            "rockchip_mpp_h264_encoder": self.h264_encoder,
            "h264parse": self.h264_parser,
        }
        if self.rga_converter:
            elements["rockchip_rga_convert"] = self.rga_converter
        return elements


@dataclass(frozen=True)
class GStreamerTargetCaptureConfig:
    device_path: str
    width: int = 1280
    height: int = 720
    fps: int = 30
    input_fourcc: str = "MJPG"
    h264_width: int | None = None
    h264_height: int | None = None
    direct_librga_preview: bool = False
    detection_width: int | None = None
    detection_height: int | None = None
    direct_librga_detection: bool = False
    detection_crop_x: int | None = None
    detection_crop_y: int | None = None
    detection_crop_width: int | None = None
    detection_crop_height: int | None = None
    raw_sink_name: str = "sorter_raw_ring"
    h264_sink_name: str = "sorter_h264_webrtc"
    detection_sink_name: str = "sorter_yolo_reduced"
    tee_name: str = "sorter_capture_tee"
    elements: GStreamerTargetElements = field(default_factory=GStreamerTargetElements)

    def validate(self) -> None:
        if not _DEVICE_PATH_RE.fullmatch(self.device_path):
            raise ValueError(f"Target capture device must be a concrete /dev/videoN path: {self.device_path!r}")
        for name, value in (
            ("width", self.width),
            ("height", self.height),
            ("fps", self.fps),
        ):
            if int(value) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.normalized_fourcc() not in _MJPEG_FOURCCS | frozenset(_RAW_FOURCC_TO_GST):
            raise ValueError(f"Unsupported target input fourcc: {self.input_fourcc!r}")
        if self.normalized_fourcc() in _RAW_FOURCC_TO_GST and not self.elements.rga_converter:
            raise ValueError("Raw target input fourcc requires a hardware converter element")
        h264_width, h264_height = self.h264_output_dimensions()
        if (
            (h264_width != int(self.width) or h264_height != int(self.height))
            and not self.direct_librga_preview
            and not self.elements.rga_converter
        ):
            raise ValueError("Scaled H.264 output requires a hardware converter element")
        if self.direct_librga_preview and (
            h264_width == int(self.width) and h264_height == int(self.height)
        ):
            raise ValueError("Direct librga preview requires scaled H.264 output dimensions")
        detection_dimensions = self.detection_output_dimensions()
        if (
            detection_dimensions is not None
            and not self.direct_librga_detection
            and not self.elements.rga_converter
        ):
            raise ValueError("Reduced detection output requires a hardware converter element")
        if self.direct_librga_detection and detection_dimensions is None:
            raise ValueError("Direct librga detection requires detection output dimensions")
        self.detection_crop_rect()
        for role, name in (
            ("raw_sink_name", self.raw_sink_name),
            ("h264_sink_name", self.h264_sink_name),
            ("detection_sink_name", self.detection_sink_name),
            ("tee_name", self.tee_name),
        ):
            if not _ELEMENT_NAME_RE.fullmatch(name):
                raise ValueError(f"Invalid {role}: {name!r}")
        self.elements.validate()

    def normalized_fourcc(self) -> str:
        return self.input_fourcc.strip().upper()

    def h264_output_dimensions(self) -> tuple[int, int]:
        width = int(self.h264_width) if isinstance(self.h264_width, int) and self.h264_width > 0 else int(self.width)
        height = (
            int(self.h264_height)
            if isinstance(self.h264_height, int) and self.h264_height > 0
            else int(self.height)
        )
        if width <= 0 or height <= 0:
            raise ValueError("H.264 output dimensions must be positive")
        return width, height

    def scale_converter_uses_hardware(self) -> bool:
        return scale_converter_uses_hardware(self.elements.rga_converter)

    def h264_branch_needs_scale_converter(self) -> bool:
        h264_width, h264_height = self.h264_output_dimensions()
        return bool(
            self.elements.rga_converter
            and not self.direct_librga_preview
            and (h264_width != int(self.width) or h264_height != int(self.height))
        )

    def h264_branch_uses_hardware_scale(self) -> bool:
        if self.h264_branch_uses_direct_librga():
            h264_width, h264_height = self.h264_output_dimensions()
            return bool(h264_width != int(self.width) or h264_height != int(self.height))
        return bool(
            self.h264_branch_needs_scale_converter()
            and self.scale_converter_uses_hardware()
        )

    def h264_pipeline_branch_enabled(self) -> bool:
        return not self.direct_librga_preview

    def h264_branch_uses_direct_librga(self) -> bool:
        return bool(self.direct_librga_preview)

    def detection_output_dimensions(self) -> tuple[int, int] | None:
        if self.detection_width is None and self.detection_height is None:
            return None
        width = (
            int(self.detection_width)
            if isinstance(self.detection_width, int) and self.detection_width > 0
            else int(self.width)
        )
        height = (
            int(self.detection_height)
            if isinstance(self.detection_height, int) and self.detection_height > 0
            else int(self.height)
        )
        if width <= 0 or height <= 0:
            raise ValueError("Detection output dimensions must be positive")
        return width, height

    def detection_branch_enabled(self) -> bool:
        return self.detection_output_dimensions() is not None

    def detection_pipeline_branch_enabled(self) -> bool:
        return bool(self.detection_branch_enabled() and not self.direct_librga_detection)

    def detection_branch_uses_direct_librga(self) -> bool:
        return bool(self.detection_branch_enabled() and self.direct_librga_detection)

    def detection_crop_rect(self) -> tuple[int, int, int, int] | None:
        if not self.detection_branch_enabled():
            return None
        values = (
            self.detection_crop_x,
            self.detection_crop_y,
            self.detection_crop_width,
            self.detection_crop_height,
        )
        if all(value is None for value in values):
            return (0, 0, int(self.width), int(self.height))
        if any(value is None for value in values):
            raise ValueError("Detection crop rectangle must be complete when configured")
        x, y, width, height = (int(value) for value in values if value is not None)
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("Detection crop rectangle must be positive and inside the source frame")
        if x + width > int(self.width) or y + height > int(self.height):
            raise ValueError("Detection crop rectangle must be inside the source frame")
        if (x | y | width | height) & 1:
            raise ValueError("Detection crop rectangle must use even NV12 coordinates and dimensions")
        return (x, y, width, height)

    def detection_sensor_rect(self) -> tuple[int, int, int, int] | None:
        rect = self.detection_crop_rect()
        if rect is None:
            return None
        x, y, width, height = rect
        return (x, y, x + width, y + height)

    def detection_branch_has_active_crop(self) -> bool:
        rect = self.detection_crop_rect()
        return bool(rect is not None and rect != (0, 0, int(self.width), int(self.height)))

    def detection_branch_needs_scale_converter(self) -> bool:
        dimensions = self.detection_output_dimensions()
        return bool(
            dimensions is not None
            and not self.direct_librga_detection
            and self.elements.rga_converter
            and (dimensions[0] != int(self.width) or dimensions[1] != int(self.height))
        )

    def detection_branch_uses_hardware_scale(self) -> bool:
        if self.detection_branch_uses_direct_librga():
            dimensions = self.detection_output_dimensions()
            rect = self.detection_crop_rect()
            return bool(
                dimensions is not None
                and rect is not None
                and (dimensions[0] != rect[2] or dimensions[1] != rect[3])
            )
        return bool(
            self.detection_branch_needs_scale_converter()
            and self.scale_converter_uses_hardware()
        )


@dataclass(frozen=True)
class GStreamerTargetCaptureContract:
    config: GStreamerTargetCaptureConfig

    def launch_pipeline(self) -> str:
        self.config.validate()
        e = self.config.elements
        parts = [
            self._capture_head(),
            f"{e.tee} name={self.config.tee_name}",
            self._raw_ring_branch(),
            self._h264_webrtc_branch(),
            self._detection_yolo_branch(),
        ]
        return " ".join(part for part in parts if part)

    def describe(self) -> dict[str, Any]:
        self.config.validate()
        direct_librga_detection = self.config.detection_branch_uses_direct_librga()
        detection_active_crop = self.config.detection_branch_has_active_crop()
        detection_crop_strategy = target_detection_crop_strategy(
            active_media_pipeline_crop=bool(direct_librga_detection and detection_active_crop),
            hardware_crop_element="librga_virtualaddr" if direct_librga_detection else None,
            hardware_crop_runtime_available=True if direct_librga_detection else None,
            hardware_crop_runtime_path="librga_virtualaddr" if direct_librga_detection else None,
        )
        h264_needs_scale_converter = self.config.h264_branch_needs_scale_converter()
        detection_needs_scale_converter = self.config.detection_branch_needs_scale_converter()
        h264_hardware_scale = self.config.h264_branch_uses_hardware_scale()
        direct_librga_preview = self.config.h264_branch_uses_direct_librga()
        detection_hardware_scale = self.config.detection_branch_uses_hardware_scale()
        hardware_scale_convert = bool(h264_hardware_scale or detection_hardware_scale)
        scaled_by_configured_converter = bool(h264_needs_scale_converter or detection_needs_scale_converter)
        software_scale_convert_fallback = bool(
            scaled_by_configured_converter
            and self.config.elements.rga_converter
            and not self.config.scale_converter_uses_hardware()
        )
        hardware_scale_convert_element = (
            self.config.elements.rga_converter
            if (
                (h264_hardware_scale and not direct_librga_preview)
                or (detection_hardware_scale and not direct_librga_detection)
            )
            else "librga_virtualaddr"
            if (direct_librga_preview and h264_hardware_scale)
            or (direct_librga_detection and detection_hardware_scale)
            else None
        )
        scale_convert_element = (
            "librga_virtualaddr"
            if (
                (direct_librga_preview and h264_hardware_scale)
                or (direct_librga_detection and detection_hardware_scale)
            )
            and not scaled_by_configured_converter
            else self.config.elements.rga_converter
            if scaled_by_configured_converter
            else None
        )
        required_gstreamer_elements = self.config.elements.required_gstreamer_elements()
        if direct_librga_preview:
            required_gstreamer_elements["appsrc"] = self.config.elements.appsrc
        branches = [
            {
                "name": "raw_ring",
                "sink": self.config.raw_sink_name,
                "format": "NV12 appsink converted to BGR CameraFrame",
                "consumer": "backend_raw_ring_calibration_detection",
                "hardware_scale_convert": False,
            },
            {
                "name": "h264_webrtc",
                "sink": self.config.h264_sink_name,
                "format": (
                    "raw NV12 appsink scale by direct librga to appsrc, then MPP H264 byte-stream access units"
                    if direct_librga_preview
                    else "NV12 to H264 byte-stream access units"
                ),
                "consumer": "webrtc_pre_encoded_packet_track",
                "hardware_encoder": "rockchip_mpp",
                "source": (
                    "direct_librga_scale_to_appsrc_mpp_h264"
                    if direct_librga_preview
                    else "gstreamer_pipeline_h264_branch"
                ),
                "pipeline_branch": not direct_librga_preview,
                "direct_librga": direct_librga_preview,
                "input_width": self.config.width,
                "input_height": self.config.height,
                "output_width": self.config.h264_output_dimensions()[0],
                "output_height": self.config.h264_output_dimensions()[1],
                "scale_convert_element": (
                    "librga_virtualaddr"
                    if direct_librga_preview
                    else self.config.elements.rga_converter
                    if h264_needs_scale_converter
                    else None
                ),
                "hardware_scale_convert": h264_hardware_scale,
                "software_scale_convert_fallback": bool(
                    h264_needs_scale_converter and software_scale_convert_fallback
                ),
                "zero_copy_dmabuf": False if direct_librga_preview else True,
            },
        ]
        detection_dimensions = self.config.detection_output_dimensions()
        detection_crop_rect = self.config.detection_crop_rect()
        if detection_dimensions is not None:
            branches.append(
                {
                    "name": "detection_yolo",
                    "sink": None if direct_librga_detection else self.config.detection_sink_name,
                    "format": (
                        "raw NV12 appsink crop-scaled by direct librga then converted to BGR PerceptionFrame inference image"
                        if direct_librga_detection
                        else "reduced NV12 appsink converted to BGR PerceptionFrame inference image"
                    ),
                    "consumer": "perception_yolo_reduced_input",
                    "source": (
                        "direct_librga_crop_scale_from_raw_nv12_sample"
                        if direct_librga_detection and detection_active_crop
                        else "direct_librga_scale_from_raw_nv12_sample"
                        if direct_librga_detection
                        else "gstreamer_pipeline_scaled_full_frame_branch"
                    ),
                    "pipeline_branch": not direct_librga_detection,
                    "direct_librga": direct_librga_detection,
                    "input_width": self.config.width,
                    "input_height": self.config.height,
                    "output_width": detection_dimensions[0],
                    "output_height": detection_dimensions[1],
                    "scale_convert_element": (
                        "librga_virtualaddr"
                        if direct_librga_detection and detection_hardware_scale
                        else self.config.elements.rga_converter
                        if detection_needs_scale_converter
                        else None
                    ),
                    "hardware_scale_convert": detection_hardware_scale,
                    "software_scale_convert_fallback": bool(
                        detection_needs_scale_converter and software_scale_convert_fallback
                    ),
                    "hardware_crop": bool(direct_librga_detection and detection_active_crop),
                    "hardware_crop_capable": bool(direct_librga_detection),
                    "hardware_crop_element": (
                        "librga_virtualaddr"
                        if direct_librga_detection and detection_active_crop
                        else None
                    ),
                    "sensor_rect": list(self.config.detection_sensor_rect() or (0, 0, self.config.width, self.config.height)),
                    "sensor_crop_rect": {
                        "x": int((detection_crop_rect or (0, 0, self.config.width, self.config.height))[0]),
                        "y": int((detection_crop_rect or (0, 0, self.config.width, self.config.height))[1]),
                        "width": int((detection_crop_rect or (0, 0, self.config.width, self.config.height))[2]),
                        "height": int((detection_crop_rect or (0, 0, self.config.width, self.config.height))[3]),
                    },
                    "crop_strategy": detection_crop_strategy,
                }
            )
        return {
            "name": TARGET_PIPELINE_NAME,
            "implementation": TARGET_PIPELINE_NAME,
            "device_path": self.config.device_path,
            "capture": {
                "width": self.config.width,
                "height": self.config.height,
                "fps": self.config.fps,
                "input_fourcc": self.config.normalized_fourcc(),
                "io_mode": "dmabuf",
                "opens_capture_device": True,
            },
            "topology": {
                "single_capture_pipeline": True,
                "capture_owner": "v4l2src",
                "tee": self.config.tee_name,
                "raw_ring_branch": True,
                "h264_webrtc_branch": True,
                "h264_webrtc_pipeline_branch": self.config.h264_pipeline_branch_enabled(),
                "h264_webrtc_direct_librga": direct_librga_preview,
                "detection_yolo_branch": self.config.detection_branch_enabled(),
                "detection_yolo_pipeline_branch": self.config.detection_pipeline_branch_enabled(),
                "detection_yolo_direct_librga": direct_librga_detection,
                "one_encoder_per_physical_source": True,
            },
            "branches": branches,
            "required_gstreamer_elements": required_gstreamer_elements,
            "required_launch_elements": self.config.elements.launch_elements(),
            "required_device_nodes": list(REQUIRED_DEVICE_NODES),
            "zero_copy_dmabuf": True,
            "hardware_decode": self.config.normalized_fourcc() in _MJPEG_FOURCCS,
            "hardware_scale_convert": hardware_scale_convert,
            "hardware_scale_convert_element": hardware_scale_convert_element,
            "scale_convert_element": scale_convert_element,
            "software_scale_convert_fallback": software_scale_convert_fallback,
            "hardware_detection_scale_convert": detection_hardware_scale,
            "hardware_detection_crop": bool(direct_librga_detection and detection_active_crop),
            "hardware_detection_crop_capable": bool(direct_librga_detection),
            "hardware_crop": bool(direct_librga_detection and detection_active_crop),
            "hardware_crop_element": (
                "librga_virtualaddr"
                if direct_librga_detection and detection_active_crop
                else None
            ),
            "detection_crop_strategy": detection_crop_strategy,
            "hardware_color_convert": False,
            "software_h264_fallback_allowed": False,
            "profiles": {
                "capture": {
                    "width": self.config.width,
                    "height": self.config.height,
                    "fps": self.config.fps,
                    "purpose": "sensor_acquisition_and_high_res_classification_crops",
                },
                "preview_webrtc": {
                    "width": self.config.h264_output_dimensions()[0],
                    "height": self.config.h264_output_dimensions()[1],
                    "fps": self.config.fps,
                    "purpose": "frontend_preview_transport",
                    "source": (
                        "direct_librga_scale_to_appsrc_mpp_h264"
                        if direct_librga_preview
                        else "gstreamer_pipeline_h264_branch"
                    ),
                    "pipeline_branch": not direct_librga_preview,
                    "direct_librga": direct_librga_preview,
                    "hardware_h264_encode": True,
                    "scale_convert_element": (
                        "librga_virtualaddr"
                        if direct_librga_preview
                        else self.config.elements.rga_converter
                        if h264_needs_scale_converter
                        else None
                    ),
                    "hardware_scale_convert": h264_hardware_scale,
                    "software_scale_convert_fallback": bool(
                        h264_needs_scale_converter and software_scale_convert_fallback
                    ),
                    "zero_copy_dmabuf": False if direct_librga_preview else True,
                },
                "detection_yolo": {
                    "purpose": "reduced_model_input_before_inference",
                    "source": (
                        "direct_librga_crop_scale_from_raw_nv12_sample"
                        if direct_librga_detection and detection_active_crop
                        else "direct_librga_scale_from_raw_nv12_sample"
                        if direct_librga_detection
                        else
                        "dedicated_rga_scaled_full_frame_branch"
                        if detection_dimensions is not None and detection_hardware_scale
                        else "dedicated_scaled_full_frame_branch"
                        if detection_dimensions is not None
                        else "raw_ring_crop_until_dedicated_rga_detection_branch_exists"
                    ),
                    "pipeline_branch": bool(
                        detection_dimensions is not None and not direct_librga_detection
                    ),
                    "direct_librga": direct_librga_detection,
                    "width": detection_dimensions[0] if detection_dimensions is not None else None,
                    "height": detection_dimensions[1] if detection_dimensions is not None else None,
                    "scale_convert_element": (
                        "librga_virtualaddr"
                        if direct_librga_detection and detection_hardware_scale
                        else self.config.elements.rga_converter
                        if detection_needs_scale_converter
                        else None
                    ),
                    "hardware_scale_convert": detection_hardware_scale,
                    "software_scale_convert_fallback": bool(
                        detection_needs_scale_converter and software_scale_convert_fallback
                    ),
                    "hardware_crop": bool(direct_librga_detection and detection_active_crop),
                    "hardware_crop_capable": bool(direct_librga_detection),
                    "hardware_crop_element": (
                        "librga_virtualaddr"
                        if direct_librga_detection and detection_active_crop
                        else None
                    ),
                    "sensor_rect": list(self.config.detection_sensor_rect())
                    if detection_dimensions is not None
                    else None,
                    "sensor_crop_rect": {
                        "x": int(detection_crop_rect[0]),
                        "y": int(detection_crop_rect[1]),
                        "width": int(detection_crop_rect[2]),
                        "height": int(detection_crop_rect[3]),
                    }
                    if detection_dimensions is not None and detection_crop_rect is not None
                    else None,
                    "crop_strategy": detection_crop_strategy,
                },
                "classification_crops": {
                    "width": self.config.width,
                    "height": self.config.height,
                    "purpose": "high_res_crop_material",
                },
            },
            "forbidden_elements": sorted(_SOFTWARE_ENCODERS | _SOFTWARE_CONVERTERS | _SOFTWARE_DECODERS),
            "launch_pipeline": self.launch_pipeline(),
            "h264_encoder_pipeline": self.h264_encoder_pipeline(),
        }

    def _capture_head(self) -> str:
        e = self.config.elements
        head = (
            f"{e.v4l2_source} name=sorter_v4l2src "
            f"device={self.config.device_path} io-mode=dmabuf do-timestamp=true "
            f"! {self._capture_caps()}"
        )
        if self.config.normalized_fourcc() in _MJPEG_FOURCCS:
            return f"{head} ! {e.jpeg_parser} ! {e.jpeg_decoder} format=NV12 !"
        return f"{head} !"

    def _capture_caps(self) -> str:
        fourcc = self.config.normalized_fourcc()
        if fourcc in _MJPEG_FOURCCS:
            return (
                f"image/jpeg,width={self.config.width},height={self.config.height},"
                f"framerate={self.config.fps}/1"
            )
        gst_format = _RAW_FOURCC_TO_GST[fourcc]
        return (
            f"video/x-raw,format={gst_format},width={self.config.width},"
            f"height={self.config.height},framerate={self.config.fps}/1"
        )

    def _raw_ring_branch(self) -> str:
        e = self.config.elements
        needs_converter = self.config.normalized_fourcc() in _RAW_FOURCC_TO_GST
        converter = f"! {e.rga_converter} " if needs_converter and e.rga_converter else ""
        return (
            f"{self.config.tee_name}. ! {e.queue} name=sorter_raw_queue "
            "leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0 "
            f"{converter}! video/x-raw,format=NV12 "
            f"! {e.appsink} name={self.config.raw_sink_name} "
            "emit-signals=true sync=false max-buffers=2 drop=true"
        )

    def _h264_webrtc_branch(self) -> str:
        if self.config.h264_branch_uses_direct_librga():
            return ""
        e = self.config.elements
        h264_width, h264_height = self.config.h264_output_dimensions()
        needs_converter = (
            self.config.h264_branch_needs_scale_converter()
            or self.config.normalized_fourcc() in _RAW_FOURCC_TO_GST
        )
        converter = (
            f"! {e.rga_converter} ! video/x-raw,format=NV12,width={h264_width},height={h264_height} "
            if needs_converter and e.rga_converter
            else ""
        )
        return (
            f"{self.config.tee_name}. ! {e.queue} name=sorter_h264_queue "
            "leaky=downstream max-size-buffers=4 max-size-time=0 max-size-bytes=0 "
            f"{converter}"
            f"! {e.h264_encoder} name=sorter_h264_encoder "
            f"! {e.h264_parser} config-interval=-1 "
            "! video/x-h264,stream-format=byte-stream,alignment=au "
            f"! {e.appsink} name={self.config.h264_sink_name} "
            "emit-signals=true sync=false max-buffers=90 drop=true"
        )

    def h264_encoder_pipeline(self) -> str | None:
        if not self.config.h264_branch_uses_direct_librga():
            return None
        e = self.config.elements
        h264_width, h264_height = self.config.h264_output_dimensions()
        return (
            f"{e.appsrc} name=sorter_h264_appsrc is-live=true do-timestamp=false format=time "
            f"block=false max-buffers=2 "
            f"caps=video/x-raw,format=NV12,width={h264_width},height={h264_height},framerate={self.config.fps}/1 "
            f"! {e.queue} name=sorter_h264_appsrc_queue "
            "leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0 "
            f"! {e.h264_encoder} name=sorter_h264_encoder "
            f"! {e.h264_parser} config-interval=-1 "
            "! video/x-h264,stream-format=byte-stream,alignment=au "
            f"! {e.appsink} name={self.config.h264_sink_name} "
            "emit-signals=true sync=false max-buffers=90 drop=true"
        )

    def _detection_yolo_branch(self) -> str:
        e = self.config.elements
        dimensions = self.config.detection_output_dimensions()
        if dimensions is None or self.config.detection_branch_uses_direct_librga():
            return ""
        detection_width, detection_height = dimensions
        return (
            f"{self.config.tee_name}. ! {e.queue} name=sorter_yolo_queue "
            "leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0 "
            f"! {e.rga_converter} "
            f"! video/x-raw,format=NV12,width={detection_width},height={detection_height} "
            f"! {e.appsink} name={self.config.detection_sink_name} "
            "emit-signals=true sync=false max-buffers=2 drop=true"
        )


def build_gstreamer_target_capture_contract(
    *,
    device_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    input_fourcc: str = "MJPG",
    h264_width: int | None = None,
    h264_height: int | None = None,
    direct_librga_preview: bool = False,
    detection_width: int | None = None,
    detection_height: int | None = None,
    direct_librga_detection: bool = False,
    detection_crop_x: int | None = None,
    detection_crop_y: int | None = None,
    detection_crop_width: int | None = None,
    detection_crop_height: int | None = None,
    elements: GStreamerTargetElements | None = None,
) -> dict[str, Any]:
    contract = GStreamerTargetCaptureContract(
        GStreamerTargetCaptureConfig(
            device_path=device_path,
            width=width,
            height=height,
            fps=fps,
            input_fourcc=input_fourcc,
            h264_width=h264_width,
            h264_height=h264_height,
            direct_librga_preview=direct_librga_preview,
            detection_width=detection_width,
            detection_height=detection_height,
            direct_librga_detection=direct_librga_detection,
            detection_crop_x=detection_crop_x,
            detection_crop_y=detection_crop_y,
            detection_crop_width=detection_crop_width,
            detection_crop_height=detection_crop_height,
            elements=elements or GStreamerTargetElements(),
        )
    )
    return contract.describe()
