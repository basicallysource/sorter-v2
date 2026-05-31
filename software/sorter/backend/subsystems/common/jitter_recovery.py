from dataclasses import dataclass
from enum import Enum


@dataclass
class JitterParams:
    amplitude_motor_deg: float
    cycles: int
    speed_usteps_per_s: int
    accel_usteps_per_s2: int
    pause_ms: int
    max_attempts: int = 3


class JitterPhase(str, Enum):
    IDLE = "idle"
    JITTERING = "jittering"
    PAUSE = "pause"
    # Transient — returned from tick() the instant the sequence resolves.
    # The sequence is back in IDLE on the next call.
    CLEARED = "cleared"
    EXHAUSTED = "exhausted"


class JitterSequence:
    """Multi-attempt jitter recovery on a single stepper, driven by caller ticks.

    Owns: the stepper jitter command, attempt counter, inter-attempt pause timer.
    Does NOT own: the trigger (caller calls start()), the 'still stuck'
    predicate (caller passes still_stuck=bool to tick()), or whatever happens
    after EXHAUSTED (caller decides).
    """

    def __init__(self, stepper, params: JitterParams, *, label: str, logger):
        self._stepper = stepper
        self._params = params
        self._label = label
        self._logger = logger
        self._phase: JitterPhase = JitterPhase.IDLE
        self._attempts: int = 0
        self._pause_until: float = 0.0

    @property
    def attempts_made(self) -> int:
        return self._attempts

    @property
    def is_active(self) -> bool:
        return self._phase != JitterPhase.IDLE

    @property
    def phase(self) -> JitterPhase:
        return self._phase

    def reset(self) -> None:
        self._phase = JitterPhase.IDLE
        self._attempts = 0
        self._pause_until = 0.0

    def start(self) -> bool:
        if self.is_active:
            return False
        self.reset()
        return self._fire_jitter()

    def tick(self, *, still_stuck: bool, now: float) -> JitterPhase:
        if self._phase == JitterPhase.IDLE:
            return JitterPhase.IDLE

        if self._phase == JitterPhase.JITTERING:
            if self._jitter_in_progress():
                return JitterPhase.JITTERING
            self._phase = JitterPhase.PAUSE
            self._pause_until = now + (self._params.pause_ms / 1000.0)
            return JitterPhase.PAUSE

        if self._phase == JitterPhase.PAUSE:
            if now < self._pause_until:
                return JitterPhase.PAUSE
            if not still_stuck:
                self._logger.info(
                    f"{self._label}: cleared after {self._attempts} jitter attempt(s)"
                )
                self.reset()
                return JitterPhase.CLEARED
            if self._attempts >= self._params.max_attempts:
                self._logger.warning(
                    f"{self._label}: exhausted {self._params.max_attempts} jitter attempt(s), "
                    f"still stuck"
                )
                self.reset()
                return JitterPhase.EXHAUSTED
            self._fire_jitter()
            return self._phase

        return self._phase

    def _jitter_in_progress(self) -> bool:
        try:
            return bool(self._stepper.is_jittering())
        except Exception:
            return False

    def _fire_jitter(self) -> bool:
        p = self._params
        try:
            ok = bool(
                self._stepper.jitter_degrees(
                    p.amplitude_motor_deg,
                    int(p.cycles),
                    int(p.speed_usteps_per_s),
                    int(p.accel_usteps_per_s2),
                    force=True,
                )
            )
        except Exception as exc:
            self._logger.warning(f"{self._label}: jitter command failed: {exc}")
            self.reset()
            return False
        if not ok:
            self._logger.warning(f"{self._label}: jitter command not acked")
            self.reset()
            return False
        self._attempts += 1
        self._phase = JitterPhase.JITTERING
        self._logger.info(
            f"{self._label}: jitter attempt {self._attempts}/{p.max_attempts} "
            f"(amp={p.amplitude_motor_deg}° motor, cycles={p.cycles})"
        )
        return True
