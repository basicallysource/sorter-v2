"""GStreamer/Rockchip target capture pipeline contract.

This module does not start a camera. It describes the capture topology the
SorterOS image and backend must eventually run: one v4l2src owner per physical
camera, a tee into a raw-ring branch, and a hardware H.264 branch for WebRTC.
"""

from __future__ import annotations

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
_RAW_FOURCC_TO_GST = {
    "YUYV": "YUY2",
    "UYVY": "UYVY",
    "NV12": "NV12",
}


@dataclass(frozen=True)
class GStreamerTargetElements:
    v4l2_source: str = "v4l2src"
    queue: str = "queue"
    tee: str = "tee"
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
    raw_sink_name: str = "sorter_raw_ring"
    h264_sink_name: str = "sorter_h264_webrtc"
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
        for role, name in (
            ("raw_sink_name", self.raw_sink_name),
            ("h264_sink_name", self.h264_sink_name),
            ("tee_name", self.tee_name),
        ):
            if not _ELEMENT_NAME_RE.fullmatch(name):
                raise ValueError(f"Invalid {role}: {name!r}")
        self.elements.validate()

    def normalized_fourcc(self) -> str:
        return self.input_fourcc.strip().upper()


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
        ]
        return " ".join(part for part in parts if part)

    def describe(self) -> dict[str, Any]:
        self.config.validate()
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
                "one_encoder_per_physical_source": True,
            },
            "branches": [
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
                    "format": "NV12 to H264 byte-stream access units",
                    "consumer": "webrtc_pre_encoded_packet_track",
                    "hardware_encoder": "rockchip_mpp",
                    "hardware_scale_convert": False,
                },
            ],
            "required_gstreamer_elements": self.config.elements.required_gstreamer_elements(),
            "required_launch_elements": self.config.elements.launch_elements(),
            "required_device_nodes": list(REQUIRED_DEVICE_NODES),
            "zero_copy_dmabuf": True,
            "hardware_decode": self.config.normalized_fourcc() in _MJPEG_FOURCCS,
            "hardware_scale_convert": False,
            "hardware_scale_convert_element": self.config.elements.rga_converter,
            "hardware_color_convert": False,
            "software_h264_fallback_allowed": False,
            "forbidden_elements": sorted(_SOFTWARE_ENCODERS | _SOFTWARE_CONVERTERS | _SOFTWARE_DECODERS),
            "launch_pipeline": self.launch_pipeline(),
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
        converter = f"! {e.rga_converter} " if e.rga_converter else ""
        return (
            f"{self.config.tee_name}. ! {e.queue} name=sorter_raw_queue "
            "leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0 "
            f"{converter}! video/x-raw,format=NV12 "
            f"! {e.appsink} name={self.config.raw_sink_name} "
            "emit-signals=true sync=false max-buffers=2 drop=true"
        )

    def _h264_webrtc_branch(self) -> str:
        e = self.config.elements
        converter = (
            f"! {e.rga_converter} ! video/x-raw,format=NV12 "
            if e.rga_converter
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


def build_gstreamer_target_capture_contract(
    *,
    device_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    input_fourcc: str = "MJPG",
    elements: GStreamerTargetElements | None = None,
) -> dict[str, Any]:
    contract = GStreamerTargetCaptureContract(
        GStreamerTargetCaptureConfig(
            device_path=device_path,
            width=width,
            height=height,
            fps=fps,
            input_fourcc=input_fourcc,
            elements=elements or GStreamerTargetElements(),
        )
    )
    return contract.describe()
