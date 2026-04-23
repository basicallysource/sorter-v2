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
DEFAULT_PULSE_COOLDOWN_S = 0.25
DEFAULT_MAX_RECOVERY_CYCLES = 5


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
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        jam_timeout_s: float = DEFAULT_JAM_TIMEOUT_S,
        jam_min_pulses: int = DEFAULT_JAM_MIN_PULSES,
        jam_cooldown_s: float = DEFAULT_JAM_COOLDOWN_S,
        max_recovery_cycles: int = DEFAULT_MAX_RECOVERY_CYCLES,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
    ) -> None:
        super().__init__("c1", feed_id=None, logger=logger, hw_worker=hw_worker)
        self._downstream_slot = downstream_slot
        self._pulse_command = pulse_command
        self._recovery_command = recovery_command
        self._jam_timeout_s = float(jam_timeout_s)
        self._jam_min_pulses = int(jam_min_pulses)
        self._jam_cooldown_s = float(jam_cooldown_s)
        self._max_recovery_cycles = max(1, int(max_recovery_cycles))
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._jam = _JamState()
        self._next_pulse_at: float = 0.0
        self._paused_reason: str | None = None

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        # C1 is the source of parts; its only backpressure signal upstream
        # is pause-on-exhaustion.
        return 0 if self._paused_reason else 1

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            if self._paused_reason:
                self._set_state("paused", blocked_reason=self._paused_reason)
                return
            if self._hw.busy() or self._jam.in_flight:
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

    # ------------------------------------------------------------------
    # Internals

    def _mark_progress(self, now_mono: float) -> None:
        self._jam.pulses_since_progress = 0
        self._jam.last_progress_mono = float(now_mono)
        self._jam.level = 0
        self._jam.attempts = 0

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
        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c1_pulse")
        if not enqueued:
            # Queue full; roll back the reservation.
            self._downstream_slot.release()
            self._set_state("idle", blocked_reason="hw_queue_full")
            return
        self._set_state("pulsing")

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
        self._set_state("recovering")


__all__ = ["RuntimeC1", "DEFAULT_JAM_TIMEOUT_S", "DEFAULT_JAM_MIN_PULSES"]
