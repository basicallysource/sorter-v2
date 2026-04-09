from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np


DetectionScope = Literal["classification", "feeder", "carousel"]
DetectionAlgorithmId = Literal["baseline_diff", "mog2", "heatmap_diff", "gemini_sam"]
ClassificationDetectionAlgorithm = Literal["baseline_diff", "gemini_sam"]
FeederDetectionAlgorithm = Literal["mog2", "gemini_sam"]
CarouselDetectionAlgorithm = Literal["heatmap_diff", "gemini_sam"]


@dataclass(frozen=True)
class DetectionRequest:
    scope: DetectionScope
    role: str
    frame: np.ndarray | None = None
    gray_frame: np.ndarray | None = None
    zone_polygon: np.ndarray | None = None
    baseline_state: Any | None = None
    background_state: Any | None = None
    force: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionResult:
    bbox: tuple[int, int, int, int] | None
    bboxes: tuple[tuple[int, int, int, int], ...]
    score: float | None
    algorithm: str
    found: bool | None = None
    message: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionAlgorithmDefinition:
    id: DetectionAlgorithmId
    label: str
    description: str
    supported_scopes: frozenset[DetectionScope]
    required_inputs: frozenset[str]
    default_for_scopes: frozenset[DetectionScope] = frozenset()
    needs_baseline: bool = False


_ALGORITHMS: tuple[DetectionAlgorithmDefinition, ...] = (
    DetectionAlgorithmDefinition(
        id="baseline_diff",
        label="Baseline Diff",
        description="Uses an empty-chamber baseline envelope and frame diffing.",
        supported_scopes=frozenset({"classification"}),
        required_inputs=frozenset({"frame", "gray_frame", "baseline_state"}),
        default_for_scopes=frozenset({"classification"}),
        needs_baseline=True,
    ),
    DetectionAlgorithmDefinition(
        id="mog2",
        label="MOG2",
        description="Uses the existing per-channel foreground detector inside the saved C-channel masks.",
        supported_scopes=frozenset({"feeder"}),
        required_inputs=frozenset({"gray_frame", "background_state"}),
        default_for_scopes=frozenset({"feeder"}),
        needs_baseline=False,
    ),
    DetectionAlgorithmDefinition(
        id="heatmap_diff",
        label="Heatmap Diff",
        description="Uses the saved carousel baseline and live diff heatmap to detect a drop event.",
        supported_scopes=frozenset({"carousel"}),
        required_inputs=frozenset({"gray_frame", "baseline_state"}),
        default_for_scopes=frozenset({"carousel"}),
        needs_baseline=True,
    ),
    DetectionAlgorithmDefinition(
        id="gemini_sam",
        label="Cloud Vision + SAM",
        description="Runs the selected OpenRouter vision model asynchronously on the scoped image crop and reuses those detections live.",
        supported_scopes=frozenset({"classification", "feeder", "carousel"}),
        required_inputs=frozenset({"frame"}),
        default_for_scopes=frozenset(),
        needs_baseline=False,
    ),
)


def all_detection_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    return _ALGORITHMS


def detection_algorithm_definition(
    algorithm_id: str | None,
) -> DetectionAlgorithmDefinition | None:
    for definition in _ALGORITHMS:
        if definition.id == algorithm_id:
            return definition
    return None


def detection_algorithms_for_scope(scope: DetectionScope) -> tuple[DetectionAlgorithmDefinition, ...]:
    return tuple(
        definition for definition in _ALGORITHMS if scope in definition.supported_scopes
    )


def default_detection_algorithm(scope: DetectionScope) -> DetectionAlgorithmId:
    for definition in _ALGORITHMS:
        if scope in definition.default_for_scopes:
            return definition.id
    available = detection_algorithms_for_scope(scope)
    if not available:
        raise ValueError(f"No detection algorithms are registered for scope '{scope}'.")
    return available[0].id


def scope_supports_detection_algorithm(scope: DetectionScope, algorithm_id: str | None) -> bool:
    definition = detection_algorithm_definition(algorithm_id)
    return definition is not None and scope in definition.supported_scopes


def normalize_detection_algorithm(scope: DetectionScope, value: str | None) -> DetectionAlgorithmId:
    if scope_supports_detection_algorithm(scope, value):
        return value  # type: ignore[return-value]
    return default_detection_algorithm(scope)


def detection_algorithm_options(scope: DetectionScope) -> list[dict[str, Any]]:
    return [
        {
            "id": definition.id,
            "label": definition.label,
            "needs_baseline": definition.needs_baseline,
            "description": definition.description,
            "required_inputs": sorted(definition.required_inputs),
        }
        for definition in detection_algorithms_for_scope(scope)
    ]
