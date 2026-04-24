from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


SAMPLE_PAYLOAD_SCHEMA_VERSION = "hive_sample_v1"
PRIMARY_IMAGE_ASSET_ID = "img_primary"
FULL_FRAME_ASSET_ID = "img_full_frame"
OVERLAY_ASSET_ID = "img_overlay"


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _normalize_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]
    except Exception:
        return None


def _normalize_bboxes(value: Any) -> list[list[int]]:
    if not isinstance(value, (list, tuple)):
        return []

    if len(value) >= 4 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:4]):
        bbox = _normalize_bbox(value)
        return [bbox] if bbox is not None else []

    return [
        bbox
        for bbox in (_normalize_bbox(item) for item in value)
        if bbox is not None
    ]


def _format_timestamp(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    return None


def _preferred_view(metadata: dict[str, Any]) -> str | None:
    for key in ("preferred_camera", "camera", "source_role"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _capture_scope(metadata: dict[str, Any]) -> str | None:
    scope = metadata.get("detection_scope")
    if isinstance(scope, str) and scope:
        return scope
    source_role = metadata.get("source_role")
    if source_role == "classification_chamber":
        return "classification"
    if source_role in {"c_channel_2", "c_channel_3"}:
        return "feeder"
    if source_role == "classification_channel":
        return "classification_channel"
    if source_role == "carousel":
        return "carousel"
    return None


def _capture_mode(metadata: dict[str, Any]) -> str:
    capture_reason = metadata.get("capture_reason")
    source = metadata.get("source")
    if capture_reason == "manual_capture":
        return "manual"
    if capture_reason == "settings_detection_test":
        return "settings_test"
    if metadata.get("archive_mode") == "backfill":
        return "backfill"
    if metadata.get("teacher_capture") or source == "live_aux_teacher_capture":
        return "background_teacher"
    return "runtime"


def _build_assets(
    *,
    preferred_view: str | None,
    include_primary_asset: bool,
    include_full_frame: bool,
    include_overlay: bool,
) -> dict[str, Any]:
    assets: dict[str, Any] = {}
    if include_primary_asset:
        assets[PRIMARY_IMAGE_ASSET_ID] = {
            "kind": "crop",
            "view": preferred_view,
            "role": "primary",
            "mime_type": "image/jpeg",
        }
    if include_full_frame:
        assets[FULL_FRAME_ASSET_ID] = {
            "kind": "full_frame",
            "view": preferred_view,
            "role": "context",
            "mime_type": "image/jpeg",
        }
    if include_overlay:
        assets[OVERLAY_ASSET_ID] = {
            "kind": "overlay",
            "view": preferred_view,
            "role": "analysis_artifact",
            "mime_type": "image/jpeg",
            "derived_from_asset_id": PRIMARY_IMAGE_ASSET_ID,
        }
    return assets


def _build_detection_analysis(metadata: dict[str, Any], *, include_overlay: bool) -> dict[str, Any] | None:
    provider = metadata.get("detection_algorithm")
    candidate_boxes = _normalize_bboxes(metadata.get("detection_candidate_bboxes"))
    boxes = candidate_boxes or _normalize_bboxes(metadata.get("detection_bboxes"))
    primary_box = _normalize_bbox(metadata.get("detection_bbox"))
    if primary_box is not None and primary_box not in boxes:
        boxes = [primary_box, *boxes]

    detection_score = _safe_float(metadata.get("detection_score"))
    found_value = metadata.get("detection_found")
    found = bool(found_value) if isinstance(found_value, bool) else bool(boxes)

    if not provider and not boxes and detection_score is None and not isinstance(metadata.get("detection_message"), str):
        return None

    outputs: dict[str, Any] = {
        "found": found,
        "boxes": [
            {
                "box_px": box,
                **({"score": detection_score} if idx == 0 and detection_score is not None else {}),
            }
            for idx, box in enumerate(boxes)
        ],
    }
    if boxes:
        outputs["primary_box_index"] = 0
    message = metadata.get("detection_message")
    if isinstance(message, str) and message:
        outputs["message"] = message

    analysis_metadata: dict[str, Any] = {}
    for key in ("top_detection_bbox_count", "bottom_detection_bbox_count"):
        value = metadata.get(key)
        if isinstance(value, int):
            analysis_metadata[key] = value

    return {
        "analysis_id": "det_primary",
        "kind": "detection",
        "stage": "primary_detection",
        "provider": provider,
        "model": metadata.get("detection_openrouter_model") if isinstance(metadata.get("detection_openrouter_model"), str) else None,
        "status": "completed",
        "input_asset_ids": [PRIMARY_IMAGE_ASSET_ID],
        "artifact_asset_ids": [OVERLAY_ASSET_ID] if include_overlay else [],
        "outputs": outputs,
        "metadata": analysis_metadata,
    }


def _build_classification_analysis(metadata: dict[str, Any]) -> dict[str, Any] | None:
    classification = metadata.get("classification_result")
    if not isinstance(classification, dict):
        return None

    candidate: dict[str, Any] = {}
    for source_key, target_key in (
        ("part_id", "part_id"),
        ("item_name", "item_name"),
        ("item_category", "item_category"),
        ("color_id", "color_id"),
        ("color_name", "color_name"),
        ("confidence", "confidence"),
        ("preview_url", "preview_url"),
    ):
        value = classification.get(source_key)
        if value is not None:
            candidate[target_key] = value

    outputs: dict[str, Any] = {
        "best_candidate_index": 0 if candidate else None,
        "candidates": [candidate] if candidate else [],
        "source_view": classification.get("source_view"),
    }
    metadata_block: dict[str, Any] = {}
    for key in ("top_items_count", "bottom_items_count", "top_colors_count", "bottom_colors_count"):
        value = classification.get(key)
        if isinstance(value, int):
            metadata_block[key] = value

    return {
        "analysis_id": "cls_primary",
        "kind": "classification",
        "stage": "part_classification",
        "provider": classification.get("provider"),
        "model": classification.get("model"),
        "status": classification.get("status") or "completed",
        "input_asset_ids": [PRIMARY_IMAGE_ASSET_ID],
        "artifact_asset_ids": [],
        "outputs": outputs,
        "error": classification.get("error"),
        "metadata": metadata_block,
    }


def build_sample_payload(
    *,
    session_id: str,
    sample_id: str,
    session_name: str | None,
    metadata: dict[str, Any],
    include_primary_asset: bool = True,
    include_full_frame: bool = False,
    include_overlay: bool = False,
) -> dict[str, Any]:
    preferred_view = _preferred_view(metadata)
    payload: dict[str, Any] = {
        "schema_version": SAMPLE_PAYLOAD_SCHEMA_VERSION,
        "sample": {
            "source_session_id": session_id,
            "local_sample_id": sample_id,
            "source_role": metadata.get("source_role"),
            "capture_reason": metadata.get("capture_reason") or metadata.get("source"),
            "capture_scope": _capture_scope(metadata),
            "capture_mode": _capture_mode(metadata),
            "captured_at": _format_timestamp(metadata.get("captured_at")),
            "machine_id": metadata.get("machine_id"),
            "run_id": metadata.get("run_id"),
            "piece_uuid": metadata.get("piece_uuid"),
            "preferred_view": preferred_view,
        },
        "assets": _build_assets(
            preferred_view=preferred_view,
            include_primary_asset=include_primary_asset,
            include_full_frame=include_full_frame,
            include_overlay=include_overlay,
        ),
        "analyses": [],
        "annotations": {},
        "provenance": {
            "session_name": session_name,
            "processor": metadata.get("processor"),
            "archive_mode": metadata.get("archive_mode"),
            "source": metadata.get("source"),
        },
    }

    detection_analysis = _build_detection_analysis(metadata, include_overlay=include_overlay)
    if detection_analysis is not None:
        payload["analyses"].append(detection_analysis)

    classification_analysis = _build_classification_analysis(metadata)
    if classification_analysis is not None:
        payload["analyses"].append(classification_analysis)

    manual_annotations = metadata.get("manual_annotations")
    if isinstance(manual_annotations, dict):
        payload["annotations"]["manual_regions"] = copy.deepcopy(manual_annotations)

    manual_classification = metadata.get("manual_classification")
    if isinstance(manual_classification, dict):
        payload["annotations"]["manual_classification"] = copy.deepcopy(manual_classification)

    trigger_metadata = {
        key: copy.deepcopy(value)
        for key, value in metadata.items()
        if isinstance(key, str) and key.startswith("trigger_") and value is not None and key != "trigger_algorithm"
    }
    if metadata.get("trigger_algorithm") or trigger_metadata:
        payload["provenance"]["trigger"] = {
            "algorithm": metadata.get("trigger_algorithm"),
            "metadata": trigger_metadata,
        }

    teacher_capture_metadata = {
        key: copy.deepcopy(value)
        for key, value in metadata.items()
        if isinstance(key, str) and key.startswith("teacher_capture_") and value is not None
    }
    if teacher_capture_metadata or metadata.get("teacher_capture") is True:
        payload["provenance"]["teacher_capture"] = {
            "enabled": bool(metadata.get("teacher_capture")),
            **teacher_capture_metadata,
        }

    consumed_keys = {
        "sample_payload",
        "source_role",
        "capture_reason",
        "captured_at",
        "machine_id",
        "run_id",
        "piece_uuid",
        "preferred_camera",
        "camera",
        "source",
        "detection_scope",
        "detection_algorithm",
        "detection_openrouter_model",
        "detection_found",
        "detection_bbox",
        "detection_bboxes",
        "detection_candidate_bboxes",
        "detection_bbox_count",
        "detection_score",
        "detection_message",
        "top_detection_bbox_count",
        "bottom_detection_bbox_count",
        "classification_result",
        "manual_annotations",
        "manual_classification",
        "teacher_capture",
        "processor",
        "archive_mode",
        "session_name",
        "sample_id",
        "input_image",
        "top_zone_path",
        "bottom_zone_path",
        "top_frame_path",
        "bottom_frame_path",
    }
    extra_metadata = {
        key: copy.deepcopy(value)
        for key, value in metadata.items()
        if key not in consumed_keys
        and not (isinstance(key, str) and key.startswith("trigger_"))
        and not (isinstance(key, str) and key.startswith("teacher_capture_"))
        and value is not None
    }
    if extra_metadata:
        payload["provenance"]["metadata"] = extra_metadata

    return payload
