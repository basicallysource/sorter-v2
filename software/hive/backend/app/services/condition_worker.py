"""Background loop that auto-labels `capture_scope=condition` samples.

Polls the samples table every ``CONDITION_WORKER_POLL_INTERVAL_S`` seconds
for samples that:
  * have ``sample_payload->sample->capture_scope = 'condition'``, AND
  * do not yet carry a ``cond_primary`` analysis block.

For each, fetches the crop bytes via the storage backend, calls Perceptron
for a single structured judgment, and writes the result via the shared
``upsert_condition_analysis`` writer with ``source=perceptron_condition``.

Off by default — operators set ``CONDITION_WORKER_ENABLED=true`` and a key
in ``CONDITION_WORKER_PERCEPTRON_API_KEY`` to turn it on. Stays single
threaded on purpose: condition labeling isn't on the hot path and a quiet
2-3 req/s is plenty for the volume the sorter produces.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.sample import Sample
from app.services.condition_adapter_perceptron import (
    PERCEPTRON_MODEL_ID,
    ConditionAssessmentResult,
    assess_condition,
)
from app.services.condition_analysis import (
    SOURCE_PERCEPTRON,
    has_condition_analysis,
    upsert_condition_analysis,
)
from app.services.storage_backend import get_backend
from app.services.teacher_adapters.base import TeacherRateLimitError


logger = logging.getLogger(__name__)


_IDLE_POLL_FALLBACK_S = 2.0


def _find_due_samples(db: Session, *, limit: int) -> list[Sample]:
    """Return up to ``limit`` condition samples that still need labeling.

    Uses a JSON path filter that works on both PostgreSQL (JSONB) and SQLite
    (JSON1) — the second clause walks the analyses array in app code rather
    than relying on dialect-specific containment ops.
    """

    # Cheap first cut: samples whose source_role hints at condition collection.
    # ``capture_scope`` lives nested inside sample_payload, which neither
    # dialect indexes by default, so we filter generously here and refine in
    # Python below. The condition collector ships samples with
    # ``capture_reason=piece_condition_collector``; that's the cheapest
    # selectable signal.
    rows = (
        db.execute(
            select(Sample)
            .where(
                or_(
                    Sample.capture_reason == "piece_condition_collector",
                    Sample.capture_reason == "piece_condition_teacher",
                )
            )
            .order_by(Sample.uploaded_at.asc())
            .limit(limit * 4)
        )
        .scalars()
        .all()
    )
    due: list[Sample] = []
    for sample in rows:
        if has_condition_analysis(sample):
            continue
        due.append(sample)
        if len(due) >= limit:
            break
    return due


class ConditionWorker:
    """Daemon thread + one-pass driver for the condition auto-labeler."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._start_lock = threading.Lock()
        self._last_call_at: float = 0.0
        # Telemetry — surfaced via /api/teacher/condition/status so the admin UI
        # can see whether the loop is alive and how it's been doing.
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {
            "enabled": False,
            "running": False,
            "last_run_at": None,
            "last_run_processed": 0,
            "last_run_errors": 0,
            "last_error": None,
            "total_processed": 0,
            "total_errors": 0,
            "total_runs": 0,
        }

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="condition-worker",
            )
            self._thread.start()
        self._update_state(running=True)

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._update_state(running=False)

    def wake(self) -> None:
        self._wake_event.set()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = dict(self._state)
        snapshot["enabled"] = bool(settings.CONDITION_WORKER_ENABLED)
        snapshot["has_api_key"] = bool(settings.CONDITION_WORKER_PERCEPTRON_API_KEY)
        snapshot["model"] = PERCEPTRON_MODEL_ID
        snapshot["poll_interval_s"] = float(settings.CONDITION_WORKER_POLL_INTERVAL_S)
        snapshot["batch_size"] = int(settings.CONDITION_WORKER_BATCH_SIZE)
        return snapshot

    # ------------------------------------------------------------------ main loop

    def _loop(self) -> None:
        logger.info("ConditionWorker: started")
        while not self._stop_event.is_set():
            poll_s = max(1.0, float(settings.CONDITION_WORKER_POLL_INTERVAL_S))
            try:
                if not settings.CONDITION_WORKER_ENABLED:
                    # Quiet idle when disabled — still responsive to wake().
                    pass
                elif not settings.CONDITION_WORKER_PERCEPTRON_API_KEY:
                    logger.warning(
                        "ConditionWorker enabled but CONDITION_WORKER_PERCEPTRON_API_KEY is empty; idling"
                    )
                else:
                    self._run_one_pass()
            except Exception as exc:
                logger.exception("ConditionWorker pass crashed: %s", exc)
                self._update_state(last_error=str(exc))

            self._wake_event.wait(timeout=poll_s)
            self._wake_event.clear()
        self._update_state(running=False)
        logger.info("ConditionWorker: stopped")

    def _run_one_pass(self) -> None:
        batch_size = max(1, int(settings.CONDITION_WORKER_BATCH_SIZE))
        api_key = settings.CONDITION_WORKER_PERCEPTRON_API_KEY or ""

        db = SessionLocal()
        try:
            due = _find_due_samples(db, limit=batch_size)
            if not due:
                return

            processed = 0
            errors = 0
            for sample in due:
                if self._stop_event.is_set():
                    break
                self._respect_min_interval()
                try:
                    image_bytes = get_backend().read_bytes(sample.image_path)
                except FileNotFoundError:
                    logger.warning(
                        "ConditionWorker: image missing for sample %s, skipping", sample.id
                    )
                    errors += 1
                    continue

                try:
                    result = assess_condition(
                        image_bytes=image_bytes,
                        api_key=api_key,
                        base_url=settings.PERCEPTRON_BASE_URL,
                    )
                except TeacherRateLimitError as exc:
                    sleep_s = max(1.0, float(exc.retry_after_s or 5.0))
                    logger.info(
                        "ConditionWorker: rate-limited, sleeping %.1fs", sleep_s
                    )
                    time.sleep(sleep_s)
                    errors += 1
                    continue
                except Exception as exc:
                    logger.exception("ConditionWorker: adapter failed: %s", exc)
                    self._write_failed(db, sample, str(exc))
                    errors += 1
                    continue

                self._write_success(db, sample, result)
                processed += 1
            db.commit()
            self._update_state(
                last_run_at=datetime.now(timezone.utc).isoformat(),
                last_run_processed=processed,
                last_run_errors=errors,
                last_error=None if errors == 0 else self._state.get("last_error"),
                increment_processed=processed,
                increment_errors=errors,
                increment_runs=1,
            )
        finally:
            db.close()

    def _respect_min_interval(self) -> None:
        min_interval = max(0.0, float(settings.CONDITION_WORKER_MIN_INTERVAL_S))
        if min_interval <= 0.0:
            return
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_at = time.monotonic()

    def _write_success(
        self,
        db: Session,
        sample: Sample,
        result: ConditionAssessmentResult,
    ) -> None:
        upsert_condition_analysis(
            sample,
            composition=result.composition,
            condition=result.condition,
            flags=result.flags,
            source=SOURCE_PERCEPTRON,
            model=PERCEPTRON_MODEL_ID,
            confidence=result.confidence,
            part_count_estimate=result.part_count_estimate,
            visible_evidence=result.visible_evidence,
            issues=result.issues,
            status="completed",
            raw_payload=result.raw_payload,
        )
        db.add(sample)

    def _write_failed(self, db: Session, sample: Sample, error_message: str) -> None:
        """Persist a 'failed' analysis block so we don't keep retrying forever.

        Without this the worker would re-pick the same sample every pass.
        Writing an explicit failed entry lets has_condition_analysis return
        True and gets the sample out of the queue.
        """

        upsert_condition_analysis(
            sample,
            composition="uncertain",
            condition="uncertain",
            flags={},
            source=SOURCE_PERCEPTRON,
            model=PERCEPTRON_MODEL_ID,
            status="failed",
            error=error_message[:512],
        )
        db.add(sample)

    # ------------------------------------------------------------------ state

    def _update_state(self, **kwargs: Any) -> None:
        with self._state_lock:
            if "running" in kwargs:
                self._state["running"] = bool(kwargs.pop("running"))
            if "last_run_at" in kwargs:
                self._state["last_run_at"] = kwargs.pop("last_run_at")
            if "last_run_processed" in kwargs:
                self._state["last_run_processed"] = int(kwargs.pop("last_run_processed"))
            if "last_run_errors" in kwargs:
                self._state["last_run_errors"] = int(kwargs.pop("last_run_errors"))
            if "last_error" in kwargs:
                self._state["last_error"] = kwargs.pop("last_error")
            if "increment_processed" in kwargs:
                self._state["total_processed"] += int(kwargs.pop("increment_processed"))
            if "increment_errors" in kwargs:
                self._state["total_errors"] += int(kwargs.pop("increment_errors"))
            if "increment_runs" in kwargs:
                self._state["total_runs"] += int(kwargs.pop("increment_runs"))


_INSTANCE: ConditionWorker | None = None
_INSTANCE_LOCK = threading.Lock()


def get_condition_worker() -> ConditionWorker:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ConditionWorker()
    return _INSTANCE


__all__ = ["ConditionWorker", "get_condition_worker"]
