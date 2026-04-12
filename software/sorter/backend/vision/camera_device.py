"""Thin wrapper around CaptureThread with health tracking."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from irl.config import CameraConfig, CameraColorProfile, CameraPictureSettings
from .camera import CaptureThread
from .types import CameraFrame

# Health thresholds (seconds since last frame)
_ONLINE_MAX_AGE = 2.0
_RECONNECTING_MAX_AGE = 10.0


class DeviceHealth(str, Enum):
    online = "online"
    offline = "offline"
    reconnecting = "reconnecting"
    unassigned = "unassigned"


class CameraDevice:
    """Wraps a CaptureThread with health derivation.

    A device represents a single physical camera source.
    """

    def __init__(self, device_id: str, config: CameraConfig) -> None:
        self.device_id = device_id
        self._capture = CaptureThread(device_id, config)
        self._config = config

    @property
    def capture_thread(self) -> CaptureThread:
        return self._capture

    @property
    def config(self) -> CameraConfig:
        return self._config

    @property
    def latest_frame(self) -> Optional[CameraFrame]:
        return self._capture.latest_frame

    @property
    def last_frame_at(self) -> Optional[float]:
        frame = self._capture.latest_frame
        return frame.timestamp if frame is not None else None

    @property
    def frame_age_s(self) -> Optional[float]:
        ts = self.last_frame_at
        if ts is None:
            return None
        return time.time() - ts

    @property
    def health(self) -> DeviceHealth:
        source = self._capture.getCameraSource()
        if source is None:
            return DeviceHealth.unassigned

        frame = self._capture.latest_frame
        if frame is None:
            return DeviceHealth.reconnecting

        age = time.time() - frame.timestamp
        if age < _ONLINE_MAX_AGE:
            return DeviceHealth.online
        if age < _RECONNECTING_MAX_AGE:
            return DeviceHealth.reconnecting
        return DeviceHealth.offline

    # ---- Delegate CaptureThread lifecycle ----

    def start(self) -> None:
        self._capture.start()

    def stop(self) -> None:
        self._capture.stop()

    def set_source(self, source: int | str | None) -> None:
        self._capture.setCameraSource(source)

    # ---- Delegate settings ----

    def set_picture_settings(self, settings: CameraPictureSettings) -> None:
        self._capture.setPictureSettings(settings)

    def get_picture_settings(self) -> CameraPictureSettings:
        return self._capture.getPictureSettings()

    def set_color_profile(self, profile: CameraColorProfile | None) -> None:
        self._capture.setColorProfile(profile)

    def get_color_profile(self) -> CameraColorProfile:
        return self._capture.getColorProfile()

    def set_device_settings(
        self,
        settings: dict[str, int | float | bool] | None,
        *,
        persist: bool = False,
    ) -> dict[str, int | float | bool]:
        return self._capture.setDeviceSettings(settings, persist=persist)

    def get_device_settings(self) -> dict[str, int | float | bool]:
        return self._capture.getDeviceSettings()

    def describe_device_controls(self) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
        return self._capture.describeDeviceControls()
