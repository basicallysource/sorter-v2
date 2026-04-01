"""Background uploader that forwards archived samples to SortHive."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

import requests

from blob_manager import getSortHiveConfig

log = logging.getLogger(__name__)

UPLOAD_MAX_RETRIES = 3
UPLOAD_RETRY_BASE_S = 2.0
UPLOAD_THROTTLE_S = 0.8
HEARTBEAT_INTERVAL_S = 30.0
SERVER_DOWN_BACKOFF_S = 10.0
SERVER_DOWN_MAX_BACKOFF_S = 120.0


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


class _SortHiveClient:
    def __init__(self, api_url: str, api_token: str) -> None:
        self._url = api_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_token}"

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
        ]:
            if value is not None:
                metadata[key] = value
        if extra_metadata:
            metadata["extra_metadata"] = extra_metadata

        handles: list[Any] = []
        try:
            image_fh = open(image_path, "rb")
            handles.append(image_fh)
            files: dict[str, Any] = {
                "image": (image_path.name, image_fh, "image/jpeg"),
            }
            if full_frame_path and full_frame_path.exists():
                full_frame_fh = open(full_frame_path, "rb")
                handles.append(full_frame_fh)
                files["full_frame"] = (full_frame_path.name, full_frame_fh, "image/jpeg")
            if overlay_path and overlay_path.exists():
                overlay_fh = open(overlay_path, "rb")
                handles.append(overlay_fh)
                files["overlay"] = (overlay_path.name, overlay_fh, "image/jpeg")

            response = self._session.post(
                f"{self._url}/api/machine/upload",
                data={"metadata": json.dumps(metadata)},
                files=files,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        finally:
            for handle in handles:
                handle.close()

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


class SortHiveUploader:
    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._client: _SortHiveClient | None = None
        self._enabled = False
        self._uploaded = 0
        self._failed = 0
        self._requeued = 0
        self._last_error: str | None = None
        self._server_reachable = True
        self._reload_config()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="sorthive-uploader")
        self._worker.start()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="sorthive-heartbeat",
        )
        self._heartbeat_thread.start()

    def _reload_config(self) -> None:
        config = getSortHiveConfig()
        if not isinstance(config, dict):
            self._enabled = False
            self._client = None
            return

        enabled = bool(config.get("enabled", False))
        url = config.get("url", "")
        token = config.get("api_token", "")
        if not enabled or not isinstance(url, str) or not url or not isinstance(token, str) or not token:
            self._enabled = False
            self._client = None
            return

        try:
            self._client = _SortHiveClient(url, token)
            self._enabled = True
            self._server_reachable = True
            log.info("SortHive uploader enabled: %s", url)
        except Exception as exc:
            log.warning("SortHive uploader disabled (client init failed): %s", exc)
            self._enabled = False
            self._client = None
            self._last_error = str(exc)

    def reload(self) -> dict[str, Any]:
        with self._lock:
            self._reload_config()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "server_reachable": self._server_reachable,
                "queue_size": self._queue.qsize(),
                "uploaded": self._uploaded,
                "failed": self._failed,
                "requeued": self._requeued,
                "last_error": self._last_error,
            }

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
    ) -> None:
        with self._lock:
            if not self._enabled:
                return
        self._queue.put(
            {
                "session_id": session_id,
                "session_name": session_name,
                "sample_id": sample_id,
                "metadata": metadata,
                "image_path": image_path,
                "full_frame_path": full_frame_path,
                "overlay_path": overlay_path,
                "queued_at": time.time(),
            }
        )

    def backfill(self, training_root: Path, session_ids: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            if not self._enabled:
                return {"ok": False, "error": "SortHive uploader is not enabled."}
        if not training_root.exists():
            return {"ok": False, "error": "Training root does not exist."}

        queued = 0
        skipped = 0
        errors = 0
        samples_scanned = 0
        if session_ids:
            session_dirs = [training_root / session_id for session_id in session_ids if (training_root / session_id).is_dir()]
        else:
            session_dirs = sorted([path for path in training_root.iterdir() if path.is_dir()], key=lambda path: path.name)

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
            for metadata_path in sorted(metadata_dir.glob("*.json")):
                samples_scanned += 1
                try:
                    metadata = json.loads(metadata_path.read_text())
                except Exception:
                    errors += 1
                    continue
                if not isinstance(metadata, dict):
                    errors += 1
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

                self.enqueue(
                    session_id=session_id,
                    session_name=session_name,
                    sample_id=sample_id,
                    metadata=metadata,
                    image_path=str(image_path),
                    full_frame_path=str(full_frame_path) if full_frame_path is not None else None,
                    overlay_path=str(overlay_path) if overlay_path is not None else None,
                )
                queued += 1

        return {
            "ok": True,
            "queued": queued,
            "skipped": skipped,
            "errors": errors,
            "samples_scanned": samples_scanned,
            "sessions_scanned": len(session_dirs),
        }

    def _heartbeat_loop(self) -> None:
        while True:
            time.sleep(HEARTBEAT_INTERVAL_S)
            with self._lock:
                if not self._enabled or self._client is None:
                    continue
                client = self._client
            try:
                reachable = client.heartbeat()
                with self._lock:
                    was_down = not self._server_reachable
                    self._server_reachable = reachable
                if reachable and was_down:
                    log.info("SortHive server is back online")
                elif not reachable and not was_down:
                    log.warning("SortHive server is unreachable")
            except Exception:
                with self._lock:
                    self._server_reachable = False

    def _worker_loop(self) -> None:
        down_backoff = SERVER_DOWN_BACKOFF_S
        while True:
            job = self._queue.get()
            if job is None:
                return
            with self._lock:
                if not self._enabled or self._client is None:
                    continue
                reachable = self._server_reachable
            if not reachable:
                self._queue.put(job)
                time.sleep(down_backoff)
                down_backoff = min(down_backoff * 1.5, SERVER_DOWN_MAX_BACKOFF_S)
                continue
            down_backoff = SERVER_DOWN_BACKOFF_S
            self._process_job(job)
            time.sleep(UPLOAD_THROTTLE_S)

    def _process_job(self, job: dict[str, Any]) -> None:
        image_path = Path(job["image_path"])
        if not image_path.exists():
            log.warning("SortHive upload skipped: image not found %s", image_path)
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
        }
        extra_metadata = {key: value for key, value in metadata.items() if key not in skip_keys and value is not None}

        for attempt in range(1, UPLOAD_MAX_RETRIES + 1):
            try:
                assert self._client is not None
                self._client.upload_sample(
                    source_session_id=job["session_id"],
                    local_sample_id=job["sample_id"],
                    image_path=image_path,
                    full_frame_path=full_frame_path,
                    overlay_path=overlay_path,
                    source_role=metadata.get("source_role"),
                    capture_reason=metadata.get("capture_reason") or metadata.get("source"),
                    captured_at=self._format_timestamp(metadata.get("captured_at")),
                    session_name=job.get("session_name"),
                    detection_algorithm=metadata.get("detection_algorithm"),
                    detection_bboxes=(
                        _normalize_bbox_list_payload(metadata.get("detection_bboxes"))
                        or _normalize_bbox_list_payload(metadata.get("detection_bbox"))
                    ),
                    detection_count=_safe_int(metadata.get("detection_bbox_count")),
                    detection_score=_safe_float(metadata.get("detection_score")),
                    extra_metadata=extra_metadata or None,
                )
                with self._lock:
                    self._uploaded += 1
                    self._last_error = None
                    self._server_reachable = True
                return
            except Exception as exc:
                if _is_transient(exc):
                    with self._lock:
                        self._server_reachable = False
                        self._requeued += 1
                        self._last_error = f"Server unreachable: {exc}"
                    self._queue.put(job)
                    return
                if attempt < UPLOAD_MAX_RETRIES:
                    time.sleep(UPLOAD_RETRY_BASE_S * (2 ** (attempt - 1)))
                    continue
                with self._lock:
                    self._failed += 1
                    self._last_error = str(exc)
                log.error(
                    "SortHive upload failed after %d attempts: %s/%s: %s",
                    UPLOAD_MAX_RETRIES,
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
