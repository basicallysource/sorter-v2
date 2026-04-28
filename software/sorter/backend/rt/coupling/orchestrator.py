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


_C1_C2_VISION_TARGET_LOW = 1
_C1_C2_VISION_TARGET_HIGH = 3
_C1_C2_VISION_CLUMP_BLOCK_THRESHOLD = 0.65
_C1_C2_VISION_EXIT_QUEUE_LIMIT = 1
_C1_C4_BACKPRESSURE_RAW_HIGH = 7
_C1_C4_BACKPRESSURE_DOSSIER_HIGH = 3
# Hysteresis: once the C4 backlog gate has fired, C1 stays inhibited until
# both backlog signals drop to/below the resume thresholds. Picking
# resume = high - 3 / high - 2 leaves a real dwell window so C1 cannot
# unblock between two distributor cycles.
_C1_C4_BACKPRESSURE_RAW_RESUME = 4
_C1_C4_BACKPRESSURE_DOSSIER_RESUME = 1
# Headroom-gated C1 jam-recovery defaults. Level estimates are q95 piece
# counts that the corresponding recovery push is expected to deliver onto
# C2 in the worst case. Initial values are conservative seed numbers
# until the pulse-response observer collects enough live samples to
# replace them. ``c2_safe_capacity_eq`` is the maximum equivalent piece
# count C2 can absorb without entering an unsafe load state.
_C1_RECOVERY_ADMISSION_ENABLED = True
_C1_RECOVERY_C2_SAFE_CAPACITY_EQ = 14
_C1_RECOVERY_LEVEL_ESTIMATES_EQ: tuple[int, ...] = (3, 6, 12, 25, 40)


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
        c1_c2_vision_target_low: int = _C1_C2_VISION_TARGET_LOW,
        c1_c2_vision_target_high: int = _C1_C2_VISION_TARGET_HIGH,
        c1_c2_vision_clump_block_threshold: float = _C1_C2_VISION_CLUMP_BLOCK_THRESHOLD,
        c1_c2_vision_exit_queue_limit: int = _C1_C2_VISION_EXIT_QUEUE_LIMIT,
        c1_c4_backpressure_raw_high: int = _C1_C4_BACKPRESSURE_RAW_HIGH,
        c1_c4_backpressure_dossier_high: int = _C1_C4_BACKPRESSURE_DOSSIER_HIGH,
        c1_c4_backpressure_raw_resume: int = _C1_C4_BACKPRESSURE_RAW_RESUME,
        c1_c4_backpressure_dossier_resume: int = _C1_C4_BACKPRESSURE_DOSSIER_RESUME,
        c1_recovery_admission_enabled: bool = _C1_RECOVERY_ADMISSION_ENABLED,
        c1_recovery_c2_safe_capacity_eq: int = _C1_RECOVERY_C2_SAFE_CAPACITY_EQ,
        c1_recovery_level_estimates_eq: tuple[int, ...] = _C1_RECOVERY_LEVEL_ESTIMATES_EQ,
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
        self._capacity_debug: dict[str, dict[str, Any]] = {}
        self._flow_gate_totals_s: dict[str, float] = {}
        self._flow_gate_current: dict[str, str] = {}
        self._flow_gate_last_observed_at: float | None = None
        self.update_c1_c2_vision_controller(
            target_low=c1_c2_vision_target_low,
            target_high=c1_c2_vision_target_high,
            clump_block_threshold=c1_c2_vision_clump_block_threshold,
            exit_queue_limit=c1_c2_vision_exit_queue_limit,
        )
        self._c1_c4_backpressure_blocked = False
        self.update_c1_c4_backpressure(
            raw_high=c1_c4_backpressure_raw_high,
            dossier_high=c1_c4_backpressure_dossier_high,
            raw_resume=c1_c4_backpressure_raw_resume,
            dossier_resume=c1_c4_backpressure_dossier_resume,
        )
        self._c1_pulse_observer: Any | None = None
        # Same idea for C4: default ``"runtime"`` keeps RuntimeC4 as a
        # maintenance fallback. Production bootstrap switches this to
        # ``"sector_carousel"`` and delegates C4 motion/eject ownership to
        # the five-sector scheduler while RuntimeC4 continues perception,
        # classification, and dossier bookkeeping.
        self._sector_carousel_handler: Any | None = None
        self._c4_mode: str = "runtime"
        self._last_c1_recovery_decision: dict[str, Any] | None = None
        self._c1_recovery_admission_enabled = True
        self._c1_recovery_c2_safe_capacity_eq = 14
        self._c1_recovery_level_estimates_eq: tuple[int, ...] = (3, 6, 12, 25, 40)
        self.update_c1_recovery_admission(
            enabled=c1_recovery_admission_enabled,
            c2_safe_capacity_eq=c1_recovery_c2_safe_capacity_eq,
            level_estimates_eq=c1_recovery_level_estimates_eq,
        )

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

    def c1_recovery_admission_snapshot(self) -> dict[str, Any]:
        """Live tunables for the headroom-gated C1 jam-recovery escalation."""
        return {
            "name": "c1_recovery_admission",
            "enabled": bool(self._c1_recovery_admission_enabled),
            "c2_safe_capacity_eq": int(self._c1_recovery_c2_safe_capacity_eq),
            "level_estimates_eq": list(self._c1_recovery_level_estimates_eq),
            "last_decision": (
                dict(self._last_c1_recovery_decision)
                if self._last_c1_recovery_decision
                else None
            ),
        }

    def update_c1_recovery_admission(
        self,
        *,
        enabled: bool | None = None,
        c2_safe_capacity_eq: int | None = None,
        level_estimates_eq: tuple[int, ...] | list[int] | None = None,
    ) -> dict[str, Any]:
        if enabled is not None:
            self._c1_recovery_admission_enabled = bool(enabled)
        if c2_safe_capacity_eq is not None:
            self._c1_recovery_c2_safe_capacity_eq = self._bounded_int(
                c2_safe_capacity_eq,
                "c2_safe_capacity_eq",
                min_value=1,
                max_value=200,
            )
        if level_estimates_eq is not None:
            try:
                values = [int(v) for v in level_estimates_eq]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "level_estimates_eq must be a list of ints"
                ) from exc
            if not values:
                raise ValueError("level_estimates_eq must not be empty")
            for n in values:
                if n < 0 or n > 500:
                    raise ValueError(
                        "level_estimates_eq entries must be between 0 and 500"
                    )
            # Estimates must be monotonically non-decreasing — escalation
            # without a non-decreasing q95 makes no physical sense and
            # would let a higher level pass admission while a lower one
            # is blocked.
            for prev, cur in zip(values, values[1:]):
                if cur < prev:
                    raise ValueError(
                        "level_estimates_eq must be non-decreasing"
                    )
            self._c1_recovery_level_estimates_eq = tuple(values)
        return self.c1_recovery_admission_snapshot()

    def c1_recovery_admission_decision(self, level: int) -> tuple[bool, dict[str, Any]]:
        """Decide whether C1 may run recovery level ``level`` right now.

        Returns ``(allowed, info)``. ``info`` is always populated with
        the inputs to the decision (current C2 load, headroom, level
        estimate, admission state) so it can be surfaced in the runtime
        snapshot or the pulse-response log.
        """
        info: dict[str, Any] = {"level": int(level)}
        if not self._c1_recovery_admission_enabled:
            info.update({"enabled": False, "reason": "admission_disabled"})
            self._last_c1_recovery_decision = dict(info)
            return True, info

        snapshot = self.cross_runtime_snapshot()
        c2_load_eq = self._safe_int(snapshot.get("c2_piece_count_estimate"))
        c2_safe_capacity = int(self._c1_recovery_c2_safe_capacity_eq)
        headroom_eq = max(0, c2_safe_capacity - c2_load_eq)
        estimates = self._c1_recovery_level_estimates_eq
        idx = max(0, min(int(level), len(estimates) - 1))
        level_estimate_eq = int(estimates[idx])

        allowed = level_estimate_eq <= headroom_eq
        info.update(
            {
                "enabled": True,
                "c2_load_eq": int(c2_load_eq),
                "c2_safe_capacity_eq": c2_safe_capacity,
                "headroom_eq": int(headroom_eq),
                "level_estimate_eq": level_estimate_eq,
                "allowed": bool(allowed),
                "reason": (
                    "ok" if allowed else "insufficient_c2_headroom"
                ),
            }
        )
        self._last_c1_recovery_decision = dict(info)
        return allowed, info

    def attach_sector_carousel_handler(self, handler: Any) -> None:
        """Install the five-slot C4 sector carousel handler."""
        self._sector_carousel_handler = handler
        if self._c4_mode == "sector_carousel":
            self._apply_c4_mode_side_effects()

    def c4_mode(self) -> str:
        return str(self._c4_mode)

    def set_c4_mode(self, mode: str) -> str:
        """``"runtime"`` maintenance fallback or ``"sector_carousel"``."""
        normalized = str(mode or "").strip().lower()
        if normalized not in {"runtime", "sector_carousel"}:
            raise ValueError(
                f"c4_mode must be 'runtime' or 'sector_carousel', got {mode!r}"
            )
        if normalized == "sector_carousel" and self._sector_carousel_handler is None:
            raise RuntimeError(
                "sector carousel handler is not attached; cannot switch to sector_carousel mode"
            )
        previous = self._c4_mode
        if previous == normalized:
            self._apply_c4_mode_side_effects()
            return normalized
        self._c4_mode = normalized
        self._apply_c4_mode_side_effects()
        return normalized

    def _apply_c4_mode_side_effects(self) -> None:
        normalized = str(self._c4_mode)
        c4 = self._runtime_by_id.get("c4")
        if c4 is not None:
            set_carousel_mode = getattr(c4, "set_carousel_mode_active", None)
            if callable(set_carousel_mode):
                try:
                    set_carousel_mode(normalized == "sector_carousel")
                except Exception:
                    self._logger.exception(
                        "Orchestrator: c4.set_carousel_mode_active raised"
                    )
        c3 = self._runtime_by_id.get("c3")
        if c3 is not None:
            set_lease = getattr(c3, "set_landing_lease_port", None)
            if callable(set_lease):
                try:
                    if normalized == "sector_carousel" and self._sector_carousel_handler is not None:
                        port_fn = getattr(
                            self._sector_carousel_handler,
                            "landing_lease_port",
                            None,
                        )
                        set_lease(port_fn() if callable(port_fn) else None)
                    elif c4 is not None:
                        port_fn = getattr(c4, "landing_lease_port", None)
                        set_lease(port_fn() if callable(port_fn) else None)
                    else:
                        set_lease(None)
                except Exception:
                    self._logger.exception(
                        "Orchestrator: c3.set_landing_lease_port raised"
                    )
        sector_handler = self._sector_carousel_handler
        if sector_handler is not None:
            try:
                if normalized == "sector_carousel":
                    sector_handler.enable()
                else:
                    sector_handler.disable()
            except Exception:
                self._logger.exception(
                    "Orchestrator: sector carousel handler enable/disable raised"
                )

    def attach_c1_pulse_observer(self, observer: Any) -> None:
        """Install the C1 pulse-response observer.

        The observer is ticked from inside the main loop so its t1/t3
        deadlines advance at the same cadence as the runtime gates. The
        observer is responsible for pulling C2/C4 snapshots via the
        ``cross_runtime_snapshot`` callable below; we hand it a closure
        rather than a back-reference to keep the API surface small.
        """
        self._c1_pulse_observer = observer

    def cross_runtime_snapshot(self) -> dict[str, Any]:
        """Compact dict of C2/C4 fields the C1 pulse observer cares about.

        Kept tight on purpose: only the metrics that influence whether a
        C1 dispatch was the right call. Adding fields here is cheap, but
        every additional field shows up in every persisted JSONL row.
        """
        out: dict[str, Any] = {}
        c2 = self._runtime_by_id.get("c2")
        if c2 is not None:
            try:
                c2_dbg = dict(c2.capacity_debug_snapshot() or {})
            except Exception:
                self._logger.exception(
                    "Orchestrator: c2.capacity_debug_snapshot() raised"
                )
                c2_dbg = {}
            density = c2_dbg.get("density")
            if isinstance(density, dict):
                for key in (
                    "piece_count_estimate",
                    "occupancy_area_px",
                    "clump_score",
                    "free_arc_fraction",
                    "exit_queue_length",
                ):
                    value = density.get(key)
                    if isinstance(value, (int, float)):
                        out[f"c2_{key}"] = float(value)
            visible = c2_dbg.get("visible_track_count")
            if isinstance(visible, (int, float)):
                out["c2_visible_track_count"] = float(visible)
        c4 = self._runtime_by_id.get("c4")
        if c4 is not None:
            try:
                c4_dbg = dict(c4.debug_snapshot() or {})
            except Exception:
                self._logger.exception("Orchestrator: c4.debug_snapshot() raised")
                c4_dbg = {}
            for src_key, dst_key in (
                ("raw_detection_count", "c4_raw_detection_count"),
                ("raw_track_count", "c4_raw_track_count"),
                ("dossier_count", "c4_dossier_count"),
            ):
                value = c4_dbg.get(src_key)
                if isinstance(value, (int, float)):
                    out[dst_key] = float(value)
        return out

    def register_perception_source(self, feed_id: str, source: TrackSource) -> None:
        """Install (or replace) a perception source after construction.

        Used when the detection-config endpoint rebuilds a runner with a
        new detector slug — the orchestrator tick must read from the fresh
        source, not the old one. Safe to call while ``start()``-ed.
        """
        self._perception[str(feed_id)] = source

    def c1_c2_vision_controller_snapshot(self) -> dict[str, Any]:
        """Return the live C1 bulk-feed backpressure thresholds."""

        return {
            "name": "c1_c2_vision_burst",
            "target_low": int(self._c1_c2_vision_target_low),
            "target_high": int(self._c1_c2_vision_target_high),
            "clump_block_threshold": float(self._c1_c2_vision_clump_block_threshold),
            "exit_queue_limit": int(self._c1_c2_vision_exit_queue_limit),
        }

    def update_c1_c2_vision_controller(
        self,
        *,
        target_low: int | None = None,
        target_high: int | None = None,
        clump_block_threshold: float | None = None,
        exit_queue_limit: int | None = None,
    ) -> dict[str, Any]:
        """Tune the C1 stochastic-dose gate used against C2 density."""

        next_low = (
            self._bounded_int(target_low, "target_low", min_value=0, max_value=30)
            if target_low is not None
            else int(getattr(self, "_c1_c2_vision_target_low", _C1_C2_VISION_TARGET_LOW))
        )
        next_high = (
            self._bounded_int(target_high, "target_high", min_value=1, max_value=30)
            if target_high is not None
            else int(getattr(self, "_c1_c2_vision_target_high", _C1_C2_VISION_TARGET_HIGH))
        )
        next_exit_queue = (
            self._bounded_int(
                exit_queue_limit,
                "exit_queue_limit",
                min_value=0,
                max_value=30,
            )
            if exit_queue_limit is not None
            else int(
                getattr(
                    self,
                    "_c1_c2_vision_exit_queue_limit",
                    _C1_C2_VISION_EXIT_QUEUE_LIMIT,
                )
            )
        )
        next_clump = (
            self._bounded_float(
                clump_block_threshold,
                "clump_block_threshold",
                min_value=0.0,
                # Upper bound > 1.0 leaves headroom to *disable* the
                # clump gate without removing the field — set 1.5+ to
                # effectively skip the check, since clump_score is in
                # [0, 1]. Live evidence (sector shadow observer) showed
                # the gate creating a deadlock when 3 pieces stick in
                # a single C2 sector.
                max_value=2.0,
            )
            if clump_block_threshold is not None
            else float(
                getattr(
                    self,
                    "_c1_c2_vision_clump_block_threshold",
                    _C1_C2_VISION_CLUMP_BLOCK_THRESHOLD,
                )
            )
        )
        if next_high < max(1, next_low):
            raise ValueError("target_high must be >= target_low")

        self._c1_c2_vision_target_low = next_low
        self._c1_c2_vision_target_high = next_high
        self._c1_c2_vision_clump_block_threshold = next_clump
        self._c1_c2_vision_exit_queue_limit = next_exit_queue
        return self.c1_c2_vision_controller_snapshot()

    def c1_c4_backpressure_snapshot(self) -> dict[str, Any]:
        """Return the live C1 backpressure thresholds derived from C4 backlog."""

        return {
            "name": "c1_c4_backpressure",
            "raw_high": int(self._c1_c4_backpressure_raw_high),
            "dossier_high": int(self._c1_c4_backpressure_dossier_high),
            "raw_resume": int(self._c1_c4_backpressure_raw_resume),
            "dossier_resume": int(self._c1_c4_backpressure_dossier_resume),
            "blocked": bool(self._c1_c4_backpressure_blocked),
        }

    def update_c1_c4_backpressure(
        self,
        *,
        raw_high: int | None = None,
        dossier_high: int | None = None,
        raw_resume: int | None = None,
        dossier_resume: int | None = None,
    ) -> dict[str, Any]:
        """Tune the C1 bulk-feed stop line for downstream C4 backlog."""

        next_raw_high = (
            self._bounded_int(raw_high, "raw_high", min_value=1, max_value=50)
            if raw_high is not None
            else int(
                getattr(
                    self,
                    "_c1_c4_backpressure_raw_high",
                    _C1_C4_BACKPRESSURE_RAW_HIGH,
                )
            )
        )
        next_dossier_high = (
            self._bounded_int(dossier_high, "dossier_high", min_value=1, max_value=50)
            if dossier_high is not None
            else int(
                getattr(
                    self,
                    "_c1_c4_backpressure_dossier_high",
                    _C1_C4_BACKPRESSURE_DOSSIER_HIGH,
                )
            )
        )
        next_raw_resume = (
            self._bounded_int(raw_resume, "raw_resume", min_value=0, max_value=50)
            if raw_resume is not None
            else int(
                getattr(
                    self,
                    "_c1_c4_backpressure_raw_resume",
                    _C1_C4_BACKPRESSURE_RAW_RESUME,
                )
            )
        )
        next_dossier_resume = (
            self._bounded_int(
                dossier_resume,
                "dossier_resume",
                min_value=0,
                max_value=50,
            )
            if dossier_resume is not None
            else int(
                getattr(
                    self,
                    "_c1_c4_backpressure_dossier_resume",
                    _C1_C4_BACKPRESSURE_DOSSIER_RESUME,
                )
            )
        )
        if next_raw_resume >= next_raw_high:
            raise ValueError("raw_resume must be < raw_high")
        if next_dossier_resume >= next_dossier_high:
            raise ValueError("dossier_resume must be < dossier_high")
        self._c1_c4_backpressure_raw_high = next_raw_high
        self._c1_c4_backpressure_dossier_high = next_dossier_high
        self._c1_c4_backpressure_raw_resume = next_raw_resume
        self._c1_c4_backpressure_dossier_resume = next_dossier_resume
        # If the new low-water marks already place us below resume, drop
        # the sticky-blocked state so a tightening tune does not silently
        # leave C1 inhibited.
        if (
            self._c1_c4_backpressure_blocked
            and next_raw_resume == 0
            and next_dossier_resume == 0
        ):
            self._c1_c4_backpressure_blocked = False
        return self.c1_c4_backpressure_snapshot()

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

        observer = self._c1_pulse_observer
        c1_pulse_summary: dict[str, Any] | None = None
        if observer is not None:
            try:
                c1_pulse_summary = dict(observer.summary() or {})
            except Exception:
                self._logger.exception(
                    "Orchestrator: C1 pulse observer summary raised"
                )
        sector_carousel_snap: dict[str, Any] | None = None
        sector_handler = self._sector_carousel_handler
        if sector_handler is not None:
            try:
                sector_carousel_snap = dict(sector_handler.snapshot() or {})
            except Exception:
                self._logger.exception(
                    "Orchestrator: sector carousel handler snapshot raised"
                )
        return {
            "runtime_health": self.health(),
            "runtime_debug": runtime_debug,
            "slot_debug": slot_debug,
            "capacity_debug": dict(self._capacity_debug),
            "flow_gate_accounting": self._flow_gate_snapshot(),
            "c1_pulse_observer": c1_pulse_summary,
            "c4_mode": str(self._c4_mode),
            "sector_carousel_handler": sector_carousel_snap,
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

        observer = self._c1_pulse_observer
        c1_pulse_inspect: dict[str, Any] | None = None
        if observer is not None:
            try:
                c1_pulse_inspect = {
                    "summary": dict(observer.summary() or {}),
                    "in_flight": list(observer.in_flight()),
                    "recent": list(observer.recent(limit=20)),
                }
            except Exception:
                self._logger.exception(
                    "Orchestrator: C1 pulse observer inspect raised"
                )
                c1_pulse_inspect = {"_error": "inspect_failed"}
        base.update(
            {
                "tick_count": int(self._tick_count),
                "paused": bool(self._paused),
                "tick_period_s": float(self._tick_period_s),
                "runtime_inspect": runtime_inspect,
                "slot_inspect": slot_inspect,
                "now_mono": float(now),
                "c1_pulse_observer": c1_pulse_inspect,
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
        """Return how many pieces ``runtime_id`` may push downstream right now.

        Single source of truth: the downstream runtime's own ``available_slots()``
        — i.e. the visible-track-density gate. The CapacitySlot's claim/expiry
        machinery used to AND with this, but the live debugger surfaced the
        bug it caused: a transient slot claim from an upstream pulse that
        never produced a visible arrival held the slot for its 3 s expiry,
        which blocked all upstream movement even when the downstream
        channel had plenty of headroom. Trusting the downstream's own count
        instead removes that lying gate entirely while keeping the same
        density bound that ``available_slots()`` already enforces.
        """
        downstream_id = self._downstream_of.get(runtime_id)
        if downstream_id is None:
            return 0
        downstream = self._runtime_by_id.get(downstream_id)
        if downstream is None:
            self._capacity_debug[runtime_id] = {
                "downstream": downstream_id,
                "available": 0,
                "reason": "missing_downstream_runtime",
            }
            return 0
        try:
            available = max(0, int(downstream.available_slots()))
        except Exception:
            self._logger.exception(
                "Orchestrator: available_slots() raised for %r", downstream_id
            )
            self._capacity_debug[runtime_id] = {
                "downstream": downstream_id,
                "available": 0,
                "reason": "available_slots_failed",
            }
            return 0
        debug = self._downstream_capacity_debug(
            downstream,
            downstream_id=downstream_id,
            available=available,
        )
        if runtime_id == "c1" and available > 0:
            vision_debug = self._c1_c2_vision_backpressure_debug(debug)
            if vision_debug is not None:
                self._capacity_debug[runtime_id] = vision_debug
                return 0
            transitive_debug = self._c1_transitive_backpressure_debug()
            if transitive_debug is not None:
                self._capacity_debug[runtime_id] = transitive_debug
                return 0
            c4_backlog_debug = self._c1_c4_backpressure_debug()
            if c4_backlog_debug is not None:
                self._capacity_debug[runtime_id] = c4_backlog_debug
                return 0
        self._capacity_debug[runtime_id] = debug
        return available

    def _c1_c2_vision_backpressure_debug(
        self,
        c2_debug: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Treat C1 as a stochastic dose source and C2 as the measured buffer."""
        if str(c2_debug.get("downstream") or "") != "c2":
            return None
        density = c2_debug.get("density")
        if not isinstance(density, dict):
            return None
        piece_count = self._safe_int(
            density.get("piece_count_estimate"),
            fallback=c2_debug.get("visible_track_count"),
        )
        clump_score = self._safe_float(density.get("clump_score"))
        exit_queue_length = self._safe_int(density.get("exit_queue_length"))
        target_low = int(self._c1_c2_vision_target_low)
        target_high = int(self._c1_c2_vision_target_high)
        clump_block_threshold = float(self._c1_c2_vision_clump_block_threshold)
        exit_queue_limit = int(self._c1_c2_vision_exit_queue_limit)

        reason: str | None = None
        if piece_count >= target_high:
            reason = "vision_target_high"
        elif exit_queue_limit > 0 and exit_queue_length >= exit_queue_limit:
            reason = "vision_exit_queue"
        elif (
            piece_count >= 2
            and clump_score >= clump_block_threshold
        ):
            reason = "vision_density_clump"
        elif target_low > 0 and piece_count >= target_low:
            reason = "vision_target_band"
        if reason is None:
            return None

        blocked = dict(c2_debug)
        blocked.update({
            "downstream": "c2",
            "available": 0,
            "reason": reason,
            "controller": {
                "name": "c1_c2_vision_burst",
                "target_low": target_low,
                "target_high": target_high,
                "clump_block_threshold": clump_block_threshold,
                "exit_queue_limit": exit_queue_limit,
                "piece_count_estimate": int(piece_count),
                "clump_score": float(clump_score),
                "exit_queue_length": int(exit_queue_length),
            },
        })
        return blocked

    def _c1_transitive_backpressure_debug(self) -> dict[str, Any] | None:
        """Stop blind bulk feed when the C2->C3 side is already backed up.

        C1 has no camera of its own. If it only listens to C2's local headroom,
        it can keep adding pieces while C2 is below its cap but C3 is already
        saturated by a downstream C4 admission bottleneck. That pattern showed
        up live as C2/C3 overflow after C1's first delayed release.
        """
        c3 = self._runtime_by_id.get("c3")
        if c3 is None:
            return None
        try:
            c3_available = max(0, int(c3.available_slots()))
        except Exception:
            self._logger.exception("Orchestrator: c3.available_slots() raised")
            return {
                "downstream": "c3",
                "available": 0,
                "reason": "available_slots_failed",
            }
        if c3_available > 0:
            return None
        debug = self._downstream_capacity_debug(
            c3,
            downstream_id="c3",
            available=0,
        )
        debug["immediate_downstream"] = "c2"
        return debug

    def _c1_c4_backpressure_debug(self) -> dict[str, Any] | None:
        """Keep C1 from feeding while C4 is already carrying downstream WIP.

        Stateful with hysteresis: once we cross the high-water mark we stay
        blocked until both raw and dossier counts drop to/below the resume
        thresholds. Without that the gate flips bang-bang at the high-water
        line and the line oscillates between starvation and C4 overfill — a
        failure mode documented in operation-target-10ppm.
        """
        c4 = self._runtime_by_id.get("c4")
        if c4 is None:
            return None
        snapshot_fn = getattr(c4, "debug_snapshot", None)
        if not callable(snapshot_fn):
            return None
        try:
            snapshot = dict(snapshot_fn() or {})
        except Exception:
            self._logger.exception("Orchestrator: c4.debug_snapshot() raised")
            return {
                "downstream": "c4",
                "immediate_downstream": "c2",
                "available": 0,
                "reason": "debug_snapshot_failed",
            }

        raw_count = self._safe_int(
            snapshot.get("raw_detection_count"),
            fallback=snapshot.get("raw_track_count"),
        )
        dossier_count = self._safe_int(
            snapshot.get("dossier_count"),
            fallback=len(snapshot.get("dossiers") or ()),
        )
        raw_high = int(self._c1_c4_backpressure_raw_high)
        dossier_high = int(self._c1_c4_backpressure_dossier_high)
        raw_resume = int(self._c1_c4_backpressure_raw_resume)
        dossier_resume = int(self._c1_c4_backpressure_dossier_resume)

        was_blocked = bool(self._c1_c4_backpressure_blocked)
        reason: str | None = None
        if was_blocked:
            # Sticky block: stay inhibited until *both* counters relax.
            if raw_count <= raw_resume and dossier_count <= dossier_resume:
                self._c1_c4_backpressure_blocked = False
            else:
                if dossier_count > dossier_resume:
                    reason = "backlog_dossiers_holding"
                else:
                    reason = "backlog_raw_holding"
        else:
            if dossier_count >= dossier_high:
                reason = "backlog_dossiers"
                self._c1_c4_backpressure_blocked = True
            elif raw_count >= raw_high:
                reason = "backlog_raw"
                self._c1_c4_backpressure_blocked = True
        if reason is None:
            return None

        return {
            "downstream": "c4",
            "immediate_downstream": "c2",
            "available": 0,
            "reason": reason,
            "raw_detection_count": int(raw_count),
            "dossier_count": int(dossier_count),
            "controller": {
                "name": "c1_c4_backpressure",
                "raw_high": int(raw_high),
                "dossier_high": int(dossier_high),
                "raw_resume": int(raw_resume),
                "dossier_resume": int(dossier_resume),
                "state": "blocked",
            },
        }

    def _downstream_capacity_debug(
        self,
        downstream: Runtime,
        *,
        downstream_id: str,
        available: int,
    ) -> dict[str, Any]:
        debug: dict[str, Any] = {
            "downstream": downstream_id,
            "available": int(available),
            "reason": "ok" if available > 0 else "no_capacity",
        }
        snapshot_fn = getattr(downstream, "capacity_debug_snapshot", None)
        if not callable(snapshot_fn):
            return debug
        try:
            snapshot = dict(snapshot_fn() or {})
        except Exception:
            self._logger.exception(
                "Orchestrator: capacity_debug_snapshot() raised for %r",
                downstream_id,
            )
            return {
                "downstream": downstream_id,
                "available": int(available),
                "reason": "capacity_debug_failed",
            }
        debug.update(snapshot)
        debug["downstream"] = downstream_id
        debug["available"] = int(available)
        if not isinstance(debug.get("reason"), str) or not debug["reason"]:
            debug["reason"] = "ok" if available > 0 else "no_capacity"
        return debug

    def _flow_gate_snapshot(self) -> dict[str, Any]:
        totals = dict(sorted(self._flow_gate_totals_s.items()))
        pareto = [
            {"gate": key, "seconds": seconds}
            for key, seconds in sorted(
                totals.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if seconds > 0.0
        ]
        return {
            "current": dict(sorted(self._flow_gate_current.items())),
            "totals_s": totals,
            "pareto": pareto[:20],
            "observed_at_mono": self._flow_gate_last_observed_at,
        }

    def _observe_flow_gates(self, now_mono: float) -> None:
        last = self._flow_gate_last_observed_at
        self._flow_gate_last_observed_at = float(now_mono)
        current: dict[str, str] = {}
        health = self.health()
        for runtime_id, entry in health.items():
            state = str(entry.get("state") or "unknown")
            reason = entry.get("blocked_reason")
            reason_str = str(reason) if isinstance(reason, str) and reason else None
            current[runtime_id] = self._flow_gate_key(
                runtime_id=runtime_id,
                state=state,
                blocked_reason=reason_str,
            )
        self._flow_gate_current = current
        if last is None:
            return
        elapsed = max(0.0, min(1.0, float(now_mono) - float(last)))
        if elapsed <= 0.0:
            return
        for runtime_id, gate in current.items():
            key = f"{runtime_id}:{gate}"
            self._flow_gate_totals_s[key] = self._flow_gate_totals_s.get(key, 0.0) + elapsed

    def _flow_gate_key(
        self,
        *,
        runtime_id: str,
        state: str,
        blocked_reason: str | None,
    ) -> str:
        if blocked_reason == "downstream_full":
            capacity = self._capacity_debug.get(runtime_id)
            gate = self._capacity_gate_key(capacity)
            if gate is not None:
                return gate
            return "BLOCKED_DOWNSTREAM_FULL"
        if blocked_reason == "lease_denied":
            return "BLOCKED_LEASE_DENIED"
        if blocked_reason == "awaiting_downstream_arrival":
            return "BLOCKED_AWAITING_DOWNSTREAM_ARRIVAL"
        if blocked_reason == "exit_spacing":
            return "BLOCKED_EXIT_SPACING"
        if blocked_reason in {"distributor_busy", "waiting_distributor"}:
            return "BLOCKED_DISTRIBUTOR_NOT_READY"
        if blocked_reason == "waiting_distributor_request":
            return "BLOCKED_DISTRIBUTOR_NOT_READY"
        if blocked_reason in {"exit_piece_not_ready", "exit_piece_unclassified"}:
            return "BLOCKED_C4_EXIT_HOLD"
        if blocked_reason == "trailing_piece_in_chute":
            return "BLOCKED_CHUTE_NOT_SINGLETON"
        if blocked_reason == "eject_in_flight":
            return "PULSE_SENT_OR_ACTIVE"
        if blocked_reason == "cooldown":
            return "PULSE_SUPPRESSED_COOLDOWN"
        if blocked_reason == "startup_hold":
            return "PULSE_SUPPRESSED_STARTUP_HOLD"
        if blocked_reason == "observing_downstream":
            return "PULSE_SUPPRESSED_OBSERVING_DOWNSTREAM"
        if blocked_reason == "hw_busy":
            return "PULSE_SUPPRESSED_HW_BUSY"
        if blocked_reason == "hw_queue_full":
            return "PULSE_SUPPRESSED_HW_QUEUE_FULL"
        if blocked_reason:
            return f"BLOCKED_{blocked_reason.upper()}"
        if state in {"idle", "running"}:
            return "READY_OR_ACTIVE"
        if state.startswith("pulsing") or state in {
            "rotate_pipeline",
            "drop_commit",
            "classify_pending",
            "sending",
            "positioning",
        }:
            return "PULSE_SENT_OR_ACTIVE"
        return f"STATE_{state.upper()}"

    @staticmethod
    def _capacity_gate_key(capacity: dict[str, Any] | None) -> str | None:
        if not isinstance(capacity, dict):
            return None
        if int(capacity.get("available") or 0) > 0:
            return None
        downstream = str(capacity.get("downstream") or "downstream").upper()
        reason = str(capacity.get("reason") or "no_capacity")
        if downstream == "C4" and reason in {
            "dropzone_clear",
            "arc_clear",
            "zone_cap",
            "transport_cap",
            "raw_cap",
            "startup_purge",
        }:
            return f"BLOCKED_C4_ADMISSION_{reason.upper()}"
        if reason == "piece_cap":
            return f"BLOCKED_{downstream}_DENSITY_CAP"
        if reason == "purge":
            return f"BLOCKED_{downstream}_PURGE"
        return f"BLOCKED_{downstream}_{reason.upper()}"

    @staticmethod
    def _safe_int(value: Any, fallback: Any = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(fallback)
            except (TypeError, ValueError):
                return 0

    @staticmethod
    def _safe_float(value: Any, fallback: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    @staticmethod
    def _bounded_int(
        value: Any,
        name: str,
        *,
        min_value: int,
        max_value: int,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if parsed < min_value or parsed > max_value:
            raise ValueError(f"{name} must be between {min_value} and {max_value}")
        return parsed

    @staticmethod
    def _bounded_float(
        value: Any,
        name: str,
        *,
        min_value: float,
        max_value: float,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number") from exc
        if parsed < min_value or parsed > max_value:
            raise ValueError(f"{name} must be between {min_value} and {max_value}")
        return parsed

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
        if (
            self._c4_mode == "sector_carousel"
            and self._sector_carousel_handler is not None
        ):
            try:
                self._sync_sector_carousel_from_c4(now_mono)
                self._sector_carousel_handler.tick(now_mono)
            except Exception:
                self._logger.exception(
                    "Orchestrator: sector carousel handler tick raised"
                )
        self._tick_count += 1
        self._last_tick_mono = now_mono
        self._observe_flow_gates(now_mono)
        observer = self._c1_pulse_observer
        if observer is not None:
            try:
                observer.tick(now_mono)
            except Exception:
                self._logger.exception(
                    "Orchestrator: C1 pulse observer tick raised"
                )

    def _sync_sector_carousel_from_c4(self, now_mono: float) -> None:
        handler = self._sector_carousel_handler
        if handler is None:
            return
        c4 = self._runtime_by_id.get("c4")
        if c4 is None:
            return
        front_fn = getattr(c4, "carousel_front_snapshot", None)
        if not callable(front_fn):
            return
        try:
            front = front_fn()
        except Exception:
            self._logger.exception(
                "Orchestrator: c4.carousel_front_snapshot raised for sector carousel"
            )
            return
        if not isinstance(front, dict):
            return
        piece_uuid = front.get("piece_uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid:
            return
        if not bool(front.get("classification_present", False)):
            return
        bind = getattr(handler, "bind_front_classification", None)
        if not callable(bind):
            return
        try:
            bind(
                c4_piece_uuid=piece_uuid,
                classification=front.get("classification"),
                dossier=dict(front.get("dossier") or {}),
                now_mono=now_mono,
            )
        except Exception:
            self._logger.exception(
                "Orchestrator: sector carousel bind_classification raised"
            )

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
