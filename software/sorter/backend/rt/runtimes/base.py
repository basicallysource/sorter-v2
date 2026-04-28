"""Shared runtime helpers: `HwWorker` + `BaseRuntime`.

`HwWorker` — per-runtime background thread for blocking hardware calls
(stepper `move_degrees_blocking`, jam-recovery shake sequences). The main
orchestrator tick thread never blocks on hardware; it just enqueues a
`Callable[[], None]` and moves on. The worker catches exceptions so the
thread never crashes.

`BaseRuntime` — small base providing `runtime_id`, `feed_id`, a mutable
`_health` snapshot, and a convenience `stop()`/`start()` that wires the
optional `HwWorker`. Concrete runtimes in `c1.py`/`c2.py`/`c3.py` inherit
from it to avoid duplicating lifecycle boilerplate.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from rt.contracts.runtime import Runtime, RuntimeHealth


_WORKER_QUEUE_MAX = 4


@dataclass(slots=True)
class _Command:
    priority: int
    seq: int
    fn: Callable[[], None]
    label: str


class HwWorker:
    """Daemon thread consuming blocking hardware commands off a bounded queue."""

    def __init__(self, runtime_id: str, logger: logging.Logger | None = None) -> None:
        self.runtime_id = runtime_id
        self._logger = logger or logging.getLogger(f"rt.hw.{runtime_id}")
        self._queue: queue.Queue[_Command | None] = queue.Queue(maxsize=_WORKER_QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._running = False
        self._seq = 0
        self._busy = False
        self._busy_lock = threading.Lock()

    def start(self) -> None:
        thread = self._thread
        if self._running and thread is not None and thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name=f"HwWorker[{self.runtime_id}]",
            daemon=True,
        )
        self._thread.start()

    def status_snapshot(self) -> dict[str, Any]:
        thread = self._thread
        return {
            "running": bool(self._running),
            "thread_alive": bool(thread is not None and thread.is_alive()),
            "pending": int(self.pending()),
            "busy": bool(self.busy()),
        }

    def stop(self, timeout_s: float = 2.0) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # Pop something to make room for the sentinel.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout_s)
        self._thread = None

    def enqueue(
        self,
        command: Callable[[], None],
        *,
        priority: int = 0,
        label: str = "hw_cmd",
    ) -> bool:
        """Enqueue a command. Returns False if the queue is full (caller may retry)."""
        self._ensure_thread_alive(reason=f"enqueue:{label}")
        self._seq += 1
        cmd = _Command(priority=int(priority), seq=self._seq, fn=command, label=str(label))
        try:
            self._queue.put_nowait(cmd)
            return True
        except queue.Full:
            self._logger.warning(
                "HwWorker[%s] queue full; dropping command %r",
                self.runtime_id,
                label,
            )
            return False

    def busy(self) -> bool:
        """True iff a command is currently executing."""
        with self._busy_lock:
            return self._busy

    def pending(self) -> int:
        """Approximate queue depth (excluding the in-flight command)."""
        pending = self._queue.qsize()
        if pending > 0 and self._running:
            self._ensure_thread_alive(reason="pending_backlog")
        return pending

    def _ensure_thread_alive(self, *, reason: str) -> None:
        thread = self._thread
        if self._running and thread is not None and thread.is_alive():
            return
        self._logger.warning(
            "HwWorker[%s] thread was not alive (%s); restarting",
            self.runtime_id,
            reason,
        )
        self.start()

    def _run(self) -> None:
        while self._running:
            try:
                cmd = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if cmd is None:
                if not self._running:
                    break
                # A sentinel can be left behind if stop() raced with a restart
                # while commands were already queued. In a live worker it is stale.
                continue
            with self._busy_lock:
                self._busy = True
            try:
                cmd.fn()
            except Exception:
                self._logger.exception(
                    "HwWorker[%s] command %r raised",
                    self.runtime_id,
                    cmd.label,
                )
            finally:
                with self._busy_lock:
                    self._busy = False


class BaseRuntime(Runtime):
    """Lifecycle boilerplate shared by RuntimeC1/C2/C3."""

    runtime_id: str
    feed_id: str | None

    def __init__(
        self,
        runtime_id: str,
        *,
        feed_id: str | None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        state_observer: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self.feed_id = feed_id
        self._logger = logger or logging.getLogger(f"rt.runtime.{runtime_id}")
        self._hw: HwWorker = hw_worker or HwWorker(runtime_id, self._logger)
        self._state: str = "idle"
        self._blocked_reason: str | None = None
        self._last_tick_ms: float = 0.0
        self._last_tick_start: float | None = None
        # Optional observer invoked on every FSM transition: callback receives
        # (runtime_id, from_state, to_state). Used to bridge rt FSM transitions
        # into RuntimeStatsCollector so the runtime widget can show them.
        self._state_observer = state_observer

    # -- Lifecycle ---------------------------------------------------

    def start(self) -> None:
        self._hw.start()

    def stop(self) -> None:
        self._hw.stop()

    # -- Health ------------------------------------------------------

    def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            state=self._state,
            blocked_reason=self._blocked_reason,
            last_tick_ms=self._last_tick_ms,
        )

    def _set_state(self, state: str, *, blocked_reason: str | None = None) -> None:
        prev = self._state
        self._state = state
        self._blocked_reason = blocked_reason
        observer = self._state_observer
        if observer is not None and prev != state:
            try:
                observer(self.runtime_id, prev, state)
            except Exception:
                self._logger.exception(
                    "BaseRuntime[%s]: state_observer raised on %s -> %s",
                    self.runtime_id, prev, state,
                )

    def debug_snapshot(self) -> dict[str, Any]:
        """Compact runtime-local state for API/operator diagnostics."""
        return {
            "state": self._state,
            "blocked_reason": self._blocked_reason,
            "last_tick_ms": self._last_tick_ms,
            "hw_busy": bool(self._hw.busy()),
            "hw_pending": int(self._hw.pending()),
            "hw_worker": self._hw_status_snapshot(),
        }

    def _hw_status_snapshot(self) -> dict[str, Any]:
        snapshot_fn = getattr(self._hw, "status_snapshot", None)
        if callable(snapshot_fn):
            try:
                snapshot = snapshot_fn()
                if isinstance(snapshot, dict):
                    return dict(snapshot)
            except Exception:
                self._logger.exception(
                    "BaseRuntime[%s]: hw status_snapshot raised", self.runtime_id
                )
        return {
            "running": None,
            "thread_alive": None,
            "pending": int(self._hw.pending()),
            "busy": bool(self._hw.busy()),
        }

    # -- Tick helpers ------------------------------------------------

    def _tick_begin(self) -> float:
        now = time.monotonic()
        self._last_tick_start = now
        return now

    def _tick_end(self, start_mono: float) -> None:
        self._last_tick_ms = (time.monotonic() - start_mono) * 1000.0

    # -- Defaults ----------------------------------------------------

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # Default no-op; concrete runtimes override where meaningful.
        return None


__all__ = ["HwWorker", "BaseRuntime"]
