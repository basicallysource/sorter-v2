"""A channel's rotor as a recovery moves it: turns in output degrees, shakes,
and whether it has finished moving. The dashboard's Shake menu goes through the
same ``shake``."""

from __future__ import annotations

from typing import Any, Callable

from .profiles import ShakeProfile, shakeSeconds

MIN_SPEED = 16
TURN_SPEED = 1500


class ChannelMotor:
    def __init__(
        self,
        label: str,
        stepper: Any,
        to_microsteps: Callable[[float], int],
        speed: int = TURN_SPEED,
    ) -> None:
        self.label = label
        self.stepper = stepper
        self._to_microsteps = to_microsteps
        self.speed = speed

    def turn(self, output_deg: float) -> float | None:
        """Turn the channel (negative: backwards). Returns about how long it
        takes, or None when the motor refused."""
        steps = int(self._to_microsteps(output_deg))
        if steps == 0:
            return 0.0
        try:
            self.stepper.set_speed_limits(MIN_SPEED, self.speed)
        except Exception:
            pass
        if not self.stepper.move_steps(steps):
            return None
        return self.stepper.estimateMoveStepsMs(abs(steps), max_speed=self.speed) / 1000.0

    def shake(self, profile: ShakeProfile) -> float | None:
        """Shake the channel with ``profile``. Returns about how long it takes,
        or None when the motor refused (it is still shaking, say)."""
        if not self.stepper.jitter_degrees(
            profile.amplitude_deg, profile.cycles, profile.speed, profile.acceleration
        ):
            return None
        return shakeSeconds(profile, self.stepper.microsteps_for_degrees(profile.amplitude_deg))

    def idle(self) -> bool:
        try:
            if not bool(self.stepper.stopped):
                return False
            jittering = getattr(self.stepper, "is_jittering", None)
            return not (callable(jittering) and jittering())
        except Exception:
            return True


def gearedMicrosteps(stepper: Any, motor_deg_per_output_deg: float, sign: int = 1) -> Callable[[float], int]:
    """Output degrees to microsteps for a channel driven through a gear."""
    return lambda output_deg: stepper.microsteps_for_degrees(sign * output_deg * motor_deg_per_output_deg)
