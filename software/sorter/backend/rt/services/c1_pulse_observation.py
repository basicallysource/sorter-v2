"""C1 pulse-response observer.

Logs each C1 dispatch event (pulse or recovery) together with the C2/C4
state at three checkpoints: at dispatch, +1 s after, and +3 s after. The
result is a per-pulse record we can later use to build empirical
``q50/q95/q99`` output distributions per action — i.e. how many pieces a
given C1 action actually puts on C2.

The observer is intentionally side-effect light:

* It does **not** change runtime behaviour.
* It does **not** require a hardware roundtrip.
* It only stores recent observations in memory and (optionally) writes
  completed records to a JSONL file for offline analysis.

These records provide empirical input for C1 controller tuning instead of
guessing how many pieces each C1 action actually puts on C2.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


SnapshotProvider = Callable[[], dict[str, Any]]


@dataclass(slots=True)
class _PulseObservation:
    """One in-flight or completed pulse observation."""

    pulse_id: int
    action_id: str
    dispatched_at_mono: float
    dispatched_at_wall: float
    pre: dict[str, Any]
    t1_deadline_mono: float
    t3_deadline_mono: float
    t1: dict[str, Any] | None = None
    t3: dict[str, Any] | None = None
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pulse_id": self.pulse_id,
            "action_id": self.action_id,
            "dispatched_at_mono": self.dispatched_at_mono,
            "dispatched_at_wall": self.dispatched_at_wall,
            "pre": dict(self.pre),
            "t1": dict(self.t1) if self.t1 is not None else None,
            "t3": dict(self.t3) if self.t3 is not None else None,
            "delta_t1": self._delta(self.t1) if self.t1 is not None else None,
            "delta_t3": self._delta(self.t3) if self.t3 is not None else None,
            "completed": bool(self.completed),
        }

    def _delta(self, sample: dict[str, Any]) -> dict[str, Any]:
        """Compute deltas between ``pre`` and a ``post`` sample.

        Only deltas that are meaningful for C1's observation goal are
        emitted; keys that are not numeric in ``pre`` are skipped.
        """
        out: dict[str, Any] = {}
        for key, before in self.pre.items():
            after = sample.get(key)
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                out[key] = float(after) - float(before)
        return out


class C1PulseObserver:
    """Records C1 dispatch events + post-dispatch C2/C4 state samples.

    Thread-safety: ``record_dispatch`` is callable from any thread (the
    runtime's own worker thread typically), while ``tick`` runs from the
    orchestrator. A simple lock protects the in-flight buffer; the
    completed-record ring is also lock-protected so ``recent()`` is safe
    to call from API handlers.
    """

    DEFAULT_T1_S = 1.0
    DEFAULT_T3_S = 3.0
    DEFAULT_HISTORY = 200

    def __init__(
        self,
        *,
        snapshot_provider: SnapshotProvider,
        log_path: Path | str | None = None,
        history_limit: int = DEFAULT_HISTORY,
        t1_s: float = DEFAULT_T1_S,
        t3_s: float = DEFAULT_T3_S,
        logger: logging.Logger | None = None,
    ) -> None:
        if t1_s <= 0.0:
            raise ValueError("t1_s must be > 0")
        if t3_s <= t1_s:
            raise ValueError("t3_s must be > t1_s")
        self._provider = snapshot_provider
        self._log_path = Path(log_path) if log_path is not None else None
        self._history_limit = max(1, int(history_limit))
        self._t1_s = float(t1_s)
        self._t3_s = float(t3_s)
        self._logger = logger or logging.getLogger("rt.c1_pulse_observer")
        self._lock = threading.Lock()
        self._next_id = 1
        self._in_flight: list[_PulseObservation] = []
        self._completed: list[_PulseObservation] = []

    # ------------------------------------------------------------------
    # Public API

    def record_dispatch(self, action_id: str, *, now_mono: float | None = None) -> int:
        """Capture pre-state and start a new observation.

        Returns the assigned ``pulse_id``. Safe to call from any thread.
        """
        try:
            pre = dict(self._provider() or {})
        except Exception:
            self._logger.exception(
                "C1PulseObserver: snapshot provider raised at dispatch"
            )
            pre = {}
        ts = time.monotonic() if now_mono is None else float(now_mono)
        wall = time.time()
        with self._lock:
            pulse_id = self._next_id
            self._next_id += 1
            obs = _PulseObservation(
                pulse_id=pulse_id,
                action_id=str(action_id),
                dispatched_at_mono=ts,
                dispatched_at_wall=wall,
                pre=pre,
                t1_deadline_mono=ts + self._t1_s,
                t3_deadline_mono=ts + self._t3_s,
            )
            self._in_flight.append(obs)
        return pulse_id

    def tick(self, now_mono: float | None = None) -> None:
        """Advance in-flight observations: capture t1 / t3 when due."""
        ts = time.monotonic() if now_mono is None else float(now_mono)
        try:
            current = dict(self._provider() or {})
        except Exception:
            self._logger.exception("C1PulseObserver: snapshot provider raised at tick")
            current = {}
        completed_now: list[_PulseObservation] = []
        with self._lock:
            for obs in self._in_flight:
                if obs.t1 is None and ts >= obs.t1_deadline_mono:
                    obs.t1 = dict(current)
                if obs.t3 is None and ts >= obs.t3_deadline_mono:
                    obs.t3 = dict(current)
                    obs.completed = True
            still_in_flight = [obs for obs in self._in_flight if not obs.completed]
            completed_now = [obs for obs in self._in_flight if obs.completed]
            self._in_flight = still_in_flight
            self._completed.extend(completed_now)
            if len(self._completed) > self._history_limit:
                drop = len(self._completed) - self._history_limit
                self._completed = self._completed[drop:]
        for obs in completed_now:
            self._maybe_persist(obs)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent completed observations as plain dicts."""
        cap = max(1, int(limit))
        with self._lock:
            window = self._completed[-cap:]
            return [obs.to_dict() for obs in window]

    def in_flight(self) -> list[dict[str, Any]]:
        """Return currently in-flight (uncompleted) observations."""
        with self._lock:
            return [obs.to_dict() for obs in self._in_flight]

    def summary(self) -> dict[str, Any]:
        """Lightweight aggregate suitable for the inspect/status snapshot."""
        with self._lock:
            return {
                "in_flight_count": int(len(self._in_flight)),
                "completed_count": int(len(self._completed)),
                "t1_s": float(self._t1_s),
                "t3_s": float(self._t3_s),
                "log_path": str(self._log_path) if self._log_path else None,
            }

    # ------------------------------------------------------------------
    # Internals

    def _maybe_persist(self, obs: _PulseObservation) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(obs.to_dict(), separators=(",", ":")) + "\n")
        except Exception:
            self._logger.exception(
                "C1PulseObserver: failed to persist pulse %d to %s",
                obs.pulse_id,
                self._log_path,
            )


__all__ = ["C1PulseObserver"]
