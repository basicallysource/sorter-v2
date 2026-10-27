"""The worker process's parts-catalog work, each piece in a child process.

The worker process never loads the parts catalog: it is ~390 MB in memory, and
the web process already holds the copy requests need. What needs the whole
catalog runs as a catalog task (``python -m app.catalog_task``) instead:

- ``default-profiles`` once, when the worker starts;
- ``auto-sync`` whenever a check finds the catalog stale. The check runs every
  ``PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES`` (and at the start) by
  counting rows and reading the sync times in parts.db, so it loads nothing;
- ``sync <type>`` and stopping it, when an admin asks (a worker_state request).

One child at a time, each allowed ``CATALOG_TASK_TIMEOUT_MINUTES`` before it is
stopped. A failure is logged; a sync that failed or was cut short is planned
again at the next check, as the in-process auto-sync always did. The child writes what an all-in-one
process writes, and the web process picks up a finished sync within a minute
(ProfileCatalogService.follow_syncs). Its memory goes back to the box when it
exits; it logs its peak.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.profile_catalog import (
    PROFILE_CATALOG_AUTO_SYNC_TYPES,
    auto_sync_plan,
    catalog_lookup,
)

logger = logging.getLogger(__name__)

# How long a stopped child gets to finish the page it is on before it is killed.
# Inside the worker's own stop_grace_period (docker-compose.prod.yml).
_TERM_GRACE_S = 20.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_sync_enabled() -> bool:
    return settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED


class CatalogTaskRunner:
    name = "catalog-tasks"

    def __init__(self, command: list[str] | None = None) -> None:
        # What starts a child, before the task's own words. Tests put a stand-in here.
        self._command = command or [sys.executable, "-m", "app.catalog_task"]
        self._lock = threading.Lock()
        self._queue: list[tuple[str, ...]] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._stop_child = threading.Event()
        self._check_now = True
        self._thread: threading.Thread | None = None
        self._current: dict[str, Any] | None = None
        self._last: dict[str, Any] | None = None
        self._plan: list[str] = []
        self._last_checked_at: str | None = None
        self._last_started_at: str | None = None

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            # The tests make their own catalog; there is nothing to publish from it.
            if settings.ENVIRONMENT != "test" and ("default-profiles",) not in self._queue:
                self._queue.append(("default-profiles",))
            self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
            self._thread.start()

    def stop(self, timeout: float = _TERM_GRACE_S + 5) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def wake(self) -> None:
        """Check whether the catalog is stale now rather than at the next tick."""
        self._check_now = True
        self._wake.set()

    def request(self, *task: str) -> None:
        """Run ``task`` when the child before it is done (once, however often asked)."""
        with self._lock:
            running = self._current is not None and tuple(self._current["task"]) == task
            if not running and task not in self._queue:
                self._queue.append(task)
        self._wake.set()

    def request_stop(self) -> None:
        """Stop the sync that is running and drop the ones waiting: the catalog
        page's stop button."""
        with self._lock:
            self._queue = [t for t in self._queue if t[0] not in ("sync", "auto-sync")]
            if self._current is not None and self._current["task"][0] in ("sync", "auto-sync"):
                self._stop_child.set()
        self._wake.set()

    # ---------------------------------------------------------------- state

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "current": dict(self._current) if self._current else None,
                "queued": [list(t) for t in self._queue],
                "last": dict(self._last) if self._last else None,
                "auto_sync_enabled": _auto_sync_enabled(),
                "auto_sync_plan": list(self._plan),
                "auto_sync_last_checked_at": self._last_checked_at,
                "auto_sync_last_started_at": self._last_started_at,
            }

    def catalog_status(self) -> dict[str, Any]:
        """What the catalog page shows (ProfileCatalogService.status's shape),
        without loading the catalog: the heartbeat carries it to the web process."""
        state = self.status()
        task = state["current"]["task"] if state["current"] else None
        auto_running = bool(task and task[0] == "auto-sync")
        return catalog_lookup().status(
            running_task=task,
            auto_sync={
                "auto_sync_enabled": state["auto_sync_enabled"],
                "auto_sync_running": auto_running,
                "auto_sync_loop_running": state["running"] and state["auto_sync_enabled"],
                "auto_sync_plan": state["auto_sync_plan"] if auto_running else [],
                "auto_sync_last_checked_at": state["auto_sync_last_checked_at"],
                "auto_sync_last_started_at": state["auto_sync_last_started_at"],
            },
        )

    # ---------------------------------------------------------------- the loop

    def _loop(self) -> None:
        logger.info("%s: started", self.name)
        next_check = time.monotonic()
        while not self._stop.is_set():
            with self._lock:
                task = self._queue.pop(0) if self._queue else None
                if task is not None:
                    # Taken and shown as current in one step, so a stop asked
                    # for from here on reaches it.
                    self._stop_child.clear()
                    self._current = {"task": list(task), "pid": None, "started_at": _now_iso()}
            if task is not None:
                self._run(task)
                continue
            now = time.monotonic()
            if self._check_now or now >= next_check:
                self._check_now = False
                next_check = now + max(1, int(settings.PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES)) * 60
                self._check_auto_sync()
                continue
            self._wake.wait(timeout=min(60.0, max(0.1, next_check - now)))
            self._wake.clear()
        logger.info("%s: stopped", self.name)

    def _check_auto_sync(self) -> None:
        if not _auto_sync_enabled():
            self._plan = []
            return
        now = datetime.now(timezone.utc)
        self._last_checked_at = now.isoformat()
        try:
            lookup = catalog_lookup()
            plan = auto_sync_plan(lookup.counts(), lookup.last_synced(), now)
        except FileNotFoundError:
            plan = list(PROFILE_CATALOG_AUTO_SYNC_TYPES)  # no catalog yet: the child builds it
        except Exception:
            logger.exception("%s: could not tell whether the catalog is stale", self.name)
            return
        self._plan = plan
        if plan:
            logger.info("%s: the catalog is stale (%s); syncing in a child", self.name, ", ".join(plan))
            self.request("auto-sync")

    def _run(self, task: tuple[str, ...]) -> None:
        started = time.monotonic()
        try:
            child = subprocess.Popen([*self._command, *task])
        except Exception as exc:
            logger.exception("%s: could not start %s", self.name, " ".join(task))
            self._finish(task, None, started, f"could not start: {exc}")
            return
        with self._lock:
            if self._current is not None:
                self._current["pid"] = child.pid
                if task[0] == "auto-sync":
                    self._last_started_at = self._current["started_at"]
        deadline = started + float(settings.CATALOG_TASK_TIMEOUT_MINUTES) * 60
        why = None
        while True:
            try:
                code = child.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                pass
            if self._stop.is_set():
                why = "stopped: the worker is stopping"
            elif self._stop_child.is_set():
                why = "stopped, as asked"
            elif time.monotonic() > deadline:
                why = f"timed out after {settings.CATALOG_TASK_TIMEOUT_MINUTES:g} min"
            if why:
                code = self._end(child)
                break
        self._finish(task, code, started, why)

    def _end(self, child: subprocess.Popen) -> int | None:
        child.terminate()
        try:
            return child.wait(timeout=_TERM_GRACE_S)
        except subprocess.TimeoutExpired:
            child.kill()
            return child.wait()

    def _finish(self, task: tuple[str, ...], code: int | None, started: float, why: str | None) -> None:
        outcome = why or ("done" if code == 0 else "failed")
        result = {
            "task": list(task),
            "exit": code,
            "outcome": outcome,
            "seconds": round(time.monotonic() - started, 1),
            "finished_at": _now_iso(),
        }
        if code == 0 and why is None:
            logger.info("%s: %s done in %.0fs", self.name, " ".join(task), result["seconds"])
        else:
            logger.warning("%s: %s %s (exit %s) after %.0fs", self.name, " ".join(task), outcome, code, result["seconds"])
        with self._lock:
            self._current = None
            self._last = result


_runner = CatalogTaskRunner()


def get_catalog_task_runner() -> CatalogTaskRunner:
    return _runner
