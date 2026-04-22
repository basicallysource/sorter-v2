"""Minimal post-cutover shim for ``vision.detection_registry``.

The legacy detection registry (baseline_diff / mog2 / heatmap_diff /
gemini_sam / hive:<slug>) belonged to the old VisionManager-driven pipeline.
With the rt/ runtime doing detection via its own pipeline, the admin-UI
detection-config endpoints in ``server/routers/detection.py`` no longer drive
anything live; keep just enough of this module's public shape alive so the
router imports still succeed.

Everything here returns empty / default values — the downstream UI will
render "no detection algorithms configured" rather than 500.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DetectionScope = str
DetectionAlgorithmId = str
ClassificationDetectionAlgorithm = str
FeederDetectionAlgorithm = str
CarouselDetectionAlgorithm = str

HIVE_ID_PREFIX = "hive:"


@dataclass(frozen=True)
class DetectionAlgorithmDefinition:
    id: str
    label: str
    description: str
    supported_scopes: frozenset[str]
    required_inputs: frozenset[str] = frozenset()
    default_for_scopes: frozenset[str] = frozenset()
    needs_baseline: bool = False
    kind: str = "builtin"
    model_path: Path | None = None
    model_family: str | None = None
    imgsz: int | None = None
    runtime: str | None = None
    hive_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DetectionRequest:
    scope: str
    role: str
    frame: Any | None = None
    gray_frame: Any | None = None
    zone_polygon: Any | None = None
    baseline_state: Any | None = None
    background_state: Any | None = None
    force: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionResult:
    bbox: tuple[int, int, int, int] | None = None
    bboxes: tuple[tuple[int, int, int, int], ...] = ()
    score: float | None = None
    algorithm: str = "none"
    found: bool | None = None
    message: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


def invalidate_registry() -> None:
    return None


def all_detection_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    return ()


def detection_algorithm_definition(_algorithm_id: str | None) -> DetectionAlgorithmDefinition | None:
    return None


def detection_algorithms_for_scope(_scope: str) -> tuple[DetectionAlgorithmDefinition, ...]:
    return ()


def default_detection_algorithm(_scope: str) -> str:
    return "none"


def scope_supports_detection_algorithm(_scope: str, _algorithm_id: str | None) -> bool:
    return False


def normalize_detection_algorithm(_scope: str, value: str | None) -> str:
    return str(value or "none")


def detection_algorithm_options(_scope: str) -> list[dict[str, Any]]:
    return []
