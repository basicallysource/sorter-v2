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

from local_state import get_classification_training_state, set_classification_training_state
from server.hive_uploader import HiveUploader
from server.sample_payloads import build_sample_payload


TRAINING_ROOT = Path(__file__).parent.parent / "blob" / "classification_training"
DEFAULT_PROCESSOR = "local_archive"
LEGACY_PROCESSORS = {"gemini_sam"}
SUPPORTED_PROCESSORS = {DEFAULT_PROCESSOR, *LEGACY_PROCESSORS}

# Cap on how much captured imagery we keep on the local disk. Once exceeded we
# delete the oldest samples first. Default 1 GiB; the operator can change it from
# the sample-capture settings (None disables the cap entirely).
DEFAULT_LOCAL_STORAGE_CAP_BYTES = 1024 * 1024 * 1024
# Evict down to this fraction of the cap so we don't walk the whole tree on every
# single saved frame once we're sitting at the limit.
STORAGE_CAP_LOW_WATER = 0.9


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
        self._storage_cap_bytes: int | None = DEFAULT_LOCAL_STORAGE_CAP_BYTES
        self._last_usage_bytes: int | None = None
        self._hive = HiveUploader()
        self._loadPersistedConfig()

    def _loadPersistedConfig(self) -> None:
        saved = get_classification_training_state()
        if not isinstance(saved, dict):
            return

        processor = saved.get("processor")
        if isinstance(processor, str) and processor in SUPPORTED_PROCESSORS:
            self._processor = processor

        if "local_storage_cap_bytes" in saved:
            cap = saved.get("local_storage_cap_bytes")
            if isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap > 0:
                self._storage_cap_bytes = int(cap)
            else:
                self._storage_cap_bytes = None

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
                "local_storage_cap_bytes": self._storage_cap_bytes,
            }
        )

    def getStorageStatus(self) -> dict[str, Any]:
        with self._lock:
            if self._last_usage_bytes is None:
                self._last_usage_bytes = self._computeUsageBytes()
            return {
                "storage_cap_bytes": self._storage_cap_bytes,
                "storage_used_bytes": self._last_usage_bytes,
            }

    def setStorageCapBytes(self, cap_bytes: int | None) -> dict[str, Any]:
        with self._lock:
            if isinstance(cap_bytes, (int, float)) and not isinstance(cap_bytes, bool) and cap_bytes > 0:
                self._storage_cap_bytes = int(cap_bytes)
            else:
                self._storage_cap_bytes = None
            self._persistConfig()
            if self._last_usage_bytes is None:
                self._last_usage_bytes = self._computeUsageBytes()
            cap = self._storage_cap_bytes
            if cap is not None and self._last_usage_bytes > cap:
                self._evictToLowWaterLocked(cap)
            return {
                "storage_cap_bytes": self._storage_cap_bytes,
                "storage_used_bytes": self._last_usage_bytes,
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

    def _ensureSessionLocked(self) -> bool:
        if self._session_dir is None or not self._session_dir.is_dir():
            self._createSessionLocked(None)
            return True
        required_dirs = (
            self._session_dir / "captures",
            self._session_dir / "metadata",
            self._session_dir / "dataset" / "images",
            self._session_dir / "classification" / "json",
        )
        if any(not path.is_dir() for path in required_dirs):
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

    def _writeImage(self, path: Path, image: np.ndarray | None) -> None:
        if image is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])

    def _computeUsageBytes(self) -> int:
        total = 0
        if not TRAINING_ROOT.exists():
            return 0
        for path in TRAINING_ROOT.rglob("*"):
            if not path.is_file():
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def _noteWriteAndEnforceLocked(self, added_bytes: int) -> None:
        if self._last_usage_bytes is None:
            self._last_usage_bytes = self._computeUsageBytes()
        else:
            self._last_usage_bytes += max(0, added_bytes)
        cap = self._storage_cap_bytes
        if cap is None or cap <= 0:
            return
        if self._last_usage_bytes > cap:
            self._evictToLowWaterLocked(cap)

    def _evictToLowWaterLocked(self, cap: int) -> None:
        # Delete oldest sample files first until we're back under the low-water
        # mark. manifest.json is tiny and identifies the session, so it's never a
        # delete target — fully drained sessions get their dir removed wholesale.
        low_water = int(cap * STORAGE_CAP_LOW_WATER)
        entries: list[tuple[float, int, Path]] = []
        total = 0
        for path in TRAINING_ROOT.rglob("*"):
            if not path.is_file() or path.name == "manifest.json":
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

        entries.sort(key=lambda item: item[0])
        for _mtime, size, path in entries:
            if total <= low_water:
                break
            try:
                path.unlink()
            except OSError:
                continue
            total -= size

        active = self._session_dir.resolve() if self._session_dir is not None else None
        self._pruneEmptySessionDirsLocked(active)
        self._last_usage_bytes = total

    def _pruneEmptySessionDirsLocked(self, active: Path | None) -> None:
        if not TRAINING_ROOT.exists():
            return
        for session_dir in TRAINING_ROOT.iterdir():
            if not session_dir.is_dir():
                continue
            if active is not None and session_dir.resolve() == active:
                continue
            has_payload = any(
                path.is_file() and path.name != "manifest.json"
                for path in session_dir.rglob("*")
            )
            if has_payload:
                continue
            try:
                shutil.rmtree(session_dir)
            except OSError:
                continue

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
        captures_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        dataset_images_dir.mkdir(parents=True, exist_ok=True)

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

        source_role_for_geometry = metadata_payload.get("source_role")
        if isinstance(source_role_for_geometry, str) and source_role_for_geometry:
            from channel_geometry_payload import buildChannelGeometryForRole

            channel_geometry = buildChannelGeometryForRole(source_role_for_geometry)
            if channel_geometry is not None:
                metadata_payload["channel_geometry"] = channel_geometry

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
        )

        added_bytes = 0
        for written_path in (
            top_zone_path,
            bottom_zone_path,
            top_frame_path,
            bottom_frame_path,
            dataset_image_path,
            metadata_path,
        ):
            try:
                added_bytes += written_path.stat().st_size
            except OSError:
                continue
        with self._lock:
            self._noteWriteAndEnforceLocked(added_bytes)

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
