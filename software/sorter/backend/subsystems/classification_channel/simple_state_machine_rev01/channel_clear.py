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


_SHAKE_JITTER_TIMEOUT_S = 6.0


def _waitJitterDone(stepper: Any, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    probe = getattr(stepper, "is_jittering", None)
    while time.monotonic() < deadline:
        try:
            if not callable(probe) or not bool(probe()):
                return
        except Exception:
            return
        time.sleep(0.05)


def shakeChannelClear(
    gc: Any,
    irl: Any,
    irl_config: Any,
    *,
    vision: Any = None,
    label: str = LOG_TAG,
) -> ChannelClearResult:
    """Second stall-recovery action, for a piece that forward rotation cannot
    move (e.g. a tyre resting on the fall-off lip): walk the exit-release
    shimmy ladder from irl_config (calm to firm, output degrees), re-checking
    occupancy after every stage. Blocking; coordinator thread only."""
    occupied = channelOccupied(gc, vision)
    if occupied is False:
        return ChannelClearResult(True, False, 0.0, "already_clear")
    stepper = _carouselStepper(irl)
    if stepper is None:
        return ChannelClearResult(False, bool(occupied), 0.0, "no_stepper")
    # The ladder lives on the classification-channel config; accept the bare
    # channel config too (tests, legacy callers).
    cc = getattr(irl_config, "classification_channel_config", None) or irl_config
    stages = tuple(getattr(cc, "exit_release_shimmy_stages", None) or ())
    ratio = float(getattr(cc, "exit_release_shimmy_stepper_per_output_deg", 0.0) or 0.0)
    if not stages or ratio <= 0.0:
        return ChannelClearResult(False, True, 0.0, "no_shimmy_config")
    jitter = getattr(stepper, "jitter_degrees", None)
    if not callable(jitter):
        return ChannelClearResult(False, True, 0.0, "no_jitter")

    for stage in stages:
        amplitude_stepper_deg = float(stage.amplitude_output_deg) * ratio
        gc.logger.info(
            f"{label} channel shake: stage '{stage.name}' "
            f"{stage.amplitude_output_deg:.2f}° x{stage.cycles} @ {stage.microsteps_per_second} µsteps/s"
        )
        try:
            ok = bool(jitter(
                amplitude_stepper_deg,
                int(stage.cycles),
                int(stage.microsteps_per_second),
                int(stage.acceleration_microsteps_per_second_sq),
                force=True,
            ))
        except Exception as exc:
            gc.logger.warning(f"{label} channel shake: jitter failed at '{stage.name}': {exc}")
            return ChannelClearResult(False, True, 0.0, "jitter_failed")
        if not ok:
            return ChannelClearResult(False, True, 0.0, "jitter_failed")
        _waitJitterDone(stepper, _SHAKE_JITTER_TIMEOUT_S)
        time.sleep(max(0, int(stage.settle_ms)) / 1000.0)
        if channelOccupied(gc, vision) is False:
            gc.logger.info(f"{label} channel shake: channel empty after stage '{stage.name}'")
            return ChannelClearResult(True, True, 0.0, "shaken_clear")
    gc.logger.warning(f"{label} channel shake: still occupied after {len(stages)} stages")
    return ChannelClearResult(False, True, 0.0, "shake_exhausted")
