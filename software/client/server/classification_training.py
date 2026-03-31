from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

import cv2
import numpy as np

from blob_manager import (
    BLOB_DIR,
    getClassificationTrainingConfig,
    setClassificationTrainingConfig,
)
from server.local_detector_models import get_local_detector_model, local_detector_model_options

if TYPE_CHECKING:
    from vision import VisionManager


TRAINING_ROOT = BLOB_DIR / "classification_training"
CLIENT_ROOT = Path(__file__).resolve().parents[1]
SAM2_CHECKPOINT = CLIENT_ROOT / "models" / "checkpoints" / "sam2.1_hiera_small.pt"
DISTILL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "distill_segment_sample.py"
LOCAL_RETEST_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retest_local_detector_sample.py"
DEFAULT_PROCESSOR = "gemini_sam"
CLASSIFICATION_SAMPLE_SOURCES = {
    "manual_capture",
    "settings_detection_test",
    "live_classification",
}
ASYNC_AUXILIARY_SAMPLE_ROLES = {
    "c_channel_2",
    "c_channel_3",
    "carousel",
}
ASYNC_AUXILIARY_DETECTION_SCOPES = {
    "feeder",
    "carousel",
}
DEFAULT_LIBRARY_PAGE_SIZE = 36
MAX_LIBRARY_PAGE_SIZE = 120
VALID_SAMPLE_REVIEW_STATUSES = {"accepted", "rejected"}
DISTILL_MAX_CONCURRENCY = 3
DISTILL_FAILURE_BACKOFF_S = 3.0


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "sample-session"


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


class ClassificationTrainingManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._vision_manager: VisionManager | None = None
        self._processor = DEFAULT_PROCESSOR
        self._session_id: str | None = None
        self._session_name: str | None = None
        self._session_dir: Path | None = None
        self._created_at: float | None = None
        self._queued = 0
        self._completed = 0
        self._failed = 0
        self._running_tasks: dict[str, dict[str, Any]] = {}
        self._last_task: dict[str, Any] | None = None
        self._deleted_samples: set[tuple[str, str]] = set()
        self._distill_pause_until: float = 0.0
        self._recent_completion_times: list[float] = []
        self._loadPersistedConfig()
        self._workers = [
            threading.Thread(
                target=self._workerLoop,
                daemon=True,
                name=f"classification-training-worker-{index + 1}",
            )
            for index in range(DISTILL_MAX_CONCURRENCY)
        ]
        for worker in self._workers:
            worker.start()

    def _loadPersistedConfig(self) -> None:
        saved = getClassificationTrainingConfig()
        if not isinstance(saved, dict):
            return
        processor = saved.get("processor")
        if isinstance(processor, str) and processor == DEFAULT_PROCESSOR:
            self._processor = processor
        session_dir = saved.get("session_dir")
        session_id = saved.get("session_id")
        session_name = saved.get("session_name")
        created_at = saved.get("created_at")
        if isinstance(session_dir, str) and session_dir:
            path = Path(session_dir)
            if path.exists():
                self._session_dir = path
                self._session_id = session_id if isinstance(session_id, str) else path.name
                self._session_name = session_name if isinstance(session_name, str) else path.name
                self._created_at = float(created_at) if isinstance(created_at, (int, float)) else time.time()
                self._queued = len(list((path / "metadata").glob("*.json")))
                self._completed = len(list((path / "distilled" / "json").glob("*.json")))
                self._failed = 0

    def _persistConfig(self) -> None:
        payload = {
            "processor": self._processor,
            "session_id": self._session_id,
            "session_name": self._session_name,
            "session_dir": str(self._session_dir) if self._session_dir is not None else None,
            "created_at": self._created_at,
        }
        setClassificationTrainingConfig(payload)

    def setVisionManager(self, manager: VisionManager | None) -> None:
        with self._lock:
            self._vision_manager = manager
        self.requeueSkippedAuxiliarySamples()

    def startSession(self, session_name: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._createSessionLocked(session_name)
            self._persistConfig()
            return {
                "ok": True,
                "session_id": self._session_id,
                "session_name": self._session_name,
                "session_dir": str(self._session_dir) if self._session_dir is not None else None,
                "created_at": self._created_at,
            }

    def setProcessor(self, processor: str) -> dict[str, Any]:
        with self._lock:
            if processor != DEFAULT_PROCESSOR:
                raise ValueError(f"Unsupported sample processor '{processor}'.")
            self._processor = processor
            self._persistConfig()
            return {
                "ok": True,
                "processor": self._processor,
                "session_id": self._session_id,
                "session_name": self._session_name,
            }

    def captureCurrentFrame(self, camera: str) -> dict[str, Any]:
        with self._lock:
            vision = self._vision_manager
            if self._ensureSessionLocked():
                self._persistConfig()
            session_dir = self._requireSessionDirLocked()
            processor = self._processor
        if vision is None:
            raise ValueError("Vision manager is not initialized.")
        capture = vision.captureClassificationSample(camera)
        zone_key = f"{camera}_zone"
        zone = capture.get(zone_key)
        if not isinstance(zone, np.ndarray) or zone.size == 0:
            raise ValueError("No live classification tray crop is available for this view.")
        metadata = {
            "source": "manual_capture",
            "source_role": "classification_chamber",
            "capture_reason": "manual_capture",
            "detection_scope": "classification",
            "camera": camera,
            "captured_at": time.time(),
        }
        return self._enqueueSavedSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera=camera,
            top_zone=capture.get("top_zone"),
            bottom_zone=capture.get("bottom_zone"),
            top_frame=capture.get("top_frame"),
            bottom_frame=capture.get("bottom_frame"),
            metadata=metadata,
        )

    def saveDetectionDebugCapture(
        self,
        *,
        camera: str,
        algorithm: str,
        openrouter_model: str | None,
        debug_result: dict[str, Any] | None,
        top_zone: np.ndarray | None,
        bottom_zone: np.ndarray | None,
        top_frame: np.ndarray | None,
        bottom_frame: np.ndarray | None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._ensureSessionLocked():
                self._persistConfig()
            session_dir = self._requireSessionDirLocked()
            processor = self._processor
        metadata: dict[str, Any] = {
            "source": "settings_detection_test",
            "source_role": "classification_chamber",
            "capture_reason": "settings_detection_test",
            "detection_scope": "classification",
            "camera": camera,
            "captured_at": time.time(),
            "detection_algorithm": algorithm if isinstance(algorithm, str) and algorithm else None,
            "detection_openrouter_model": (
                openrouter_model
                if isinstance(openrouter_model, str) and openrouter_model and algorithm == "gemini_sam"
                else None
            ),
        }
        if isinstance(debug_result, dict):
            bbox = debug_result.get("bbox")
            candidate_bboxes = debug_result.get("candidate_bboxes")
            metadata.update(
                {
                    "detection_found": bool(debug_result.get("found")),
                    "detection_bbox": bbox if isinstance(bbox, list) else None,
                    "detection_candidate_bboxes": candidate_bboxes if isinstance(candidate_bboxes, list) else [],
                    "detection_bbox_count": int(debug_result.get("bbox_count", 0)),
                    "detection_score": _safe_float(debug_result.get("score")),
                    "detection_message": (
                        debug_result.get("message")
                        if isinstance(debug_result.get("message"), str)
                        else None
                    ),
                }
            )
        return self._enqueueSavedSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera=camera,
            top_zone=top_zone,
            bottom_zone=bottom_zone,
            top_frame=top_frame,
            bottom_frame=bottom_frame,
            metadata=metadata,
        )

    def saveLiveClassificationCapture(
        self,
        *,
        piece_uuid: str,
        machine_id: str,
        run_id: str,
        detection_found: bool,
        detection_algorithm: str | None,
        detection_openrouter_model: str | None,
        detection_bbox_count: int | None = None,
        top_detection_bbox_count: int | None = None,
        bottom_detection_bbox_count: int | None = None,
        detection_message: str | None = None,
        top_zone: np.ndarray | None,
        bottom_zone: np.ndarray | None,
        top_frame: np.ndarray | None,
        bottom_frame: np.ndarray | None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._ensureSessionLocked():
                self._persistConfig()
            session_dir = self._requireSessionDirLocked()
            processor = self._processor
        metadata = {
            "source": "live_classification",
            "source_role": "classification_chamber",
            "capture_reason": "live_classification",
            "detection_scope": "classification",
            "piece_uuid": piece_uuid,
            "machine_id": machine_id,
            "run_id": run_id,
            "captured_at": time.time(),
            "detection_found": bool(detection_found),
            "detection_algorithm": (
                detection_algorithm
                if isinstance(detection_algorithm, str) and detection_algorithm
                else None
            ),
            "detection_openrouter_model": (
                detection_openrouter_model
                if (
                    isinstance(detection_openrouter_model, str)
                    and detection_openrouter_model
                    and detection_algorithm == "gemini_sam"
                )
                else None
            ),
            "detection_bbox_count": int(detection_bbox_count or 0),
            "top_detection_bbox_count": int(top_detection_bbox_count or 0),
            "bottom_detection_bbox_count": int(bottom_detection_bbox_count or 0),
            "detection_message": detection_message if isinstance(detection_message, str) else None,
        }
        return self._enqueueSavedSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera="top" if top_zone is not None else "bottom",
            top_zone=top_zone,
            bottom_zone=bottom_zone,
            top_frame=top_frame,
            bottom_frame=bottom_frame,
            metadata=metadata,
        )

    def attachLiveClassificationResult(
        self,
        session_id: str,
        sample_id: str,
        *,
        status: str,
        part_id: str | None,
        color_id: str | None,
        color_name: str | None,
        confidence: float | None,
        preview_url: str | None,
        source_view: str | None,
        top_crop: np.ndarray | None,
        bottom_crop: np.ndarray | None,
        result_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        captures_dir = session_dir / "captures"
        results_dir = session_dir / "classification"
        results_json_dir = results_dir / "json"
        results_json_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            metadata = self._readJsonFile(metadata_path)
            if metadata is None:
                raise ValueError("Unknown sample.")

            top_crop_path = captures_dir / f"{sample_id}_brickognize_top_crop.jpg"
            bottom_crop_path = captures_dir / f"{sample_id}_brickognize_bottom_crop.jpg"
            result_json_path = results_json_dir / f"{sample_id}_brickognize.json"

            self._writeImage(top_crop_path, top_crop)
            self._writeImage(bottom_crop_path, bottom_crop)

            selected_crop_path: Path | None = None
            if source_view == "top" and top_crop is not None:
                selected_crop_path = top_crop_path
            elif source_view == "bottom" and bottom_crop is not None:
                selected_crop_path = bottom_crop_path
            elif top_crop is not None:
                selected_crop_path = top_crop_path
            elif bottom_crop is not None:
                selected_crop_path = bottom_crop_path

            if isinstance(result_payload, dict):
                result_json_path.write_text(json.dumps(result_payload, indent=2))
            elif result_json_path.exists():
                result_json_path.unlink(missing_ok=True)

            best_item = result_payload.get("best_item") if isinstance(result_payload, dict) else None
            best_color = result_payload.get("best_color") if isinstance(result_payload, dict) else None
            top_result = result_payload.get("top_result") if isinstance(result_payload, dict) else None
            bottom_result = result_payload.get("bottom_result") if isinstance(result_payload, dict) else None
            provider = (
                result_payload.get("provider")
                if isinstance(result_payload, dict) and isinstance(result_payload.get("provider"), str)
                else "brickognize"
            )
            error = (
                result_payload.get("error")
                if isinstance(result_payload, dict) and isinstance(result_payload.get("error"), str)
                else None
            )

            metadata["classification_result"] = {
                "provider": provider,
                "status": status if isinstance(status, str) and status else "unknown",
                "completed_at": time.time(),
                "part_id": part_id if isinstance(part_id, str) and part_id else None,
                "item_name": best_item.get("name") if isinstance(best_item, dict) and isinstance(best_item.get("name"), str) else None,
                "item_category": (
                    best_item.get("category")
                    if isinstance(best_item, dict) and isinstance(best_item.get("category"), str)
                    else None
                ),
                "color_id": color_id if isinstance(color_id, str) and color_id else None,
                "color_name": color_name if isinstance(color_name, str) and color_name else None,
                "confidence": _safe_float(confidence),
                "preview_url": preview_url if isinstance(preview_url, str) and preview_url else None,
                "source_view": source_view if isinstance(source_view, str) and source_view else None,
                "top_crop_path": str(top_crop_path) if top_crop is not None else None,
                "bottom_crop_path": str(bottom_crop_path) if bottom_crop is not None else None,
                "selected_crop_path": str(selected_crop_path) if selected_crop_path is not None else None,
                "result_json": str(result_json_path) if isinstance(result_payload, dict) else None,
                "top_items_count": len(top_result.get("items", [])) if isinstance(top_result, dict) and isinstance(top_result.get("items"), list) else 0,
                "bottom_items_count": len(bottom_result.get("items", [])) if isinstance(bottom_result, dict) and isinstance(bottom_result.get("items"), list) else 0,
                "top_colors_count": len(top_result.get("colors", [])) if isinstance(top_result, dict) and isinstance(top_result.get("colors"), list) else 0,
                "bottom_colors_count": len(bottom_result.get("colors", [])) if isinstance(bottom_result, dict) and isinstance(bottom_result.get("colors"), list) else 0,
                "error": error,
            }
            metadata_path.write_text(json.dumps(metadata, indent=2))

        manifest = self._readSessionManifest(session_dir)
        return self._sampleDetail(session_dir, metadata, manifest)

    def saveAuxiliaryDetectionCapture(
        self,
        *,
        source: str,
        source_role: str,
        detection_scope: str,
        capture_reason: str,
        detection_algorithm: str | None,
        detection_openrouter_model: str | None,
        detection_found: bool,
        detection_bbox: list[int] | tuple[int, int, int, int] | None,
        detection_candidate_bboxes: list[list[int]] | list[tuple[int, int, int, int]] | None,
        detection_bbox_count: int | None,
        detection_score: float | None,
        detection_message: str | None,
        input_image: np.ndarray | None,
        source_frame: np.ndarray | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._ensureSessionLocked():
                self._persistConfig()
            session_dir = self._requireSessionDirLocked()
            processor = self._processor
        metadata = {
            "source": source,
            "source_role": source_role,
            "camera": source_role,
            "capture_reason": capture_reason,
            "detection_scope": detection_scope,
            "captured_at": time.time(),
            "detection_found": bool(detection_found),
            "detection_algorithm": (
                detection_algorithm
                if isinstance(detection_algorithm, str) and detection_algorithm
                else None
            ),
            "detection_openrouter_model": (
                detection_openrouter_model
                if (
                    isinstance(detection_openrouter_model, str)
                    and detection_openrouter_model
                    and detection_algorithm == "gemini_sam"
                )
                else None
            ),
            "detection_bbox": list(detection_bbox) if isinstance(detection_bbox, (list, tuple)) else None,
            "detection_candidate_bboxes": [
                list(candidate)
                for candidate in (detection_candidate_bboxes or [])
                if isinstance(candidate, (list, tuple)) and len(candidate) >= 4
            ],
            "detection_bbox_count": int(detection_bbox_count or 0),
            "detection_score": _safe_float(detection_score),
            "detection_message": detection_message if isinstance(detection_message, str) else None,
        }
        if isinstance(extra_metadata, dict):
            metadata.update(extra_metadata)
        return self._enqueueSavedSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera="top",
            top_zone=input_image,
            bottom_zone=None,
            top_frame=source_frame,
            bottom_frame=None,
            metadata=metadata,
            enqueue_distill=True,
        )

    def requeueSkippedAuxiliarySamples(self) -> dict[str, int]:
        queued = 0
        skipped = 0
        for session_dir in self._sessionDirs():
            manifest = self._readSessionManifest(session_dir)
            processor = (
                manifest.get("processor")
                if isinstance(manifest.get("processor"), str) and manifest.get("processor")
                else self._processor
            )
            for metadata_path in sorted((session_dir / "metadata").glob("*.json")):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
                metadata = self._normalizeAndPersistMetadata(metadata_path, metadata)
                if not self._shouldRequeueAuxiliarySample(metadata):
                    skipped += 1
                    continue
                task = self._queueExistingDistillTask(
                    session_dir=session_dir,
                    metadata_path=metadata_path,
                    metadata=metadata,
                    processor=processor,
                )
                if task is None:
                    skipped += 1
                    continue
                queued += 1
        return {"queued": queued, "skipped": skipped}

    def getLibrary(self) -> dict[str, Any]:
        return self.queryLibrary(page=1, page_size=0)

    def getWorkerStatus(self) -> dict[str, Any]:
        pending_count = 0
        completed_count = 0
        failed_count = 0
        pending_model_counts: dict[str, int] = {}
        pending_scope_counts: dict[str, int] = {}

        for session_dir in self._sessionDirs():
            for metadata_path in sorted((session_dir / "metadata").glob("*.json"), reverse=True):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
                metadata = self._normalizeAndPersistMetadata(metadata_path, metadata)
                status = self._distillStatus(metadata)
                if status == "pending":
                    pending_count += 1
                    model = (
                        metadata.get("detection_openrouter_model")
                        if isinstance(metadata.get("detection_openrouter_model"), str)
                        and metadata.get("detection_openrouter_model")
                        else self._processor
                    )
                    pending_model_counts[model] = pending_model_counts.get(model, 0) + 1
                    scope = (
                        metadata.get("detection_scope")
                        if isinstance(metadata.get("detection_scope"), str) and metadata.get("detection_scope")
                        else "classification"
                    )
                    pending_scope_counts[scope] = pending_scope_counts.get(scope, 0) + 1
                elif status == "completed":
                    completed_count += 1
                elif status == "failed":
                    failed_count += 1

        with self._lock:
            running_tasks = [dict(task) for task in self._running_tasks.values() if isinstance(task, dict)]
            last_task = dict(self._last_task) if isinstance(self._last_task, dict) else None
            queue_depth = self._queue.qsize() + len(running_tasks)
            completion_times = list(self._recent_completion_times)
            processor = self._processor

        items_per_minute: float | None = None
        eta_seconds: float | None = None
        if len(completion_times) >= 2:
            window_s = completion_times[-1] - completion_times[0]
            if window_s > 0:
                items_per_minute = ((len(completion_times) - 1) / window_s) * 60.0
        if items_per_minute and items_per_minute > 0 and pending_count > 0:
            eta_seconds = (pending_count / items_per_minute) * 60.0

        active_model = max(pending_model_counts, key=pending_model_counts.get) if pending_model_counts else None
        active_scope = max(pending_scope_counts, key=pending_scope_counts.get) if pending_scope_counts else None

        return {
            "processor": processor,
            "pending_count": pending_count,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "queue_depth": queue_depth,
            "running": bool(running_tasks),
            "running_count": len(running_tasks),
            "items_per_minute": items_per_minute,
            "eta_seconds": eta_seconds,
            "active_model": active_model,
            "active_scope": active_scope,
            "last_task_status": last_task.get("status") if isinstance(last_task, dict) else None,
        }

    def queryLibrary(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_LIBRARY_PAGE_SIZE,
        search: str | None = None,
        session_id: str | None = None,
        detection_scope: str | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        detection_algorithm: str | None = None,
        classification_status: str | None = None,
        has_classification_result: bool | None = None,
        review_status: str | None = None,
        sort_by: str = "captured_at",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        sessions, samples = self._collectLibrarySamples()
        facets = self._libraryFacets(samples, sessions)
        filtered_samples = self._filterLibrarySamples(
            samples,
            search=search,
            session_id=session_id,
            detection_scope=detection_scope,
            source_role=source_role,
            capture_reason=capture_reason,
            detection_algorithm=detection_algorithm,
            classification_status=classification_status,
            has_classification_result=has_classification_result,
            review_status=review_status,
        )
        filtered_samples.sort(
            key=lambda sample: self._librarySortValue(sample, sort_by),
            reverse=(sort_dir or "desc").lower() != "asc",
        )
        requested_page_size = (
            int(page_size)
            if isinstance(page_size, int)
            else DEFAULT_LIBRARY_PAGE_SIZE
        )
        total_count = len(filtered_samples)
        safe_page_size = (
            max(total_count, 1)
            if requested_page_size <= 0
            else max(1, min(MAX_LIBRARY_PAGE_SIZE, requested_page_size))
        )
        page_count = max(1, (total_count + safe_page_size - 1) // safe_page_size)
        safe_page = max(1, min(int(page or 1), page_count))
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        return {
            "ok": True,
            "sessions": sessions,
            "samples": filtered_samples[start:end],
            "pagination": {
                "page": safe_page,
                "page_size": safe_page_size,
                "page_count": page_count,
                "total_count": total_count,
            },
            "facets": facets,
            "query": {
                "search": search.strip() if isinstance(search, str) and search.strip() else None,
                "session_id": session_id if isinstance(session_id, str) and session_id else None,
                "detection_scope": detection_scope if isinstance(detection_scope, str) and detection_scope else None,
                "source_role": source_role if isinstance(source_role, str) and source_role else None,
                "capture_reason": capture_reason if isinstance(capture_reason, str) and capture_reason else None,
                "detection_algorithm": detection_algorithm if isinstance(detection_algorithm, str) and detection_algorithm else None,
                "classification_status": classification_status if isinstance(classification_status, str) and classification_status else None,
                "has_classification_result": has_classification_result if isinstance(has_classification_result, bool) else None,
                "review_status": review_status if isinstance(review_status, str) and review_status else None,
                "sort_by": sort_by,
                "sort_dir": "asc" if (sort_dir or "").lower() == "asc" else "desc",
            },
        }

    def clearLibrarySamples(
        self,
        *,
        distill_status: str,
        search: str | None = None,
        session_id: str | None = None,
        detection_scope: str | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        detection_algorithm: str | None = None,
        classification_status: str | None = None,
        has_classification_result: bool | None = None,
        review_status: str | None = None,
    ) -> dict[str, Any]:
        allowed_statuses = {"failed", "pending", "skipped"}
        if distill_status not in allowed_statuses:
            raise ValueError(f"Unsupported distill status '{distill_status}'.")

        _sessions, samples = self._collectLibrarySamples()
        filtered_samples = self._filterLibrarySamples(
            samples,
            search=search,
            session_id=session_id,
            detection_scope=detection_scope,
            source_role=source_role,
            capture_reason=capture_reason,
            detection_algorithm=detection_algorithm,
            classification_status=classification_status,
            has_classification_result=has_classification_result,
            review_status=review_status,
        )
        matching_samples = [
            sample for sample in filtered_samples if sample.get("distill_status") == distill_status
        ]

        deleted_count = 0
        blocked_count = 0
        error_count = 0
        removed_session_count = 0

        for sample in matching_samples:
            sample_session_id = sample.get("session_id")
            sample_id = sample.get("sample_id")
            if not isinstance(sample_session_id, str) or not sample_session_id:
                error_count += 1
                continue
            if not isinstance(sample_id, str) or not sample_id:
                error_count += 1
                continue
            try:
                result = self.deleteSample(sample_session_id, sample_id)
                deleted_count += 1
                if bool(result.get("removed_session")):
                    removed_session_count += 1
            except RuntimeError:
                blocked_count += 1
            except Exception:
                error_count += 1

        return {
            "ok": True,
            "distill_status": distill_status,
            "matched_count": len(matching_samples),
            "deleted_count": deleted_count,
            "blocked_count": blocked_count,
            "error_count": error_count,
            "removed_session_count": removed_session_count,
        }

    def retryLibrarySamples(
        self,
        *,
        distill_status: str,
        search: str | None = None,
        session_id: str | None = None,
        detection_scope: str | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        detection_algorithm: str | None = None,
        classification_status: str | None = None,
        has_classification_result: bool | None = None,
        review_status: str | None = None,
    ) -> dict[str, Any]:
        allowed_statuses = {"failed", "skipped", "pending"}
        if distill_status not in allowed_statuses:
            raise ValueError(f"Unsupported retry distill status '{distill_status}'.")

        _sessions, samples = self._collectLibrarySamples()
        filtered_samples = self._filterLibrarySamples(
            samples,
            search=search,
            session_id=session_id,
            detection_scope=detection_scope,
            source_role=source_role,
            capture_reason=capture_reason,
            detection_algorithm=detection_algorithm,
            classification_status=classification_status,
            has_classification_result=has_classification_result,
            review_status=review_status,
        )
        matching_samples = [
            sample for sample in filtered_samples if sample.get("distill_status") == distill_status
        ]

        queued_count = 0
        skipped_count = 0
        error_count = 0

        for sample in matching_samples:
            sample_session_id = sample.get("session_id")
            sample_id = sample.get("sample_id")
            if not isinstance(sample_session_id, str) or not sample_session_id:
                error_count += 1
                continue
            if not isinstance(sample_id, str) or not sample_id:
                error_count += 1
                continue
            session_dir = TRAINING_ROOT / sample_session_id
            metadata_path = session_dir / "metadata" / f"{sample_id}.json"
            metadata = self._readJsonFile(metadata_path)
            if not isinstance(metadata, dict):
                error_count += 1
                continue
            metadata = self._normalizeAndPersistMetadata(metadata_path, metadata)
            processor = (
                metadata.get("processor")
                if isinstance(metadata.get("processor"), str) and metadata.get("processor")
                else self._processor
            )
            try:
                task = self._queueExistingDistillTask(
                    session_dir=session_dir,
                    metadata_path=metadata_path,
                    metadata=metadata,
                    processor=processor,
                )
                if task is None:
                    skipped_count += 1
                else:
                    queued_count += 1
            except Exception:
                error_count += 1

        return {
            "ok": True,
            "distill_status": distill_status,
            "matched_count": len(matching_samples),
            "queued_count": queued_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
        }

    def _collectLibrarySamples(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sessions: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []
        for session_dir in self._sessionDirs():
            manifest = self._readSessionManifest(session_dir)
            session_samples: list[dict[str, Any]] = []
            for metadata_path in sorted((session_dir / "metadata").glob("*.json"), reverse=True):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
                metadata = self._normalizeAndPersistMetadata(metadata_path, metadata)
                summary = self._sampleSummary(session_dir, metadata, manifest)
                session_samples.append(summary)
                samples.append(summary)
            sessions.append(
                {
                    "session_id": manifest["session_id"],
                    "session_name": manifest["session_name"],
                    "created_at": manifest["created_at"],
                    "processor": manifest["processor"],
                    "sample_count": len(session_samples),
                    "completed_count": sum(
                        1 for sample in session_samples if sample.get("distill_status") == "completed"
                    ),
                    "failed_count": sum(
                        1 for sample in session_samples if sample.get("distill_status") == "failed"
                    ),
                    "latest_sample": session_samples[0] if session_samples else None,
                }
            )
        sessions.sort(key=lambda session: float(session.get("created_at") or 0.0), reverse=True)
        return sessions, samples

    def _filterLibrarySamples(
        self,
        samples: list[dict[str, Any]],
        *,
        search: str | None,
        session_id: str | None,
        detection_scope: str | None,
        source_role: str | None,
        capture_reason: str | None,
        detection_algorithm: str | None,
        classification_status: str | None,
        has_classification_result: bool | None,
        review_status: str | None,
    ) -> list[dict[str, Any]]:
        return [
            sample
            for sample in samples
            if self._sampleMatchesLibraryQuery(
                sample,
                search=search,
                session_id=session_id,
                detection_scope=detection_scope,
                source_role=source_role,
                capture_reason=capture_reason,
                detection_algorithm=detection_algorithm,
                classification_status=classification_status,
                has_classification_result=has_classification_result,
                review_status=review_status,
            )
        ]

    def _libraryFacets(
        self,
        samples: list[dict[str, Any]],
        sessions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        def uniqueStrings(values: list[Any]) -> list[str]:
            return sorted({value for value in values if isinstance(value, str) and value})

        return {
            "sessions": [
                {
                    "id": session.get("session_id"),
                    "label": session.get("session_name"),
                    "count": int(session.get("sample_count", 0)),
                }
                for session in sessions
                if isinstance(session.get("session_id"), str)
            ],
            "detection_scopes": uniqueStrings([sample.get("detection_scope") for sample in samples]),
            "source_roles": uniqueStrings([sample.get("source_role") for sample in samples]),
            "capture_reasons": uniqueStrings([sample.get("capture_reason") for sample in samples]),
            "detection_algorithms": uniqueStrings([sample.get("detection_algorithm") for sample in samples]),
            "classification_statuses": uniqueStrings(
                [
                    sample.get("classification_result", {}).get("status")
                    for sample in samples
                    if isinstance(sample.get("classification_result"), dict)
                ]
            ),
            "review_statuses": uniqueStrings([sample.get("review_status") for sample in samples]),
        }

    def _sampleMatchesLibraryQuery(
        self,
        sample: dict[str, Any],
        *,
        search: str | None,
        session_id: str | None,
        detection_scope: str | None,
        source_role: str | None,
        capture_reason: str | None,
        detection_algorithm: str | None,
        classification_status: str | None,
        has_classification_result: bool | None,
        review_status: str | None,
    ) -> bool:
        if isinstance(session_id, str) and session_id and sample.get("session_id") != session_id:
            return False
        if isinstance(detection_scope, str) and detection_scope and sample.get("detection_scope") != detection_scope:
            return False
        if isinstance(source_role, str) and source_role and sample.get("source_role") != source_role:
            return False
        if isinstance(capture_reason, str) and capture_reason and sample.get("capture_reason") != capture_reason:
            return False
        if isinstance(detection_algorithm, str) and detection_algorithm and sample.get("detection_algorithm") != detection_algorithm:
            return False
        classification_result = (
            sample.get("classification_result")
            if isinstance(sample.get("classification_result"), dict)
            else None
        )
        if isinstance(classification_status, str) and classification_status:
            if classification_result is None or classification_result.get("status") != classification_status:
                return False
        if isinstance(has_classification_result, bool):
            if has_classification_result != bool(classification_result):
                return False
        sample_review_status = (
            sample.get("review_status")
            if isinstance(sample.get("review_status"), str) and sample.get("review_status")
            else None
        )
        if isinstance(review_status, str) and review_status:
            if review_status == "unreviewed":
                if sample_review_status is not None:
                    return False
            elif sample_review_status != review_status:
                return False
        if isinstance(search, str) and search.strip():
            needle = search.strip().lower()
            haystack = " ".join(
                str(value)
                for value in (
                    sample.get("sample_id"),
                    sample.get("session_name"),
                    sample.get("source"),
                    sample.get("source_role"),
                    sample.get("capture_reason"),
                    sample.get("detection_scope"),
                    sample.get("camera"),
                    sample.get("preferred_camera"),
                    sample.get("detection_algorithm"),
                    sample.get("detection_openrouter_model"),
                    sample_review_status,
                    classification_result.get("status") if classification_result else None,
                    classification_result.get("part_id") if classification_result else None,
                    classification_result.get("item_name") if classification_result else None,
                    classification_result.get("color_name") if classification_result else None,
                )
                if value is not None
            ).lower()
            if needle not in haystack:
                return False
        return True

    def _librarySortValue(self, sample: dict[str, Any], sort_by: str) -> Any:
        classification_result = (
            sample.get("classification_result")
            if isinstance(sample.get("classification_result"), dict)
            else None
        )
        if sort_by == "sample_id":
            return str(sample.get("sample_id") or "")
        if sort_by == "session":
            return str(sample.get("session_name") or "")
        if sort_by == "detections":
            return int(sample.get("detection_bbox_count") or 0)
        if sort_by == "retests":
            return int(sample.get("retest_count") or 0)
        if sort_by == "classification_confidence":
            return float(classification_result.get("confidence") or 0.0) if classification_result else 0.0
        if sort_by == "classification_completed_at":
            return float(classification_result.get("completed_at") or 0.0) if classification_result else 0.0
        return float(sample.get("captured_at") or 0.0)

    def availableRetestModels(self) -> list[dict[str, str]]:
        from vision.gemini_sam_detector import SUPPORTED_OPENROUTER_MODELS

        cloud_options = [{"id": model, "label": model} for model in SUPPORTED_OPENROUTER_MODELS]
        return [*local_detector_model_options(), *cloud_options]

    def getSampleDetail(self, session_id: str, sample_id: str) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        manifest = self._readSessionManifest(session_dir)
        metadata = self._loadSampleMetadata(session_dir, sample_id)
        detail = self._sampleDetail(session_dir, metadata, manifest)

        # Determine previous and next sample IDs from the session metadata dir
        prev_sample_id: str | None = None
        next_sample_id: str | None = None
        metadata_dir = session_dir / "metadata"
        if metadata_dir.exists():
            all_sample_ids = sorted(
                (p.stem for p in metadata_dir.glob("*.json")),
                reverse=True,
            )
            try:
                idx = all_sample_ids.index(sample_id)
            except ValueError:
                idx = -1
            if idx >= 0:
                if idx > 0:
                    next_sample_id = all_sample_ids[idx - 1]
                if idx < len(all_sample_ids) - 1:
                    prev_sample_id = all_sample_ids[idx + 1]

        detail["prev_sample_id"] = prev_sample_id
        detail["next_sample_id"] = next_sample_id

        return {
            "ok": True,
            "session": {
                "session_id": manifest["session_id"],
                "session_name": manifest["session_name"],
                "created_at": manifest["created_at"],
                "processor": manifest["processor"],
            },
            "sample": detail,
        }

    def setSampleReview(
        self,
        session_id: str,
        sample_id: str,
        *,
        status: str | None,
        box_corrections: list[dict[str, Any]] | None = None,
        added_boxes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        with self._lock:
            metadata = self._readJsonFile(metadata_path)
            if metadata is None:
                raise ValueError("Unknown sample.")

            normalized_status = (
                status.strip().lower()
                if isinstance(status, str) and status.strip()
                else None
            )
            if normalized_status is None:
                metadata.pop("review", None)
            elif normalized_status in VALID_SAMPLE_REVIEW_STATUSES:
                review: dict[str, Any] = {
                    "status": normalized_status,
                    "updated_at": time.time(),
                }
                if box_corrections is not None:
                    review["box_corrections"] = box_corrections
                if added_boxes is not None:
                    review["added_boxes"] = added_boxes
                metadata["review"] = review

                # Apply corrections to ground truth labels
                has_corrections = (
                    (box_corrections is not None and any(
                        c.get("status") == "rejected" for c in box_corrections if isinstance(c, dict)
                    ))
                    or (added_boxes is not None and len(added_boxes) > 0)
                )
                if has_corrections:
                    self._applyBoxCorrections(
                        session_dir, metadata, sample_id,
                        box_corrections=box_corrections,
                        added_boxes=added_boxes,
                    )
            else:
                raise ValueError("Unsupported sample review status.")

            metadata_path.write_text(json.dumps(metadata, indent=2))

        manifest = self._readSessionManifest(session_dir)
        return self._sampleDetail(session_dir, metadata, manifest)

    def _applyBoxCorrections(
        self,
        session_dir: Path,
        metadata: dict[str, Any],
        sample_id: str,
        *,
        box_corrections: list[dict[str, Any]] | None,
        added_boxes: list[dict[str, Any]] | None,
    ) -> None:
        """Update distill_result JSON and YOLO labels based on review corrections."""
        distill = metadata.get("distill_result")
        if not isinstance(distill, dict):
            return

        # Load existing distill JSON
        result_json_path = distill.get("result_json")
        if not isinstance(result_json_path, str):
            return
        result_path = Path(result_json_path)
        if not result_path.is_absolute():
            result_path = session_dir / result_json_path
        if not result_path.exists():
            return

        try:
            distill_data = json.loads(result_path.read_text())
        except Exception:
            return
        if not isinstance(distill_data, dict):
            return

        existing_detections = distill_data.get("detections", [])
        if not isinstance(existing_detections, list):
            existing_detections = []

        width = distill_data.get("width", 0)
        height = distill_data.get("height", 0)
        if width <= 0 or height <= 0:
            return

        # Build final detection list: keep confirmed, drop rejected
        final_detections: list[dict[str, Any]] = []
        rejected_bboxes: set[tuple[int, ...]] = set()

        if box_corrections:
            for correction in box_corrections:
                if not isinstance(correction, dict):
                    continue
                if correction.get("status") == "rejected":
                    bbox = correction.get("bbox")
                    if isinstance(bbox, list) and len(bbox) == 4:
                        rejected_bboxes.add(tuple(int(v) for v in bbox[:4]))

        for det in existing_detections:
            if not isinstance(det, dict):
                continue
            bbox = det.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                key = tuple(int(v) for v in bbox[:4])
                if key in rejected_bboxes:
                    continue
            final_detections.append(det)

        # Add new boxes
        if added_boxes:
            for added in added_boxes:
                if not isinstance(added, dict):
                    continue
                bbox = added.get("bbox")
                if not isinstance(bbox, list) or len(bbox) < 4:
                    continue
                raw = [float(v) for v in bbox[:4]]
                # If normalized flag is set, scale from 0-1000 to pixel coords
                if added.get("normalized"):
                    x1 = int(raw[0] / 1000.0 * width)
                    y1 = int(raw[1] / 1000.0 * height)
                    x2 = int(raw[2] / 1000.0 * width)
                    y2 = int(raw[3] / 1000.0 * height)
                else:
                    x1, y1, x2, y2 = [int(v) for v in raw]
                if x2 <= x1 or y2 <= y1:
                    continue
                final_detections.append({
                    "description": "manually added",
                    "bbox": [x1, y1, x2, y2],
                    "polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                    "confidence": 1.0,
                    "manual": True,
                })

        # Write updated distill JSON
        distill_data["detections"] = final_detections
        distill_data["corrected_at"] = time.time()
        result_path.write_text(json.dumps(distill_data, indent=2))

        # Regenerate YOLO label
        yolo_label_path_str = distill.get("yolo_label")
        if isinstance(yolo_label_path_str, str):
            yolo_path = Path(yolo_label_path_str)
            if not yolo_path.is_absolute():
                yolo_path = session_dir / yolo_label_path_str
            lines: list[str] = []
            for det in final_detections:
                polygon = det.get("polygon")
                bbox = det.get("bbox")
                if isinstance(polygon, list) and len(polygon) >= 3:
                    coords: list[str] = []
                    for pt in polygon:
                        if isinstance(pt, list) and len(pt) >= 2:
                            coords.append(f"{pt[0] / width:.6f}")
                            coords.append(f"{pt[1] / height:.6f}")
                    if coords:
                        lines.append("0 " + " ".join(coords))
                elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
                    poly = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                    coords = []
                    for px, py in poly:
                        coords.append(f"{px / width:.6f}")
                        coords.append(f"{py / height:.6f}")
                    lines.append("0 " + " ".join(coords))
            yolo_path.parent.mkdir(parents=True, exist_ok=True)
            yolo_path.write_text("\n".join(lines))

        # Regenerate overlay image
        overlay_path_str = distill.get("overlay_image")
        if isinstance(overlay_path_str, str):
            overlay_path = Path(overlay_path_str)
            if not overlay_path.is_absolute():
                overlay_path = session_dir / overlay_path_str
            image_path = self._existingSampleImagePath(metadata)
            if image_path is not None:
                image = cv2.imread(str(image_path))
                if image is not None:
                    bboxes = []
                    for det in final_detections:
                        b = det.get("bbox")
                        if isinstance(b, (list, tuple)) and len(b) >= 4:
                            bboxes.append(tuple(int(v) for v in b[:4]))
                    dummy_result = type("R", (), {
                        "bbox": bboxes[0] if bboxes else None,
                        "bboxes": tuple(bboxes),
                        "score": 1.0,
                        "algorithm": "manual_correction",
                    })()
                    overlay = self._annotatedDetectionOverlay(image, dummy_result)
                    self._writeImage(overlay_path, overlay)

        # Update metadata counts
        distill["detections"] = len(final_detections)
        distill["corrected_at"] = time.time()

    def getNextUnverifiedSample(self) -> dict[str, Any] | None:
        for session_dir in self._sessionDirs():
            manifest = self._readSessionManifest(session_dir)
            metadata_dir = session_dir / "metadata"
            if not metadata_dir.exists():
                continue
            for metadata_path in sorted(metadata_dir.glob("*.json")):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
                if self._distillStatus(metadata) != "completed":
                    continue
                if isinstance(metadata.get("review"), dict):
                    continue
                detail = self._sampleDetail(session_dir, metadata, manifest)
                detail["_session_id"] = manifest["session_id"]
                return detail
        return None

    def getVerifyStats(self) -> dict[str, Any]:
        total = 0
        accepted = 0
        rejected = 0
        unverified = 0
        for session_dir in self._sessionDirs():
            metadata_dir = session_dir / "metadata"
            if not metadata_dir.exists():
                continue
            for metadata_path in metadata_dir.glob("*.json"):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
                if self._distillStatus(metadata) != "completed":
                    continue
                total += 1
                review = metadata.get("review")
                if isinstance(review, dict) and review.get("status") in VALID_SAMPLE_REVIEW_STATUSES:
                    if review["status"] == "accepted":
                        accepted += 1
                    elif review["status"] == "rejected":
                        rejected += 1
                else:
                    unverified += 1
        return {
            "total": total,
            "verified": accepted + rejected,
            "unverified": unverified,
            "accepted": accepted,
            "rejected": rejected,
        }

    def deleteSample(self, session_id: str, sample_id: str) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._readJsonFile(metadata_path)
        if metadata is None:
            raise ValueError("Unknown sample.")

        sample_key = (session_id, sample_id)
        with self._lock:
            running_match = any(
                task.get("session_id") == session_id and task.get("sample_id") == sample_id
                for task in self._running_tasks.values()
                if isinstance(task, dict)
            )
            if running_match:
                raise RuntimeError("Cannot delete a sample while pseudo-label distillation is running.")
            self._deleted_samples.add(sample_key)

        for path in self._sampleAssetPaths(session_dir, sample_id, metadata):
            self._removeSampleFile(session_dir, path)
        self._removeSampleFile(session_dir, metadata_path)
        self._pruneEmptySessionDirs(session_dir)

        removed_session = False
        metadata_dir = session_dir / "metadata"
        if not metadata_dir.exists() or not any(metadata_dir.glob("*.json")):
            shutil.rmtree(session_dir, ignore_errors=True)
            removed_session = True

        with self._lock:
            if removed_session and self._session_dir is not None:
                try:
                    same_session = self._session_dir.resolve() == session_dir.resolve()
                except Exception:
                    same_session = False
                if same_session:
                    self._session_id = None
                    self._session_name = None
                    self._session_dir = None
                    self._created_at = None
                    self._queued = 0
                    self._completed = 0
                    self._failed = 0
                    self._running_tasks = {}
                    self._last_task = None
                    self._persistConfig()

        return {
            "ok": True,
            "session_id": session_id,
            "sample_id": sample_id,
            "removed_session": removed_session,
        }

    def runSampleRetest(self, session_id: str, sample_id: str, *, model_id: str) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._loadSampleMetadata(session_dir, sample_id)
        image_path = self._existingSampleImagePath(metadata)
        if image_path is None:
            raise ValueError("Saved sample image is unavailable.")

        image = cv2.imread(str(image_path))
        if image is None or image.size == 0:
            raise ValueError("Saved sample image could not be read.")

        retest_id = f"{int(time.time() * 1000)}-{uuid4().hex[:8]}"
        model_slug = _slugify(model_id)
        retest_dir = session_dir / "retests"
        retest_json_dir = retest_dir / "json"
        retest_overlay_dir = retest_dir / "overlays"
        retest_json_dir.mkdir(parents=True, exist_ok=True)
        retest_overlay_dir.mkdir(parents=True, exist_ok=True)
        result_path = retest_json_dir / f"{sample_id}__{model_slug}__{retest_id}.json"
        overlay_path = retest_overlay_dir / f"{sample_id}__{model_slug}__{retest_id}.jpg"
        zone = self._zoneFromMetadata(metadata)
        payload = self._runRetestModel(
            image=image,
            image_path=image_path,
            model_id=model_id,
            result_path=result_path,
            overlay_path=overlay_path,
            zone=zone,
        )
        payload.update(
            {
                "retest_id": retest_id,
                "sample_id": sample_id,
                "created_at": time.time(),
                "model": model_id,
                "result_json": str(result_path),
                "overlay_image": str(overlay_path),
            }
        )
        result_path.write_text(json.dumps(payload, indent=2))

        retests = metadata.get("retests", [])
        if not isinstance(retests, list):
            retests = []
        retests.append(payload)
        metadata["retests"] = retests
        metadata_path.write_text(json.dumps(metadata, indent=2))

        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": session_id,
            "retest": self._retestSummary(session_dir, payload),
        }

    def runSampleRetests(
        self,
        session_id: str,
        sample_id: str,
        *,
        model_ids: list[str],
    ) -> dict[str, Any]:
        requested_models = [
            model for model in dict.fromkeys(model_ids)
            if isinstance(model, str) and model.strip()
        ]
        if not requested_models:
            raise ValueError("No retest models were provided.")

        retests: list[dict[str, Any]] = []
        for model in requested_models:
            result = self.runSampleRetest(session_id, sample_id, model_id=model)
            retest = result.get("retest")
            if isinstance(retest, dict):
                retests.append(retest)

        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": session_id,
            "retests": retests,
        }

    def promoteRetestToGroundTruth(
        self,
        session_id: str,
        sample_id: str,
        *,
        retest_id: str,
    ) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._loadSampleMetadata(session_dir, sample_id)
        image_path = self._existingSampleImagePath(metadata)
        if image_path is None:
            raise ValueError("Saved sample image is unavailable.")

        image = cv2.imread(str(image_path))
        if image is None or image.size == 0:
            raise ValueError("Saved sample image could not be read.")
        height, width = image.shape[:2]

        retests = metadata.get("retests", [])
        retest: dict[str, Any] | None = None
        for entry in retests:
            if isinstance(entry, dict) and entry.get("retest_id") == retest_id:
                retest = entry
                break
        if retest is None:
            raise ValueError("Unknown retest.")

        candidate_bboxes = retest.get("candidate_bboxes", [])
        if not isinstance(candidate_bboxes, list) or not candidate_bboxes:
            bbox = retest.get("bbox")
            candidate_bboxes = [bbox] if isinstance(bbox, list) and len(bbox) == 4 else []
        if not candidate_bboxes:
            raise ValueError("Retest has no valid bounding boxes to promote.")

        current_distill = metadata.get("distill_result")
        if isinstance(current_distill, dict):
            previous = metadata.get("previous_distill_results", [])
            if not isinstance(previous, list):
                previous = []
            previous.append({
                **current_distill,
                "replaced_at": time.time(),
                "replaced_by_retest_id": retest_id,
            })
            metadata["previous_distill_results"] = previous

        yolo_label_path = session_dir / "dataset" / "labels" / f"{sample_id}.txt"
        lines: list[str] = []
        detections_for_json: list[dict[str, Any]] = []
        for bbox in candidate_bboxes:
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            if x2 <= x1 or y2 <= y1:
                continue
            polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            coords: list[str] = []
            for px, py in polygon:
                coords.append(f"{px / width:.6f}")
                coords.append(f"{py / height:.6f}")
            lines.append("0 " + " ".join(coords))
            detections_for_json.append({
                "bbox": [x1, y1, x2, y2],
                "polygon": polygon,
                "confidence": retest.get("score", 0.5),
            })
        yolo_label_path.parent.mkdir(parents=True, exist_ok=True)
        yolo_label_path.write_text("\n".join(lines))

        distill_json_path = session_dir / "distilled" / "json" / f"{sample_id}.json"
        distill_json_payload = {
            "ok": True,
            "image": str(image_path),
            "width": width,
            "height": height,
            "model": retest.get("model", "unknown"),
            "promoted_from_retest": retest_id,
            "detections": detections_for_json,
        }
        distill_json_path.parent.mkdir(parents=True, exist_ok=True)
        distill_json_path.write_text(json.dumps(distill_json_payload, indent=2))

        distill_overlay_path = session_dir / "distilled" / "overlays" / f"{sample_id}.jpg"
        retest_overlay = retest.get("overlay_image")
        if isinstance(retest_overlay, str) and Path(retest_overlay).exists():
            distill_overlay_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(retest_overlay, distill_overlay_path)

        metadata["distill_result"] = {
            "detections": len(detections_for_json),
            "result_json": str(distill_json_path),
            "overlay_image": str(distill_overlay_path),
            "yolo_label": str(yolo_label_path),
            "processed_at": time.time(),
            "promoted_from_retest": retest_id,
            "promoted_model": retest.get("model"),
        }
        metadata.pop("distill_error", None)
        metadata_path.write_text(json.dumps(metadata, indent=2))

        manifest = self._readSessionManifest(session_dir)
        detail = self._sampleDetail(session_dir, metadata, manifest)
        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": session_id,
            "sample": detail,
        }

    def deleteSampleRetest(self, session_id: str, sample_id: str, *, retest_id: str) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._loadSampleMetadata(session_dir, sample_id)

        retests = metadata.get("retests", [])
        if not isinstance(retests, list):
            retests = []

        target: dict[str, Any] | None = None
        remaining: list[dict[str, Any]] = []
        for entry in retests:
            if isinstance(entry, dict) and entry.get("retest_id") == retest_id:
                target = entry
            else:
                remaining.append(entry)

        if target is None:
            raise ValueError("Unknown retest.")

        # Delete retest files from disk
        for key in ("result_json", "overlay_image"):
            file_path = target.get(key)
            if isinstance(file_path, str) and file_path:
                self._removeSampleFile(session_dir, Path(file_path))

        metadata["retests"] = remaining
        metadata_path.write_text(json.dumps(metadata, indent=2))

        manifest = self._readSessionManifest(session_dir)
        detail = self._sampleDetail(session_dir, metadata, manifest)
        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": session_id,
            "sample": detail,
        }

    def clearSampleRetests(self, session_id: str, sample_id: str) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._loadSampleMetadata(session_dir, sample_id)

        retests = metadata.get("retests", [])
        if isinstance(retests, list):
            for entry in retests:
                if not isinstance(entry, dict):
                    continue
                for key in ("result_json", "overlay_image"):
                    file_path = entry.get(key)
                    if isinstance(file_path, str) and file_path:
                        self._removeSampleFile(session_dir, Path(file_path))

        metadata["retests"] = []
        metadata_path.write_text(json.dumps(metadata, indent=2))

        manifest = self._readSessionManifest(session_dir)
        detail = self._sampleDetail(session_dir, metadata, manifest)
        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": session_id,
            "sample": detail,
        }

    @staticmethod
    def _zoneFromMetadata(metadata: dict[str, Any]) -> str:
        scope = metadata.get("detection_scope", "")
        if scope == "feeder":
            return "c_channel"
        if scope == "carousel":
            return "carousel"
        return "classification_chamber"

    def _runRetestModel(
        self,
        *,
        image: np.ndarray,
        image_path: Path,
        model_id: str,
        result_path: Path,
        overlay_path: Path,
        zone: str = "classification_chamber",
    ) -> dict[str, Any]:
        local_model = get_local_detector_model(model_id)
        if local_model is not None:
            return self._runLocalDetectorRetest(
                image_path=image_path,
                model_id=model_id,
                local_model=local_model,
                result_path=result_path,
                overlay_path=overlay_path,
            )
        return self._runOpenRouterRetest(
            image=image,
            model_id=model_id,
            result_path=result_path,
            overlay_path=overlay_path,
            zone=zone,
        )

    def _runOpenRouterRetest(
        self,
        *,
        image: np.ndarray,
        model_id: str,
        result_path: Path,
        overlay_path: Path,
        zone: str = "classification_chamber",
    ) -> dict[str, Any]:
        from vision.gemini_sam_detector import GeminiSamDetector, normalize_openrouter_model

        normalized_model = normalize_openrouter_model(model_id)
        detector = GeminiSamDetector(normalized_model, zone=zone)
        t0 = time.time()
        detection = detector.detect(image, force=True)
        inference_ms = (time.time() - t0) * 1000.0
        last_error = getattr(detector, "_last_error", None)

        overlay = self._annotatedDetectionOverlay(image, detection)
        self._writeImage(overlay_path, overlay)

        bboxes = list(detection.bboxes) if detection is not None else []
        bbox = detection.bbox if detection is not None else None
        return {
            "found": bool(detection is not None and detection.bbox is not None),
            "bbox": list(bbox) if bbox is not None else None,
            "candidate_bboxes": [list(candidate) for candidate in bboxes],
            "bbox_count": len(bboxes),
            "score": float(detection.score) if detection is not None and detection.score is not None else None,
            "error": last_error if isinstance(last_error, str) and last_error else None,
            "inference_ms": round(inference_ms, 1),
            "fps": round(1000.0 / inference_ms, 1) if inference_ms > 0 else None,
        }

    def _runLocalDetectorRetest(
        self,
        *,
        image_path: Path,
        model_id: str,
        local_model: Any,
        result_path: Path,
        overlay_path: Path,
    ) -> dict[str, Any]:
        if not LOCAL_RETEST_SCRIPT.exists():
            raise RuntimeError(f"Local detector retest script not found at {LOCAL_RETEST_SCRIPT}.")

        command = ["uv", "run", "--with", "ultralytics"]
        if getattr(local_model, "runtime", "onnx") == "ncnn":
            command.extend(["--with", "ncnn"])
        else:
            command.extend(["--with", "onnx", "--with", "onnxruntime"])
        command.extend(
            [
                "python",
                str(LOCAL_RETEST_SCRIPT),
                "--input",
                str(image_path),
                "--model",
                str(local_model.model_path),
                "--result-json",
                str(result_path),
                "--overlay-image",
                str(overlay_path),
                "--imgsz",
                str(local_model.imgsz),
            ]
        )
        proc = subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            detail = stderr or stdout or f"local detector subprocess exited with {proc.returncode}"
            raise RuntimeError(detail)
        if not result_path.exists():
            raise RuntimeError("Local detector result JSON was not written.")
        payload = json.loads(result_path.read_text())
        return {
            "found": bool(payload.get("found")),
            "bbox": payload.get("bbox") if isinstance(payload.get("bbox"), list) else None,
            "candidate_bboxes": (
                payload.get("candidate_bboxes") if isinstance(payload.get("candidate_bboxes"), list) else []
            ),
            "bbox_count": int(payload.get("bbox_count", 0)),
            "score": _safe_float(payload.get("score")),
            "error": payload.get("error") if isinstance(payload.get("error"), str) else None,
            "inference_ms": _safe_float(payload.get("inference_ms")),
            "fps": _safe_float(payload.get("fps")),
        }

    def resolveAssetPath(self, session_id: str, asset_path: str) -> Path:
        session_dir = self.resolveSessionDir(session_id)
        candidate = (session_dir / asset_path).resolve()
        session_root = session_dir.resolve()
        try:
            candidate.relative_to(session_root)
        except ValueError as exc:
            raise ValueError("Requested asset is outside the session directory.") from exc
        if not candidate.exists() or not candidate.is_file():
            raise ValueError("Requested asset does not exist.")
        return candidate

    def resolveSessionDir(self, session_id: str) -> Path:
        session_dir = (TRAINING_ROOT / session_id).resolve()
        root = TRAINING_ROOT.resolve()
        try:
            session_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError("Unknown sample session.") from exc
        if not session_dir.exists() or not session_dir.is_dir():
            raise ValueError("Unknown sample session.")
        return session_dir

    def _ensureSessionLocked(self) -> bool:
        if self._session_dir is None:
            self._createSessionLocked(None)
            return True
        return False

    def _requireSessionDirLocked(self) -> Path:
        if self._session_dir is None:
            raise ValueError("No sample session is active.")
        return self._session_dir

    def _createSessionLocked(self, session_name: str | None) -> None:
        TRAINING_ROOT.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        name = _slugify(session_name) if isinstance(session_name, str) and session_name.strip() else f"session-{timestamp}"
        session_id = f"{timestamp}-{uuid4().hex[:8]}"
        session_dir = TRAINING_ROOT / session_id
        for path in (
            session_dir / "captures",
            session_dir / "metadata",
            session_dir / "distilled" / "json",
            session_dir / "distilled" / "overlays",
            session_dir / "dataset" / "images",
            session_dir / "dataset" / "labels",
        ):
            path.mkdir(parents=True, exist_ok=True)
        data_yaml = session_dir / "dataset" / "data.yaml"
        data_yaml.write_text(
            "path: .\ntrain: images\nval: images\nnames:\n  0: piece\n"
        )
        manifest = {
            "session_id": session_id,
            "session_name": name,
            "created_at": time.time(),
            "processor": self._processor,
        }
        (session_dir / "session.json").write_text(json.dumps(manifest, indent=2))
        self._session_id = session_id
        self._session_name = name
        self._session_dir = session_dir
        self._created_at = manifest["created_at"]
        self._queued = 0
        self._completed = 0
        self._failed = 0
        self._running_tasks = {}
        self._last_task = None

    def _sessionDirs(self) -> list[Path]:
        if not TRAINING_ROOT.exists():
            return []
        return sorted(
            [path for path in TRAINING_ROOT.iterdir() if path.is_dir()],
            key=lambda path: path.name,
            reverse=True,
        )

    def _readJsonFile(self, path: Path) -> dict[str, Any] | None:
        try:
            parsed = json.loads(path.read_text())
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _sampleAssetPaths(
        self,
        session_dir: Path,
        sample_id: str,
        metadata: dict[str, Any],
    ) -> list[Path]:
        paths: set[Path] = set()

        def addPath(value: Any) -> None:
            if isinstance(value, str) and value:
                paths.add(Path(value))

        for key in ("input_image", "top_zone_path", "bottom_zone_path", "top_frame_path", "bottom_frame_path"):
            addPath(metadata.get(key))

        distill_result = metadata.get("distill_result")
        if isinstance(distill_result, dict):
            for key in ("overlay_image", "result_json", "yolo_label"):
                addPath(distill_result.get(key))

        classification_result = metadata.get("classification_result")
        if isinstance(classification_result, dict):
            for key in ("result_json", "top_crop_path", "bottom_crop_path", "selected_crop_path"):
                addPath(classification_result.get(key))

        retests = metadata.get("retests")
        if isinstance(retests, list):
            for retest in retests:
                if not isinstance(retest, dict):
                    continue
                for key in ("overlay_image", "result_json"):
                    addPath(retest.get(key))

        paths.add(session_dir / "dataset" / "images" / f"{sample_id}.jpg")
        paths.add(session_dir / "dataset" / "labels" / f"{sample_id}.txt")
        paths.add(session_dir / "distilled" / "json" / f"{sample_id}.json")
        paths.add(session_dir / "distilled" / "overlays" / f"{sample_id}.jpg")
        paths.update((session_dir / "captures").glob(f"{sample_id}_*"))
        paths.update((session_dir / "retests" / "json").glob(f"{sample_id}__*"))
        paths.update((session_dir / "retests" / "overlays").glob(f"{sample_id}__*"))

        return sorted(paths, key=lambda path: len(path.parts), reverse=True)

    def _removeSampleFile(self, session_dir: Path, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(session_dir.resolve())
        except Exception:
            return
        try:
            resolved.unlink(missing_ok=True)
        except Exception:
            pass

    def _pruneEmptySessionDirs(self, session_dir: Path) -> None:
        if not session_dir.exists():
            return
        for directory in sorted(
            (path for path in session_dir.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                next(directory.iterdir())
            except StopIteration:
                try:
                    directory.rmdir()
                except Exception:
                    pass
            except Exception:
                pass

    def _readSessionManifest(self, session_dir: Path) -> dict[str, Any]:
        manifest = self._readJsonFile(session_dir / "session.json") or {}
        created_at = _safe_float(manifest.get("created_at")) or session_dir.stat().st_mtime
        session_id = manifest.get("session_id")
        session_name = manifest.get("session_name")
        processor = manifest.get("processor")
        return {
            "session_id": session_id if isinstance(session_id, str) and session_id else session_dir.name,
            "session_name": session_name if isinstance(session_name, str) and session_name else session_dir.name,
            "created_at": created_at,
            "processor": processor if isinstance(processor, str) and processor else DEFAULT_PROCESSOR,
        }

    def _loadSampleMetadata(self, session_dir: Path, sample_id: str) -> dict[str, Any]:
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._readJsonFile(metadata_path)
        if metadata is None:
            raise ValueError("Unknown sample.")
        return self._normalizeAndPersistMetadata(metadata_path, metadata)

    def _normalizeLegacyMetadata(self, metadata: dict[str, Any]) -> bool:
        changed = False
        source = metadata.get("source")
        if not isinstance(source, str):
            return False

        if source in CLASSIFICATION_SAMPLE_SOURCES:
            if not isinstance(metadata.get("source_role"), str) or not metadata.get("source_role"):
                metadata["source_role"] = "classification_chamber"
                changed = True
            if not isinstance(metadata.get("detection_scope"), str) or not metadata.get("detection_scope"):
                metadata["detection_scope"] = "classification"
                changed = True
            if not isinstance(metadata.get("capture_reason"), str) or not metadata.get("capture_reason"):
                metadata["capture_reason"] = source
                changed = True
            if (
                not isinstance(metadata.get("camera"), str)
                and isinstance(metadata.get("preferred_camera"), str)
                and metadata.get("preferred_camera")
            ):
                metadata["camera"] = metadata["preferred_camera"]
                changed = True

        return changed

    def _normalizeAndPersistMetadata(
        self,
        metadata_path: Path,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._normalizeLegacyMetadata(metadata):
            return metadata
        try:
            metadata_path.write_text(json.dumps(metadata, indent=2))
        except Exception:
            pass
        return metadata

    def _existingSampleImagePath(self, metadata: dict[str, Any]) -> Path | None:
        candidates = [
            metadata.get("input_image"),
            metadata.get("top_zone_path"),
            metadata.get("bottom_zone_path"),
        ]
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                continue
            path = Path(candidate)
            if path.exists() and path.is_file():
                return path
        return None

    def _pathRelativeToSession(self, session_dir: Path, path_value: Any) -> str | None:
        if not isinstance(path_value, str) or not path_value:
            return None
        path = Path(path_value)
        if not path.exists():
            return None
        try:
            return str(path.resolve().relative_to(session_dir.resolve()))
        except ValueError:
            return None

    def _distillStatus(self, metadata: dict[str, Any]) -> str:
        if metadata.get("distill_requested") is False:
            return "skipped"
        if isinstance(metadata.get("distill_result"), dict):
            return "completed"
        if isinstance(metadata.get("distill_error"), str) and metadata["distill_error"]:
            return "failed"
        return "pending"

    def _retestSummary(self, session_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "retest_id": payload.get("retest_id"),
            "created_at": _safe_float(payload.get("created_at")),
            "model": payload.get("model"),
            "found": bool(payload.get("found")),
            "bbox": payload.get("bbox"),
            "candidate_bboxes": payload.get("candidate_bboxes") if isinstance(payload.get("candidate_bboxes"), list) else [],
            "bbox_count": int(payload.get("bbox_count", 0)),
            "score": _safe_float(payload.get("score")),
            "error": payload.get("error") if isinstance(payload.get("error"), str) else None,
            "overlay_image_rel": self._pathRelativeToSession(session_dir, payload.get("overlay_image")),
            "result_json_rel": self._pathRelativeToSession(session_dir, payload.get("result_json")),
            "inference_ms": _safe_float(payload.get("inference_ms")),
            "fps": _safe_float(payload.get("fps")),
        }

    def _sampleSummary(
        self,
        session_dir: Path,
        metadata: dict[str, Any],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        sample_id = metadata.get("sample_id")
        distill_result = metadata.get("distill_result") if isinstance(metadata.get("distill_result"), dict) else {}
        retests = metadata.get("retests")
        retest_count = len(retests) if isinstance(retests, list) else 0
        review = metadata.get("review") if isinstance(metadata.get("review"), dict) else None
        classification_result = (
            metadata.get("classification_result")
            if isinstance(metadata.get("classification_result"), dict)
            else None
        )
        return {
            "session_id": manifest["session_id"],
            "session_name": manifest["session_name"],
            "sample_id": sample_id if isinstance(sample_id, str) else None,
            "source": metadata.get("source") if isinstance(metadata.get("source"), str) else "unknown",
            "source_role": metadata.get("source_role") if isinstance(metadata.get("source_role"), str) else None,
            "capture_reason": (
                metadata.get("capture_reason") if isinstance(metadata.get("capture_reason"), str) else None
            ),
            "detection_scope": (
                metadata.get("detection_scope") if isinstance(metadata.get("detection_scope"), str) else None
            ),
            "camera": metadata.get("camera") if isinstance(metadata.get("camera"), str) else None,
            "preferred_camera": metadata.get("preferred_camera") if isinstance(metadata.get("preferred_camera"), str) else None,
            "captured_at": _safe_float(metadata.get("captured_at")),
            "processor": metadata.get("processor") if isinstance(metadata.get("processor"), str) else manifest["processor"],
            "detection_algorithm": (
                metadata.get("detection_algorithm")
                if isinstance(metadata.get("detection_algorithm"), str)
                else None
            ),
            "detection_openrouter_model": (
                metadata.get("detection_openrouter_model")
                if isinstance(metadata.get("detection_openrouter_model"), str)
                else None
            ),
            "detection_bbox_count": int(metadata.get("detection_bbox_count", 0))
            if metadata.get("detection_bbox_count") is not None
            else None,
            "distill_status": self._distillStatus(metadata),
            "distill_detections": int(distill_result.get("detections", 0)) if isinstance(distill_result.get("detections"), int) else None,
            "retest_count": retest_count,
            "review_status": (
                review.get("status")
                if isinstance(review, dict) and isinstance(review.get("status"), str)
                else None
            ),
            "review_updated_at": (
                _safe_float(review.get("updated_at"))
                if isinstance(review, dict)
                else None
            ),
            "classification_result": (
                {
                    "provider": classification_result.get("provider") if isinstance(classification_result.get("provider"), str) else None,
                    "status": classification_result.get("status") if isinstance(classification_result.get("status"), str) else None,
                    "completed_at": _safe_float(classification_result.get("completed_at")),
                    "part_id": classification_result.get("part_id") if isinstance(classification_result.get("part_id"), str) else None,
                    "item_name": classification_result.get("item_name") if isinstance(classification_result.get("item_name"), str) else None,
                    "item_category": classification_result.get("item_category") if isinstance(classification_result.get("item_category"), str) else None,
                    "color_id": classification_result.get("color_id") if isinstance(classification_result.get("color_id"), str) else None,
                    "color_name": classification_result.get("color_name") if isinstance(classification_result.get("color_name"), str) else None,
                    "confidence": _safe_float(classification_result.get("confidence")),
                    "preview_url": classification_result.get("preview_url") if isinstance(classification_result.get("preview_url"), str) else None,
                    "source_view": classification_result.get("source_view") if isinstance(classification_result.get("source_view"), str) else None,
                    "selected_crop_rel": self._pathRelativeToSession(session_dir, classification_result.get("selected_crop_path")),
                    "top_crop_rel": self._pathRelativeToSession(session_dir, classification_result.get("top_crop_path")),
                    "bottom_crop_rel": self._pathRelativeToSession(session_dir, classification_result.get("bottom_crop_path")),
                    "result_json_rel": self._pathRelativeToSession(session_dir, classification_result.get("result_json")),
                    "top_items_count": int(classification_result.get("top_items_count", 0)) if classification_result.get("top_items_count") is not None else None,
                    "bottom_items_count": int(classification_result.get("bottom_items_count", 0)) if classification_result.get("bottom_items_count") is not None else None,
                    "top_colors_count": int(classification_result.get("top_colors_count", 0)) if classification_result.get("top_colors_count") is not None else None,
                    "bottom_colors_count": int(classification_result.get("bottom_colors_count", 0)) if classification_result.get("bottom_colors_count") is not None else None,
                    "error": classification_result.get("error") if isinstance(classification_result.get("error"), str) else None,
                }
                if classification_result
                else None
            ),
            "input_image_rel": self._pathRelativeToSession(session_dir, metadata.get("input_image")),
            "overlay_image_rel": self._pathRelativeToSession(session_dir, distill_result.get("overlay_image")),
            "top_frame_rel": self._pathRelativeToSession(session_dir, metadata.get("top_frame_path")),
            "bottom_frame_rel": self._pathRelativeToSession(session_dir, metadata.get("bottom_frame_path")),
        }

    def _sampleDetail(
        self,
        session_dir: Path,
        metadata: dict[str, Any],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        detail = self._sampleSummary(session_dir, metadata, manifest)
        distill_result = metadata.get("distill_result") if isinstance(metadata.get("distill_result"), dict) else {}
        retests = metadata.get("retests")
        detail.update(
            {
                "piece_uuid": metadata.get("piece_uuid") if isinstance(metadata.get("piece_uuid"), str) else None,
                "machine_id": metadata.get("machine_id") if isinstance(metadata.get("machine_id"), str) else None,
                "run_id": metadata.get("run_id") if isinstance(metadata.get("run_id"), str) else None,
                "source_role": metadata.get("source_role") if isinstance(metadata.get("source_role"), str) else None,
                "capture_reason": (
                    metadata.get("capture_reason") if isinstance(metadata.get("capture_reason"), str) else None
                ),
                "detection_scope": (
                    metadata.get("detection_scope") if isinstance(metadata.get("detection_scope"), str) else None
                ),
                "detection_found": bool(metadata.get("detection_found")) if metadata.get("detection_found") is not None else None,
                "detection_bbox": metadata.get("detection_bbox") if isinstance(metadata.get("detection_bbox"), list) else None,
                "detection_candidate_bboxes": (
                    metadata.get("detection_candidate_bboxes")
                    if isinstance(metadata.get("detection_candidate_bboxes"), list)
                    else []
                ),
                "detection_bbox_count": int(metadata.get("detection_bbox_count", 0))
                if metadata.get("detection_bbox_count") is not None
                else None,
                "detection_score": _safe_float(metadata.get("detection_score")),
                "detection_message": (
                    metadata.get("detection_message")
                    if isinstance(metadata.get("detection_message"), str)
                    else None
                ),
                "input_image_rel": self._pathRelativeToSession(session_dir, metadata.get("input_image")),
                "top_zone_rel": self._pathRelativeToSession(session_dir, metadata.get("top_zone_path")),
                "bottom_zone_rel": self._pathRelativeToSession(session_dir, metadata.get("bottom_zone_path")),
                "top_frame_rel": self._pathRelativeToSession(session_dir, metadata.get("top_frame_path")),
                "bottom_frame_rel": self._pathRelativeToSession(session_dir, metadata.get("bottom_frame_path")),
                "distill_error": metadata.get("distill_error") if isinstance(metadata.get("distill_error"), str) else None,
                "distill_result": (
                    {
                        "detections": int(distill_result.get("detections", 0)) if isinstance(distill_result.get("detections"), int) else 0,
                        "overlay_image_rel": self._pathRelativeToSession(session_dir, distill_result.get("overlay_image")),
                        "result_json_rel": self._pathRelativeToSession(session_dir, distill_result.get("result_json")),
                        "yolo_label_rel": self._pathRelativeToSession(session_dir, distill_result.get("yolo_label")),
                        "processed_at": _safe_float(distill_result.get("processed_at")),
                    }
                    if distill_result
                    else None
                ),
                "retests": [
                    self._retestSummary(session_dir, retest)
                    for retest in reversed(retests if isinstance(retests, list) else [])
                    if isinstance(retest, dict)
                ],
                "review": (
                    {
                        "status": metadata["review"].get("status")
                        if isinstance(metadata.get("review"), dict)
                        and isinstance(metadata["review"].get("status"), str)
                        else None,
                        "updated_at": _safe_float(metadata["review"].get("updated_at")),
                    }
                    if isinstance(metadata.get("review"), dict)
                    else None
                ),
            }
        )
        return detail

    def _shouldRequeueAuxiliarySample(self, metadata: dict[str, Any]) -> bool:
        source_role = metadata.get("source_role")
        if source_role not in ASYNC_AUXILIARY_SAMPLE_ROLES:
            return False
        detection_scope = metadata.get("detection_scope")
        if detection_scope not in ASYNC_AUXILIARY_DETECTION_SCOPES:
            return False
        if isinstance(metadata.get("distill_result"), dict):
            return False
        if isinstance(metadata.get("distill_error"), str) and metadata.get("distill_error"):
            return False
        input_image = metadata.get("input_image")
        if not isinstance(input_image, str) or not input_image:
            return False
        return Path(input_image).exists()

    def _queueExistingDistillTask(
        self,
        *,
        session_dir: Path,
        metadata_path: Path,
        metadata: dict[str, Any],
        processor: str,
    ) -> dict[str, Any] | None:
        sample_id = metadata.get("sample_id")
        input_image = metadata.get("input_image")
        if not isinstance(sample_id, str) or not sample_id:
            return None
        if not isinstance(input_image, str) or not input_image:
            return None
        input_image_path = Path(input_image)
        if not input_image_path.exists():
            return None

        metadata["distill_requested"] = True
        metadata.pop("distill_error", None)
        metadata.pop("distill_result", None)
        metadata_path.write_text(json.dumps(metadata, indent=2))

        task = self._buildDistillTask(
            session_dir=session_dir,
            sample_id=sample_id,
            processor=processor,
            input_image=str(input_image_path),
            metadata_path=str(metadata_path),
            zone=self._zoneFromMetadata(metadata),
        )
        for stale_path in (
            Path(task["result_json"]),
            Path(task["overlay_image"]),
            Path(task["yolo_label"]),
        ):
            try:
                stale_path.unlink(missing_ok=True)
            except Exception:
                pass
        with self._lock:
            self._queue.put(task)
            self._last_task = {
                "task_id": task["task_id"],
                "sample_id": sample_id,
                "status": "queued",
                "queued_at": task["queued_at"],
                "processor": processor,
            }
        return task

    def _buildDistillTask(
        self,
        *,
        session_dir: Path,
        sample_id: str,
        processor: str,
        input_image: str,
        metadata_path: str,
        zone: str = "classification_chamber",
    ) -> dict[str, Any]:
        dataset_labels_dir = session_dir / "dataset" / "labels"
        distilled_json_dir = session_dir / "distilled" / "json"
        distilled_overlay_dir = session_dir / "distilled" / "overlays"
        session_id = session_dir.name
        return {
            "task_id": uuid4().hex,
            "sample_id": sample_id,
            "session_id": session_id,
            "session_dir": str(session_dir),
            "processor": processor,
            "input_image": input_image,
            "result_json": str(distilled_json_dir / f"{sample_id}.json"),
            "overlay_image": str(distilled_overlay_dir / f"{sample_id}.jpg"),
            "yolo_label": str(dataset_labels_dir / f"{sample_id}.txt"),
            "metadata_path": metadata_path,
            "zone": zone,
            "queued_at": time.time(),
        }

    def _annotatedDetectionOverlay(
        self,
        image: np.ndarray,
        detection: Any,
    ) -> np.ndarray:
        overlay = image.copy()
        bboxes = list(detection.bboxes) if detection is not None else []
        for index, bbox in enumerate(bboxes, start=1):
            x1, y1, x2, y2 = [int(value) for value in bbox]
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (168, 85, 247), 2, cv2.LINE_AA)
            label_x = max(x1 + 6, 0)
            label_y = max(y1 + 18, 14)
            cv2.putText(
                overlay,
                str(index),
                (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (168, 85, 247),
                2,
                cv2.LINE_AA,
            )
        return overlay

    def _writeImage(self, path: Path, image: np.ndarray | None) -> None:
        if image is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])

    def _enqueueSavedSample(
        self,
        *,
        session_dir: Path,
        processor: str,
        preferred_camera: str,
        top_zone: np.ndarray | None,
        bottom_zone: np.ndarray | None,
        metadata: dict[str, Any],
        top_frame: np.ndarray | None = None,
        bottom_frame: np.ndarray | None = None,
        enqueue_distill: bool = True,
    ) -> dict[str, Any]:
        sample_id = f"{int(time.time() * 1000)}-{uuid4().hex[:8]}"
        captures_dir = session_dir / "captures"
        metadata_dir = session_dir / "metadata"
        dataset_images_dir = session_dir / "dataset" / "images"
        dataset_labels_dir = session_dir / "dataset" / "labels"
        distilled_json_dir = session_dir / "distilled" / "json"
        distilled_overlay_dir = session_dir / "distilled" / "overlays"

        top_zone_path = captures_dir / f"{sample_id}_top_zone.jpg"
        bottom_zone_path = captures_dir / f"{sample_id}_bottom_zone.jpg"
        top_frame_path = captures_dir / f"{sample_id}_top_full.jpg"
        bottom_frame_path = captures_dir / f"{sample_id}_bottom_full.jpg"
        self._writeImage(top_zone_path, top_zone)
        self._writeImage(bottom_zone_path, bottom_zone)
        self._writeImage(top_frame_path, top_frame)
        self._writeImage(bottom_frame_path, bottom_frame)

        preferred_path = top_zone_path if preferred_camera == "top" and top_zone is not None else bottom_zone_path
        if preferred_camera != "top" and bottom_zone is None and top_zone is not None:
            preferred_path = top_zone_path
            preferred_camera = "top"
        if preferred_camera != "bottom" and top_zone is None and bottom_zone is not None:
            preferred_path = bottom_zone_path
            preferred_camera = "bottom"
        if not preferred_path.exists():
            raise ValueError("No preferred tray crop was available for the sample capture.")

        dataset_image_path = dataset_images_dir / f"{sample_id}.jpg"
        shutil.copy2(preferred_path, dataset_image_path)

        metadata_payload = {
            **metadata,
            "sample_id": sample_id,
            "processor": processor,
            "preferred_camera": preferred_camera,
            "distill_requested": bool(enqueue_distill),
            "input_image": str(dataset_image_path),
            "top_zone_path": str(top_zone_path) if top_zone is not None else None,
            "bottom_zone_path": str(bottom_zone_path) if bottom_zone is not None else None,
            "top_frame_path": str(top_frame_path) if top_frame is not None else None,
            "bottom_frame_path": str(bottom_frame_path) if bottom_frame is not None else None,
        }
        metadata_path = metadata_dir / f"{sample_id}.json"
        metadata_path.write_text(json.dumps(metadata_payload, indent=2))

        if not enqueue_distill:
            return {
                "ok": True,
                "sample_id": sample_id,
                "session_id": self._session_id,
                "session_dir": str(session_dir),
                "input_image": str(dataset_image_path),
                "message": "Sample saved to the library without pseudo-label distillation.",
            }

        task = self._buildDistillTask(
            session_dir=session_dir,
            sample_id=sample_id,
            processor=processor,
            input_image=str(dataset_image_path),
            metadata_path=str(metadata_path),
            zone=self._zoneFromMetadata(metadata_payload),
        )
        with self._lock:
            self._queue.put(task)
            self._queued += 1
            self._last_task = {
                "task_id": task["task_id"],
                "sample_id": sample_id,
                "status": "queued",
                "queued_at": task["queued_at"],
                "processor": processor,
            }
        return {
            "ok": True,
            "task_id": task["task_id"],
            "sample_id": sample_id,
            "session_id": self._session_id,
            "session_dir": str(session_dir),
            "input_image": str(dataset_image_path),
            "message": "Classification sample saved and queued for pseudo-labeling.",
        }

    def _workerLoop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            sample_key = (str(task.get("session_id") or ""), str(task.get("sample_id") or ""))
            task_id = str(task.get("task_id") or "")
            with self._lock:
                if sample_key in self._deleted_samples:
                    self._last_task = {
                        "task_id": task["task_id"],
                        "session_id": task.get("session_id"),
                        "sample_id": task["sample_id"],
                        "status": "deleted",
                        "finished_at": time.time(),
                        "processor": task["processor"],
                    }
                    continue
                self._running_tasks[task_id] = {
                    "task_id": task["task_id"],
                    "session_id": task.get("session_id"),
                    "sample_id": task["sample_id"],
                    "status": "running",
                    "started_at": time.time(),
                    "processor": task["processor"],
                }
            try:
                self._waitForDistillPause()
                result = self._runTask(task)
                with self._lock:
                    self._completed += 1
                    self._recent_completion_times.append(time.time())
                    self._recent_completion_times = self._recent_completion_times[-12:]
                    self._last_task = {
                        "task_id": task["task_id"],
                        "session_id": task.get("session_id"),
                        "sample_id": task["sample_id"],
                        "status": "completed",
                        "finished_at": time.time(),
                        "processor": task["processor"],
                        "result": result,
                    }
            except Exception as exc:
                with self._lock:
                    self._distill_pause_until = max(
                        self._distill_pause_until,
                        time.time() + DISTILL_FAILURE_BACKOFF_S,
                    )
                with self._lock:
                    self._failed += 1
                    self._last_task = {
                        "task_id": task["task_id"],
                        "session_id": task.get("session_id"),
                        "sample_id": task["sample_id"],
                        "status": "failed",
                        "finished_at": time.time(),
                        "processor": task["processor"],
                        "error": str(exc),
                    }
                metadata_path = Path(task["metadata_path"])
                if metadata_path.exists():
                    try:
                        payload = json.loads(metadata_path.read_text())
                        payload["distill_error"] = str(exc)
                        metadata_path.write_text(json.dumps(payload, indent=2))
                    except Exception:
                        pass
            finally:
                with self._lock:
                    self._running_tasks.pop(task_id, None)

    def _waitForDistillPause(self) -> None:
        with self._lock:
            wait_s = max(0.0, self._distill_pause_until - time.time())
        if wait_s <= 0.0:
            return
        time.sleep(wait_s)

    def _runTask(self, task: dict[str, Any]) -> dict[str, Any]:
        if task["processor"] != DEFAULT_PROCESSOR:
            raise RuntimeError(f"Unsupported sample processor '{task['processor']}'.")
        if not DISTILL_SCRIPT.exists():
            raise RuntimeError(f"Distill script not found at {DISTILL_SCRIPT}.")
        if not SAM2_CHECKPOINT.exists():
            raise RuntimeError(f"SAM2 checkpoint not found at {SAM2_CHECKPOINT}.")

        command = [
            "uv",
            "run",
            "--with",
            "openai",
            "--with",
            "sam-2 @ git+https://github.com/facebookresearch/sam2.git",
            "python",
            str(DISTILL_SCRIPT),
            "--input",
            task["input_image"],
            "--result-json",
            task["result_json"],
            "--overlay-image",
            task["overlay_image"],
            "--yolo-label",
            task["yolo_label"],
            "--checkpoint",
            str(SAM2_CHECKPOINT),
            "--zone",
            task.get("zone", "classification_chamber"),
        ]
        proc = subprocess.run(
            command,
            cwd=str(CLIENT_ROOT),
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            detail = stderr or stdout or f"distill subprocess exited with {proc.returncode}"
            raise RuntimeError(detail)

        result_path = Path(task["result_json"])
        if not result_path.exists():
            raise RuntimeError("Distill result JSON was not written.")
        payload = json.loads(result_path.read_text())
        metadata_path = Path(task["metadata_path"])
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
            metadata["distill_result"] = {
                "detections": len(payload.get("detections", [])),
                "result_json": str(result_path),
                "overlay_image": task["overlay_image"],
                "yolo_label": task["yolo_label"],
                "processed_at": time.time(),
            }
            metadata_path.write_text(json.dumps(metadata, indent=2))
        return {
            "detections": len(payload.get("detections", [])),
            "result_json": str(result_path),
            "overlay_image": task["overlay_image"],
            "yolo_label": task["yolo_label"],
        }


_training_manager = ClassificationTrainingManager()


def getClassificationTrainingManager() -> ClassificationTrainingManager:
    return _training_manager
