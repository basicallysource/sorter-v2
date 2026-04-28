from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .feed import FeedFrame, Zone


@dataclass(frozen=True, slots=True)
class Detection:
    """Single raw detection in a frame, pre-tracking."""

    bbox_xyxy: tuple[int, int, int, int]
    score: float
    class_id: str | None = None
    mask: Any | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DetectionBatch:
    """Output of a Detector for one FeedFrame."""

    feed_id: str
    frame_seq: int
    timestamp: float
    detections: tuple[Detection, ...]
    algorithm: str
    latency_ms: float


class Detector(Protocol):
    """Per-feed detector strategy — stateless or stateful, returns DetectionBatch."""

    key: str

    def requires(self) -> frozenset[str]: ...

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch: ...

    def reset(self) -> None: ...

    def stop(self) -> None: ...
