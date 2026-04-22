import threading
import time
from collections import deque
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
        from hardware.macos_camera_registry import refresh_macos_cameras as _refresh_macos_cameras
    except Exception:
        _apply_macos_uvc_controls_for_index = None
        _describe_macos_uvc_controls_for_index = None
        _refresh_macos_cameras = None
else:
    _apply_macos_uvc_controls_for_index = None
    _describe_macos_uvc_controls_for_index = None
    _refresh_macos_cameras = None


def _open_capture_source(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int) and platform.system() == "Darwin":
        return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
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
        current = read_camera_device_settings(cap)
        return controls, current or normalized_settings
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
                current = read_camera_device_settings(self._cap)
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

        while not self._stop_event.is_set():
            source, is_url, width, height, fps, fourcc = self._get_config_snapshot()

            if source != previous_source:
                previous_source = source
                open_failures = 0
                read_failures = 0
                next_open_attempt_at = 0.0

            if self._reopen_event.is_set():
                self._reopen_event.clear()
                if cap is not None:
                    cap.release()
                    cap = None
                    self._cap = None
                open_failures = 0
                read_failures = 0
                next_open_attempt_at = 0.0

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
                    candidate = _open_capture_source(source)
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

                    if not is_url:
                        if isinstance(fourcc, str) and len(fourcc) >= 4:
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
                        applied_device_settings = apply_camera_device_settings(
                            cap,
                            self.getDeviceSettings(),
                            source=source,
                        )
                        if applied_device_settings:
                            with self._device_settings_lock:
                                self._device_settings = dict(applied_device_settings)

            with self._cap_lock:
                ret, frame = cap.read()
            if ret:
                read_failures = 0
                frame = apply_camera_color_profile(frame, self.getColorProfile())
                frame = apply_picture_settings(frame, self.getPictureSettings())
                camera_frame = CameraFrame(
                    raw=frame, annotated=None, results=[], timestamp=time.time()
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
