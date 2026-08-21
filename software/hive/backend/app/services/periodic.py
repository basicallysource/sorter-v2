"""One periodic background worker, used by everything that runs on a cadence.

Four services had each grown their own copy of the same daemon thread — a
``_thread``, a ``_stop_event``, a ``_start_lock``, a ``start``/``stop`` pair, a
``_loop`` that waits then calls one function, and a module-level singleton
behind ``get_x_worker()``. The copies had drifted (some logged the duration,
some swallowed exceptions differently, one read its interval once at startup
instead of per pass), which is the usual cost of four things doing one thing.

A periodic worker is the whole abstraction: a name, a callable, and how long to
wait between calls. Everything specific to a job belongs in the callable.

The interval is a callable rather than a number so a job whose cadence comes
from settings picks up a change without a restart, and so a job can back off.

Note this is for jobs that run on a CLOCK. A worker that waits on a queue
(``teacher_worker``) or drains a table as fast as rows appear
(``condition_worker``) is a different animal and does not belong here.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PeriodicWorker:
    """Daemon thread that calls ``job`` every ``interval()`` seconds.

    ``job`` may return a dict, which is merged into ``status()``. That is how a
    job reports something only it understands ("machines refreshed") without
    this class having to know what the job does.

    An exception in ``job`` is logged with its traceback, recorded as
    ``last_error``, and the loop continues. A cache that fails to rebuild
    serves stale data, which is worth much more than a worker that dies
    silently on one bad pass.
    """

    def __init__(
        self,
        name: str,
        job: Callable[[], Any],
        interval: Callable[[], float],
        *,
        run_at_start: bool | Callable[[], bool] = False,
    ) -> None:
        self.name = name
        self._job = job
        self._interval = interval
        # Callable form is for a job whose first pass is expensive and may
        # already be warm from the previous process (walking an object store),
        # so it is decided on the thread rather than at construction.
        self._run_at_start = run_at_start
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._start_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "last_run_at": None,
            "last_run_duration_s": None,
            "last_error": None,
            "total_runs": 0,
        }

    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name=self.name)
            self._thread.start()
        self._merge_state(running=True)

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._merge_state(running=False)

    def wake(self) -> None:
        """Ask the loop to run a pass as soon as it can, without waiting out the interval."""
        self._wake_event.set()

    def run_once(self) -> Any:
        """Run one pass inline. For tests and for cold-start warmup."""
        return self._run()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = dict(self._state)
        snapshot["interval_s"] = self._interval()
        return snapshot

    def _loop(self) -> None:
        logger.info("%s: started", self.name)
        first = self._run_at_start() if callable(self._run_at_start) else self._run_at_start
        if first:
            self._run()
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=self._interval())
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self._run()
        self._merge_state(running=False)
        logger.info("%s: stopped", self.name)

    def _run(self) -> Any:
        started = time.monotonic()
        try:
            detail = self._job()
        except Exception as exc:
            logger.exception("%s: pass failed", self.name)
            self._merge_state(last_error=str(exc))
            return None
        elapsed = round(time.monotonic() - started, 3)
        state: dict[str, Any] = {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_run_duration_s": elapsed,
            "last_error": None,
        }
        if isinstance(detail, dict):
            state.update(detail)
        self._merge_state(_increment_runs=True, **state)
        logger.info("%s: pass finished in %.1fs", self.name, elapsed)
        return detail

    def _merge_state(self, *, _increment_runs: bool = False, **values: Any) -> None:
        with self._state_lock:
            if _increment_runs:
                self._state["total_runs"] += 1
            self._state.update(values)
