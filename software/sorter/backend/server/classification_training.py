from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np

from blob_manager import BLOB_DIR
from local_state import (
    get_classification_training_state,
    set_classification_training_state,
)
from server.hive_uploader import HiveUploader, teacher_state_from_metadata
from server.sample_payloads import build_sample_payload


TRAINING_ROOT = BLOB_DIR / "classification_training"
DEFAULT_PROCESSOR = "local_archive"
LEGACY_PROCESSORS = {"gemini_sam"}
SUPPORTED_PROCESSORS = {DEFAULT_PROCESSOR, *LEGACY_PROCESSORS}
HIVE_AUTO_BACKFILL_INTERVAL_S = 15.0
HIVE_AUTO_BACKFILL_BATCH_SIZE = 75
HIVE_AUTO_BACKFILL_QUEUE_HIGH_WATERMARK = 150


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "sample-session"


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _coerce_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]
    except Exception:
        return None


class ClassificationTrainingManager:
    """Runtime-only local archive for captured classification samples.

    The old sorter branch used this module for three concerns at once:
    local sample archival, review/library APIs, and ML post-processing
    (distillation/retests/training helpers). After moving the platform side to
    Hive, the sorter only keeps the lightweight archival piece that runtime
    code still depends on.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processor = DEFAULT_PROCESSOR
        self._session_id: str | None = None
        self._session_name: str | None = None
        self._session_dir: Path | None = None
        self._created_at: float | None = None
        self._hive = HiveUploader()
        self._loadPersistedConfig()
        self._hive_auto_backfill_thread = threading.Thread(
            target=self._hiveAutoBackfillLoop,
            daemon=True,
            name="hive-auto-backfill",
        )
        self._hive_auto_backfill_thread.start()

    def _loadPersistedConfig(self) -> None:
        saved = get_classification_training_state()
        if not isinstance(saved, dict):
            return

        processor = saved.get("processor")
        if isinstance(processor, str) and processor in SUPPORTED_PROCESSORS:
            self._processor = processor

        session_dir = saved.get("session_dir")
        session_id = saved.get("session_id")
        session_name = saved.get("session_name")
        created_at = saved.get("created_at")

        if not isinstance(session_dir, str) or not session_dir:
            return

        path = Path(session_dir)
        if not path.exists() or not path.is_dir():
            return

        self._session_dir = path
        self._session_id = session_id if isinstance(session_id, str) and session_id else path.name
        self._session_name = (
            session_name if isinstance(session_name, str) and session_name else self._session_id
        )
        self._created_at = float(created_at) if isinstance(created_at, (int, float)) else time.time()
        self._writeSessionManifest(path)

    def _persistConfig(self) -> None:
        set_classification_training_state(
            {
                "processor": self._processor,
                "session_id": self._session_id,
                "session_name": self._session_name,
                "session_dir": str(self._session_dir) if self._session_dir is not None else None,
                "created_at": self._created_at,
            }
        )

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
        normalized = processor.strip() if isinstance(processor, str) else ""
        if normalized not in SUPPORTED_PROCESSORS:
            raise ValueError(f"Unsupported sample processor '{processor}'.")
        with self._lock:
            self._processor = normalized
            self._persistConfig()
            return {
                "ok": True,
                "processor": self._processor,
                "session_id": self._session_id,
                "session_name": self._session_name,
            }

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
            metadata.update(
                {
                    "detection_found": bool(debug_result.get("found")),
                    "detection_bbox": _coerce_bbox(debug_result.get("bbox")),
                    "detection_candidate_bboxes": [
                        candidate
                        for candidate in (_coerce_bbox(value) for value in debug_result.get("candidate_bboxes", []))
                        if candidate is not None
                    ],
                    "detection_bbox_count": int(debug_result.get("bbox_count", 0)),
                    "detection_score": _safe_float(debug_result.get("score")),
                    "detection_message": (
                        debug_result.get("message")
                        if isinstance(debug_result.get("message"), str)
                        else None
                    ),
                }
            )

        return self._archiveSample(
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
        source_role: str = "classification_chamber",
        preferred_camera: str | None = None,
        detection_found: bool,
        detection_algorithm: str | None,
        detection_openrouter_model: str | None,
        detection_bbox: list[int] | tuple[int, int, int, int] | None = None,
        detection_candidate_bboxes: list[list[int]] | list[tuple[int, int, int, int]] | None = None,
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
            "source_role": source_role if isinstance(source_role, str) and source_role else "classification_chamber",
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
            "detection_bbox": _coerce_bbox(detection_bbox),
            "detection_candidate_bboxes": [
                candidate
                for candidate in (_coerce_bbox(value) for value in (detection_candidate_bboxes or []))
                if candidate is not None
            ],
            "detection_bbox_count": int(detection_bbox_count or 0),
            "top_detection_bbox_count": int(top_detection_bbox_count or 0),
            "bottom_detection_bbox_count": int(bottom_detection_bbox_count or 0),
            "detection_message": detection_message if isinstance(detection_message, str) else None,
        }

        return self._archiveSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera=(
                preferred_camera
                if isinstance(preferred_camera, str) and preferred_camera
                else ("top" if top_zone is not None else "bottom")
            ),
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
        classification_dir = session_dir / "classification"
        classification_json_dir = classification_dir / "json"
        classification_json_dir.mkdir(parents=True, exist_ok=True)
        session_name: str | None = None

        with self._lock:
            metadata = self._readJsonFile(metadata_path)
            if metadata is None:
                raise ValueError("Unknown sample.")

            top_crop_path = session_dir / "captures" / f"{sample_id}_brickognize_top_crop.jpg"
            bottom_crop_path = session_dir / "captures" / f"{sample_id}_brickognize_bottom_crop.jpg"
            result_json_path = classification_json_dir / f"{sample_id}_brickognize.json"

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
            else:
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
                "item_name": (
                    best_item.get("name")
                    if isinstance(best_item, dict) and isinstance(best_item.get("name"), str)
                    else None
                ),
                "item_category": (
                    best_item.get("category")
                    if isinstance(best_item, dict) and isinstance(best_item.get("category"), str)
                    else None
                ),
                "color_id": color_id if isinstance(color_id, str) and color_id else None,
                "color_name": (
                    color_name
                    if isinstance(color_name, str) and color_name
                    else (
                        best_color.get("name")
                        if isinstance(best_color, dict) and isinstance(best_color.get("name"), str)
                        else None
                    )
                ),
                "confidence": _safe_float(confidence),
                "preview_url": preview_url if isinstance(preview_url, str) and preview_url else None,
                "source_view": source_view if isinstance(source_view, str) and source_view else None,
                "top_crop_path": str(top_crop_path) if top_crop is not None else None,
                "bottom_crop_path": str(bottom_crop_path) if bottom_crop is not None else None,
                "selected_crop_path": str(selected_crop_path) if selected_crop_path is not None else None,
                "result_json": str(result_json_path) if isinstance(result_payload, dict) else None,
                "top_items_count": (
                    len(top_result.get("items", []))
                    if isinstance(top_result, dict) and isinstance(top_result.get("items"), list)
                    else 0
                ),
                "bottom_items_count": (
                    len(bottom_result.get("items", []))
                    if isinstance(bottom_result, dict) and isinstance(bottom_result.get("items"), list)
                    else 0
                ),
                "top_colors_count": (
                    len(top_result.get("colors", []))
                    if isinstance(top_result, dict) and isinstance(top_result.get("colors"), list)
                    else 0
                ),
                "bottom_colors_count": (
                    len(bottom_result.get("colors", []))
                    if isinstance(bottom_result, dict) and isinstance(bottom_result.get("colors"), list)
                    else 0
                ),
                "error": error,
            }
            manifest = self._readJsonFile(session_dir / "manifest.json") or {}
            session_name = (
                manifest.get("session_name")
                if isinstance(manifest.get("session_name"), str) and manifest.get("session_name")
                else session_id
            )
            metadata["sample_payload"] = build_sample_payload(
                session_id=session_id,
                sample_id=sample_id,
                session_name=session_name,
                metadata=metadata,
                include_primary_asset=True,
                include_full_frame=bool(metadata.get("top_frame_path") or metadata.get("bottom_frame_path")),
                include_overlay=False,
            )
            metadata_path.write_text(json.dumps(metadata, indent=2))

        self._hive.enqueue_update(
            session_id=session_id,
            session_name=session_name,
            sample_id=sample_id,
            metadata=metadata,
            metadata_path=str(metadata_path),
        )

        return {
            "ok": True,
            "session_id": session_id,
            "sample_id": sample_id,
            "classification_result": metadata.get("classification_result"),
        }

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
            "detection_bbox": _coerce_bbox(detection_bbox),
            "detection_candidate_bboxes": [
                candidate
                for candidate in (_coerce_bbox(value) for value in (detection_candidate_bboxes or []))
                if candidate is not None
            ],
            "detection_bbox_count": int(detection_bbox_count or 0),
            "detection_score": _safe_float(detection_score),
            "detection_message": detection_message if isinstance(detection_message, str) else None,
        }
        if isinstance(extra_metadata, dict):
            metadata.update(extra_metadata)

        return self._archiveSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera="top",
            top_zone=input_image,
            bottom_zone=None,
            top_frame=source_frame,
            bottom_frame=None,
            metadata=metadata,
        )

    def getHiveUploaderStatus(self) -> dict[str, Any]:
        return self._hive.status()

    def reloadHiveUploader(self) -> dict[str, Any]:
        return self._hive.reload()

    def backfillToHive(
        self,
        session_ids: list[str] | None = None,
        target_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._hive.backfill(TRAINING_ROOT, session_ids=session_ids, target_ids=target_ids)

    def purgeHiveQueue(
        self,
        target_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._hive.purge(target_ids=target_ids)

    def _hiveAutoBackfillLoop(self) -> None:
        """Keep local ready samples draining to Hive after restarts or relinks."""

        while True:
            time.sleep(HIVE_AUTO_BACKFILL_INTERVAL_S)
            try:
                status = self._hive.status()
                targets = status.get("targets") if isinstance(status, dict) else []
                enabled_targets = [
                    target
                    for target in targets
                    if isinstance(target, dict) and target.get("enabled")
                ]
                if not enabled_targets:
                    continue
                queued = sum(
                    int(target.get("queue_size", 0) or 0)
                    for target in enabled_targets
                    if isinstance(target.get("queue_size", 0), (int, float))
                )
                if queued >= HIVE_AUTO_BACKFILL_QUEUE_HIGH_WATERMARK:
                    continue
                self._hive.backfill(
                    TRAINING_ROOT,
                    max_samples=HIVE_AUTO_BACKFILL_BATCH_SIZE,
                )
            except Exception:
                # The uploader remains opportunistic; fresh captures still enqueue
                # directly even if one archive scan fails.
                pass

    def getHiveQueueDetails(
        self,
        *,
        target_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        target_ids = [target_id] if isinstance(target_id, str) and target_id else None
        details = self._hive.queue_details(target_ids=target_ids, limit=limit)
        teacher = self._teacherReadinessSummary(limit=limit)
        targets = details.get("targets") if isinstance(details.get("targets"), list) else []
        queued = sum(int(target.get("queue_size", 0)) for target in targets if isinstance(target, dict))
        uploading = sum(
            len(target.get("active_jobs", []))
            for target in targets
            if isinstance(target, dict) and isinstance(target.get("active_jobs"), list)
        )
        recent_uploaded = sum(
            1
            for target in targets
            if isinstance(target, dict)
            for job in target.get("recent_jobs", [])
            if isinstance(job, dict) and job.get("status") == "uploaded"
        )
        recent_failed = sum(
            1
            for target in targets
            if isinstance(target, dict)
            for job in target.get("recent_jobs", [])
            if isinstance(job, dict) and job.get("status") == "failed"
        )
        recent_retrying = sum(
            1
            for target in targets
            if isinstance(target, dict)
            for job in target.get("recent_jobs", [])
            if isinstance(job, dict) and job.get("status") == "retrying"
        )
        return {
            "ok": True,
            **details,
            "teacher": teacher,
            "totals": {
                "queued": queued,
                "uploading": uploading,
                "recent_uploaded": recent_uploaded,
                "recent_failed": recent_failed,
                "recent_retrying": recent_retrying,
                "needs_gemini": teacher["counts"]["needs_gemini"],
                "no_teacher_detection": teacher["counts"]["no_teacher_detection"],
                "bad_teacher_sample": teacher["counts"]["bad_teacher_sample"],
                "teacher_ready": teacher["counts"]["teacher_ready"],
                "other_samples": teacher["counts"]["not_teacher_sample"],
            },
        }

    def purgeSamplesByTeacherState(self, states: list[str]) -> dict[str, Any]:
        requested = {
            state
            for state in states
            if state
            in {
                "needs_gemini",
                "no_teacher_detection",
                "bad_teacher_sample",
                "teacher_ready",
                "not_teacher_sample",
            }
        }
        if not requested:
            return {"ok": False, "error": "No supported sample state was selected."}

        purged_samples = 0
        deleted_files = 0
        freed_bytes = 0

        if not TRAINING_ROOT.exists():
            return {
                "ok": True,
                "states": sorted(requested),
                "purged_samples": 0,
                "deleted_files": 0,
                "freed_bytes": 0,
            }

        root = TRAINING_ROOT.resolve()
        for session_dir in sorted(TRAINING_ROOT.iterdir(), key=lambda path: path.name):
            if not session_dir.is_dir():
                continue
            metadata_dir = session_dir / "metadata"
            if not metadata_dir.exists():
                continue
            for metadata_path in sorted(metadata_dir.glob("*.json")):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
                teacher_state = teacher_state_from_metadata(metadata)["state"]
                if teacher_state not in requested:
                    continue

                sample_id = (
                    metadata.get("sample_id")
                    if isinstance(metadata.get("sample_id"), str) and metadata.get("sample_id")
                    else metadata_path.stem
                )
                paths = self._sampleFilesForDeletion(
                    metadata,
                    session_dir=session_dir,
                    metadata_path=metadata_path,
                    sample_id=sample_id,
                )
                for path in paths:
                    try:
                        resolved = path.resolve()
                    except Exception:
                        continue
                    try:
                        resolved.relative_to(root)
                    except ValueError:
                        continue
                    if not resolved.is_file():
                        continue
                    try:
                        freed_bytes += resolved.stat().st_size
                        resolved.unlink()
                        deleted_files += 1
                    except Exception:
                        continue
                purged_samples += 1

        return {
            "ok": True,
            "states": sorted(requested),
            "purged_samples": purged_samples,
            "deleted_files": deleted_files,
            "freed_bytes": freed_bytes,
        }

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

    def _teacherReadinessSummary(self, *, limit: int = 100) -> dict[str, Any]:
        counts = {
            "teacher_ready": 0,
            "needs_gemini": 0,
            "no_teacher_detection": 0,
            "bad_teacher_sample": 0,
            "not_teacher_sample": 0,
            "invalid": 0,
        }
        recent_needs_gemini: list[dict[str, Any]] = []
        recent_ready: list[dict[str, Any]] = []
        max_items = max(1, min(500, int(limit)))

        if not TRAINING_ROOT.exists():
            return {
                "counts": counts,
                "recent_needs_gemini": [],
                "recent_ready": [],
            }

        for session_dir in sorted(TRAINING_ROOT.iterdir(), key=lambda path: path.name, reverse=True):
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            manifest = self._readJsonFile(session_dir / "manifest.json") or {}
            session_name = (
                manifest.get("session_name")
                if isinstance(manifest.get("session_name"), str) and manifest.get("session_name")
                else session_id
            )
            metadata_dir = session_dir / "metadata"
            if not metadata_dir.exists():
                continue
            metadata_paths = sorted(
                metadata_dir.glob("*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for metadata_path in metadata_paths:
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    counts["invalid"] += 1
                    continue
                teacher_state = teacher_state_from_metadata(metadata)
                state = teacher_state["state"]
                if state not in counts:
                    counts["invalid"] += 1
                    continue
                counts[state] += 1
                if state not in {
                    "needs_gemini",
                    "teacher_ready",
                    "no_teacher_detection",
                    "bad_teacher_sample",
                }:
                    continue
                if state == "needs_gemini" and len(recent_needs_gemini) >= max_items:
                    continue
                if state == "no_teacher_detection" and len(recent_needs_gemini) >= max_items:
                    continue
                if state == "bad_teacher_sample" and len(recent_needs_gemini) >= max_items:
                    continue
                if state == "teacher_ready" and len(recent_ready) >= max_items:
                    continue
                item = self._sampleQueueSummary(
                    metadata,
                    session_id=session_id,
                    session_name=session_name,
                    fallback_sample_id=metadata_path.stem,
                    teacher_state=teacher_state,
                )
                if state in {"needs_gemini", "no_teacher_detection", "bad_teacher_sample"}:
                    recent_needs_gemini.append(item)
                else:
                    recent_ready.append(item)

        return {
            "counts": counts,
            "recent_needs_gemini": recent_needs_gemini,
            "recent_ready": recent_ready,
        }

    @staticmethod
    def _sampleQueueSummary(
        metadata: dict[str, Any],
        *,
        session_id: str,
        session_name: str,
        fallback_sample_id: str,
        teacher_state: dict[str, str],
    ) -> dict[str, Any]:
        sample_id = (
            metadata.get("sample_id")
            if isinstance(metadata.get("sample_id"), str) and metadata.get("sample_id")
            else fallback_sample_id
        )
        return {
            "session_id": session_id,
            "session_name": session_name,
            "sample_id": sample_id,
            "source_role": metadata.get("source_role"),
            "capture_reason": metadata.get("capture_reason") or metadata.get("source"),
            "captured_at": _safe_float(metadata.get("captured_at")),
            "detection_algorithm": metadata.get("detection_algorithm"),
            "detection_bbox_count": (
                int(metadata.get("detection_bbox_count"))
                if isinstance(metadata.get("detection_bbox_count"), int)
                and not isinstance(metadata.get("detection_bbox_count"), bool)
                else None
            ),
            "teacher_state": teacher_state["state"],
            "teacher_label": teacher_state["label"],
            "teacher_reason": teacher_state["reason"],
            "hive_uploads": (
                metadata.get("hive_uploads")
                if isinstance(metadata.get("hive_uploads"), dict)
                else None
            ),
        }

    @staticmethod
    def _sampleFilesForDeletion(
        metadata: dict[str, Any],
        *,
        session_dir: Path,
        metadata_path: Path,
        sample_id: str,
    ) -> set[Path]:
        paths = {metadata_path}
        for key in (
            "input_image",
            "top_zone_path",
            "bottom_zone_path",
            "top_frame_path",
            "bottom_frame_path",
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                paths.add(Path(value.strip()))

        for directory in (
            session_dir / "captures",
            session_dir / "dataset" / "images",
            session_dir / "classification" / "json",
        ):
            if directory.exists():
                paths.update(directory.glob(f"{sample_id}*"))
        return paths

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
        for relative in (
            "captures",
            "metadata",
            "dataset/images",
            "classification/json",
        ):
            (session_dir / relative).mkdir(parents=True, exist_ok=True)

        self._session_id = session_id
        self._session_name = session_name.strip() if isinstance(session_name, str) and session_name.strip() else name
        self._session_dir = session_dir
        self._created_at = time.time()
        self._writeSessionManifest(session_dir)

    def _writeSessionManifest(self, session_dir: Path) -> None:
        manifest = {
            "session_id": self._session_id or session_dir.name,
            "session_name": self._session_name or session_dir.name,
            "created_at": self._created_at or time.time(),
            "processor": self._processor,
            "mode": "runtime_archive_only",
        }
        (session_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    @staticmethod
    def _readJsonFile(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _writeImage(self, path: Path, image: np.ndarray | None) -> None:
        if image is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])

    def _archiveSample(
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
    ) -> dict[str, Any]:
        sample_id = f"{int(time.time() * 1000)}-{uuid4().hex[:8]}"
        captures_dir = session_dir / "captures"
        metadata_dir = session_dir / "metadata"
        dataset_images_dir = session_dir / "dataset" / "images"

        top_zone_path = captures_dir / f"{sample_id}_top_zone.jpg"
        bottom_zone_path = captures_dir / f"{sample_id}_bottom_zone.jpg"
        top_frame_path = captures_dir / f"{sample_id}_top_full.jpg"
        bottom_frame_path = captures_dir / f"{sample_id}_bottom_full.jpg"

        self._writeImage(top_zone_path, top_zone)
        self._writeImage(bottom_zone_path, bottom_zone)
        self._writeImage(top_frame_path, top_frame)
        self._writeImage(bottom_frame_path, bottom_frame)

        preferred_path = (
            top_zone_path if preferred_camera == "top" and top_zone is not None else bottom_zone_path
        )
        if preferred_camera != "top" and bottom_zone is None and top_zone is not None:
            preferred_path = top_zone_path
            preferred_camera = "top"
        if preferred_camera != "bottom" and top_zone is None and bottom_zone is not None:
            preferred_path = bottom_zone_path
            preferred_camera = "bottom"
        if not preferred_path.exists():
            raise ValueError("No preferred tray crop was available for the sample capture.")

        dataset_image_path = dataset_images_dir / f"{sample_id}.jpg"
        dataset_image_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preferred_path, dataset_image_path)

        metadata_payload = {
            **metadata,
            "sample_id": sample_id,
            "processor": processor,
            "preferred_camera": preferred_camera,
            "captured_at": _safe_float(metadata.get("captured_at")) or time.time(),
            "archive_mode": "runtime_archive_only",
            "input_image": str(dataset_image_path),
            "top_zone_path": str(top_zone_path) if top_zone is not None else None,
            "bottom_zone_path": str(bottom_zone_path) if bottom_zone is not None else None,
            "top_frame_path": str(top_frame_path) if top_frame is not None else None,
            "bottom_frame_path": str(bottom_frame_path) if bottom_frame is not None else None,
        }
        metadata_payload["sample_payload"] = build_sample_payload(
            session_id=self._session_id or session_dir.name,
            sample_id=sample_id,
            session_name=self._session_name,
            metadata=metadata_payload,
            include_primary_asset=True,
            include_full_frame=bool(top_frame is not None or bottom_frame is not None),
            include_overlay=False,
        )

        metadata_path = metadata_dir / f"{sample_id}.json"
        metadata_path.write_text(json.dumps(metadata_payload, indent=2))

        full_frame_path = None
        for candidate_key in ("top_frame_path", "bottom_frame_path"):
            candidate_path = metadata_payload.get(candidate_key)
            if isinstance(candidate_path, str) and candidate_path:
                full_frame_path = candidate_path
                break
        self._hive.enqueue(
            session_id=self._session_id or session_dir.name,
            session_name=self._session_name,
            sample_id=sample_id,
            metadata=metadata_payload,
            image_path=str(dataset_image_path),
            full_frame_path=full_frame_path,
            overlay_path=None,
            metadata_path=str(metadata_path),
        )

        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": self._session_id,
            "session_dir": str(session_dir),
            "input_image": str(dataset_image_path),
            "message": "Sample archived locally.",
        }


_training_manager = ClassificationTrainingManager()


def getClassificationTrainingManager() -> ClassificationTrainingManager:
    return _training_manager
