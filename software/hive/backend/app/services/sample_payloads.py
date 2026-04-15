from __future__ import annotations

from copy import deepcopy
from typing import Any


SAMPLE_PAYLOAD_SCHEMA_VERSION = "hive_sample_v1"
PRIMARY_IMAGE_ASSET_ID = "img_primary"
FULL_FRAME_ASSET_ID = "img_full_frame"
OVERLAY_ASSET_ID = "img_overlay"


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


def _deep_merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def normalize_sample_payload(
    payload: Any,
    *,
    source_session_id: str | None = None,
    local_sample_id: str | None = None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "schema_version": SAMPLE_PAYLOAD_SCHEMA_VERSION,
        "sample": {},
        "assets": {},
        "analyses": [],
        "annotations": {},
        "provenance": {},
    }

    if isinstance(payload, dict):
        normalized["schema_version"] = (
            payload.get("schema_version")
            if isinstance(payload.get("schema_version"), str) and payload.get("schema_version")
            else SAMPLE_PAYLOAD_SCHEMA_VERSION
        )
        for section in ("sample", "assets", "annotations", "provenance"):
            if isinstance(payload.get(section), dict):
                normalized[section] = deepcopy(payload[section])
        if isinstance(payload.get("analyses"), list):
            normalized["analyses"] = [deepcopy(item) for item in payload["analyses"] if isinstance(item, dict)]

    sample = normalized["sample"]
    if source_session_id and not isinstance(sample.get("source_session_id"), str):
        sample["source_session_id"] = source_session_id
    if local_sample_id and not isinstance(sample.get("local_sample_id"), str):
        sample["local_sample_id"] = local_sample_id

    return normalized


def build_legacy_sample_payload(
    *,
    source_session_id: str,
    local_sample_id: str,
    source_role: str | None = None,
    capture_reason: str | None = None,
    captured_at: str | None = None,
    detection_algorithm: str | None = None,
    detection_bboxes: Any = None,
    detection_count: int | None = None,
    detection_score: float | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = deepcopy(extra_metadata) if isinstance(extra_metadata, dict) else {}

    payload = normalize_sample_payload(
        None,
        source_session_id=source_session_id,
        local_sample_id=local_sample_id,
    )
    sample = payload["sample"]
    if source_role:
        sample["source_role"] = source_role
    if capture_reason:
        sample["capture_reason"] = capture_reason
    if captured_at:
        sample["captured_at"] = captured_at
    if isinstance(extra.get("detection_scope"), str) and extra.get("detection_scope"):
        sample["capture_scope"] = extra["detection_scope"]
    if isinstance(extra.get("machine_id"), str) and extra.get("machine_id"):
        sample["machine_id"] = extra["machine_id"]
    if isinstance(extra.get("run_id"), str) and extra.get("run_id"):
        sample["run_id"] = extra["run_id"]
    if isinstance(extra.get("piece_uuid"), str) and extra.get("piece_uuid"):
        sample["piece_uuid"] = extra["piece_uuid"]
    preferred_view = extra.get("preferred_view") or extra.get("preferred_camera") or extra.get("camera")
    if isinstance(preferred_view, str) and preferred_view:
        sample["preferred_view"] = preferred_view

    boxes = _normalize_bboxes(detection_bboxes)
    candidate_boxes = _normalize_bboxes(extra.get("detection_candidate_bboxes"))
    if candidate_boxes:
        boxes = candidate_boxes
    primary_box = _normalize_bbox(extra.get("detection_bbox"))
    if primary_box is not None and primary_box not in boxes:
        boxes = [primary_box, *boxes]

    found_value = extra.get("detection_found")
    found = bool(found_value) if isinstance(found_value, bool) else bool(boxes)
    if detection_algorithm or boxes or detection_count is not None or detection_score is not None or "detection_message" in extra:
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
        message = extra.get("detection_message")
        if isinstance(message, str) and message:
            outputs["message"] = message

        analysis_metadata: dict[str, Any] = {}
        for key in ("top_detection_bbox_count", "bottom_detection_bbox_count"):
            value = extra.get(key)
            if isinstance(value, int):
                analysis_metadata[key] = value

        payload["analyses"].append(
            {
                "analysis_id": "det_primary",
                "kind": "detection",
                "stage": "primary_detection",
                "provider": detection_algorithm,
                "model": extra.get("detection_openrouter_model") if isinstance(extra.get("detection_openrouter_model"), str) else None,
                "status": "completed",
                "input_asset_ids": [PRIMARY_IMAGE_ASSET_ID],
                "artifact_asset_ids": [OVERLAY_ASSET_ID] if extra.get("distill_result") else [],
                "outputs": outputs,
                "metadata": analysis_metadata,
            }
        )

    classification = extra.get("classification_result")
    if isinstance(classification, dict):
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
        payload["analyses"].append(
            {
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
                "metadata": {},
            }
        )

    manual_annotations = extra.get("manual_annotations")
    if isinstance(manual_annotations, dict):
        payload["annotations"]["manual_regions"] = deepcopy(manual_annotations)

    manual_classification = extra.get("manual_classification")
    if isinstance(manual_classification, dict):
        payload["annotations"]["manual_classification"] = deepcopy(manual_classification)

    if extra:
        payload["provenance"]["legacy_extra_metadata"] = extra

    return payload


def merge_sample_payload(existing: Any, patch: Any) -> dict[str, Any]:
    merged = normalize_sample_payload(existing)
    patch_payload = normalize_sample_payload(
        patch,
        source_session_id=merged["sample"].get("source_session_id"),
        local_sample_id=merged["sample"].get("local_sample_id"),
    )

    for section in ("sample", "annotations", "provenance"):
        merged[section] = _deep_merge_dicts(merged.get(section, {}), patch_payload.get(section, {}))

    for asset_id, asset_data in patch_payload.get("assets", {}).items():
        if not isinstance(asset_data, dict):
            continue
        existing_asset = merged["assets"].get(asset_id)
        if isinstance(existing_asset, dict):
            merged["assets"][asset_id] = _deep_merge_dicts(existing_asset, asset_data)
        else:
            merged["assets"][asset_id] = deepcopy(asset_data)

    existing_analyses: list[dict[str, Any]] = [
        deepcopy(item)
        for item in merged.get("analyses", [])
        if isinstance(item, dict)
    ]
    index_by_id = {
        item.get("analysis_id"): idx
        for idx, item in enumerate(existing_analyses)
        if isinstance(item.get("analysis_id"), str) and item.get("analysis_id")
    }
    for analysis in patch_payload.get("analyses", []):
        if not isinstance(analysis, dict):
            continue
        analysis_id = analysis.get("analysis_id")
        if isinstance(analysis_id, str) and analysis_id in index_by_id:
            existing_analyses[index_by_id[analysis_id]] = deepcopy(analysis)
        else:
            existing_analyses.append(deepcopy(analysis))
            if isinstance(analysis_id, str) and analysis_id:
                index_by_id[analysis_id] = len(existing_analyses) - 1
    merged["analyses"] = existing_analyses
    return merged


def upsert_asset(
    payload: Any,
    *,
    asset_id: str,
    stored_path: str,
    kind: str,
    role: str,
    mime_type: str | None = None,
    view: str | None = None,
    derived_from_asset_id: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_sample_payload(payload)
    asset = deepcopy(normalized["assets"].get(asset_id)) if isinstance(normalized["assets"].get(asset_id), dict) else {}
    asset["kind"] = kind
    asset["role"] = role
    asset["storage_path"] = stored_path
    if mime_type:
        asset["mime_type"] = mime_type
    if view:
        asset["view"] = view
    if derived_from_asset_id:
        asset["derived_from_asset_id"] = derived_from_asset_id
    normalized["assets"][asset_id] = asset
    return normalized


def derive_denormalized_fields(
    payload: Any,
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = fallback or {}
    normalized = normalize_sample_payload(payload)
    sample = normalized.get("sample", {})

    detection_analysis = next(
        (
            item
            for item in normalized.get("analyses", [])
            if isinstance(item, dict) and item.get("kind") == "detection"
        ),
        None,
    )
    outputs = detection_analysis.get("outputs", {}) if isinstance(detection_analysis, dict) else {}
    raw_boxes = outputs.get("boxes")
    boxes = [
        box.get("box_px")
        for box in raw_boxes
        if isinstance(box, dict) and _normalize_bbox(box.get("box_px")) is not None
    ] if isinstance(raw_boxes, list) else []
    boxes = [_normalize_bbox(box) for box in boxes]
    boxes = [box for box in boxes if box is not None]

    primary_index = outputs.get("primary_box_index") if isinstance(outputs, dict) else None
    primary_score = None
    if (
        isinstance(primary_index, int)
        and isinstance(raw_boxes, list)
        and 0 <= primary_index < len(raw_boxes)
        and isinstance(raw_boxes[primary_index], dict)
    ):
        score = raw_boxes[primary_index].get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            primary_score = float(score)
    if primary_score is None and boxes and isinstance(raw_boxes, list) and raw_boxes and isinstance(raw_boxes[0], dict):
        score = raw_boxes[0].get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            primary_score = float(score)

    return {
        "source_role": sample.get("source_role") if isinstance(sample.get("source_role"), str) else fallback.get("source_role"),
        "capture_reason": sample.get("capture_reason") if isinstance(sample.get("capture_reason"), str) else fallback.get("capture_reason"),
        "captured_at": sample.get("captured_at") if isinstance(sample.get("captured_at"), str) else fallback.get("captured_at"),
        "detection_algorithm": (
            detection_analysis.get("provider")
            if isinstance(detection_analysis, dict) and isinstance(detection_analysis.get("provider"), str)
            else fallback.get("detection_algorithm")
        ),
        "detection_bboxes": boxes or fallback.get("detection_bboxes"),
        "detection_count": len(boxes) if boxes else fallback.get("detection_count"),
        "detection_score": primary_score if primary_score is not None else fallback.get("detection_score"),
    }


def set_manual_annotations(payload: Any, annotations_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_sample_payload(payload)
    normalized["annotations"]["manual_regions"] = deepcopy(annotations_payload)
    return normalized


def set_manual_classification(payload: Any, classification_payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_sample_payload(payload)
    if classification_payload:
        normalized["annotations"]["manual_classification"] = deepcopy(classification_payload)
    else:
        normalized["annotations"].pop("manual_classification", None)
    return normalized


def is_classification_payload(payload: Any, *, fallback_source_role: str | None = None, fallback_capture_reason: str | None = None) -> bool:
    normalized = normalize_sample_payload(payload)
    sample = normalized.get("sample", {})
    capture_scope = sample.get("capture_scope")
    source_role = sample.get("source_role") if isinstance(sample.get("source_role"), str) else fallback_source_role
    capture_reason = sample.get("capture_reason") if isinstance(sample.get("capture_reason"), str) else fallback_capture_reason

    return (
        capture_scope == "classification"
        or source_role == "classification_chamber"
        or capture_reason == "live_classification"
    )
