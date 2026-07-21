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


# Phantom drop-zone recovery. When rotating the platter can't clear a stall, the
# "piece" the C4 camera sees in the drop zone is almost always hung at the
# feeder->classification hand-off — physically on the last feeder rotor's exit,
# not on the platter — so turning the platter does nothing to it. Nudging the
# feeder rotor that feeds C4 forward a couple output degrees either pushes it the
# rest of the way onto the platter (where it becomes a normal, classifiable
# piece) or frees it entirely. Matches the feeder's own output gearing.
_FEEDER_OUTPUT_GEAR_RATIO = 130.0 / 12.0  # keep in sync with pulse_perception flow.py
_PHANTOM_NUDGE_OUTPUT_DEG = 2.0


def _upstreamFeederStepper(irl: Any, cfg: Any) -> tuple:
    # The feeder rotor that hands pieces into the classification channel's drop
    # zone. Pick the highest-numbered ENABLED feeder rotor: C3 on the default
    # three-feeder machine, C1 on a bulk->classification build. Either way it's
    # the rotor physically holding a piece hung at the C4 drop-zone lip.
    candidates = (
        ("enable_ch3", "c_channel_3_rotor_stepper", "C3"),
        ("enable_ch2", "c_channel_2_rotor_stepper", "C2"),
        ("enable_ch1", "c_channel_1_rotor_stepper", "C1"),
    )
    for enable_key, attr, label in candidates:
        if cfg is not None and not bool(getattr(cfg, enable_key, True)):
            continue
        stepper = getattr(irl, attr, None)
        if stepper is not None:
            return stepper, label
    return None, ""


def _nudgeBlocking(stepper: Any, motor_deg: float) -> bool:
    blocking = getattr(stepper, "move_degrees_blocking", None)
    if callable(blocking):
        return bool(blocking(float(motor_deg), timeout_ms=5000))
    if not bool(stepper.move_degrees(float(motor_deg))):
        return False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if bool(getattr(stepper, "stopped", True)):
            return True
        time.sleep(0.01)
    return True


def nudgeUpstreamFeederOnce(
    gc: Any,
    irl: Any,
    *,
    output_deg: float = _PHANTOM_NUDGE_OUTPUT_DEG,
    label: str = LOG_TAG,
) -> Optional[float]:
    """One phantom-recovery nudge: advance the feeder rotor that feeds C4 forward
    a couple output degrees to free (or seat) a piece hung at the
    feeder->classification hand-off that the C4 camera reads as a drop-zone piece
    the platter can't move. Returns the output degrees moved, or None if there
    was no feeder rotor to nudge / the move was not acknowledged. Blocking; must
    only run on the coordinator thread (same as clearChannelByAdvancing)."""
    try:
        from toml_config import getPulsePerceptionConfig
        from subsystems.feeder.pulse_perception.config import configFromDict

        cfg = configFromDict(getPulsePerceptionConfig())
    except Exception:
        cfg = None

    stepper, ch_label = _upstreamFeederStepper(irl, cfg)
    if stepper is None:
        gc.logger.warning(f"{label} phantom nudge: no upstream feeder rotor available")
        return None

    sign = 1
    speed = 2000
    if cfg is not None:
        sign = 1 if int(getattr(cfg, "forward_direction_sign", 1)) >= 0 else -1
        speed = int(getattr(cfg, "move_speed_usteps_per_s", 2000))
    motor_deg = sign * float(output_deg) * _FEEDER_OUTPUT_GEAR_RATIO

    try:
        stepper.enabled = True
    except Exception:
        pass
    try:
        stepper.set_speed_limits(16, max(16, int(speed)))
    except Exception as exc:
        gc.logger.warning(f"{label} phantom nudge: set_speed_limits failed: {exc}")

    if not _nudgeBlocking(stepper, motor_deg):
        gc.logger.warning(f"{label} phantom nudge: {ch_label} move not acknowledged")
        return None
    time.sleep(0.25)
    gc.logger.info(
        f"{label} phantom nudge: advanced {ch_label} feeder forward {abs(output_deg):.1f}°"
    )
    return float(abs(output_deg))
