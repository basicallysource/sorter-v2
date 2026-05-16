from __future__ import annotations

from typing import Any

import server.shared_state as shared_state

CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0
MOTOR_STEPS_PER_REVOLUTION = 200
MIN_STEPPER_SPEED_MICROSTEPS_PER_SECOND = 16


def output_rpm_to_microsteps_per_second(
    rpm: float,
    *,
    microsteps: int = 8,
    gear_ratio: float = CHANNEL_OUTPUT_GEAR_RATIO,
    steps_per_revolution: int = MOTOR_STEPS_PER_REVOLUTION,
) -> int:
    speed = float(rpm) * int(steps_per_revolution) * int(microsteps) * float(gear_ratio) / 60.0
    return max(MIN_STEPPER_SPEED_MICROSTEPS_PER_SECOND, int(round(speed)))


def microsteps_per_second_to_output_rpm(
    microsteps_per_second: int | float,
    *,
    microsteps: int = 8,
    gear_ratio: float = CHANNEL_OUTPUT_GEAR_RATIO,
    steps_per_revolution: int = MOTOR_STEPS_PER_REVOLUTION,
) -> float:
    denominator = int(steps_per_revolution) * int(microsteps) * float(gear_ratio)
    if denominator <= 0:
        return 0.0
    return float(microsteps_per_second) * 60.0 / denominator


def microsteps_from_stepper_config(stepper_config: Any, fallback: int = 8) -> int:
    value = getattr(stepper_config, "microsteps", fallback)
    if isinstance(value, bool):
        return int(fallback)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(fallback)
    return parsed if parsed > 0 else int(fallback)


def sample_collection_effective_speed_microsteps_per_second(
    role: str,
    *,
    default_microsteps_per_second: int,
    microsteps: int = 8,
    enabled: bool,
) -> int | None:
    if not enabled:
        return None
    rpm = shared_state.getSampleCollectionSpeedRpm(role)
    if rpm is None:
        return int(default_microsteps_per_second)
    return output_rpm_to_microsteps_per_second(float(rpm), microsteps=microsteps)


def default_speed_rpm(
    default_microsteps_per_second: int,
    *,
    microsteps: int = 8,
) -> float:
    return round(
        microsteps_per_second_to_output_rpm(
            int(default_microsteps_per_second),
            microsteps=microsteps,
        ),
        2,
    )
