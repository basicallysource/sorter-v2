import time
from dataclasses import dataclass
from typing import Any, Optional

from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter

from .constants import C4_TRAVEL_SIGN, LOG_TAG

# Shared "advance the carousel forward until the channel is empty" routine. Both
# the spoke-home pre-purge and the C4 stuck-incident auto-resolve drive it, so
# they clear the channel the same way and agree on when it is actually clear.
# Forward == the same travel direction the normal classification flow uses to
# push a piece to the fall-off (discharge applies C4_TRAVEL_SIGN), so a piece is
# carried OUT the exit, never back toward the entry.
_CLEAR_STEP_OUTPUT_DEG = 72.0  # one 5-sector spoke per increment
_CLEAR_MAX_OUTPUT_DEG = 720.0  # two full revolutions before giving up


@dataclass(frozen=True)
class ChannelClearResult:
    cleared: bool
    occupied_at_start: bool
    output_deg_moved: float
    reason: str


def _carouselStepper(irl: Any) -> Any:
    # These three attributes are aliases for the same physical motor (see
    # irl/config.py); try each so the helper works regardless of which name a
    # given setup exposes.
    return (
        getattr(irl, "carousel_stepper", None)
        or getattr(irl, "classification_channel_rotor_stepper", None)
        or getattr(irl, "c_channel_4_rotor_stepper", None)
    )


def _rev01RotateSpeed() -> int:
    try:
        from toml_config import getClassificationChannelRev01Config

        from .rev01_config import configFromDict

        return int(configFromDict(getClassificationChannelRev01Config()).rotate_speed_usteps_per_s)
    except Exception:
        return 5000


def channelOccupied(gc: Any, vision: Any = None) -> Optional[bool]:
    # The same n_pieces signal the discharge loop trusts. Vision bboxes are only
    # a fallback for when perception is not running. Returns None when neither
    # source can answer (caller then advances the full blind budget).
    perception_service = getattr(gc, "perception_service", None)
    if perception_service is not None:
        try:
            return int(perception_service.read_state(4).n_pieces) > 0
        except Exception:
            pass
    if vision is not None:
        try:
            from .vision import Rev01Vision

            return len(Rev01Vision(vision, gc).bboxesOnChannel()) > 0
        except Exception:
            pass
    return None


def _advanceOneStep(stepper: Any, step_microsteps: int, speed_usteps_per_s: int) -> bool:
    # Blocking so the occupancy re-check happens only after the carousel has
    # actually settled, never mid-move.
    estimate_ms = 2000
    try:
        estimate_ms = int(stepper.estimateMoveStepsMs(step_microsteps, max(16, speed_usteps_per_s)))
    except Exception:
        pass
    timeout_ms = max(2000, estimate_ms * 2 + 1000)
    blocking = getattr(stepper, "move_steps_blocking", None)
    if callable(blocking):
        return bool(blocking(int(step_microsteps), timeout_ms=timeout_ms))
    if not bool(stepper.move_steps(int(step_microsteps))):
        return False
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if bool(getattr(stepper, "stopped", True)):
            return True
        time.sleep(0.01)
    return True


def clearChannelByAdvancing(
    gc: Any,
    irl: Any,
    irl_config: Any,
    *,
    vision: Any = None,
    speed_usteps_per_s: Optional[int] = None,
    step_output_deg: float = _CLEAR_STEP_OUTPUT_DEG,
    max_output_deg: float = _CLEAR_MAX_OUTPUT_DEG,
    label: str = LOG_TAG,
) -> ChannelClearResult:
    occupied = channelOccupied(gc, vision)
    if occupied is False:
        gc.logger.info(f"{label} channel clear: already empty, nothing to advance")
        return ChannelClearResult(True, False, 0.0, "already_clear")

    stepper = _carouselStepper(irl)
    if stepper is None:
        gc.logger.warning(f"{label} channel clear: carousel stepper unavailable")
        return ChannelClearResult(False, bool(occupied), 0.0, "no_stepper")

    if speed_usteps_per_s is None:
        speed_usteps_per_s = _rev01RotateSpeed()
    try:
        stepper.set_speed_limits(16, max(16, int(speed_usteps_per_s)))
    except Exception as exc:
        gc.logger.warning(f"{label} channel clear: set_speed_limits failed: {exc}")

    platter = C4FiveSectorPlatter.from_irl_config(irl_config)
    step_microsteps = platter.output_degrees_to_motor_microsteps(
        C4_TRAVEL_SIGN * abs(step_output_deg)
    )

    if occupied is None:
        gc.logger.info(
            f"{label} channel clear: occupancy unknown — advancing up to "
            f"{abs(max_output_deg):.0f}° blind"
        )
    else:
        gc.logger.info(
            f"{label} channel clear: piece on channel — advancing forward in "
            f"{abs(step_output_deg):.0f}° steps until clear (max {abs(max_output_deg):.0f}°)"
        )

    moved_output_deg = 0.0
    while moved_output_deg < abs(max_output_deg):
        if not _advanceOneStep(stepper, step_microsteps, int(speed_usteps_per_s)):
            gc.logger.warning(f"{label} channel clear: advance move not acknowledged — aborting")
            return ChannelClearResult(False, True, moved_output_deg, "move_failed")
        moved_output_deg += abs(step_output_deg)
        occupied = channelOccupied(gc, vision)
        if occupied is False:
            gc.logger.info(
                f"{label} channel clear: channel empty after advancing {moved_output_deg:.0f}°"
            )
            return ChannelClearResult(True, True, moved_output_deg, "cleared")

    cleared = channelOccupied(gc, vision) is False
    gc.logger.info(
        f"{label} channel clear: advanced full budget {moved_output_deg:.0f}° (cleared={cleared})"
    )
    return ChannelClearResult(
        cleared, True, moved_output_deg, "cleared" if cleared else "budget_exhausted"
    )
