"""Background worker that sends everything this machine keeps for Hive.

Each kind of data is a leg with a cursor (see sync_seq.py for the one rule):
piece records and piece images, which change after they are written, go by
sync_seq; piece predictions, channel crops, control-data segments and training
samples, which never change, go by id. Hive keeps the highest value it
accepted per data type ("what's the max local_id you already have for me?"),
and the worker sends only what is above it, in cursor order, so months of
backlog sync without re-uploads, and because every Hive ingest endpoint
upserts by natural key, retries and at-least-once delivery never duplicate.

Every enabled target syncs on its OWN thread with its own watermarks and
backoff, so a slow or unreachable target (e.g. a local hive that 401s) can
never stall the others.

Every leg runs every pass, in the order below, and a leg that has nothing to
send, is out of budget, or is paused never holds up the next one. Two lanes:
table rows (records, predictions) are small and always go; everything that
carries a file draws on a per-target budget of bytes and files per minute that
the target's Hive sets (hive_limits). A file leg sends at most FILES_PER_PASS
files and then lets the next leg have its turn. When nothing moved, the worker
waits, for the budget to refill if that is what stopped it, else IDLE_POLL_S.

The throttle is the budget plus one concurrency gate across ALL targets: 1
upload in flight while a sort is running, a few when idle. There are no
per-file sleeps.

Errors: a connection failure, a 5xx, a 429 or an auth failure backs the whole
target off (10 s growing to 120 s; a 429 waits at least its Retry-After). A
Hive that answers 404/405 for one leg (not updated yet) turns that leg off for
UNSUPPORTED_RETRY_S; any other 4xx turns it off for LEG_ERROR_RETRY_S. The
other legs carry on either way.

A training-sample backlog larger than SAMPLES_BACKLOG_MAX is thinned from the
oldest end, evenly across cameras: an old frame is worth little next to
keeping up, and no camera is starved for another.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import requests

import channel_crop_store
import hive_limits
import piece_image_store
import piece_predictions
import piece_records
import control_data_store
import sample_store
from hive_telemetry import HiveTelemetryClient, TelemetryBlocked, getTargetTelemetrySettings, telemetryAllows
from local_state import get_hive_config

log = logging.getLogger(__name__)

DATA_TYPE_RECORDS = "piece_records"
DATA_TYPE_PREDICTIONS = "piece_predictions"
DATA_TYPE_IMAGES = "piece_images"
DATA_TYPE_SAMPLES = "samples"
DATA_TYPE_CROPS = "channel_crops"
DATA_TYPE_CONTROL_DATA = "control_data_segments"
# Leg order. Samples (a few a minute) go before crops, which can hold a backlog
# of tens of thousands.
DATA_TYPES = (
    DATA_TYPE_RECORDS,
    DATA_TYPE_PREDICTIONS,
    DATA_TYPE_IMAGES,
    DATA_TYPE_SAMPLES,
    DATA_TYPE_CROPS,
    DATA_TYPE_CONTROL_DATA,
)
# The telemetry field each data type rides on. With it off for a target, that
# leg's watermark freezes and its backlog drains if it is turned on again.
TELEMETRY_FIELD = {
    DATA_TYPE_RECORDS: "piece_metadata",
    DATA_TYPE_PREDICTIONS: "piece_metadata",
    DATA_TYPE_IMAGES: "detection_images",
    DATA_TYPE_SAMPLES: "full_frames",
    DATA_TYPE_CROPS: "upstream_channel_crops",
    DATA_TYPE_CONTROL_DATA: "feeder_dynamics",
}

# Table rows per request.
ROWS_BATCH = 500
# Files a file leg sends per pass before the next leg gets its turn.
FILES_PER_PASS = 20
# Most samples kept waiting for a target; beyond it the oldest are skipped,
# evenly across cameras.
SAMPLES_BACKLOG_MAX = 200
# Most sample rows read in one pass (the skipped ones included).
SAMPLES_FETCH_MAX = 1000

IDLE_POLL_S = 10.0
# Shortest wait for the budget to refill, so a nearly-full bucket is not polled
# in a tight loop.
MIN_BUDGET_WAIT_S = 0.5
# A Hive that refuses a newer endpoint (404/405: not updated yet) is asked again
# after this long, so a sorter updated before its Hive starts sending once the
# Hive catches up, without a restart.
UNSUPPORTED_RETRY_S = 1800.0
# A leg whose request Hive refuses for another reason (a 4xx) waits this long
# before it tries again; the other legs carry on.
LEG_ERROR_RETRY_S = 600.0
SERVER_DOWN_BACKOFF_S = 10.0
SERVER_DOWN_MAX_BACKOFF_S = 120.0

# Total uploads in flight across ALL targets: 1 while sorting, a few when idle
# so targets drain in parallel. A hard ceiling regardless of how many targets
# get configured later.
BUSY_MAX_CONCURRENT = 1
IDLE_MAX_CONCURRENT = 3

# Retention marking is a periodic sweep, not per-upload: coalesce it so an idle
# blast doesn't fire an UPDATE per image.
RETENTION_MARK_INTERVAL_S = 5.0

# A watermark for a data type a target does not take (its telemetry field is
# off): it never holds retention back.
NOT_WANTED = 2**62


def _machineBusy(gc: Any) -> bool:
    # One upload in flight while a sort is running; a few when idle. Any
    # uncertainty falls back to "busy" so we never upload more aggressively
    # than the machine can afford.
    try:
        stats = getattr(gc, "runtime_stats", None)
        if stats is None:
            return True
        return bool(getattr(stats, "_is_running", True))
    except Exception:
        return True


def _retryAfterS(exc: Exception) -> float | None:
    """Seconds a 429 asks to wait (Retry-After in seconds), or None."""
    if not isinstance(exc, requests.HTTPError) or exc.response is None or exc.response.status_code != 429:
        return None
    try:
        return max(0.0, float(exc.response.headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return None


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
        "sync_seq": row["sync_seq"],
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
        "color_confidence": row["color_confidence"],
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
        # The machine operator's verdict, whole: Hive stores it as the machine's
        # own, apart from any verdict a Hive labeler gives.
        "part_correct": None if row["part_correct"] is None else bool(row["part_correct"]),
        "color_corrected_id": row["color_corrected_id"],
        "part_feedback_submitted": bool(row["part_feedback_submitted"]),
        "color_feedback_submitted": bool(row["color_feedback_submitted"]),
        "correction_updated_at": row["correction_updated_at"],
        "rejection_reasons": list(row["rejection_reasons"]),
    }


def _predictionToPayload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_id": row["id"],
        "piece_uuid": row["piece_uuid"],
        "request": row["request"],
        "provider": row["provider"],
        "model": row["model"],
        "kind": row["kind"],
        "rank": row["rank"],
        "value_id": row["value_id"],
        "value_name": row["value_name"],
        "score": row["score"],
        "applied": bool(row["applied"]),
        "created_at": row["created_at"],
    }


def _imageToMeta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "piece_uuid": row["piece_uuid"],
        "seq": row["seq"],
        "local_id": row["id"],
        "sync_seq": row["sync_seq"],
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


def _controlSegmentToMeta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_id": row["id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "records": row["records"],
        "bytes": row["bytes"],
        "machine_setup": row["machine_setup"],
        "feeder_mode": row["feeder_mode"],
        "classification_mode": row["classification_mode"],
        "autotune_mode": row["autotune_mode"],
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


def _sampleToMeta(row: dict[str, Any]) -> dict[str, Any]:
    meta = row["meta"]
    detection = meta.get("detection") or {}
    bboxes = detection.get("candidate_bboxes") or ([detection["bbox"]] if detection.get("bbox") else None)
    return {
        "local_id": row["id"],
        # Hive files samples into upload sessions; the sorter's samples all
        # belong to one standing session per machine.
        "source_session_id": "sample-capture",
        "local_sample_id": str(row["id"]),
        "source_role": row["camera"],
        "captured_at": row["captured_at"],
        "capture_reason": meta.get("capture_reason"),
        "bytes": row["bytes"],
        "detection_algorithm": detection.get("algorithm"),
        "detection_bboxes": bboxes,
        "detection_count": detection.get("count"),
        "detection_score": detection.get("score"),
        "channel_geometry": meta.get("channel_geometry"),
        "camera": meta.get("camera"),
        "lamp": meta.get("lamp"),
        "software": meta.get("software"),
        "extra_metadata": {
            "width": row["width"],
            "height": row["height"],
            "detection_scope": meta.get("detection_scope"),
            "detection": detection,
            "channel_geometry_matches_frame": meta.get("channel_geometry_matches_frame"),
        },
    }


def _evenDrops(waiting: dict[str, int], keep_total: int) -> dict[str, int]:
    """How many of each camera's oldest waiting samples to skip so at most
    keep_total wait in all, sharing what is kept evenly: a camera with fewer
    waiting than its share keeps them all and its leftover share goes to the
    others."""
    if sum(waiting.values()) <= keep_total:
        return {}
    drops: dict[str, int] = {}
    remaining = keep_total
    cameras = sorted(waiting, key=lambda camera: waiting[camera])
    for i, camera in enumerate(cameras):
        share = remaining // (len(cameras) - i)
        keep = min(waiting[camera], share)
        remaining -= keep
        if waiting[camera] > keep:
            drops[camera] = waiting[camera] - keep
    return drops


class _UploadBudget:
    """Bytes and files per minute for one target's file uploads, as a token
    bucket holding at most one minute's worth. A file larger than a whole
    minute's bytes still goes once the bucket is full, so nothing is stuck."""

    def __init__(self) -> None:
        self._bytes = 0.0
        self._files = 0.0
        self._at = time.monotonic()
        self.bytes_per_minute = 0
        self.files_per_minute = 0

    def setLimits(self, bytes_per_minute: int, files_per_minute: int) -> None:
        first = self.bytes_per_minute == 0
        self.bytes_per_minute = max(1, int(bytes_per_minute))
        self.files_per_minute = max(1, int(files_per_minute))
        if first:
            self._bytes, self._files = float(self.bytes_per_minute), float(self.files_per_minute)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed_min = (now - self._at) / 60.0
        self._at = now
        self._bytes = min(float(self.bytes_per_minute), self._bytes + elapsed_min * self.bytes_per_minute)
        self._files = min(float(self.files_per_minute), self._files + elapsed_min * self.files_per_minute)

    def take(self, nbytes: int) -> bool:
        self._refill()
        full = self._bytes >= self.bytes_per_minute
        if self._files < 1.0 or (self._bytes < nbytes and not full):
            return False
        self._files -= 1.0
        self._bytes -= min(float(nbytes), self._bytes)
        return True

    def waitS(self, nbytes: int) -> float:
        """Seconds until take(nbytes) can succeed."""
        self._refill()
        need_files = max(0.0, 1.0 - self._files) / self.files_per_minute * 60.0
        need_bytes = max(0.0, min(float(nbytes), float(self.bytes_per_minute)) - self._bytes)
        return max(need_files, need_bytes / self.bytes_per_minute * 60.0)

    def status(self) -> dict[str, Any]:
        self._refill()
        return {
            "bytes_per_minute": self.bytes_per_minute,
            "files_per_minute": self.files_per_minute,
            "bytes_available": int(self._bytes),
            "files_available": int(self._files),
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
        self._wm: dict[str, int | None] = {data_type: None for data_type in DATA_TYPES}
        # Until when a leg is off (monotonic), and why: "unsupported" (the
        # target 404s its endpoint) or the error that stopped it.
        self._paused_until: dict[str, float] = {data_type: 0.0 for data_type in DATA_TYPES}
        self._paused_why: dict[str, str] = {}
        self._budget = _UploadBudget()
        # Set by a file leg the budget stopped this pass: how long until it
        # could send again.
        self._budget_wait_s: float | None = None
        self._last_error: str | None = None
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

    def watermark(self, data_type: str) -> int | None:
        return self._wm.get(data_type)

    def stateOk(self) -> bool:
        return self._state_ok

    def retentionWatermarks(self) -> dict[str, int | None]:
        """Per data type, how far this target is known to have everything: its
        watermark, NOT_WANTED for a type it does not take, None while its state
        is unknown."""
        settings = getTargetTelemetrySettings(self._id)
        out: dict[str, int | None] = {}
        for data_type in DATA_TYPES:
            if not settings.get(TELEMETRY_FIELD[data_type], False):
                out[data_type] = NOT_WANTED
            elif not self._state_ok or self._wm.get(data_type) is None:
                out[data_type] = None
            else:
                out[data_type] = int(self._wm[data_type])
        return out

    def status(self) -> dict[str, Any]:
        """For the Hive settings page: how far behind each kind of data is."""
        def waiting(data_type: str, count: Callable[[int], int]) -> int | None:
            wm = self._wm.get(data_type)
            if wm is None:
                return None
            try:
                return max(0, count(int(wm)))
            except Exception:
                return None

        now = time.monotonic()
        return {
            "state_ok": self._state_ok,
            "backoff_s": self._backoff_s if not self._state_ok else 0.0,
            "last_error": self._last_error,
            "waiting": {
                DATA_TYPE_RECORDS: waiting(DATA_TYPE_RECORDS, piece_records.countRecordsAfter),
                DATA_TYPE_PREDICTIONS: waiting(DATA_TYPE_PREDICTIONS, lambda wm: piece_predictions.getMaxId() - wm),
                DATA_TYPE_IMAGES: waiting(DATA_TYPE_IMAGES, piece_image_store.countImagesAfter),
                DATA_TYPE_CROPS: waiting(DATA_TYPE_CROPS, lambda wm: channel_crop_store.getMaxCropId() - wm),
                DATA_TYPE_CONTROL_DATA: waiting(DATA_TYPE_CONTROL_DATA, lambda wm: control_data_store.getMaxSegmentId() - wm),
                DATA_TYPE_SAMPLES: waiting(DATA_TYPE_SAMPLES, lambda wm: sample_store.getMaxSampleId() - wm),
            },
            "unsupported": [
                data_type
                for data_type in DATA_TYPES
                if self._paused_until[data_type] > now and self._paused_why.get(data_type) == "unsupported"
            ],
            "upload_budget": self._budget.status(),
        }

    def _loop(self) -> None:
        log.info("Hive sync enabled: %s (%s)", self._name, self._url)
        while not self._stop.is_set():
            try:
                progressed = self._runOnce()
                self._backoff_s = SERVER_DOWN_BACKOFF_S
                self._last_error = self._legError()
            except Exception as exc:
                self._noteBackoff(exc)
                self._wake.wait(self._backoff_s)
                self._wake.clear()
                continue
            if progressed and not self._stop.is_set():
                continue
            wait = IDLE_POLL_S
            if self._budget_wait_s is not None:
                wait = min(wait, max(MIN_BUDGET_WAIT_S, self._budget_wait_s))
            self._wake.wait(wait)
            self._wake.clear()

    def _legs(self) -> tuple[tuple[str, Callable[[], bool]], ...]:
        return (
            (DATA_TYPE_RECORDS, self._drainRecords),
            (DATA_TYPE_PREDICTIONS, self._drainPredictions),
            (DATA_TYPE_IMAGES, self._drainImages),
            (DATA_TYPE_SAMPLES, self._drainSamples),
            (DATA_TYPE_CROPS, self._drainChannelCrops),
            (DATA_TYPE_CONTROL_DATA, self._drainControlData),
        )

    def _runOnce(self) -> bool:
        """One pass over every leg. True when anything was sent."""
        self._ensureState()
        limits = hive_limits.targetLimits(self._id)
        self._budget.setLimits(int(limits["upload_bytes_per_minute"]), int(limits["upload_files_per_minute"]))
        self._budget_wait_s = None
        progressed = False
        for data_type, drain in self._legs():
            if self._stop.is_set():
                break
            if self._paused_until[data_type] > time.monotonic():
                continue
            if not telemetryAllows(self._id, TELEMETRY_FIELD[data_type]):
                continue
            try:
                progressed = drain() or progressed
            except TelemetryBlocked:
                continue  # turned off while the leg ran
            except requests.HTTPError as exc:
                if not self._pauseLeg(data_type, exc):
                    raise
            else:
                self._paused_why.pop(data_type, None)
        self._state_ok = True
        if progressed:
            self._mark_retention()
        return progressed

    def _pauseLeg(self, data_type: str, exc: requests.HTTPError) -> bool:
        """Turn one leg off for a while after a 4xx that is about that leg's
        request. False for errors about the target as a whole (a 5xx, a 429, an
        auth failure), which back the whole target off instead."""
        status = exc.response.status_code if exc.response is not None else None
        if status is None or status >= 500 or status in (401, 403, 429):
            return False
        unsupported = status in (404, 405)
        retry_s = UNSUPPORTED_RETRY_S if unsupported else LEG_ERROR_RETRY_S
        self._paused_until[data_type] = time.monotonic() + retry_s
        self._paused_why[data_type] = "unsupported" if unsupported else str(exc)
        if unsupported:
            log.warning(
                "hive_sync: %s does not accept %s yet (HTTP %s); trying again in %.0f min",
                self._name, data_type, status, retry_s / 60,
            )
        else:
            log.warning(
                "hive_sync: %s refused %s (HTTP %s); that leg waits %.0f min, the rest carry on: %s",
                self._name, data_type, status, retry_s / 60, exc,
            )
        return True

    def _legError(self) -> str | None:
        """The error a paused leg is waiting out, for the settings page."""
        now = time.monotonic()
        for data_type, why in self._paused_why.items():
            if why != "unsupported" and self._paused_until[data_type] > now:
                return f"{data_type}: {why}"
        return None

    def _ensureState(self) -> None:
        if self._state_ok and self._wm[DATA_TYPE_RECORDS] is not None:
            return
        state = self._client.getSyncState()
        for data_type in DATA_TYPES:
            raw = state.get(data_type) if isinstance(state, dict) else None
            value = raw.get("max_local_id") if isinstance(raw, dict) else 0
            self._wm[data_type] = int(value or 0)

    def _advance(self, data_type: str, *values: int) -> None:
        self._wm[data_type] = max(int(self._wm[data_type] or 0), *(int(v) for v in values))

    def _takeBudget(self, nbytes: int) -> bool:
        if self._budget.take(nbytes):
            return True
        wait = self._budget.waitS(nbytes)
        self._budget_wait_s = wait if self._budget_wait_s is None else min(self._budget_wait_s, wait)
        return False

    def _drainRecords(self) -> bool:
        wm = int(self._wm[DATA_TYPE_RECORDS] or 0)
        rows = piece_records.listRecordsAfter(wm, ROWS_BATCH)
        if not rows:
            return False
        with self._gate.slot():
            new_max = self._client.pushPieceRecords([_recordToPayload(r) for r in rows])
        self._advance(DATA_TYPE_RECORDS, new_max, rows[-1]["sync_seq"])
        return True

    def _drainPredictions(self) -> bool:
        wm = int(self._wm[DATA_TYPE_PREDICTIONS] or 0)
        rows = piece_predictions.listAfter(wm, ROWS_BATCH)
        if not rows:
            return False
        with self._gate.slot():
            new_max = self._client.pushPiecePredictions([_predictionToPayload(r) for r in rows])
        self._advance(DATA_TYPE_PREDICTIONS, new_max, rows[-1]["id"])
        return True

    def _drainImages(self) -> bool:
        rows = piece_image_store.listImagesAfter(int(self._wm[DATA_TYPE_IMAGES] or 0), FILES_PER_PASS)
        sent = False
        for row in rows:
            if self._stop.is_set():
                break
            # Model guesses must never be uploaded as piece images — they would
            # land in Hive's labeling gallery as "this IS the piece" and poison
            # the training data. New code writes them to piece_link_images, but
            # rows from the window where they landed in piece_images get skipped
            # here (watermark still advances so the backlog drains past them).
            if row.get("source") == "link_match":
                self._advance(DATA_TYPE_IMAGES, row["sync_seq"])
                sent = True
                continue
            file_path = None if row["evicted_locally"] else piece_image_store.getImageFileById(row["id"])
            if file_path is not None and not self._takeBudget(int(row.get("bytes") or 0)):
                break
            with self._gate.slot():
                new_max = self._client.pushPieceImage(_imageToMeta(row), file_path)
            self._advance(DATA_TYPE_IMAGES, new_max, row["sync_seq"])
            sent = True
        return sent

    def _drainChannelCrops(self) -> bool:
        rows = channel_crop_store.listCropsAfter(int(self._wm[DATA_TYPE_CROPS] or 0), FILES_PER_PASS)
        sent = False
        for row in rows:
            if self._stop.is_set():
                break
            file_path = None if row["evicted_locally"] else channel_crop_store.getCropFileById(row["id"])
            if file_path is not None and not self._takeBudget(int(row.get("bytes") or 0)):
                break
            with self._gate.slot():
                new_max = self._client.pushChannelCrop(_cropToMeta(row), file_path)
            self._advance(DATA_TYPE_CROPS, new_max, row["id"])
            sent = True
        return sent

    def _drainControlData(self) -> bool:
        # Evicted segments ride up metadata-only so counts stay complete.
        rows = control_data_store.listSegmentsAfter(int(self._wm[DATA_TYPE_CONTROL_DATA] or 0), FILES_PER_PASS)
        sent = False
        for row in rows:
            if self._stop.is_set():
                break
            file_path = None if row["evicted_locally"] else control_data_store.getSegmentFileById(row["id"])
            if file_path is not None and not self._takeBudget(int(row.get("bytes") or 0)):
                break
            with self._gate.slot():
                new_max = self._client.pushControlDataSegment(_controlSegmentToMeta(row), file_path)
            self._advance(DATA_TYPE_CONTROL_DATA, new_max, row["id"])
            sent = True
        return sent

    def _drainSamples(self) -> bool:
        wm = int(self._wm[DATA_TYPE_SAMPLES] or 0)
        drops = _evenDrops(sample_store.countWaitingByCamera(wm), SAMPLES_BACKLOG_MAX)
        if drops:
            log.info(
                "hive_sync: %s: skipping the oldest waiting samples: %s",
                self._name, ", ".join(f"{n} from {camera}" for camera, n in sorted(drops.items())),
            )
        rows = sample_store.listSamplesAfter(wm, min(SAMPLES_FETCH_MAX, FILES_PER_PASS + sum(drops.values())))
        progressed = False
        for row in rows:
            if self._stop.is_set():
                break
            file_path = None if row["evicted_locally"] else sample_store.getSampleFileById(row["id"])
            if file_path is None:
                # Retention removed it before it was sent: nothing to send.
                self._advance(DATA_TYPE_SAMPLES, row["id"])
                progressed = True
                continue
            if drops.get(row["camera"], 0) > 0:
                drops[row["camera"]] -= 1
                self._advance(DATA_TYPE_SAMPLES, row["id"])
                progressed = True
                continue
            if not self._takeBudget(int(row["bytes"])):
                break
            try:
                with self._gate.slot():
                    new_max = self._client.pushSample(_sampleToMeta(row), file_path)
            except FileNotFoundError:
                self._advance(DATA_TYPE_SAMPLES, row["id"])
                continue
            self._advance(DATA_TYPE_SAMPLES, new_max, row["id"])
            progressed = True
        return progressed

    def _noteBackoff(self, exc: Exception) -> None:
        self._state_ok = False  # re-fetch watermark on recovery (handles a hive DB reset)
        self._last_error = str(exc)
        self._backoff_s = min(
            max(float(self._backoff_s), SERVER_DOWN_BACKOFF_S) * 1.5,
            SERVER_DOWN_MAX_BACKOFF_S,
        )
        retry_after = _retryAfterS(exc)
        if retry_after is not None:
            self._backoff_s = max(self._backoff_s, retry_after)
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

    def status(self, target_id: str) -> dict[str, Any] | None:
        with self._lock:
            syncer = self._syncers.get(target_id)
        return syncer.status() if syncer is not None else None

    def confirmedWatermarks(self) -> dict[str, int | None] | None:
        """Per data type, how far EVERY enabled target is known to have
        everything (the lowest of their watermarks), for retention. None when
        no target is enabled. A type's value is None while any target's state
        is unknown, which holds retention back; a target that does not take a
        type (its telemetry field is off) does not."""
        with self._lock:
            syncers = list(self._syncers.values())
        if not syncers:
            return None
        per_target = [syncer.retentionWatermarks() for syncer in syncers]
        out: dict[str, int | None] = {}
        for data_type in DATA_TYPES:
            values = [wms[data_type] for wms in per_target]
            out[data_type] = None if any(v is None for v in values) else min(int(v) for v in values)
        return out

    def _rebuildLocked(self) -> None:
        # Config edits are rare (a target add/remove/enable), so just tear the
        # target threads down and rebuild from fresh config. Each new thread
        # re-fetches its watermark from the server, so no progress is lost — the
        # brief overlap with an exiting thread is harmless: both push in cursor
        # order and Hive upserts idempotently, so no gap can open.
        for syncer in self._syncers.values():
            syncer.stop()
        self._syncers = {}
        config = get_hive_config()
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
        # Stamp synced_at up to what every enabled target has, per store, so a
        # store's cap evicts those files first. A target whose state is unknown
        # (e.g. a local hive that 401s) freezes it rather than marking data a
        # broken target never received.
        now = time.time()
        with self._retention_lock:
            if now - self._last_retention < RETENTION_MARK_INTERVAL_S:
                return
            self._last_retention = now
        confirmed = self.confirmedWatermarks()
        if confirmed is None:
            return
        for data_type, mark in (
            (DATA_TYPE_IMAGES, piece_image_store.markImagesSyncedUpTo),
            (DATA_TYPE_CROPS, channel_crop_store.markSyncedUpTo),
            (DATA_TYPE_CONTROL_DATA, control_data_store.markSyncedUpTo),
            (DATA_TYPE_SAMPLES, sample_store.markSyncedUpTo),
        ):
            wm = confirmed[data_type]
            if wm is not None and wm != NOT_WANTED:
                mark(wm, now)
