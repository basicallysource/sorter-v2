import logging
import subprocess
import threading
import time
from collections import deque
from typing import Any, Optional
import platform
import cv2
import numpy as np

log = logging.getLogger(__name__)

# One-shot flags so we log only the *first* time a non-identity picture/color
# path runs in a given process. Lets ops grep journalctl for these strings —
# their absence means we never paid the cost.
_PICTURE_NONIDENTITY_LOGGED = False
_COLOR_ACTIVE_LOGGED = False

from irl.config import (
    CameraConfig,
    CameraColorProfile,
    CameraPictureSettings,
    cameraDeviceSettingsToDict,
    clampCameraColorProfile,
    clampCameraPictureSettings,
    parseCameraDeviceSettings,
)
from .types import CameraFrame
from .gst_capture import GstMjpegCapture, hw_jpeg_decode_available

CAPTURE_MODE_SETTLE_S = 2.0
CAPTURE_EXPECTED_FRAME_FALLBACK_S = 10.0
AUTO_CAMERA_CONTROL_KEYS = ("auto_exposure", "auto_white_balance", "autofocus")

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
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", f"--set-fmt-video={fmt_arg}"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


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
        # HW JPEG decode (RK3588 VPU via GStreamer mppjpegdec). Software
        # cv2.imdecode of 1080p/4K MJPEG is the capture bottleneck on the Pi;
        # the VPU offloads it. Only taken when a concrete MJPEG mode is known
        # and the element exists — otherwise (Mac, non-rockchip Linux, probes
        # with no mode) fall through to cv2.VideoCapture. A pipeline that opens
        # but delivers no frame self-fails so we still drop back to cv2.
        fourcc_is_mjpeg = (
            fourcc is None
            or (isinstance(fourcc, str) and fourcc.strip()[:4].upper() in {"MJPG", "MJPE"})
        )
        if (
            isinstance(width, int) and width > 0
            and isinstance(height, int) and height > 0
            and isinstance(fps, int) and fps > 0
            and fourcc_is_mjpeg
            and hw_jpeg_decode_available()
        ):
            gst = GstMjpegCapture(source, width, height, fps)
            if gst.isOpened():
                return gst  # type: ignore[return-value]
            gst.release()
        if isinstance(fourcc, str) and len(fourcc.strip()) >= 4:
            _try_v4l2ctl_set_format(source, fourcc.strip()[:4].upper(), width, height)
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
                return cv2.VideoCapture(source, cv2.CAP_V4L2, params)
            except Exception:
                pass
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


# Maps our schema key → (v4l2-ctl control name, value formatter)
_LINUX_V4L2CTL_CONTROL_MAP: dict[str, tuple[str, Any]] = {
    "auto_exposure": ("auto_exposure", lambda v: "3" if bool(v) else "1"),
    "auto_white_balance": ("white_balance_automatic", lambda v: "1" if bool(v) else "0"),
    "autofocus": ("focus_automatic_continuous", lambda v: "1" if bool(v) else "0"),
    "brightness": ("brightness", lambda v: str(int(round(float(v))))),
    "contrast": ("contrast", lambda v: str(int(round(float(v))))),
    "saturation": ("saturation", lambda v: str(int(round(float(v))))),
    "sharpness": ("sharpness", lambda v: str(int(round(float(v))))),
    "gamma": ("gamma", lambda v: str(int(round(float(v))))),
    "gain": ("gain", lambda v: str(int(round(float(v))))),
    "exposure": ("exposure_time_absolute", lambda v: str(int(round(float(v))))),
    "white_balance_temperature": ("white_balance_temperature", lambda v: str(int(round(float(v))))),
    "focus": ("focus_absolute", lambda v: str(int(round(float(v))))),
    "power_line_frequency": ("power_line_frequency", lambda v: str(int(round(float(v))))),
    "backlight_compensation": ("backlight_compensation", lambda v: str(int(round(float(v))))),
}


def _try_v4l2ctl_set(source: int, key: str, value: bool | float) -> bool:
    entry = _LINUX_V4L2CTL_CONTROL_MAP.get(key)
    if entry is None:
        return False
    ctrl_name, fmt = entry
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", "-c", f"{ctrl_name}={fmt(value)}"],
            capture_output=True,
            timeout=2,
        )
        return result.returncode == 0
    except Exception:
        return False


# OpenCV's V4L2 backend lies about menu controls (auto_exposure especially) on
# some drivers — cap.get returns 0.0/0.25 even when the kernel has the control
# in mode 3. v4l2-ctl is the authoritative source. Returns None if unavailable.
def _try_v4l2ctl_get_raw(source: int, key: str) -> str | None:
    entry = _LINUX_V4L2CTL_CONTROL_MAP.get(key)
    if entry is None:
        return None
    ctrl_name, _ = entry
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", "-C", ctrl_name],
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
        return n == 3
    return n != 0


def _try_v4l2ctl_get_number(source: int, key: str) -> float | None:
    raw = _try_v4l2ctl_get_raw(source, key)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _try_v4l2ctl_describe(source: int) -> dict[str, dict[str, float | bool]]:
    by_ctrl_name: dict[str, str] = {}
    for key, (ctrl_name, _) in _LINUX_V4L2CTL_CONTROL_MAP.items():
        by_ctrl_name[ctrl_name] = key
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", "-L"],
            capture_output=True,
            timeout=3,
            text=True,
        )
        if result.returncode != 0:
            return {}
    except Exception:
        return {}

    described: dict[str, dict[str, float | bool]] = {}
    for line in result.stdout.splitlines():
        raw_line = line.rstrip()
        if not raw_line or raw_line.lstrip() == raw_line or "0x" not in raw_line:
            continue
        ctrl_name = raw_line.split()[0]
        key = by_ctrl_name.get(ctrl_name)
        if key is None:
            continue
        details: dict[str, float | bool] = {}
        for token in raw_line.split():
            if "=" not in token:
                continue
            token_key, token_value = token.split("=", 1)
            if token_key in {"min", "max", "step", "default", "value"}:
                try:
                    details[token_key] = float(token_value)
                except Exception:
                    continue
            elif token_key == "flags":
                details["inactive"] = "inactive" in token_value
        described[key] = details
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

    spec_by_key = {spec["key"]: spec for spec in _usb_camera_control_specs()}
    applied: dict[str, int | float | bool] = {}

    linux_int_source = source if platform.system() == "Linux" and isinstance(source, int) else None

    for key, value in normalized.items():
        spec = spec_by_key.get(key)
        if spec is None:
            continue
        try:
            cap.set(spec["prop"], _value_for_capture(key, value))
            current = _read_capture_value(cap, spec, source=source)
            # If the readback doesn't match the intent, try v4l2-ctl on Linux.
            # This handles cameras where OpenCV's cap.set encoding doesn't stick.
            if current is not None and current != value and linux_int_source is not None:
                if _try_v4l2ctl_set(linux_int_source, key, value):
                    # Trust the intent; don't let the wrong readback poison _device_settings.
                    applied[key] = value
                    continue
            if current is not None:
                applied[key] = current
            else:
                applied[key] = value
        except Exception:
            continue

    return applied


def _is_gst_capture(cap: object) -> bool:
    return isinstance(cap, GstMjpegCapture)


def apply_camera_device_settings_v4l2(
    source: int,
    settings: dict[str, int | float | bool] | None,
) -> dict[str, int | float | bool]:
    """Apply device settings via v4l2-ctl only (no cv2.set).

    Used for the GStreamer HW-decode capture path, where there is no
    cv2.VideoCapture to take CAP_PROP_* writes. Auto-mode toggles are applied
    first so a following manual exposure/gain actually sticks. Keys with no
    v4l2-ctl mapping are silently skipped (they only work through cv2).
    """
    normalized = parseCameraDeviceSettingsForCapture(settings)
    applied: dict[str, int | float | bool] = {}
    ordered = sorted(normalized.items(), key=lambda kv: 0 if "auto" in kv[0] else 1)
    for key, value in ordered:
        if key in _LINUX_V4L2CTL_CONTROL_MAP and _try_v4l2ctl_set(source, key, value):
            applied[key] = value
    return applied


def read_camera_device_settings(
    cap: cv2.VideoCapture,
    *,
    source: int | str | None = None,
) -> dict[str, int | float | bool]:
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


def apply_camera_color_profile(
    frame: np.ndarray,
    profile: CameraColorProfile | None,
) -> np.ndarray:
    if profile is None or not getattr(profile, "enabled", False):
        return frame

    global _COLOR_ACTIVE_LOGGED
    if not _COLOR_ACTIVE_LOGGED:
        _COLOR_ACTIVE_LOGGED = True
        log.warning(
            "apply_camera_color_profile: enabled branch active — full-frame LUT+tensordot+gamma will run per frame"
        )

    current = clampCameraColorProfile(profile)
    if not current.enabled:
        return frame

    matrix = np.array(current.matrix, dtype=np.float32)
    bias = np.array(current.bias, dtype=np.float32)
    if matrix.shape != (3, 3) or bias.shape != (3,):
        return frame

    # Step 1: Linearize via response LUT (if available)
    has_lut = (
        current.response_lut_r is not None
        and current.response_lut_g is not None
        and current.response_lut_b is not None
        and len(current.response_lut_r) == 256
        and len(current.response_lut_g) == 256
        and len(current.response_lut_b) == 256
    )

    if has_lut:
        # Build per-channel LUT: uint8 → float32 linear [0, 1]
        lut_b = np.array(current.response_lut_b, dtype=np.float32)
        lut_g = np.array(current.response_lut_g, dtype=np.float32)
        lut_r = np.array(current.response_lut_r, dtype=np.float32)
        rgb = np.stack([lut_r[frame[:, :, 2]], lut_g[frame[:, :, 1]], lut_b[frame[:, :, 0]]], axis=-1)
    else:
        rgb = frame[:, :, ::-1].astype(np.float32) / 255.0

    # Step 2: Affine CCM (3×3 matrix + bias)
    corrected = np.tensordot(rgb, matrix.T, axes=1) + bias

    # Step 3: Per-channel gamma (if available)
    has_gamma = (
        current.gamma_a is not None
        and current.gamma_exp is not None
        and current.gamma_b is not None
        and len(current.gamma_a) == 3
        and len(current.gamma_exp) == 3
        and len(current.gamma_b) == 3
    )

    if has_gamma:
        ga = current.gamma_a
        ge = current.gamma_exp
        gb = current.gamma_b
        for c in range(3):
            ch = np.clip(corrected[:, :, c], 0.0, None)
            corrected[:, :, c] = ga[c] * np.power(ch, ge[c]) + gb[c]

    corrected = np.clip(corrected, 0.0, 1.0)
    return np.round(corrected[:, :, ::-1] * 255.0).astype(np.uint8)


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
        self.latest_frame = None
        # 90-frame ring buffer (~3 s at 30 FPS) for burst-capture replay. The
        # GIL + deque.append atomicity lets us push without holding a lock.
        self._ring_buffer: deque[CameraFrame] = deque(maxlen=90)
        self._picture_settings = clampCameraPictureSettings(config.picture_settings)
        self._device_settings = parseCameraDeviceSettingsForCapture(config.device_settings)
        self._color_profile = clampCameraColorProfile(config.color_profile)
        self._picture_settings_lock = threading.Lock()
        self._device_settings_lock = threading.Lock()
        self._color_profile_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._cap_lock = threading.Lock()

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

    def setColorProfile(self, profile: CameraColorProfile | None) -> None:
        clamped = clampCameraColorProfile(profile or CameraColorProfile())
        with self._color_profile_lock:
            self._color_profile = clamped
            self._config.color_profile = clamped

    def getColorProfile(self) -> CameraColorProfile:
        with self._color_profile_lock:
            return clampCameraColorProfile(self._color_profile)

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
                if _is_gst_capture(self._cap):
                    applied = apply_camera_device_settings_v4l2(source, normalized)
                else:
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
        self._reopen_event.set()

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
        self._reopen_event.set()

    def getCaptureMode(self) -> dict[str, int | str | None]:
        with self._config_lock:
            return {
                "width": int(self._config.width),
                "height": int(self._config.height),
                "fps": int(self._config.fps),
                "fourcc": getattr(self._config, "fourcc", None),
            }

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._captureLoop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _captureLoop(self) -> None:
        cap: Optional[cv2.VideoCapture] = None
        self._cap = None
        open_failures = 0
        read_failures = 0
        next_open_attempt_at = 0.0
        previous_source: int | str | None = None
        expected_frame_settle_until = 0.0
        # One-shot startup log per camera so journalctl shows the
        # picture/color identity state. If `picture=identity color=disabled`
        # appears for every camera and the non-identity warnings never fire,
        # we know the per-frame apply_* calls are no-ops the whole run.
        _initial_pic = self._picture_settings
        _initial_col = self._color_profile
        log.warning(
            "CaptureThread[%s] starting — picture=%s color=%s",
            self.name,
            "identity"
            if _picture_settings_is_identity(_initial_pic)
            else f"rotation={getattr(_initial_pic, 'rotation', '?')} flip_h={getattr(_initial_pic, 'flip_horizontal', '?')} flip_v={getattr(_initial_pic, 'flip_vertical', '?')}",
            "enabled" if getattr(_initial_col, "enabled", False) else "disabled",
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

                    if not is_url and _is_gst_capture(cap):
                        # HW-decode path: capture mode is baked into the pipeline
                        # caps and there is no cv2.VideoCapture to take CAP_PROP_*
                        # writes, so device controls go through v4l2-ctl directly.
                        settings_to_apply = self.getDeviceSettings()
                        pre_settings = settings_to_apply or default_auto_camera_device_settings()
                        applied_device_settings = apply_camera_device_settings_v4l2(
                            source, pre_settings
                        ) if isinstance(source, int) else {}
                        if applied_device_settings:
                            with self._device_settings_lock:
                                self._device_settings = dict(applied_device_settings)
                        # Re-apply after the first frame: v4l2src starting the
                        # stream can reset controls (e.g. auto_exposure).
                        if isinstance(source, int):
                            post_stream_settings = dict(pre_settings)
                            post_stream_source = source
                        else:
                            post_stream_settings = None
                            post_stream_source = None
                    elif not is_url:
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

            with self._cap_lock:
                ret, frame = cap.read()
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
                            if _is_gst_capture(cap):
                                applied = apply_camera_device_settings_v4l2(
                                    post_stream_source, post_stream_settings
                                )
                            else:
                                applied = apply_camera_device_settings(
                                    cap, post_stream_settings, source=post_stream_source
                                )
                            if applied:
                                with self._device_settings_lock:
                                    self._device_settings = dict(applied)
                    post_stream_settings = None
                    post_stream_source = None
                picture_settings = self.getPictureSettings()
                color_profile = self.getColorProfile()
                # Apply rotation/flip once; downstream consumers see the same
                # geometry whether or not color correction is active.
                geom_frame = apply_picture_settings(frame, picture_settings)
                if getattr(color_profile, "enabled", False):
                    corrected_frame = apply_camera_color_profile(geom_frame, color_profile)
                else:
                    corrected_frame = geom_frame
                camera_frame = CameraFrame(
                    raw=corrected_frame,
                    annotated=None,
                    results=[],
                    timestamp=time.time(),
                    uncorrected_raw=geom_frame,
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
