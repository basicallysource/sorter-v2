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
        self._cached_annotated: tuple[float, CameraFrame] | None = None
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
            self._cached_annotated = None

    def clear_overlays(self) -> None:
        with self._lock:
            self._overlays.clear()
            self._cached_annotated = None

    def get_frame(self, annotated: bool = True) -> Optional[CameraFrame]:
        frame = self._device.latest_frame
        if frame is None:
            return None

        with self._lock:
            if not annotated or not self._overlays:
                return frame

            # Cache hit: same source timestamp
            if self._cached_annotated is not None and self._cached_annotated[0] == frame.timestamp:
                return self._cached_annotated[1]

            result_img = frame.annotated if frame.annotated is not None else frame.raw.copy()
            for overlay in self._overlays:
                result_img = overlay.annotate(result_img)

            result = CameraFrame(
                raw=frame.raw,
                annotated=result_img,
                results=[],
                timestamp=frame.timestamp,
            )
            self._cached_annotated = (frame.timestamp, result)
            return result
