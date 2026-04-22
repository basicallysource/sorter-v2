"""Test-only detector helpers.

These helpers are intentionally NOT registered in the global DETECTORS
registry. They exist so unit tests for the PerceptionPipeline / runner /
config-factory wiring can feed synthetic detections without needing a real
detector implementation.

Tests that need factory-level wiring (``build_pipeline_from_config`` with a
``{"key": ...}`` entry) should register FakeDetector locally via a fixture
or via ``temporary_detector``, and unregister it in teardown so no global
state leaks between tests.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Sequence

from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame, Zone
from rt.contracts.registry import DETECTORS


DetectionsFor = Callable[[FeedFrame, Zone], Sequence[Detection]]


class FakeDetector:
    """Scripted Detector that yields canned detections per frame.

    Parameters
    ----------
    fixed_detections:
        Detections returned for every frame. Mutually exclusive with
        ``detections_for``.
    detections_for:
        Callable ``(frame, zone) -> sequence[Detection]`` for per-frame
        scripted output. Takes precedence over ``fixed_detections``.
    key:
        Registry key used on the instance. Defaults to ``"fake"``. Only
        relevant when the detector is temporarily registered.
    """

    def __init__(
        self,
        fixed_detections: Sequence[Detection] | None = None,
        detections_for: DetectionsFor | None = None,
        *,
        key: str = "fake",
    ) -> None:
        self.key = key
        self._fixed: tuple[Detection, ...] = tuple(fixed_detections or ())
        self._script = detections_for

    def requires(self) -> frozenset[str]:
        return frozenset()

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch:
        t0 = time.perf_counter()
        if self._script is not None:
            dets = tuple(self._script(frame, zone))
        else:
            dets = self._fixed
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=dets,
            algorithm=self.key,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def reset(self) -> None:
        return None

    def stop(self) -> None:
        return None


@contextmanager
def temporary_detector(key: str, factory) -> Iterator[None]:
    """Register a detector factory under ``key`` only for the ``with`` block.

    Removes the entry on exit, even on test failure, so other tests don't
    see leaked registry state.
    """

    DETECTORS.register(key, factory)
    try:
        yield
    finally:
        DETECTORS._entries.pop(key, None)


__all__ = ["FakeDetector", "temporary_detector"]
