"""c_channel_2 slip-stick separation driver.

Runs an idle-time motion pattern on the middle feeder ring that separates
touching pieces without transporting them toward c_channel_3. Parameters
come straight from the spring-2026 parameter-sweep study:

    500 ms constant-velocity pulse at 8000 µsteps/s
    500 ms slow counter-direction drift at 300 µsteps/s
    alternating cw / ccw  → net-zero drift

The slow counter-drift window doubles as gear-backlash takeup for the next
pulse, so reversals are quiet.

The driver is a non-blocking state machine — call ``step(now, allowed)``
every feeder tick, and it manages ``move_at_speed`` transitions when a
phase elapses. Passing ``allowed=False`` triggers a hard cancel: the
stepper is stopped immediately and the state machine returns to IDLE.
That is the only safety valve — callers are expected to flip ``allowed``
to ``False`` the moment any piece enters c_channel_2's exit zone or a
higher-priority motion wants the rotor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


# Production pattern fixed by the April 2026 study.
PULSE_SPEED_USTEPS_S = 8000
COUNTER_DRIFT_SPEED_USTEPS_S = 300
PULSE_DURATION_S = 0.5
COUNTER_DRIFT_DURATION_S = 0.5


_STATE_IDLE = "idle"
_STATE_PULSE_CW = "pulse_cw"
_STATE_DRIFT_CCW = "drift_ccw"
_STATE_PULSE_CCW = "pulse_ccw"
_STATE_DRIFT_CW = "drift_cw"


@dataclass
class _PhaseDef:
    speed: int  # signed µsteps/s
    duration_s: float
    next_state: str


_PHASES: dict[str, _PhaseDef] = {
    _STATE_PULSE_CW:  _PhaseDef(speed=+PULSE_SPEED_USTEPS_S,         duration_s=PULSE_DURATION_S,         next_state=_STATE_DRIFT_CCW),
    _STATE_DRIFT_CCW: _PhaseDef(speed=-COUNTER_DRIFT_SPEED_USTEPS_S, duration_s=COUNTER_DRIFT_DURATION_S, next_state=_STATE_PULSE_CCW),
    _STATE_PULSE_CCW: _PhaseDef(speed=-PULSE_SPEED_USTEPS_S,         duration_s=PULSE_DURATION_S,         next_state=_STATE_DRIFT_CW),
    _STATE_DRIFT_CW:  _PhaseDef(speed=+COUNTER_DRIFT_SPEED_USTEPS_S, duration_s=COUNTER_DRIFT_DURATION_S, next_state=_STATE_PULSE_CW),
}


class Ch2SeparationDriver:
    def __init__(self, stepper, logger) -> None:
        self._stepper = stepper
        self._logger = logger
        self._state: str = _STATE_IDLE
        self._state_entered_at: float = 0.0

    @property
    def active(self) -> bool:
        return self._state != _STATE_IDLE

    @property
    def state_name(self) -> str:
        return self._state

    def cancel(self, reason: str) -> None:
        """Stop any running pattern immediately and return to IDLE. Safe to
        call when already idle (no-op)."""
        if self._state == _STATE_IDLE:
            return
        self._halt_stepper()
        self._logger.info(f"ch2 separation cancelled ({reason})")
        self._state = _STATE_IDLE
        self._state_entered_at = 0.0

    def step(self, now_mono: float, allowed: bool) -> None:
        """Advance the state machine one tick. When ``allowed`` is False the
        driver hard-cancels. Otherwise the current phase is checked against
        its timer and transitioned when elapsed."""
        if not allowed:
            self.cancel("preempt")
            return

        if self._state == _STATE_IDLE:
            self._enter(_STATE_PULSE_CW, now_mono)
            return

        phase = _PHASES[self._state]
        if (now_mono - self._state_entered_at) >= phase.duration_s:
            self._enter(phase.next_state, now_mono)

    def _enter(self, new_state: str, now_mono: float) -> None:
        phase = _PHASES[new_state]
        try:
            if self._state == _STATE_IDLE:
                self._stepper.enabled = True
            self._stepper.move_at_speed(phase.speed)
        except Exception as exc:
            self._logger.warning(
                f"ch2 separation enter {new_state} failed: {exc}"
            )
            # Revert to idle with a best-effort stop so the next allowed
            # tick restarts cleanly from PULSE_CW.
            self._halt_stepper()
            self._state = _STATE_IDLE
            self._state_entered_at = 0.0
            return
        self._state = new_state
        self._state_entered_at = now_mono

    def _halt_stepper(self) -> None:
        try:
            self._stepper.move_at_speed(0)
        except Exception as exc:
            self._logger.warning(f"ch2 separation halt failed: {exc}")


__all__ = ["Ch2SeparationDriver"]
