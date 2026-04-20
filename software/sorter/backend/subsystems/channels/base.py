from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subsystems.feeder.analysis import ChannelAction


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
