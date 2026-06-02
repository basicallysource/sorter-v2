from __future__ import annotations

import os
import time
from typing import Any

import numpy as np

from global_config import GlobalConfig

# Source-agnostic bridge: hand a raw camera frame to the EXISTING classification
# pipeline (save -> archive -> enqueue -> Hive upload) used by the legacy vision
# system's teacher captures, without going through VisionManager. Any capture
# source (the standalone collector, a future loop, etc.) calls ingestSampleFrame
# and the same downstream machinery handles it.

_FEEDER_ROLES = {"c_channel_2", "c_channel_3"}

# Hive only runs its teacher pass on samples whose source_role maps to a teacher
# zone (mirror of hive teacher_detector.SOURCE_ROLE_TO_ZONE). A frame from a
# camera with no teacher zone (e.g. the wide "feeder" overview cam) can never be
# promoted past "raw", so we don't ship it — matching the legacy teacher-capture
# flow, which only captured these roles.
_TEACHER_ZONE_ROLES = {
    "classification_chamber",
    "carousel",
    "classification_channel",
    "c_channel",
    "c_channel_1",
    "c_channel_2",
    "c_channel_3",
    "c_channel_full",
}

# scope -> Gemini prompt zone (see vision/gemini_sam_detector.ZONE_PROMPTS).
# Unknown zones fall back to classification_chamber inside the detector.
_ZONE_FOR_SCOPE = {
    "classification": "classification_channel",
    "carousel": "carousel",
    "feeder": "classification_chamber",
}

# One detector per scope, reused across frames (detect(force=True) is stateless
# per call, so sharing is safe and avoids re-init churn).
_detectors: dict[str, Any] = {}


def scopeForRole(role: str) -> str:
    if role in _FEEDER_ROLES:
        return "feeder"
    if role == "carousel":
        return "carousel"
    return "classification"


def _openRouterModelForScope(scope: str) -> str:
    from blob_manager import (
        getCarouselDetectionConfig,
        getClassificationDetectionConfig,
        getFeederDetectionConfig,
    )
    from vision.gemini_sam_detector import DEFAULT_OPENROUTER_MODEL, normalize_openrouter_model

    try:
        if scope == "feeder":
            cfg = getFeederDetectionConfig()
        elif scope == "carousel":
            cfg = getCarouselDetectionConfig()
        else:
            cfg = getClassificationDetectionConfig()
        model = cfg.get("openrouter_model") if isinstance(cfg, dict) else None
        return normalize_openrouter_model(model)
    except Exception:
        return DEFAULT_OPENROUTER_MODEL


def _annotate(gc: GlobalConfig, scope: str, frame_bgr: np.ndarray) -> tuple[Any | None, str | None]:
    # Best-effort: a missing key or any failure returns (None, model) so the
    # frame still uploads as a raw sample rather than being lost.
    if not os.getenv("OPENROUTER_API_KEY"):
        return None, None
    model = _openRouterModelForScope(scope)
    try:
        from vision.gemini_sam_detector import GeminiSamDetector

        detector = _detectors.get(scope)
        if detector is None:
            detector = GeminiSamDetector(model, zone=_ZONE_FOR_SCOPE.get(scope, "classification_chamber"))
            _detectors[scope] = detector
        else:
            detector.setOpenRouterModel(model)
        return detector.detect(frame_bgr, force=True), model
    except Exception as exc:
        gc.logger.warning("sample ingest annotation failed (%s): %s" % (scope, exc))
        return None, model


def ingestSampleFrame(
    gc: GlobalConfig,
    role: str,
    frame_bgr: np.ndarray,
    *,
    annotate: bool,
    source: str = "standalone_sample_collector",
    capture_reason: str = "standalone_sample_collection",
) -> dict[str, Any] | None:
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return None
    if role not in _TEACHER_ZONE_ROLES:
        return None

    scope = scopeForRole(role)
    detection = None
    model: str | None = None
    if annotate:
        detection, model = _annotate(gc, scope, frame_bgr)

    found = bool(detection is not None and getattr(detection, "bbox", None) is not None)
    if detection is not None:
        algorithm = "gemini_sam"
        message = (
            "Standalone capture: Gemini found candidate pieces."
            if found
            else "Standalone capture: Gemini found no piece."
        )
        bbox = list(detection.bbox) if found else None
        candidate_bboxes = [list(b) for b in detection.bboxes]
        bbox_count = len(detection.bboxes)
        score = float(detection.score) if getattr(detection, "score", None) is not None else None
    else:
        algorithm = "raw_capture"
        message = "Standalone raw capture (no on-device annotation)."
        bbox = None
        candidate_bboxes = []
        bbox_count = 0
        score = None

    from server.classification_training import getClassificationTrainingManager

    return getClassificationTrainingManager().saveAuxiliaryDetectionCapture(
        source=source,
        source_role=role,
        detection_scope=scope,
        capture_reason=capture_reason,
        detection_algorithm=algorithm,
        detection_openrouter_model=model if algorithm == "gemini_sam" else None,
        detection_found=found,
        detection_bbox=bbox,
        detection_candidate_bboxes=candidate_bboxes,
        detection_bbox_count=bbox_count,
        detection_score=score,
        detection_message=message,
        input_image=frame_bgr,
        source_frame=frame_bgr,
        extra_metadata={
            "standalone_capture": True,
            "capture_source_role": role,
            "ingested_at": time.time(),
        },
    )
