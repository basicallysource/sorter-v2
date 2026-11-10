"""The chute: its settings, homing, aiming calibration and test moves."""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import machine_toml
from hardware_settings.chute import (
    DEFAULT_ENDSTOP_ACTIVE_HIGH,
    DEFAULT_NUM_SECTIONS,
    ChuteSettings,
    applyChuteSettings,
    readChuteSettings,
    saveChuteSettings,
)
from irl.bin_layout import getBinLayout
from chute_calibrations import (
    activateChuteCalibrationInstance,
    deleteChuteCalibrationInstance,
    getChuteCalibrationInstance,
    listChuteCalibrationInstances,
    recordChuteCalibrationInstance,
)
from server import hardware_needs, shared_state
from server.routers.steppers import _stop_all_steppers
from subsystems.distribution.chute_homing import measureTurn
from subsystems.distribution.chute_variants import HOME_ON_MAGNET, VARIANTS

router = APIRouter()


# In both settings payloads a field left out stays as saved; a partial save
# never puts another setting back to its default.
class ChuteHardwareSettingsPayload(BaseModel):
    first_bin_center: Optional[float] = None
    pillar_width_deg: Optional[float] = None
    endstop_active_high: Optional[bool] = None
    operating_speed_microsteps_per_second: Optional[int] = None
    position_check: Optional[bool] = None
    position_check_every: Optional[int] = None


class ChuteAimingSettingsPayload(BaseModel):
    num_sections: Optional[int] = None
    section_width_deg: Optional[float] = None
    first_section_offset_deg: Optional[float] = None
    endstop_active_high: Optional[bool] = None
    operating_speed_microsteps_per_second: Optional[int] = None
    label: Optional[str] = None


class ChuteAimingDerivePayload(BaseModel):
    # Measurements from the calibration routine: the chute is jogged to the
    # first and last bin of a test section with a known bin count.
    first_bin_angle: float
    last_bin_angle: float
    bins_in_test_section: int
    num_sections: int = DEFAULT_NUM_SECTIONS
    label: Optional[str] = None


class ChuteMoveToAnglePayload(BaseModel):
    angle: float


class ChuteVariantPayload(BaseModel):
    variant: str


class ChuteDiscardBinPayload(BaseModel):
    # The bin, counted from 0, or all three left out to have none.
    layer_index: Optional[int] = None
    section_index: Optional[int] = None
    bin_index: Optional[int] = None


class ChuteVirtualBinPayload(BaseModel):
    num_sections: int
    bins_in_section: int
    section_index: int
    bin_index: int


def _pin_channel(pin: Any | None) -> int | None:
    channel = getattr(pin, "channel", None)
    if isinstance(channel, int) and not isinstance(channel, bool):
        return channel

    channel = getattr(pin, "_channel", None)
    if isinstance(channel, int) and not isinstance(channel, bool):
        return channel

    return None


def _live_chute() -> Any | None:
    irl = shared_state.getActiveIRL()
    return getattr(irl, "chute", None) if irl is not None else None


def _board_defaults() -> Dict[str, Any]:
    """The distribution board's own home input, polarity and kind of chute, used
    where none is saved. Only the running chute knows them; it was built with them."""
    chute = _live_chute()
    defaults: Dict[str, Any] = {}
    variant = getattr(chute, "variant", None)
    if variant is not None:
        defaults["variant_key"] = variant.key
    channel = _pin_channel(getattr(chute, "home_pin", None))
    if channel is not None:
        defaults["home_pin_channel"] = channel
    active_high = getattr(chute, "endstop_active_high", None)
    defaults["endstop_active_high"] = (
        active_high if isinstance(active_high, bool) else DEFAULT_ENDSTOP_ACTIVE_HIGH
    )
    return defaults


def _chute_payload(settings: ChuteSettings) -> Dict[str, Any]:
    return {
        "num_sections": settings.num_sections,
        "section_width_deg": round(settings.section_width_deg, 4),
        "first_section_offset_deg": round(settings.first_section_offset_deg, 4),
        "section_pitch_deg": round(settings.section_pitch_deg, 4),
        "pillar_width_deg": round(settings.pillar_width_deg, 4),
        # The legacy page's name for the first section's offset; saving it back
        # unchanged keeps the geometry as it is.
        "first_bin_center": round(settings.first_section_offset_deg, 4),
        "endstop_active_high": settings.endstop_active_high,
        "operating_speed_microsteps_per_second": settings.operating_speed_microsteps_per_second,
        "position_check": settings.position_check,
        "position_check_every": settings.position_check_every,
        "home_pin_channel": settings.home_pin_channel,
        # Which kind of chute this is, and what follows from it.
        "variant": settings.variant.key,
        "variant_label": settings.variant.label,
        "variant_saved": "variant" in settings.saved,
        "variants": [_variant_payload(variant) for variant in VARIANTS.values()],
        "turns_freely": settings.variant.turns_freely,
        "falls_through": settings.variant.falls_through,
        "fixed_bottom_door": settings.variant.fixed_bottom_door,
        "home_on": settings.variant.home_on,
        # None on a chute that turns without limit.
        "max_angle_deg": settings.variant.travel_deg,
        "gear_ratio": round(settings.gear_ratio or settings.variant.gear_ratio, 5),
        "gear_ratio_measured": settings.gear_ratio is not None,
        "discard_bin": (
            None
            if settings.discard_bin is None
            else dict(zip(("layer_index", "section_index", "bin_index"), settings.discard_bin))
        ),
    }


def _variant_payload(variant: Any) -> Dict[str, Any]:
    return {
        "key": variant.key,
        "label": variant.label,
        "summary": variant.summary,
        "turns_freely": variant.turns_freely,
        "falls_through": variant.falls_through,
        "fixed_bottom_door": variant.fixed_bottom_door,
        "home_on": variant.home_on,
    }


def _chute_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return _chute_payload(readChuteSettings(config, **_board_defaults()))


def _save_and_apply_chute(changes: Dict[str, Any]) -> tuple[ChuteSettings, bool]:
    """Save chute settings and put them on the running chute, if there is one.
    Returns the settings and whether they were applied now (otherwise they
    apply at the next start)."""
    try:
        settings = saveChuteSettings(changes, **_board_defaults())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    chute = _live_chute()
    if chute is None:
        return settings, False
    applyChuteSettings(chute, settings)
    return settings, True


def _live_chute_status() -> Dict[str, Any]:
    irl = shared_state.getActiveIRL()
    chute = getattr(irl, "chute", None)
    stepper = getattr(irl, "chute_stepper", None)
    if chute is None or stepper is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": None,
            "current_angle": None,
            "stepper_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "digital_inputs": [],
            "home_pin_channel": None,
        }

    interfaces = getattr(irl, "interfaces", {})
    distribution_board = interfaces.get("DISTRIBUTION MB") if isinstance(interfaces, dict) else None
    status: Dict[str, Any] = {
        "live_available": True,
        "endstop_triggered": None,
        "raw_endstop_high": None,
        "endstop_active_high": getattr(chute, "endstop_active_high", DEFAULT_ENDSTOP_ACTIVE_HIGH),
        "stepper_direction_inverted": bool(getattr(stepper, "direction_inverted", True)),
        "current_angle": None,
        "stepper_position_degrees": None,
        "stepper_microsteps": None,
        "stepper_stopped": None,
        "homed": None,
        "digital_inputs": [],
        "home_pin_channel": _pin_channel(getattr(chute, "home_pin", None)),
    }

    try:
        status["homed"] = bool(chute.homed)
    except Exception:
        pass

    try:
        status["raw_endstop_high"] = bool(chute.home_pin.value)
        if hasattr(chute, "endstop_triggered"):
            status["endstop_triggered"] = bool(chute.endstop_triggered)
        elif status["raw_endstop_high"] is not None:
            active_high = bool(status["endstop_active_high"])
            status["endstop_triggered"] = (
                bool(status["raw_endstop_high"])
                if active_high
                else not bool(status["raw_endstop_high"])
            )
    except Exception as e:
        status["endstop_error"] = str(e)

    try:
        status["current_angle"] = float(chute.current_angle)
    except Exception as e:
        status["current_angle_error"] = str(e)

    try:
        status["stepper_position_degrees"] = float(stepper.position_degrees)
        status["stepper_microsteps"] = int(stepper.position)
    except Exception as e:
        status["stepper_position_error"] = str(e)

    try:
        status["stepper_stopped"] = bool(stepper.stopped)
    except Exception as e:
        status["stepper_stopped_error"] = str(e)

    if distribution_board is not None:
        try:
            status["digital_inputs"] = [
                {
                    "channel": index,
                    "raw_high": bool(pin.value),
                }
                for index, pin in enumerate(getattr(distribution_board, "digital_inputs", []))
            ]
        except Exception as e:
            status["digital_inputs_error"] = str(e)

    return status


@router.get("/api/hardware-config/chute")
def get_chute_hardware_config() -> Dict[str, Any]:
    config = machine_toml.read()
    return _chute_settings_from_config(config)


@router.post("/api/hardware-config/chute")
def save_chute_hardware_config(
    payload: ChuteHardwareSettingsPayload,
) -> Dict[str, Any]:
    settings, applied_live = _save_and_apply_chute(payload.model_dump(exclude_none=True))
    return {
        "ok": True,
        "settings": _chute_payload(settings),
        "applied_live": applied_live,
        "message": (
            "Chute settings saved and applied live."
            if applied_live
            else "Chute settings saved. They apply when the hardware starts."
        ),
    }


@router.get("/api/hardware-config/chute/live")
def get_live_chute_status() -> Dict[str, Any]:
    return _live_chute_status()


@router.post("/api/hardware-config/chute/variant")
def save_chute_variant(payload: ChuteVariantPayload) -> Dict[str, Any]:
    """Say which kind of chute this machine has. The running hardware keeps the
    kind it started with until it is started again."""
    try:
        settings = saveChuteSettings({"variant": payload.variant}, **_board_defaults())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    chute = _live_chute()
    restart_needed = chute is not None and getattr(chute.variant, "key", None) != settings.variant.key
    return {
        "ok": True,
        "settings": _chute_payload(settings),
        "restart_needed": restart_needed,
        "message": (
            f"Saved: {settings.variant.label}. Start the hardware again to use it."
            if restart_needed
            else f"Saved: {settings.variant.label}."
        ),
    }


@router.post("/api/hardware-config/chute/discard-bin")
def save_chute_discard_bin(payload: ChuteDiscardBinPayload) -> Dict[str, Any]:
    """Choose the bin that takes the pieces no other bin wants, or none."""
    indices = (payload.layer_index, payload.section_index, payload.bin_index)
    if all(index is None for index in indices):
        discard_bin = None
    elif any(index is None for index in indices):
        raise HTTPException(status_code=400, detail="Give the layer, section and bin, or none of them.")
    else:
        discard_bin = [int(index) for index in indices]  # type: ignore[arg-type]
        layout = getBinLayout()
        layer, section, bin_index = discard_bin
        if (
            layer >= len(layout.layers)
            or section >= len(layout.layers[layer].sections)
            or bin_index >= len(layout.layers[layer].sections[section])
        ):
            raise HTTPException(status_code=400, detail="There is no such bin in this machine's layout.")
    settings, applied_live = _save_and_apply_chute({"discard_bin": discard_bin})
    return {"ok": True, "settings": _chute_payload(settings), "applied_live": applied_live}


@router.post("/api/hardware-config/chute/calibrate/measure-turn")
def calibrate_chute_measure_turn() -> Dict[str, Any]:
    """Measure how many motor turns one turn of this chute takes, on a chute
    that turns without limit: home, turn once round to the magnet again, save
    the ratio, home again."""
    chute = getattr(hardware_needs.needStarted(), "chute", None)
    if chute is None:
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")
    if not chute.variant.turns_freely:
        raise HTTPException(
            status_code=409,
            detail=f"The {chute.variant.label} cannot turn all the way round, so its turn cannot be measured.",
        )
    try:
        if not chute.homed and not chute.home():
            raise HTTPException(status_code=409, detail="The chute could not find its home, so its turn was not measured.")
        ratio = measureTurn(chute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Measuring the chute's turn failed: {exc}")
    if ratio is None:
        raise HTTPException(status_code=409, detail="The magnet did not come round. Check the sensor and that the chute turns freely.")
    settings, _ = _save_and_apply_chute({"gear_ratio": ratio})
    homed = bool(chute.home())
    return {
        "ok": True,
        "gear_ratio": round(ratio, 5),
        "homed": homed,
        "settings": _chute_payload(settings),
        "message": f"One turn of the chute is {ratio:.3f} turns of its motor. Saved.",
    }


@router.post("/api/hardware-config/chute/calibrate/find-endstop")
def calibrate_chute_find_endstop() -> Dict[str, Any]:
    chute = getattr(hardware_needs.needStarted(), "chute", None)
    if chute is None or not hasattr(chute, "home"):
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")

    try:
        homed = bool(chute.home())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find chute endstop: {e}")
    on_magnet = chute.variant.home_on == HOME_ON_MAGNET
    if not homed:
        raise HTTPException(
            status_code=409,
            detail=(
                "The chute turned a full turn and its home sensor never saw the magnet. Check that the "
                "sensor is plugged in, that the magnet is fitted, and that the chute turns."
                if on_magnet
                else "Chute homing stopped before the endstop triggered. It's possible that the switch is not making good contact with the chute. Try moving it closer to the chute."
            ),
        )

    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": (
            "The chute found its magnet and stands at home."
            if on_magnet
            else "Step 1 complete. Chute moved slowly until the endstop was found and then moved to bin 1."
        ),
    }


@router.post("/api/hardware-config/chute/calibrate/cancel")
def cancel_chute_find_endstop() -> Dict[str, Any]:
    _stop_all_steppers()
    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": "Chute homing canceled. All steppers were stopped for safety.",
    }


def _homed_chute() -> Any:
    # Mirror the chute home endpoint (find-endstop): resolve off the active
    # runtime IRL, not a fully-published SorterController. This lets the chute
    # be aimed after a no-homing /api/system/initialize (steppers up, nothing
    # homed) — homing the chute alone is enough to use it, no cameras or full
    # recover required.
    chute = getattr(hardware_needs.needStarted(), "chute", None)
    if chute is None:
        raise HTTPException(status_code=503, detail="Chute subsystem not available.")
    if not getattr(chute, "homed", False):
        raise HTTPException(status_code=409, detail="Home the chute first.")
    return chute


def _chute_move(move: Any, target: Any) -> Any:
    try:
        estimated_ms = move(target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chute move failed: {e}")
    if estimated_ms is None:
        raise HTTPException(status_code=409, detail="The chute is still moving; try again when it stops.")
    return estimated_ms


def _virtual_bin_angle(
    num_sections: int,
    bins_in_section: int,
    section_index: int,
    bin_index: int,
    section_width_deg: float,
    first_section_offset_deg: float,
) -> float:
    # Mirror of Chute.angleForVirtualBin so reachability can be reported for
    # an arbitrary (not-yet-applied) geometry. Keep in lockstep with chute.py.
    n = max(1, int(num_sections))
    k = max(1, int(bins_in_section))
    slot = section_width_deg / k
    return first_section_offset_deg + section_index * (360.0 / n) + (bin_index + 0.5) * slot


def _chute_reachability(
    num_sections: int, section_width_deg: float, first_section_offset_deg: float
) -> Dict[str, Any]:
    # For the active (or default) layout, report whether every bin's center
    # angle lands inside the chute's travel, the way Chute.angleForVirtualBin
    # judges it. A chute that turns without limit reaches them all.
    travel = readChuteSettings(**_board_defaults()).variant.travel_deg
    layout = getBinLayout()
    unreachable: List[Dict[str, Any]] = []
    total = 0
    for layer_index, layer in enumerate(layout.layers):
        for section_index, section in enumerate(layer.sections):
            bins_in_section = len(section)
            for bin_index in range(bins_in_section):
                total += 1
                angle = _virtual_bin_angle(
                    num_sections,
                    bins_in_section,
                    section_index,
                    bin_index,
                    section_width_deg,
                    first_section_offset_deg,
                )
                if travel is not None and angle % 360.0 > travel:
                    unreachable.append(
                        {
                            "layer_index": layer_index,
                            "section_index": section_index,
                            "bin_index": bin_index,
                            "angle": round(angle, 2),
                        }
                    )
    return {
        "total_bins": total,
        "all_reachable": len(unreachable) == 0,
        "unreachable": unreachable[:24],
        "unreachable_count": len(unreachable),
    }


def _calibrations_payload(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        return listChuteCalibrationInstances(limit=limit)
    except Exception:
        return []


def _record_calibration_instance(
    *,
    label: str,
    num_sections: int,
    section_width_deg: float,
    first_section_offset_deg: float,
    measurements: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        recordChuteCalibrationInstance(
            label=label,
            num_sections=num_sections,
            section_width_deg=round(section_width_deg, 4),
            first_section_offset_deg=round(first_section_offset_deg, 4),
            measurements=measurements,
        )
    except Exception:
        # History is best-effort; never block a successful TOML write on it.
        pass


def _persist_and_apply_chute_aiming(changes: Dict[str, Any]) -> tuple[Dict[str, Any], ChuteSettings]:
    settings, applied_live = _save_and_apply_chute(changes)
    result = {
        "ok": True,
        "settings": _chute_payload(settings),
        "reachability": _chute_reachability(
            settings.num_sections, settings.section_width_deg, settings.first_section_offset_deg
        ),
        "applied_live": applied_live,
    }
    return result, settings


@router.post("/api/hardware-config/chute/aiming")
def save_chute_aiming_config(payload: ChuteAimingSettingsPayload) -> Dict[str, Any]:
    result, settings = _persist_and_apply_chute_aiming(
        payload.model_dump(exclude_none=True, exclude={"label"})
    )
    _record_calibration_instance(
        label=payload.label or "Manual edit",
        num_sections=settings.num_sections,
        section_width_deg=settings.section_width_deg,
        first_section_offset_deg=settings.first_section_offset_deg,
    )
    result["calibrations"] = _calibrations_payload()
    result["message"] = (
        "Chute aiming saved and applied live."
        if result["applied_live"]
        else "Chute aiming saved."
    )
    return result


@router.post("/api/hardware-config/chute/aiming/derive")
def derive_chute_aiming_config(payload: ChuteAimingDerivePayload) -> Dict[str, Any]:
    num_sections = int(payload.num_sections)
    if num_sections < 1:
        raise HTTPException(status_code=400, detail="num_sections must be >= 1.")
    k = int(payload.bins_in_test_section)
    if k < 2:
        raise HTTPException(
            status_code=400,
            detail="bins_in_test_section must be >= 2 to measure a first→last span.",
        )
    a = float(payload.first_bin_angle)
    span = float(payload.last_bin_angle) - a
    if span <= 0:
        raise HTTPException(
            status_code=400,
            detail="last_bin_angle must be greater than first_bin_angle.",
        )
    # Bins are equal slots aimed at their midpoints, so the measured first→last
    # span covers (K-1) slots, i.e. span = (K-1)/K · W. Recover W and the
    # section start offset theta0 = first_bin_center - half a slot.
    slot = span / (k - 1)
    section_width_deg = slot * k
    first_section_offset_deg = a - 0.5 * slot
    section_pitch_deg = 360.0 / num_sections
    if section_width_deg >= section_pitch_deg:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Derived section width {section_width_deg:.2f}° exceeds the section pitch "
                f"({section_pitch_deg:.2f}°). Check the measured angles and bin count."
            ),
        )

    result, _settings = _persist_and_apply_chute_aiming({
        "num_sections": num_sections,
        "section_width_deg": section_width_deg,
        "first_section_offset_deg": first_section_offset_deg,
    })
    _record_calibration_instance(
        label=payload.label or "Calibration",
        num_sections=num_sections,
        section_width_deg=section_width_deg,
        first_section_offset_deg=first_section_offset_deg,
        measurements={
            "first_bin_angle": round(a, 4),
            "last_bin_angle": round(float(payload.last_bin_angle), 4),
            "bins_in_test_section": k,
        },
    )
    result["calibrations"] = _calibrations_payload()
    result["derived"] = {
        "num_sections": num_sections,
        "section_width_deg": round(section_width_deg, 4),
        "first_section_offset_deg": round(first_section_offset_deg, 4),
        "slot_deg": round(slot, 4),
        "pillar_width_deg": round(section_pitch_deg - section_width_deg, 4),
    }
    result["message"] = (
        "Chute aiming derived from measurements and applied live."
        if result["applied_live"]
        else "Chute aiming derived from measurements and saved."
    )
    return result


def _position_check_status() -> Dict[str, Any]:
    from subsystems.distribution import position_check

    settings = readChuteSettings(machine_toml.read(), **_board_defaults())
    chute = _live_chute()
    return {
        "enabled": settings.position_check,
        "every": settings.position_check_every,
        "pieces_since_check": getattr(chute, "pieces_since_check", None),
        "checking": bool(getattr(chute, "checking", False)),
        **position_check.summary(),
    }


@router.get("/api/hardware-config/chute/position-check")
def get_chute_position_check() -> Dict[str, Any]:
    """The chute's position check (subsystems/distribution/position_check.py):
    whether it runs, every how many pieces, how many have gone since, and what
    the checks found."""
    return _position_check_status()


@router.post("/api/hardware-config/chute/position-check/run")
def run_chute_position_check() -> Dict[str, Any]:
    """Check the chute's position now. Sorting moves the chute too, so the
    machine must be paused."""
    controller = shared_state.controller_ref
    if getattr(getattr(controller, "state", None), "value", None) == "running":
        raise HTTPException(status_code=409, detail="Pause the machine to check the chute's position.")
    chute = _homed_chute()
    if chute.checking:
        raise HTTPException(status_code=409, detail="A position check is already running.")
    check = chute.checkPosition()
    return {
        "ok": check.ok,
        "check": {**dataclasses.asdict(check), "lost_steps": check.lost_steps},
        "status": _position_check_status(),
    }


@router.post("/api/hardware-config/chute/move-to-angle")
def move_chute_to_angle(payload: ChuteMoveToAnglePayload) -> Dict[str, Any]:
    chute = _homed_chute()
    angle = float(payload.angle)
    if angle < 0 or angle > 360:
        raise HTTPException(status_code=400, detail="angle must be between 0 and 360°.")
    estimated_ms = _chute_move(chute.moveToAngle, angle)
    return {
        "ok": True,
        "target_angle": round(angle, 2),
        "estimated_ms": estimated_ms,
        "status": _live_chute_status(),
    }


@router.post("/api/hardware-config/chute/move-to-virtual-bin")
def move_chute_to_virtual_bin(payload: ChuteVirtualBinPayload) -> Dict[str, Any]:
    # "Test aim" for the calibration circle: aim at a bin in an arbitrary,
    # not-necessarily-installed layout using the canonical aiming formula.
    chute = _homed_chute()
    if payload.num_sections < 1 or payload.bins_in_section < 1:
        raise HTTPException(status_code=400, detail="num_sections and bins_in_section must be >= 1.")
    if payload.section_index < 0 or payload.section_index >= payload.num_sections:
        raise HTTPException(status_code=400, detail="section_index out of range.")
    if payload.bin_index < 0 or payload.bin_index >= payload.bins_in_section:
        raise HTTPException(status_code=400, detail="bin_index out of range.")

    target_angle = chute.angleForVirtualBin(
        payload.section_index,
        payload.bin_index,
        payload.bins_in_section,
        num_sections=payload.num_sections,
    )
    if target_angle is None:
        raise HTTPException(
            status_code=400,
            detail="That bin is unreachable with the current aiming geometry (angle out of range).",
        )
    estimated_ms = _chute_move(chute.moveToAngle, target_angle)
    return {
        "ok": True,
        "target_angle": round(target_angle, 2),
        "estimated_ms": estimated_ms,
        "section_index": payload.section_index,
        "bin_index": payload.bin_index,
        "status": _live_chute_status(),
    }


@router.get("/api/hardware-config/chute/calibrations")
def list_chute_calibrations() -> Dict[str, Any]:
    return {"ok": True, "calibrations": _calibrations_payload()}


@router.post("/api/hardware-config/chute/calibrations/{calibration_id}/activate")
def activate_chute_calibration(calibration_id: str) -> Dict[str, Any]:
    instance = activateChuteCalibrationInstance(calibration_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Calibration not found.")

    # Locking in an instance writes its geometry to the TOML and applies it live.
    result, _settings = _persist_and_apply_chute_aiming({
        "num_sections": int(instance["num_sections"]),
        "section_width_deg": float(instance["section_width_deg"]),
        "first_section_offset_deg": float(instance["first_section_offset_deg"]),
    })
    result["calibrations"] = _calibrations_payload()
    result["active"] = instance
    result["message"] = (
        "Calibration locked in and applied live."
        if result["applied_live"]
        else "Calibration locked in."
    )
    return result


@router.delete("/api/hardware-config/chute/calibrations/{calibration_id}")
def delete_chute_calibration(calibration_id: str) -> Dict[str, Any]:
    instance = getChuteCalibrationInstance(calibration_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Calibration not found.")
    if instance.get("is_active"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the active calibration. Lock in another one first.",
        )
    deleteChuteCalibrationInstance(calibration_id)
    return {"ok": True, "calibrations": _calibrations_payload()}
