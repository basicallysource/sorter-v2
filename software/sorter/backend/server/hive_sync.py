"""Background worker that reconciles local piece history to the Hive.

Unlike the fire-and-forget sample HiveUploader, this walks a monotonic sqlite
cursor (piece_records.id / piece_images.id) against a server-held watermark:
it asks each Hive "what's the max local_id you already have for me?", then
pushes only the gap in id order. That makes months of backlog syncable without
redundant re-uploads, and — because every Hive ingest endpoint upserts by
natural key — retries and at-least-once delivery never duplicate.

Every enabled target syncs on its OWN thread with its own watermark and
backoff, so a slow or unreachable target (e.g. a local hive that 401s) can
never stall the others — each drains prod/staging/local independently.

Throughput is adaptive:
  - While a sort is running (gc.runtime_stats._is_running) uploads stay gentle,
    throttled exactly as before so they never compete with live sorting.
  - When the machine is idle, uploads blast back-to-back (network/disk bound).
A single concurrency gate caps total uploads in flight across ALL targets —
1 while sorting (identical to the old serial behavior), a few when idle — so
the worst-case load stays bounded no matter how many targets are configured.

Ordering matters: the server watermark is MAX(local_id), so a gap that gets
skipped is lost on the next restart. Each target therefore uploads strictly
serially and in id order; the gate parallelizes ACROSS targets, never within
one target's id stream.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import requests

import channel_crop_store
import piece_image_store
import piece_records
from blob_manager import getHiveConfig
from hive_telemetry import HiveTelemetryClient, telemetryAllows

log = logging.getLogger(__name__)

DATA_TYPE_RECORDS = "piece_records"
DATA_TYPE_IMAGES = "piece_images"
DATA_TYPE_CROPS = "channel_crops"
DATA_TYPE_CORRECTIONS = "piece_corrections"

RECORDS_BATCH = 500
CORRECTIONS_BATCH = 500
# Images/crops push one file per request (multipart). Small chunks while
# sorting keep each pass short and responsive to a mode change; bigger chunks
# when idle cut the per-chunk requery overhead during a backlog blast.
IMAGES_CHUNK = 10
CROPS_CHUNK = 10
IMAGES_CHUNK_IDLE = 50
CROPS_CHUNK_IDLE = 100

# Gentle throttles applied only while a sort is running — identical to the
# pre-adaptive behavior, so backlog draining never competes with live sorting
# more than it used to.
RECORDS_THROTTLE_S = 0.15
CORRECTIONS_THROTTLE_S = 0.15
IMAGES_THROTTLE_S = 0.8
CROPS_THROTTLE_S = 0.3
# Idle: standby, so upload back-to-back. The concurrency gate still bounds how
# many run at once.
IDLE_THROTTLE_S = 0.0

IDLE_POLL_S = 10.0
SERVER_DOWN_BACKOFF_S = 10.0
SERVER_DOWN_MAX_BACKOFF_S = 120.0

# Total uploads in flight across ALL targets. 1 while sorting reproduces the old
# single-threaded load exactly; a few when idle lets targets drain in parallel.
# A hard ceiling regardless of how many targets get configured later.
BUSY_MAX_CONCURRENT = 1
IDLE_MAX_CONCURRENT = 3

# Retention marking is a periodic sweep, not per-upload: coalesce it so an idle
# blast doesn't fire an UPDATE per image.
RETENTION_MARK_INTERVAL_S = 5.0


def _machineBusy(gc: Any) -> bool:
    # Gentle while a sort is running; blast when idle. Any uncertainty falls
    # back to "busy" so we never upload more aggressively than the machine can
    # afford.
    try:
        stats = getattr(gc, "runtime_stats", None)
        if stats is None:
            return True
        return bool(getattr(stats, "_is_running", True))
    except Exception:
        return True


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
        # Correction provenance from the applied Brickognize request, so a
        # correction entered on Hive can be submitted to Brickognize there.
        "brickognize_listing_id": row["brickognize_listing_id"],
        "brickognize_item_rank": row["brickognize_item_rank"],
        "brickognize_item_type": row["brickognize_item_type"],
        "brickognize_color_rank": row["brickognize_color_rank"],
        # Which service actually produced this piece's color / mold, so Hive can
        # compare provider accuracy against user corrections.
        "color_provider": row["color_provider"],
        "mold_provider": row["mold_provider"],
    }


def _correctionToPayload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "piece_uuid": row["piece_uuid"],
        "local_id": row["id"],
        "part_correct": (
            None if row["part_correct"] is None else bool(row["part_correct"])
        ),
        "color_corrected_id": row["color_corrected_id"],
        "part_feedback_submitted": bool(row["part_feedback_submitted"]),
        "color_feedback_submitted": bool(row["color_feedback_submitted"]),
        "updated_at": row["updated_at"],
        "rejection_reasons": row["rejection_reasons"],
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


def _cropToMeta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_id": row["id"],
        "channel": row["channel"],
        "ts": row["ts"],
        "captured_at": row["created_at"],
        "track_id": row["track_id"],
        "com_forward_to_exit_deg": row["com_forward_to_exit_deg"],
        "com_section": row["com_section"],
        "zone_code": row["zone_code"],
        "sharpness": row["sharpness"],
        "bbox": row["bbox"],
        "bytes": row["bytes"],
    }


class _ConcurrencyGate:
    """Caps total uploads in flight across all target threads.

    The limit is evaluated per acquire, so the same gate tightens to
    BUSY_MAX_CONCURRENT the moment a sort starts and loosens again when it
    stops — without recreating anything.
    """

    def __init__(self, busy_limit: int, idle_limit: int, busy_fn: Callable[[], bool]) -> None:
        self._busy_limit = max(1, busy_limit)
        self._idle_limit = max(1, idle_limit)
        self._busy_fn = busy_fn
        self._cond = threading.Condition()
        self._active = 0

    def _limit(self) -> int:
        return self._busy_limit if self._busy_fn() else self._idle_limit

    @contextmanager
    def slot(self) -> Iterator[None]:
        with self._cond:
            # Re-poll the limit on a timeout so a busy->idle (or idle->busy)
            # transition while waiting takes effect within a second.
            while self._active >= self._limit():
                self._cond.wait(timeout=1.0)
            self._active += 1
        try:
            yield
        finally:
            with self._cond:
                self._active -= 1
                self._cond.notify()


class _TargetSyncer:
    """Drains local history to a single Hive target on its own thread."""

    def __init__(
        self,
        gc: Any,
        target: dict[str, Any],
        gate: _ConcurrencyGate,
        mark_retention: Callable[[], None],
    ) -> None:
        self._gc = gc
        self._id = target["id"]
        self._name = target["name"]
        self._url = target["url"]
        self._gate = gate
        self._mark_retention = mark_retention
        self._client = HiveTelemetryClient(self._url, target["token"], self._id)
        self._wm: dict[str, int | None] = {
            DATA_TYPE_RECORDS: None,
            DATA_TYPE_IMAGES: None,
            DATA_TYPE_CROPS: None,
            DATA_TYPE_CORRECTIONS: None,
        }
        self._state_ok = False
        self._backoff_s = SERVER_DOWN_BACKOFF_S
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"hive-sync-{self._id[:8]}"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poke(self) -> None:
        self._wake.set()

    def watermark(self, data_type: str) -> int | None:
        return self._wm.get(data_type)

    def stateOk(self) -> bool:
        return self._state_ok

    def _loop(self) -> None:
        log.info("Hive sync enabled: %s (%s)", self._name, self._url)
        while not self._stop.is_set():
            try:
                progressed = self._runOnce()
                self._backoff_s = SERVER_DOWN_BACKOFF_S
            except Exception as exc:
                self._noteBackoff(exc)
                self._wake.wait(self._backoff_s)
                self._wake.clear()
                continue
            if progressed and not self._stop.is_set():
                continue
            self._wake.wait(IDLE_POLL_S)
            self._wake.clear()

    def _runOnce(self) -> bool:
        self._ensureState()
        # Drain crops on their own leg rather than short-circuited behind
        # records/images: piece-image capture is continuous during a run, so an
        # `or` chain would starve crops behind that backlog.
        records_or_images = self._drainRecords() or self._drainImages()
        crops = self._drainChannelCrops()
        corrections = self._drainCorrections()
        self._state_ok = True
        progressed = records_or_images or crops or corrections
        if progressed:
            self._mark_retention()
        return progressed

    def _ensureState(self) -> None:
        if self._state_ok and self._wm[DATA_TYPE_RECORDS] is not None:
            return
        state = self._client.getSyncState()
        for data_type in (
            DATA_TYPE_RECORDS,
            DATA_TYPE_IMAGES,
            DATA_TYPE_CROPS,
            DATA_TYPE_CORRECTIONS,
        ):
            raw = state.get(data_type) if isinstance(state, dict) else None
            value = raw.get("max_local_id") if isinstance(raw, dict) else 0
            self._wm[data_type] = int(value or 0)

    def _throttle(self, busy_value: float) -> None:
        delay = busy_value if _machineBusy(self._gc) else IDLE_THROTTLE_S
        if delay > 0:
            time.sleep(delay)

    def _drainRecords(self) -> bool:
        if not telemetryAllows(self._id, "piece_metadata"):
            return False
        wm = int(self._wm[DATA_TYPE_RECORDS] or 0)
        if piece_records.getMaxRecordId() <= wm:
            return False
        rows = piece_records.listRecordsAfter(wm, RECORDS_BATCH)
        if not rows:
            return False
        with self._gate.slot():
            new_max = self._client.pushPieceRecords([_recordToPayload(r) for r in rows])
        self._wm[DATA_TYPE_RECORDS] = max(wm, int(new_max), int(rows[-1]["id"]))
        self._throttle(RECORDS_THROTTLE_S)
        return True

    def _drainImages(self) -> bool:
        # Skip instead of pushing metadata-only rows: with images disabled the
        # watermark freezes here and the backlog drains if re-enabled later.
        if not telemetryAllows(self._id, "detection_images"):
            return False
        wm = int(self._wm[DATA_TYPE_IMAGES] or 0)
        if piece_image_store.getMaxImageId() <= wm:
            return False
        chunk = IMAGES_CHUNK if _machineBusy(self._gc) else IMAGES_CHUNK_IDLE
        rows = piece_image_store.listImagesAfter(wm, chunk)
        if not rows:
            return False
        for row in rows:
            if self._stop.is_set():
                break
            # Model guesses must never be uploaded as piece images — they would
            # land in Hive's labeling gallery as "this IS the piece" and poison
            # the training data. New code writes them to piece_link_images, but
            # rows from the window where they landed in piece_images get skipped
            # here (watermark still advances so the backlog drains past them).
            if row.get("source") == "link_match":
                self._wm[DATA_TYPE_IMAGES] = max(int(self._wm[DATA_TYPE_IMAGES] or 0), int(row["id"]))
                continue
            file_path = None if row["evicted_locally"] else piece_image_store.getImageFileById(row["id"])
            with self._gate.slot():
                new_max = self._client.pushPieceImage(_imageToMeta(row), file_path)
            self._wm[DATA_TYPE_IMAGES] = max(int(self._wm[DATA_TYPE_IMAGES] or 0), int(new_max), int(row["id"]))
            self._throttle(IMAGES_THROTTLE_S)
        return True

    def _drainChannelCrops(self) -> bool:
        # Gated on its own upstream_channel_crops field so crops only leave the
        # machine when the target allows it. With it off the watermark freezes
        # here and the backlog drains if it is enabled later.
        if not telemetryAllows(self._id, "upstream_channel_crops"):
            return False
        wm = int(self._wm[DATA_TYPE_CROPS] or 0)
        if channel_crop_store.getMaxCropId() <= wm:
            return False
        chunk = CROPS_CHUNK if _machineBusy(self._gc) else CROPS_CHUNK_IDLE
        rows = channel_crop_store.listCropsAfter(wm, chunk)
        if not rows:
            return False
        for row in rows:
            if self._stop.is_set():
                break
            file_path = None if row["evicted_locally"] else channel_crop_store.getCropFileById(row["id"])
            with self._gate.slot():
                new_max = self._client.pushChannelCrop(_cropToMeta(row), file_path)
            self._wm[DATA_TYPE_CROPS] = max(int(self._wm[DATA_TYPE_CROPS] or 0), int(new_max), int(row["id"]))
            self._throttle(CROPS_THROTTLE_S)
        return True

    def _drainCorrections(self) -> bool:
        # Correction edits are piece metadata, so they follow the same gate as
        # piece_records. The append-only piece_corrections log gives a clean
        # monotonic cursor; Hive upserts the latest edit per piece.
        if not telemetryAllows(self._id, "piece_metadata"):
            return False
        wm = int(self._wm[DATA_TYPE_CORRECTIONS] or 0)
        if piece_records.getMaxCorrectionId() <= wm:
            return False
        rows = piece_records.listCorrectionsAfter(wm, CORRECTIONS_BATCH)
        if not rows:
            return False
        with self._gate.slot():
            new_max = self._client.pushPieceCorrections(
                [_correctionToPayload(r) for r in rows]
            )
        self._wm[DATA_TYPE_CORRECTIONS] = max(wm, int(new_max), int(rows[-1]["id"]))
        self._throttle(CORRECTIONS_THROTTLE_S)
        return True

    def _noteBackoff(self, exc: Exception) -> None:
        self._state_ok = False  # re-fetch watermark on recovery (handles a hive DB reset)
        self._backoff_s = min(
            max(float(self._backoff_s), SERVER_DOWN_BACKOFF_S) * 1.5,
            SERVER_DOWN_MAX_BACKOFF_S,
        )
        level = "debug" if _is_transient(exc) else "warning"
        getattr(log, level)(
            "hive_sync: %s unreachable, backing off %.0fs: %s",
            self._name, self._backoff_s, exc,
        )


class HiveSyncWorker:
    def __init__(self, gc: Any) -> None:
        self._gc = gc
        self._lock = threading.Lock()
        self._syncers: dict[str, _TargetSyncer] = {}
        self._started = False
        self._gate = _ConcurrencyGate(
            BUSY_MAX_CONCURRENT, IDLE_MAX_CONCURRENT, lambda: _machineBusy(gc)
        )
        self._retention_lock = threading.Lock()
        self._last_retention = 0.0

    def start(self) -> None:
        with self._lock:
            self._started = True
            self._rebuildLocked()

    def stop(self) -> None:
        with self._lock:
            for syncer in self._syncers.values():
                syncer.stop()
            self._syncers = {}
            self._started = False

    def reload(self) -> None:
        with self._lock:
            if self._started:
                self._rebuildLocked()

    def poke(self) -> None:
        with self._lock:
            for syncer in self._syncers.values():
                syncer.poke()

    def _rebuildLocked(self) -> None:
        # Config edits are rare (a target add/remove/enable), so just tear the
        # target threads down and rebuild from fresh config. Each new thread
        # re-fetches its watermark from the server, so no progress is lost — the
        # brief overlap with an exiting thread is harmless: both push in id
        # order and Hive upserts idempotently, so no gap can open.
        for syncer in self._syncers.values():
            syncer.stop()
        self._syncers = {}
        config = getHiveConfig()
        targets = config.get("targets") if isinstance(config, dict) else None
        if not isinstance(targets, list):
            return
        for raw in targets:
            parsed = self._parseTarget(raw)
            if parsed is None:
                continue
            try:
                syncer = _TargetSyncer(self._gc, parsed, self._gate, self._markRetention)
            except Exception as exc:
                log.warning("Hive sync disabled for %s: %s", parsed["url"], exc)
                continue
            self._syncers[parsed["id"]] = syncer
            syncer.start()

    @staticmethod
    def _parseTarget(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        target_id = raw.get("id")
        url = raw.get("url")
        token = raw.get("api_token")
        if not isinstance(target_id, str) or not target_id:
            return None
        if not isinstance(url, str) or not url:
            return None
        if not isinstance(token, str) or not token:
            return None
        if not bool(raw.get("enabled", False)):
            return None
        name = raw.get("name") if isinstance(raw.get("name"), str) else url
        return {"id": target_id, "url": url, "token": token, "name": name}

    def _markRetention(self) -> None:
        now = time.time()
        with self._retention_lock:
            if now - self._last_retention < RETENTION_MARK_INTERVAL_S:
                return
            self._last_retention = now
        with self._lock:
            syncers = list(self._syncers.values())
        if not syncers:
            return

        # Stamp synced_at up to the MIN watermark across enabled targets so
        # retention only evicts a crop once EVERY hive has it — per store. A
        # target that isn't state_ok (e.g. a local hive that 401s) makes the
        # set incomplete, freezing retention rather than evicting data a broken
        # target never received.
        def _min_wm(data_type: str) -> int | None:
            watermarks: list[int] = []
            for syncer in syncers:
                wm = syncer.watermark(data_type)
                if not syncer.stateOk() or wm is None:
                    return None  # incomplete set -> freeze retention, don't evict
                watermarks.append(int(wm))
            return min(watermarks) if watermarks else None

        images_wm = _min_wm(DATA_TYPE_IMAGES)
        if images_wm is not None:
            piece_image_store.markImagesSyncedUpTo(images_wm, now)
        crops_wm = _min_wm(DATA_TYPE_CROPS)
        if crops_wm is not None:
            channel_crop_store.markSyncedUpTo(crops_wm, now)
