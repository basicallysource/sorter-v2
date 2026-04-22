"""Bridge shim that exposes the rt/ Hive detectors to the legacy detection API.

The old VisionManager registry (baseline_diff / mog2 / heatmap_diff /
gemini_sam / hive:<slug>) is gone. rt/ now owns live detection. The admin-UI
endpoints in ``server/routers/detection.py`` still speak the old shape, so
this module reflects the rt-registered Hive detectors into that shape:

- ``DETECTORS.keys()`` is the source of truth for available algorithms.
- Per-detector metadata (slug, imgsz, model_family, legacy_scopes) is read
  directly from ``blob/hive_detection_models/*/run.json`` to avoid eagerly
  instantiating ONNX / NCNN sessions.
- All Hive models are advertised on every scope ("feeder", "carousel",
  "classification"). The C-channel optic is shared across scopes, so the
  UI should let operators pick any model for any scope.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterable


log = logging.getLogger(__name__)


DetectionScope = str
DetectionAlgorithmId = str
ClassificationDetectionAlgorithm = str
FeederDetectionAlgorithm = str
CarouselDetectionAlgorithm = str

HIVE_ID_PREFIX = "hive:"

# Every rt Hive detector is advertised on every scope. Marc's call: the
# C-channel optic drives all three and per-scope whitelisting would only
# hide models that are in fact safe to select.
_ALL_SCOPES: frozenset[str] = frozenset({"feeder", "carousel", "classification"})

_NONE_ALGORITHM_ID = "none"


# --- rt self-registration side effect ---------------------------------------
# Importing ``rt.perception`` fires ``@register_detector`` decorators + the
# Hive discovery scan so ``DETECTORS.keys()`` contains the 5 Hive models.
# Defensive try/except: tests may stub rt or the blob dir may be missing.
try:  # pragma: no cover - import-time side effect, exercised by real runs
    import rt.perception  # noqa: F401
except Exception as exc:
    log.warning("vision.detection_registry: rt.perception import failed: %s", exc)


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


# ---------------------------------------------------------------------------
# Lazy cache of algorithm definitions
# ---------------------------------------------------------------------------


_CACHED_ALGOS: tuple[DetectionAlgorithmDefinition, ...] | None = None
_CACHE_LOCK = Lock()

_HIVE_MODELS_DIRNAME = "hive_detection_models"


def _hive_models_dir() -> Path:
    # backend/vision/detection_registry.py -> backend/
    return Path(__file__).resolve().parents[1] / "blob" / _HIVE_MODELS_DIRNAME


def _prettify_slug(slug: str) -> str:
    """Turn ``c-channel-yolo11n-320`` into ``C-Channel YOLO11n 320``.

    Single-letter prefixes ("c", "c4") stay attached to the next token with
    a hyphen so "C-Channel" reads correctly.
    """
    raw = slug.replace("_", "-").strip("-")
    parts = [p for p in raw.split("-") if p]
    pretty: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        lower = part.lower()
        # Glue single-letter prefix (e.g. "c") to the next token with a hyphen.
        if len(part) == 1 and part.isalpha() and i + 1 < len(parts):
            nxt = parts[i + 1]
            pretty.append(f"{part.upper()}-{nxt.capitalize()}")
            i += 2
            continue
        if lower in {"yolo11n", "yolo11s", "yolo8n"}:
            pretty.append("YOLO11n" if lower == "yolo11n" else part)
        elif lower == "nanodet":
            pretty.append("NanoDet")
        elif lower.replace(".", "").isdigit():
            pretty.append(part)
        elif lower.endswith("x") and lower[:-1].replace(".", "").isdigit():
            pretty.append(f"{part}")
        else:
            pretty.append(part.capitalize())
        i += 1
    return " ".join(pretty)


def _index_hive_run_metadata() -> dict[str, dict[str, Any]]:
    """Scan ``blob/hive_detection_models/`` once and return slug -> metadata.

    The returned dict is keyed by ``hive:<slug>`` (registry key) so the
    caller can look it up directly from ``DETECTORS.keys()``. Unparseable
    entries are skipped silently — discovery already logged them.
    """
    root = _hive_models_dir()
    if not root.exists() or not root.is_dir():
        return {}

    # Import locally so tests that monkeypatch ``rt.perception.detectors.hive_onnx._slugify``
    # don't have to also stub vision.detection_registry.
    try:
        from rt.perception.detectors.hive_onnx import _slugify  # type: ignore
    except Exception:  # pragma: no cover - defensive

        def _slugify(name: str) -> str:
            return (name or "").strip().lower().replace(" ", "-")

    out: dict[str, dict[str, Any]] = {}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        run_json = entry / "run.json"
        if not run_json.exists():
            continue
        try:
            meta = json.loads(run_json.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        hive_info = meta.get("hive") or {}
        name = str(meta.get("name") or meta.get("run_name") or entry.name)
        slug = _slugify(name)
        if not slug:
            continue
        key = f"{HIVE_ID_PREFIX}{slug}"
        if key in out:
            continue
        imgsz = (
            _coerce_int(meta.get("imgsz"))
            or _coerce_int((meta.get("inference") or {}).get("imgsz"))
            or _coerce_int((meta.get("dataset") or {}).get("imgsz"))
        )
        out[key] = {
            "slug": slug,
            "model_id": str(hive_info.get("model_id") or entry.name),
            "model_family": str(meta.get("model_family") or "").lower() or None,
            "imgsz": imgsz,
            "runtime": str(hive_info.get("variant_runtime") or meta.get("runtime") or "onnx").lower(),
            "legacy_scopes": tuple(
                str(s).lower() for s in (meta.get("scopes") or []) if isinstance(s, str)
            ),
            "run_name": str(meta.get("run_name") or ""),
            "display_name": name,
            "map50": _coerce_float(((meta.get("best_metrics") or {}).get("mAP50"))),
        }
    return out


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], int):
        return int(value[0])
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _default_hive_key() -> str | None:
    try:
        from rt.perception.detectors.hive_onnx import default_hive_detector_slug

        return default_hive_detector_slug()
    except Exception:  # pragma: no cover - defensive
        return None


def _load_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    global _CACHED_ALGOS
    with _CACHE_LOCK:
        if _CACHED_ALGOS is not None:
            return _CACHED_ALGOS

        try:
            from rt.contracts.registry import DETECTORS
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("vision.detection_registry: DETECTORS unavailable: %s", exc)
            _CACHED_ALGOS = ()
            return _CACHED_ALGOS

        registered_keys = sorted(DETECTORS.keys())
        if not registered_keys:
            _CACHED_ALGOS = ()
            return _CACHED_ALGOS

        metadata_by_key = _index_hive_run_metadata()
        default_key = _default_hive_key()

        defs: list[DetectionAlgorithmDefinition] = []
        for key in registered_keys:
            if not key.startswith(HIVE_ID_PREFIX):
                # Non-hive detectors aren't expected post-cutover, but keep a
                # minimal definition so the router still sees them.
                defs.append(
                    DetectionAlgorithmDefinition(
                        id=key,
                        label=key,
                        description=f"Detector {key}.",
                        supported_scopes=_ALL_SCOPES,
                        kind="builtin",
                        default_for_scopes=(
                            _ALL_SCOPES if key == default_key else frozenset()
                        ),
                    )
                )
                continue

            meta = metadata_by_key.get(key, {})
            slug = meta.get("slug") or key[len(HIVE_ID_PREFIX):]
            model_family = meta.get("model_family") or "yolo"
            imgsz = meta.get("imgsz")
            runtime = meta.get("runtime") or "onnx"
            legacy_scopes = frozenset(meta.get("legacy_scopes") or ())

            display_name = meta.get("display_name") or ""
            # If ``name`` in run.json is just the kebab slug (common for
            # newer uploads), prettify it. Otherwise keep the curated name.
            if display_name and display_name.lower() != slug.lower():
                label = display_name
            else:
                label = _prettify_slug(slug)
            family_label = {"yolo": "YOLO", "nanodet": "NanoDet"}.get(
                (model_family or "").lower(), (model_family or "detector").upper()
            )
            description_bits = [family_label]
            if imgsz:
                description_bits.append(f"@ {imgsz}px")
            description_bits.append(runtime.upper())
            map50 = meta.get("map50")
            if isinstance(map50, float):
                description_bits.append(f"mAP50 {map50 * 100:.1f}%")
            description = " ".join(description_bits)

            defs.append(
                DetectionAlgorithmDefinition(
                    id=key,
                    label=label,
                    description=description,
                    supported_scopes=_ALL_SCOPES,
                    kind="hive",
                    model_family=model_family,
                    imgsz=imgsz,
                    runtime=runtime,
                    hive_metadata={
                        "slug": slug,
                        "model_id": meta.get("model_id"),
                        "legacy_scopes": sorted(legacy_scopes),
                        "run_name": meta.get("run_name") or "",
                        "map50": map50,
                    },
                    default_for_scopes=_ALL_SCOPES if key == default_key else frozenset(),
                )
            )

        _CACHED_ALGOS = tuple(defs)
        return _CACHED_ALGOS


def invalidate_registry() -> None:
    """Drop the cached algorithm list so the next call re-queries ``DETECTORS``."""
    global _CACHED_ALGOS
    with _CACHE_LOCK:
        _CACHED_ALGOS = None


# ---------------------------------------------------------------------------
# Public API consumed by server/routers/detection.py and tests
# ---------------------------------------------------------------------------


def all_detection_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    return _load_algorithms()


def detection_algorithm_definition(
    algorithm_id: str | None,
) -> DetectionAlgorithmDefinition | None:
    if not algorithm_id:
        return None
    for algo in _load_algorithms():
        if algo.id == algorithm_id:
            return algo
    return None


def detection_algorithms_for_scope(
    scope: str,
) -> tuple[DetectionAlgorithmDefinition, ...]:
    if not scope:
        return ()
    return tuple(algo for algo in _load_algorithms() if scope in algo.supported_scopes)


def default_detection_algorithm(scope: str) -> str:
    candidates = detection_algorithms_for_scope(scope)
    if not candidates:
        return _NONE_ALGORITHM_ID
    default_key = _default_hive_key()
    if default_key is not None:
        for algo in candidates:
            if algo.id == default_key:
                return algo.id
    # Fallback: any default_for_scopes match, else the first candidate.
    for algo in candidates:
        if scope in algo.default_for_scopes:
            return algo.id
    return candidates[0].id


def scope_supports_detection_algorithm(
    scope: str, algorithm_id: str | None
) -> bool:
    if not algorithm_id:
        return False
    definition = detection_algorithm_definition(algorithm_id)
    if definition is None:
        return False
    return scope in definition.supported_scopes


def normalize_detection_algorithm(scope: str, value: str | None) -> str:
    if value and scope_supports_detection_algorithm(scope, value):
        return value
    return default_detection_algorithm(scope)


def detection_algorithm_options(scope: str) -> list[dict[str, Any]]:
    """Shape expected by the Svelte settings dropdown.

    Frontend filter in ``ClassificationBaselineSection.svelte`` requires
    ``id`` + ``label`` + ``needs_baseline`` to be present; additional fields
    are ignored but useful for the dropdown description text.
    """
    default_id = default_detection_algorithm(scope)
    return [
        {
            "id": algo.id,
            "label": algo.label,
            "description": algo.description,
            "needs_baseline": bool(algo.needs_baseline),
            "default": algo.id == default_id,
            "kind": algo.kind,
            "model_family": algo.model_family,
            "imgsz": algo.imgsz,
            "runtime": algo.runtime,
        }
        for algo in detection_algorithms_for_scope(scope)
    ]


__all__ = [
    "HIVE_ID_PREFIX",
    "DetectionAlgorithmDefinition",
    "DetectionRequest",
    "DetectionResult",
    "DetectionScope",
    "DetectionAlgorithmId",
    "ClassificationDetectionAlgorithm",
    "FeederDetectionAlgorithm",
    "CarouselDetectionAlgorithm",
    "all_detection_algorithms",
    "default_detection_algorithm",
    "detection_algorithm_definition",
    "detection_algorithm_options",
    "detection_algorithms_for_scope",
    "invalidate_registry",
    "normalize_detection_algorithm",
    "scope_supports_detection_algorithm",
]
