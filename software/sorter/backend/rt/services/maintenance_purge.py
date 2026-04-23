"""C234 purge coordinator — rt maintenance service.

Arms every C-channel PurgePort top-down (C2 -> C3 -> C4), drives them in
parallel on a daemon thread, and only disarms each channel once every
upstream channel has already reported clear. That top-down invariant is
what keeps a late piece from C2 from landing on a just-stopped C3.

The coordinator owns its own state + cancel event + worker thread so that
``RtRuntimeHandle`` stays a pure composition root: no more purge-specific
fields, threads, or locks on the handle (Principle 3 — composition wires,
services coordinate). The handle forwards start/cancel/status through a
tiny pass-through.

Minimal coupling: a caller passes the iterable of purge-capable runtimes
and a small ``RuntimeControl`` protocol (``paused`` flag, ``pause()``,
``resume()``). The coordinator knows nothing about orchestrator,
perception, or bootstrap.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterable, Protocol

from rt.runtimes._strategies import GenericPurgeStrategy

_LOG = logging.getLogger(__name__)


class RuntimeControl(Protocol):
    """Minimal surface the coordinator needs to restore the pre-purge state.

    If the runtime was paused when purge started, we must resume it for the
    drain and then re-pause it on completion. The protocol is kept tiny so
    tests can substitute a ``MagicMock`` without monkey-patching the handle.
    """

    paused: bool

    def pause(self) -> None: ...

    def resume(self) -> None: ...


def _initial_status() -> dict[str, Any]:
    return {
        "active": False,
        "phase": "idle",
        "started_at": None,
        "finished_at": None,
        "success": None,
        "reason": None,
        "was_paused": None,
        "cancel_requested": False,
        "counts": {"c2": 0, "c3": 0, "c4_raw": 0, "c4_dossiers": 0},
    }


class C234PurgeCoordinator:
    """Owns the C234 purge thread + UI-facing status dict.

    One instance per ``RtRuntimeHandle``. Reusable across consecutive
    purges — ``start()`` rejects a second run while one is already active.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._status: dict[str, Any] = _initial_status()

    # ------------------------------------------------------------------ status

    def status(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._status)
            counts = snap.get("counts")
            if isinstance(counts, dict):
                snap["counts"] = dict(counts)
            return snap

    # ------------------------------------------------------------------ control

    def start(
        self,
        *,
        runtimes: Iterable[Any],
        control: RuntimeControl,
        state_publisher: Callable[[str], None] | None = None,
        timeout_s: float = 120.0,
        clear_hold_s: float = 0.75,
        poll_s: float = 0.05,
    ) -> bool:
        """Arm + drive a new purge. Returns ``False`` if one is already active."""
        if timeout_s <= 0.0:
            raise ValueError("timeout_s must be > 0")
        if clear_hold_s < 0.0:
            raise ValueError("clear_hold_s must be >= 0")
        if poll_s <= 0.0:
            raise ValueError("poll_s must be > 0")

        with self._lock:
            if bool(self._status.get("active")):
                return False
            self._status = {
                "active": True,
                "phase": "starting",
                "started_at": time.time(),
                "finished_at": None,
                "success": None,
                "reason": None,
                "was_paused": bool(getattr(control, "paused", False)),
                "cancel_requested": False,
                "counts": {"c2": 0, "c3": 0, "c4_raw": 0, "c4_dossiers": 0},
            }
            self._cancel.clear()
            thread = threading.Thread(
                target=self._run,
                kwargs={
                    "runtimes": list(runtimes),
                    "control": control,
                    "state_publisher": state_publisher,
                    "timeout_s": float(timeout_s),
                    "clear_hold_s": float(clear_hold_s),
                    "poll_s": float(poll_s),
                },
                name="RtC234Purge",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return True

    def cancel(self) -> bool:
        """Request graceful cancellation. Returns ``False`` if no purge is active."""
        with self._lock:
            if not bool(self._status.get("active")):
                return False
            next_status = dict(self._status)
            next_status["cancel_requested"] = True
            next_status["phase"] = "cancelling"
            self._status = next_status
            self._cancel.set()
            return True

    def request_cancel(self) -> None:
        """Unconditional cancel signal for shutdown paths. No-op if idle."""
        self._cancel.set()

    # ------------------------------------------------------------------ internals

    def _update_status(self, **updates: Any) -> None:
        with self._lock:
            next_status = dict(self._status)
            next_status.update(updates)
            counts = next_status.get("counts")
            if isinstance(counts, dict):
                next_status["counts"] = dict(counts)
            self._status = next_status

    @staticmethod
    def _collect_strategies(
        runtimes: list[Any], *, clear_hold_s: float
    ) -> list[GenericPurgeStrategy]:
        """Gather strategies in the order the caller supplied (top-down).

        Order matters — the coordinator enforces that a downstream channel
        may only disarm once all upstream channels have already disarmed,
        so a late piece from C2 never lands on a stopped C3.
        """
        strategies: list[GenericPurgeStrategy] = []
        for runtime in runtimes:
            if runtime is None:
                continue
            port_fn = getattr(runtime, "purge_port", None)
            if not callable(port_fn):
                continue
            try:
                port = port_fn()
            except Exception:
                _LOG.exception(
                    "C234PurgeCoordinator: purge_port() raised for %s",
                    getattr(runtime, "name", type(runtime).__name__),
                )
                continue
            strategies.append(
                GenericPurgeStrategy(port, clear_hold_ms=float(clear_hold_s) * 1000.0)
            )
        return strategies

    @staticmethod
    def _aggregate_counts(
        strategies: list[GenericPurgeStrategy],
    ) -> dict[str, int]:
        """Build the UI-facing counts dict from per-channel PurgePort snapshots.

        Output shape matches the contract consumed by AppHeader:
        ``{c2, c3, c4_raw, c4_dossiers}``.
        """
        counts = {"c2": 0, "c3": 0, "c4_raw": 0, "c4_dossiers": 0}
        for strat in strategies:
            try:
                snap = strat.port.counts()
            except Exception:
                _LOG.exception(
                    "C234PurgeCoordinator: purge port counts raised for %s",
                    strat.channel,
                )
                continue
            if strat.channel == "c2":
                counts["c2"] = int(snap.piece_count)
            elif strat.channel == "c3":
                counts["c3"] = int(snap.piece_count)
            elif strat.channel == "c4":
                counts["c4_raw"] = int(snap.piece_count)
                counts["c4_dossiers"] = int(snap.owned_count)
        return counts

    def _run(
        self,
        *,
        runtimes: list[Any],
        control: RuntimeControl,
        state_publisher: Callable[[str], None] | None,
        timeout_s: float,
        clear_hold_s: float,
        poll_s: float,
    ) -> None:
        was_paused = bool(getattr(control, "paused", False))
        deadline = time.monotonic() + float(timeout_s)
        success = False
        reason = "timeout"
        phase = "running"
        strategies = self._collect_strategies(runtimes, clear_hold_s=clear_hold_s)
        try:
            if not strategies:
                raise RuntimeError("no purge-capable runtimes available")
            for strat in strategies:
                strat.arm()
            if was_paused:
                control.resume()
                if callable(state_publisher):
                    try:
                        state_publisher("running")
                    except Exception:
                        _LOG.exception(
                            "C234PurgeCoordinator: state publisher raised during resume"
                        )
            while time.monotonic() < deadline:
                if self._cancel.is_set():
                    reason = "cancelled"
                    phase = "cancelled"
                    break
                now = time.monotonic()

                # Parallel drive: every armed strategy runs its tick.
                for strat in strategies:
                    if strat.is_armed:
                        try:
                            strat.tick(now)
                        except Exception:
                            _LOG.exception(
                                "C234PurgeCoordinator: tick raised for %s",
                                strat.channel,
                            )

                # Top-down disarm: a channel may only disarm once every
                # upstream strategy has finished draining.
                for idx, strat in enumerate(strategies):
                    if not strat.is_armed:
                        continue
                    upstream_done = all(not s.is_armed for s in strategies[:idx])
                    if upstream_done and strat.is_channel_clear(now):
                        try:
                            strat.disarm()
                        except Exception:
                            _LOG.exception(
                                "C234PurgeCoordinator: disarm raised for %s",
                                strat.channel,
                            )

                counts = self._aggregate_counts(strategies)
                all_done = all(not s.is_armed for s in strategies)
                if all_done:
                    success = True
                    reason = "cleared"
                    phase = "idle"
                else:
                    phase = (
                        "verifying_clear"
                        if all(
                            s.is_channel_clear(now) or not s.is_armed
                            for s in strategies
                        )
                        else "purging"
                    )
                self._update_status(
                    active=True,
                    phase=phase,
                    cancel_requested=False,
                    counts=counts,
                )
                if all_done:
                    break
                time.sleep(float(poll_s))
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            _LOG.exception("C234PurgeCoordinator: c234 purge failed")
        finally:
            # Safety net: force-disarm anything still armed on timeout/cancel.
            for strat in strategies:
                if strat.is_armed:
                    try:
                        strat.disarm()
                    except Exception:
                        _LOG.exception(
                            "C234PurgeCoordinator: final disarm raised for %s",
                            strat.channel,
                        )
            if was_paused:
                try:
                    control.pause()
                except Exception:
                    _LOG.exception(
                        "C234PurgeCoordinator: control.pause raised"
                    )
                if callable(state_publisher):
                    try:
                        state_publisher("paused")
                    except Exception:
                        _LOG.exception(
                            "C234PurgeCoordinator: state publisher raised during pause"
                        )
            self._update_status(
                active=False,
                phase="idle" if success else phase,
                finished_at=time.time(),
                success=success,
                reason=reason,
                cancel_requested=False,
            )


__all__ = ["C234PurgeCoordinator", "RuntimeControl"]
