from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subsystems.feeder.analysis import ChannelAction


# ---------------------------------------------------------------------------
# Exit-zone wiggle defaults — small forward/reverse jog to break static
# friction when a piece is parked on the exit boundary and the downstream
# gate is closed so the normal pulse would be rejected anyway. Defaults
# chosen to be conservative: only fires after the piece has been stuck with
# >=50% bbox coverage on the exit-sections for at least 600 ms, and at most
# once every 800 ms.
# ---------------------------------------------------------------------------
EXIT_WIGGLE_OVERLAP_THRESHOLD: float = 0.5
EXIT_WIGGLE_STALL_MS: int = 600
EXIT_WIGGLE_REVERSE_DEG: float = 1.5
EXIT_WIGGLE_FORWARD_DEG: float = 2.0
EXIT_WIGGLE_COOLDOWN_MS: int = 800


@dataclass
class FeederTickContext:
    now_mono: float
    detections: list
    analysis: Any
    ch2_action: ChannelAction
    ch3_action: ChannelAction
    can_run: bool
    ch3_held: bool
    classification_channel_block: bool
    classification_channel_piece_count: int
    ch1_pulse_intent: bool
    ch2_pulse_intent: bool
    ch3_pulse_intent: bool
    ch1_stepper_busy: bool
    ch2_stepper_busy: bool
    ch3_stepper_busy: bool
    wait_stepper_busy: bool
    pulse_intent: bool = False
    pulse_sent: bool = False
    ch1_jam_recovery_triggered: bool = False
    abort_tick: bool = False


class BaseStation:
    def __init__(self, *, gc, machine_name: str) -> None:
        self.gc = gc
        self.logger = gc.logger
        self._machine_name = machine_name
        self._current_state: str | None = None

    @property
    def current_state(self) -> str | None:
        return self._current_state

    def set_state(self, state_name: str) -> None:
        if self._current_state == state_name:
            return
        prev_state = self._current_state
        self._current_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            self._machine_name,
            prev_state,
            state_name,
        )

    def cleanup(self) -> None:
        pass


__all__ = ["BaseStation", "FeederTickContext"]
