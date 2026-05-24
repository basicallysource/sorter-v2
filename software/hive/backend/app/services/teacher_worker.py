"""Background worker that drives TeacherJob/TeacherJobItem to completion.

A dispatcher thread continuously claims queued items (via SELECT … FOR UPDATE SKIP LOCKED
so the same item can't be picked twice) and hands them to a ThreadPoolExecutor. Each
worker thread then:

1. Acquires a per-adapter semaphore (max_concurrent) so a single noisy provider can't
   monopolize the pool.
2. Sleeps to enforce a per-adapter min_interval_s so we don't sprint at a fresh quota
   window and trip a per-second cap.
3. Calls adapter.detect(). On HTTP 429 (`TeacherRateLimitError`) backs off using the
   server-provided Retry-After hint plus jitter, then retries up to N times.
4. Writes the result and bumps the job aggregates inside a single transaction.

Per-adapter knobs live on the adapter class (``max_concurrent``, ``min_interval_s``) so
adding a new provider with different rate-limit characteristics is one entry in the
registry rather than a worker-level change.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.sample import Sample
from app.models.teacher_job import TeacherJob, TeacherJobItem
from app.models.user import User
from app.services.secrets import decrypt_secret
from app.services.storage_backend import get_backend
from app.services.teacher_adapters import TeacherRateLimitError, get_adapter
from app.services.teacher_prompts import adapter_kind_for, resolve_prompt
from app.services.teacher_detector import (
    DEFAULT_OPENROUTER_MODEL,
    apply_teacher_result_to_sample,
    normalize_openrouter_model,
    run_teacher_detection,
    zone_for_source_role,
)


logger = logging.getLogger(__name__)


# Short sleep when the queue is empty so we don't busy-wait but still react quickly when
# a new job lands.
_IDLE_POLL_S = 2.0
# Max retries on 429 before we give up and mark the item as errored.
_MAX_RATE_LIMIT_RETRIES = 4
# Worst-case jitter window so a wave of 429s doesn't reconverge in a thundering herd.
_RETRY_JITTER_S = 0.75


class TeacherWorker:
    """Dispatcher thread + per-adapter throttled executor pool."""

    def __init__(self) -> None:
        self._dispatcher: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._start_lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        # Per-adapter concurrency + spacing state, keyed by adapter_kind.
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._sem_lock = threading.Lock()
        self._last_call_at: dict[str, float] = {}
        self._last_call_locks: dict[str, threading.Lock] = {}
        # In-flight item ids the dispatcher has handed off but not yet seen finish — used
        # to size the next claim batch without re-querying the executor.
        self._in_flight: set[UUID] = set()
        self._in_flight_lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        with self._start_lock:
            if self._dispatcher is not None and self._dispatcher.is_alive():
                return
            self._stop_event.clear()
            self._executor = ThreadPoolExecutor(
                max_workers=max(1, settings.TEACHER_WORKER_PARALLELISM),
                thread_name_prefix="teacher-worker",
            )
            self._dispatcher = threading.Thread(
                target=self._dispatch_loop,
                name="teacher-dispatcher",
                daemon=True,
            )
            self._dispatcher.start()
            logger.info(
                "Teacher worker started (parallelism=%d)",
                settings.TEACHER_WORKER_PARALLELISM,
            )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._dispatcher
        if thread is not None:
            thread.join(timeout=timeout)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def notify(self) -> None:
        self._wake_event.set()

    # ------------------------------------------------------------------ dispatcher

    def _dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                submitted = self._dispatch_once()
            except Exception:  # defensive — keep the dispatcher alive across failures
                logger.exception("Dispatcher iteration failed")
                submitted = 0
            if submitted > 0:
                # Stay hot: more items might be ready right now.
                continue
            self._wake_event.wait(timeout=_IDLE_POLL_S)
            self._wake_event.clear()
        logger.info("Teacher worker stopped")

    def _dispatch_once(self) -> int:
        """Claim up to ``free_slots`` items and submit them to the executor."""
        with self._in_flight_lock:
            free_slots = max(0, settings.TEACHER_WORKER_PARALLELISM - len(self._in_flight))
        if free_slots == 0:
            return 0

        db: Session = SessionLocal()
        submitted = 0
        try:
            for _ in range(free_slots):
                item_id = self._claim_next_item_id(db)
                if item_id is None:
                    break
                with self._in_flight_lock:
                    self._in_flight.add(item_id)
                future = self._executor.submit(self._run_item, item_id)  # type: ignore[union-attr]
                future.add_done_callback(lambda _f, _iid=item_id: self._mark_finished(_iid))
                submitted += 1
        finally:
            db.close()
        return submitted

    def _claim_next_item_id(self, db: Session) -> UUID | None:
        """Atomically transition the oldest queued item to ``running`` and return its id.

        Uses ``SELECT … FOR UPDATE SKIP LOCKED`` (Postgres-native) so concurrent claim
        passes from a future multi-dispatcher setup can't grab the same row.
        """
        item = (
            db.query(TeacherJobItem)
            .join(TeacherJob, TeacherJobItem.job_id == TeacherJob.id)
            .filter(TeacherJobItem.status == "queued")
            .filter(TeacherJob.status.in_(("pending", "running")))
            .order_by(TeacherJobItem.created_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if item is None:
            return None

        item.status = "running"
        job = db.query(TeacherJob).filter(TeacherJob.id == item.job_id).first()
        if job is not None and job.status == "pending":
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.add(job)
        db.add(item)
        db.commit()
        return item.id

    def _mark_finished(self, item_id: UUID) -> None:
        with self._in_flight_lock:
            self._in_flight.discard(item_id)
        # Wake the dispatcher so it can refill the slot we just freed.
        self._wake_event.set()

    # ------------------------------------------------------------------ throttling

    def _semaphore_for(self, adapter_kind: str, max_concurrent: int) -> threading.BoundedSemaphore:
        with self._sem_lock:
            sem = self._semaphores.get(adapter_kind)
            if sem is None:
                sem = threading.BoundedSemaphore(max(1, max_concurrent))
                self._semaphores[adapter_kind] = sem
            return sem

    def _reserve_rate_slot(self, adapter_kind: str, min_interval_s: float) -> float:
        """Reserve the next call slot for ``adapter_kind`` and return the seconds to sleep.

        Reserves the slot under a short-held lock by writing the *future* timestamp this
        call will occur at, then releases the lock and returns the wait so the caller can
        sleep outside the critical section. That way other threads can stack their own
        reservations concurrently.
        """
        lock = self._last_call_locks.setdefault(adapter_kind, threading.Lock())
        with lock:
            now = time.monotonic()
            last = self._last_call_at.get(adapter_kind, 0.0)
            target = max(now, last + min_interval_s)
            wait = target - now
            self._last_call_at[adapter_kind] = target
        return wait

    # ------------------------------------------------------------------ per-item worker

    def _run_item(self, item_id: UUID) -> None:
        """Executor-thread entry point.

        Critical: the slow OpenRouter/Perceptron call MUST NOT happen while a DB session
        is held — otherwise 6 worker threads × multi-second adapter latency exhausts the
        SQLAlchemy connection pool and starves the FastAPI handlers. We pull what we need
        in a short open-close transaction, release the connection, run the API call, then
        reopen a fresh session to write the result back.
        """
        try:
            ctx = self._load_item_context(item_id)
            if ctx is None:
                return

            zone, adapter, api_key, image_bytes, override_prompt, sample_id, job_id, error = ctx
            if error is not None:
                self._record_terminal_status(item_id, job_id, **error)
                return

            # Throttle + run with retries on 429. NO database session is held here.
            max_concurrent = getattr(adapter, "max_concurrent", 1)
            min_interval = float(getattr(adapter, "min_interval_s", 1.0))
            adapter_kind = adapter.adapter_kind
            sem = self._semaphore_for(adapter_kind, max_concurrent)

            with sem:
                try:
                    result = self._call_with_retry(
                        adapter=adapter,
                        image_bytes=image_bytes,
                        zone=zone,
                        api_key=api_key,
                        adapter_kind=adapter_kind,
                        min_interval=min_interval,
                        override_prompt=override_prompt,
                    )
                except Exception as exc:
                    logger.exception("Teacher item %s failed", item_id)
                    self._record_terminal_status(
                        item_id, job_id,
                        status="error",
                        error_message=str(exc)[:500],
                        succeeded=False,
                        count_as_failure=True,
                    )
                    return

            self._write_result(item_id, job_id, sample_id, result)
        except Exception:
            logger.exception("Teacher item %s crashed", item_id)

    def _load_item_context(self, item_id: UUID):
        """Open a short-lived session to fetch everything the adapter call needs.

        Returns ``(zone, adapter, api_key, image_bytes, sample_id, job_id, error_dict)``
        or ``None`` if the item disappeared. ``error_dict`` is non-None when the item
        can't be processed for a deterministic reason (missing zone, missing key, missing
        image); the caller then writes the terminal status without making the API call.
        """
        db: Session = SessionLocal()
        try:
            item = db.query(TeacherJobItem).filter(TeacherJobItem.id == item_id).first()
            if item is None:
                return None
            job = db.query(TeacherJob).filter(TeacherJob.id == item.job_id).first()
            if job is None:
                db.delete(item)
                db.commit()
                return None
            sample = db.query(Sample).filter(Sample.id == item.sample_id).first()
            owner = db.query(User).filter(User.id == job.owner_id).first()
            job_id = job.id
            sample_id = sample.id if sample else None

            if owner is None:
                return (
                    None, None, None, None, None, sample_id, job_id,
                    {
                        "status": "error", "error_message": "Job owner no longer exists",
                        "succeeded": False, "count_as_failure": True,
                    },
                )
            if sample is None:
                return (
                    None, None, None, None, None, sample_id, job_id,
                    {
                        "status": "error", "error_message": "Sample no longer exists",
                        "succeeded": False, "count_as_failure": True,
                    },
                )

            zone = zone_for_source_role(sample.source_role)
            if zone is None:
                return (
                    None, None, None, None, None, sample_id, job_id,
                    {
                        "status": "skipped",
                        "error_message": f"No teacher zone for source_role={sample.source_role!r}",
                        "succeeded": False,
                    },
                )

            model_id = normalize_openrouter_model(job.openrouter_model)
            adapter = get_adapter(model_id)
            if adapter is None:
                return (
                    None, None, None, None, None, sample_id, job_id,
                    {
                        "status": "error",
                        "error_message": f"Unknown model {job.openrouter_model!r}",
                        "succeeded": False, "count_as_failure": True,
                    },
                )

            secret_kind = getattr(adapter, "secret_kind", "openrouter")
            if secret_kind == "perceptron":
                api_key = decrypt_secret(owner.perceptron_api_key_encrypted)
                missing_msg = "Job owner has no Perceptron API key configured."
            else:
                api_key = decrypt_secret(owner.openrouter_api_key_encrypted)
                missing_msg = "Job owner has no OpenRouter API key configured."
            if not api_key:
                return (
                    None, None, None, None, None, sample_id, job_id,
                    {
                        "status": "error", "error_message": missing_msg,
                        "succeeded": False, "count_as_failure": True,
                    },
                )

            try:
                image_bytes = get_backend().read_bytes(sample.image_path)
            except FileNotFoundError:
                return (
                    None, None, None, None, None, sample_id, job_id,
                    {
                        "status": "error", "error_message": "Sample image is missing",
                        "succeeded": False, "count_as_failure": True,
                    },
                )

            # Resolve the admin-edited prompt for this zone+kind (DB row or default
            # template). Done inside the short-lived session so the slow API call
            # downstream doesn't hold a connection. Falls back cleanly to the adapter's
            # built-in default when no row is set.
            resolved = resolve_prompt(
                db,
                zone,
                adapter_kind_for(adapter.adapter_kind),
                width=int(sample.image_width or 1024),
                height=int(sample.image_height or 1024),
            )

            return zone, adapter, api_key, image_bytes, resolved.content, sample_id, job_id, None
        finally:
            db.close()

    def _write_result(self, item_id: UUID, job_id: UUID, sample_id: UUID, result: dict) -> None:
        """Persist a successful adapter result in a fresh, short-lived transaction."""
        db: Session = SessionLocal()
        try:
            item = db.query(TeacherJobItem).filter(TeacherJobItem.id == item_id).first()
            job = db.query(TeacherJob).filter(TeacherJob.id == job_id).first()
            sample = db.query(Sample).filter(Sample.id == sample_id).first()
            if item is None or job is None or sample is None:
                return

            apply_teacher_result_to_sample(
                sample, result, source="hive_teacher_worker", job_id=str(job.id),
            )
            db.add(sample)

            item.status = "done"
            item.error_message = None
            item.detection_count = int(result["count"])
            item.detection_score = f"{float(result['score']):.4f}"
            item.cost_usd = result.get("cost_usd")
            item.tokens_input = result.get("prompt_tokens")
            item.tokens_output = result.get("completion_tokens")
            item.processed_at = datetime.now(timezone.utc)

            job.processed += 1
            job.succeeded += 1
            if isinstance(item.cost_usd, (int, float)):
                job.cost_usd = float(job.cost_usd or 0.0) + float(item.cost_usd)
            if isinstance(item.tokens_input, int):
                job.tokens_input = int(job.tokens_input or 0) + int(item.tokens_input)
            if isinstance(item.tokens_output, int):
                job.tokens_output = int(job.tokens_output or 0) + int(item.tokens_output)
            db.add(item)
            db.add(job)
            db.commit()
            self._maybe_finalize_job(db, job.id)
        finally:
            db.close()

    def _record_terminal_status(
        self,
        item_id: UUID,
        job_id: UUID,
        *,
        status: str,
        error_message: str | None,
        succeeded: bool,
        count_as_failure: bool = False,
    ) -> None:
        """Write a terminal item status (error/skipped) without holding the connection."""
        db: Session = SessionLocal()
        try:
            item = db.query(TeacherJobItem).filter(TeacherJobItem.id == item_id).first()
            job = db.query(TeacherJob).filter(TeacherJob.id == job_id).first()
            if item is None or job is None:
                return
            self._mark_item_status(
                db, item, job,
                status=status,
                error_message=error_message,
                succeeded=succeeded,
                count_as_failure=count_as_failure,
            )
        finally:
            db.close()

    def _call_with_retry(
        self,
        *,
        adapter: Any,
        image_bytes: bytes,
        zone: str,
        api_key: str,
        adapter_kind: str,
        min_interval: float,
        override_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Call adapter.detect with min-interval throttle + 429 exponential backoff."""
        last_error: Exception | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            wait = self._reserve_rate_slot(adapter_kind, min_interval)
            if wait > 0:
                time.sleep(wait)
            try:
                result = adapter.detect(
                    image_bytes=image_bytes,
                    zone=zone,
                    api_key=api_key,
                    public_app_url=settings.public_app_url,
                    override_prompt=override_prompt,
                )
                return result.to_payload()
            except TeacherRateLimitError as exc:
                last_error = exc
                if attempt >= _MAX_RATE_LIMIT_RETRIES:
                    break
                base = exc.retry_after_s if exc.retry_after_s is not None else float(2 ** attempt)
                backoff = base + random.uniform(0.0, _RETRY_JITTER_S)
                logger.warning(
                    "Rate-limited on %s (attempt %d/%d) — sleeping %.2fs",
                    adapter_kind, attempt + 1, _MAX_RATE_LIMIT_RETRIES + 1, backoff,
                )
                time.sleep(backoff)
        # All retries exhausted — re-raise the last 429 so the caller marks it errored.
        raise last_error if last_error else RuntimeError("Rate-limit retry loop exhausted")

    # ------------------------------------------------------------------ status writers

    def _mark_item_error(
        self, db: Session, item: TeacherJobItem, job: TeacherJob, message: str
    ) -> None:
        self._mark_item_status(
            db, item, job,
            status="error",
            error_message=message,
            succeeded=False,
            count_as_failure=True,
        )

    def _mark_item_status(
        self,
        db: Session,
        item: TeacherJobItem,
        job: TeacherJob,
        *,
        status: str,
        error_message: str | None,
        succeeded: bool,
        count_as_failure: bool = False,
    ) -> None:
        item.status = status
        item.error_message = error_message
        item.processed_at = datetime.now(timezone.utc)
        job.processed += 1
        if succeeded:
            job.succeeded += 1
        elif count_as_failure:
            job.failed += 1
            job.last_error = error_message
        db.add(item)
        db.add(job)
        db.commit()
        self._maybe_finalize_job(db, job.id)

    def _maybe_finalize_job(self, db: Session, job_id: UUID) -> None:
        job = db.query(TeacherJob).filter(TeacherJob.id == job_id).first()
        if job is None or job.status not in ("pending", "running"):
            return
        remaining = (
            db.query(TeacherJobItem)
            .filter(TeacherJobItem.job_id == job_id)
            .filter(TeacherJobItem.status.in_(("queued", "running")))
            .count()
        )
        if remaining == 0:
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            db.commit()


_worker = TeacherWorker()


def get_teacher_worker() -> TeacherWorker:
    return _worker
