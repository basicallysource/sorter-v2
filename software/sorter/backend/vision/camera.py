import threading
import time
from typing import Any, Optional
import platform
import cv2
import numpy as np

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

if platform.system() == "Darwin":
    try:
        from hardware.macos_uvc_controls import (
            apply_controls_for_index as _apply_macos_uvc_controls_for_index,
            describe_controls_for_index as _describe_macos_uvc_controls_for_index,
        )
    except Exception:
        _apply_macos_uvc_controls_for_index = None
        _describe_macos_uvc_controls_for_index = None
else:
    _apply_macos_uvc_controls_for_index = None
    _describe_macos_uvc_controls_for_index = None


def _open_capture_source(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int) and platform.system() == "Darwin":
        return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(source)


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


def _bool_from_capture_value(key: str, value: float) -> bool:
    if key == "auto_exposure" and platform.system() == "Linux":
        return value >= 0.5
    return value >= 0.5


def _value_for_capture(key: str, value: bool | float) -> float:
    if key == "auto_exposure" and platform.system() == "Linux":
        return 0.75 if bool(value) else 0.25
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def _read_capture_value(cap: cv2.VideoCapture, spec: dict[str, Any]) -> bool | float | None:
    prop = spec.get("prop")
    if prop is None:
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

    spec_by_key = {spec["key"]: spec for spec in _usb_camera_control_specs()}
    applied: dict[str, int | float | bool] = {}

    for key, value in normalized.items():
        spec = spec_by_key.get(key)
        if spec is None:
            continue
        try:
            cap.set(spec["prop"], _value_for_capture(key, value))
            current = _read_capture_value(cap, spec)
            if current is not None:
                applied[key] = current
            else:
                applied[key] = value
        except Exception:
            continue

    return applied


def read_camera_device_settings(cap: cv2.VideoCapture) -> dict[str, int | float | bool]:
    settings: dict[str, int | float | bool] = {}
    for spec in _usb_camera_control_specs():
        current = _read_capture_value(cap, spec)
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
    for spec in _usb_camera_control_specs():
        current = _read_capture_value(cap, spec)
        if current is None:
            continue

        supported = False
        try:
            supported = bool(cap.set(spec["prop"], _value_for_capture(spec["key"], current)))
        except Exception:
            supported = False

        if not supported:
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
) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
    if not isinstance(source, int):
        return [], {}

    macos_controls, macos_settings = _describe_macos_uvc_controls(source)
    if macos_controls:
        if settings:
            applied = _apply_macos_uvc_controls(source, settings)
            return macos_controls, applied or macos_settings
        return macos_controls, macos_settings

    cap = _open_capture_source(source)
    if not cap.isOpened():
        cap.release()
        return [], {}

    try:
        if settings:
            apply_camera_device_settings(cap, settings)
        controls = describe_camera_device_controls(cap)
        current = read_camera_device_settings(cap)
        return controls, current
    finally:
        cap.release()


def apply_picture_settings(
    frame: np.ndarray,
    settings: CameraPictureSettings | None,
) -> np.ndarray:
    if settings is None:
        return frame

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
    if profile is None:
        return frame

    current = clampCameraColorProfile(profile)
    if not current.enabled:
        return frame

    matrix = np.array(current.matrix, dtype=np.float32)
    bias = np.array(current.bias, dtype=np.float32)
    if matrix.shape != (3, 3) or bias.shape != (3,):
        return frame

    rgb = frame[:, :, ::-1].astype(np.float32) / 255.0
    corrected = np.tensordot(rgb, matrix.T, axes=1) + bias
    corrected = np.clip(corrected, 0.0, 1.0)
    return np.round(corrected[:, :, ::-1] * 255.0).astype(np.uint8)


def _apply_device_settings_software(
    frame: np.ndarray,
    settings: dict[str, int | float | bool],
    defaults: dict[str, int | float | bool],
) -> np.ndarray:
    """Apply device setting adjustments as software post-processing.

    Computes the delta between current settings and defaults and applies
    brightness, contrast, saturation, gamma, and sharpness as OpenCV
    image operations.  This is used on macOS where UVC controls do not
    reliably affect AVFoundation captures.
    """
    result = frame

    # --- Brightness: shift pixel values ---
    bri = float(settings.get("brightness", 0))
    bri_def = float(defaults.get("brightness", 0))
    bri_delta = bri - bri_def
    if abs(bri_delta) > 0.5:
        result = cv2.convertScaleAbs(result, alpha=1.0, beta=bri_delta)

    # --- Contrast: scale around mid-gray ---
    con = float(settings.get("contrast", 40))
    con_def = float(defaults.get("contrast", 40))
    if abs(con - con_def) > 0.5:
        # Map 0..100 → alpha 0.5..1.5 (default 40 → 1.0)
        alpha = 0.5 + (con / 100.0)
        alpha_def = 0.5 + (con_def / 100.0)
        scale = alpha / max(alpha_def, 0.01)
        if abs(scale - 1.0) > 0.01:
            mean = np.mean(result)
            result = cv2.convertScaleAbs(result, alpha=scale, beta=mean * (1.0 - scale))

    # --- Saturation: scale HSV S channel ---
    sat = float(settings.get("saturation", 64))
    sat_def = float(defaults.get("saturation", 64))
    if abs(sat - sat_def) > 0.5 and sat_def > 0:
        scale = sat / sat_def
        if abs(scale - 1.0) > 0.01:
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, 255)
            result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # --- Gamma correction ---
    gam = float(settings.get("gamma", 300))
    gam_def = float(defaults.get("gamma", 300))
    if abs(gam - gam_def) > 0.5:
        # Map 100..500 → gamma 0.33..1.67 (300 → 1.0)
        gamma_val = gam / max(gam_def, 1.0)
        if abs(gamma_val - 1.0) > 0.01:
            inv_gamma = 1.0 / max(gamma_val, 0.01)
            lut = np.array(
                [((i / 255.0) ** inv_gamma) * 255 for i in range(256)],
                dtype=np.uint8,
            )
            result = cv2.LUT(result, lut)

    # --- Sharpness: unsharp mask ---
    shp = float(settings.get("sharpness", 50))
    shp_def = float(defaults.get("sharpness", 50))
    shp_delta = shp - shp_def
    if abs(shp_delta) > 0.5:
        # Positive delta → sharpen, negative → blur
        amount = shp_delta / 50.0  # -1.0 to +1.0 range
        blurred = cv2.GaussianBlur(result, (0, 0), 3)
        if amount > 0:
            result = cv2.addWeighted(result, 1.0 + amount, blurred, -amount, 0)
        else:
            result = cv2.addWeighted(result, 1.0 + amount, blurred, -amount, 0)

    return result


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
        self._picture_settings = clampCameraPictureSettings(config.picture_settings)
        self._device_settings = parseCameraDeviceSettingsForCapture(config.device_settings)
        self._device_defaults: dict[str, int | float | bool] = {}
        self._color_profile = clampCameraColorProfile(config.color_profile)
        self._picture_settings_lock = threading.Lock()
        self._device_settings_lock = threading.Lock()
        self._color_profile_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._cap_lock = threading.Lock()

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
            if self._cap is not None and isinstance(self.getCameraSource(), int):
                applied = apply_camera_device_settings(
                    self._cap,
                    normalized,
                    source=self.getCameraSource(),
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

    def describeDeviceControls(self) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
        source = self.getCameraSource()
        if not isinstance(source, int):
            return [], {}

        with self._cap_lock:
            if self._cap is not None:
                controls = describe_camera_device_controls(self._cap, source=source)
                current = read_camera_device_settings(self._cap)
                if controls:
                    macos_controls, macos_settings = _describe_macos_uvc_controls(source)
                    if macos_controls:
                        return macos_controls, macos_settings
                return controls, current

        return probe_camera_device_controls(source, self.getDeviceSettings())

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

    def _get_config_snapshot(self) -> tuple[int | str | None, bool, int, int, int]:
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
            )

    def start(self) -> None:
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
        use_sw_device_settings = platform.system() == "Darwin"

        while not self._stop_event.is_set():
            source, is_url, width, height, fps = self._get_config_snapshot()

            if self._reopen_event.is_set():
                self._reopen_event.clear()
                if cap is not None:
                    cap.release()
                    cap = None
                    self._cap = None

            if source is None:
                self.latest_frame = None
                time.sleep(0.1)
                continue

            if cap is None:
                with self._cap_lock:
                    cap = _open_capture_source(source)
                    self._cap = cap
                    if not is_url:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                        cap.set(cv2.CAP_PROP_FPS, fps)
                        applied_device_settings = apply_camera_device_settings(
                            cap,
                            self.getDeviceSettings(),
                            source=source,
                        )
                        if applied_device_settings:
                            with self._device_settings_lock:
                                self._device_settings = dict(applied_device_settings)
                        # Capture hardware defaults for software post-processing
                        if use_sw_device_settings and not self._device_defaults:
                            self._device_defaults = dict(
                                applied_device_settings or self.getDeviceSettings()
                            )
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                        self._cap = None
                        self.latest_frame = None
                        time.sleep(0.2)
                        continue

            with self._cap_lock:
                ret, frame = cap.read()
            if ret:
                frame = apply_camera_color_profile(frame, self.getColorProfile())
                frame = apply_picture_settings(frame, self.getPictureSettings())
                if use_sw_device_settings and self._device_defaults:
                    frame = _apply_device_settings_software(
                        frame, self.getDeviceSettings(), self._device_defaults
                    )
                self.latest_frame = CameraFrame(
                    raw=frame, annotated=None, results=[], timestamp=time.time()
                )
            else:
                # For URL sources, briefly wait then retry (stream may reconnect)
                time.sleep(0.1 if is_url else 0.05)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    self._cap = None

        if cap is not None:
            cap.release()
        self._cap = None
