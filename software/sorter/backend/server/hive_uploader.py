"""Background uploader that forwards archived samples to Hive."""

from __future__ import annotations

from collections import deque
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

import requests

from blob_manager import getHiveConfig
from hive_telemetry import HiveTelemetryClient, TelemetryBlocked, telemetryAllows
from server.sample_payloads import build_sample_payload

log = logging.getLogger(__name__)

UPLOAD_MAX_RETRIES = 3
UPLOAD_RETRY_BASE_S = 2.0
UPLOAD_THROTTLE_S = 0.8
HEARTBEAT_INTERVAL_S = 30.0
# How often the heartbeat also carries a full machine-specs snapshot. The first
# heartbeat after start always sends one (so every restart lands a fresh
# timestamped report), then only every half hour to keep the history table from
# growing on each keep-alive. The server hash-dedupes anyway. When the snapshot
# is still incomplete because hardware hasn't finished coming up (no controller
# boards discovered yet), retry on the shorter interval until it fills in.
SPECS_INTERVAL_S = 1800.0
SPECS_RETRY_INTERVAL_S = 60.0
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
        self._reload_config()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="hive-uploader")
        self._worker.start()
        self._specs_next_at = 0.0  # 0 => send specs on the first heartbeat
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="hive-heartbeat",
        )
        self._heartbeat_thread.start()

    def _reload_config(self) -> None:
        config = getHiveConfig()
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
                    state["client"] = HiveTelemetryClient(url, token, target_id)
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

    def has_enabled_targets(self) -> bool:
        with self._lock:
            return any(
                target.get("enabled") and target.get("client") is not None
                for target in self._targets.values()
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

    def _resolve_upload_target_ids(self, target_ids: list[str] | None) -> list[str]:
        with self._lock:
            resolved = self._resolve_target_ids_locked(target_ids)
        return [
            target_id
            for target_id in resolved
            if telemetryAllows(target_id, "detection_images")
        ]

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
        target_ids: list[str] | None = None,
    ) -> None:
        resolved_target_ids = self._resolve_upload_target_ids(target_ids)
        if not resolved_target_ids:
            return
        with self._lock:
            for target_id in resolved_target_ids:
                target = self._targets.get(target_id)
                if target is not None:
                    target["queued"] = int(target.get("queued", 0)) + 1

        for target_id in resolved_target_ids:
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
                    "queued_at": time.time(),
                }
            )

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
        target_ids: list[str] | None = None,
    ) -> None:
        resolved_target_ids = self._resolve_upload_target_ids(target_ids)
        if not resolved_target_ids:
            return
        with self._lock:
            for target_id in resolved_target_ids:
                target = self._targets.get(target_id)
                if target is not None:
                    target["queued"] = int(target.get("queued", 0)) + 1

        for target_id in resolved_target_ids:
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
                    "queued_at": time.time(),
                }
            )

    def backfill(
        self,
        training_root: Path,
        session_ids: list[str] | None = None,
        target_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved_target_ids = self._resolve_upload_target_ids(target_ids)
        if not resolved_target_ids:
            return {"ok": False, "error": "No enabled Hive target allows detection image uploads."}
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
                    target_ids=resolved_target_ids,
                )
                queued += 1

        return {
            "ok": True,
            "queued": queued,
            "skipped": skipped,
            "errors": errors,
            "samples_scanned": samples_scanned,
            "sessions_scanned": len(session_dirs),
            "target_count": len(resolved_target_ids),
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

            # Build the specs snapshot at most once per cycle (identical across
            # targets); the client drops it per-target if the field is off.
            machine_specs = None
            if heartbeat_targets and time.time() >= self._specs_next_at:
                machine_specs = self._collect_machine_specs()
                complete = bool(machine_specs and machine_specs.get("controller_boards"))
                self._specs_next_at = time.time() + (SPECS_INTERVAL_S if complete else SPECS_RETRY_INTERVAL_S)

            for target_id, target_name, client in heartbeat_targets:
                try:
                    reachable = client.heartbeat(machine_specs=machine_specs)
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

    @staticmethod
    def _collect_machine_specs() -> dict[str, Any] | None:
        try:
            from machine_specs import buildMachineSpecs

            return buildMachineSpecs()
        except Exception as exc:
            log.debug("Machine specs collection failed: %s", exc)
            return None

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
            elif operation == "upload":
                log.warning("Hive upload skipped: image not found %s", candidate)
                with self._lock:
                    self._decrement_queue_locked(target_id)
                return
        elif operation == "upload":
            log.warning("Hive upload skipped: missing image path for %s/%s", job.get("session_id"), job.get("sample_id"))
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

        if not telemetryAllows(target_id, "full_frames"):
            full_frame_path = None
            overlay_path = None

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
                self._decrement_queue_locked(target_id)
                return

            retry_after = float(target.get("retry_after", 0.0))
            if retry_after > time.time():
                self._queue.put(job)
                return

            client = target["client"]
            target_name = target["name"]

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
                    client.updateSample(**request_kwargs)
                else:
                    if image_path is None:
                        raise FileNotFoundError("Upload job is missing the primary image path.")
                    client.uploadSample(**request_kwargs)  # type: ignore[arg-type]
                with self._lock:
                    target = self._targets.get(target_id)
                    if target is not None:
                        target["uploaded"] = int(target.get("uploaded", 0)) + 1
                        target["last_error"] = None
                        target["server_reachable"] = True
                        target["retry_after"] = 0.0
                        target["backoff_s"] = SERVER_DOWN_BACKOFF_S
                        self._decrement_queue_locked(target_id)
                return
            except TelemetryBlocked as exc:
                # The field was toggled off after this job was queued — drop
                # it silently, matching what enqueue() would have done.
                with self._lock:
                    self._decrement_queue_locked(target_id)
                log.debug("Hive upload dropped for %s/%s: %s", job["session_id"], job["sample_id"], exc)
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
