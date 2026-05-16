"""Feed: role → device + overlay pipeline + frame access."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol
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

    When ``pinned_ts_provider`` is set, ``get_frame(annotated=True)`` pulls
    the ring-buffer frame whose timestamp matches the provider's value
    instead of the device's ``latest_frame``. This is how the encode path
    keeps overlay positions in sync with the frame the detector actually
    ran on — without it, the bbox lags behind the moving piece by one
    detection cadence.
    """

    def __init__(
        self,
        role: str,
        device: CameraDevice,
        *,
        pinned_ts_provider: Optional[Callable[[], Optional[float]]] = None,
    ) -> None:
        self.role = role
        self._device = device
        self._overlays: list[FrameOverlay] = []
        self._cached_annotated: tuple[tuple[float, bool], CameraFrame] | None = None
        self._pinned_ts_provider = pinned_ts_provider
        self._lock = threading.Lock()

    def set_pinned_ts_provider(
        self,
        provider: Optional[Callable[[], Optional[float]]],
    ) -> None:
        """Install (or remove) the detection-frame-timestamp provider."""
        with self._lock:
            self._pinned_ts_provider = provider
            self._cached_annotated = None

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

    def describe_overlays(
        self,
        exclude_categories: Optional[frozenset[str]] = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            active_overlays = [
                ov for ov in self._overlays
                if not exclude_categories or getattr(ov, "category", "") not in exclude_categories
            ]
            descriptions: list[dict[str, Any]] = []
            for overlay in active_overlays:
                category = str(getattr(overlay, "category", ""))
                metadata_fn = getattr(overlay, "metadata", None)
                if callable(metadata_fn):
                    try:
                        metadata = metadata_fn()
                    except Exception:
                        metadata = None
                    if isinstance(metadata, list):
                        descriptions.extend(item for item in metadata if isinstance(item, dict))
                        continue
                    if isinstance(metadata, dict):
                        descriptions.append(metadata)
                        continue
                descriptions.append({
                    "type": type(overlay).__name__,
                    "category": category,
                })
            return descriptions

    def get_frame(
        self,
        annotated: bool = True,
        exclude_categories: Optional[frozenset[str]] = None,
        color_correct: bool = True,
    ) -> Optional[CameraFrame]:
        latest = self._device.latest_frame
        if latest is None:
            return None

        # Default to the latest frame; switch to a pinned ring-buffer frame
        # only when we know overlays will run AND a pinned timestamp is
        # available. Raw (annotated=False) reads always use latest_frame.
        frame = latest
        if annotated and self._overlays and self._pinned_ts_provider is not None:
            try:
                pinned_ts = self._pinned_ts_provider()
            except Exception:
                pinned_ts = None
            if pinned_ts is not None and pinned_ts != latest.timestamp:
                pinned_frame = self._device.frame_at_or_before(float(pinned_ts))
                if pinned_frame is not None:
                    frame = pinned_frame

        with self._lock:
            raw = frame.raw if color_correct or frame.uncorrected_raw is None else frame.uncorrected_raw
            if not annotated or not self._overlays:
                if raw is frame.raw:
                    return frame
                return CameraFrame(
                    raw=raw,
                    annotated=None,
                    results=frame.results,
                    timestamp=frame.timestamp,
                    segmentation_map=frame.segmentation_map,
                    uncorrected_raw=frame.uncorrected_raw,
                )

            active_overlays = [
                ov for ov in self._overlays
                if not exclude_categories or getattr(ov, "category", "") not in exclude_categories
            ]
            if not active_overlays:
                if raw is frame.raw:
                    return frame
                return CameraFrame(
                    raw=raw,
                    annotated=None,
                    results=frame.results,
                    timestamp=frame.timestamp,
                    segmentation_map=frame.segmentation_map,
                    uncorrected_raw=frame.uncorrected_raw,
                )

            # Cache only the default (unfiltered) path — keeps the hot loop fast
            # without per-filter cache bookkeeping.
            cache_eligible = not exclude_categories
            cache_key = (frame.timestamp, bool(color_correct))
            if (
                cache_eligible
                and self._cached_annotated is not None
                and self._cached_annotated[0] == cache_key
            ):
                return self._cached_annotated[1]

            result_img = raw.copy()
            for overlay in active_overlays:
                result_img = overlay.annotate(result_img)

            result = CameraFrame(
                raw=raw,
                annotated=result_img,
                results=frame.results,
                timestamp=frame.timestamp,
                segmentation_map=frame.segmentation_map,
                uncorrected_raw=frame.uncorrected_raw,
            )
            if cache_eligible:
                self._cached_annotated = (cache_key, result)
            return result
