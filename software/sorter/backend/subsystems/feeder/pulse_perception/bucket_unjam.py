"""The bucket gives no pieces: C1 has been asked to feed for a while and nothing
has come off it, though the bucket may be full (the pieces have bridged, or
have lost their grip on the bowl). The feeder then shakes C1 a few times, turns
it half round in one go, pulses it the normal way and waits. A piece coming off
C1 at any point ends it. Nothing by the end: the bucket is taken as empty, and
nothing more is tried until pieces have come again or the operator says so.

This is C1's own state inside the feeder's step, not a recovery that holds the
machine (recovery/): C2, C3 and the classification channel keep working through
the pieces already on them. Its incident, "Potentially bucket empty", is a
warning beside whatever else is open: it says what is being tried, and keeps
what was. While a shake or the turn is being sent ``step`` returns True, and
the feeder sends C1 nothing of its own.

Only on a machine whose generation has ``bucket_unjam``. The numbers are the
feeder's ``bucket_*`` settings (config.py).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

import incidents
from recovery.motors import MIN_SPEED, ChannelMotor
from recovery.profiles import ShakeProfile

if TYPE_CHECKING:
    from .config import PulsePerceptionConfig

KIND = "potentially_bucket_empty"
SUBJECT = "C1"

WATCHING = "watching"
SHAKING = "shaking"
SWEEPING = "sweeping"
PULSING = "pulsing"
WAITING = "waiting"
GAVE_UP = "gave up"

# Steps further apart than this mean the feeder was not running in between
# (sorting paused, or an incident held the machine): that time counts for
# nothing here.
_GAP_S = 1.0
# A motor that should have finished by now is asked again this often.
_RECHECK_S = 0.2
# The feeder leaves C1 alone this long after the turn is braked.
_BRAKE_S = 0.5


class BucketUnjam:
    def __init__(
        self,
        gc: Any,
        shared: Any,
        motor: Callable[["PulsePerceptionConfig"], ChannelMotor],
        hold: Callable[[float], None],
        record: Callable[[dict], None],
    ) -> None:
        self.gc = gc
        self.shared = shared
        # C1's rotor, the feeder's own pulses held off it until a (monotonic)
        # time, and the feeder's control-data record.
        self._motor = motor
        self._hold = hold
        self._record = record
        self.state = WATCHING
        # How long C1 has been asked to feed since a piece last came off it.
        self._asked_s = 0.0
        self._stepped_at: float | None = None
        self._fed_at = shared.c1_fed_at
        self._opened_at = 0.0
        # Nothing more is sent to C1 before this; when the last shake ended;
        # when the pulsing, then the wait, ends.
        self._until = 0.0
        self._shook_at = 0.0
        self._ends_at = 0.0
        self._shakes = 0
        # The motor while it is on the turn, so a piece can stop it.
        self._turning: ChannelMotor | None = None
        self._tried: list[dict] = []

    def step(self, now: float, wants: bool, cfg: "PulsePerceptionConfig") -> bool:
        """One tick of the feeder. ``wants``: C1 is asked to feed (C2's landing
        zone is clear and C2 has room). True while C1's motor is taken for a
        shake or the turn: the feeder then sends it no pulse of its own."""
        gap = now - self._stepped_at if self._stepped_at is not None else 0.0
        self._stepped_at = now
        if gap > _GAP_S:
            self._until += gap
            self._shook_at += gap
            self._ends_at += gap
            gap = 0.0
        fed = self.shared.c1_fed_at != self._fed_at
        self._fed_at = self.shared.c1_fed_at
        if self.state == WATCHING:
            after = float(cfg.bucket_unjam_after_s)
            if fed or after <= 0:
                self._asked_s = 0.0
            elif wants:
                self._asked_s += gap
            if after <= 0 or self._asked_s < after:
                return False
            self._open(now, cfg, after)
            return True
        if fed:
            self._close(now, "pieces")
            return False
        if incidents.openWarning(self.gc, KIND) is None:
            # The operator pressed Done, or resumed sorting.
            self._close(now, "operator")
            return False
        if self.state == SHAKING:
            return self._shake(now, cfg)
        if self.state == SWEEPING:
            return self._sweep(now, cfg)
        # Pulsing, waiting or given up: C1 feeds the normal way.
        if self.state == PULSING and now >= self._ends_at:
            self.state = WAITING
            self._ends_at = max(now, self._shook_at + max(0.0, float(cfg.bucket_wait_s)))
            self._note(cfg, "waiting", seconds=round(self._ends_at - now, 1))
        if self.state == WAITING and now >= self._ends_at:
            self.state = GAVE_UP
            self._note(cfg, "gave_up", after_s=round(now - self._opened_at, 1))
        return False

    def pause(self, now: float) -> None:
        """Sorting paused or stopped: what was being tried ends there. A bucket
        already taken as empty stays so until sorting resumes."""
        if self.state not in (WATCHING, GAVE_UP):
            self._close(now, "paused")

    def _open(self, now: float, cfg: "PulsePerceptionConfig", asked_s: float) -> None:
        self.state = SHAKING
        self._asked_s = 0.0
        self._opened_at = self._until = self._shook_at = now
        self._shakes = 0
        self._tried = []
        self._note(cfg, "opened", asked_s=round(asked_s, 1))

    def _shake(self, now: float, cfg: "PulsePerceptionConfig") -> bool:
        """The next shake once the last one and its pause are over, and after
        the last of them the turn."""
        if now < self._until:
            return True
        motor = self._motor(cfg)
        if not motor.idle():
            # A pulse of the feeder's own, or a shake, is still finishing.
            self._until = now + _RECHECK_S
            return True
        count = max(0, int(cfg.bucket_shake_count))
        if self._shakes < count:
            self._shakes += 1
            profile = ShakeProfile(
                "bucket",
                "Sharp & short",
                "",
                abs(float(cfg.bucket_shake_stroke_motor_deg)),
                int(cfg.bucket_shake_cycles),
                int(cfg.bucket_shake_speed_usteps_per_s),
                int(cfg.bucket_shake_accel_usteps_per_s2),
            )
            # The profile is this motor's own: nothing of it is scaled here.
            seconds = motor.shake(profile, for_gearing=False)
            # A shake the motor refused counts as one made: no endless tries.
            self._shook_at = now + (seconds or 0.0)
            self._until = self._shook_at + max(0.0, float(cfg.bucket_shake_pause_s))
            self._hold(self._shook_at)
            self._note(
                cfg,
                "shake",
                n=self._shakes,
                of=count,
                ok=seconds is not None,
                stroke_usteps=motor.stepper.microsteps_for_degrees(profile.amplitude_deg),
                cycles=profile.cycles,
                speed=profile.speed,
                accel=profile.acceleration,
                seconds=round(seconds or 0.0, 2),
            )
            return True
        deg = max(0.0, float(cfg.bucket_sweep_output_deg))
        motor.speed = max(
            MIN_SPEED,
            motor.stepper.microsteps_for_degrees(abs(float(cfg.bucket_sweep_output_deg_per_s)) * motor.gear_ratio),
        )
        seconds = motor.turn(deg)
        self.state = SWEEPING
        self._turning = motor if seconds else None
        self._until = now + (seconds or 0.0)
        self._hold(self._until)
        self._note(
            cfg, "sweep", deg=deg, speed=motor.speed, ok=seconds is not None, seconds=round(seconds or 0.0, 2)
        )
        return True

    def _sweep(self, now: float, cfg: "PulsePerceptionConfig") -> bool:
        """Wait out the turn, then give C1 back to the feeder's pulses."""
        if now < self._until:
            return True
        if self._turning is not None and not self._turning.idle():
            self._until = now + _RECHECK_S
            return True
        self._turning = None
        self.state = PULSING
        seconds = max(0.0, float(cfg.bucket_pulse_s))
        self._ends_at = now + seconds
        self._note(cfg, "pulsing", seconds=seconds)
        return False

    def _close(self, now: float, by: str) -> None:
        """It is over without the bucket being taken as empty for good: a piece
        came ("pieces"), the operator said so, or sorting paused."""
        if self._turning is not None:
            # Still on its turn: brake it, so C1 stands as it does whenever a
            # piece lies where pieces land.
            self._turning.halt()
            self._turning = None
            self._hold(now + _BRAKE_S)
        self._record(
            {
                "kind": "bucket_unjam",
                "what": "resolved",
                "by": by,
                "during": self.state,
                "shakes": self._shakes,
                "after_s": round(now - self._opened_at, 1),
            }
        )
        if by == "pieces":
            by = "system" if self.state == GAVE_UP else "recovery"
        incidents.clear(self.gc, KIND, subject=SUBJECT, resolved_by=by)
        self.state = WATCHING
        self._asked_s = 0.0

    def _note(self, cfg: "PulsePerceptionConfig", what: str, **more: Any) -> None:
        """One step: into the control data, and onto the incident with what
        the card now says."""
        self._record({"kind": "bucket_unjam", "what": what, **more})
        self._tried.append({"what": what, "t": round(time.time(), 3), **more})
        if self.state == GAVE_UP:
            doing = (
                f"No piece came after {_times(self._shakes, 'shake')} and a turn of C1: the bucket may be "
                "empty. Check it or refill it, then press Done."
            )
        else:
            step = {
                "opened": "shaking C1",
                "shake": f"shake {self._shakes} of {max(0, int(cfg.bucket_shake_count))}",
                "sweep": "turning C1",
                "pulsing": "pulsing C1",
                "waiting": "waiting for a piece",
            }[what]
            doing = f"C1 gave no piece. Trying to free the bucket: {step}."
        incidents.report(
            self.gc,
            KIND,
            subject=SUBJECT,
            channel="c1",
            channel_label=SUBJECT,
            operator_message=doing,
            doing=doing,
            gave_up=self.state == GAVE_UP,
            tried=list(self._tried),
        )


def _times(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
