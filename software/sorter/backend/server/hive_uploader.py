"""Background uploader that forwards archived samples to Hive."""

from __future__ import annotations

from collections import deque
import json
import logging
import queue
import random
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests

from local_state import get_hive_config
from server.sample_payloads import build_sample_payload

log = logging.getLogger(__name__)

UPLOAD_MAX_RETRIES = 3
UPLOAD_RETRY_BASE_S = 2.0
UPLOAD_THROTTLE_S = 0.8
HEARTBEAT_INTERVAL_S = 30.0
SERVER_DOWN_BACKOFF_S = 10.0
SERVER_DOWN_MAX_BACKOFF_S = 120.0
RECENT_UPLOAD_EVENT_LIMIT = 120
LOW_SIGNAL_MEAN_GRAY = 3.0
LOW_SIGNAL_NONBLACK_RATIO = 0.01
PRIMARY_IMAGE_MIN_MEAN_GRAY = 8.0
PRIMARY_IMAGE_MIN_NONBLACK_RATIO = 0.02
PRIMARY_IMAGE_MIN_P95_GRAY = 24.0
PRIMARY_IMAGE_NONBLACK_THRESHOLD = 16
UPLOAD_MARKER_KEY = "hive_uploads"
STRICT_TEACHER_SAMPLE_ROLES = {
    "classification_channel",
    "c_channel_2",
    "c_channel_3",
}
BLOCKED_TEACHER_STATES = {
    "needs_gemini",
    "no_teacher_detection",
    "bad_teacher_sample",
}
SUPPORTED_SAMPLE_TYPE_FILTERS = {
    "all",
    "teacher_detection",
    "condition",
    "classification",
    "other",
}
SAMPLE_TYPE_LABELS = {
    "teacher_detection": "Gemini boxes",
    "condition": "Condition",
    "classification": "Classification",
    "other": "Other",
}


def teacher_state_from_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    """Classify whether an archived sample is ready for training upload."""

    is_teacher_capture = _is_teacher_capture_metadata(metadata)
    if is_teacher_capture:
        quality_issue = _teacher_sample_quality_issue(metadata)
        if quality_issue is not None:
            return quality_issue

    algorithm = metadata.get("detection_algorithm")
    if algorithm == "gemini_sam":
        bbox_count = _safe_int(metadata.get("detection_bbox_count"))
        if metadata.get("detection_found") is False or bbox_count == 0:
            if metadata.get("teacher_capture_negative") is True:
                return {
                    "state": "teacher_ready",
                    "label": "Gemini negative",
                    "reason": "Gemini-SAM confirmed an empty detector crop with no loose items.",
                }
            return {
                "state": "no_teacher_detection",
                "label": "No Gemini box",
                "reason": "Gemini-SAM returned no usable object box for this sample.",
            }
        return {
            "state": "teacher_ready",
            "label": "Gemini ready",
            "reason": "Sample has Gemini-SAM teacher labels.",
        }

    if is_teacher_capture:
        return {
            "state": "needs_gemini",
            "label": "Needs Gemini",
            "reason": "Background teacher sample was captured before Gemini-SAM labels were applied.",
        }

    return {
        "state": "not_teacher_sample",
        "label": "Other sample",
        "reason": "Sample is not part of the background Gemini teacher pipeline.",
    }


def _is_teacher_capture_metadata(metadata: dict[str, Any]) -> bool:
    return (
        metadata.get("teacher_capture") is True
        or metadata.get("source") == "live_aux_teacher_capture"
        or metadata.get("capture_reason") == "rt_periodic_interval"
        or isinstance(metadata.get("teacher_capture_source"), str)
    )


def _payload_capture_scope(metadata: dict[str, Any]) -> str | None:
    sample_payload = metadata.get("sample_payload")
    if not isinstance(sample_payload, dict):
        return None
    sample = sample_payload.get("sample")
    if not isinstance(sample, dict):
        return None
    scope = sample.get("capture_scope")
    return scope if isinstance(scope, str) and scope else None


def normalize_sample_type_filter(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip().lower().replace("-", "_")
        aliases = {
            "teacher": "teacher_detection",
            "gemini": "teacher_detection",
            "gemini_boxes": "teacher_detection",
            "condition_teacher": "condition",
            "piece_condition": "condition",
            "classification_channel": "classification",
            "class": "classification",
        }
        candidate = aliases.get(candidate, candidate)
        if candidate in SUPPORTED_SAMPLE_TYPE_FILTERS:
            return candidate
    return "all"


def sample_type_from_metadata(metadata: dict[str, Any]) -> str:
    """Return the first-class dataset type represented by archived metadata."""

    if not isinstance(metadata, dict):
        return "other"

    payload_scope = _payload_capture_scope(metadata)
    detection_scope = metadata.get("detection_scope")
    capture_reason = metadata.get("capture_reason")
    algorithm = metadata.get("detection_algorithm")
    source_role = metadata.get("source_role")

    if (
        metadata.get("condition_sample") is True
        or isinstance(metadata.get("condition_assessment"), dict)
        or payload_scope == "condition"
        or detection_scope == "condition"
        or capture_reason == "piece_condition_teacher"
    ):
        return "condition"

    if _is_teacher_capture_metadata(metadata) or algorithm == "gemini_sam":
        return "teacher_detection"

    if (
        payload_scope in {"classification", "classification_channel"}
        or detection_scope == "classification"
        or capture_reason == "live_classification"
        or source_role in {"classification_channel", "classification_chamber"}
    ):
        return "classification"

    return "other"


def sample_type_label(sample_type: Any) -> str:
    normalized = normalize_sample_type_filter(sample_type)
    if normalized == "all":
        return "All"
    return SAMPLE_TYPE_LABELS.get(normalized, "Other")


def sample_type_matches(metadata: dict[str, Any], sample_type: Any) -> bool:
    normalized = normalize_sample_type_filter(sample_type)
    return normalized == "all" or sample_type_from_metadata(metadata) == normalized


def _teacher_sample_quality_issue(metadata: dict[str, Any]) -> dict[str, str] | None:
    """Reject archived teacher samples that are not provably clean crops."""

    source_role = metadata.get("source_role")
    crop_mode = metadata.get("teacher_capture_crop_mode")
    if source_role in STRICT_TEACHER_SAMPLE_ROLES and crop_mode != "polygon_masked_zone":
        return {
            "state": "bad_teacher_sample",
            "label": "Bad sample",
            "reason": "Teacher sample is not a strict polygon-masked crop.",
        }

    signal = metadata.get("teacher_capture_crop_signal")
    if not isinstance(signal, dict):
        return {
            "state": "bad_teacher_sample",
            "label": "Bad sample",
            "reason": "Teacher sample is missing crop quality proof.",
        }

    mean_gray = _safe_float(signal.get("mean_gray"))
    nonblack_ratio = _safe_float(signal.get("nonblack_ratio"))
    if mean_gray is None or nonblack_ratio is None:
        return {
            "state": "bad_teacher_sample",
            "label": "Bad sample",
            "reason": "Teacher sample has invalid crop quality metrics.",
        }
    if mean_gray < LOW_SIGNAL_MEAN_GRAY or nonblack_ratio < LOW_SIGNAL_NONBLACK_RATIO:
        return {
            "state": "bad_teacher_sample",
            "label": "Bad sample",
            "reason": "Teacher crop is too dark or empty for training.",
        }

    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _normalize_bbox_payload(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]
    except Exception:
        return None


def _normalize_bbox_list_payload(value: Any) -> list[list[int]] | None:
    if not isinstance(value, (list, tuple)):
        return None

    # Legacy shape: a single bbox stored directly as [x1, y1, x2, y2]
    if len(value) >= 4 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:4]):
        bbox = _normalize_bbox_payload(value)
        return [bbox] if bbox is not None else None

    normalized = [
        bbox
        for bbox in (_normalize_bbox_payload(item) for item in value)
        if bbox is not None
    ]
    return normalized or None


def _job_key(job: dict[str, Any]) -> tuple[str, str, str, str] | None:
    operation = job.get("operation") if isinstance(job.get("operation"), str) else "upload"
    target_id = job.get("target_id")
    session_id = job.get("session_id")
    sample_id = job.get("sample_id")
    if not all(isinstance(value, str) and value for value in (target_id, session_id, sample_id)):
        return None
    return (operation, target_id, session_id, sample_id)


def _uploaded_marker_for_target(metadata: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    uploads = metadata.get(UPLOAD_MARKER_KEY)
    if not isinstance(uploads, dict):
        return None
    marker = uploads.get(target_id)
    return marker if isinstance(marker, dict) else None


def _is_uploaded_to_target(metadata: dict[str, Any], target_id: str) -> bool:
    marker = _uploaded_marker_for_target(metadata, target_id)
    return bool(marker and marker.get("status") == "uploaded")


def _primary_image_quality_issue(image_path: Path) -> dict[str, Any] | None:
    """Reject empty or almost-black primary images before they reach Hive."""

    if not image_path.exists():
        return None

    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if gray is None or getattr(gray, "size", 0) <= 0:
        return {
            "reason": "Primary sample image could not be decoded.",
            "stats": None,
        }

    mean_gray = float(gray.mean())
    nonblack_ratio = float((gray > PRIMARY_IMAGE_NONBLACK_THRESHOLD).mean())
    p95_gray = float(np.percentile(gray, 95))
    stats = {
        "mean_gray": mean_gray,
        "nonblack_ratio": nonblack_ratio,
        "p95_gray": p95_gray,
    }
    if (
        mean_gray < PRIMARY_IMAGE_MIN_MEAN_GRAY
        or nonblack_ratio < PRIMARY_IMAGE_MIN_NONBLACK_RATIO
        or p95_gray < PRIMARY_IMAGE_MIN_P95_GRAY
    ):
        return {
            "reason": "Primary sample image is too dark or empty for training.",
            "stats": stats,
        }

    return None


def _resolve_archived_file_path(
    value: Any,
    *,
    training_root: Path,
    session_dir: Path,
    fallback_dirs: tuple[Path, ...] = (),
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None

    candidate = Path(value.strip())
    if candidate.exists():
        return candidate

    parts = candidate.parts
    if "classification_training" in parts:
        marker_index = parts.index("classification_training")
        remapped = training_root.joinpath(*parts[marker_index + 1 :])
        if remapped.exists():
            return remapped

    if session_dir.name in parts:
        session_index = parts.index(session_dir.name)
        remapped = session_dir.joinpath(*parts[session_index + 1 :])
        if remapped.exists():
            return remapped

    if candidate.name:
        for base_dir in fallback_dirs:
            remapped = base_dir / candidate.name
            if remapped.exists():
                return remapped

    return None


class _HiveClient:
    def __init__(self, api_url: str, api_token: str) -> None:
        self._url = api_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_token}"

    def _send_sample_request(
        self,
        *,
        method: str,
        url: str,
        source_session_id: str,
        local_sample_id: str,
        image_path: Path | None = None,
        full_frame_path: Path | None = None,
        overlay_path: Path | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        captured_at: str | None = None,
        session_name: str | None = None,
        detection_algorithm: str | None = None,
        detection_bboxes: Any = None,
        detection_count: int | None = None,
        detection_score: float | None = None,
        sample_payload: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source_session_id": source_session_id,
            "local_sample_id": local_sample_id,
        }
        for key, value in [
            ("source_role", source_role),
            ("capture_reason", capture_reason),
            ("captured_at", captured_at),
            ("session_name", session_name),
            ("detection_algorithm", detection_algorithm),
            ("detection_bboxes", detection_bboxes),
            ("detection_count", detection_count),
            ("detection_score", detection_score),
            ("sample_payload", sample_payload),
        ]:
            if value is not None:
                metadata[key] = value
        if extra_metadata:
            metadata["extra_metadata"] = extra_metadata

        handles: list[Any] = []
        try:
            files: dict[str, Any] = {}
            if image_path is not None:
                image_fh = open(image_path, "rb")
                handles.append(image_fh)
                files["image"] = (image_path.name, image_fh, "image/jpeg")
            if full_frame_path and full_frame_path.exists():
                full_frame_fh = open(full_frame_path, "rb")
                handles.append(full_frame_fh)
                files["full_frame"] = (full_frame_path.name, full_frame_fh, "image/jpeg")
            if overlay_path and overlay_path.exists():
                overlay_fh = open(overlay_path, "rb")
                handles.append(overlay_fh)
                files["overlay"] = (overlay_path.name, overlay_fh, "image/jpeg")

            request = getattr(self._session, method.lower())
            response = request(
                url,
                data={"metadata": json.dumps(metadata)},
                files=files or None,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        finally:
            for handle in handles:
                handle.close()

    def upload_sample(
        self,
        *,
        source_session_id: str,
        local_sample_id: str,
        image_path: Path,
        full_frame_path: Path | None = None,
        overlay_path: Path | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        captured_at: str | None = None,
        session_name: str | None = None,
        detection_algorithm: str | None = None,
        detection_bboxes: Any = None,
        detection_count: int | None = None,
        detection_score: float | None = None,
        sample_payload: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send_sample_request(
            method="POST",
            url=f"{self._url}/api/machine/upload",
            source_session_id=source_session_id,
            local_sample_id=local_sample_id,
            image_path=image_path,
            full_frame_path=full_frame_path,
            overlay_path=overlay_path,
            source_role=source_role,
            capture_reason=capture_reason,
            captured_at=captured_at,
            session_name=session_name,
            detection_algorithm=detection_algorithm,
            detection_bboxes=detection_bboxes,
            detection_count=detection_count,
            detection_score=detection_score,
            sample_payload=sample_payload,
            extra_metadata=extra_metadata,
        )

    def update_sample(
        self,
        *,
        source_session_id: str,
        local_sample_id: str,
        image_path: Path | None = None,
        full_frame_path: Path | None = None,
        overlay_path: Path | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        captured_at: str | None = None,
        session_name: str | None = None,
        detection_algorithm: str | None = None,
        detection_bboxes: Any = None,
        detection_count: int | None = None,
        detection_score: float | None = None,
        sample_payload: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send_sample_request(
            method="PATCH",
            url=f"{self._url}/api/machine/upload/{source_session_id}/{local_sample_id}",
            source_session_id=source_session_id,
            local_sample_id=local_sample_id,
            image_path=image_path,
            full_frame_path=full_frame_path,
            overlay_path=overlay_path,
            source_role=source_role,
            capture_reason=capture_reason,
            captured_at=captured_at,
            session_name=session_name,
            detection_algorithm=detection_algorithm,
            detection_bboxes=detection_bboxes,
            detection_count=detection_count,
            detection_score=detection_score,
            sample_payload=sample_payload,
            extra_metadata=extra_metadata,
        )

    def heartbeat(self) -> bool:
        try:
            response = self._session.post(f"{self._url}/api/machine/heartbeat", timeout=10)
            return response.status_code < 500
        except requests.RequestException:
            return False


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class HiveUploader:
    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._targets: dict[str, dict[str, Any]] = {}
        self._active_jobs: dict[str, dict[str, Any]] = {}
        self._recent_jobs: deque[dict[str, Any]] = deque(maxlen=RECENT_UPLOAD_EVENT_LIMIT)
        self._queued_job_keys: set[tuple[str, str, str, str]] = set()
        self._reload_config()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="hive-uploader")
        self._worker.start()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="hive-heartbeat",
        )
        self._heartbeat_thread.start()

    def _reload_config(self) -> None:
        config = get_hive_config()
        targets = config.get("targets") if isinstance(config, dict) else None
        previous = self._targets
        self._targets = {}

        if not isinstance(targets, list):
            return

        for raw_target in targets:
            if not isinstance(raw_target, dict):
                continue

            target_id = raw_target.get("id")
            url = raw_target.get("url")
            token = raw_target.get("api_token")
            if not isinstance(target_id, str) or not target_id:
                continue
            if not isinstance(url, str) or not url:
                continue
            if not isinstance(token, str) or not token:
                continue

            previous_state = previous.get(target_id, {})
            enabled = bool(raw_target.get("enabled", False))
            state: dict[str, Any] = {
                "id": target_id,
                "name": raw_target.get("name") if isinstance(raw_target.get("name"), str) else url,
                "url": url,
                "machine_id": raw_target.get("machine_id") if isinstance(raw_target.get("machine_id"), str) else None,
                "enabled": enabled,
                "client": None,
                "server_reachable": bool(previous_state.get("server_reachable", True)),
                "uploaded": int(previous_state.get("uploaded", 0)),
                "failed": int(previous_state.get("failed", 0)),
                "requeued": int(previous_state.get("requeued", 0)),
                "queued": int(previous_state.get("queued", 0)),
                "last_error": previous_state.get("last_error"),
                "retry_after": float(previous_state.get("retry_after", 0.0)),
                "backoff_s": float(previous_state.get("backoff_s", SERVER_DOWN_BACKOFF_S)),
            }

            if enabled:
                try:
                    state["client"] = _HiveClient(url, token)
                    state["server_reachable"] = bool(previous_state.get("server_reachable", True))
                    log.info("Hive uploader enabled: %s (%s)", state["name"], url)
                except Exception as exc:
                    state["enabled"] = False
                    state["last_error"] = str(exc)
                    log.warning("Hive uploader disabled for %s: %s", url, exc)

            self._targets[target_id] = state

    def reload(self) -> dict[str, Any]:
        with self._lock:
            self._reload_config()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "targets": [
                    {
                        "id": target["id"],
                        "name": target["name"],
                        "url": target["url"],
                        "machine_id": target["machine_id"],
                        "enabled": target["enabled"],
                        "server_reachable": target["server_reachable"],
                        "queue_size": target["queued"],
                        "uploaded": target["uploaded"],
                        "failed": target["failed"],
                        "requeued": target["requeued"],
                        "last_error": target["last_error"],
                    }
                    for target in self._targets.values()
                ]
            }

    def queue_details(
        self,
        *,
        target_ids: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        requested = (
            {
                target_id
                for target_id in target_ids
                if isinstance(target_id, str) and target_id
            }
            if target_ids is not None
            else None
        )
        max_items = max(1, min(500, int(limit)))
        now = time.time()

        with self._lock:
            target_summaries = {
                target_id: {
                    "id": target["id"],
                    "name": target["name"],
                    "url": target["url"],
                    "machine_id": target["machine_id"],
                    "enabled": target["enabled"],
                    "server_reachable": target["server_reachable"],
                    "queue_size": target["queued"],
                    "uploaded": target["uploaded"],
                    "failed": target["failed"],
                    "requeued": target["requeued"],
                    "last_error": target["last_error"],
                }
                for target_id, target in self._targets.items()
                if requested is None or target_id in requested
            }

            active_jobs = [
                dict(job)
                for target_id, job in getattr(self, "_active_jobs", {}).items()
                if requested is None or target_id in requested
            ]
            recent_jobs = [
                dict(job)
                for job in list(getattr(self, "_recent_jobs", deque()))
                if requested is None or job.get("target_id") in requested
            ][:max_items]

            with self._queue.mutex:
                queued_jobs = [
                    self._job_summary_locked(job, "queued", now=now)
                    for job in list(self._queue.queue)
                    if isinstance(job, dict)
                    and (requested is None or job.get("target_id") in requested)
                ][:max_items]

        queued_by_target: dict[str, list[dict[str, Any]]] = {
            target_id: [] for target_id in target_summaries
        }
        active_by_target: dict[str, list[dict[str, Any]]] = {
            target_id: [] for target_id in target_summaries
        }
        recent_by_target: dict[str, list[dict[str, Any]]] = {
            target_id: [] for target_id in target_summaries
        }
        for job in queued_jobs:
            target_id = job.get("target_id")
            if isinstance(target_id, str) and target_id in queued_by_target:
                queued_by_target[target_id].append(job)
        for job in active_jobs:
            target_id = job.get("target_id")
            if isinstance(target_id, str) and target_id in active_by_target:
                active_by_target[target_id].append(job)
        for job in recent_jobs:
            target_id = job.get("target_id")
            if isinstance(target_id, str) and target_id in recent_by_target:
                recent_by_target[target_id].append(job)

        return {
            "generated_at": now,
            "targets": [
                {
                    **target,
                    "queued_jobs": queued_by_target.get(target_id, []),
                    "active_jobs": active_by_target.get(target_id, []),
                    "recent_jobs": recent_by_target.get(target_id, []),
                }
                for target_id, target in target_summaries.items()
            ],
        }

    def _job_summary_locked(
        self,
        job: dict[str, Any],
        status: str,
        *,
        now: float | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
        target_id = job.get("target_id") if isinstance(job.get("target_id"), str) else None
        target = self._targets.get(target_id or "")
        queued_at = _safe_float(job.get("queued_at"))
        timestamp = now if now is not None else time.time()
        teacher_state = teacher_state_from_metadata(metadata)
        sample_type = sample_type_from_metadata(metadata)
        return {
            "status": status,
            "operation": job.get("operation") if isinstance(job.get("operation"), str) else "upload",
            "target_id": target_id,
            "target_name": target.get("name") if target else None,
            "session_id": job.get("session_id"),
            "session_name": job.get("session_name"),
            "sample_id": job.get("sample_id"),
            "source_role": metadata.get("source_role"),
            "capture_reason": metadata.get("capture_reason") or metadata.get("source"),
            "captured_at": _safe_float(metadata.get("captured_at")),
            "queued_at": queued_at,
            "age_s": max(0.0, timestamp - queued_at) if queued_at is not None else None,
            "detection_algorithm": metadata.get("detection_algorithm"),
            "detection_bbox_count": _safe_int(metadata.get("detection_bbox_count")),
            "detection_score": _safe_float(metadata.get("detection_score")),
            "sample_type": sample_type,
            "sample_type_label": sample_type_label(sample_type),
            "teacher_state": teacher_state["state"],
            "teacher_label": teacher_state["label"],
            "teacher_reason": teacher_state["reason"],
            "message": message,
        }

    def _set_active_job(self, target_id: str, job: dict[str, Any]) -> None:
        with self._lock:
            self._active_jobs[target_id] = self._job_summary_locked(
                job,
                "uploading",
                now=time.time(),
            )

    def _finish_active_job(
        self,
        target_id: str,
        job: dict[str, Any],
        status: str,
        *,
        message: str | None = None,
    ) -> None:
        with self._lock:
            self._finish_active_job_locked(
                target_id,
                job,
                status,
                message=message,
            )

    def _finish_active_job_locked(
        self,
        target_id: str,
        job: dict[str, Any],
        status: str,
        *,
        message: str | None = None,
    ) -> None:
        finished_at = time.time()
        summary = self._job_summary_locked(
            job,
            status,
            now=finished_at,
            message=message,
        )
        summary["finished_at"] = finished_at
        self._recent_jobs.appendleft(summary)
        self._active_jobs.pop(target_id, None)
        if status != "retrying":
            key = _job_key(job)
            if key is not None:
                getattr(self, "_queued_job_keys", set()).discard(key)

    def _mark_job_uploaded(
        self,
        job: dict[str, Any],
        target_id: str,
        *,
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        metadata_path_value = job.get("metadata_path")
        if not isinstance(metadata_path_value, str) or not metadata_path_value:
            return

        metadata_path = Path(metadata_path_value)
        try:
            metadata = json.loads(metadata_path.read_text())
        except Exception:
            log.debug(
                "Hive upload marker skipped: metadata unavailable for %s/%s",
                job.get("session_id"),
                job.get("sample_id"),
                exc_info=True,
            )
            return
        if not isinstance(metadata, dict):
            return

        uploads = metadata.get(UPLOAD_MARKER_KEY)
        if not isinstance(uploads, dict):
            uploads = {}
        target = self._targets.get(target_id, {})
        uploads[target_id] = {
            "status": "uploaded",
            "operation": job.get("operation") if isinstance(job.get("operation"), str) else "upload",
            "uploaded_at": time.time(),
            "target_id": target_id,
            "target_name": target.get("name") if isinstance(target.get("name"), str) else None,
            "target_url": target.get("url") if isinstance(target.get("url"), str) else None,
            "remote_sample_id": (
                response_payload.get("id")
                if isinstance(response_payload, dict) and isinstance(response_payload.get("id"), str)
                else None
            ),
        }
        metadata[UPLOAD_MARKER_KEY] = uploads
        try:
            metadata_path.write_text(json.dumps(metadata, indent=2))
            job_metadata = job.get("metadata")
            if isinstance(job_metadata, dict):
                job_metadata[UPLOAD_MARKER_KEY] = uploads
        except Exception:
            log.debug(
                "Hive upload marker write failed for %s/%s",
                job.get("session_id"),
                job.get("sample_id"),
                exc_info=True,
            )

    def _resolve_target_ids_locked(self, requested_target_ids: list[str] | None = None) -> list[str]:
        enabled_target_ids = [
            target_id
            for target_id, target in self._targets.items()
            if target.get("enabled") and target.get("client") is not None
        ]
        if requested_target_ids is None:
            return enabled_target_ids

        requested = {target_id for target_id in requested_target_ids if isinstance(target_id, str)}
        return [target_id for target_id in enabled_target_ids if target_id in requested]

    def enqueue(
        self,
        *,
        session_id: str,
        session_name: str | None,
        sample_id: str,
        metadata: dict[str, Any],
        image_path: str,
        full_frame_path: str | None = None,
        overlay_path: str | None = None,
        metadata_path: str | None = None,
        target_ids: list[str] | None = None,
    ) -> int:
        if teacher_state_from_metadata(metadata)["state"] in BLOCKED_TEACHER_STATES:
            log.info(
                "Hive upload skipped until teacher sample is usable: %s/%s",
                session_id,
                sample_id,
            )
            return 0
        quality_issue = _primary_image_quality_issue(Path(image_path))
        if quality_issue is not None:
            log.info(
                "Hive upload skipped because primary image is unusable: %s/%s: %s",
                session_id,
                sample_id,
                quality_issue["reason"],
            )
            return 0

        with self._lock:
            resolved_target_ids = self._resolve_target_ids_locked(target_ids)
            if not resolved_target_ids:
                return 0
            queued_target_ids: list[str] = []
            queued_keys = getattr(self, "_queued_job_keys", set())
            for target_id in resolved_target_ids:
                if _is_uploaded_to_target(metadata, target_id):
                    continue
                key = ("upload", target_id, session_id, sample_id)
                if key in queued_keys:
                    continue
                target = self._targets.get(target_id)
                if target is not None:
                    target["queued"] = int(target.get("queued", 0)) + 1
                    queued_keys.add(key)
                    queued_target_ids.append(target_id)
            self._queued_job_keys = queued_keys

        for target_id in queued_target_ids:
            self._queue.put(
                {
                    "operation": "upload",
                    "target_id": target_id,
                    "session_id": session_id,
                    "session_name": session_name,
                    "sample_id": sample_id,
                    "metadata": metadata,
                    "image_path": image_path,
                    "full_frame_path": full_frame_path,
                    "overlay_path": overlay_path,
                    "metadata_path": metadata_path,
                    "queued_at": time.time(),
                }
            )
        return len(queued_target_ids)

    def enqueue_update(
        self,
        *,
        session_id: str,
        session_name: str | None,
        sample_id: str,
        metadata: dict[str, Any],
        image_path: str | None = None,
        full_frame_path: str | None = None,
        overlay_path: str | None = None,
        metadata_path: str | None = None,
        target_ids: list[str] | None = None,
    ) -> int:
        if teacher_state_from_metadata(metadata)["state"] in BLOCKED_TEACHER_STATES:
            log.info(
                "Hive update skipped until teacher sample is usable: %s/%s",
                session_id,
                sample_id,
            )
            return 0

        with self._lock:
            resolved_target_ids = self._resolve_target_ids_locked(target_ids)
            if not resolved_target_ids:
                return 0
            queued_target_ids: list[str] = []
            queued_keys = getattr(self, "_queued_job_keys", set())
            for target_id in resolved_target_ids:
                key = ("update", target_id, session_id, sample_id)
                if key in queued_keys:
                    continue
                target = self._targets.get(target_id)
                if target is not None:
                    target["queued"] = int(target.get("queued", 0)) + 1
                    queued_keys.add(key)
                    queued_target_ids.append(target_id)
            self._queued_job_keys = queued_keys

        for target_id in queued_target_ids:
            self._queue.put(
                {
                    "operation": "update",
                    "target_id": target_id,
                    "session_id": session_id,
                    "session_name": session_name,
                    "sample_id": sample_id,
                    "metadata": metadata,
                    "image_path": image_path,
                    "full_frame_path": full_frame_path,
                    "overlay_path": overlay_path,
                    "metadata_path": metadata_path,
                    "queued_at": time.time(),
                }
            )
        return len(queued_target_ids)

    def backfill(
        self,
        training_root: Path,
        session_ids: list[str] | None = None,
        target_ids: list[str] | None = None,
        max_samples: int | None = None,
        sample_type: str | None = None,
        selection: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            resolved_target_ids = self._resolve_target_ids_locked(target_ids)
            if not resolved_target_ids:
                return {"ok": False, "error": "No enabled Hive target is available."}
        if not training_root.exists():
            return {"ok": False, "error": "Training root does not exist."}

        queued = 0
        skipped = 0
        errors = 0
        needs_gemini = 0
        no_teacher_detection = 0
        bad_teacher_sample = 0
        dark_image_sample = 0
        samples_scanned = 0
        scan_limit = max(0, int(max_samples)) if isinstance(max_samples, int) else None
        normalized_sample_type = normalize_sample_type_filter(sample_type)
        selection_mode = (
            selection.strip().lower().replace("-", "_")
            if isinstance(selection, str) and selection.strip()
            else "latest"
        )
        if session_ids:
            session_dirs = [training_root / session_id for session_id in session_ids if (training_root / session_id).is_dir()]
        else:
            session_dirs = sorted([path for path in training_root.iterdir() if path.is_dir()], key=lambda path: path.name, reverse=True)

        metadata_entries: list[tuple[Path, str, str, Path]] = []
        for session_dir in session_dirs:
            session_id = session_dir.name
            manifest_path = session_dir / "manifest.json"
            manifest = {}
            if manifest_path.exists():
                try:
                    parsed = json.loads(manifest_path.read_text())
                    if isinstance(parsed, dict):
                        manifest = parsed
                except Exception:
                    errors += 1
            session_name = (
                manifest.get("session_name")
                if isinstance(manifest.get("session_name"), str) and manifest.get("session_name")
                else session_id
            )
            metadata_dir = session_dir / "metadata"
            if not metadata_dir.exists():
                continue
            for metadata_path in metadata_dir.glob("*.json"):
                metadata_entries.append((session_dir, session_id, session_name, metadata_path))

        def _entry_mtime(entry: tuple[Path, str, str, Path]) -> float:
            try:
                return entry[3].stat().st_mtime
            except Exception:
                return 0.0

        if selection_mode == "random":
            random.shuffle(metadata_entries)
        else:
            metadata_entries.sort(key=_entry_mtime, reverse=True)

        for session_dir, session_id, session_name, metadata_path in metadata_entries:
            if scan_limit is not None and queued >= scan_limit:
                break
            try:
                metadata_mtime = metadata_path.stat().st_mtime
            except Exception:
                metadata_mtime = 0.0
            samples_scanned += 1
            try:
                metadata = json.loads(metadata_path.read_text())
            except Exception:
                errors += 1
                continue
            if not isinstance(metadata, dict):
                errors += 1
                continue
            sample_timestamp = _safe_float(metadata.get("captured_at")) or metadata_mtime
            if since_ts is not None and sample_timestamp < since_ts:
                skipped += 1
                continue
            if until_ts is not None and sample_timestamp > until_ts:
                skipped += 1
                continue
            if not sample_type_matches(metadata, normalized_sample_type):
                skipped += 1
                continue
            teacher_state = teacher_state_from_metadata(metadata)["state"]
            if teacher_state == "needs_gemini":
                needs_gemini += 1
                skipped += 1
                continue
            if teacher_state == "no_teacher_detection":
                no_teacher_detection += 1
                skipped += 1
                continue
            if teacher_state == "bad_teacher_sample":
                bad_teacher_sample += 1
                skipped += 1
                continue
            if all(_is_uploaded_to_target(metadata, target_id) for target_id in resolved_target_ids):
                skipped += 1
                continue
            sample_id = metadata.get("sample_id") if isinstance(metadata.get("sample_id"), str) else metadata_path.stem
            image_path = _resolve_archived_file_path(
                metadata.get("input_image"),
                training_root=training_root,
                session_dir=session_dir,
                fallback_dirs=(session_dir / "dataset" / "images", session_dir / "captures"),
            )
            if image_path is None:
                skipped += 1
                continue
            quality_issue = _primary_image_quality_issue(image_path)
            if quality_issue is not None:
                dark_image_sample += 1
                skipped += 1
                continue
            full_frame_path: Path | None = None
            for candidate_key in ("top_frame_path", "bottom_frame_path"):
                resolved_path = _resolve_archived_file_path(
                    metadata.get(candidate_key),
                    training_root=training_root,
                    session_dir=session_dir,
                    fallback_dirs=(session_dir / "captures",),
                )
                if resolved_path is not None:
                    full_frame_path = resolved_path
                    break

            overlay_path: Path | None = None
            distill_result = metadata.get("distill_result")
            if isinstance(distill_result, dict):
                overlay_path = _resolve_archived_file_path(
                    distill_result.get("overlay_image"),
                    training_root=training_root,
                    session_dir=session_dir,
                    fallback_dirs=(session_dir / "distilled" / "overlays",),
                )

            queued += self.enqueue(
                session_id=session_id,
                session_name=session_name,
                sample_id=sample_id,
                metadata=metadata,
                image_path=str(image_path),
                full_frame_path=str(full_frame_path) if full_frame_path is not None else None,
                overlay_path=str(overlay_path) if overlay_path is not None else None,
                metadata_path=str(metadata_path),
                target_ids=resolved_target_ids,
            )
            if scan_limit is not None and queued >= scan_limit:
                break

        return {
            "ok": True,
            "queued": queued,
            "skipped": skipped,
            "errors": errors,
            "needs_gemini": needs_gemini,
            "no_teacher_detection": no_teacher_detection,
            "bad_teacher_sample": bad_teacher_sample,
            "dark_image_sample": dark_image_sample,
            "samples_scanned": samples_scanned,
            "sessions_scanned": len(session_dirs),
            "target_count": len(resolved_target_ids),
            "sample_type": normalized_sample_type,
            "selection": selection_mode,
        }

    def purge(self, target_ids: list[str] | None = None) -> dict[str, Any]:
        requested_target_ids = (
            {
                target_id.strip()
                for target_id in target_ids
                if isinstance(target_id, str) and target_id.strip()
            }
            if target_ids is not None
            else None
        )
        if target_ids is not None and not requested_target_ids:
            return {"ok": False, "error": "No valid Hive target is available for purge."}

        purged = 0
        purged_by_target: dict[str, int] = {}
        target_count = len(requested_target_ids) if requested_target_ids is not None else 0

        with self._lock:
            if requested_target_ids is None:
                target_count = len(self._targets)

            # Purge only queued jobs while preserving order for the rest.
            with self._queue.mutex:
                kept_jobs: deque[dict[str, Any] | None] = deque()
                while self._queue.queue:
                    job = self._queue.queue.popleft()
                    if job is None:
                        kept_jobs.append(job)
                        continue

                    job_target_id = job.get("target_id")
                    if requested_target_ids is not None and job_target_id not in requested_target_ids:
                        kept_jobs.append(job)
                        continue

                    purged += 1
                    if isinstance(job_target_id, str) and job_target_id:
                        purged_by_target[job_target_id] = purged_by_target.get(job_target_id, 0) + 1
                    key = _job_key(job)
                    if key is not None:
                        getattr(self, "_queued_job_keys", set()).discard(key)

                self._queue.queue.extend(kept_jobs)
                self._queue.unfinished_tasks = max(0, self._queue.unfinished_tasks - purged)
                self._queue.not_full.notify_all()

            affected_target_ids = requested_target_ids if requested_target_ids is not None else set(self._targets.keys())
            for target_id in affected_target_ids:
                target = self._targets.get(target_id)
                if target is None:
                    continue

                removed = purged_by_target.get(target_id, 0)
                if removed > 0:
                    target["queued"] = max(0, int(target.get("queued", 0)) - removed)
                    target["retry_after"] = 0.0
                    target["backoff_s"] = SERVER_DOWN_BACKOFF_S
                    if int(target.get("queued", 0)) == 0 and isinstance(target.get("last_error"), str):
                        target["last_error"] = None

            remaining = sum(
                max(0, int(target.get("queued", 0)))
                for target_id, target in self._targets.items()
                if requested_target_ids is None or target_id in requested_target_ids
            )

        return {
            "ok": True,
            "purged": purged,
            "remaining": remaining,
            "target_count": target_count,
            "purged_by_target": purged_by_target,
        }

    def _heartbeat_loop(self) -> None:
        while True:
            time.sleep(HEARTBEAT_INTERVAL_S)
            with self._lock:
                heartbeat_targets = [
                    (target_id, target["name"], target["client"])
                    for target_id, target in self._targets.items()
                    if target.get("enabled") and target.get("client") is not None
                ]

            for target_id, target_name, client in heartbeat_targets:
                try:
                    reachable = client.heartbeat()
                except Exception:
                    reachable = False

                with self._lock:
                    target = self._targets.get(target_id)
                    if target is None:
                        continue
                    was_down = not bool(target.get("server_reachable", True))
                    target["server_reachable"] = reachable
                    if reachable:
                        target["retry_after"] = 0.0
                        target["backoff_s"] = SERVER_DOWN_BACKOFF_S

                if reachable and was_down:
                    log.info("Hive server is back online: %s", target_name)
                elif not reachable and not was_down:
                    log.warning("Hive server is unreachable: %s", target_name)

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            self._process_job(job)
            time.sleep(UPLOAD_THROTTLE_S)

    def _decrement_queue_locked(self, target_id: str) -> None:
        target = self._targets.get(target_id)
        if target is None:
            return
        target["queued"] = max(0, int(target.get("queued", 0)) - 1)

    def _process_job(self, job: dict[str, Any]) -> None:
        target_id = job.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            return
        operation = job.get("operation") if isinstance(job.get("operation"), str) else "upload"

        image_path = None
        if job.get("image_path"):
            candidate = Path(job["image_path"])
            if candidate.exists():
                image_path = candidate
                quality_issue = _primary_image_quality_issue(candidate)
                if quality_issue is not None:
                    log.info(
                        "Hive upload skipped: primary image is unusable %s: %s",
                        candidate,
                        quality_issue["reason"],
                    )
                    self._finish_active_job(
                        target_id,
                        job,
                        "skipped",
                        message=quality_issue["reason"],
                    )
                    with self._lock:
                        self._decrement_queue_locked(target_id)
                    return
            elif operation == "upload":
                log.warning("Hive upload skipped: image not found %s", candidate)
                self._finish_active_job(target_id, job, "skipped", message="Image file was missing.")
                with self._lock:
                    self._decrement_queue_locked(target_id)
                return
        elif operation == "upload":
            log.warning("Hive upload skipped: missing image path for %s/%s", job.get("session_id"), job.get("sample_id"))
            self._finish_active_job(target_id, job, "skipped", message="Primary image path was missing.")
            with self._lock:
                self._decrement_queue_locked(target_id)
            return

        full_frame_path = None
        if job.get("full_frame_path"):
            candidate = Path(job["full_frame_path"])
            if candidate.exists():
                full_frame_path = candidate

        overlay_path = None
        if job.get("overlay_path"):
            candidate = Path(job["overlay_path"])
            if candidate.exists():
                overlay_path = candidate

        metadata = job["metadata"]
        skip_keys = {
            "source_role",
            "capture_reason",
            "source",
            "captured_at",
            "detection_algorithm",
            "detection_bbox_count",
            "detection_score",
            "sample_id",
            "input_image",
            "top_zone_path",
            "bottom_zone_path",
            "top_frame_path",
            "bottom_frame_path",
            "processor",
            "preferred_camera",
            "archive_mode",
            "sample_payload",
            "condition_assessment",
            "condition_sample",
            "condition_source",
            "condition_source_piece_uuid",
            "condition_source_crop_path",
            "condition_source_segment_sequence",
            "condition_source_kind",
            "condition_source_crop_index",
            "condition_source_crop_stats",
        }
        extra_metadata = {key: value for key, value in metadata.items() if key not in skip_keys and value is not None}
        sample_payload = metadata.get("sample_payload")
        if not isinstance(sample_payload, dict):
            sample_payload = build_sample_payload(
                session_id=job["session_id"],
                sample_id=job["sample_id"],
                session_name=job.get("session_name"),
                metadata=metadata,
                include_primary_asset=image_path is not None,
                include_full_frame=full_frame_path is not None,
                include_overlay=overlay_path is not None,
            )

        with self._lock:
            target = self._targets.get(target_id)
            if target is None:
                return
            if not target.get("enabled") or target.get("client") is None:
                self._finish_active_job_locked(
                    target_id,
                    job,
                    "skipped",
                    message="Hive target is disabled.",
                )
                self._decrement_queue_locked(target_id)
                return

            retry_after = float(target.get("retry_after", 0.0))
            if retry_after > time.time():
                self._queue.put(job)
                return

            client = target["client"]
            target_name = target["name"]

        self._set_active_job(target_id, job)
        for attempt in range(1, UPLOAD_MAX_RETRIES + 1):
            try:
                request_kwargs = {
                    "source_session_id": job["session_id"],
                    "local_sample_id": job["sample_id"],
                    "image_path": image_path,
                    "full_frame_path": full_frame_path,
                    "overlay_path": overlay_path,
                    "source_role": metadata.get("source_role"),
                    "capture_reason": metadata.get("capture_reason") or metadata.get("source"),
                    "captured_at": self._format_timestamp(metadata.get("captured_at")),
                    "session_name": job.get("session_name"),
                    "detection_algorithm": metadata.get("detection_algorithm"),
                    "detection_bboxes": (
                        _normalize_bbox_list_payload(metadata.get("detection_bboxes"))
                        or _normalize_bbox_list_payload(metadata.get("detection_bbox"))
                    ),
                    "detection_count": _safe_int(metadata.get("detection_bbox_count")),
                    "detection_score": _safe_float(metadata.get("detection_score")),
                    "sample_payload": sample_payload,
                    "extra_metadata": extra_metadata or None,
                }
                if operation == "update":
                    response_payload = client.update_sample(**request_kwargs)
                else:
                    if image_path is None:
                        raise FileNotFoundError("Upload job is missing the primary image path.")
                    response_payload = client.upload_sample(**request_kwargs)  # type: ignore[arg-type]
                with self._lock:
                    self._mark_job_uploaded(
                        job,
                        target_id,
                        response_payload=response_payload if isinstance(response_payload, dict) else None,
                    )
                    target = self._targets.get(target_id)
                    if target is not None:
                        target["uploaded"] = int(target.get("uploaded", 0)) + 1
                        target["last_error"] = None
                        target["server_reachable"] = True
                        target["retry_after"] = 0.0
                        target["backoff_s"] = SERVER_DOWN_BACKOFF_S
                        self._decrement_queue_locked(target_id)
                        self._finish_active_job_locked(
                            target_id,
                            job,
                            "uploaded",
                            message="Uploaded to Hive.",
                        )
                return
            except Exception as exc:
                retry_missing_sample = (
                    operation == "update"
                    and isinstance(exc, requests.HTTPError)
                    and exc.response is not None
                    and exc.response.status_code == 404
                )
                if _is_transient(exc) or retry_missing_sample:
                    with self._lock:
                        target = self._targets.get(target_id)
                        if target is not None:
                            target["server_reachable"] = not retry_missing_sample
                            target["requeued"] = int(target.get("requeued", 0)) + 1
                            target["last_error"] = f"Retrying sample sync: {exc}"
                            backoff_s = min(
                                max(float(target.get("backoff_s", SERVER_DOWN_BACKOFF_S)), SERVER_DOWN_BACKOFF_S) * 1.5,
                                SERVER_DOWN_MAX_BACKOFF_S,
                            )
                            target["backoff_s"] = backoff_s
                            target["retry_after"] = time.time() + backoff_s
                            self._finish_active_job_locked(
                                target_id,
                                job,
                                "retrying",
                                message=f"Retrying sample sync: {exc}",
                            )
                    self._queue.put(job)
                    return
                if attempt < UPLOAD_MAX_RETRIES:
                    time.sleep(UPLOAD_RETRY_BASE_S * (2 ** (attempt - 1)))
                    continue
                with self._lock:
                    target = self._targets.get(target_id)
                    if target is not None:
                        target["failed"] = int(target.get("failed", 0)) + 1
                        target["last_error"] = str(exc)
                        self._decrement_queue_locked(target_id)
                        self._finish_active_job_locked(
                            target_id,
                            job,
                            "failed",
                            message=str(exc),
                        )
                log.error(
                    "Hive upload failed after %d attempts for %s: %s/%s: %s",
                    UPLOAD_MAX_RETRIES,
                    target_name,
                    job["session_id"],
                    job["sample_id"],
                    exc,
                )

    @staticmethod
    def _format_timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            from datetime import datetime, timezone

            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        return None
