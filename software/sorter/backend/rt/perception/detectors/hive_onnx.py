"""Hive-trained object detector wrapper for the rt/ pipeline.

Ports the Hive model-loading path into the new ``Detector`` protocol. A
``HiveDetector`` instance wraps one Hive-installed model (YOLO/NanoDet,
ONNX/NCNN/Hailo via ``backend.vision.ml``) and returns a ``DetectionBatch``
in original-frame coordinates for an rt ``PerceptionPipeline``.

Bridge imports: this module intentionally reaches into ``backend.vision.*``
for ``create_processor`` and ``resolve_variant_artifact``. That dependency
is **temporary**, mirrors the ``CameraFeed`` pattern in ``rt/perception/feeds.py``,
and will be removed once ``rt/vision/ml`` (or equivalent) is extracted.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame, PolarZone, PolygonZone, RectZone, Zone
from rt.contracts.registry import DETECTORS
from utils.polygon_crop import apply_polygon_crop


log = logging.getLogger(__name__)


# --- bridge imports (legacy) -------------------------------------------------
# These import lazily inside the factory so unit tests can stub them without
# pulling onnxruntime / ncnn on import.


_DEFAULT_CONF_THRESHOLD = 0.25
_DEFAULT_IOU_THRESHOLD = 0.45
_HIVE_MODELS_DIRNAME = "hive_detection_models"
_DEFAULT_TARGET_SLUG = "c-channel-yolo11n-320"
_SLUG_KEY_PREFIX = "hive:"


def default_hive_detector_slug() -> str:
    """Registry key for the primary C-channel YOLOv11n detector.

    The four other Hive models (carousel / classification-chamber variants)
    are historical and remain registered but not picked by default.
    """
    return f"{_SLUG_KEY_PREFIX}{_DEFAULT_TARGET_SLUG}"


class HiveDetector:
    """Detector implementation backed by a legacy ``BaseProcessor``.

    The ``processor`` is constructed by the caller (typically by
    ``discover_and_register_hive_detectors``) and injected so tests can pass
    a fake. The detector owns zone crop/mask pre-processing and translates
    bbox coordinates back into the original-frame system.
    """

    def __init__(
        self,
        model_id: str,
        slug: str,
        processor: Any,
        imgsz: int,
        model_family: str,
        legacy_scopes: frozenset[str] = frozenset(),
    ) -> None:
        self._model_id = model_id
        self._slug = slug
        self._processor = processor
        self._imgsz = int(imgsz)
        self._model_family = model_family
        self._legacy_scopes = legacy_scopes
        self.key = f"{_SLUG_KEY_PREFIX}{slug}"

    # --- Detector protocol ---------------------------------------------------

    def requires(self) -> frozenset[str]:
        # YOLO/NanoDet processors consume BGR raw frames.
        return frozenset({"raw"})

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch:
        t0 = time.perf_counter()
        raw = frame.raw
        if raw is None:
            return self._empty_batch(frame, t0)

        crop, offset_xy = self._apply_zone(raw, zone)
        if crop is None or crop.size == 0:
            return self._empty_batch(frame, t0)

        try:
            raw_detections = self._processor.infer(crop)
        except Exception:  # pragma: no cover - defensive; depends on ort/ncnn
            log.exception("HiveDetector %s inference failed", self.key)
            return self._empty_batch(frame, t0)

        detections: list[Detection] = []
        for det in raw_detections:
            if det is None:
                continue
            translated = self._to_contract_detection(det, offset_xy, raw.shape)
            if self._center_in_zone(translated.bbox_xyxy, zone):
                detections.append(translated)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=tuple(detections),
            algorithm=self.key,
            latency_ms=latency_ms,
        )

    def reset(self) -> None:
        # YOLO/NanoDet are stateless; still call into processor defensively.
        reset_fn = getattr(self._processor, "reset", None)
        if callable(reset_fn):
            try:
                reset_fn()
            except Exception:  # pragma: no cover - defensive
                log.exception("HiveDetector %s processor.reset() failed", self.key)

    def stop(self) -> None:
        for name in ("close", "release"):
            fn = getattr(self._processor, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # pragma: no cover - defensive
                    log.exception("HiveDetector %s processor.%s() failed", self.key, name)
                return

    # --- helpers -------------------------------------------------------------

    def _empty_batch(self, frame: FeedFrame, t0: float) -> DetectionBatch:
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=(),
            algorithm=self.key,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def _apply_zone(self, raw: np.ndarray, zone: Zone) -> tuple[np.ndarray | None, tuple[int, int]]:
        """Crop/mask the incoming frame according to the zone geometry.

        Returns ``(crop_bgr, (offset_x, offset_y))`` where the offset is the
        top-left corner of the crop in the original frame. The returned crop
        is always contiguous; original frame pixels are not mutated.
        """
        h, w = raw.shape[:2]
        if isinstance(zone, RectZone):
            x1 = max(0, int(zone.x))
            y1 = max(0, int(zone.y))
            x2 = min(w, int(zone.x + zone.w))
            y2 = min(h, int(zone.y + zone.h))
            if x2 <= x1 or y2 <= y1:
                return None, (0, 0)
            return np.ascontiguousarray(raw[y1:y2, x1:x2]), (x1, y1)

        if isinstance(zone, PolygonZone):
            return apply_polygon_crop(raw, zone.vertices)

        if isinstance(zone, PolarZone):
            raise NotImplementedError(
                "PolarZone cropping for HiveDetector is not implemented yet — "
                "PolarZone feeds should use a polar-aware detector path."
            )

        raise TypeError(f"Unsupported Zone type: {type(zone).__name__}")

    def _center_in_zone(
        self,
        bbox_xyxy: tuple[int, int, int, int],
        zone: Zone,
    ) -> bool:
        x1, y1, x2, y2 = (int(v) for v in bbox_xyxy)
        cx = float(x1 + x2) / 2.0
        cy = float(y1 + y2) / 2.0

        if isinstance(zone, RectZone):
            return (
                cx >= float(zone.x)
                and cx <= float(zone.x + zone.w)
                and cy >= float(zone.y)
                and cy <= float(zone.y + zone.h)
            )

        if isinstance(zone, PolygonZone):
            polygon = np.array(zone.vertices, dtype=np.int32)
            if polygon.ndim != 2 or polygon.shape[0] < 3:
                return False
            return cv2.pointPolygonTest(polygon, (cx, cy), False) >= 0

        if isinstance(zone, PolarZone):
            return True

        raise TypeError(f"Unsupported Zone type: {type(zone).__name__}")

    def _to_contract_detection(
        self,
        det: Any,
        offset_xy: tuple[int, int],
        frame_shape: tuple[int, ...],
    ) -> Detection:
        """Translate a legacy ``vision.ml.Detection`` into a contract Detection.

        Clamps bbox to the original frame dimensions, re-adds the crop offset,
        and attaches the model_family + slug in ``meta`` for observability.
        """
        ox, oy = offset_xy
        x1, y1, x2, y2 = (int(v) for v in det.bbox)
        h = int(frame_shape[0])
        w = int(frame_shape[1])
        X1 = max(0, min(w, x1 + ox))
        Y1 = max(0, min(h, y1 + oy))
        X2 = max(0, min(w, x2 + ox))
        Y2 = max(0, min(h, y2 + oy))
        return Detection(
            bbox_xyxy=(X1, Y1, X2, Y2),
            score=float(det.score),
            class_id=None,
            mask=None,
            meta={
                "model_id": self._model_id,
                "slug": self._slug,
                "model_family": self._model_family,
            },
        )


# ---------------------------------------------------------------------------
# Discovery + registration
# ---------------------------------------------------------------------------


_SUPPORTED_FAMILIES = frozenset({"yolo", "nanodet"})
_SUPPORTED_RUNTIMES = frozenset({"onnx", "ncnn", "hailo"})


def _slugify(name: str) -> str:
    """Normalise a model ``name`` into a lower-case kebab slug.

    Examples:
        "Carousel YOLO11n 320" -> "carousel-yolo11n-320"
        "c-channel-yolo11n-320" -> "c-channel-yolo11n-320"
    """
    trimmed = (name or "").strip().lower()
    if not trimmed:
        return ""
    # Collapse any whitespace (spaces, tabs, newlines) to single dashes.
    collapsed = re.sub(r"\s+", "-", trimmed)
    # Collapse runs of multiple dashes.
    collapsed = re.sub(r"-{2,}", "-", collapsed)
    return collapsed.strip("-")


def _default_hive_models_dir() -> Path:
    """Locate ``blob/hive_detection_models`` relative to this file."""
    # rt/perception/detectors/hive_onnx.py -> backend/
    return Path(__file__).resolve().parents[3] / "blob" / _HIVE_MODELS_DIRNAME


def _load_run_meta(run_json: Path) -> dict[str, Any] | None:
    try:
        meta = json.loads(run_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Skipping Hive model %s — unreadable run.json: %s", run_json.parent.name, exc)
        return None
    if not isinstance(meta, dict) or "hive" not in meta:
        return None
    return meta


def _imgsz_from_meta(meta: dict[str, Any]) -> int:
    """Fallback when the vision.ml bridge is not importable (tests)."""
    for key in ("imgsz", "input_size", "image_size"):
        value = meta.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], int):
            return int(value[0])
    dataset = meta.get("dataset")
    if isinstance(dataset, dict):
        imgsz = dataset.get("imgsz")
        if isinstance(imgsz, int) and imgsz > 0:
            return imgsz
    run_name = str(meta.get("run_name") or "")
    for token in run_name.replace("_", "-").split("-"):
        if token.isdigit() and int(token) in (160, 224, 320, 416, 512, 640):
            return int(token)
    return 320


def discover_and_register_hive_detectors(
    models_dir: Path | None = None,
    *,
    registry: Any | None = None,
) -> list[str]:
    """Scan ``blob/hive_detection_models/`` and register one detector per model.

    Each model registers under ``hive:<slug>`` in the ``DETECTORS`` registry
    with a lazy factory — the backing ``BaseProcessor`` is only constructed
    on first ``create()`` call, so imports do not load 5 ONNX sessions.

    Returns the list of registered slug keys (minus the ``hive:`` prefix).
    Broken or unsupported entries are logged and skipped — discovery is
    robust to missing artifacts, a missing directory, etc.
    """
    root = Path(models_dir) if models_dir is not None else _default_hive_models_dir()
    reg = registry if registry is not None else DETECTORS

    if not root.exists() or not root.is_dir():
        log.info("HiveDetector discovery: models dir absent at %s — nothing to register", root)
        return []

    registered: list[str] = []
    seen_slugs: set[str] = set()

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        run_json = entry / "run.json"
        if not run_json.exists():
            continue
        meta = _load_run_meta(run_json)
        if meta is None:
            continue

        hive_info = meta.get("hive") or {}
        model_id = str(hive_info.get("model_id") or entry.name)

        model_family = str(meta.get("model_family") or "").lower()
        if model_family not in _SUPPORTED_FAMILIES:
            log.info("Skipping Hive model %s — unsupported family %r", entry.name, model_family)
            continue

        variant_runtime = str(hive_info.get("variant_runtime") or "onnx").lower()
        if variant_runtime not in _SUPPORTED_RUNTIMES:
            log.info(
                "Skipping Hive model %s — unsupported runtime %r",
                entry.name,
                variant_runtime,
            )
            continue

        slug = _slugify(str(meta.get("name") or meta.get("run_name") or model_id))
        if not slug:
            log.warning("Skipping Hive model %s — cannot derive slug", entry.name)
            continue
        if slug in seen_slugs:
            log.warning(
                "Skipping Hive model %s — duplicate slug %r (already registered)",
                entry.name,
                slug,
            )
            continue

        imgsz = _imgsz_from_meta(meta)

        try:
            model_path = _resolve_model_artifact(entry, variant_runtime)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Skipping Hive model %s — artifact resolve failed: %s", entry.name, exc)
            continue
        if model_path is None:
            log.info(
                "Skipping Hive model %s — no %s artifact found under exports/",
                entry.name,
                variant_runtime,
            )
            continue

        legacy_scopes = frozenset(
            str(s).lower()
            for s in (meta.get("scopes") or [])
            if isinstance(s, str)
        )

        key = f"{_SLUG_KEY_PREFIX}{slug}"
        factory = _make_lazy_factory(
            key=key,
            slug=slug,
            model_id=model_id,
            model_path=model_path,
            model_family=model_family,
            variant_runtime=variant_runtime,
            imgsz=imgsz,
            legacy_scopes=legacy_scopes,
        )

        registration_metadata = {
            "slug": slug,
            "model_id": model_id,
            "model_family": model_family,
            "runtime": variant_runtime,
            "imgsz": imgsz,
            # Scopes as declared in the model's run.json (may be empty for
            # legacy models with no scope declaration). The UI-scope mapping
            # lives in rt/contracts/registry.py, not here.
            "scopes": tuple(sorted(legacy_scopes)),
            "run_dir": str(entry),
        }

        try:
            reg.register(key, factory, metadata=registration_metadata)
        except ValueError:
            # Already registered — normal on re-import. Refresh metadata so
            # re-scan picks up run.json changes without a full restart.
            log.debug("HiveDetector %s already registered — refreshing metadata", key)
            try:
                reg.set_metadata(key, registration_metadata)
            except Exception:  # pragma: no cover - defensive
                log.exception("HiveDetector %s set_metadata failed", key)
        else:
            log.info(
                "Registered HiveDetector %s (family=%s runtime=%s imgsz=%d scopes=%s path=%s)",
                key,
                model_family,
                variant_runtime,
                imgsz,
                sorted(legacy_scopes) or "-",
                model_path,
            )

        seen_slugs.add(slug)
        registered.append(slug)

    return registered


def _resolve_model_artifact(run_dir: Path, runtime: str) -> Path | None:
    """Bridge to ``vision.ml.resolve_variant_artifact``.

    Isolated so tests can monkeypatch this symbol without touching the
    legacy package.
    """
    from vision.ml import resolve_variant_artifact  # legacy-bridge

    return resolve_variant_artifact(run_dir, runtime)


def _build_processor(
    *,
    model_path: Path,
    model_family: str,
    runtime: str,
    imgsz: int,
    conf_threshold: float = _DEFAULT_CONF_THRESHOLD,
    iou_threshold: float = _DEFAULT_IOU_THRESHOLD,
) -> Any:
    """Bridge to ``vision.ml.create_processor``.

    Isolated so tests can monkeypatch this symbol.
    """
    from vision.ml import create_processor  # legacy-bridge

    return create_processor(
        model_path=model_path,
        model_family=model_family,
        runtime=runtime,
        imgsz=imgsz,
        conf_threshold=conf_threshold,
        iou_threshold=iou_threshold,
    )


def _make_lazy_factory(
    *,
    key: str,
    slug: str,
    model_id: str,
    model_path: Path,
    model_family: str,
    variant_runtime: str,
    imgsz: int,
    legacy_scopes: frozenset[str],
):
    """Return a ``factory(**kwargs) -> HiveDetector`` for the registry.

    The processor is instantiated lazily inside the factory call so importing
    ``rt.perception.detectors`` doesn't eagerly load every ONNX session.
    Callers may override ``conf_threshold`` / ``iou_threshold`` via ``**kwargs``.
    """

    def factory(
        *,
        conf_threshold: float = _DEFAULT_CONF_THRESHOLD,
        iou_threshold: float = _DEFAULT_IOU_THRESHOLD,
        processor: Any | None = None,
    ) -> HiveDetector:
        proc = processor if processor is not None else _build_processor(
            model_path=model_path,
            model_family=model_family,
            runtime=variant_runtime,
            imgsz=imgsz,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
        )
        return HiveDetector(
            model_id=model_id,
            slug=slug,
            processor=proc,
            imgsz=imgsz,
            model_family=model_family,
            legacy_scopes=legacy_scopes,
        )

    factory.__name__ = f"hive_detector_factory[{key}]"
    return factory


__all__ = [
    "HiveDetector",
    "discover_and_register_hive_detectors",
    "default_hive_detector_slug",
]
