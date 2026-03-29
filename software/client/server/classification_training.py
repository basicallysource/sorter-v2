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

if TYPE_CHECKING:
    from vision import VisionManager


TRAINING_ROOT = BLOB_DIR / "classification_training"
AUTODISTILL_ROOT = Path("/Users/mneuhaus/Workspace/LegoSorter/autodistill")
SAM2_CHECKPOINT = AUTODISTILL_ROOT / "checkpoints" / "sam2.1_hiera_small.pt"
DISTILL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "distill_segment_sample.py"
DEFAULT_PROCESSOR = "gemini_sam"


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
        self._running_task: dict[str, Any] | None = None
        self._last_task: dict[str, Any] | None = None
        self._loadPersistedConfig()
        self._worker = threading.Thread(target=self._workerLoop, daemon=True, name="classification-training-worker")
        self._worker.start()

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
        return self._enqueueSavedSample(
            session_dir=session_dir,
            processor=processor,
            preferred_camera="top",
            top_zone=input_image,
            bottom_zone=None,
            top_frame=source_frame,
            bottom_frame=None,
            metadata=metadata,
            enqueue_distill=False,
        )

    def getLibrary(self) -> dict[str, Any]:
        sessions: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []
        for session_dir in self._sessionDirs():
            manifest = self._readSessionManifest(session_dir)
            session_samples: list[dict[str, Any]] = []
            for metadata_path in sorted((session_dir / "metadata").glob("*.json"), reverse=True):
                metadata = self._readJsonFile(metadata_path)
                if not isinstance(metadata, dict):
                    continue
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
        samples.sort(key=lambda sample: float(sample.get("captured_at") or 0.0), reverse=True)
        sessions.sort(key=lambda session: float(session.get("created_at") or 0.0), reverse=True)
        return {
            "ok": True,
            "sessions": sessions,
            "samples": samples,
        }

    def getSampleDetail(self, session_id: str, sample_id: str) -> dict[str, Any]:
        session_dir = self.resolveSessionDir(session_id)
        manifest = self._readSessionManifest(session_dir)
        metadata = self._loadSampleMetadata(session_dir, sample_id)
        detail = self._sampleDetail(session_dir, metadata, manifest)
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

    def runSampleRetest(self, session_id: str, sample_id: str, *, openrouter_model: str) -> dict[str, Any]:
        from vision.gemini_sam_detector import GeminiSamDetector, normalize_openrouter_model

        session_dir = self.resolveSessionDir(session_id)
        metadata_path = session_dir / "metadata" / f"{sample_id}.json"
        metadata = self._loadSampleMetadata(session_dir, sample_id)
        image_path = self._existingSampleImagePath(metadata)
        if image_path is None:
            raise ValueError("Saved sample image is unavailable.")

        image = cv2.imread(str(image_path))
        if image is None or image.size == 0:
            raise ValueError("Saved sample image could not be read.")

        normalized_model = normalize_openrouter_model(openrouter_model)
        detector = GeminiSamDetector(normalized_model)
        detection = detector.detect(image, force=True)
        last_error = getattr(detector, "_last_error", None)

        overlay = self._annotatedDetectionOverlay(image, detection)
        retest_id = f"{int(time.time() * 1000)}-{uuid4().hex[:8]}"
        model_slug = _slugify(normalized_model)
        retest_dir = session_dir / "retests"
        retest_json_dir = retest_dir / "json"
        retest_overlay_dir = retest_dir / "overlays"
        retest_json_dir.mkdir(parents=True, exist_ok=True)
        retest_overlay_dir.mkdir(parents=True, exist_ok=True)
        result_path = retest_json_dir / f"{sample_id}__{model_slug}__{retest_id}.json"
        overlay_path = retest_overlay_dir / f"{sample_id}__{model_slug}__{retest_id}.jpg"
        self._writeImage(overlay_path, overlay)

        bboxes = list(detection.bboxes) if detection is not None else []
        bbox = detection.bbox if detection is not None else None
        payload = {
            "retest_id": retest_id,
            "sample_id": sample_id,
            "created_at": time.time(),
            "model": normalized_model,
            "found": bool(detection is not None and detection.bbox is not None),
            "bbox": list(bbox) if bbox is not None else None,
            "candidate_bboxes": [list(candidate) for candidate in bboxes],
            "bbox_count": len(bboxes),
            "score": float(detection.score) if detection is not None else None,
            "error": last_error if isinstance(last_error, str) and last_error else None,
            "result_json": str(result_path),
            "overlay_image": str(overlay_path),
        }
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
        openrouter_models: list[str],
    ) -> dict[str, Any]:
        requested_models = [
            model for model in dict.fromkeys(openrouter_models)
            if isinstance(model, str) and model.strip()
        ]
        if not requested_models:
            raise ValueError("No OpenRouter models were provided for retesting.")

        retests: list[dict[str, Any]] = []
        for model in requested_models:
            result = self.runSampleRetest(session_id, sample_id, openrouter_model=model)
            retest = result.get("retest")
            if isinstance(retest, dict):
                retests.append(retest)

        return {
            "ok": True,
            "sample_id": sample_id,
            "session_id": session_id,
            "retests": retests,
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
        self._running_task = None
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
            }
        )
        return detail

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

        task = {
            "task_id": uuid4().hex,
            "sample_id": sample_id,
            "session_id": self._session_id,
            "session_dir": str(session_dir),
            "processor": processor,
            "input_image": str(dataset_image_path),
            "result_json": str(distilled_json_dir / f"{sample_id}.json"),
            "overlay_image": str(distilled_overlay_dir / f"{sample_id}.jpg"),
            "yolo_label": str(dataset_labels_dir / f"{sample_id}.txt"),
            "metadata_path": str(metadata_path),
            "queued_at": time.time(),
        }
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
            with self._lock:
                self._running_task = {
                    "task_id": task["task_id"],
                    "sample_id": task["sample_id"],
                    "status": "running",
                    "started_at": time.time(),
                    "processor": task["processor"],
                }
            try:
                result = self._runTask(task)
                with self._lock:
                    self._completed += 1
                    self._last_task = {
                        "task_id": task["task_id"],
                        "sample_id": task["sample_id"],
                        "status": "completed",
                        "finished_at": time.time(),
                        "processor": task["processor"],
                        "result": result,
                    }
            except Exception as exc:
                with self._lock:
                    self._failed += 1
                    self._last_task = {
                        "task_id": task["task_id"],
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
                    self._running_task = None

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
        ]
        proc = subprocess.run(
            command,
            cwd=str(AUTODISTILL_ROOT),
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
