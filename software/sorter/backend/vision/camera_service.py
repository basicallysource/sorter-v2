"""Central camera registry, lifecycle management, and output delivery."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from defs.events import CameraName
from irl.config import (
    CameraColorProfile,
    CameraPictureSettings,
    CameraConfig,
    mkCameraConfig,
)
from .camera import CaptureThread, probe_camera_device_controls
from .camera_device import CameraDevice
from .camera_feed import CameraFeed

if TYPE_CHECKING:
    from global_config import GlobalConfig
    from irl.config import IRLConfig

# Maps role → IRLConfig attribute name
_ROLE_TO_CONFIG_ATTR: dict[str, str] = {
    "feeder": "feeder_camera",
    "classification_bottom": "classification_camera_bottom",
    "classification_top": "classification_camera_top",
    "c_channel_2": "c_channel_2_camera",
    "c_channel_3": "c_channel_3_camera",
    "classification_channel": "carousel_camera",
    "carousel": "carousel_camera",
}

# Health poll interval. Video is streamed through the MJPEG endpoint only; this
# lightweight loop just surfaces camera status changes over the control socket.
_HEALTH_POLL_INTERVAL_S = 0.5


class CameraService:
    """Owns camera devices, live feeds, and health tracking."""

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig) -> None:
        self._irl_config = irl_config
        self._gc = gc
        self._camera_layout: str = getattr(irl_config, "camera_layout", "default")
        self._disabled_cameras: set[str] = set(gc.disable_video_streams)

        self._devices: dict[str, CameraDevice] = {}
        self._feeds: dict[str, CameraFeed] = {}

        self._build_devices_and_feeds()

        self._health_thread: threading.Thread | None = None
        self._health_stop = threading.Event()

        # Health tracking
        self._last_health: dict[str, str] = {}
        self._health_lock = threading.Lock()
        self._health_event_callback = None

    def _build_devices_and_feeds(self) -> None:
        irl = self._irl_config

        def _is_real_camera(cfg) -> bool:
            return cfg is not None and (cfg.url is not None or cfg.device_index >= 0)

        if self._camera_layout == "split_feeder":
            if irl.c_channel_2_camera is not None:
                self._add_device_feed("c_channel_2", irl.c_channel_2_camera)
            if irl.c_channel_3_camera is not None:
                self._add_device_feed("c_channel_3", irl.c_channel_3_camera)
            if irl.carousel_camera is not None:
                uses_c4 = bool(
                    getattr(getattr(irl, "machine_setup", None), "uses_classification_channel", False)
                )
                aux_role = "classification_channel" if uses_c4 else "carousel"
                self._add_device_feed(aux_role, irl.carousel_camera)
                if uses_c4:
                    device = self._devices[aux_role]
                    self._devices["carousel"] = device
                    self._feeds["carousel"] = CameraFeed("carousel", device)
            # feeder alias → c_channel_2 device (fallback for code that expects "feeder")
            c2 = self._devices.get("c_channel_2")
            if c2 is not None:
                self._feeds["feeder"] = CameraFeed("feeder", c2)
            else:
                self._add_device_feed("feeder", irl.feeder_camera)
            # Classification cameras optional in split_feeder
            if _is_real_camera(irl.classification_camera_top):
                self._add_device_feed("classification_top", irl.classification_camera_top)
            if _is_real_camera(irl.classification_camera_bottom):
                self._add_device_feed("classification_bottom", irl.classification_camera_bottom)
        else:
            if "feeder" in self._disabled_cameras:
                raise RuntimeError("Cannot disable feeder camera — it is required for operation")
            self._add_device_feed("feeder", irl.feeder_camera)

            if "classification_bottom" in self._disabled_cameras and "classification_top" in self._disabled_cameras:
                raise RuntimeError("Cannot disable both classification cameras — at least one is required")

            if "classification_bottom" not in self._disabled_cameras:
                self._add_device_feed("classification_bottom", irl.classification_camera_bottom)
            if "classification_top" not in self._disabled_cameras:
                self._add_device_feed("classification_top", irl.classification_camera_top)

    def _add_device_feed(self, role: str, config: CameraConfig) -> None:
        device = CameraDevice(role, config)
        self._devices[role] = device
        self._feeds[role] = CameraFeed(role, device)

    # ---- Public accessors ----

    @property
    def devices(self) -> dict[str, CameraDevice]:
        return self._devices

    @property
    def feeds(self) -> dict[str, CameraFeed]:
        return self._feeds

    @property
    def camera_layout(self) -> str:
        return self._camera_layout

    def get_feed(self, role: str) -> Optional[CameraFeed]:
        return self._feeds.get(role)

    def get_device(self, role: str) -> Optional[CameraDevice]:
        return self._devices.get(role)

    def _device_for_role(self, role: str) -> Optional[CameraDevice]:
        device = self._devices.get(role)
        if device is not None:
            return device
        feed = self._feeds.get(role)
        if feed is not None:
            return feed.device
        return None

    def get_capture_thread_for_role(self, role: str) -> Optional[CaptureThread]:
        device = self._device_for_role(role)
        if device is None:
            return None
        return device.capture_thread

    def get_device_settings_for_role(self, role: str) -> dict[str, int | float | bool] | None:
        device = self._device_for_role(role)
        if device is None:
            return None
        return device.get_device_settings()

    def describe_device_controls_for_role(
        self,
        role: str,
    ) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]] | None:
        device = self._device_for_role(role)
        if device is None:
            return None
        return device.describe_device_controls()

    def inspect_device_controls_for_role(
        self,
        role: str,
        source: int | str | None,
        saved_settings: dict[str, int | float | bool],
    ) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
        device = self._device_for_role(role)
        if device is not None:
            controls, live_settings = device.describe_device_controls()
            return controls, live_settings or dict(saved_settings)
        if isinstance(source, int):
            controls, current_settings = probe_camera_device_controls(source, saved_settings)
            return controls, current_settings or dict(saved_settings)
        return [], dict(saved_settings)

    # ---- Health ----

    def get_health_status(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for role, feed in self._feeds.items():
            device = feed.device
            result[role] = {
                "status": device.health.value,
                "last_frame_at": device.last_frame_at,
            }
        return result

    def get_health_map(self) -> dict[str, str]:
        return {role: feed.device.health.value for role, feed in self._feeds.items()}

    def set_health_event_callback(self, callback) -> None:
        self._health_event_callback = callback

    def _check_health_changes(self) -> None:
        current = self.get_health_map()
        with self._health_lock:
            if current != self._last_health:
                self._last_health = dict(current)
                if self._health_event_callback is not None:
                    self._health_event_callback(current)

    # ---- Source management ----

    def set_camera_source_for_role(
        self, role: str, source: int | str | None
    ) -> bool:
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if config_attr is None:
            return False

        config = getattr(self._irl_config, config_attr, None)
        if config is None:
            config = mkCameraConfig(device_index=-1)
            setattr(self._irl_config, config_attr, config)

        if isinstance(source, str):
            config.url = source
            config.device_index = -1
        elif isinstance(source, int):
            config.url = None
            config.device_index = source
        else:
            config.url = None
            config.device_index = -1

        device = self._devices.get(role)
        if device is None:
            if source is None:
                return True
            self._add_device_feed(role, config)
            device = self._devices[role]
            if self._started:
                device.start()
        else:
            device.set_source(source)

        # feeder alias in split_feeder mode
        if self._camera_layout == "split_feeder" and role == "c_channel_2":
            self._feeds["feeder"] = CameraFeed("feeder", device)
        if self._camera_layout == "split_feeder" and role == "classification_channel":
            self._devices["carousel"] = device
            self._feeds["carousel"] = CameraFeed("carousel", device)

        return True

    def set_picture_settings_for_role(
        self, role: str, settings: CameraPictureSettings
    ) -> bool:
        device = self._device_for_role(role)
        if device is None:
            return False
        device.set_picture_settings(settings)
        return True

    def set_device_settings_for_role(
        self,
        role: str,
        settings: dict[str, int | float | bool] | None,
        *,
        persist: bool = False,
    ) -> dict[str, int | float | bool] | None:
        device = self._device_for_role(role)
        if device is None:
            return None
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if persist and config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.device_settings = dict(settings or {})
        return device.set_device_settings(settings, persist=persist)

    def clear_persisted_device_settings_for_role(self, role: str) -> bool:
        device = self._device_for_role(role)
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if config_attr is None:
            return False
        config = getattr(self._irl_config, config_attr, None)
        if config is not None:
            config.device_settings = {}
        if device is not None:
            device.config.device_settings = {}
        return True

    def set_capture_mode_for_role(
        self,
        role: str,
        *,
        width: int,
        height: int,
        fps: int,
        fourcc: str | None = None,
    ) -> bool:
        device = self._device_for_role(role)
        if device is None:
            return False
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.width = width
                config.height = height
                config.fps = fps
                config.fourcc = fourcc
        device.set_capture_mode(width=width, height=height, fps=fps, fourcc=fourcc)
        return True

    def get_capture_mode_for_role(self, role: str) -> dict[str, int | str | None] | None:
        device = self._device_for_role(role)
        if device is None:
            return None
        return device.get_capture_mode()

    def set_color_profile_for_role(
        self, role: str, profile: CameraColorProfile | None
    ) -> bool:
        device = self._device_for_role(role)
        if device is None:
            return False
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.color_profile = profile
        device.set_color_profile(profile)
        return True

    # ---- Health polling ----

    @property
    def active_cameras(self) -> List[CameraName]:
        if self._camera_layout == "split_feeder":
            cams: list[CameraName] = [CameraName.c_channel_2, CameraName.c_channel_3, CameraName.carousel]
            if "classification_top" in self._devices:
                cams.append(CameraName.classification_top)
            if "classification_bottom" in self._devices:
                cams.append(CameraName.classification_bottom)
            return cams
        return [CameraName.feeder, CameraName.classification_bottom, CameraName.classification_top]

    def _health_poll_loop(self) -> None:
        while not self._health_stop.is_set():
            prof = self._gc.profiler
            prof.hit("camera_service.health_thread.calls")
            with prof.timer("camera_service.health_thread.total_ms"):
                # Health is derived from the capture thread's latest frame age.
                # No JPEG encoding happens on this thread.
                self._check_health_changes()

            self._health_stop.wait(_HEALTH_POLL_INTERVAL_S)

    # ---- Lifecycle ----

    _started: bool = False

    def _unique_devices(self) -> list[CameraDevice]:
        # A single CameraDevice can be registered under multiple role keys
        # (e.g. classification_channel + carousel alias). Dedupe by identity
        # so we don't start/stop the same CaptureThread twice — double-start
        # races two threads on the same /dev/videoN, and the loser spams
        # failed-open retries that stall the device's UVC control endpoint.
        seen: set[int] = set()
        out: list[CameraDevice] = []
        for device in self._devices.values():
            if id(device) in seen:
                continue
            seen.add(id(device))
            out.append(device)
        return out

    def start(self) -> None:
        self._started = True
        for device in self._unique_devices():
            device.start()

        self._health_stop.clear()
        self._health_thread = threading.Thread(
            target=self._health_poll_loop, daemon=True, name="camera-service-health"
        )
        self._health_thread.start()

    def stop(self) -> None:
        self._started = False
        self._health_stop.set()
        if self._health_thread:
            self._health_thread.join(timeout=2.0)
        for device in self._unique_devices():
            device.stop()
