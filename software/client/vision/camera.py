import threading
import time
from functools import lru_cache
from typing import Optional
import platform
import cv2
import numpy as np

from irl.config import CameraConfig, CameraPictureSettings, clampCameraPictureSettings
from .types import CameraFrame


def _open_capture_source(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int) and platform.system() == "Darwin":
        return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(source)


@lru_cache(maxsize=32)
def _gamma_lut(gamma: float) -> np.ndarray:
    exponent = 1.0 / max(gamma, 1e-6)
    table = np.array(
        [((value / 255.0) ** exponent) * 255.0 for value in range(256)],
        dtype=np.uint8,
    )
    return table


def apply_picture_settings(
    frame: np.ndarray,
    settings: CameraPictureSettings | None,
) -> np.ndarray:
    if settings is None:
        return frame

    current = clampCameraPictureSettings(settings)
    adjusted = frame

    if current.contrast != 1.0 or current.brightness != 0:
        adjusted = cv2.convertScaleAbs(
            adjusted,
            alpha=current.contrast,
            beta=current.brightness,
        )

    if current.gamma != 1.0:
        adjusted = cv2.LUT(adjusted, _gamma_lut(current.gamma))

    if current.saturation != 1.0:
        hsv = cv2.cvtColor(adjusted, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * current.saturation, 0, 255)
        adjusted = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

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
        self.latest_frame = None
        self._picture_settings = clampCameraPictureSettings(config.picture_settings)
        self._picture_settings_lock = threading.Lock()
        self._config_lock = threading.Lock()

    def setPictureSettings(self, settings: CameraPictureSettings) -> None:
        clamped = clampCameraPictureSettings(settings)
        with self._picture_settings_lock:
            self._picture_settings = clamped
            self._config.picture_settings = clamped

    def getPictureSettings(self) -> CameraPictureSettings:
        with self._picture_settings_lock:
            return clampCameraPictureSettings(self._picture_settings)

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
                cap = _open_capture_source(source)
                self._cap = cap
                if not is_url:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                    cap.set(cv2.CAP_PROP_FPS, fps)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    self._cap = None
                    self.latest_frame = None
                    time.sleep(0.2)
                    continue

            ret, frame = cap.read()
            if ret:
                frame = apply_picture_settings(frame, self.getPictureSettings())
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
