"""RuntimeC1 — bulk seed shuttle.

C1 is blind: no camera, no perception feed. It reacts purely to downstream
capacity headroom (C1->C2 slot) and to internal jam-recovery timers. Each
forward pulse is expected to deliver one piece into C2; pulses are only
emitted when the downstream slot has room. Jam recovery (port of
``subsystems/feeder/strategies/c1_jam_recovery.py``) runs on the
``HwWorker`` because its shake + push sequences block 250 to 2500 ms per
move.

Behaviour reference (not port-target):
* ``subsystems/feeder/feeding.py``  — when C1 is allowed to pulse
* ``subsystems/channels/c1_bulk.py`` — the ch2-saturation gate
* ``subsystems/feeder/strategies/c1_jam_recovery.py`` — escalating shake+push
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from rt.contracts.runtime import RuntimeInbox
from rt.coupling.slots import CapacitySlot

from .base import BaseRuntime, HwWorker


# Timer defaults mirror legacy ``feeder_config.first_rotor_jam_timeout_s`` /
# ``first_rotor_jam_min_pulses`` / ``first_rotor_jam_retry_cooldown_s``. They
# land in rt/config in a later phase; accepting them as constructor params
# keeps the runtime self-contained for now.
DEFAULT_JAM_TIMEOUT_S = 4.0
DEFAULT_JAM_MIN_PULSES = 3
DEFAULT_JAM_COOLDOWN_S = 1.5
DEFAULT_PULSE_COOLDOWN_S = 4.0
DEFAULT_MAX_RECOVERY_CYCLES = 5
DEFAULT_STARTUP_HOLD_S = 2.0
DEFAULT_UNCONFIRMED_PULSE_LIMIT = 2
DEFAULT_OBSERVATION_HOLD_S = 12.0


@dataclass(slots=True)
class _JamState:
    pulses_since_progress: int = 0
    last_progress_mono: float | None = None
    level: int = 0
    attempts: int = 0
    cooldown_until: float = 0.0
    in_flight: bool = False
    exhausted: bool = False


class RuntimeC1(BaseRuntime):
    """Bulk-bucket rotor: pulses pieces into C2 when C1->C2 has headroom.

    States (internal): idle / pulsing / recovering / paused.
    """

    def __init__(
        self,
        *,
        downstream_slot: CapacitySlot,
        pulse_command: Callable[[], bool],
        recovery_command: Callable[[int], bool],
        sample_transport_command: Callable[[float, int | None, int | None], bool] | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        jam_timeout_s: float = DEFAULT_JAM_TIMEOUT_S,
        jam_min_pulses: int = DEFAULT_JAM_MIN_PULSES,
        jam_cooldown_s: float = DEFAULT_JAM_COOLDOWN_S,
        max_recovery_cycles: int = DEFAULT_MAX_RECOVERY_CYCLES,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
        startup_hold_s: float = DEFAULT_STARTUP_HOLD_S,
        unconfirmed_pulse_limit: int = DEFAULT_UNCONFIRMED_PULSE_LIMIT,
        observation_hold_s: float = DEFAULT_OBSERVATION_HOLD_S,
        state_observer: Callable[[str, str, str], None] | None = None,
        pulse_observer: Callable[[str], None] | None = None,
        recovery_admission_check: (
            Callable[[int], tuple[bool, dict[str, object]]] | None
        ) = None,
    ) -> None:
        super().__init__(
            "c1", feed_id=None, logger=logger, hw_worker=hw_worker,
            state_observer=state_observer,
        )
        self._downstream_slot = downstream_slot
        self._pulse_command = pulse_command
        self._recovery_command = recovery_command
        self._sample_transport_command = sample_transport_command
        self._jam_timeout_s = float(jam_timeout_s)
        self._jam_min_pulses = int(jam_min_pulses)
        self._jam_cooldown_s = float(jam_cooldown_s)
        self._max_recovery_cycles = max(1, int(max_recovery_cycles))
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._startup_hold_s = max(0.0, float(startup_hold_s))
        self._unconfirmed_pulse_limit = max(1, int(unconfirmed_pulse_limit))
        self._observation_hold_s = max(0.0, float(observation_hold_s))
        self._observation_hold_until: float = 0.0
        self._observation_hold_remaining_s: float = 0.0
        self._startup_hold_armed = self._startup_hold_s > 0.0
        self._startup_hold_until: float | None = None
        self._startup_hold_remaining_s: float = (
            self._startup_hold_s if self._startup_hold_armed else 0.0
        )
        self._jam = _JamState()
        self._next_pulse_at: float = 0.0
        self._sample_transport_step_deg: float | None = None
        self._sample_transport_max_speed: int | None = None
        self._sample_transport_acceleration: int | None = None
        self._paused_reason: str | None = None
        self._maintenance_pause_reason: str | None = None
        self._pulse_observer = pulse_observer
        self._recovery_admission_check = recovery_admission_check
        self._last_recovery_admission: dict[str, object] | None = None

    # ------------------------------------------------------------------
    # Runtime ABC

    def start(self) -> None:
        self.arm_startup_hold()
        super().start()

    def available_slots(self) -> int:
        # C1 is the source of parts; its only backpressure signal upstream
        # is pause-on-exhaustion.
        return 0 if self._paused_reason or self._maintenance_pause_reason else 1

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            if self._maintenance_pause_reason:
                self._set_state("paused", blocked_reason=self._maintenance_pause_reason)
                return
            if self._paused_reason:
                self._set_state("paused", blocked_reason=self._paused_reason)
                return
            if self._startup_hold_active(now_mono):
                self._set_state("idle", blocked_reason="startup_hold")
                return
            if self._hw.busy() or self._hw.pending() > 0 or self._jam.in_flight:
                self._set_state("pulsing", blocked_reason="hw_busy")
                return
            if now_mono < self._next_pulse_at:
                self._set_state("idle", blocked_reason="cooldown")
                return
            if inbox.capacity_downstream <= 0:
                self._set_state("idle", blocked_reason="downstream_full")
                return
            # Jam detection: no progress + minimum pulse count reached.
            # `last_progress_mono is None` means we haven't seen progress yet;
            # seed it from the first tick so the stall timer is relative.
            if self._jam.last_progress_mono is None:
                self._jam.last_progress_mono = now_mono
            stalled_for = now_mono - self._jam.last_progress_mono
            if (
                stalled_for >= self._jam_timeout_s
                and self._jam.pulses_since_progress >= self._jam_min_pulses
                and now_mono >= self._jam.cooldown_until
            ):
                self._launch_recovery(now_mono)
                return
            if self._observation_hold_active(now_mono):
                self._set_state("idle", blocked_reason="observing_downstream")
                return
            self._dispatch_pulse(now_mono)
        finally:
            self._tick_end(start)

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # Called by the orchestrator when a downstream runtime confirms
        # it saw a new piece — resets the stall timer.
        self._mark_progress(now_mono)

    # ------------------------------------------------------------------
    # Public helpers for tests / orchestrator

    def notify_downstream_progress(self, now_mono: float) -> None:
        """Called when C2 reports it saw a new piece (clears jam state)."""
        self._mark_progress(now_mono)

    def is_paused(self) -> bool:
        return self._paused_reason is not None

    def clear_pause(self) -> None:
        self._paused_reason = None
        self._jam = _JamState()
        self.arm_startup_hold()
        self._set_state("idle")

    def sample_transport_port(self) -> "_C1SampleTransportPort":
        return _C1SampleTransportPort(self)

    def pause_for_maintenance(self, reason: str = "maintenance") -> None:
        self._maintenance_pause_reason = str(reason or "maintenance")
        self._set_state("paused", blocked_reason=self._maintenance_pause_reason)

    def resume_from_maintenance(self) -> None:
        self._maintenance_pause_reason = None
        if self._paused_reason is None:
            self.arm_startup_hold()
            self._set_state("idle")

    def arm_startup_hold(self) -> None:
        """Delay blind C1 feed briefly after start/resume.

        C1 has no camera; without a warm-up hold it can pulse before C2's
        first fresh capacity observation has caught up with real parts already
        lying in the ring.
        """
        if self._startup_hold_s <= 0.0:
            self._startup_hold_armed = False
            self._startup_hold_until = None
            self._startup_hold_remaining_s = 0.0
            return
        self._startup_hold_armed = True
        self._startup_hold_until = None
        self._startup_hold_remaining_s = self._startup_hold_s

    def debug_snapshot(self) -> dict[str, object]:
        snap = super().debug_snapshot()
        snap.update(
            {
                "sample_transport_step_deg": self._sample_transport_step_deg,
                "pulse_cooldown_s": float(self._pulse_cooldown_s),
                "next_pulse_at_mono": float(self._next_pulse_at),
                "startup_hold_s": float(self._startup_hold_s),
                "startup_hold_armed": bool(self._startup_hold_armed),
                "startup_hold_until_mono": self._startup_hold_until,
                "startup_hold_remaining_s": float(self._startup_hold_remaining_s),
                "unconfirmed_pulse_limit": int(self._unconfirmed_pulse_limit),
                "observation_hold_s": float(self._observation_hold_s),
                "observation_hold_until_mono": float(self._observation_hold_until),
                "observation_hold_remaining_s": float(
                    self._observation_hold_remaining_s
                ),
                "maintenance_pause_reason": self._maintenance_pause_reason,
                "jam_timeout_s": float(self._jam_timeout_s),
                "jam_min_pulses": int(self._jam_min_pulses),
                "jam_cooldown_s": float(self._jam_cooldown_s),
                "max_recovery_cycles": int(self._max_recovery_cycles),
                "jam": {
                    "pulses_since_progress": int(self._jam.pulses_since_progress),
                    "last_progress_mono": self._jam.last_progress_mono,
                    "level": int(self._jam.level),
                    "attempts": int(self._jam.attempts),
                    "cooldown_until_mono": float(self._jam.cooldown_until),
                    "in_flight": bool(self._jam.in_flight),
                    "exhausted": bool(self._jam.exhausted),
                },
                "last_recovery_admission": (
                    dict(self._last_recovery_admission)
                    if self._last_recovery_admission is not None
                    else None
                ),
            }
        )
        return snap

    # ------------------------------------------------------------------
    # Internals

    def _startup_hold_active(self, now_mono: float) -> bool:
        if self._startup_hold_s <= 0.0 or not self._startup_hold_armed:
            self._startup_hold_remaining_s = 0.0
            return False
        if self._startup_hold_until is None:
            self._startup_hold_until = now_mono + self._startup_hold_s
        remaining = self._startup_hold_until - now_mono
        if remaining > 0.0:
            self._startup_hold_remaining_s = remaining
            return True
        self._startup_hold_armed = False
        self._startup_hold_until = None
        self._startup_hold_remaining_s = 0.0
        # Do not let the warm-up interval count as a stall for jam recovery.
        self._jam.last_progress_mono = now_mono
        return False

    def _mark_progress(self, now_mono: float) -> None:
        self._jam.pulses_since_progress = 0
        self._jam.last_progress_mono = float(now_mono)
        self._jam.level = 0
        self._jam.attempts = 0
        if self._observation_hold_s > 0.0:
            self._observation_hold_until = max(
                self._observation_hold_until,
                now_mono + self._observation_hold_s,
            )
            self._observation_hold_remaining_s = max(
                0.0,
                self._observation_hold_until - now_mono,
            )
        else:
            self._observation_hold_until = 0.0
            self._observation_hold_remaining_s = 0.0

    def _observation_hold_active(self, now_mono: float) -> bool:
        if self._observation_hold_s <= 0.0:
            self._observation_hold_remaining_s = 0.0
            return False
        remaining = self._observation_hold_until - now_mono
        if remaining > 0.0:
            self._observation_hold_remaining_s = remaining
            return True
        if self._jam.pulses_since_progress < self._unconfirmed_pulse_limit:
            self._observation_hold_remaining_s = 0.0
            return False
        self._observation_hold_remaining_s = 0.0
        return False

    def _dispatch_pulse(self, now_mono: float) -> None:
        # 3 s handoff budget: if the announced piece never arrives at C2,
        # the slot auto-releases so C1 can keep feeding.
        claimed = self._downstream_slot.try_claim(
            now_mono=now_mono, hold_time_s=3.0
        )
        if not claimed:
            self._set_state("idle", blocked_reason="downstream_full")
            return

        def _run_pulse() -> None:
            try:
                ok = self._pulse_command()
            except Exception:
                self._logger.exception("RuntimeC1: pulse command raised")
                ok = False
            if not ok:
                # Hardware rejected the move — release the slot so we don't
                # deadlock downstream waiting for a piece that never arrived.
                self._downstream_slot.release()

        self._jam.pulses_since_progress += 1
        if (
            self._observation_hold_s > 0.0
            and self._jam.pulses_since_progress >= self._unconfirmed_pulse_limit
        ):
            self._observation_hold_until = now_mono + self._observation_hold_s
            self._observation_hold_remaining_s = self._observation_hold_s
        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c1_pulse")
        if not enqueued:
            # Queue full; roll back the reservation.
            self._downstream_slot.release()
            self._set_state("idle", blocked_reason="hw_queue_full")
            return
        self._notify_pulse_observer("pulse")
        self._set_state("pulsing")

    def _dispatch_sample_transport_pulse(self, now_mono: float) -> bool:
        """Move C1 without claiming C1->C2 capacity."""
        if self._hw.busy() or self._hw.pending() > 0:
            self._set_state("sample_transport", blocked_reason="hw_busy")
            return False

        def _run_pulse() -> None:
            try:
                if (
                    self._sample_transport_command is not None
                    and self._sample_transport_step_deg
                ):
                    ok = bool(
                        self._sample_transport_command(
                            self._sample_transport_step_deg,
                            self._sample_transport_max_speed,
                            self._sample_transport_acceleration,
                        )
                    )
                else:
                    ok = bool(self._pulse_command())
            except Exception:
                self._logger.exception("RuntimeC1: sample transport pulse raised")
                ok = False
            if not ok:
                self._logger.warning("RuntimeC1: sample transport pulse failed")

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c1_sample_transport")
        if not enqueued:
            self._set_state("sample_transport", blocked_reason="hw_queue_full")
            return False
        self._set_state("sample_transport")
        return True

    def _configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self._sample_transport_max_speed = direct_max_speed_usteps_per_s
        self._sample_transport_acceleration = direct_acceleration_usteps_per_s2
        if target_rpm is None:
            self._sample_transport_step_deg = None
            return
        target_degrees_per_second = max(0.0, float(target_rpm)) * 6.0
        self._sample_transport_step_deg = max(1.0, target_degrees_per_second * 0.75)

    def _notify_pulse_observer(self, action_id: str) -> None:
        observer = self._pulse_observer
        if observer is None:
            return
        try:
            observer(action_id)
        except Exception:
            self._logger.exception(
                "RuntimeC1: pulse_observer raised for %s", action_id
            )

    def _launch_recovery(self, now_mono: float) -> None:
        if self._jam.attempts >= self._max_recovery_cycles:
            self._jam.exhausted = True
            self._paused_reason = "jam_recovery_exhausted"
            self._logger.error(
                "RuntimeC1: jam recovery exhausted after %d attempts; pausing",
                self._jam.attempts,
            )
            self._set_state("paused", blocked_reason=self._paused_reason)
            return

        level = self._jam.level
        if self._recovery_admission_check is not None:
            try:
                allowed, info = self._recovery_admission_check(level)
            except Exception:
                self._logger.exception(
                    "RuntimeC1: recovery admission check raised; allowing as fail-open"
                )
                allowed, info = True, {"error": "admission_check_failed"}
            self._last_recovery_admission = dict(info)
            if not allowed:
                # Hold off without burning a recovery attempt — the
                # safety win is sitting in this state until C2 has
                # drained enough to absorb the worst-case push. Bump
                # the cooldown so we revisit later instead of spinning.
                self._jam.cooldown_until = now_mono + self._jam_cooldown_s
                self._logger.info(
                    "RuntimeC1: recovery level %d blocked by C2 headroom (info=%s)",
                    level,
                    info,
                )
                self._set_state(
                    "idle", blocked_reason="recovery_headroom_insufficient"
                )
                return

        self._jam.in_flight = True
        self._jam.cooldown_until = now_mono + self._jam_cooldown_s

        def _run_recovery() -> None:
            try:
                ok = self._recovery_command(level)
            except Exception:
                self._logger.exception("RuntimeC1: recovery command raised")
                ok = False
            self._jam.in_flight = False
            self._jam.attempts += 1
            self._jam.level = min(self._jam.level + 1, self._max_recovery_cycles - 1)
            if not ok:
                self._logger.warning(
                    "RuntimeC1: recovery level %d reported failure", level
                )

        enqueued = self._hw.enqueue(_run_recovery, priority=1, label="c1_jam_recover")
        if not enqueued:
            self._jam.in_flight = False
            self._set_state("recovering", blocked_reason="hw_queue_full")
            return
        self._notify_pulse_observer(f"recover_level_{level}")
        self._set_state("recovering")


class _C1SampleTransportPort:
    key = "c1"

    def __init__(self, runtime: RuntimeC1) -> None:
        self._runtime = runtime

    def step(self, now_mono: float) -> bool:
        return self._runtime._dispatch_sample_transport_pulse(now_mono)

    def configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self._runtime._configure_sample_transport(
            target_rpm=target_rpm,
            direct_max_speed_usteps_per_s=direct_max_speed_usteps_per_s,
            direct_acceleration_usteps_per_s2=direct_acceleration_usteps_per_s2,
        )

    def nominal_degrees_per_step(self) -> float | None:
        if self._runtime._sample_transport_step_deg is not None:
            return float(self._runtime._sample_transport_step_deg)
        fn = getattr(self._runtime._pulse_command, "nominal_degrees_per_step", None)
        if callable(fn):
            value = fn()
            return float(value) if isinstance(value, (int, float)) and value > 0 else None
        return None


__all__ = [
    "RuntimeC1",
    "DEFAULT_JAM_TIMEOUT_S",
    "DEFAULT_JAM_MIN_PULSES",
    "DEFAULT_JAM_COOLDOWN_S",
    "DEFAULT_PULSE_COOLDOWN_S",
    "DEFAULT_MAX_RECOVERY_CYCLES",
    "DEFAULT_STARTUP_HOLD_S",
    "DEFAULT_UNCONFIRMED_PULSE_LIMIT",
    "DEFAULT_OBSERVATION_HOLD_S",
]
