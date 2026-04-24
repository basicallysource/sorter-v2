"""Named C-channel motion profiles plus ramp-aware diagnostics.

This module is the runtime-facing home for stepper motion policy. The bridge
still touches legacy ``irl`` steppers, but the policy is no longer a handful of
local speed/acceleration calls hidden inside each channel callable.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_MIN_SPEED_USTEPS_PER_S = 16
DEFAULT_ACCELERATION_USTEPS_PER_S2 = 10000

PROFILE_GENTLE = "gentle"
PROFILE_TRANSPORT = "transport"
PROFILE_CONTINUOUS = "continuous"
PROFILE_DIRECT = "direct"
PROFILE_PURGE = "purge"
PROFILE_WIGGLE = "wiggle"
PROFILE_SHAKE = "shake"
PROFILE_UNJAM = "unjam"
PROFILE_EJECT = "eject"


_WARN_SHORT_MOVE_PROFILES = {
    PROFILE_TRANSPORT,
    PROFILE_CONTINUOUS,
    PROFILE_DIRECT,
    PROFILE_PURGE,
    PROFILE_UNJAM,
}


@dataclass(frozen=True, slots=True)
class MotionProfile:
    """One named speed/acceleration policy for a single stepper move."""

    channel: str
    name: str
    min_speed_usteps_per_s: int = DEFAULT_MIN_SPEED_USTEPS_PER_S
    max_speed_usteps_per_s: int | None = None
    acceleration_usteps_per_s2: int | None = DEFAULT_ACCELERATION_USTEPS_PER_S2
    warn_on_short_move: bool = False
    warn_duration_ratio: float = 1.25

    def with_name(self, name: str) -> "MotionProfile":
        return MotionProfile(
            channel=self.channel,
            name=name,
            min_speed_usteps_per_s=self.min_speed_usteps_per_s,
            max_speed_usteps_per_s=self.max_speed_usteps_per_s,
            acceleration_usteps_per_s2=self.acceleration_usteps_per_s2,
            warn_on_short_move=name in _WARN_SHORT_MOVE_PROFILES,
            warn_duration_ratio=self.warn_duration_ratio,
        )


@dataclass(frozen=True, slots=True)
class MotionPlan:
    """Computed ramp facts for one intended move."""

    profile: MotionProfile
    source: str
    distance_usteps: int | None
    degrees: float | None = None
    expected_duration_ms: float | None = None
    reaches_cruise: bool | None = None
    accel_distance_usteps: float | None = None
    peak_speed_usteps_per_s: float | None = None
    estimated_duration_ms: float | None = None
    warnings: tuple[str, ...] = ()
    ok: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.profile.channel,
            "profile": self.profile.name,
            "source": self.source,
            "degrees": self.degrees,
            "distance_usteps": self.distance_usteps,
            "min_speed_usteps_per_s": self.profile.min_speed_usteps_per_s,
            "max_speed_usteps_per_s": self.profile.max_speed_usteps_per_s,
            "acceleration_usteps_per_s2": self.profile.acceleration_usteps_per_s2,
            "expected_duration_ms": self.expected_duration_ms,
            "estimated_duration_ms": self.estimated_duration_ms,
            "reaches_cruise": self.reaches_cruise,
            "accel_distance_usteps": self.accel_distance_usteps,
            "peak_speed_usteps_per_s": self.peak_speed_usteps_per_s,
            "warnings": list(self.warnings),
            "ok": self.ok,
        }

    def with_result(self, ok: bool) -> "MotionPlan":
        return MotionPlan(
            profile=self.profile,
            source=self.source,
            distance_usteps=self.distance_usteps,
            degrees=self.degrees,
            expected_duration_ms=self.expected_duration_ms,
            reaches_cruise=self.reaches_cruise,
            accel_distance_usteps=self.accel_distance_usteps,
            peak_speed_usteps_per_s=self.peak_speed_usteps_per_s,
            estimated_duration_ms=self.estimated_duration_ms,
            warnings=self.warnings,
            ok=ok,
        )


class MotionDiagnostics:
    """Thread-safe last-motion read model for ``/api/rt/status``."""

    def __init__(self, *, warn_throttle_s: float = 10.0) -> None:
        self._lock = threading.Lock()
        self._last_by_channel: dict[str, dict[str, Any]] = {}
        self._last_by_key: dict[str, dict[str, Any]] = {}
        self._warned_at: dict[tuple[str, str, str, int | None], float] = {}
        self._warn_throttle_s = max(0.0, float(warn_throttle_s))

    def record(
        self,
        plan: MotionPlan,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        data = plan.as_dict()
        key = f"{plan.profile.channel}.{plan.profile.name}"
        with self._lock:
            self._last_by_channel[plan.profile.channel] = data
            self._last_by_key[key] = data
        if logger is not None:
            self.warn_if_needed(plan, logger)

    def warn_if_needed(self, plan: MotionPlan, logger: logging.Logger) -> None:
        for reason in plan.warnings:
            bucket = _distance_bucket(plan.distance_usteps)
            key = (plan.profile.channel, plan.profile.name, reason, bucket)
            now = time.monotonic()
            with self._lock:
                last = self._warned_at.get(key)
                if last is not None and (now - last) < self._warn_throttle_s:
                    continue
                self._warned_at[key] = now
            logger.warning(
                "motion-profile warning channel=%s profile=%s source=%s reason=%s "
                "distance_usteps=%s target_speed=%s accel=%s peak_speed=%.1f "
                "estimated_ms=%s expected_ms=%s reaches_cruise=%s",
                plan.profile.channel,
                plan.profile.name,
                plan.source,
                reason,
                plan.distance_usteps,
                plan.profile.max_speed_usteps_per_s,
                plan.profile.acceleration_usteps_per_s2,
                float(plan.peak_speed_usteps_per_s or 0.0),
                _round_or_none(plan.estimated_duration_ms),
                _round_or_none(plan.expected_duration_ms),
                plan.reaches_cruise,
            )

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "last_by_channel": dict(self._last_by_channel),
                "last_by_profile": dict(self._last_by_key),
            }


def profile_from_values(
    *,
    channel: str,
    name: str,
    max_speed: int | None,
    acceleration: int | None = DEFAULT_ACCELERATION_USTEPS_PER_S2,
    min_speed: int | None = DEFAULT_MIN_SPEED_USTEPS_PER_S,
) -> MotionProfile:
    return MotionProfile(
        channel=channel,
        name=name,
        min_speed_usteps_per_s=_positive_int(min_speed)
        or DEFAULT_MIN_SPEED_USTEPS_PER_S,
        max_speed_usteps_per_s=_positive_int(max_speed),
        acceleration_usteps_per_s2=_positive_int(acceleration),
        warn_on_short_move=name in _WARN_SHORT_MOVE_PROFILES,
    )


def profile_from_rotor_config(
    *,
    channel: str,
    name: str,
    cfg: Any,
    default_speed: int | None = None,
    default_acceleration: int | None = DEFAULT_ACCELERATION_USTEPS_PER_S2,
) -> MotionProfile:
    speed = _positive_int(getattr(cfg, "microsteps_per_second", None))
    if speed is None:
        speed = _positive_int(default_speed)
    acceleration = _positive_int(
        getattr(cfg, "acceleration_microsteps_per_second_sq", None)
    )
    if acceleration is None:
        acceleration = _positive_int(default_acceleration)
    return profile_from_values(
        channel=channel,
        name=name,
        max_speed=speed,
        acceleration=acceleration,
    )


def plan_motion(
    profile: MotionProfile,
    *,
    source: str,
    distance_usteps: int | None,
    degrees: float | None = None,
    expected_duration_ms: float | None = None,
) -> MotionPlan:
    distance = abs(int(distance_usteps)) if distance_usteps is not None else None
    max_speed = _positive_int(profile.max_speed_usteps_per_s)
    min_speed = _positive_int(profile.min_speed_usteps_per_s) or 0
    acceleration = _positive_int(profile.acceleration_usteps_per_s2)
    if distance is None or distance <= 0 or max_speed is None or acceleration is None:
        return MotionPlan(
            profile=profile,
            source=source,
            distance_usteps=distance,
            degrees=degrees,
            expected_duration_ms=expected_duration_ms,
        )

    min_speed = min(min_speed, max_speed)
    accel_distance = max(
        0.0,
        ((max_speed * max_speed) - (min_speed * min_speed))
        / (2.0 * acceleration),
    )
    needed_for_cruise = accel_distance * 2.0
    reaches_cruise = distance >= needed_for_cruise
    if reaches_cruise:
        peak_speed = float(max_speed)
        accel_time = max(0.0, (max_speed - min_speed) / acceleration)
        cruise_distance = max(0.0, distance - needed_for_cruise)
        cruise_time = cruise_distance / max_speed if max_speed > 0 else 0.0
        duration_ms = (2.0 * accel_time + cruise_time) * 1000.0
    else:
        peak_speed = math.sqrt(max(0.0, (min_speed * min_speed) + acceleration * distance))
        duration_ms = (2.0 * max(0.0, peak_speed - min_speed) / acceleration) * 1000.0

    warnings: list[str] = []
    if profile.warn_on_short_move and not reaches_cruise:
        warnings.append("target_speed_unreachable")
    if (
        expected_duration_ms is not None
        and expected_duration_ms > 0.0
        and duration_ms > expected_duration_ms * profile.warn_duration_ratio
    ):
        warnings.append("estimated_duration_exceeds_expected")

    return MotionPlan(
        profile=profile,
        source=source,
        distance_usteps=distance,
        degrees=degrees,
        expected_duration_ms=expected_duration_ms,
        reaches_cruise=reaches_cruise,
        accel_distance_usteps=accel_distance,
        peak_speed_usteps_per_s=peak_speed,
        estimated_duration_ms=duration_ms,
        warnings=tuple(warnings),
    )


def apply_profile(
    stepper: Any,
    profile: MotionProfile,
) -> None:
    acceleration = _positive_int(profile.acceleration_usteps_per_s2)
    if acceleration is not None and hasattr(stepper, "set_acceleration"):
        stepper.set_acceleration(acceleration)
    speed = _positive_int(profile.max_speed_usteps_per_s)
    if speed is not None and hasattr(stepper, "set_speed_limits"):
        stepper.set_speed_limits(profile.min_speed_usteps_per_s, speed)


def move_degrees_with_profile(
    stepper: Any,
    profile: MotionProfile,
    degrees: float,
    *,
    source: str,
    logger: logging.Logger,
    diagnostics: MotionDiagnostics | None = None,
    expected_duration_ms: float | None = None,
) -> bool:
    distance_usteps = microsteps_for_degrees(stepper, degrees)
    plan = plan_motion(
        profile,
        source=source,
        distance_usteps=distance_usteps,
        degrees=float(degrees),
        expected_duration_ms=expected_duration_ms,
    )
    apply_profile(stepper, profile)
    ok = bool(stepper.move_degrees(degrees))
    if diagnostics is not None:
        diagnostics.record(plan.with_result(ok), logger=logger)
    elif plan.warnings:
        MotionDiagnostics(warn_throttle_s=0.0).warn_if_needed(plan, logger)
    return ok


def microsteps_for_degrees(stepper: Any, degrees: float) -> int | None:
    fn = getattr(stepper, "microsteps_for_degrees", None)
    if callable(fn):
        try:
            return abs(int(fn(float(degrees))))
        except Exception:
            return None
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    coerced = int(value)
    return coerced if coerced > 0 else None


def _distance_bucket(distance_usteps: int | None) -> int | None:
    if distance_usteps is None:
        return None
    return int(round(float(distance_usteps) / 50.0) * 50)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


__all__ = [
    "DEFAULT_ACCELERATION_USTEPS_PER_S2",
    "DEFAULT_MIN_SPEED_USTEPS_PER_S",
    "MotionDiagnostics",
    "MotionPlan",
    "MotionProfile",
    "PROFILE_CONTINUOUS",
    "PROFILE_DIRECT",
    "PROFILE_EJECT",
    "PROFILE_GENTLE",
    "PROFILE_PURGE",
    "PROFILE_SHAKE",
    "PROFILE_TRANSPORT",
    "PROFILE_UNJAM",
    "PROFILE_WIGGLE",
    "apply_profile",
    "microsteps_for_degrees",
    "move_degrees_with_profile",
    "plan_motion",
    "profile_from_rotor_config",
    "profile_from_values",
]
