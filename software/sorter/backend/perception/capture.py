"""Per-camera frame access for the perception package.

A ``CaptureWorker`` is a thin, source_id-tagged adapter over an existing
``vision.camera.CaptureThread`` (the OS-level V4L2 reader that
``CameraService`` already starts for previews). Perception does not open
its own V4L2 device — the camera is shared with the preview path. What
perception owns is:

  - the ``source_id`` (immutable, set at construction),
  - the single ``CaptureThread`` reference it reads from (immutable),
  - the assertion that those two stay consistent.

The ``InferenceWorker`` only ever sees the ``CaptureWorker``; it never
holds a role-string -> thread dict lookup. Combined with the immutable
construction-time wiring in ``PerceptionService``, this is what makes
"wrong-camera-on-wrong-NPU-core" impossible without an explicit code
change to rewire it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np


@dataclass(frozen=True)
class PerceptionFrame:
    """Frame as seen by the perception package.

    Carries the same ``source_id`` as the ``CaptureWorker`` that produced
    it — the ``InferenceWorker`` asserts the round-trip on every read.
    """

    source_id: str
    timestamp: float
    bgr: np.ndarray   # HxWx3 uint8, BGR, original resolution
    inference_bgr: Optional[np.ndarray] = None
    inference_sensor_rect: Optional[tuple[float, float, float, float]] = None
    inference_scale_backend: Optional[str] = None

    @property
    def inference_image(self) -> np.ndarray:
        return self.inference_bgr if self.inference_bgr is not None else self.bgr

    @property
    def sensor_size(self) -> tuple[int, int]:
        h, w = self.bgr.shape[:2]
        return int(w), int(h)

    @property
    def inference_rect(self) -> tuple[float, float, float, float]:
        if self.inference_sensor_rect is not None:
            x1, y1, x2, y2 = self.inference_sensor_rect
            return float(x1), float(y1), float(x2), float(y2)
        w, h = self.sensor_size
        return 0.0, 0.0, float(w), float(h)

    def inference_bbox_to_sensor(self, bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        image = self.inference_image
        ih, iw = image.shape[:2]
        if iw <= 0 or ih <= 0:
            return (0, 0, 0, 0)
        rx1, ry1, rx2, ry2 = self.inference_rect
        scale_x = (rx2 - rx1) / float(iw)
        scale_y = (ry2 - ry1) / float(ih)
        sensor_w, sensor_h = self.sensor_size
        x1 = int(round(rx1 + float(bbox[0]) * scale_x))
        y1 = int(round(ry1 + float(bbox[1]) * scale_y))
        x2 = int(round(rx1 + float(bbox[2]) * scale_x))
        y2 = int(round(ry1 + float(bbox[3]) * scale_y))
        return (
            max(0, min(sensor_w, x1)),
            max(0, min(sensor_h, y1)),
            max(0, min(sensor_w, x2)),
            max(0, min(sensor_h, y2)),
        )


class CaptureLike(Protocol):
    """The single attribute we need from ``vision.camera.CaptureThread``.

    Typed as a Protocol so tests can pass a stub without importing the
    full CaptureThread machinery.
    """

    latest_frame: object  # actually CameraFrame | None — typed loosely so
                          # the test stubs don't have to match the dataclass.


class CaptureWorker:
    """Source_id-tagged view over an existing capture thread."""

    __slots__ = ("_source_id", "_capture", "_last_frame_ts")

    def __init__(self, source_id: str, capture_thread: CaptureLike) -> None:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("CaptureWorker requires a non-empty string source_id")
        self._source_id = source_id
        self._capture = capture_thread
        self._last_frame_ts: float = -1.0

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def capture_thread(self) -> CaptureLike:
        """The underlying capture thread — exposed for read-only introspection
        (the perception-debug overlay reads camera specs off it)."""
        return self._capture

    def latest_frame(self) -> Optional[PerceptionFrame]:
        """Snapshot of the most recent frame the capture thread has produced.

        Returns ``None`` when:
        - the capture thread has not yet produced a frame, or
        - the underlying frame's ``raw`` ndarray is None.

        Returns the same frame across calls if the capture thread has not
        produced a new one — callers should compare ``timestamp`` against
        their own ``_last_frame_ts`` to skip redundant work.
        """
        frame = getattr(self._capture, "latest_frame", None)
        if frame is None:
            return None
        raw = getattr(frame, "raw", None)
        ts = getattr(frame, "timestamp", None)
        if raw is None or ts is None:
            return None
        inference_bgr = None
        inference_sensor_rect = None
        inference_scale_backend = None
        latest_detection = getattr(self._capture, "latest_detection_frame", None)
        detection_frame = None
        if callable(latest_detection):
            try:
                detection_frame = latest_detection()
            except Exception:
                detection_frame = None
        if detection_frame is not None:
            candidate = getattr(detection_frame, "raw", None)
            if candidate is not None:
                inference_bgr = candidate
                rect = getattr(detection_frame, "sensor_rect", None)
                if isinstance(rect, (list, tuple)) and len(rect) == 4:
                    inference_sensor_rect = (
                        float(rect[0]),
                        float(rect[1]),
                        float(rect[2]),
                        float(rect[3]),
                    )
                backend = getattr(detection_frame, "scale_backend", None)
                if isinstance(backend, str) and backend:
                    inference_scale_backend = backend
        return PerceptionFrame(
            source_id=self._source_id,
            timestamp=float(ts),
            bgr=raw,
            inference_bgr=inference_bgr,
            inference_sensor_rect=inference_sensor_rect,
            inference_scale_backend=inference_scale_backend,
        )
