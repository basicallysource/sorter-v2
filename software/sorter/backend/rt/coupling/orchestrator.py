"""Runtime Orchestrator — builds the main-loop tick and wires slots.

Replaces the legacy ``Coordinator.step`` in ``subsystems/``: a daemon thread
ticks each runtime at a fixed cadence (default 20 ms / 50 Hz), downstream-
first so upstream runtimes see fresh capacity values. Per-runtime exceptions
are caught and logged so one misbehaving runtime cannot crash the main loop.

The orchestrator deliberately makes no assumptions about which runtimes are
wired in — Phase 3 passes C1/C2/C3, Phase 4 adds C4, Phase 5 adds the
Distributor. The only requirement is a consistent ordering (upstream->
downstream) and a slot per neighbour edge.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

from rt.contracts.events import EventBus
from rt.contracts.runtime import Runtime, RuntimeInbox
from rt.contracts.tracking import TrackBatch

from .slots import CapacitySlot


class TrackSource(Protocol):
    """Anything that can return the latest TrackBatch for a feed id.

    Keeps the orchestrator from depending on ``PerceptionRunner`` directly,
    which makes it trivial to mock in tests.
    """

    def latest_tracks(self) -> TrackBatch | None: ...


class Orchestrator:
    """Ticks runtimes on a daemon thread at a fixed cadence."""

    def __init__(
        self,
        *,
        runtimes: list[Runtime],
        slots: dict[tuple[str, str], CapacitySlot],
        perception_sources: dict[str, TrackSource] | None = None,
        event_bus: EventBus | None = None,
        logger: logging.Logger | None = None,
        tick_period_s: float = 0.020,
    ) -> None:
        if tick_period_s <= 0.0:
            raise ValueError("tick_period_s must be > 0")
        self._runtimes = list(runtimes)
        self._slots = dict(slots)
        self._perception: dict[str, TrackSource] = dict(perception_sources or {})
        self._bus = event_bus
        self._logger = logger or logging.getLogger("rt.orchestrator")
        self._tick_period_s = float(tick_period_s)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._paused = False
        self._tick_count = 0
        self._last_tick_mono: float = 0.0
        self._downstream_of = self._build_downstream_map()
        self._runtime_by_id = {rt.runtime_id: rt for rt in self._runtimes}

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self, *, paused: bool = False) -> None:
        if self._running:
            return
        self._paused = bool(paused)
        self._running = True
        self._stop.clear()
        for rt in self._runtimes:
            try:
                rt.start()
            except Exception:
                self._logger.exception(
                    "Orchestrator: runtime %r start() raised", rt.runtime_id
                )
        self._thread = threading.Thread(
            target=self._run, name="RuntimeOrchestrator", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        for rt in self._runtimes:
            try:
                rt.stop()
            except Exception:
                self._logger.exception(
                    "Orchestrator: runtime %r stop() raised", rt.runtime_id
                )
        self._paused = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Public introspection

    def tick_once(self, now_mono: float | None = None) -> None:
        """Run a single tick. Used by tests and by the main loop thread."""
        ts = time.monotonic() if now_mono is None else float(now_mono)
        self._tick(ts)

    def step(self, n: int = 1) -> dict[str, Any]:
        """Step the runtime forward by ``n`` ticks while paused.

        The orchestrator must be paused first so the daemon loop is parked
        and this caller is the sole writer of runtime state. ``n`` is
        bounded so a stray call cannot accidentally drain a long backlog;
        for long runs use ``resume()``.
        """
        if not self._paused:
            raise RuntimeError("orchestrator must be paused before stepping")
        steps = int(n)
        if steps < 1:
            raise ValueError("step n must be >= 1")
        if steps > 100:
            raise ValueError("step n must be <= 100; use resume() for long runs")
        started_count = self._tick_count
        for _ in range(steps):
            self._tick(time.monotonic())
        return {
            "ticks_executed": self._tick_count - started_count,
            "tick_count": self._tick_count,
            "last_tick_mono": self._last_tick_mono,
            "paused": self._paused,
        }

    def tick_count(self) -> int:
        return self._tick_count

    def register_perception_source(self, feed_id: str, source: TrackSource) -> None:
        """Install (or replace) a perception source after construction.

        Used when the detection-config endpoint rebuilds a runner with a
        new detector slug — the orchestrator tick must read from the fresh
        source, not the old one. Safe to call while ``start()``-ed.
        """
        self._perception[str(feed_id)] = source

    def health(self) -> dict[str, dict[str, object]]:
        """Aggregate per-runtime health into a flat dict."""
        out: dict[str, dict[str, object]] = {}
        for rt in self._runtimes:
            try:
                h = rt.health()
                out[rt.runtime_id] = {
                    "state": h.state,
                    "blocked_reason": h.blocked_reason,
                    "last_tick_ms": h.last_tick_ms,
                }
            except Exception:
                self._logger.exception(
                    "Orchestrator: health() raised for %r", rt.runtime_id
                )
                out[rt.runtime_id] = {"state": "error", "blocked_reason": "health_failed"}
        return out

    def status_snapshot(self) -> dict[str, Any]:
        runtime_debug: dict[str, dict[str, Any]] = {}
        for rt in self._runtimes:
            runtime_id = getattr(rt, "runtime_id", None)
            if not isinstance(runtime_id, str) or not runtime_id:
                continue
            debug_fn = getattr(rt, "debug_snapshot", None)
            if callable(debug_fn):
                try:
                    runtime_debug[runtime_id] = dict(debug_fn() or {})
                except Exception:
                    self._logger.exception(
                        "Orchestrator: debug_snapshot() raised for %r", runtime_id
                    )
                    runtime_debug[runtime_id] = {}

        slot_debug: dict[str, dict[str, int]] = {}
        now = time.monotonic()
        for (upstream, downstream), slot in self._slots.items():
            if not isinstance(upstream, str) or not isinstance(downstream, str):
                continue
            key = f"{upstream}_to_{downstream}"
            try:
                # Sweep expired claims on every status probe so the
                # dashboard doesn't lie about orphaned reservations.
                slot_debug[key] = {
                    "capacity": int(slot.capacity()),
                    "taken": int(slot.taken(now_mono=now)),
                    "available": int(slot.available(now_mono=now)),
                }
            except Exception:
                self._logger.exception(
                    "Orchestrator: slot debug snapshot raised for %s", key
                )
                slot_debug[key] = {}

        return {
            "runtime_health": self.health(),
            "runtime_debug": runtime_debug,
            "slot_debug": slot_debug,
        }

    def inspect_snapshot(self) -> dict[str, Any]:
        """Deep-introspect view for the step debugger.

        Returns the regular ``status_snapshot`` plus per-runtime detail
        intended for stepwise debugging: full dossier lists (not the
        five-row preview), pending downstream claims with their deadline
        ages, and per-slot claim deadlines. Every field is plain JSON —
        no raw runtime objects leak.
        """
        base = self.status_snapshot()
        now = time.monotonic()

        runtime_inspect: dict[str, dict[str, Any]] = {}
        for rt in self._runtimes:
            runtime_id = getattr(rt, "runtime_id", None)
            if not isinstance(runtime_id, str) or not runtime_id:
                continue
            inspect_fn = getattr(rt, "inspect_snapshot", None)
            if not callable(inspect_fn):
                continue
            try:
                runtime_inspect[runtime_id] = dict(inspect_fn(now_mono=now) or {})
            except Exception:
                self._logger.exception(
                    "Orchestrator: inspect_snapshot() raised for %r", runtime_id
                )
                runtime_inspect[runtime_id] = {"_error": "inspect_failed"}

        slot_inspect: dict[str, dict[str, Any]] = {}
        for (upstream, downstream), slot in self._slots.items():
            if not isinstance(upstream, str) or not isinstance(downstream, str):
                continue
            key = f"{upstream}_to_{downstream}"
            claims_attr = getattr(slot, "_claims", None)
            claims_view: list[dict[str, Any]] = []
            if isinstance(claims_attr, list):
                import math as _math
                for deadline in claims_attr:
                    if not isinstance(deadline, (int, float)):
                        continue
                    if _math.isinf(deadline):
                        claims_view.append({"deadline_age_s": None, "no_expiry": True})
                    else:
                        claims_view.append(
                            {"deadline_age_s": float(deadline) - now, "no_expiry": False}
                        )
            try:
                slot_inspect[key] = {
                    "capacity": int(slot.capacity()),
                    "taken": int(slot.taken(now_mono=now)),
                    "available": int(slot.available(now_mono=now)),
                    "claims": claims_view,
                }
            except Exception:
                self._logger.exception(
                    "Orchestrator: slot inspect snapshot raised for %s", key
                )
                slot_inspect[key] = {"_error": "inspect_failed"}

        base.update(
            {
                "tick_count": int(self._tick_count),
                "paused": bool(self._paused),
                "tick_period_s": float(self._tick_period_s),
                "runtime_inspect": runtime_inspect,
                "slot_inspect": slot_inspect,
                "now_mono": float(now),
            }
        )
        return base

    # ------------------------------------------------------------------
    # Internals

    def _build_downstream_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for (up, down) in self._slots.keys():
            mapping[up] = down
        return mapping

    def _capacity_for(self, runtime_id: str) -> int:
        downstream_id = self._downstream_of.get(runtime_id)
        if downstream_id is None:
            return 0
        slot = self._slots.get((runtime_id, downstream_id))
        if slot is None:
            return 0
        # Pass now_mono so expired claims are swept before the runtime tick
        # sees a "full" slot and blocks unnecessarily.
        slot_capacity = slot.available(now_mono=time.monotonic())
        downstream = self._runtime_by_id.get(downstream_id)
        if downstream is None:
            return slot_capacity
        try:
            downstream_capacity = max(0, int(downstream.available_slots()))
        except Exception:
            self._logger.exception(
                "Orchestrator: available_slots() raised for %r", downstream_id
            )
            return slot_capacity
        return min(slot_capacity, downstream_capacity)

    def _tick(self, now_mono: float) -> None:
        # Downstream-first so upstream runtimes see fresh capacity.
        for rt in reversed(self._runtimes):
            tracks: TrackBatch | None = None
            feed_id = getattr(rt, "feed_id", None)
            source = self._perception.get(feed_id) if feed_id is not None else None
            if source is not None:
                try:
                    tracks = source.latest_tracks()
                except Exception:
                    self._logger.exception(
                        "Orchestrator: track source for %s raised", feed_id
                    )
                    tracks = None
                # Runtimes that build piece crops (currently RuntimeC4)
                # need the raw FeedFrame alongside the track batch. Push
                # the latest frame from the perception runner so the
                # classification submit path isn't gated on a never-set
                # latest_frame — without this, C4 silently dropped every
                # classify attempt at _build_crop.
                set_frame = getattr(rt, "set_latest_frame", None)
                if callable(set_frame):
                    latest_state = getattr(source, "latest_state", None)
                    state = latest_state() if callable(latest_state) else None
                    frame = getattr(state, "frame", None)
                    if frame is not None:
                        try:
                            set_frame(frame)
                        except Exception:
                            self._logger.exception(
                                "Orchestrator: set_latest_frame raised for %r",
                                rt.runtime_id,
                            )
            capacity = self._capacity_for(rt.runtime_id)
            inbox = RuntimeInbox(tracks=tracks, capacity_downstream=capacity)
            try:
                rt.tick(inbox, now_mono)
            except Exception:
                self._logger.exception(
                    "Orchestrator: runtime %r tick raised", rt.runtime_id
                )
        self._tick_count += 1
        self._last_tick_mono = now_mono

    def _run(self) -> None:
        period = self._tick_period_s
        while not self._stop.is_set():
            if self._paused:
                self._stop.wait(timeout=min(period, 0.050))
                continue
            t0 = time.monotonic()
            try:
                self._tick(t0)
            except Exception:
                self._logger.exception("Orchestrator: _tick raised")
            elapsed = time.monotonic() - t0
            wait = period - elapsed
            if wait > 0:
                self._stop.wait(timeout=wait)
        self._running = False


__all__ = ["Orchestrator", "TrackSource"]
