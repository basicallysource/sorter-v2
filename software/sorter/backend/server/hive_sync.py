"""Background worker that reconciles local piece history to the Hive.

Unlike the fire-and-forget sample HiveUploader, this walks a monotonic sqlite
cursor (piece_records.id / piece_images.id) against a server-held watermark:
it asks each Hive "what's the max local_id you already have for me?", then
pushes only the gap in id order. That makes months of backlog syncable without
redundant re-uploads, and — because every Hive ingest endpoint upserts by
natural key — retries and at-least-once delivery never duplicate.

Syncs to EVERY enabled target in the hive config, each with its own watermark,
so the same machine drains its full history into prod and staging independently.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

import piece_image_store
import piece_records
from blob_manager import getHiveConfig
from hive_telemetry import HiveTelemetryClient, telemetryAllows

log = logging.getLogger(__name__)

DATA_TYPE_RECORDS = "piece_records"
DATA_TYPE_IMAGES = "piece_images"

RECORDS_BATCH = 500
# Images push one file per request (multipart), so a small chunk per cycle keeps
# each pass short and interleaves fairly across targets.
IMAGES_CHUNK = 10

RECORDS_THROTTLE_S = 0.15
IMAGES_THROTTLE_S = 0.8
IDLE_POLL_S = 10.0

SERVER_DOWN_BACKOFF_S = 10.0
SERVER_DOWN_MAX_BACKOFF_S = 120.0


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


def _recordToPayload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "piece_uuid": row["uuid"],
        "local_id": row["id"],
        "run_id": row["run_id"],
        "seen_at": row["seen_at"],
        "recorded_at": row["recorded_at"],
        "classification_status": row["classification_status"],
        "part_id": row["part_id"],
        "part_name": row["part_name"],
        "color_id": row["color_id"],
        "color_name": row["color_name"],
        "category_id": row["category_id"],
        "confidence": row["confidence"],
        "bin_x": row["bin_x"],
        "bin_y": row["bin_y"],
        "bin_z": row["bin_z"],
        "dead": bool(row["dead"]),
        "brickognize_preview_url": row["brickognize_preview_url"],
    }


def _imageToMeta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "piece_uuid": row["piece_uuid"],
        "seq": row["seq"],
        "local_id": row["id"],
        "source": row["source"],
        "channel": row["channel"],
        "ts": row["ts"],
        "captured_at": row["created_at"],
        "sharpness": row["sharpness"],
        "bytes": row["bytes"],
        "used": row["used"],
        "excluded_from_result": row["excluded_from_result"],
        "score": row["score"],
    }


class HiveSyncWorker:
    def __init__(self, gc: Any) -> None:
        self._gc = gc
        self._lock = threading.Lock()
        self._targets: dict[str, dict[str, Any]] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._reloadConfig()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hive-sync")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def reload(self) -> None:
        with self._lock:
            self._reloadConfig()
        self._wake.set()

    def poke(self) -> None:
        self._wake.set()

    def _reloadConfig(self) -> None:
        config = getHiveConfig()
        targets = config.get("targets") if isinstance(config, dict) else None
        previous = self._targets
        self._targets = {}
        if not isinstance(targets, list):
            return
        for raw in targets:
            if not isinstance(raw, dict):
                continue
            target_id = raw.get("id")
            url = raw.get("url")
            token = raw.get("api_token")
            if not isinstance(target_id, str) or not target_id:
                continue
            if not isinstance(url, str) or not url or not isinstance(token, str) or not token:
                continue
            enabled = bool(raw.get("enabled", False))
            prev = previous.get(target_id, {})
            state: dict[str, Any] = {
                "id": target_id,
                "name": raw.get("name") if isinstance(raw.get("name"), str) else url,
                "url": url,
                "enabled": enabled,
                "client": None,
                "state_ok": False,
                "wm": dict(prev.get("wm", {DATA_TYPE_RECORDS: None, DATA_TYPE_IMAGES: None})),
                "backoff_s": float(prev.get("backoff_s", SERVER_DOWN_BACKOFF_S)),
                "retry_after": float(prev.get("retry_after", 0.0)),
                "last_error": prev.get("last_error"),
            }
            if enabled:
                try:
                    state["client"] = HiveTelemetryClient(url, token, target_id)
                    log.info("Hive sync enabled: %s (%s)", state["name"], url)
                except Exception as exc:
                    state["enabled"] = False
                    state["last_error"] = str(exc)
                    log.warning("Hive sync disabled for %s: %s", url, exc)
            self._targets[target_id] = state

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                progressed = self._runOnce()
            except Exception as exc:
                log.warning("hive_sync: unexpected loop error: %s", exc)
                progressed = False
            if progressed and not self._stop.is_set():
                continue
            self._wake.wait(IDLE_POLL_S)
            self._wake.clear()

    def _runOnce(self) -> bool:
        with self._lock:
            targets = [t for t in self._targets.values() if t["enabled"] and t["client"] is not None]
        now = time.time()
        any_progress = False
        for target in targets:
            if now < target["retry_after"]:
                continue
            try:
                self._ensureState(target)
                progressed = self._drainRecords(target) or self._drainImages(target)
                target["state_ok"] = True
                target["backoff_s"] = SERVER_DOWN_BACKOFF_S
                target["last_error"] = None
                any_progress = any_progress or progressed
            except Exception as exc:
                self._backoff(target, exc)
        if any_progress:
            self._markImageRetention(targets)
        return any_progress

    def _ensureState(self, target: dict[str, Any]) -> None:
        if target["state_ok"] and target["wm"][DATA_TYPE_RECORDS] is not None:
            return
        state = target["client"].getSyncState()
        for data_type in (DATA_TYPE_RECORDS, DATA_TYPE_IMAGES):
            raw = state.get(data_type) if isinstance(state, dict) else None
            value = raw.get("max_local_id") if isinstance(raw, dict) else 0
            target["wm"][data_type] = int(value or 0)

    def _drainRecords(self, target: dict[str, Any]) -> bool:
        if not telemetryAllows(target["id"], "piece_metadata"):
            return False
        wm = int(target["wm"][DATA_TYPE_RECORDS] or 0)
        if piece_records.getMaxRecordId() <= wm:
            return False
        rows = piece_records.listRecordsAfter(wm, RECORDS_BATCH)
        if not rows:
            return False
        new_max = target["client"].pushPieceRecords([_recordToPayload(r) for r in rows])
        target["wm"][DATA_TYPE_RECORDS] = max(wm, int(new_max), int(rows[-1]["id"]))
        time.sleep(RECORDS_THROTTLE_S)
        return True

    def _drainImages(self, target: dict[str, Any]) -> bool:
        # Skip instead of pushing metadata-only rows: with images disabled the
        # watermark freezes here and the backlog drains if re-enabled later.
        if not telemetryAllows(target["id"], "detection_images"):
            return False
        wm = int(target["wm"][DATA_TYPE_IMAGES] or 0)
        if piece_image_store.getMaxImageId() <= wm:
            return False
        rows = piece_image_store.listImagesAfter(wm, IMAGES_CHUNK)
        if not rows:
            return False
        for row in rows:
            file_path = None if row["evicted_locally"] else piece_image_store.getImageFileById(row["id"])
            new_max = target["client"].pushPieceImage(_imageToMeta(row), file_path)
            target["wm"][DATA_TYPE_IMAGES] = max(int(target["wm"][DATA_TYPE_IMAGES] or 0), int(new_max), int(row["id"]))
            time.sleep(IMAGES_THROTTLE_S)
        return True

    def _markImageRetention(self, targets: list[dict[str, Any]]) -> None:
        # Stamp synced_at up to the MIN image watermark across enabled targets so
        # retention only evicts a crop once EVERY hive has it.
        watermarks = [
            int(t["wm"][DATA_TYPE_IMAGES])
            for t in targets
            if t["state_ok"] and t["wm"][DATA_TYPE_IMAGES] is not None
        ]
        if watermarks and len(watermarks) == len(targets):
            piece_image_store.markImagesSyncedUpTo(min(watermarks), time.time())

    def _backoff(self, target: dict[str, Any], exc: Exception) -> None:
        target["state_ok"] = False  # re-fetch watermark on recovery (handles a hive DB reset)
        target["backoff_s"] = min(
            max(float(target.get("backoff_s", SERVER_DOWN_BACKOFF_S)), SERVER_DOWN_BACKOFF_S) * 1.5,
            SERVER_DOWN_MAX_BACKOFF_S,
        )
        target["retry_after"] = time.time() + target["backoff_s"]
        target["last_error"] = str(exc)
        level = "debug" if _is_transient(exc) else "warning"
        getattr(log, level)(
            "hive_sync: %s unreachable, backing off %.0fs: %s",
            target["name"], target["backoff_s"], exc,
        )
