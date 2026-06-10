import logging
import asyncio
import os
import re
import subprocess
import threading
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
import platform
import cv2
import numpy as np

log = logging.getLogger(__name__)

# One-shot flag so we log only the *first* time a non-identity picture path
# runs in a given process. Lets ops grep journalctl for this string.
_PICTURE_NONIDENTITY_LOGGED = False

from irl.config import (
    CameraConfig,
    CameraPictureSettings,
    cameraDeviceSettingsToDict,
    clampCameraPictureSettings,
    parseCameraDeviceSettings,
)
from .types import CameraFrame

CAPTURE_MODE_SETTLE_S = 2.0
CAPTURE_EXPECTED_FRAME_FALLBACK_S = 10.0
AUTO_CAMERA_CONTROL_KEYS = ("auto_exposure", "auto_white_balance", "autofocus")
GSTREAMER_H264_PREVIEW_MAX_WIDTH = 1280
GSTREAMER_H264_PREVIEW_MAX_HEIGHT = 720
GSTREAMER_YOLO_DETECTION_MAX_WIDTH = 640
GSTREAMER_YOLO_DETECTION_MAX_HEIGHT = 360

if platform.system() == "Darwin":
    try:
        from hardware.macos_uvc_controls import (
            apply_controls_for_index as _apply_macos_uvc_controls_for_index,
            describe_controls_for_index as _describe_macos_uvc_controls_for_index,
        )
        from hardware.macos_camera_registry import refresh_macos_cameras as _refresh_macos_cameras
    except Exception:
        _apply_macos_uvc_controls_for_index = None
        _describe_macos_uvc_controls_for_index = None
        _refresh_macos_cameras = None
else:
    _apply_macos_uvc_controls_for_index = None
    _describe_macos_uvc_controls_for_index = None
    _refresh_macos_cameras = None


def _linux_video_index_from_path(path: Path) -> int | None:
    name = path.name
    if not name.startswith("video"):
        return None
    suffix = name[len("video") :]
    return int(suffix) if suffix.isdigit() else None


def _linux_index0_video_indices() -> list[int]:
    by_path = Path("/dev/v4l/by-path")
    if not by_path.exists():
        return []
    indices: list[int] = []
    seen: set[int] = set()
    for link in sorted(by_path.glob("*video-index0")):
        try:
            index = _linux_video_index_from_path(link.resolve(strict=False))
        except Exception:
            index = None
        if index is None or index in seen:
            continue
        seen.add(index)
        indices.append(index)
    return indices


# Serializes GStreamer/UVC pipeline bring-up across CaptureThreads and keeps a
# minimum gap between consecutive starts. Starting multiple UVC streams in the
# same instant can wedge the RK3588 vendor kernel's USB host controller.
_CAPTURE_START_LOCK = threading.Lock()
_CAPTURE_START_MIN_GAP_S = 2.0
_capture_last_start_monotonic = 0.0


class _gstreamer_capture_start_gate:
    # Best-effort serialization: if a bring-up wedges in an uninterruptible
    # kernel call (a dying UVC device can do that), the gate must not starve
    # every other camera forever — fall through after a bounded wait.
    _ACQUIRE_TIMEOUT_S = 30.0

    def __init__(self) -> None:
        self._acquired = False

    def __enter__(self):
        global _capture_last_start_monotonic
        self._acquired = _CAPTURE_START_LOCK.acquire(timeout=self._ACQUIRE_TIMEOUT_S)
        if not self._acquired:
            log.warning(
                "capture start gate held for >%.0fs (wedged bring-up?) — proceeding unserialized",
                self._ACQUIRE_TIMEOUT_S,
            )
            return self
        wait = _capture_last_start_monotonic + _CAPTURE_START_MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        return self

    def __exit__(self, *exc):
        global _capture_last_start_monotonic
        _capture_last_start_monotonic = time.monotonic()
        if self._acquired:
            _CAPTURE_START_LOCK.release()
        return False


def _resolve_linux_video_index(source: int) -> int | None:
    if source >= 0 and source % 2 == 0:
        index0_nodes = _linux_index0_video_indices()
        slot = source // 2
        if 0 <= slot < len(index0_nodes):
            return index0_nodes[slot]
    if Path(f"/dev/video{source}").exists():
        return source
    return None


def _linux_video_device_path(source: int) -> Path:
    resolved = _resolve_linux_video_index(source)
    return Path(f"/dev/video{resolved if resolved is not None else source}")


def _try_v4l2ctl_set_format(source: int, fourcc: str, width: int | None, height: int | None) -> bool:
    # Some cameras (e.g. Innomaker U30CAM) ignore OpenCV's CAP_V4L2 FOURCC
    # param and stay at their firmware default (often YUYV full-res), saturating
    # shared USB 2.0 bandwidth. Force the format at the kernel level while the
    # device is still closed so OpenCV inherits it on open.
    fmt_arg = f"pixelformat={fourcc}"
    if isinstance(width, int) and width > 0:
        fmt_arg += f",width={width}"
    if isinstance(height, int) and height > 0:
        fmt_arg += f",height={height}"
    try:
        device_path = _linux_video_device_path(source)
        result = subprocess.run(
            ["v4l2-ctl", "-d", str(device_path), f"--set-fmt-video={fmt_arg}"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _try_v4l2ctl_get_format(source: int) -> tuple[int | None, int | None, str | None]:
    try:
        device_path = _linux_video_device_path(source)
        result = subprocess.run(
            ["v4l2-ctl", "-d", str(device_path), "--get-fmt-video"],
            capture_output=True,
            timeout=3,
            text=True,
        )
    except Exception:
        return None, None, None
    if result.returncode != 0:
        return None, None, None
    text = result.stdout
    width: int | None = None
    height: int | None = None
    fourcc: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Width/Height"):
            _, _, raw = stripped.partition(":")
            left, _, right = raw.strip().partition("/")
            try:
                width = int(left.strip())
                height = int(right.strip())
            except Exception:
                pass
        elif stripped.startswith("Pixel Format"):
            _, _, raw = stripped.partition(":")
            raw = raw.strip()
            if raw.startswith("'") and "'" in raw[1:]:
                fourcc = raw.split("'", 2)[1]
    return width, height, fourcc


@lru_cache(maxsize=1)
def _gstreamer_rga_converter_element() -> str | None:
    if platform.system() != "Linux":
        return None
    for name in ("rgaconvert", "rkrgaconvert", "rkvideoconvert"):
        try:
            result = subprocess.run(
                ["gst-inspect-1.0", name],
                capture_output=True,
                timeout=2,
            )
        except Exception:
            continue
        if result.returncode == 0:
            return name
    if os.environ.get("GST_VIDEO_CONVERT_USE_RGA", "").strip().lower() in {"0", "false", "no", "off"}:
        return None
    try:
        env = {**os.environ, "GST_VIDEO_CONVERT_USE_RGA": "1"}
        result = subprocess.run(
            [
                "gst-launch-1.0",
                "-q",
                "videotestsrc",
                "num-buffers=1",
                "!",
                "video/x-raw,format=NV12,width=64,height=64,framerate=1/1",
                "!",
                "videoconvertscale",
                "!",
                "video/x-raw,format=NV12,width=32,height=32",
                "!",
                "fakesink",
                "sync=false",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            env=env,
        )
    except Exception:
        return None
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode == 0 and "rga_api" in output.lower():
        return "videoconvertscale"
    return None


@lru_cache(maxsize=1)
def _direct_librga_detection_available() -> bool:
    if platform.system() != "Linux":
        return False
    if os.environ.get("SORTER_DISABLE_DIRECT_LIBRGA_DETECTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    try:
        from .librga_nv12 import DirectLibrgaNv12Scaler

        return DirectLibrgaNv12Scaler.available()
    except Exception:
        return False


def _bounded_h264_preview_dimensions(
    width: int,
    height: int,
    *,
    max_width: int = GSTREAMER_H264_PREVIEW_MAX_WIDTH,
    max_height: int = GSTREAMER_H264_PREVIEW_MAX_HEIGHT,
) -> tuple[int, int]:
    width = max(1, int(width))
    height = max(1, int(height))
    max_width = max(1, int(max_width))
    max_height = max(1, int(max_height))
    if width <= max_width and height <= max_height:
        return width, height
    scale = min(max_width / float(width), max_height / float(height))
    out_w = max(2, int(round(width * scale)))
    out_h = max(2, int(round(height * scale)))
    # Chroma-subsampled NV12/H.264 paths are happiest with even dimensions.
    return out_w - (out_w % 2), out_h - (out_h % 2)


def _bounded_yolo_detection_dimensions(width: int, height: int) -> tuple[int, int]:
    return _bounded_h264_preview_dimensions(
        width,
        height,
        max_width=GSTREAMER_YOLO_DETECTION_MAX_WIDTH,
        max_height=GSTREAMER_YOLO_DETECTION_MAX_HEIGHT,
    )


def _open_capture_source(
    source: int | str,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    fourcc: str | None = None,
) -> cv2.VideoCapture:
    if isinstance(source, int) and platform.system() == "Darwin":
        return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
    if isinstance(source, int) and platform.system() == "Linux":
        # V4L2 MJPEG capture via cv2.VideoCapture (software JPEG decode). A HW
        # GStreamer mppjpegdec path used to live here; it was removed because it
        # offloaded the JPEG decode to the VPU but then did a full-frame
        # NV12->BGR cv2.cvtColor + copy on the CPU per frame, making it slower
        # than plain cv2.VideoCapture on the Pi (and it silently varied by
        # whether the gi/GStreamer bindings happened to be installed). RGA for
        # the convert is only a win with full dmabuf zero-copy while cv2 keeps up.
        if isinstance(fourcc, str) and len(fourcc.strip()) >= 4:
            _try_v4l2ctl_set_format(source, fourcc.strip()[:4].upper(), width, height)
        device_path = _linux_video_device_path(source)
        params: list[int] = []
        if isinstance(fourcc, str) and len(fourcc.strip()) >= 4:
            params.extend(
                [
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*fourcc.strip()[:4].upper()),
                ]
            )
        if isinstance(width, int) and width > 0:
            params.extend([cv2.CAP_PROP_FRAME_WIDTH, width])
        if isinstance(height, int) and height > 0:
            params.extend([cv2.CAP_PROP_FRAME_HEIGHT, height])
        if isinstance(fps, int) and fps > 0:
            params.extend([cv2.CAP_PROP_FPS, fps])
        if params:
            try:
                return cv2.VideoCapture(str(device_path), cv2.CAP_V4L2, params)
            except Exception:
                pass
        return cv2.VideoCapture(str(device_path), cv2.CAP_V4L2)
    return cv2.VideoCapture(source)


def _capture_failure_backoff_s(failure_count: int) -> float:
    if failure_count <= 0:
        return 0.0
    return min(5.0, 0.25 * (2 ** min(failure_count - 1, 4)))


def _is_macos_camera_index_available(source: int | str | None) -> bool:
    if platform.system() != "Darwin" or not isinstance(source, int) or _refresh_macos_cameras is None:
        return True
    try:
        return any(int(camera.index) == source for camera in _refresh_macos_cameras())
    except Exception:
        return True


def _is_linux_video_device_available(source: int | str | None) -> bool:
    if platform.system() != "Linux" or not isinstance(source, int):
        return True
    return _resolve_linux_video_index(source) is not None


def _cv_prop(name: str) -> int | None:
    return getattr(cv2, name, None)


def _usb_camera_control_specs() -> list[dict[str, Any]]:
    specs = [
        {
            "key": "auto_exposure",
            "label": "Auto Exposure",
            "kind": "boolean",
            "prop": _cv_prop("CAP_PROP_AUTO_EXPOSURE"),
            "help": "Let the camera manage exposure automatically.",
        },
        {
            "key": "exposure",
            "label": "Exposure",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_EXPOSURE"),
            "min": -13.0,
            "max": 13.0,
            "step": 1.0,
            "help": "Driver-reported exposure value.",
        },
        {
            "key": "gain",
            "label": "Gain",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_GAIN"),
            "min": 0.0,
            "max": 255.0,
            "step": 1.0,
            "help": "Analog or digital sensor gain, if exposed by the driver.",
        },
        {
            "key": "brightness",
            "label": "Brightness",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_BRIGHTNESS"),
            "min": -100.0,
            "max": 255.0,
            "step": 1.0,
            "help": "Real camera brightness control when supported by the device.",
        },
        {
            "key": "contrast",
            "label": "Contrast",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_CONTRAST"),
            "min": 0.0,
            "max": 255.0,
            "step": 1.0,
            "help": "Real camera contrast control when supported by the device.",
        },
        {
            "key": "saturation",
            "label": "Saturation",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_SATURATION"),
            "min": 0.0,
            "max": 255.0,
            "step": 1.0,
            "help": "Real camera saturation control when supported by the device.",
        },
        {
            "key": "sharpness",
            "label": "Sharpness",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_SHARPNESS"),
            "min": 0.0,
            "max": 255.0,
            "step": 1.0,
            "help": "Real camera sharpness control when supported by the device.",
        },
        {
            "key": "auto_white_balance",
            "label": "Auto White Balance",
            "kind": "boolean",
            "prop": _cv_prop("CAP_PROP_AUTO_WB"),
            "help": "Let the camera manage white balance automatically.",
        },
        {
            "key": "white_balance_temperature",
            "label": "White Balance Temperature",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_WB_TEMPERATURE"),
            "min": 2000.0,
            "max": 8000.0,
            "step": 50.0,
            "help": "White balance temperature in Kelvin, when supported by the driver.",
        },
        {
            "key": "autofocus",
            "label": "Autofocus",
            "kind": "boolean",
            "prop": _cv_prop("CAP_PROP_AUTOFOCUS"),
            "help": "Let the camera focus automatically, when supported.",
        },
        {
            "key": "focus",
            "label": "Focus",
            "kind": "number",
            "prop": _cv_prop("CAP_PROP_FOCUS"),
            "min": 0.0,
            "max": 255.0,
            "step": 1.0,
            "help": "Manual focus distance, when supported by the driver.",
        },
    ]
    return [spec for spec in specs if spec["prop"] is not None]


def default_auto_camera_device_settings() -> dict[str, bool]:
    return {key: True for key in AUTO_CAMERA_CONTROL_KEYS}


def _bool_from_capture_value(key: str, value: float) -> bool:
    if key == "auto_exposure" and platform.system() == "Linux":
        rounded = round(value)
        if abs(value - rounded) < 0.05 and rounded in {1, 3}:
            return rounded != 1
        return value >= 0.5
    return value >= 0.5


def _value_for_capture(key: str, value: bool | float) -> float:
    if key == "auto_exposure" and platform.system() == "Linux":
        return 0.75 if bool(value) else 0.25
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


_V4L2_SAFE_CONTROL_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_V4L2_CONTROL_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s+0x[0-9A-Fa-f]+\s+\(([^)]+)\)\s*:\s*(.*)$"
)
_V4L2_MENU_OPTION_LINE_RE = re.compile(r"^\s*(-?\d+)\s*:\s*(.+?)\s*$")


def _format_v4l2_integer(value: int | float | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(int(round(float(value))))


def _format_v4l2_auto_exposure(value: int | float | bool) -> str:
    if isinstance(value, bool):
        return "3" if value else "1"
    try:
        numeric = int(round(float(value)))
    except Exception:
        return "3" if bool(value) else "1"
    if numeric in {0, 1, 2, 3}:
        return str(numeric)
    return "3" if numeric else "1"


def _format_v4l2_bool(value: int | float | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return "1" if float(value) != 0 else "0"


# Maps our schema key → (v4l2-ctl control name, value formatter)
_LINUX_V4L2CTL_CONTROL_MAP: dict[str, tuple[str, Any]] = {
    "auto_exposure": ("auto_exposure", _format_v4l2_auto_exposure),
    "auto_white_balance": ("white_balance_automatic", _format_v4l2_bool),
    "autofocus": ("focus_automatic_continuous", _format_v4l2_bool),
    "brightness": ("brightness", _format_v4l2_integer),
    "contrast": ("contrast", _format_v4l2_integer),
    "saturation": ("saturation", _format_v4l2_integer),
    "sharpness": ("sharpness", _format_v4l2_integer),
    "gamma": ("gamma", _format_v4l2_integer),
    "gain": ("gain", _format_v4l2_integer),
    "exposure": ("exposure_time_absolute", _format_v4l2_integer),
    "white_balance_temperature": ("white_balance_temperature", _format_v4l2_integer),
    "focus": ("focus_absolute", _format_v4l2_integer),
    "power_line_frequency": ("power_line_frequency", _format_v4l2_integer),
    "backlight_compensation": ("backlight_compensation", _format_v4l2_integer),
}


# Order in which controls are written in a single v4l2-ctl call. A manual value
# (exposure/white_balance_temperature/focus) only sticks once its auto toggle is
# off, and v4l2-ctl applies -c args left-to-right, so each auto_* must precede
# the value it gates.
_V4L2_APPLY_ORDER: tuple[str, ...] = (
    "auto_exposure",
    "exposure",
    "auto_white_balance",
    "white_balance_temperature",
    "autofocus",
    "focus",
    "gain",
    "brightness",
    "contrast",
    "saturation",
    "sharpness",
    "gamma",
    "power_line_frequency",
    "backlight_compensation",
)

# Manual control → the auto toggle that, when enabled, makes it driver-managed
# (and inactive). We skip writing the manual value in that case so v4l2-ctl
# doesn't error on an inactive control.
_V4L2_AUTO_GATE: dict[str, str] = {
    "exposure": "auto_exposure",
    "white_balance_temperature": "auto_white_balance",
    "focus": "autofocus",
}


def _v4l2_reverse_control_map() -> dict[str, str]:
    return {ctrl_name: key for key, (ctrl_name, _) in _LINUX_V4L2CTL_CONTROL_MAP.items()}


def _v4l2_control_name_for_key(key: str) -> str | None:
    entry = _LINUX_V4L2CTL_CONTROL_MAP.get(key)
    if entry is not None:
        return entry[0]
    if _V4L2_SAFE_CONTROL_KEY_RE.match(key):
        return key
    return None


def _v4l2_schema_key_for_control(ctrl_name: str) -> str:
    return _v4l2_reverse_control_map().get(ctrl_name, ctrl_name)


def _humanize_v4l2_control_label(ctrl_name: str) -> str:
    known = _v4l2_schema_key_for_control(ctrl_name)
    for spec in _usb_camera_control_specs():
        if spec["key"] == known:
            return str(spec["label"])
    words = ctrl_name.replace("_", " ").strip().split()
    return " ".join(word.upper() if word in {"wb", "ae", "awb"} else word.capitalize() for word in words)


def _parse_v4l2_number(value: object) -> float | None:
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        return float(value)
    except Exception:
        return None


def _parse_v4l2_detail_tokens(raw: str) -> dict[str, float | str]:
    details: dict[str, float | str] = {}
    for match in re.finditer(r"([A-Za-z_]+)=([^\s]+)", raw):
        key = match.group(1)
        value = match.group(2)
        if key in {"min", "max", "step", "default", "value"}:
            numeric = _parse_v4l2_number(value)
            if numeric is not None:
                details[key] = numeric
        elif key == "flags":
            details[key] = value
    return details


def _v4l2_kind_from_type(control_type: str) -> str | None:
    normalized = control_type.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"bool", "boolean"}:
        return "boolean"
    if normalized in {"int", "integer", "integer64", "bitmask"}:
        return "number"
    if "menu" in normalized:
        return "menu"
    if normalized == "button":
        return "button"
    return None


def _v4l2_flag_set(raw: object) -> set[str]:
    if not isinstance(raw, str):
        return set()
    return {part.strip().lower().replace("_", "-") for part in re.split(r"[,| ]+", raw) if part.strip()}


def _coerce_v4l2_control_value(
    key: str,
    kind: object,
    value: object,
) -> int | float | bool | None:
    if kind == "button":
        return None
    numeric = _parse_v4l2_number(value)
    if numeric is None:
        return value if isinstance(value, bool) else None
    if kind == "boolean":
        if key == "auto_exposure":
            return int(round(numeric)) in {0, 2, 3}
        return numeric != 0
    return numeric


def _v4l2_auto_gate_enabled(key: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    numeric = _parse_v4l2_number(value)
    if numeric is None:
        return bool(value)
    if key == "auto_exposure":
        return int(round(numeric)) in {0, 2, 3}
    return numeric != 0


def _v4l2_control_is_readonly(control: dict[str, Any] | None) -> bool:
    return bool(control and control.get("readonly"))


def _v4l2_control_is_inactive_for_payload(
    key: str,
    control: dict[str, Any] | None,
    payload: dict[str, int | float | bool],
) -> bool:
    if not bool(control and control.get("inactive")):
        return False
    gate = _V4L2_AUTO_GATE.get(key)
    if gate is not None and gate in payload and not _v4l2_auto_gate_enabled(gate, payload.get(gate)):
        return False
    return True


def _public_v4l2_control(control: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in control.items() if not key.startswith("_")}


def _sorted_v4l2_controls(
    described: dict[str, dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    order = {key: index for index, key in enumerate(_V4L2_APPLY_ORDER)}
    return sorted(
        described.items(),
        key=lambda item: (order.get(item[0], len(order) + int(item[1].get("_order", 0))), int(item[1].get("_order", 0))),
    )


def _v4l2_current_value_from_control(
    key: str,
    control: dict[str, Any],
) -> int | float | bool | None:
    return _coerce_v4l2_control_value(key, control.get("kind"), control.get("value"))


def _v4l2ctl_set_many(source: int, items: list[tuple[str, int | float | bool]]) -> bool:
    """Apply several controls in one v4l2-ctl call, preserving the given order."""
    args: list[str] = []
    for key, value in items:
        entry = _LINUX_V4L2CTL_CONTROL_MAP.get(key)
        if entry is not None:
            ctrl_name, fmt = entry
            args += ["-c", f"{ctrl_name}={fmt(value)}"]
            continue
        ctrl_name = _v4l2_control_name_for_key(key)
        if ctrl_name is None:
            continue
        args += ["-c", f"{ctrl_name}={_format_v4l2_integer(value)}"]
    if not args:
        return True
    try:
        device_path = _linux_video_device_path(source)
        result = subprocess.run(
            ["v4l2-ctl", "-d", str(device_path), *args],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _apply_linux_v4l2_device_settings(
    normalized: dict[str, int | float | bool],
    source: int,
) -> dict[str, int | float | bool]:
    """Apply device settings on Linux through v4l2-ctl only.

    OpenCV's V4L2 CAP_PROP_* path is unreliable here: it reports/sets a
    different scale than the kernel control (e.g. CAP_PROP_EXPOSURE 3509 vs
    exposure_time_absolute 35), and writing CAP_PROP_EXPOSURE silently flips
    auto_exposure to manual. v4l2-ctl is authoritative, so we set and read back
    exclusively through it and store the real driver values (not the intent).

    Controls are device-global per ``/dev/video{source}``, so this works whether
    or not a capture is open — letting the setup wizard tune a camera the runtime
    isn't streaming.
    """
    described = _try_v4l2ctl_describe(source)
    described_keys = set(described.keys())
    ordered_keys: list[str] = []
    for key in _V4L2_APPLY_ORDER:
        if key not in normalized:
            continue
        ordered_keys.append(key)
    for key in normalized:
        if key not in ordered_keys:
            ordered_keys.append(key)

    items: list[tuple[str, int | float | bool]] = []
    for key in ordered_keys:
        if described and key not in described_keys:
            continue
        control = described.get(key)
        if _v4l2_control_is_readonly(control):
            continue
        if _v4l2_control_is_inactive_for_payload(key, control, normalized):
            continue
        if control and control.get("kind") == "button":
            continue
        gate = _V4L2_AUTO_GATE.get(key)
        if gate is not None and _v4l2_auto_gate_enabled(gate, normalized.get(gate)):
            # Auto owns this control; leave the manual value untouched.
            continue
        items.append((key, normalized[key]))

    _v4l2ctl_set_many(source, items)

    described_after = _try_v4l2ctl_describe(source)
    applied: dict[str, int | float | bool] = {}
    for key, value in normalized.items():
        control = described_after.get(key) or described.get(key)
        if control is not None:
            current = _v4l2_current_value_from_control(key, control)
            if current is not None:
                applied[key] = current
                continue
            if control.get("kind") == "button":
                continue
        if described and control is None:
            continue
        if control and control.get("kind") == "boolean":
            current = _try_v4l2ctl_get_bool(source, key)
        else:
            current = _try_v4l2ctl_get_number(source, key)
        applied[key] = current if current is not None else value
    return applied


def apply_device_settings_via_v4l2(
    source: int,
    settings: dict[str, int | float | bool] | None,
) -> dict[str, int | float | bool]:
    """Public entry point to push device settings straight to a Linux V4L2 node.

    Used when no live capture object owns the camera (e.g. the setup wizard),
    since v4l2-ctl controls are global to the device node.
    """
    return _apply_linux_v4l2_device_settings(
        parseCameraDeviceSettingsForCapture(settings), source
    )


# OpenCV's V4L2 backend lies about menu controls (auto_exposure especially) on
# some drivers — cap.get returns 0.0/0.25 even when the kernel has the control
# in mode 3. v4l2-ctl is the authoritative source. Returns None if unavailable.
def _try_v4l2ctl_get_raw(source: int, key: str) -> str | None:
    ctrl_name = _v4l2_control_name_for_key(key)
    if ctrl_name is None:
        return None
    try:
        device_path = _linux_video_device_path(source)
        result = subprocess.run(
            ["v4l2-ctl", "-d", str(device_path), "-C", ctrl_name],
            capture_output=True,
            timeout=2,
            text=True,
        )
        if result.returncode != 0:
            return None
        # Output format: "auto_exposure: 3" or "white_balance_automatic: 1"
        _, _, raw = result.stdout.strip().partition(":")
        raw = raw.strip()
        if not raw:
            return None
        return raw.split()[0]
    except Exception:
        return None


def _try_v4l2ctl_get_bool(source: int, key: str) -> bool | None:
    raw = _try_v4l2ctl_get_raw(source, key)
    if raw is None:
        return None
    try:
        n = int(raw)
    except Exception:
        return None
    if key == "auto_exposure":
        return n in {0, 2, 3}
    return n != 0


def _try_v4l2ctl_get_number(source: int, key: str) -> float | None:
    raw = _try_v4l2ctl_get_raw(source, key)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _try_v4l2ctl_describe(source: int) -> dict[str, dict[str, Any]]:
    try:
        device_path = _linux_video_device_path(source)
        result = subprocess.run(
            ["v4l2-ctl", "-d", str(device_path), "-L"],
            capture_output=True,
            timeout=3,
            text=True,
        )
        if result.returncode != 0:
            return {}
    except Exception:
        return {}

    described: dict[str, dict[str, Any]] = {}
    category: str | None = None
    current_menu_key: str | None = None
    known_specs = {spec["key"]: spec for spec in _usb_camera_control_specs()}
    order = 0

    for line in result.stdout.splitlines():
        raw_line = line.rstrip()
        stripped = raw_line.strip()
        if not stripped:
            current_menu_key = None
            continue

        if raw_line.lstrip() == raw_line:
            if stripped.lower().endswith("controls"):
                category = stripped
            current_menu_key = None
            continue

        menu_match = _V4L2_MENU_OPTION_LINE_RE.match(raw_line)
        if menu_match and current_menu_key is not None:
            option_value = _parse_v4l2_number(menu_match.group(1))
            if option_value is None:
                continue
            label = menu_match.group(2).strip()
            options = described[current_menu_key].setdefault("options", [])
            options.append({"value": option_value, "label": label})
            continue

        match = _V4L2_CONTROL_LINE_RE.match(raw_line)
        if not match:
            current_menu_key = None
            continue

        ctrl_name = match.group(1)
        control_type = match.group(2)
        raw_details = match.group(3)
        kind = _v4l2_kind_from_type(control_type)
        if kind is None:
            current_menu_key = None
            continue

        key = _v4l2_schema_key_for_control(ctrl_name)
        spec = known_specs.get(key, {})
        parsed_details = _parse_v4l2_detail_tokens(raw_details)
        flags = _v4l2_flag_set(parsed_details.get("flags"))
        inactive = "inactive" in flags or "disabled" in flags
        readonly = "read-only" in flags or "readonly" in flags or "write-only" in flags
        control: dict[str, Any] = {
            "key": key,
            "label": spec.get("label") or _humanize_v4l2_control_label(ctrl_name),
            "kind": kind,
            "driverKey": ctrl_name,
            "type": control_type.strip(),
            "_order": order,
        }
        order += 1
        if category:
            control["category"] = category
        if spec.get("help"):
            control["help"] = spec["help"]
        if inactive:
            control["inactive"] = True
        if readonly:
            control["readonly"] = True
        if inactive or readonly:
            control["disabled"] = True

        for detail_key in ("min", "max", "step"):
            value = parsed_details.get(detail_key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                control[detail_key] = float(value)

        for detail_key in ("default", "value"):
            value = _coerce_v4l2_control_value(key, kind, parsed_details.get(detail_key))
            if value is not None:
                control[detail_key] = value

        described[key] = control
        current_menu_key = key if kind == "menu" else None

    return described


def _read_capture_value(
    cap: cv2.VideoCapture,
    spec: dict[str, Any],
    *,
    source: int | str | None = None,
) -> bool | float | None:
    prop = spec.get("prop")
    if prop is None:
        return None
    if (
        platform.system() == "Linux"
        and isinstance(source, int)
        and spec["key"] in _LINUX_V4L2CTL_CONTROL_MAP
    ):
        if spec["kind"] == "boolean":
            v = _try_v4l2ctl_get_bool(source, spec["key"])
            if v is not None:
                return v
        else:
            v = _try_v4l2ctl_get_number(source, spec["key"])
            if v is not None:
                return v
    if cap is None:
        # No capture handle (e.g. a v4l2-ctl-only describe that deliberately
        # avoids opening the device while it's being streamed). Anything not
        # covered by v4l2-ctl above is simply unknown here.
        return None
    raw = cap.get(prop)
    if raw is None or (isinstance(raw, float) and (np.isnan(raw) or np.isinf(raw))):
        return None
    if spec["kind"] == "boolean":
        return _bool_from_capture_value(spec["key"], float(raw))
    return float(raw)


def parseCameraDeviceSettingsForCapture(raw: object) -> dict[str, int | float | bool]:
    return cameraDeviceSettingsToDict(parseCameraDeviceSettings(raw))


def _supports_macos_uvc_controls(source: int | str | None) -> bool:
    return (
        platform.system() == "Darwin"
        and isinstance(source, int)
        and _describe_macos_uvc_controls_for_index is not None
        and _apply_macos_uvc_controls_for_index is not None
    )


def _describe_macos_uvc_controls(
    source: int | str | None,
) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
    if not _supports_macos_uvc_controls(source):
        return [], {}
    assert isinstance(source, int)
    try:
        return _describe_macos_uvc_controls_for_index(source)
    except Exception:
        return [], {}


def _apply_macos_uvc_controls(
    source: int | str | None,
    settings: dict[str, int | float | bool] | None,
) -> tuple[bool, dict[str, int | float | bool]]:
    if not _supports_macos_uvc_controls(source):
        return False, {}
    assert isinstance(source, int)
    controls, current = _describe_macos_uvc_controls(source)
    if not controls:
        return False, {}
    normalized = parseCameraDeviceSettingsForCapture(settings)
    if not normalized:
        return True, current
    try:
        applied = cameraDeviceSettingsToDict(_apply_macos_uvc_controls_for_index(source, normalized))
        return True, applied or current
    except Exception:
        return True, current


def apply_camera_device_settings(
    cap: cv2.VideoCapture,
    settings: dict[str, int | float | bool] | None,
    *,
    source: int | str | None = None,
) -> dict[str, int | float | bool]:
    normalized = parseCameraDeviceSettingsForCapture(settings)
    macos_handled, macos_applied = _apply_macos_uvc_controls(source, normalized)
    if macos_handled:
        return macos_applied

    linux_int_source = source if platform.system() == "Linux" and isinstance(source, int) else None
    if linux_int_source is not None:
        return _apply_linux_v4l2_device_settings(normalized, linux_int_source)

    spec_by_key = {spec["key"]: spec for spec in _usb_camera_control_specs()}
    applied: dict[str, int | float | bool] = {}

    for key, value in normalized.items():
        spec = spec_by_key.get(key)
        if spec is None:
            continue
        try:
            cap.set(spec["prop"], _value_for_capture(key, value))
            current = _read_capture_value(cap, spec, source=source)
            if current is not None:
                applied[key] = current
            else:
                applied[key] = value
        except Exception:
            continue

    return applied


def read_camera_device_settings(
    cap: cv2.VideoCapture,
    *,
    source: int | str | None = None,
) -> dict[str, int | float | bool]:
    if platform.system() == "Linux" and isinstance(source, int):
        described = _try_v4l2ctl_describe(source)
        if described:
            settings: dict[str, int | float | bool] = {}
            for key, control in described.items():
                current = _v4l2_current_value_from_control(key, control)
                if current is not None:
                    settings[key] = current
            return settings

    settings: dict[str, int | float | bool] = {}
    for spec in _usb_camera_control_specs():
        current = _read_capture_value(cap, spec, source=source)
        if current is not None:
            settings[spec["key"]] = current
    return settings


def describe_camera_device_controls(
    cap: cv2.VideoCapture,
    *,
    source: int | str | None = None,
) -> list[dict[str, Any]]:
    macos_controls, _ = _describe_macos_uvc_controls(source)
    if macos_controls:
        return macos_controls

    if platform.system() == "Linux" and isinstance(source, int):
        linux_described = _try_v4l2ctl_describe(source)
        if linux_described:
            return [
                _public_v4l2_control(control)
                for _, control in _sorted_v4l2_controls(linux_described)
            ]

    controls: list[dict[str, Any]] = []
    linux_described = (
        _try_v4l2ctl_describe(source)
        if platform.system() == "Linux" and isinstance(source, int)
        else {}
    )
    for spec in _usb_camera_control_specs():
        # Do NOT cap.set() here as a "support test" — on UVC cameras, writing
        # CAP_PROP_EXPOSURE silently flips auto_exposure to Manual mode, so a
        # passive describe call would corrupt the device state every time the
        # frontend polls for drift. If cap.get returns a usable value, treat
        # the control as supported.
        current = _read_capture_value(cap, spec, source=source)
        if current is None:
            continue

        control: dict[str, Any] = {
            "key": spec["key"],
            "label": spec["label"],
            "kind": spec["kind"],
            "help": spec.get("help"),
            "value": current,
        }
        if spec["kind"] == "number":
            min_value = spec.get("min")
            max_value = spec.get("max")
            step_value = spec.get("step", 1.0)
            linux_spec = linux_described.get(spec["key"])
            if linux_spec:
                if isinstance(linux_spec.get("min"), (int, float)):
                    min_value = float(linux_spec["min"])
                if isinstance(linux_spec.get("max"), (int, float)):
                    max_value = float(linux_spec["max"])
                if isinstance(linux_spec.get("step"), (int, float)):
                    step_value = float(linux_spec["step"])
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                if isinstance(min_value, (int, float)):
                    min_value = min(min_value, float(current))
                if isinstance(max_value, (int, float)):
                    max_value = max(max_value, float(current))
            if min_value is not None:
                control["min"] = min_value
            if max_value is not None:
                control["max"] = max_value
            control["step"] = step_value

        controls.append(control)

    return controls


def probe_camera_device_controls(
    source: int | str | None,
    settings: dict[str, int | float | bool] | None = None,
    *,
    allow_open_capture: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
    if not isinstance(source, int):
        return [], {}

    normalized_settings = parseCameraDeviceSettingsForCapture(settings)
    macos_controls, macos_settings = _describe_macos_uvc_controls(source)
    if macos_controls:
        return macos_controls, macos_settings or normalized_settings

    # On Linux, describe controls purely through v4l2-ctl — it reads the device
    # node without holding a handle, so it never conflicts with a live capture
    # (the setup wizard's direct stream, the runtime feed). Opening a second
    # cv2.VideoCapture here would hit "device busy" and return zero controls
    # while a feed is streaming, and the open/close churn black-frames the stream.
    if platform.system() == "Linux":
        controls = describe_camera_device_controls(None, source=source)
        if controls:
            current = read_camera_device_settings(None, source=source)
            return controls, current or normalized_settings

    if not allow_open_capture:
        return [], normalized_settings

    cap = _open_capture_source(source)
    if not cap.isOpened():
        cap.release()
        return [], normalized_settings

    try:
        controls = describe_camera_device_controls(cap, source=source)
        current = read_camera_device_settings(cap, source=source)
        return controls, current or normalized_settings
    finally:
        cap.release()


def _picture_settings_is_identity(settings: CameraPictureSettings | None) -> bool:
    if settings is None:
        return True
    return (
        int(getattr(settings, "rotation", 0) or 0) % 360 == 0
        and not bool(getattr(settings, "flip_horizontal", False))
        and not bool(getattr(settings, "flip_vertical", False))
    )


def apply_picture_settings(
    frame: np.ndarray,
    settings: CameraPictureSettings | None,
) -> np.ndarray:
    if _picture_settings_is_identity(settings):
        return frame

    global _PICTURE_NONIDENTITY_LOGGED
    if not _PICTURE_NONIDENTITY_LOGGED:
        _PICTURE_NONIDENTITY_LOGGED = True
        log.warning(
            "apply_picture_settings: non-identity branch active (rotation=%s flip_h=%s flip_v=%s) — this allocates per frame",
            getattr(settings, "rotation", None),
            getattr(settings, "flip_horizontal", None),
            getattr(settings, "flip_vertical", None),
        )

    current = clampCameraPictureSettings(settings)
    adjusted = frame

    if current.rotation == 90:
        adjusted = cv2.rotate(adjusted, cv2.ROTATE_90_CLOCKWISE)
    elif current.rotation == 180:
        adjusted = cv2.rotate(adjusted, cv2.ROTATE_180)
    elif current.rotation == 270:
        adjusted = cv2.rotate(adjusted, cv2.ROTATE_90_COUNTERCLOCKWISE)

    if current.flip_horizontal:
        adjusted = cv2.flip(adjusted, 1)

    if current.flip_vertical:
        adjusted = cv2.flip(adjusted, 0)

    return adjusted


class CaptureThread:
    _thread: Optional[threading.Thread]
    _stop_event: threading.Event
    _config: CameraConfig
    _cap: Optional[cv2.VideoCapture]
    latest_frame: Optional[CameraFrame]
    name: str

    def __init__(self, name: str, config: CameraConfig):
        self.name = name
        self._config = config
        self._thread = None
        self._stop_event = threading.Event()
        self._reopen_event = threading.Event()
        self._cap = None
        self._gst_runtime: Any | None = None
        self._detection_crop_rect_xyxy: tuple[int, int, int, int] | None = None
        self.latest_frame = None
        # 90-frame ring buffer (~3 s at 30 FPS) for burst-capture replay. The
        # GIL + deque.append atomicity lets us push without holding a lock.
        self._ring_buffer: deque[CameraFrame] = deque(maxlen=90)
        self._picture_settings = clampCameraPictureSettings(config.picture_settings)
        self._device_settings = parseCameraDeviceSettingsForCapture(config.device_settings)
        self._picture_settings_lock = threading.Lock()
        self._device_settings_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._cap_lock = threading.Lock()

    @staticmethod
    def _requested_capture_backend() -> str:
        return os.environ.get("SORTER_CAMERA_CAPTURE_BACKEND", "").strip().lower()

    @staticmethod
    def _gstreamer_capture_enabled() -> bool:
        explicit = CaptureThread._requested_capture_backend()
        env_enabled = os.environ.get("SORTER_ENABLE_GSTREAMER_MPP_CAPTURE", "").strip().lower()
        return explicit in {"gstreamer", "gstreamer_mpp", "mpp", "auto"} or env_enabled in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _gstreamer_capture_strict() -> bool:
        return CaptureThread._requested_capture_backend() in {"gstreamer", "gstreamer_mpp", "mpp"}

    @staticmethod
    def _should_use_gstreamer_mpp_capture(
        source: int | str | None,
        *,
        is_url: bool,
        fourcc: str | None,
    ) -> bool:
        if platform.system() != "Linux" or is_url or not isinstance(source, int):
            return False
        if not CaptureThread._gstreamer_capture_enabled():
            return False
        normalized_fourcc = (fourcc or "MJPG").strip().upper()
        return normalized_fourcc in {"MJPG", "JPEG"}

    def drain_ring_buffer(self, max_frames: int) -> list[CameraFrame]:
        """Return up to ``max_frames`` most-recent frames from the ring buffer.

        The buffer is NOT cleared — this is a non-destructive snapshot used by
        the drop-zone burst capture to replay the pre-trigger seconds. Returns
        a chronologically-ordered list (oldest → newest). ``list(deque)`` is a
        safe shallow copy under the GIL.
        """
        if max_frames <= 0:
            return []
        frames = list(self._ring_buffer)
        if len(frames) <= max_frames:
            return frames
        return frames[-max_frames:]

    def ring_buffer_depth(self) -> int:
        """Return the number of timestamped raw frames currently retained."""
        return len(self._ring_buffer)

    def latest_detection_frame(self) -> Optional[CameraFrame]:
        """Return the reduced hardware YOLO frame when the capture backend has one.

        The full-resolution ``latest_frame`` remains the authoritative sensor
        frame for overlays and classification crops; this optional frame is only
        an inference input with metadata that maps it back to the sensor frame.
        """
        with self._cap_lock:
            gst_runtime = self._gst_runtime
        getter = getattr(gst_runtime, "latest_detection_frame", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def setDetectionCropRect(
        self,
        sensor_rect_xyxy: tuple[int, int, int, int] | None,
    ) -> bool:
        """Request a sensor-space YOLO crop for direct hardware detection.

        ``sensor_rect_xyxy`` uses the same coordinate convention as perception
        and UI overlays: ``x1,y1,x2,y2`` in the full sensor frame. The active
        GStreamer runtime converts that to the even NV12 crop required by RGA.
        """
        rect: tuple[int, int, int, int] | None = None
        if sensor_rect_xyxy is not None:
            if len(sensor_rect_xyxy) != 4:
                raise ValueError("Detection crop rect must be x1,y1,x2,y2")
            rect = tuple(int(value) for value in sensor_rect_xyxy)
        with self._cap_lock:
            self._detection_crop_rect_xyxy = rect
            gst_runtime = self._gst_runtime
        setter = getattr(gst_runtime, "set_detection_crop_rect", None)
        if callable(setter):
            try:
                return bool(setter(rect))
            except Exception:
                return False
        return False

    def frame_at_or_before(
        self,
        timestamp: float,
        *,
        tolerance_s: float = 0.5,
    ) -> Optional[CameraFrame]:
        """Look up the most recent ring-buffer frame at or before ``timestamp``.

        Used by the overlay timestamp-pinning path: the dynamic-detection
        cache stores ``(frame_ts, detection)``; the encode needs the frame
        from THAT capture tick so the bbox sits on the piece position the
        detector actually saw. Returns ``None`` if no buffered frame falls
        within ``tolerance_s`` seconds before ``timestamp`` — the encode
        path then falls back to ``latest_frame``.

        ``list(deque)`` is atomic under the GIL, so this is lock-free even
        while the capture thread keeps appending.
        """
        frames = list(self._ring_buffer)
        if not frames:
            return None
        best: Optional[CameraFrame] = None
        for frame in reversed(frames):
            ts = float(frame.timestamp)
            if ts <= float(timestamp) + 1e-6:
                if float(timestamp) - ts <= tolerance_s:
                    best = frame
                break
        return best

    def setPictureSettings(self, settings: CameraPictureSettings) -> None:
        clamped = clampCameraPictureSettings(settings)
        with self._picture_settings_lock:
            self._picture_settings = clamped
            self._config.picture_settings = clamped

    def getPictureSettings(self) -> CameraPictureSettings:
        with self._picture_settings_lock:
            return clampCameraPictureSettings(self._picture_settings)

    def setDeviceSettings(
        self,
        settings: dict[str, int | float | bool] | None,
        *,
        persist: bool = False,
    ) -> dict[str, int | float | bool]:
        normalized = parseCameraDeviceSettingsForCapture(settings)
        with self._device_settings_lock:
            self._device_settings = normalized
            if persist:
                self._config.device_settings = dict(normalized)

        with self._cap_lock:
            source = self.getCameraSource()
            if self._cap is not None and isinstance(source, int):
                applied = apply_camera_device_settings(
                    self._cap,
                    normalized,
                    source=source,
                )
                with self._device_settings_lock:
                    self._device_settings = dict(applied)
                    if persist:
                        self._config.device_settings = dict(applied)
                return dict(applied)
            if platform.system() == "Linux" and isinstance(source, int):
                applied = apply_camera_device_settings(
                    None,
                    normalized,
                    source=source,
                )
                with self._device_settings_lock:
                    self._device_settings = dict(applied)
                    if persist:
                        self._config.device_settings = dict(applied)
                return dict(applied)

        return dict(normalized)

    def getDeviceSettings(self) -> dict[str, int | float | bool]:
        with self._device_settings_lock:
            return dict(self._device_settings)

    def getTelemetrySnapshot(self) -> dict[str, object]:
        """Return a small dict of currently-known runtime stats for the
        camera — resolution, fps (actual, not requested), exposure, gain,
        focus, white-balance temperature, auto-exposure / auto-wb flags.
        Used by the TelemetryOverlay to paint a corner indicator; also
        safe for general telemetry consumers. Missing values are simply
        absent from the returned dict.
        """
        stats: dict[str, object] = {}
        with self._cap_lock:
            cap = self._cap
            if cap is not None:
                try:
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                    if w > 0 and h > 0:
                        stats["resolution"] = (w, h)
                except Exception:
                    pass
                try:
                    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                    if fps > 0:
                        stats["fps"] = fps
                except Exception:
                    pass
        settings = self.getDeviceSettings()
        for src_key, out_key in (
            ("exposure", "exposure"),
            ("gain", "gain"),
            ("focus", "focus"),
            ("white_balance_temperature", "wb"),
            ("auto_exposure", "auto_exposure"),
            ("auto_white_balance", "auto_wb"),
        ):
            if src_key in settings and settings[src_key] is not None:
                stats[out_key] = settings[src_key]
        return stats

    def describeDeviceControls(self) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
        source = self.getCameraSource()
        if not isinstance(source, int):
            return [], {}

        with self._cap_lock:
            if self._cap is not None:
                controls = describe_camera_device_controls(self._cap, source=source)
                current = read_camera_device_settings(self._cap, source=source)
                if controls:
                    macos_controls, macos_settings = _describe_macos_uvc_controls(source)
                    if macos_controls:
                        return macos_controls, macos_settings
                return controls, current

        return probe_camera_device_controls(
            source,
            self.getDeviceSettings(),
            allow_open_capture=False,
        )

    def setCameraSource(self, source: int | str | None) -> None:
        with self._config_lock:
            if isinstance(source, str):
                self._config.url = source
                self._config.device_index = -1
            elif isinstance(source, int):
                self._config.url = None
                self._config.device_index = source
            else:
                self._config.url = None
                self._config.device_index = -1
        self.latest_frame = None
        self._requestReopen()

    def getCameraSource(self) -> int | str | None:
        with self._config_lock:
            if self._config.url:
                return self._config.url
            if self._config.device_index >= 0:
                return self._config.device_index
            return None

    def _get_config_snapshot(self) -> tuple[int | str | None, bool, int, int, int, str | None]:
        with self._config_lock:
            source: int | str | None = self._config.url if self._config.url else self._config.device_index
            if isinstance(source, int) and source < 0:
                source = None
            return (
                source,
                bool(self._config.url),
                self._config.width,
                self._config.height,
                self._config.fps,
                getattr(self._config, "fourcc", None),
            )

    def setCaptureMode(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        fourcc: str | None = None,
    ) -> None:
        with self._config_lock:
            if isinstance(width, int) and width > 0:
                self._config.width = width
            if isinstance(height, int) and height > 0:
                self._config.height = height
            if isinstance(fps, int) and fps > 0:
                self._config.fps = fps
            if isinstance(fourcc, str) and fourcc.strip():
                self._config.fourcc = fourcc.strip()
        self._requestReopen()

    def getCaptureMode(self) -> dict[str, int | str | None]:
        with self._config_lock:
            return {
                "width": int(self._config.width),
                "height": int(self._config.height),
                "fps": int(self._config.fps),
                "fourcc": getattr(self._config, "fourcc", None),
            }

    def describeCaptureBackend(self) -> dict[str, Any]:
        source, is_url, width, height, fps, fourcc = self._get_config_snapshot()
        with self._cap_lock:
            gst_runtime = self._gst_runtime
        if gst_runtime is not None:
            describe = getattr(gst_runtime, "describe_capture_backend", None)
            if callable(describe):
                return describe()
        # The integrated GStreamer/MPP runtime is briefly absent while the
        # capture pipeline (re)builds — a camera remap or a transient read-fail
        # reopen under load. Report the CONFIGURED target architecture
        # (compliant, but inactive) in that window instead of the OpenCV
        # fallback, so the WebRTC compliance gate (source_pipeline_target_
        # compliant) does not flap to non-compliant on every capture hiccup and
        # bounce offers with 409. The H.264 reader tolerates the gap and resumes
        # once the runtime is back.
        if self._should_use_gstreamer_mpp_capture(source, is_url=is_url, fourcc=fourcc):
            from .gstreamer_target_capture import (
                TARGET_PIPELINE_NAME,
                scale_converter_uses_hardware,
                target_detection_crop_strategy,
            )
            from .librga_nv12 import LIBRGA_VIRTUALADDR_PATH

            preview_width, preview_height = _bounded_h264_preview_dimensions(width, height)
            detection_width, detection_height = _bounded_yolo_detection_dimensions(width, height)
            rga_converter = _gstreamer_rga_converter_element()
            direct_librga_detection = bool(_direct_librga_detection_available())
            direct_librga_preview = bool(
                direct_librga_detection
                and (preview_width != int(width) or preview_height != int(height))
            )
            scale_converter_hardware = scale_converter_uses_hardware(rga_converter)
            h264_scaled = bool(
                (direct_librga_preview or (rga_converter and scale_converter_hardware))
                and (preview_width != int(width) or preview_height != int(height))
            )
            detection_scaled = bool(
                (direct_librga_detection or (rga_converter and scale_converter_hardware))
                and (detection_width != int(width) or detection_height != int(height))
            )
            hardware_scale_convert = bool(scale_converter_hardware and h264_scaled)
            hardware_preview_scale_convert = bool(
                (direct_librga_preview and h264_scaled)
                or (scale_converter_hardware and h264_scaled)
            )
            hardware_detection_scale_convert = bool(
                (direct_librga_detection and detection_scaled)
                or (scale_converter_hardware and detection_scaled)
            )
            software_scale_convert_fallback = bool(
                rga_converter
                and not scale_converter_hardware
                and (
                    (h264_scaled and not direct_librga_preview)
                    or (detection_scaled and not direct_librga_detection)
                )
            )
            return {
                "implementation": TARGET_PIPELINE_NAME,
                "source": source,
                "requested_mode": {
                    "width": int(width),
                    "height": int(height),
                    "fps": int(fps),
                    "fourcc": fourcc,
                },
                "owns_capture_device": source is not None,
                "single_capture_owner": True,
                "raw_ring_branch": True,
                "h264_webrtc_branch": True,
                "h264_webrtc_pipeline_branch": not direct_librga_preview,
                "h264_webrtc_direct_librga": direct_librga_preview,
                "detection_yolo_branch": bool(detection_scaled),
                "detection_yolo_pipeline_branch": bool(detection_scaled and not direct_librga_detection),
                "detection_yolo_direct_librga": bool(detection_scaled and direct_librga_detection),
                "hardware_scale_convert": bool(hardware_preview_scale_convert or hardware_detection_scale_convert),
                "hardware_preview_scale_convert": hardware_preview_scale_convert,
                "hardware_preview_scale_convert_element": (
                    LIBRGA_VIRTUALADDR_PATH
                    if direct_librga_preview and h264_scaled
                    else rga_converter
                    if hardware_scale_convert
                    else None
                ),
                "hardware_scale_convert_element": rga_converter
                if hardware_scale_convert
                or (hardware_detection_scale_convert and not direct_librga_detection)
                else LIBRGA_VIRTUALADDR_PATH
                if (hardware_preview_scale_convert and direct_librga_preview)
                or (hardware_detection_scale_convert and direct_librga_detection)
                else None,
                "scale_convert_element": (
                    LIBRGA_VIRTUALADDR_PATH
                    if direct_librga_preview
                    or (direct_librga_detection and detection_scaled and not h264_scaled)
                    else rga_converter
                    if h264_scaled or (detection_scaled and not direct_librga_detection)
                    else None
                ),
                "software_scale_convert_fallback": software_scale_convert_fallback,
                "hardware_detection_scale_convert": hardware_detection_scale_convert,
                "hardware_crop": False,
                "hardware_crop_element": None,
                "hardware_detection_crop": False,
                "hardware_detection_crop_capable": bool(direct_librga_detection and detection_scaled),
                "detection_crop_strategy": target_detection_crop_strategy(
                    hardware_crop_runtime_available=True
                    if direct_librga_detection and detection_scaled
                    else None,
                    hardware_crop_runtime_path=LIBRGA_VIRTUALADDR_PATH
                    if direct_librga_detection and detection_scaled
                    else None,
                ),
                "h264_output_mode": {
                    "width": int(preview_width if h264_scaled else width),
                    "height": int(preview_height if h264_scaled else height),
                    "fps": int(fps),
                },
                "detection_output_mode": {
                    "width": int(detection_width),
                    "height": int(detection_height),
                    "fps": int(fps),
                }
                if detection_scaled
                else None,
                "zero_copy_dmabuf": True,
                "preview_zero_copy_dmabuf": False if direct_librga_preview else True,
                "preview_input_memory": "virtualaddr" if direct_librga_preview else "gstreamer_pipeline",
                "detection_zero_copy_dmabuf": False if direct_librga_detection and detection_scaled else True,
                "detection_input_memory": (
                    "virtualaddr" if direct_librga_detection and detection_scaled else "gstreamer_appsink"
                ),
                "target_compliant": True,
                "active": False,
                "reason": "Integrated GStreamer v4l2src/MPP tee target backend (pipeline (re)building).",
            }
        if source is None:
            implementation = "unassigned"
        elif is_url:
            implementation = "opencv_url_raw_ring"
        elif platform.system() == "Linux":
            implementation = "opencv_v4l2_raw_ring"
        elif platform.system() == "Darwin":
            implementation = "opencv_avfoundation_raw_ring"
        else:
            implementation = "opencv_raw_ring"
        return {
            "implementation": implementation,
            "source": source,
            "requested_mode": {
                "width": int(width),
                "height": int(height),
                "fps": int(fps),
                "fourcc": fourcc,
            },
            "owns_capture_device": source is not None,
            "single_capture_owner": True,
            "raw_ring_branch": True,
            "h264_webrtc_branch": False,
            "hardware_scale_convert": False,
            "zero_copy_dmabuf": False,
            "target_compliant": False,
            "reason": (
                "Current backend owns one OpenCV capture and feeds the raw ring only; "
                "the target requires an integrated v4l2src/MPP tee with raw-ring and H.264 branches."
            )
            if source is not None
            else "No camera source is assigned.",
        }

    async def recv_encoded_h264(self) -> Any:
        # During a camera remap the runtime is briefly torn down and rebuilt.
        # Report that as a *restarting* transient (not a hard failure) so the
        # WebRTC fanout waits and resumes instead of tearing the peer down. The
        # fanout bounds how long it tolerates restarting before giving up, so we
        # only need a short per-call wait here.
        from .gstreamer_target_runtime import GStreamerTargetRestartingError

        deadline = time.time() + 1.5
        while not self._stop_event.is_set():
            with self._cap_lock:
                runtime = self._gst_runtime
            if runtime is not None and getattr(runtime, "active", False):
                return await runtime.recv_encoded_h264()
            if time.time() >= deadline:
                raise GStreamerTargetRestartingError(
                    f"CaptureThread[{self.name}] GStreamer H.264 source is (re)starting."
                )
            await asyncio.sleep(0.02)
        raise RuntimeError(f"CaptureThread[{self.name}] is stopping; no GStreamer H.264 source.")

    def describeEncodedH264Source(self) -> dict[str, Any]:
        with self._cap_lock:
            runtime = self._gst_runtime
        if runtime is None:
            return {
                "available": False,
                "active": False,
                "source": self.getCameraSource(),
                "reason": "GStreamer MPP capture runtime is not active.",
            }
        describe = getattr(runtime, "describe_capture_backend", None)
        backend = describe() if callable(describe) else {}
        return {
            "available": bool(getattr(runtime, "active", False)),
            "active": bool(getattr(runtime, "active", False)),
            "source": self.getCameraSource(),
            "codec": "h264",
            "pipeline_profile": "gstreamer_v4l2_mpp_tee_h264",
            "target_compliant": bool(backend.get("target_compliant")),
            "backend": backend,
        }

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._captureLoop,
            daemon=True,
            name=f"capture-{self.name}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._requestReopen()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _requestReopen(self) -> None:
        self._reopen_event.set()
        with self._cap_lock:
            cap = self._cap
            self._cap = None
            gst_runtime = self._gst_runtime
            self._gst_runtime = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        if gst_runtime is not None:
            try:
                gst_runtime.stop()
            except Exception:
                pass

    def _publish_raw_frame(self, frame: np.ndarray, *, timestamp: float | None = None) -> None:
        picture_settings = self.getPictureSettings()
        geom_frame = apply_picture_settings(frame, picture_settings)
        camera_frame = CameraFrame(
            raw=geom_frame,
            annotated=None,
            results=[],
            timestamp=float(timestamp or time.time()),
        )
        self.latest_frame = camera_frame
        self._ring_buffer.append(camera_frame)

    def _publish_gstreamer_raw_frame(self, frame: CameraFrame) -> None:
        raw = getattr(frame, "raw", None)
        if raw is None:
            return
        # GStreamer PTS is stream-relative, while CameraFrame timestamps are
        # wall-clock seconds used by health checks and overlay pinning.
        self._publish_raw_frame(raw, timestamp=time.time())

    def _runGStreamerMppCapture(
        self,
        *,
        source: int,
        width: int,
        height: int,
        fps: int,
        fourcc: str | None,
    ) -> bool:
        # Bringing up several UVC pipelines at the same instant reliably
        # wedges the RK3588 vendor kernel's USB host stack (observed as a
        # hard kernel lockup with 3 cameras). Serialize pipeline bring-up
        # across all CaptureThreads and keep a small gap between starts.
        with _gstreamer_capture_start_gate():
            return self._runGStreamerMppCaptureLocked(
                source=source, width=width, height=height, fps=fps, fourcc=fourcc
            )

    def _runGStreamerMppCaptureLocked(
        self,
        *,
        source: int,
        width: int,
        height: int,
        fps: int,
        fourcc: str | None,
    ) -> bool:
        from .gstreamer_target_capture import GStreamerTargetCaptureConfig, GStreamerTargetElements
        from .gstreamer_target_capture import scale_converter_uses_hardware
        from .gstreamer_target_runtime import GStreamerTargetCaptureRuntime

        actual_source = _resolve_linux_video_index(source)
        if actual_source is None:
            log.warning(
                "CaptureThread[%s] cannot resolve Linux camera source %s to a /dev/video node.",
                self.name,
                source,
            )
            return False
        normalized_fourcc = (fourcc or "MJPG").strip().upper()
        _try_v4l2ctl_set_format(actual_source, normalized_fourcc, width, height)
        actual_width, actual_height, actual_fourcc = _try_v4l2ctl_get_format(actual_source)
        if actual_width and actual_height:
            width = actual_width
            height = actual_height
        if actual_fourcc:
            normalized_fourcc = actual_fourcc.strip().upper()
        h264_width: int | None = None
        h264_height: int | None = None
        detection_width: int | None = None
        detection_height: int | None = None
        elements = GStreamerTargetElements()
        rga_converter = _gstreamer_rga_converter_element()
        direct_librga_detection = bool(_direct_librga_detection_available())
        scale_converter_hardware = scale_converter_uses_hardware(rga_converter)
        preview_width, preview_height = _bounded_h264_preview_dimensions(width, height)
        yolo_width, yolo_height = _bounded_yolo_detection_dimensions(width, height)
        direct_librga_preview = bool(
            direct_librga_detection
            and (preview_width != int(width) or preview_height != int(height))
        )
        if direct_librga_preview:
            h264_width = preview_width
            h264_height = preview_height
        elif rga_converter and scale_converter_hardware:
            if preview_width != int(width) or preview_height != int(height):
                h264_width = preview_width
                h264_height = preview_height
        if direct_librga_detection:
            detection_width = yolo_width
            detection_height = yolo_height
        elif (
            rga_converter
            and scale_converter_hardware
            and (yolo_width != int(width) or yolo_height != int(height))
        ):
            detection_width = yolo_width
            detection_height = yolo_height
        if rga_converter and (
            normalized_fourcc not in {"MJPG", "JPEG"}
            or (h264_width is not None and not direct_librga_preview)
            or (detection_width is not None and not direct_librga_detection)
        ):
            elements = GStreamerTargetElements(rga_converter=rga_converter)
        config = GStreamerTargetCaptureConfig(
            device_path=f"/dev/video{actual_source}",
            width=int(width),
            height=int(height),
            fps=int(fps),
            input_fourcc=normalized_fourcc,
            h264_width=h264_width,
            h264_height=h264_height,
            direct_librga_preview=direct_librga_preview,
            detection_width=detection_width,
            detection_height=detection_height,
            direct_librga_detection=direct_librga_detection and detection_width is not None and detection_height is not None,
            elements=elements,
        )
        runtime = GStreamerTargetCaptureRuntime(
            config,
            raw_frame_callback=self._publish_gstreamer_raw_frame,
        )
        try:
            with self._cap_lock:
                pending_detection_crop_rect = self._detection_crop_rect_xyxy
            if pending_detection_crop_rect is not None:
                runtime.set_detection_crop_rect(pending_detection_crop_rect)
            settings_to_apply = self.getDeviceSettings() or default_auto_camera_device_settings()
            applied_device_settings = apply_camera_device_settings(
                None,
                settings_to_apply,
                source=actual_source,
            )
            if applied_device_settings:
                with self._device_settings_lock:
                    self._device_settings = dict(applied_device_settings)
            runtime.start()
        except Exception as exc:
            try:
                runtime.stop()
            except Exception:
                pass
            log.warning(
                "CaptureThread[%s] GStreamer MPP capture failed for logical video%s -> /dev/video%s: %s",
                self.name,
                source,
                actual_source,
                exc,
            )
            return False

        with self._cap_lock:
            self._cap = None
            self._gst_runtime = runtime
        log.warning(
            "CaptureThread[%s] using GStreamer MPP capture backend for logical video%s -> /dev/video%s (%sx%s@%s %s, h264=%sx%s, yolo=%s, rga=%s, direct_librga_preview=%s, direct_librga_yolo=%s)",
            self.name,
            source,
            actual_source,
            width,
            height,
            fps,
            normalized_fourcc,
            config.h264_output_dimensions()[0],
            config.h264_output_dimensions()[1],
            f"{detection_width}x{detection_height}" if detection_width and detection_height else "raw-ring",
            config.elements.rga_converter or "none",
            config.direct_librga_preview,
            config.direct_librga_detection,
        )
        try:
            while not self._stop_event.is_set() and not self._reopen_event.is_set():
                time.sleep(0.05)
            return True
        finally:
            with self._cap_lock:
                if self._gst_runtime is runtime:
                    self._gst_runtime = None
            try:
                runtime.stop()
            except Exception:
                pass

    def _captureLoop(self) -> None:
        cap: Optional[cv2.VideoCapture] = None
        self._cap = None
        open_failures = 0
        read_failures = 0
        next_open_attempt_at = 0.0
        previous_source: int | str | None = None
        expected_frame_settle_until = 0.0
        # One-shot startup log per camera so journalctl shows whether the
        # picture path is identity at runtime.
        _initial_pic = self._picture_settings
        log.warning(
            "CaptureThread[%s] starting — picture=%s",
            self.name,
            "identity"
            if _picture_settings_is_identity(_initial_pic)
            else f"rotation={getattr(_initial_pic, 'rotation', '?')} flip_h={getattr(_initial_pic, 'flip_horizontal', '?')} flip_v={getattr(_initial_pic, 'flip_vertical', '?')}",
        )
        last_expected_frame_at = 0.0
        # Some UVC cameras (especially on Linux with MJPG) reset device controls
        # (e.g. auto_exposure) when streaming starts on the first cap.read().
        # Re-apply after the first successful read so the settings actually stick.
        post_stream_settings: dict[str, int | float | bool] | None = None
        post_stream_source: int | None = None

        while not self._stop_event.is_set():
            source, is_url, width, height, fps, fourcc = self._get_config_snapshot()

            if source != previous_source:
                previous_source = source
                open_failures = 0
                read_failures = 0
                next_open_attempt_at = 0.0
                expected_frame_settle_until = 0.0
                last_expected_frame_at = 0.0
                post_stream_settings = None
                post_stream_source = None

            if self._reopen_event.is_set():
                self._reopen_event.clear()
                if cap is not None:
                    cap.release()
                    cap = None
                self._cap = None
                open_failures = 0
                read_failures = 0
                next_open_attempt_at = 0.0
                expected_frame_settle_until = 0.0
                last_expected_frame_at = 0.0
                post_stream_settings = None
                post_stream_source = None

            if source is None:
                self.latest_frame = None
                time.sleep(0.1)
                continue

            if cap is None:
                now = time.time()
                if now < next_open_attempt_at:
                    time.sleep(min(0.1, max(0.01, next_open_attempt_at - now)))
                    continue

                if not is_url and not _is_macos_camera_index_available(source):
                    self.latest_frame = None
                    open_failures += 1
                    next_open_attempt_at = time.time() + _capture_failure_backoff_s(open_failures)
                    time.sleep(min(0.25, _capture_failure_backoff_s(open_failures)))
                    continue

                if not is_url and not _is_linux_video_device_available(source):
                    self.latest_frame = None
                    open_failures += 1
                    next_open_attempt_at = time.time() + _capture_failure_backoff_s(open_failures)
                    time.sleep(min(0.25, _capture_failure_backoff_s(open_failures)))
                    continue

                if self._should_use_gstreamer_mpp_capture(source, is_url=is_url, fourcc=fourcc):
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._cap = None
                    used_gstreamer = self._runGStreamerMppCapture(
                        source=int(source),
                        width=int(width),
                        height=int(height),
                        fps=int(fps),
                        fourcc=fourcc,
                    )
                    if used_gstreamer:
                        open_failures = 0
                        read_failures = 0
                        continue
                    open_failures += 1
                    next_open_attempt_at = time.time() + _capture_failure_backoff_s(open_failures)
                    if self._gstreamer_capture_strict():
                        self.latest_frame = None
                        time.sleep(min(0.25, _capture_failure_backoff_s(open_failures)))
                        continue

                with self._cap_lock:
                    candidate = _open_capture_source(
                        source,
                        width=width,
                        height=height,
                        fps=fps,
                        fourcc=fourcc,
                    )
                    if not candidate.isOpened():
                        candidate.release()
                        cap = None
                        self._cap = None
                        self.latest_frame = None
                        open_failures += 1
                        next_open_attempt_at = time.time() + _capture_failure_backoff_s(open_failures)
                        time.sleep(min(0.25, _capture_failure_backoff_s(open_failures)))
                        continue

                    cap = candidate
                    self._cap = cap
                    open_failures = 0
                    read_failures = 0
                    next_open_attempt_at = 0.0
                    expected_frame_settle_until = (
                        time.time() + CAPTURE_MODE_SETTLE_S
                        if not is_url and width > 0 and height > 0
                        else 0.0
                    )
                    last_expected_frame_at = 0.0

                    if not is_url:
                        # macOS uses AVFoundation, which negotiates its own pixel
                        # format at open time. Setting CAP_PROP_FOURCC after the
                        # fact can leave some cams open-but-frameless (e.g. Logitech
                        # StreamCam). Only force the FOURCC on Linux/V4L2.
                        if (
                            platform.system() == "Linux"
                            and isinstance(fourcc, str)
                            and len(fourcc) >= 4
                        ):
                            try:
                                cap.set(
                                    cv2.CAP_PROP_FOURCC,
                                    cv2.VideoWriter_fourcc(*fourcc[:4].upper()),
                                )
                            except Exception:
                                pass
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                        cap.set(cv2.CAP_PROP_FPS, fps)
                        settings_to_apply = self.getDeviceSettings()
                        pre_settings = settings_to_apply or default_auto_camera_device_settings()
                        applied_device_settings = apply_camera_device_settings(
                            cap,
                            pre_settings,
                            source=source,
                        )
                        if applied_device_settings:
                            with self._device_settings_lock:
                                self._device_settings = dict(applied_device_settings)
                        # Schedule a re-apply after the first read so MJPG
                        # streaming-start control resets don't lock in wrong values.
                        if isinstance(source, int):
                            post_stream_settings = dict(pre_settings)
                            post_stream_source = source
                        else:
                            post_stream_settings = None
                            post_stream_source = None

            # Do not hold _cap_lock while reading. AVFoundation can block inside
            # cap.read(); holding the lock there prevents stop/reopen requests
            # from releasing the handle and leaves the camera stuck until the
            # whole process exits.
            try:
                ret, frame = cap.read()
            except Exception:
                ret, frame = False, None
            if ret:
                read_failures = 0
                if not is_url and width > 0 and height > 0:
                    frame_h, frame_w = frame.shape[:2]
                    if (int(frame_w), int(frame_h)) != (int(width), int(height)):
                        now = time.time()
                        has_recent_expected = (
                            last_expected_frame_at > 0.0
                            and (now - last_expected_frame_at)
                            < CAPTURE_EXPECTED_FRAME_FALLBACK_S
                        )
                        if now < expected_frame_settle_until or has_recent_expected:
                            continue
                    else:
                        last_expected_frame_at = time.time()
                if post_stream_settings is not None and post_stream_source is not None:
                    with self._cap_lock:
                        if cap is not None:
                            applied = apply_camera_device_settings(
                                cap, post_stream_settings, source=post_stream_source
                            )
                            if applied:
                                with self._device_settings_lock:
                                    self._device_settings = dict(applied)
                    post_stream_settings = None
                    post_stream_source = None
                picture_settings = self.getPictureSettings()
                geom_frame = apply_picture_settings(frame, picture_settings)
                camera_frame = CameraFrame(
                    raw=geom_frame,
                    annotated=None,
                    results=[],
                    timestamp=time.time(),
                )
                self.latest_frame = camera_frame
                # deque.append is atomic under the GIL — no lock needed.
                self._ring_buffer.append(camera_frame)
            else:
                read_failures += 1
                # For URL sources, briefly wait then retry (stream may reconnect)
                time.sleep(0.1 if is_url else min(0.5, 0.05 * read_failures))
                if not cap.isOpened() or (not is_url and read_failures >= 5):
                    cap.release()
                    cap = None
                    self._cap = None
                    self.latest_frame = None
                    if not is_url:
                        next_open_attempt_at = time.time() + _capture_failure_backoff_s(read_failures)

        if cap is not None:
            cap.release()
        self._cap = None
