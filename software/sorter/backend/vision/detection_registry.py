from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np


log = logging.getLogger(__name__)


DetectionScope = Literal["classification", "feeder", "carousel"]
BuiltinDetectionAlgorithmId = Literal["baseline_diff", "mog2", "heatmap_diff", "gemini_sam"]
# Runtime ids may be the built-ins or a dynamic ``hive:<slug>``; keep the type as ``str``
# for everything that crosses module boundaries.
DetectionAlgorithmId = str
ClassificationDetectionAlgorithm = str
FeederDetectionAlgorithm = str
CarouselDetectionAlgorithm = str

HIVE_ID_PREFIX = "hive:"
HIVE_MODELS_DIR = Path(__file__).resolve().parent.parent / "blob" / "hive_detection_models"

_SCOPE_BY_HIVE_SCOPE: dict[str, DetectionScope] = {
    "classification_chamber": "classification",
    "classification": "classification",
    "chamber": "classification",
    "c_channel": "feeder",
    "c-channel": "feeder",
    "feeder": "feeder",
    "carousel": "carousel",
}


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
    id: str
    label: str
    description: str
    supported_scopes: frozenset[DetectionScope]
    required_inputs: frozenset[str]
    default_for_scopes: frozenset[DetectionScope] = frozenset()
    needs_baseline: bool = False
    kind: str = "builtin"  # "builtin" | "hive"
    model_path: Path | None = None
    model_family: str | None = None
    imgsz: int | None = None
    runtime: str | None = None  # "onnx" | "ncnn" | "hailo" (hive only)
    hive_metadata: dict[str, Any] | None = None


_BUILTIN_ALGORITHMS: tuple[DetectionAlgorithmDefinition, ...] = (
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


# ---------------------------------------------------------------------------
# Dynamic (Hive-installed) entries
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cached_hive_algorithms: tuple[DetectionAlgorithmDefinition, ...] | None = None


def invalidate_registry() -> None:
    """Drop the cache so the next registry read rescans the Hive models dir."""
    global _cached_hive_algorithms
    with _cache_lock:
        _cached_hive_algorithms = None


def _map_hive_scopes(scopes: Any) -> frozenset[DetectionScope]:
    if not isinstance(scopes, list):
        return frozenset()
    mapped: set[DetectionScope] = set()
    for raw in scopes:
        if not isinstance(raw, str):
            continue
        scope = _SCOPE_BY_HIVE_SCOPE.get(raw.strip().lower())
        if scope is not None:
            mapped.add(scope)
    return frozenset(mapped)


def _discover_hive_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    if not HIVE_MODELS_DIR.exists():
        return ()

    from vision.ml import imgsz_from_run_metadata, resolve_variant_artifact

    entries: list[DetectionAlgorithmDefinition] = []
    for entry in sorted(HIVE_MODELS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        run_json = entry / "run.json"
        if not run_json.exists():
            continue
        try:
            meta = json.loads(run_json.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("Skipping Hive model %s — unreadable run.json", entry.name)
            continue
        if not isinstance(meta, dict) or "hive" not in meta:
            continue

        hive_info = meta.get("hive") or {}
        model_family = str(meta.get("model_family") or "").lower()
        if model_family not in {"yolo", "nanodet"}:
            log.info("Skipping Hive model %s — unsupported family %r", entry.name, model_family)
            continue

        variant_runtime = str(hive_info.get("variant_runtime") or "onnx").lower()
        if variant_runtime not in {"onnx", "ncnn", "hailo"}:
            log.info(
                "Skipping Hive model %s — unsupported runtime %r",
                entry.name,
                variant_runtime,
            )
            continue

        model_path = resolve_variant_artifact(entry, variant_runtime)
        if model_path is None:
            log.info(
                "Skipping Hive model %s — no %s artifact found under exports/",
                entry.name,
                variant_runtime,
            )
            continue

        supported = _map_hive_scopes(meta.get("scopes"))
        if not supported:
            supported = frozenset({"classification"})

        slug = str(meta.get("name") or hive_info.get("model_id") or entry.name)
        algorithm_id = f"{HIVE_ID_PREFIX}{entry.name}"
        label = f"Hive · {slug}"
        family_label = model_family.upper()
        description = (
            f"Downloaded {family_label} model from Hive. "
            f"Runtime variant: {variant_runtime}."
        )
        imgsz = imgsz_from_run_metadata(meta)

        entries.append(
            DetectionAlgorithmDefinition(
                id=algorithm_id,
                label=label,
                description=description,
                supported_scopes=supported,
                required_inputs=frozenset({"frame"}),
                default_for_scopes=frozenset(),
                needs_baseline=False,
                kind="hive",
                model_path=model_path,
                model_family=model_family,
                imgsz=imgsz,
                runtime=variant_runtime,
                hive_metadata=hive_info,
            )
        )
    return tuple(entries)


def _hive_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    global _cached_hive_algorithms
    with _cache_lock:
        if _cached_hive_algorithms is None:
            _cached_hive_algorithms = _discover_hive_algorithms()
        return _cached_hive_algorithms


def _all_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    return _BUILTIN_ALGORITHMS + _hive_algorithms()


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def all_detection_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    return _all_algorithms()


def detection_algorithm_definition(
    algorithm_id: str | None,
) -> DetectionAlgorithmDefinition | None:
    if algorithm_id is None:
        return None
    for definition in _all_algorithms():
        if definition.id == algorithm_id:
            return definition
    return None


def detection_algorithms_for_scope(scope: DetectionScope) -> tuple[DetectionAlgorithmDefinition, ...]:
    return tuple(
        definition for definition in _all_algorithms() if scope in definition.supported_scopes
    )


def default_detection_algorithm(scope: DetectionScope) -> str:
    for definition in _all_algorithms():
        if scope in definition.default_for_scopes:
            return definition.id
    available = detection_algorithms_for_scope(scope)
    if not available:
        raise ValueError(f"No detection algorithms are registered for scope '{scope}'.")
    return available[0].id


def scope_supports_detection_algorithm(scope: DetectionScope, algorithm_id: str | None) -> bool:
    definition = detection_algorithm_definition(algorithm_id)
    return definition is not None and scope in definition.supported_scopes


def normalize_detection_algorithm(scope: DetectionScope, value: str | None) -> str:
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
            "kind": definition.kind,
            "model_family": definition.model_family,
            "imgsz": definition.imgsz,
        }
        for definition in detection_algorithms_for_scope(scope)
    ]
