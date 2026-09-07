"""Bring every stepper the IRL knows to a stop.

Used at the two moments where a stepper may still be executing a command
nobody remembers: right after the hardware is (re)discovered — a crashed
backend never got to stop the motors, and the fresh process assumes they are
idle — and first thing at shutdown, before cameras and vision are torn down.
Seen 2026-09-05: a belt started 1 s before a crash ran through restart and
homing and flooded C3 with 40 pieces.
"""
from __future__ import annotations

from typing import Any, Iterable

STEPPER_ATTRIBUTES: tuple[str, ...] = (
    "c_channel_1_rotor_stepper",
    "c_channel_2_rotor_stepper",
    "c_channel_3_rotor_stepper",
    "c_channel_4_rotor_stepper",
    "carousel_stepper",
    "chute_stepper",
)


def irlSteppers(irl: Any) -> list[tuple[str, Any]]:
    seen: set[int] = set()
    out: list[tuple[str, Any]] = []
    for name in STEPPER_ATTRIBUTES:
        stepper = getattr(irl, name, None)
        if stepper is None or id(stepper) in seen:
            continue
        seen.add(id(stepper))
        out.append((name, stepper))
    return out


def stopStepper(stepper: Any) -> None:
    """Zero the speed first (a running move_at_speed is the dangerous case),
    then halt if the stepper offers it."""
    move_at_speed = getattr(stepper, "move_at_speed", None)
    if callable(move_at_speed):
        move_at_speed(0)
    halt = getattr(stepper, "halt", None)
    if callable(halt):
        halt(disable_driver=False)


def stopAllSteppers(irl: Any, logger: Any, *, reason: str) -> list[str]:
    """Stop every stepper; failures are logged, never raised — this runs on
    paths (crash shutdown, recovery start) that must not abort."""
    stopped: list[str] = []
    for name, stepper in irlSteppers(irl):
        try:
            stopStepper(stepper)
            stopped.append(name)
        except Exception as exc:
            logger.warning(f"Stepper '{name}': stop failed during {reason}: {exc}")
    if stopped:
        logger.info(f"Stopped steppers ({reason}): {', '.join(stopped)}")
    return stopped
