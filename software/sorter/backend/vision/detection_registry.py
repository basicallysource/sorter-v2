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
# Runtime ids may be the built-ins or an installed model (``hive:<dir>`` /
# ``local:<dir>``); keep the type as ``str`` for everything that crosses module
# boundaries.
DetectionAlgorithmId = str
ClassificationDetectionAlgorithm = str
FeederDetectionAlgorithm = str
CarouselDetectionAlgorithm = str

HIVE_ID_PREFIX = "hive:"
LOCAL_ID_PREFIX = "local:"
# Installed-model kinds and their id prefixes: Hive downloads and models put in
# MODELS_DIR by hand. Both run through the same on-device inference path.
MODEL_KINDS = frozenset({"hive", "local"})
MODEL_ID_PREFIXES = (HIVE_ID_PREFIX, LOCAL_ID_PREFIX)
# The one place installed models live (``server.hive_models.LOCAL_MODELS_DIR``).
MODELS_DIR = Path(__file__).resolve().parent.parent / "blob" / "hive_detection_models"

MODEL_FAMILIES = frozenset({"yolo", "nanodet"})
# Runtimes a model can be loaded with, in the order a local model without a
# declared runtime is probed.
MODEL_RUNTIMES = ("onnx", "ncnn", "hailo", "rknn")

_SCOPE_BY_HIVE_SCOPE: dict[str, DetectionScope] = {
    "classification_chamber": "classification",
    "classification": "classification",
    "chamber": "classification",
    "c_channel": "feeder",
    "c-channel": "feeder",
    "feeder": "feeder",
    "carousel": "carousel",
    "classification_channel": "carousel",
    "classification-channel": "carousel",
    "c4": "carousel",
    "c4_sector": "carousel",
    "c4-sector": "carousel",
    "sector": "carousel",
    "sector_yolo": "carousel",
    "sector-yolo": "carousel",
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
    kind: str = "builtin"  # "builtin" | "hive" | "local"
    model_path: Path | None = None
    model_family: str | None = None
    imgsz: int | None = None
    runtime: str | None = None  # "onnx" | "ncnn" | "hailo" | "rknn" (installed models only)
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
# Installed models (Hive downloads and local ones)
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cached_model_algorithms: tuple[DetectionAlgorithmDefinition, ...] | None = None


def invalidate_registry() -> None:
    """Drop the cache so the next registry read rescans the models dir."""
    global _cached_model_algorithms
    with _cache_lock:
        _cached_model_algorithms = None


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


def local_model_artifact(model_dir: Path, meta: dict[str, Any]) -> tuple[str, Path] | None:
    """Return ``(runtime, artifact)`` when ``model_dir`` is a usable local model.

    A local model is a directory someone put in ``MODELS_DIR`` by hand: its
    ``run.json`` has no ``hive`` block (that block marks a Hive download). Its
    algorithm id is ``local:<dir name>``. The ``run.json`` fields it reads:

      model_family  ``"yolo"`` or ``"nanodet"`` (required)
      runtime       ``"onnx"``, ``"ncnn"``, ``"hailo"`` or ``"rknn"`` (optional;
                    without it the first of those with an artifact wins)
      name          the label shown in the UI (optional; the dir name otherwise)
      scopes        Hive scope names such as ``["c_channel"]`` (optional; absent
                    means every scope)
      imgsz         the model input size (optional; 320 otherwise)

    The artifact sits under ``exports/`` the way ``resolve_variant_artifact``
    expects: ``exports/best.onnx``, an extracted ``*ncnn*`` directory holding a
    ``.param``, ``exports/*.hef`` or ``exports/*.rknn``.
    """
    from vision.ml import resolve_variant_artifact

    if str(meta.get("model_family") or "").lower() not in MODEL_FAMILIES:
        return None
    declared = str(meta.get("runtime") or "").lower()
    for runtime in (declared,) if declared else MODEL_RUNTIMES:
        if runtime not in MODEL_RUNTIMES:
            return None
        artifact = resolve_variant_artifact(model_dir, runtime)
        if artifact is not None:
            return runtime, artifact
    return None


def _model_definition(entry: Path, meta: dict[str, Any]) -> DetectionAlgorithmDefinition | None:
    from vision.ml import imgsz_from_run_metadata, resolve_variant_artifact

    hive_info = meta.get("hive")
    if isinstance(hive_info, dict):
        # Hive publishes models for several purposes into one catalog and the
        # sorter installs them all the same way. Only detection models become
        # detection algorithms. Absent purpose predates the field, so it's a
        # detection model.
        purpose = str(hive_info.get("purpose") or "detection").lower()
        if purpose != "detection":
            return None
        model_family = str(meta.get("model_family") or "").lower()
        if model_family not in MODEL_FAMILIES:
            log.info("Skipping Hive model %s — unsupported family %r", entry.name, model_family)
            return None
        runtime = str(hive_info.get("variant_runtime") or "onnx").lower()
        if runtime not in MODEL_RUNTIMES:
            log.info("Skipping Hive model %s — unsupported runtime %r", entry.name, runtime)
            return None
        model_path = resolve_variant_artifact(entry, runtime)
        if model_path is None:
            log.info(
                "Skipping Hive model %s — no %s artifact found under exports/", entry.name, runtime
            )
            return None
        kind = "hive"
        algorithm_id = f"{HIVE_ID_PREFIX}{entry.name}"
        label = f"Hive · {meta.get('name') or hive_info.get('model_id') or entry.name}"
        description = (
            f"Downloaded {model_family.upper()} model from Hive. Runtime variant: {runtime}."
        )
    else:
        found = local_model_artifact(entry, meta)
        if found is None:
            log.info(
                "Skipping %s — not a Hive download, and not a local model (run.json needs "
                "model_family yolo|nanodet and exports/ an artifact for its runtime)",
                entry.name,
            )
            return None
        runtime, model_path = found
        model_family = str(meta.get("model_family")).lower()
        kind = "local"
        algorithm_id = f"{LOCAL_ID_PREFIX}{entry.name}"
        label = f"Local · {meta.get('name') or entry.name}"
        description = (
            f"Local {model_family.upper()} model installed on this machine by hand. "
            f"Runtime: {runtime}."
        )

    supported = _map_hive_scopes(meta.get("scopes"))
    if not supported:
        # When the model has no scope metadata we can't tell what it is good
        # for — but the operator installed it deliberately, so refuse-
        # everywhere is worse UX than allow-everywhere. They get to decide; if
        # it's a bad fit they'll see it on the live feed and switch back.
        supported = frozenset({"classification", "feeder", "carousel"})

    return DetectionAlgorithmDefinition(
        id=algorithm_id,
        label=label,
        description=description,
        supported_scopes=supported,
        required_inputs=frozenset({"frame"}),
        needs_baseline=False,
        kind=kind,
        model_path=model_path,
        model_family=model_family,
        imgsz=imgsz_from_run_metadata(meta),
        runtime=runtime,
        hive_metadata=hive_info if isinstance(hive_info, dict) else None,
    )


def _discover_model_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    if not MODELS_DIR.exists():
        return ()
    entries: list[DetectionAlgorithmDefinition] = []
    for entry in sorted(MODELS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        run_json = entry / "run.json"
        if not run_json.exists():
            continue
        try:
            meta = json.loads(run_json.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("Skipping model %s — unreadable run.json", entry.name)
            continue
        if not isinstance(meta, dict):
            continue
        definition = _model_definition(entry, meta)
        if definition is not None:
            entries.append(definition)
    return tuple(entries)


def _model_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    global _cached_model_algorithms
    with _cache_lock:
        if _cached_model_algorithms is None:
            _cached_model_algorithms = _discover_model_algorithms()
        return _cached_model_algorithms


def _all_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    # Installed models are never a default: the built-ins are the fallback
    # until a model is assigned (server.default_model assigns Hive's default).
    return _model_algorithms() + _BUILTIN_ALGORITHMS


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
