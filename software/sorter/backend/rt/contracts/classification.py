from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Protocol

from .feed import FeedFrame
from .tracking import Track


@dataclass(frozen=True, slots=True)
class ClassifierResult:
    """Result of classifying one piece."""

    part_id: str | None
    color_id: str | None
    category: str | None
    confidence: float
    algorithm: str
    latency_ms: float
    meta: dict[str, Any] = field(default_factory=dict)


class Classifier(Protocol):
    """Classifier strategy: maps (Track, FeedFrame, crop) → ClassifierResult."""

    key: str

    def classify(self, track: Track, frame: FeedFrame, crop: Any) -> ClassifierResult: ...

    def classify_async(
        self, track: Track, frame: FeedFrame, crop: Any
    ) -> "Future[ClassifierResult]": ...

    def reset(self) -> None: ...

    def stop(self) -> None: ...
