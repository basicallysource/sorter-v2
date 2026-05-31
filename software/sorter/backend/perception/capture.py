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
        return PerceptionFrame(
            source_id=self._source_id,
            timestamp=float(ts),
            bgr=raw,
        )
