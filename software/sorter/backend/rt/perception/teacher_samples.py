"""Move-triggered positive-sample collector for C-channel perception feeds.

The collector is a side-effect adapter: it observes the latest rt perception
state, archives local training samples when the operator enabled sample
collection, and never participates in piece-flow decisions.
"""

from __future__ import annotations

import base64
import logging
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import cv2
import numpy as np


LOG = logging.getLogger(__name__)

DEFAULT_SAMPLE_COLLECTION_INTERVAL_S = 30.0
DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT = 2
DEFAULT_SAMPLE_COLLECTION_GEMINI_WORKER_COUNT = 5
DEFAULT_SAMPLE_COLLECTION_ANGLE_STEP_DEG = 15.0
DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S = 3.0
DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE = 120
DEFAULT_SAMPLE_COLLECTION_MAX_PENDING_PER_ROLE = 20
_MIN_INTERVAL_S = 1.0
_MAX_INTERVAL_S = 3600.0
_MIN_WORKER_COUNT = 1
_MAX_WORKER_COUNT = 8
_MIN_ANGLE_STEP_DEG = 1.0
_MAX_ANGLE_STEP_DEG = 180.0
_MOVE_TRIGGER_SETTLE_S = 0.12
_MOVE_TRIGGER_MAX_DELAY_S = 3.0
_MIN_CROP_MEAN_GRAY = 3.0
_MIN_CROP_NONBLACK_RATIO = 0.01

_FEED_TO_SOURCE_ROLE = {
    "c2_feed": "c_channel_2",
    "c3_feed": "c_channel_3",
    "c4_feed": "classification_channel",
}

_SOURCE_ROLE_TO_SCOPE = {
    "c_channel_2": "feeder",
    "c_channel_3": "feeder",
    "classification_channel": "classification_channel",
}

_SOURCE_ROLE_TO_GEMINI_ZONE = {
    "c_channel_2": "c_channel",
    "c_channel_3": "c_channel",
    "classification_channel": "classification_channel",
}

_GEMINI_SAM_ALGORITHM = "gemini_sam"
_GEMINI_TIMEOUT_S = 25.0
_GEMINI_MAX_TOKENS = 2048
_GEMINI_MIN_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class TeacherSampleCollectionConfig:
    """Runtime-readable sample-collection flags from detection TOML config."""

    enabled_by_role: dict[str, bool]
    interval_s: float = DEFAULT_SAMPLE_COLLECTION_INTERVAL_S
    worker_count: int = DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT
    gemini_worker_count: int = DEFAULT_SAMPLE_COLLECTION_GEMINI_WORKER_COUNT
    angle_sample_degrees: float = DEFAULT_SAMPLE_COLLECTION_ANGLE_STEP_DEG
    min_capture_interval_s: float = DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S
    max_queue_size: int = DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE
    max_pending_per_role: int = DEFAULT_SAMPLE_COLLECTION_MAX_PENDING_PER_ROLE
    openrouter_model_by_role: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class TeacherDetection:
    """Gemini teacher output in local detector-input crop coordinates."""

    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    kind: str = "lego"
    description: str = "piece"


@dataclass(frozen=True, slots=True)
class TeacherAnnotation:
    """Parsed Gemini teacher response for one sampled frame."""

    model: str
    detections: tuple[TeacherDetection, ...]
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _CollectionTrigger:
    """Internal request to sample one or all roles."""

    reason: str
    source_role: str | None = None
    feed_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _QueuedTeacherSample:
    """Frozen crop waiting for Gemini-SAM teacher labeling."""

    source_role: str
    feed_id: str
    frame_seq: int
    crop: np.ndarray
    raw: np.ndarray
    bounds: tuple[int, int, int, int]
    crop_mode: str
    signal_stats: dict[str, float]
    trigger_reason: str
    trigger_metadata: dict[str, Any]
    model: str | None
    enqueued_at: float


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _coerce_interval(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    interval = float(value)
    if interval <= 0:
        return None
    return max(_MIN_INTERVAL_S, min(_MAX_INTERVAL_S, interval))


def _coerce_worker_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    if count <= 0:
        return None
    return max(_MIN_WORKER_COUNT, min(_MAX_WORKER_COUNT, count))


def _coerce_positive_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    count = int(value)
    if count <= 0:
        return default
    return max(minimum, min(maximum, count))


def _coerce_angle_step(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    step = float(value)
    if step <= 0:
        return None
    return max(_MIN_ANGLE_STEP_DEG, min(_MAX_ANGLE_STEP_DEG, step))


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _default_collection_config() -> TeacherSampleCollectionConfig:
    """Read C-channel sample-collection config from the TOML-backed service.

    The current setup page stores C2/C3/C4 toggles in the feeder config via
    ``sample_collection_enabled_by_role``. A historical classification-channel
    auxiliary config can still exist, so C4 accepts that as a fallback.
    """

    try:
        from server.detection_config.common import (
            get_classification_channel_detection_config,
            get_feeder_detection_config,
        )
    except Exception:
        LOG.debug("teacher-samples: detection config imports failed", exc_info=True)
        return TeacherSampleCollectionConfig(enabled_by_role={})

    try:
        feeder = get_feeder_detection_config() or {}
    except Exception:
        LOG.debug("teacher-samples: feeder config read failed", exc_info=True)
        feeder = {}
    try:
        classification_channel = get_classification_channel_detection_config() or {}
    except Exception:
        LOG.debug(
            "teacher-samples: classification-channel config read failed",
            exc_info=True,
        )
        classification_channel = {}

    feeder_by_role = feeder.get("sample_collection_enabled_by_role")
    feeder_by_role = feeder_by_role if isinstance(feeder_by_role, Mapping) else {}
    feeder_fallback = _coerce_bool(feeder.get("sample_collection_enabled"))
    c4_aux_fallback = _coerce_bool(
        classification_channel.get("sample_collection_enabled")
    )

    def _role_enabled(role: str) -> bool:
        explicit = _coerce_bool(feeder_by_role.get(role))
        if explicit is not None:
            return explicit
        if role == "classification_channel" and c4_aux_fallback is not None:
            return c4_aux_fallback
        return bool(feeder_fallback)

    interval_s = (
        _coerce_interval(feeder.get("sample_collection_interval_s"))
        or _coerce_interval(
            classification_channel.get("sample_collection_interval_s")
        )
        or DEFAULT_SAMPLE_COLLECTION_INTERVAL_S
    )
    worker_count = (
        _coerce_worker_count(feeder.get("sample_collection_worker_count"))
        or _coerce_worker_count(
            classification_channel.get("sample_collection_worker_count")
        )
        or DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT
    )
    gemini_worker_count = (
        _coerce_worker_count(feeder.get("sample_collection_gemini_worker_count"))
        or _coerce_worker_count(
            classification_channel.get("sample_collection_gemini_worker_count")
        )
        or DEFAULT_SAMPLE_COLLECTION_GEMINI_WORKER_COUNT
    )
    angle_sample_degrees = (
        _coerce_angle_step(feeder.get("sample_collection_angle_degrees"))
        or _coerce_angle_step(
            classification_channel.get("sample_collection_angle_degrees")
        )
        or DEFAULT_SAMPLE_COLLECTION_ANGLE_STEP_DEG
    )
    min_capture_interval_s = (
        _coerce_interval(feeder.get("sample_collection_min_capture_interval_s"))
        or _coerce_interval(
            classification_channel.get(
                "sample_collection_min_capture_interval_s"
            )
        )
        or DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S
    )
    max_queue_size = _coerce_positive_int(
        feeder.get("sample_collection_max_queue_size"),
        default=DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE,
        minimum=10,
        maximum=500,
    )
    max_pending_per_role = _coerce_positive_int(
        feeder.get("sample_collection_max_pending_per_role"),
        default=DEFAULT_SAMPLE_COLLECTION_MAX_PENDING_PER_ROLE,
        minimum=1,
        maximum=100,
    )
    feeder_model = feeder.get("openrouter_model")
    c4_model = classification_channel.get("openrouter_model")

    def _model(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    return TeacherSampleCollectionConfig(
        enabled_by_role={
            "c_channel_2": _role_enabled("c_channel_2"),
            "c_channel_3": _role_enabled("c_channel_3"),
            "classification_channel": _role_enabled("classification_channel"),
        },
        interval_s=interval_s,
        worker_count=worker_count,
        gemini_worker_count=gemini_worker_count,
        angle_sample_degrees=angle_sample_degrees,
        min_capture_interval_s=min_capture_interval_s,
        max_queue_size=max_queue_size,
        max_pending_per_role=max_pending_per_role,
        openrouter_model_by_role={
            "c_channel_2": _model(feeder_model) or "",
            "c_channel_3": _model(feeder_model) or "",
            "classification_channel": _model(c4_model) or _model(feeder_model) or "",
        },
    )


def _normalize_collection_config(config: Any) -> TeacherSampleCollectionConfig:
    if isinstance(config, TeacherSampleCollectionConfig):
        return config
    return TeacherSampleCollectionConfig(
        enabled_by_role=dict(getattr(config, "enabled_by_role", {}) or {}),
        interval_s=float(
            getattr(config, "interval_s", DEFAULT_SAMPLE_COLLECTION_INTERVAL_S)
        ),
        worker_count=_coerce_worker_count(getattr(config, "worker_count", None))
        or DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT,
        gemini_worker_count=_coerce_worker_count(
            getattr(config, "gemini_worker_count", None)
        )
        or DEFAULT_SAMPLE_COLLECTION_GEMINI_WORKER_COUNT,
        angle_sample_degrees=_coerce_angle_step(
            getattr(config, "angle_sample_degrees", None)
        )
        or DEFAULT_SAMPLE_COLLECTION_ANGLE_STEP_DEG,
        min_capture_interval_s=_coerce_interval(
            getattr(config, "min_capture_interval_s", None)
        )
        or DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S,
        max_queue_size=_coerce_positive_int(
            getattr(config, "max_queue_size", None),
            default=DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE,
            minimum=10,
            maximum=500,
        ),
        max_pending_per_role=_coerce_positive_int(
            getattr(config, "max_pending_per_role", None),
            default=DEFAULT_SAMPLE_COLLECTION_MAX_PENDING_PER_ROLE,
            minimum=1,
            maximum=100,
        ),
        openrouter_model_by_role=dict(
            getattr(config, "openrouter_model_by_role", {}) or {}
        ),
    )


def _default_training_manager() -> Any:
    from server.classification_training import getClassificationTrainingManager

    return getClassificationTrainingManager()


def _feed_id_for_runner(runner: Any) -> str | None:
    pipeline = getattr(runner, "_pipeline", None)
    feed = getattr(pipeline, "feed", None)
    feed_id = getattr(feed, "feed_id", None)
    return feed_id if isinstance(feed_id, str) and feed_id else None


def _state_from_runner(runner: Any) -> Any | None:
    latest_state = getattr(runner, "latest_state", None)
    if not callable(latest_state):
        return None
    return latest_state()


def _pipeline_from_runner(runner: Any) -> Any | None:
    pipeline = getattr(runner, "_pipeline", None)
    return pipeline


def _bbox_tuple(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = (int(value[idx]) for idx in range(4))
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _full_frame_bbox(
    bbox: tuple[int, int, int, int],
    crop_bounds: tuple[int, int, int, int],
) -> list[int]:
    ox, oy, _, _ = crop_bounds
    return [
        int(bbox[0] + ox),
        int(bbox[1] + oy),
        int(bbox[2] + ox),
        int(bbox[3] + oy),
    ]


def _encode_jpeg_b64(frame: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("Failed to encode Gemini teacher frame.")
    return base64.b64encode(buf).decode("utf-8")


def _crop_signal_stats(frame: np.ndarray) -> dict[str, float]:
    if frame is None or getattr(frame, "size", 0) <= 0:
        return {"mean_gray": 0.0, "nonblack_ratio": 0.0}
    if len(frame.shape) >= 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    return {
        "mean_gray": float(gray.mean()),
        "nonblack_ratio": float((gray > 8).mean()),
    }


def _crop_has_enough_signal(frame: np.ndarray) -> tuple[bool, dict[str, float]]:
    stats = _crop_signal_stats(frame)
    return (
        stats["mean_gray"] >= _MIN_CROP_MEAN_GRAY
        and stats["nonblack_ratio"] >= _MIN_CROP_NONBLACK_RATIO,
        stats,
    )


def _parse_normalized_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)):
        if len(value) < 4:
            return None
        try:
            return tuple(float(item) for item in value[:4])  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            import json

            return _parse_normalized_bbox(json.loads(value))
        except Exception:
            return None
    if isinstance(value, dict):
        key_variants = (
            ("y_min", "x_min", "y_max", "x_max"),
            ("ymin", "xmin", "ymax", "xmax"),
            ("top", "left", "bottom", "right"),
            ("y1", "x1", "y2", "x2"),
            ("min_y", "min_x", "max_y", "max_x"),
        )
        for keys in key_variants:
            if not all(key in value for key in keys):
                continue
            try:
                return tuple(float(value[key]) for key in keys)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None
    return None


def _gemini_system_prompt() -> str:
    return (
        "You are a precise object detector for a LEGO sorting machine. "
        "Detect loose LEGO pieces and loose foreign objects that are actually "
        "inside the sampled detector input. Fixed machine geometry is never "
        "an object. Return valid JSON only: no markdown, no prose, no code fences."
    )


_GEMINI_ZONE_PROMPTS: dict[str, tuple[str, str]] = {
    "classification_channel": (
        "The image comes from the classification C-channel / C4 turntable. "
        "A top-down camera watches a rotating turntable and its transfer/drop "
        "area while parts move toward classification and ejection.",
        "Ignore the turntable surface, fixed dark center/opening, exit chute, "
        "outlet slot, rails, screws, lips, fixed black wedges/openings, LED "
        "glare, specular reflections, and shadows. These are machine geometry, "
        "not pieces. Only label loose physical items sitting on or moving over "
        "that geometry.",
    ),
    "c_channel": (
        "The image comes from a C-shaped feed channel. A top-down camera watches "
        "a narrow machine channel where loose parts slide toward the next station.",
        "Ignore the channel surface, fixed side walls, rails, screws, slots, "
        "dark fixed openings, specular reflections, and shadows. These are "
        "machine geometry, not pieces. Only label loose physical items.",
    ),
}


def _gemini_prompt(width: int, height: int, zone: str) -> str:
    context, ignore_rules = _GEMINI_ZONE_PROMPTS.get(
        zone,
        _GEMINI_ZONE_PROMPTS["c_channel"],
    )
    return (
        f"{context}\n\n"
        f"{ignore_rules}\n\n"
        "The input image is already the same detector-input crop used by the "
        "local YOLO model. Pixels outside a configured active polygon may be "
        "solid black or white; treat those masked pixels as out-of-frame and "
        "never as an object. A small visible apron/context band may exist around "
        "the active region; fixed hardware in that band is still not an object.\n\n"
        "Detection rules:\n"
        "- Detect every distinct loose physical item exactly once: LEGO parts "
        "and loose foreign objects such as coins, pebbles, plastic fragments, "
        "tape, hair, wrappers, or tools.\n"
        "- Do not detect fixed machine geometry, even if it is dark, high "
        "contrast, or shaped like a part. In particular, ignore outlet slots, "
        "exit chutes, turntable holes, fixed black shadows/openings, rails, and "
        "walls.\n"
        "- Return a tight bounding box covering each loose item's full extent, "
        "including glare on the item itself.\n"
        "- Ignore dust, scratches, lighting gradients, and shadows unless there "
        "is a clear loose object casting them.\n"
        "- If two items are touching but visually separable, return one box per "
        "item; if fused into one indistinct cluster, return one box covering the "
        "cluster.\n"
        f"- Omit detections with confidence below {_GEMINI_MIN_CONFIDENCE:.1f}.\n"
        "- If no loose items are visible, return an empty detections array.\n\n"
        "Output format (JSON only):\n"
        '{"detections":[{"kind":"lego|foreign","description":"<short label>",'
        '"bbox":[y_min,x_min,y_max,x_max],"confidence":0.0}]}\n\n'
        "Field semantics:\n"
        "- bbox: Gemini normalized 0-1000 scale, order "
        f"[y_min, x_min, y_max, x_max], for this {width}x{height} image.\n"
        "- kind: 'lego' for LEGO/compatible plastic parts; 'foreign' for any "
        "loose non-LEGO object. If unsure whether it is LEGO, prefer 'foreign'.\n"
        "- confidence: confidence that this is a loose physical item, not "
        "confidence in the LEGO-vs-foreign class."
    )


class GeminiSamTeacherAnnotator:
    """OpenRouter/Gemini teacher that produces training labels for samples."""

    def annotate(
        self,
        image: np.ndarray,
        *,
        source_role: str,
        feed_id: str,
        model: str | None,
    ) -> TeacherAnnotation:
        from server.services.llm_client import (
            chat_completion,
            extract_json_object,
            message_text,
            normalize_openrouter_model,
        )

        h, w = image.shape[:2]
        if w <= 0 or h <= 0:
            return TeacherAnnotation(
                model=normalize_openrouter_model(model),
                detections=(),
                raw_payload={"detections": []},
            )

        normalized_model = normalize_openrouter_model(model)
        prompt = _gemini_prompt(
            w,
            h,
            _SOURCE_ROLE_TO_GEMINI_ZONE.get(source_role, "c_channel"),
        )
        image_b64 = _encode_jpeg_b64(image)
        messages = [
            {"role": "system", "content": _gemini_system_prompt()},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"{prompt}\n\nfeed_id: {feed_id}\nsource_role: {source_role}",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ]
        try:
            response = chat_completion(
                messages,
                model=normalized_model,
                response_format={"type": "json_object"},
                max_tokens=_GEMINI_MAX_TOKENS,
                timeout=_GEMINI_TIMEOUT_S,
            )
        except Exception:
            response = chat_completion(
                messages,
                model=normalized_model,
                max_tokens=_GEMINI_MAX_TOKENS,
                timeout=_GEMINI_TIMEOUT_S,
            )
        try:
            payload = extract_json_object(
                message_text(response.choices[0].message.content)
            )
        except Exception as exc:
            raise RuntimeError("Gemini teacher returned invalid JSON") from exc
        detections = _parse_gemini_detections(payload, width=w, height=h)
        return TeacherAnnotation(
            model=normalized_model,
            detections=tuple(detections),
            raw_payload=payload,
        )


def _parse_gemini_detections(
    payload: dict[str, Any],
    *,
    width: int,
    height: int,
) -> list[TeacherDetection]:
    raw_detections = payload.get("detections")
    if not isinstance(raw_detections, list):
        return []
    sx = float(width) / 1000.0
    sy = float(height) / 1000.0
    parsed: list[TeacherDetection] = []
    for item in raw_detections:
        if not isinstance(item, dict):
            continue
        normalized_bbox = _parse_normalized_bbox(item.get("bbox"))
        if normalized_bbox is None:
            continue
        y1n, x1n, y2n, x2n = normalized_bbox
        x1 = int(max(0.0, min(1000.0, x1n)) * sx)
        y1 = int(max(0.0, min(1000.0, y1n)) * sy)
        x2 = int(max(0.0, min(1000.0, x2n)) * sx)
        y2 = int(max(0.0, min(1000.0, y2n)) * sy)
        bbox = _bbox_tuple((x1, y1, x2, y2))
        if bbox is None:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < _GEMINI_MIN_CONFIDENCE:
            continue
        kind = str(item.get("kind") or "lego").strip().lower()
        if kind not in {"lego", "foreign"}:
            kind = "foreign"
        description = str(item.get("description") or "piece").strip() or "piece"
        parsed.append(
            TeacherDetection(
                bbox_xyxy=bbox,
                confidence=confidence,
                kind=kind,
                description=description,
            )
        )
    return parsed


def _default_teacher_annotator() -> GeminiSamTeacherAnnotator:
    return GeminiSamTeacherAnnotator()


def _teacher_input_crop(
    raw: np.ndarray,
    runner: Any,
) -> tuple[np.ndarray, tuple[int, int, int, int], str] | None:
    """Return the clean teacher image for one runtime perception frame."""

    pipeline = _pipeline_from_runner(runner)
    if pipeline is None:
        return None
    zone = getattr(pipeline, "zone", None)
    try:
        from rt.contracts.feed import PolygonZone
        from utils.polygon_crop import apply_polygon_crop
    except Exception:
        PolygonZone = None  # type: ignore[assignment]
        apply_polygon_crop = None  # type: ignore[assignment]

    if PolygonZone is not None and isinstance(zone, PolygonZone):
        if apply_polygon_crop is None:
            return None
        crop, offset = apply_polygon_crop(raw, zone.vertices)
        if crop is None or getattr(crop, "size", 0) <= 0:
            return None
        ox, oy = offset
        contiguous = np.ascontiguousarray(crop)
        return (
            contiguous,
            (
                int(ox),
                int(oy),
                int(ox + contiguous.shape[1]),
                int(oy + contiguous.shape[0]),
            ),
            "polygon_masked_zone",
        )

    detector = getattr(pipeline, "detector", None)
    apply_zone = getattr(detector, "_apply_zone", None)
    if not callable(apply_zone) or zone is None:
        return None
    try:
        crop, offset = apply_zone(raw, zone)
    except NotImplementedError:
        return None
    if crop is None or getattr(crop, "size", 0) <= 0:
        return None
    ox, oy = offset
    contiguous = np.ascontiguousarray(crop)
    return (
        contiguous,
        (
            int(ox),
            int(oy),
            int(ox + contiguous.shape[1]),
            int(oy + contiguous.shape[0]),
        ),
        "detector_apply_zone",
    )


class AuxiliaryTeacherSampleCollector:
    """Archives positive C-channel samples from the latest rt perception state."""

    def __init__(
        self,
        *,
        runner_provider: Callable[[], list[Any]],
        config_provider: Callable[[], TeacherSampleCollectionConfig] | None = None,
        training_manager_provider: Callable[[], Any] | None = None,
        teacher_annotator_provider: Callable[[], Any] | None = None,
        event_bus: Any | None = None,
        move_trigger_settle_s: float = _MOVE_TRIGGER_SETTLE_S,
        logger: logging.Logger | None = None,
    ) -> None:
        self._runner_provider = runner_provider
        self._config_provider = config_provider or _default_collection_config
        self._training_manager_provider = (
            training_manager_provider or _default_training_manager
        )
        self._teacher_annotator_provider = (
            teacher_annotator_provider or _default_teacher_annotator
        )
        self._event_bus = event_bus
        self._move_trigger_settle_s = max(0.0, float(move_trigger_settle_s))
        self._log = logger or LOG
        self._threads: list[threading.Thread] = []
        self._gemini_threads: list[threading.Thread] = []
        self._move_subscription: Any | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._trigger_cv = threading.Condition(self._lock)
        self._sample_queue: queue.Queue[_QueuedTeacherSample] = queue.Queue(
            maxsize=DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE
        )
        self._pending_triggers: list[_CollectionTrigger] = []
        self._running = False
        self._last_seen_frame_by_role: dict[str, int] = {}
        self._last_attempted_frame_by_role: dict[str, int] = {}
        self._last_captured_frame_by_role: dict[str, int] = {}
        self._last_trigger_wall_ts_by_role: dict[str, float] = {}
        self._last_trigger_reason_by_role: dict[str, str] = {}
        self._last_trigger_feed_by_role: dict[str, str] = {}
        self._enabled_by_role: dict[str, bool] = {}
        self._interval_s = DEFAULT_SAMPLE_COLLECTION_INTERVAL_S
        self._worker_count = DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT
        self._gemini_worker_count = DEFAULT_SAMPLE_COLLECTION_GEMINI_WORKER_COUNT
        self._angle_sample_degrees = DEFAULT_SAMPLE_COLLECTION_ANGLE_STEP_DEG
        self._min_capture_interval_s = DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S
        self._max_queue_size = DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE
        self._max_pending_per_role = DEFAULT_SAMPLE_COLLECTION_MAX_PENDING_PER_ROLE
        self._angle_remainder_by_role: dict[str, float] = {}
        self._last_queued_capture_wall_ts_by_role: dict[str, float] = {}
        self._captured_count = 0
        self._queued_capture_count = 0
        self._queued_capture_count_by_role: dict[str, int] = {}
        self._sample_queue_depth_by_role: dict[str, int] = {}
        self._sample_queue_dropped = 0
        self._sample_queue_dropped_by_role: dict[str, int] = {}
        self._gemini_completed_count = 0
        self._gemini_completed_count_by_role: dict[str, int] = {}
        self._move_event_count = 0
        self._angle_trigger_count = 0
        self._angle_trigger_count_by_role: dict[str, int] = {}
        self._subthreshold_move_count = 0
        self._subthreshold_move_count_by_role: dict[str, int] = {}
        self._triggered_collection_count = 0
        self._trigger_queue_coalesced = 0
        self._skipped_unknown_feed = 0
        self._skipped_failed_move = 0
        self._trigger_queue_dropped = 0
        self._skipped_disabled = 0
        self._skipped_no_state = 0
        self._skipped_low_signal = 0
        self._skipped_throttled = 0
        self._skipped_no_detections = 0
        self._skipped_teacher_no_detections = 0
        self._skipped_duplicate_frame = 0
        self._teacher_call_count = 0
        self._error_count = 0
        self._last_capture_wall_ts: float | None = None
        self._last_error: str | None = None
        self._captured_count_by_role: dict[str, int] = {}
        self._move_event_count_by_role: dict[str, int] = {}
        self._triggered_collection_count_by_role: dict[str, int] = {}
        self._trigger_queue_coalesced_by_role: dict[str, int] = {}
        self._skipped_failed_move_by_role: dict[str, int] = {}
        self._skipped_disabled_by_role: dict[str, int] = {}
        self._skipped_no_state_by_role: dict[str, int] = {}
        self._skipped_low_signal_by_role: dict[str, int] = {}
        self._skipped_throttled_by_role: dict[str, int] = {}
        self._skipped_no_detections_by_role: dict[str, int] = {}
        self._skipped_teacher_no_detections_by_role: dict[str, int] = {}
        self._skipped_duplicate_frame_by_role: dict[str, int] = {}
        self._teacher_call_count_by_role: dict[str, int] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._refresh_config_snapshot()
        self._subscribe_move_events()
        with self._lock:
            worker_count = self._worker_count
            gemini_worker_count = self._gemini_worker_count
        self._threads = [
            threading.Thread(
                target=self._run,
                name=f"AuxiliaryTeacherSampleCapture-{idx + 1}",
                daemon=True,
            )
            for idx in range(worker_count)
        ]
        self._gemini_threads = [
            threading.Thread(
                target=self._run_gemini_worker,
                name=f"AuxiliaryTeacherSampleGemini-{idx + 1}",
                daemon=True,
            )
            for idx in range(gemini_worker_count)
        ]
        for thread in self._threads:
            thread.start()
        for thread in self._gemini_threads:
            thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        with self._trigger_cv:
            self._trigger_cv.notify_all()
        self._unsubscribe_move_events()
        threads = [*self._threads, *self._gemini_threads]
        for thread in threads:
            thread.join(timeout=timeout)
        self._threads = []
        self._gemini_threads = []

    def _refresh_config_snapshot(self) -> TeacherSampleCollectionConfig | None:
        try:
            config = _normalize_collection_config(self._config_provider())
        except Exception as exc:
            self._record_error(exc)
            self._log_exception("teacher-samples: config provider raised")
            return None
        with self._lock:
            self._enabled_by_role = dict(config.enabled_by_role)
            self._interval_s = max(
                _MIN_INTERVAL_S,
                min(_MAX_INTERVAL_S, float(config.interval_s)),
            )
            self._worker_count = (
                _coerce_worker_count(config.worker_count)
                or DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT
            )
            self._gemini_worker_count = (
                _coerce_worker_count(config.gemini_worker_count)
                or DEFAULT_SAMPLE_COLLECTION_GEMINI_WORKER_COUNT
            )
            self._angle_sample_degrees = (
                _coerce_angle_step(config.angle_sample_degrees)
                or DEFAULT_SAMPLE_COLLECTION_ANGLE_STEP_DEG
            )
            self._min_capture_interval_s = (
                _coerce_interval(config.min_capture_interval_s)
                or DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S
            )
            self._max_queue_size = _coerce_positive_int(
                config.max_queue_size,
                default=DEFAULT_SAMPLE_COLLECTION_QUEUE_SIZE,
                minimum=10,
                maximum=500,
            )
            self._max_pending_per_role = _coerce_positive_int(
                config.max_pending_per_role,
                default=DEFAULT_SAMPLE_COLLECTION_MAX_PENDING_PER_ROLE,
                minimum=1,
                maximum=100,
            )
            if self._sample_queue.maxsize != self._max_queue_size and not self._running:
                self._sample_queue = queue.Queue(maxsize=self._max_queue_size)
        return config

    @staticmethod
    def _bump_role(counter: dict[str, int], source_role: str, amount: int = 1) -> None:
        counter[source_role] = int(counter.get(source_role, 0)) + int(amount)

    def collect_once(
        self,
        *,
        source_roles: set[str] | None = None,
        trigger_reason: str = "rt_manual_collect",
        trigger_metadata: dict[str, Any] | None = None,
    ) -> int:
        """Run one collection pass. Public for tests and manual probes."""

        config = self._refresh_config_snapshot()
        if config is None:
            return 0

        captured = 0
        try:
            runners = list(self._runner_provider() or [])
        except Exception as exc:
            self._record_error(exc)
            self._log_exception("teacher-samples: runner provider raised")
            return 0

        for runner in runners:
            try:
                if source_roles:
                    feed_id = _feed_id_for_runner(runner)
                    source_role = _FEED_TO_SOURCE_ROLE.get(feed_id or "")
                    if source_role not in source_roles:
                        continue
                if self._collect_from_runner(
                    runner,
                    config,
                    trigger_reason=trigger_reason,
                    trigger_metadata=trigger_metadata or {},
                ):
                    captured += 1
            except Exception as exc:
                self._record_error(exc)
                self._log_exception("teacher-samples: collection pass raised")
        return captured

    def status_snapshot(self) -> dict[str, Any]:
        threads = list(self._threads)
        gemini_threads = list(self._gemini_threads)
        alive_worker_count = sum(1 for thread in threads if thread.is_alive())
        alive_gemini_worker_count = sum(
            1 for thread in gemini_threads if thread.is_alive()
        )
        with self._lock:
            return {
                "installed": True,
                "running": bool(self._running),
                "thread_alive": alive_worker_count > 0 and alive_gemini_worker_count > 0,
                "worker_count": self._worker_count,
                "alive_worker_count": alive_worker_count,
                "gemini_worker_count": self._gemini_worker_count,
                "alive_gemini_worker_count": alive_gemini_worker_count,
                "collection_mode": "event_driven_rotation",
                "periodic_enabled": False,
                "interval_s": None,
                "configured_interval_s": self._interval_s,
                "enabled_by_role": dict(self._enabled_by_role),
                "move_trigger_settle_s": self._move_trigger_settle_s,
                "angle_sample_degrees": self._angle_sample_degrees,
                "min_capture_interval_s": self._min_capture_interval_s,
                "angle_remainder_by_role": dict(self._angle_remainder_by_role),
                "last_queued_capture_wall_ts_by_role": dict(
                    self._last_queued_capture_wall_ts_by_role
                ),
                "sample_queue_depth": self._sample_queue.qsize(),
                "sample_queue_max_size": self._max_queue_size,
                "sample_queue_depth_by_role": dict(self._sample_queue_depth_by_role),
                "sample_queue_dropped": self._sample_queue_dropped,
                "sample_queue_dropped_by_role": dict(
                    self._sample_queue_dropped_by_role
                ),
                "queued_capture_count": self._queued_capture_count,
                "queued_capture_count_by_role": dict(
                    self._queued_capture_count_by_role
                ),
                "gemini_completed_count": self._gemini_completed_count,
                "gemini_completed_count_by_role": dict(
                    self._gemini_completed_count_by_role
                ),
                "captured_count": self._captured_count,
                "move_event_count": self._move_event_count,
                "angle_trigger_count": self._angle_trigger_count,
                "angle_trigger_count_by_role": dict(
                    self._angle_trigger_count_by_role
                ),
                "subthreshold_move_count": self._subthreshold_move_count,
                "subthreshold_move_count_by_role": dict(
                    self._subthreshold_move_count_by_role
                ),
                "triggered_collection_count": self._triggered_collection_count,
                "trigger_queue_depth": len(self._pending_triggers),
                "trigger_queue_coalesced": self._trigger_queue_coalesced,
                "trigger_queue_dropped": self._trigger_queue_dropped,
                "skipped_unknown_feed": self._skipped_unknown_feed,
                "skipped_failed_move": self._skipped_failed_move,
                "skipped_disabled": self._skipped_disabled,
                "skipped_no_state": self._skipped_no_state,
                "skipped_low_signal": self._skipped_low_signal,
                "skipped_throttled": self._skipped_throttled,
                "skipped_no_detections": self._skipped_no_detections,
                "skipped_teacher_no_detections": self._skipped_teacher_no_detections,
                "skipped_duplicate_frame": self._skipped_duplicate_frame,
                "teacher_call_count": self._teacher_call_count,
                "error_count": self._error_count,
                "last_capture_wall_ts": self._last_capture_wall_ts,
                "last_error": self._last_error,
                "last_seen_frame_by_role": dict(self._last_seen_frame_by_role),
                "last_attempted_frame_by_role": dict(
                    self._last_attempted_frame_by_role
                ),
                "last_captured_frame_by_role": dict(
                    self._last_captured_frame_by_role
                ),
                "last_trigger_wall_ts_by_role": dict(
                    self._last_trigger_wall_ts_by_role
                ),
                "last_trigger_reason_by_role": dict(
                    self._last_trigger_reason_by_role
                ),
                "last_trigger_feed_by_role": dict(self._last_trigger_feed_by_role),
                "captured_count_by_role": dict(self._captured_count_by_role),
                "move_event_count_by_role": dict(self._move_event_count_by_role),
                "triggered_collection_count_by_role": dict(
                    self._triggered_collection_count_by_role
                ),
                "trigger_queue_coalesced_by_role": dict(
                    self._trigger_queue_coalesced_by_role
                ),
                "skipped_failed_move_by_role": dict(
                    self._skipped_failed_move_by_role
                ),
                "skipped_disabled_by_role": dict(self._skipped_disabled_by_role),
                "skipped_no_state_by_role": dict(self._skipped_no_state_by_role),
                "skipped_low_signal_by_role": dict(
                    self._skipped_low_signal_by_role
                ),
                "skipped_throttled_by_role": dict(
                    self._skipped_throttled_by_role
                ),
                "skipped_no_detections_by_role": dict(
                    self._skipped_no_detections_by_role
                ),
                "skipped_teacher_no_detections_by_role": dict(
                    self._skipped_teacher_no_detections_by_role
                ),
                "skipped_duplicate_frame_by_role": dict(
                    self._skipped_duplicate_frame_by_role
                ),
                "teacher_call_count_by_role": dict(self._teacher_call_count_by_role),
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._trigger_cv:
                while not self._pending_triggers and not self._stop.is_set():
                    self._trigger_cv.wait(timeout=0.25)
                if self._stop.is_set():
                    break
                trigger = self._pending_triggers.pop(0)
            try:
                self._process_trigger(trigger)
            except Exception as exc:
                self._record_error(exc)
                self._log_exception("teacher-samples: trigger processing raised")

    def _subscribe_move_events(self) -> None:
        if self._event_bus is None or self._move_subscription is not None:
            return
        try:
            from rt.events.topics import RUNTIME_MOVE_COMPLETED

            subscribe = getattr(self._event_bus, "subscribe", None)
            if not callable(subscribe):
                return
            self._move_subscription = subscribe(
                RUNTIME_MOVE_COMPLETED,
                self._on_move_completed_event,
            )
        except Exception as exc:
            self._record_error(exc)
            self._log_exception("teacher-samples: move-event subscribe failed")

    def _unsubscribe_move_events(self) -> None:
        subscription = self._move_subscription
        self._move_subscription = None
        if subscription is None:
            return
        try:
            unsubscribe = getattr(subscription, "unsubscribe", None)
            if callable(unsubscribe):
                unsubscribe()
        except Exception as exc:
            self._record_error(exc)
            self._log_exception("teacher-samples: move-event unsubscribe failed")

    def _on_move_completed_event(self, event: Any) -> None:
        payload = getattr(event, "payload", None)
        payload = payload if isinstance(payload, Mapping) else {}
        raw_feed_id = payload.get("feed_id")
        feed_id = raw_feed_id.strip() if isinstance(raw_feed_id, str) else ""
        source_role = _FEED_TO_SOURCE_ROLE.get(feed_id)
        if source_role is None:
            with self._lock:
                self._skipped_unknown_feed += 1
            return
        if payload.get("ok") is False:
            with self._lock:
                self._skipped_failed_move += 1
                self._bump_role(self._skipped_failed_move_by_role, source_role)
            return

        move_degrees = _coerce_float(payload.get("degrees"))
        trigger_count = 1
        with self._lock:
            self._move_event_count += 1
            self._bump_role(self._move_event_count_by_role, source_role)
            if move_degrees is not None:
                moved = abs(float(move_degrees))
                accumulated = (
                    float(self._angle_remainder_by_role.get(source_role, 0.0))
                    + moved
                )
                step = max(_MIN_ANGLE_STEP_DEG, float(self._angle_sample_degrees))
                trigger_count = int(accumulated // step)
                self._angle_remainder_by_role[source_role] = accumulated % step
                if trigger_count <= 0:
                    self._subthreshold_move_count += 1
                    self._bump_role(self._subthreshold_move_count_by_role, source_role)
                    return
                self._angle_trigger_count += trigger_count
                self._bump_role(
                    self._angle_trigger_count_by_role,
                    source_role,
                    trigger_count,
                )

        now_wall = time.time()
        completed_ts = payload.get("completed_ts")
        target_wall_ts = now_wall + self._move_trigger_settle_s
        if isinstance(completed_ts, (int, float)) and not isinstance(completed_ts, bool):
            target_wall_ts = (
                float(completed_ts) + self._move_trigger_settle_s
                if float(completed_ts) > now_wall
                else target_wall_ts
            )
        not_before_wall_ts = min(target_wall_ts, now_wall + _MOVE_TRIGGER_MAX_DELAY_S)
        for index in range(trigger_count):
            trigger = _CollectionTrigger(
                reason="rt_move_completed",
                source_role=source_role,
                feed_id=feed_id,
                metadata={
                    "move_source": payload.get("source"),
                    "move_completed_ts": payload.get("completed_ts"),
                    "move_duration_ms": payload.get("duration_ms"),
                    "move_degrees": payload.get("degrees"),
                    "angle_sample_degrees": self._angle_sample_degrees,
                    "angle_trigger_index": index,
                    "angle_trigger_count": trigger_count,
                    "not_before_wall_ts": not_before_wall_ts,
                },
            )
            self._enqueue_trigger(trigger)

    def _enqueue_trigger(self, trigger: _CollectionTrigger) -> None:
        with self._trigger_cv:
            self._pending_triggers.append(trigger)
            self._trigger_cv.notify()

    def _process_trigger(self, trigger: _CollectionTrigger) -> int:
        not_before = trigger.metadata.get("not_before_wall_ts")
        if isinstance(not_before, (int, float)) and not isinstance(not_before, bool):
            while not self._stop.is_set():
                remaining = float(not_before) - time.time()
                if remaining <= 0:
                    break
                self._stop.wait(timeout=min(remaining, 0.1))
        if self._stop.is_set():
            return 0

        source_roles = {trigger.source_role} if trigger.source_role else None
        with self._lock:
            if trigger.source_role:
                self._last_trigger_wall_ts_by_role[trigger.source_role] = time.time()
                self._last_trigger_reason_by_role[trigger.source_role] = trigger.reason
                if trigger.feed_id:
                    self._last_trigger_feed_by_role[trigger.source_role] = trigger.feed_id
        queued = self._enqueue_samples_once(
            source_roles=source_roles,
            trigger_reason=trigger.reason,
            trigger_metadata=trigger.metadata,
        )
        with self._lock:
            self._triggered_collection_count += 1
            if trigger.source_role:
                self._bump_role(
                    self._triggered_collection_count_by_role,
                    trigger.source_role,
                )
        return queued

    def _enqueue_samples_once(
        self,
        *,
        source_roles: set[str] | None,
        trigger_reason: str,
        trigger_metadata: dict[str, Any],
    ) -> int:
        config = self._refresh_config_snapshot()
        if config is None:
            return 0

        try:
            runners = list(self._runner_provider() or [])
        except Exception as exc:
            self._record_error(exc)
            self._log_exception("teacher-samples: runner provider raised")
            return 0

        queued = 0
        for runner in runners:
            try:
                if source_roles:
                    feed_id = _feed_id_for_runner(runner)
                    source_role = _FEED_TO_SOURCE_ROLE.get(feed_id or "")
                    if source_role not in source_roles:
                        continue
                sample = self._capture_from_runner(
                    runner,
                    config,
                    trigger_reason=trigger_reason,
                    trigger_metadata=trigger_metadata,
                )
                if sample is not None and self._enqueue_sample(sample):
                    queued += 1
            except Exception as exc:
                self._record_error(exc)
                self._log_exception("teacher-samples: sample enqueue raised")
        return queued

    def _enqueue_sample(self, sample: _QueuedTeacherSample) -> bool:
        source_role = sample.source_role
        now = time.time()
        with self._lock:
            last_queued = self._last_queued_capture_wall_ts_by_role.get(source_role)
            if (
                isinstance(last_queued, (int, float))
                and now - float(last_queued) < self._min_capture_interval_s
            ):
                self._skipped_throttled += 1
                self._bump_role(self._skipped_throttled_by_role, source_role)
                return False
            role_depth = int(self._sample_queue_depth_by_role.get(source_role, 0))
            if role_depth >= self._max_pending_per_role:
                self._sample_queue_dropped += 1
                self._bump_role(self._sample_queue_dropped_by_role, source_role)
                return False
            self._sample_queue_depth_by_role[source_role] = role_depth + 1
        try:
            self._sample_queue.put_nowait(sample)
        except queue.Full:
            with self._lock:
                self._sample_queue_depth_by_role[source_role] = max(
                    0,
                    int(self._sample_queue_depth_by_role.get(source_role, 1)) - 1,
                )
                self._sample_queue_dropped += 1
                self._bump_role(self._sample_queue_dropped_by_role, source_role)
            return False
        with self._lock:
            self._last_queued_capture_wall_ts_by_role[source_role] = now
            self._queued_capture_count += 1
            self._bump_role(self._queued_capture_count_by_role, source_role)
        return True

    def _run_gemini_worker(self) -> None:
        while not self._stop.is_set() or not self._sample_queue.empty():
            try:
                sample = self._sample_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._process_queued_sample(sample)
            except Exception as exc:
                self._record_error(exc)
                self._log_exception("teacher-samples: Gemini worker raised")
            finally:
                with self._lock:
                    self._sample_queue_depth_by_role[sample.source_role] = max(
                        0,
                        int(
                            self._sample_queue_depth_by_role.get(
                                sample.source_role,
                                1,
                            )
                        )
                        - 1,
                    )
                self._sample_queue.task_done()

    def _collect_from_runner(
        self,
        runner: Any,
        config: TeacherSampleCollectionConfig,
        *,
        trigger_reason: str,
        trigger_metadata: dict[str, Any],
    ) -> bool:
        sample = self._capture_from_runner(
            runner,
            config,
            trigger_reason=trigger_reason,
            trigger_metadata=trigger_metadata,
        )
        if sample is None:
            return False
        return self._process_queued_sample(sample)

    def _capture_from_runner(
        self,
        runner: Any,
        config: TeacherSampleCollectionConfig,
        *,
        trigger_reason: str,
        trigger_metadata: dict[str, Any],
    ) -> _QueuedTeacherSample | None:
        feed_id = _feed_id_for_runner(runner)
        source_role = _FEED_TO_SOURCE_ROLE.get(feed_id or "")
        if source_role is None:
            return None
        if not bool(config.enabled_by_role.get(source_role, False)):
            with self._lock:
                self._skipped_disabled += 1
                self._bump_role(self._skipped_disabled_by_role, source_role)
            return None

        state = _state_from_runner(runner)
        frame = getattr(state, "frame", None) if state is not None else None
        raw = getattr(frame, "raw", None) if frame is not None else None
        frame_seq = getattr(frame, "frame_seq", None) if frame is not None else None
        if raw is None or not hasattr(raw, "shape") or not isinstance(frame_seq, int):
            with self._lock:
                self._skipped_no_state += 1
                self._bump_role(self._skipped_no_state_by_role, source_role)
            return None

        with self._lock:
            self._last_seen_frame_by_role[source_role] = int(frame_seq)
            if self._last_attempted_frame_by_role.get(source_role) == int(frame_seq):
                self._skipped_duplicate_frame += 1
                self._bump_role(self._skipped_duplicate_frame_by_role, source_role)
                return None

        crop_result = _teacher_input_crop(raw, runner)
        if crop_result is None:
            with self._lock:
                self._skipped_no_state += 1
                self._bump_role(self._skipped_no_state_by_role, source_role)
            return None
        crop, bounds, crop_mode = crop_result
        if crop is None or getattr(crop, "size", 0) <= 0:
            with self._lock:
                self._skipped_no_state += 1
                self._bump_role(self._skipped_no_state_by_role, source_role)
            return None

        has_signal, signal_stats = _crop_has_enough_signal(crop)

        with self._lock:
            self._last_attempted_frame_by_role[source_role] = int(frame_seq)
            if not has_signal:
                self._skipped_low_signal += 1
                self._bump_role(self._skipped_low_signal_by_role, source_role)
                return None

        feed_id = feed_id or getattr(frame, "feed_id", None) or source_role
        return _QueuedTeacherSample(
            source_role=source_role,
            feed_id=feed_id,
            frame_seq=int(frame_seq),
            crop=np.ascontiguousarray(crop.copy()),
            raw=np.ascontiguousarray(raw.copy()),
            bounds=bounds,
            crop_mode=crop_mode,
            signal_stats=dict(signal_stats),
            trigger_reason=trigger_reason,
            trigger_metadata=dict(trigger_metadata),
            model=(config.openrouter_model_by_role or {}).get(source_role),
            enqueued_at=time.time(),
        )

    def _process_queued_sample(self, sample: _QueuedTeacherSample) -> bool:
        source_role = sample.source_role
        feed_id = sample.feed_id
        crop = sample.crop
        raw = sample.raw
        bounds = sample.bounds
        model = sample.model
        with self._lock:
            self._teacher_call_count += 1
            self._bump_role(self._teacher_call_count_by_role, source_role)

        teacher = self._teacher_annotator_provider()
        annotation = teacher.annotate(
            crop,
            source_role=source_role,
            feed_id=feed_id,
            model=model,
        )
        detections = list(getattr(annotation, "detections", ()) or ())
        if not detections:
            with self._lock:
                self._skipped_teacher_no_detections += 1
                self._bump_role(
                    self._skipped_teacher_no_detections_by_role,
                    source_role,
                )
            return False

        detections.sort(
            key=lambda det: float(getattr(det, "confidence", 0.0)),
            reverse=True,
        )
        best = detections[0]
        local_bboxes = [
            list(det.bbox_xyxy)
            for det in detections
            if _bbox_tuple(det.bbox_xyxy) is not None
        ]
        local_best_bbox = list(best.bbox_xyxy)
        if not local_bboxes:
            with self._lock:
                self._skipped_no_detections += 1
                self._bump_role(self._skipped_no_detections_by_role, source_role)
            return False

        candidate_bboxes_full_frame = [
            _full_frame_bbox(tuple(det.bbox_xyxy), bounds)
            for det in detections
            if _bbox_tuple(det.bbox_xyxy) is not None
        ]
        detection_details = [
            {
                "bbox": list(det.bbox_xyxy),
                "bbox_full_frame": _full_frame_bbox(tuple(det.bbox_xyxy), bounds),
                "confidence": float(det.confidence),
                "kind": det.kind,
                "description": det.description,
            }
            for det in detections
            if _bbox_tuple(det.bbox_xyxy) is not None
        ]
        score = float(best.confidence)
        teacher_model = str(getattr(annotation, "model", "") or model or "")
        raw_payload = getattr(annotation, "raw_payload", None)
        extra_metadata = {
            "teacher_capture": True,
            "teacher_capture_trigger": sample.trigger_reason,
            "teacher_capture_source": "gemini_sam_teacher",
            "teacher_capture_feed_id": feed_id,
            "teacher_capture_frame_seq": int(sample.frame_seq),
            "teacher_capture_crop_mode": sample.crop_mode,
            "teacher_capture_crop_signal": sample.signal_stats,
            "teacher_capture_label_source": _GEMINI_SAM_ALGORITHM,
            "teacher_capture_gemini_model": teacher_model or None,
            "teacher_capture_crop_bbox_full_frame": list(bounds),
            "teacher_capture_primary_bbox_full_frame": _full_frame_bbox(
                tuple(best.bbox_xyxy),
                bounds,
            ),
            "teacher_capture_candidate_bboxes_full_frame": candidate_bboxes_full_frame,
            "teacher_capture_gemini_detections": detection_details,
            "teacher_capture_gemini_raw_payload": (
                raw_payload if isinstance(raw_payload, dict) else None
            ),
        }
        if sample.trigger_metadata:
            extra_metadata["teacher_capture_trigger_metadata"] = {
                key: value
                for key, value in sample.trigger_metadata.items()
                if key != "not_before_wall_ts"
            }
        manager = self._training_manager_provider()
        manager.saveAuxiliaryDetectionCapture(
            source="live_aux_teacher_capture",
            source_role=source_role,
            detection_scope=_SOURCE_ROLE_TO_SCOPE[source_role],
            capture_reason=sample.trigger_reason,
            detection_algorithm=_GEMINI_SAM_ALGORITHM,
            detection_openrouter_model=teacher_model or None,
            detection_found=True,
            detection_bbox=local_best_bbox,
            detection_candidate_bboxes=local_bboxes,
            detection_bbox_count=len(local_bboxes),
            detection_score=score,
            detection_message=(
                f"{len(local_bboxes)} Gemini-SAM teacher detection(s) captured from {feed_id}."
            ),
            input_image=crop,
            source_frame=raw,
            extra_metadata=extra_metadata,
        )
        with self._lock:
            self._captured_count += 1
            self._bump_role(self._captured_count_by_role, source_role)
            self._last_capture_wall_ts = time.time()
            self._last_error = None
            self._last_captured_frame_by_role[source_role] = int(sample.frame_seq)
            self._gemini_completed_count += 1
            self._bump_role(self._gemini_completed_count_by_role, source_role)
        return True

    def _record_error(self, exc: BaseException) -> None:
        with self._lock:
            self._error_count += 1
            self._last_error = f"{type(exc).__name__}: {exc}"

    def _log_exception(self, message: str) -> None:
        """Log an exception even when the injected runtime logger is minimal."""

        exc_text = traceback.format_exc()
        exception = getattr(self._log, "exception", None)
        if callable(exception):
            try:
                exception(message)
                return
            except Exception:
                pass

        error = getattr(self._log, "error", None)
        if callable(error):
            try:
                error("%s\n%s", message, exc_text)
                return
            except Exception:
                try:
                    error(f"{message}\n{exc_text}")
                    return
                except Exception:
                    pass

        LOG.error("%s\n%s", message, exc_text)


__all__ = [
    "AuxiliaryTeacherSampleCollector",
    "DEFAULT_SAMPLE_COLLECTION_INTERVAL_S",
    "DEFAULT_SAMPLE_COLLECTION_MIN_CAPTURE_INTERVAL_S",
    "DEFAULT_SAMPLE_COLLECTION_WORKER_COUNT",
    "GeminiSamTeacherAnnotator",
    "TeacherAnnotation",
    "TeacherDetection",
    "TeacherSampleCollectionConfig",
]
