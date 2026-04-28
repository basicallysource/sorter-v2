"""Temporary adapter to existing ``backend.vision.camera_service``.

Will be replaced when ``rt/hardware/`` lands and CameraService is fully
ported into the new runtime namespace. Until then, ``CameraFeed`` reads
the latest CameraFrame from the legacy service and wraps it as a
``FeedFrame``. No capture thread is started here - the legacy service
already owns that lifecycle.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from rt.contracts.feed import FeedFrame, FeedPurpose, Zone


class CameraFeed:
    """Legacy-bridge Feed implementation backed by vision.camera_service."""

    def __init__(
        self,
        feed_id: str,
        purpose: FeedPurpose,
        camera_id: str,
        camera_service: Any,
        zone: Zone,
        fps_target: float = 10.0,
    ) -> None:
        self.feed_id = feed_id
        self.purpose: FeedPurpose = purpose
        self.camera_id = camera_id
        self._service = camera_service
        self._zone = zone
        self._fps_target = float(fps_target)
        self._last_ts: float | None = None
        self._frame_seq = 0
        self._lock = threading.Lock()
        self._observed_fps = 0.0

    @property
    def zone(self) -> Zone:
        return self._zone

    def latest(self) -> FeedFrame | None:
        raw, ts = self._read_from_service()
        if raw is None:
            return None
        with self._lock:
            if self._last_ts is not None and ts <= self._last_ts:
                # Same underlying frame as before; caller uses frame_seq to skip.
                pass
            else:
                if self._last_ts is not None and ts > self._last_ts:
                    dt = ts - self._last_ts
                    if dt > 0:
                        self._observed_fps = 1.0 / dt
                self._last_ts = ts
                self._frame_seq += 1
            seq = self._frame_seq
            timestamp = float(ts)
        return FeedFrame(
            feed_id=self.feed_id,
            camera_id=self.camera_id,
            raw=raw,
            gray=None,
            timestamp=timestamp,
            monotonic_ts=time.monotonic(),
            frame_seq=seq,
        )

    def fps(self) -> float:
        return self._observed_fps if self._observed_fps > 0 else self._fps_target

    def _read_from_service(self) -> tuple[np.ndarray | None, float]:
        """Extract (raw_frame, wall_timestamp) from the legacy CameraService."""
        service = self._service
        feed = None
        get_feed = getattr(service, "get_feed", None)
        if callable(get_feed):
            feed = get_feed(self.camera_id)
        if feed is None:
            return None, 0.0
        # CameraFeed (legacy) exposes a `get_frame(annotated, exclude_categories)`
        # method that returns a CameraFrame with .raw and .timestamp.
        get_frame = getattr(feed, "get_frame", None)
        if callable(get_frame):
            try:
                cframe = get_frame(annotated=False)
            except TypeError:
                cframe = get_frame()
            if cframe is None:
                return None, 0.0
            raw = getattr(cframe, "raw", None)
            ts = float(getattr(cframe, "timestamp", 0.0) or 0.0)
            return raw, ts
        # Fallback: direct device.latest_frame access.
        device = getattr(feed, "device", None) or getattr(feed, "_device", None)
        if device is not None:
            cframe = getattr(device, "latest_frame", None)
            if cframe is not None:
                raw = getattr(cframe, "raw", None)
                ts = float(getattr(cframe, "timestamp", 0.0) or 0.0)
                return raw, ts
        return None, 0.0


__all__ = ["CameraFeed"]
