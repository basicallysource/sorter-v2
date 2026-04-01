from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import cv2
import numpy as np

from blob_manager import BLOB_DIR, getClassificationTrainingConfig, setClassificationTrainingConfig
from server.sorthive_uploader import SortHiveUploader

if TYPE_CHECKING:
    from vision import VisionManager


TRAINING_ROOT = BLOB_DIR / "classification_training"
DEFAULT_PROCESSOR = "local_archive"
LEGACY_PROCESSORS = {"gemini_sam"}
SUPPORTED_PROCESSORS = {DEFAULT_PROCESSOR, *LEGACY_PROCESSORS}


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
    SortHive, the sorter only keeps the lightweight archival piece that runtime
    code still depends on.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vision_manager: VisionManager | None = None
        self._processor = DEFAULT_PROCESSOR
        self._session_id: str | None = None
        self._session_name: str | None = None
        self._session_dir: Path | None = None
        self._created_at: float | None = None
        self._sorthive = SortHiveUploader()
        self._loadPersistedConfig()

    def _loadPersistedConfig(self) -> None:
        saved = getClassificationTrainingConfig()
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
        setClassificationTrainingConfig(
            {
                "processor": self._processor,
                "session_id": self._session_id,
                "session_name": self._session_name,
                "session_dir": str(self._session_dir) if self._session_dir is not None else None,
                "created_at": self._created_at,
            }
        )

    def setVisionManager(self, manager: VisionManager | None) -> None:
        with self._lock:
            self._vision_manager = manager

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
        return self._archiveSample(
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
        classification_dir = session_dir / "classification"
        classification_json_dir = classification_dir / "json"
        classification_json_dir.mkdir(parents=True, exist_ok=True)

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
            metadata_path.write_text(json.dumps(metadata, indent=2))

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

    def getSortHiveUploaderStatus(self) -> dict[str, Any]:
        return self._sorthive.status()

    def reloadSortHiveUploader(self) -> dict[str, Any]:
        return self._sorthive.reload()

    def backfillToSortHive(
        self,
        session_ids: list[str] | None = None,
        target_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._sorthive.backfill(TRAINING_ROOT, session_ids=session_ids, target_ids=target_ids)

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

        metadata_path = metadata_dir / f"{sample_id}.json"
        metadata_path.write_text(json.dumps(metadata_payload, indent=2))

        full_frame_path = None
        for candidate_key in ("top_frame_path", "bottom_frame_path"):
            candidate_path = metadata_payload.get(candidate_key)
            if isinstance(candidate_path, str) and candidate_path:
                full_frame_path = candidate_path
                break
        self._sorthive.enqueue(
            session_id=self._session_id or session_dir.name,
            session_name=self._session_name,
            sample_id=sample_id,
            metadata=metadata_payload,
            image_path=str(dataset_image_path),
            full_frame_path=full_frame_path,
            overlay_path=None,
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
