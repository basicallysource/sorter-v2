"""Central camera registry, lifecycle management, and output delivery."""

from __future__ import annotations

import base64
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

import cv2
import numpy as np

from defs.events import CameraName, FrameData, FrameEvent, FrameResultData
from irl.config import (
    CameraColorProfile,
    CameraPictureSettings,
    CameraConfig,
    mkCameraConfig,
)
from .camera import CaptureThread
from .camera_device import CameraDevice, DeviceHealth
from .camera_feed import CameraFeed
from .types import CameraFrame

if TYPE_CHECKING:
    from global_config import GlobalConfig
    from irl.config import IRLConfig

FRAME_ENCODE_INTERVAL_MS = 100

# Maps role → IRLConfig attribute name
_ROLE_TO_CONFIG_ATTR: dict[str, str] = {
    "feeder": "feeder_camera",
    "classification_bottom": "classification_camera_bottom",
    "classification_top": "classification_camera_top",
    "c_channel_2": "c_channel_2_camera",
    "c_channel_3": "c_channel_3_camera",
    "carousel": "carousel_camera",
}

# Health poll interval
_HEALTH_POLL_INTERVAL_S = 2.0


class CameraService:
    """Owns camera devices and feeds, frame encoding, and health tracking."""

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig) -> None:
        self._irl_config = irl_config
        self._gc = gc
        self._camera_layout: str = getattr(irl_config, "camera_layout", "default")
        self._disabled_cameras: set[str] = set(gc.disable_video_streams)

        self._devices: dict[str, CameraDevice] = {}
        self._feeds: dict[str, CameraFeed] = {}

        self._build_devices_and_feeds()

        # Frame encode loop state
        self._cached_frame_events: List[FrameEvent] = []
        self._cached_frame_events_lock = threading.Lock()
        self._frame_encode_thread: threading.Thread | None = None
        self._frame_encode_stop = threading.Event()

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
                self._add_device_feed("carousel", irl.carousel_camera)
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

    def get_capture_thread_for_role(self, role: str) -> Optional[CaptureThread]:
        device = self._devices.get(role)
        if device is None:
            # feeder alias: in split_feeder mode feeder feed maps to c_channel_2 device
            feed = self._feeds.get(role)
            if feed is not None:
                return feed.device.capture_thread
            return None
        return device.capture_thread

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

        return True

    def set_picture_settings_for_role(
        self, role: str, settings: CameraPictureSettings
    ) -> bool:
        device = self._devices.get(role)
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
        device = self._devices.get(role)
        if device is None:
            return None
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if persist and config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.device_settings = dict(settings or {})
        return device.set_device_settings(settings, persist=persist)

    def set_color_profile_for_role(
        self, role: str, profile: CameraColorProfile | None
    ) -> bool:
        device = self._devices.get(role)
        if device is None:
            return False
        config_attr = _ROLE_TO_CONFIG_ATTR.get(role)
        if config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.color_profile = profile
        device.set_color_profile(profile)
        return True

    # ---- Frame encode loop ----

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

    def _encode_frame(self, frame: np.ndarray) -> str:
        prof = self._gc.profiler
        with prof.timer("camera_service.encode_frame.imencode_ms"):
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with prof.timer("camera_service.encode_frame.base64_ms"):
            return base64.b64encode(buffer).decode("utf-8")

    def get_frame_event(self, camera_name: CameraName) -> Optional[FrameEvent]:
        prof = self._gc.profiler
        prof.hit(f"camera_service.get_frame_event.calls.{camera_name.value}")
        prof.startTimer("camera_service.get_frame_event.total_ms")

        feed = self._feeds.get(camera_name.value)
        if feed is None:
            prof.endTimer("camera_service.get_frame_event.total_ms")
            return None

        frame = feed.get_frame(annotated=True)
        if frame is None:
            prof.endTimer("camera_service.get_frame_event.total_ms")
            return None

        results_data = [
            FrameResultData(
                class_id=r.class_id,
                class_name=r.class_name,
                confidence=r.confidence,
                bbox=r.bbox,
            )
            for r in frame.results
        ]

        raw_b64 = self._encode_frame(frame.raw)
        annotated_b64 = (
            self._encode_frame(frame.annotated) if frame.annotated is not None else None
        )

        event = FrameEvent(
            tag="frame",
            data=FrameData(
                camera=camera_name,
                timestamp=frame.timestamp,
                raw=raw_b64,
                annotated=annotated_b64,
                results=results_data,
            ),
        )
        prof.endTimer("camera_service.get_frame_event.total_ms")
        return event

    def get_all_frame_events(self) -> List[FrameEvent]:
        with self._cached_frame_events_lock:
            return list(self._cached_frame_events)

    def _frame_encode_loop(self) -> None:
        while not self._frame_encode_stop.is_set():
            prof = self._gc.profiler
            prof.hit("camera_service.frame_encode_thread.calls")
            with prof.timer("camera_service.frame_encode_thread.total_ms"):
                events: List[FrameEvent] = []
                for camera in self.active_cameras:
                    event = self.get_frame_event(camera)
                    if event:
                        events.append(event)
                with self._cached_frame_events_lock:
                    self._cached_frame_events = events

            # Check health on each encode cycle (~100ms)
            self._check_health_changes()

            self._frame_encode_stop.wait(FRAME_ENCODE_INTERVAL_MS / 1000.0)

    # ---- Lifecycle ----

    _started: bool = False

    def start(self) -> None:
        self._started = True
        for device in self._devices.values():
            device.start()

        self._frame_encode_stop.clear()
        self._frame_encode_thread = threading.Thread(
            target=self._frame_encode_loop, daemon=True, name="camera-service-encode"
        )
        self._frame_encode_thread.start()

    def stop(self) -> None:
        self._started = False
        self._frame_encode_stop.set()
        if self._frame_encode_thread:
            self._frame_encode_thread.join(timeout=2.0)
        for device in self._devices.values():
            device.stop()
