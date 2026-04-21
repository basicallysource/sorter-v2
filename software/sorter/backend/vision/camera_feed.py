"""Feed: role → device + overlay pipeline + frame access."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional, Protocol
import numpy as np

from .camera_device import CameraDevice, DeviceHealth
from .types import CameraFrame

if TYPE_CHECKING:
    pass


class FrameOverlay(Protocol):
    """Single annotation pass over a frame."""

    def annotate(self, frame: np.ndarray) -> np.ndarray: ...


class CameraFeed:
    """Maps a camera role to a device, with an ordered overlay pipeline.

    Each feed produces frames by reading from its device and composing
    overlays in registration order.
    """

    def __init__(self, role: str, device: CameraDevice) -> None:
        self.role = role
        self._device = device
        self._overlays: list[FrameOverlay] = []
        self._cached_annotated: dict[tuple[float, tuple[str, ...]], CameraFrame] = {}
        self._lock = threading.Lock()

    @property
    def device(self) -> CameraDevice:
        return self._device

    @property
    def health(self) -> DeviceHealth:
        return self._device.health

    def add_overlay(self, overlay: FrameOverlay) -> None:
        with self._lock:
            self._overlays.append(overlay)
            self._cached_annotated.clear()

    def clear_overlays(self) -> None:
        with self._lock:
            self._overlays.clear()
            self._cached_annotated.clear()

    def get_frame(
        self,
        annotated: bool = True,
        exclude_categories: Optional[frozenset[str]] = None,
    ) -> Optional[CameraFrame]:
        frame = self._device.latest_frame
        if frame is None:
            return None

        with self._lock:
            if not annotated or not self._overlays:
                return frame

            active_overlays = [
                ov for ov in self._overlays
                if not exclude_categories or getattr(ov, "category", "") not in exclude_categories
            ]
            if not active_overlays:
                return frame

            exclude_key = tuple(sorted(exclude_categories or ()))
            cache_key = (float(frame.timestamp), exclude_key)
            cached = self._cached_annotated.get(cache_key)
            if cached is not None:
                return cached
            # New frame timestamp: older rendered variants can be discarded.
            if self._cached_annotated:
                stale_keys = [
                    key
                    for key in self._cached_annotated.keys()
                    if key[0] != float(frame.timestamp)
                ]
                for key in stale_keys:
                    self._cached_annotated.pop(key, None)

            result_img = frame.annotated if frame.annotated is not None else frame.raw.copy()
            for overlay in active_overlays:
                result_img = overlay.annotate(result_img)

            result = CameraFrame(
                raw=frame.raw,
                annotated=result_img,
                results=[],
                timestamp=frame.timestamp,
            )
            self._cached_annotated[cache_key] = result
            return result
