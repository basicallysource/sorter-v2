"""Detector metadata + option shape for admin/UI consumers.

Reads ``blob/hive_detection_models/<uuid>/run.json`` directly (no detector
instantiation) and surfaces it in the shape the Svelte settings dropdown
needs. Scope filtering goes through
``rt.contracts.registry.ui_scopes_for_detector`` — the UI-scope mapping is
owned by ``registry.py``, not duplicated here.

This module replaces the legacy ``vision.detection_registry`` shim. It is
safe to import without pulling onnxruntime / ncnn: metadata comes from
``run.json`` on disk plus the rt ``DETECTORS`` registry keys.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from rt.contracts.registry import (
    DETECTORS,
    default_detector_slug_for_ui_scope,
    ui_scopes_for_detector,
)


log = logging.getLogger(__name__)


HIVE_ID_PREFIX = "hive:"
_NONE_ALGORITHM_ID = "none"
_HIVE_MODELS_DIRNAME = "hive_detection_models"


@dataclass(frozen=True)
class DetectionAlgorithmDefinition:
    """Metadata describing a registered detector for admin/UI consumers.

    Shape mirrors what ``ClassificationBaselineSection.svelte`` expects
    (``id`` / ``label`` / ``description`` / ``needs_baseline`` / ``kind`` /
    ``model_family`` / ``imgsz`` / ``runtime``).
    """

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


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _hive_models_dir() -> Path:
    # rt/perception/detector_metadata.py -> backend/
    return Path(__file__).resolve().parents[2] / "blob" / _HIVE_MODELS_DIRNAME


# ---------------------------------------------------------------------------
# Label pretty-printer
# ---------------------------------------------------------------------------


def _prettify_slug(slug: str) -> str:
    """Turn ``c-channel-yolo11n-320`` into ``C-Channel YOLO11n 320``."""
    raw = slug.replace("_", "-").strip("-")
    parts = [p for p in raw.split("-") if p]
    pretty: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        lower = part.lower()
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


# ---------------------------------------------------------------------------
# run.json indexer (disk-only, no ONNX/NCNN loads)
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    # Local copy avoids a circular-ish import-time dependency on hive_onnx.
    import re

    trimmed = (name or "").strip().lower()
    if not trimmed:
        return ""
    collapsed = re.sub(r"\s+", "-", trimmed)
    collapsed = re.sub(r"-{2,}", "-", collapsed)
    return collapsed.strip("-")


def _index_hive_run_metadata() -> dict[str, dict[str, Any]]:
    """Scan ``blob/hive_detection_models/`` and return ``hive:<slug>`` → meta."""
    root = _hive_models_dir()
    if not root.exists() or not root.is_dir():
        return {}

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
            "runtime": str(
                hive_info.get("variant_runtime") or meta.get("runtime") or "onnx"
            ).lower(),
            "scopes": tuple(
                str(s).lower() for s in (meta.get("scopes") or []) if isinstance(s, str)
            ),
            "run_name": str(meta.get("run_name") or ""),
            "display_name": name,
            "map50": _coerce_float(((meta.get("best_metrics") or {}).get("mAP50"))),
        }
    return out


# ---------------------------------------------------------------------------
# Definition builder
# ---------------------------------------------------------------------------


_CACHE_LOCK = Lock()
_CACHED_DEFS: tuple[DetectionAlgorithmDefinition, ...] | None = None


def invalidate_cache() -> None:
    """Drop cached definitions so the next call re-reads run.json + DETECTORS."""
    global _CACHED_DEFS
    with _CACHE_LOCK:
        _CACHED_DEFS = None


def _build_definition(
    key: str,
    disk_meta: Mapping[str, Any],
) -> DetectionAlgorithmDefinition:
    slug = disk_meta.get("slug") or (key[len(HIVE_ID_PREFIX):] if key.startswith(HIVE_ID_PREFIX) else key)
    model_family = disk_meta.get("model_family") or "yolo"
    imgsz = disk_meta.get("imgsz")
    runtime = disk_meta.get("runtime") or "onnx"

    display_name = disk_meta.get("display_name") or ""
    if display_name and display_name.lower() != str(slug).lower():
        label = display_name
    else:
        label = _prettify_slug(str(slug))
    family_label = {"yolo": "YOLO", "nanodet": "NanoDet"}.get(
        (model_family or "").lower(), (model_family or "detector").upper()
    )
    bits = [family_label]
    if imgsz:
        bits.append(f"@ {imgsz}px")
    bits.append(str(runtime).upper())
    map50 = disk_meta.get("map50")
    if isinstance(map50, float):
        bits.append(f"mAP50 {map50 * 100:.1f}%")
    description = " ".join(bits)

    ui_scopes = ui_scopes_for_detector(key)
    default_for = frozenset(
        scope
        for scope in ui_scopes
        if default_detector_slug_for_ui_scope(scope) == key
    )

    return DetectionAlgorithmDefinition(
        id=key,
        label=label,
        description=description,
        supported_scopes=ui_scopes,
        kind="hive" if key.startswith(HIVE_ID_PREFIX) else "builtin",
        model_family=model_family,
        imgsz=imgsz,
        runtime=runtime,
        default_for_scopes=default_for,
        hive_metadata=(
            {
                "slug": slug,
                "model_id": disk_meta.get("model_id"),
                "scopes": list(disk_meta.get("scopes") or ()),
                "run_name": disk_meta.get("run_name") or "",
                "map50": map50,
            }
            if key.startswith(HIVE_ID_PREFIX)
            else None
        ),
    )


def _load_definitions() -> tuple[DetectionAlgorithmDefinition, ...]:
    global _CACHED_DEFS
    with _CACHE_LOCK:
        if _CACHED_DEFS is not None:
            return _CACHED_DEFS
        registered = sorted(DETECTORS.keys())
        if not registered:
            _CACHED_DEFS = ()
            return _CACHED_DEFS
        disk_index = _index_hive_run_metadata()
        defs = tuple(
            _build_definition(key, disk_index.get(key, {})) for key in registered
        )
        _CACHED_DEFS = defs
        return defs


# ---------------------------------------------------------------------------
# Public helpers (shim-replacement API)
# ---------------------------------------------------------------------------


def all_detection_algorithms() -> tuple[DetectionAlgorithmDefinition, ...]:
    return _load_definitions()


def detection_algorithm_definition(
    algorithm_id: str | None,
) -> DetectionAlgorithmDefinition | None:
    if not algorithm_id:
        return None
    for algo in _load_definitions():
        if algo.id == algorithm_id:
            return algo
    return None


def detection_algorithms_for_scope(
    scope: str,
) -> tuple[DetectionAlgorithmDefinition, ...]:
    if not scope:
        return ()
    return tuple(algo for algo in _load_definitions() if scope in algo.supported_scopes)


def default_detection_algorithm(scope: str) -> str:
    """UI-scope default detector slug; returns ``"none"`` when no detector fits."""
    slug = default_detector_slug_for_ui_scope(scope)
    return slug or _NONE_ALGORITHM_ID


def scope_supports_detection_algorithm(
    scope: str, algorithm_id: str | None
) -> bool:
    if not algorithm_id or not scope:
        return False
    if algorithm_id not in DETECTORS.keys():
        return False
    return scope in ui_scopes_for_detector(algorithm_id)


def normalize_detection_algorithm(scope: str, value: str | None) -> str:
    if value and scope_supports_detection_algorithm(scope, value):
        return value
    return default_detection_algorithm(scope)


def detection_algorithm_options(scope: str) -> list[dict[str, Any]]:
    """Frontend shape consumed by ``ClassificationBaselineSection.svelte``."""
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
    "all_detection_algorithms",
    "default_detection_algorithm",
    "detection_algorithm_definition",
    "detection_algorithm_options",
    "detection_algorithms_for_scope",
    "invalidate_cache",
    "normalize_detection_algorithm",
    "scope_supports_detection_algorithm",
]
