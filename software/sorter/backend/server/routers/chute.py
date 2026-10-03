"""The chute: its settings, homing, aiming calibration and test moves."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import machine_toml
from irl.bin_layout import getBinLayout
from irl.parse_user_toml import (
    DEFAULT_CHUTE_FIRST_BIN_CENTER,
    DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH,
    DEFAULT_CHUTE_FIRST_SECTION_OFFSET_DEG,
    DEFAULT_CHUTE_HOME_PIN_CHANNEL,
    DEFAULT_CHUTE_NUM_SECTIONS,
    DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    DEFAULT_CHUTE_SECTION_WIDTH_DEG,
)
from chute_calibrations import (
    activateChuteCalibrationInstance,
    deleteChuteCalibrationInstance,
    getChuteCalibrationInstance,
    listChuteCalibrationInstances,
    recordChuteCalibrationInstance,
)
from server import shared_state
from server.routers.steppers import _ensure_not_homing, _stop_all_steppers
from subsystems.distribution.chute import CHUTE_MAX_ANGLE

router = APIRouter()


class ChuteHardwareSettingsPayload(BaseModel):
    first_bin_center: float = DEFAULT_CHUTE_FIRST_BIN_CENTER
    pillar_width_deg: float = DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    endstop_active_high: bool = DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH
    operating_speed_microsteps_per_second: int = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC


class ChuteAimingSettingsPayload(BaseModel):
    num_sections: int = DEFAULT_CHUTE_NUM_SECTIONS
    section_width_deg: float = DEFAULT_CHUTE_SECTION_WIDTH_DEG
    first_section_offset_deg: float = DEFAULT_CHUTE_FIRST_SECTION_OFFSET_DEG
    endstop_active_high: Optional[bool] = None
    operating_speed_microsteps_per_second: Optional[int] = None
    label: Optional[str] = None


class ChuteAimingDerivePayload(BaseModel):
    # Measurements from the calibration routine: the chute is jogged to the
    # first and last bin of a test section with a known bin count.
    first_bin_angle: float
    last_bin_angle: float
    bins_in_test_section: int
    num_sections: int = DEFAULT_CHUTE_NUM_SECTIONS
    label: Optional[str] = None


class ChuteMoveToAnglePayload(BaseModel):
    angle: float


class ChuteVirtualBinPayload(BaseModel):
    num_sections: int
    bins_in_section: int
    section_index: int
    bin_index: int


def _coerce_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _pin_channel(pin: Any | None) -> int | None:
    channel = getattr(pin, "channel", None)
    if isinstance(channel, int) and not isinstance(channel, bool):
        return channel

    channel = getattr(pin, "_channel", None)
    if isinstance(channel, int) and not isinstance(channel, bool):
        return channel

    return None


def _chute_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    chute = config.get("chute", {})
    if not isinstance(chute, dict):
        chute = {}

    first_bin_center = _coerce_float(
        chute.get("first_bin_center"),
        DEFAULT_CHUTE_FIRST_BIN_CENTER,
    )
    pillar_width_deg = _coerce_float(
        chute.get("pillar_width_deg"),
        DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    )
    irl = shared_state.getActiveIRL()
    live_chute = getattr(irl, "chute", None) if irl is not None else None
    # Unsaved, the polarity is the board's default, which only the live chute knows.
    endstop_active_high = chute.get("endstop_active_high")
    if not isinstance(endstop_active_high, bool):
        live_active_high = getattr(live_chute, "endstop_active_high", None)
        endstop_active_high = (
            live_active_high if isinstance(live_active_high, bool) else DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH
        )
    operating_speed_microsteps_per_second = chute.get(
        "operating_speed_microsteps_per_second",
        DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    )
    if not isinstance(operating_speed_microsteps_per_second, int) or isinstance(
        operating_speed_microsteps_per_second, bool
    ):
        operating_speed_microsteps_per_second = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC
    if operating_speed_microsteps_per_second <= 0:
        operating_speed_microsteps_per_second = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC

    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG

    num_sections = _coerce_int(chute.get("num_sections"), DEFAULT_CHUTE_NUM_SECTIONS)
    if num_sections < 1:
        num_sections = DEFAULT_CHUTE_NUM_SECTIONS
    section_pitch_deg = 360.0 / num_sections

    # Canonical aiming params win; otherwise derive from the legacy geometry so
    # the old machine.toml and the legacy page still read sensibly.
    if "section_width_deg" in chute:
        section_width_deg = _coerce_float(
            chute.get("section_width_deg"), section_pitch_deg - pillar_width_deg
        )
    else:
        section_width_deg = section_pitch_deg - pillar_width_deg
    if section_width_deg <= 0 or section_width_deg >= section_pitch_deg:
        section_width_deg = min(DEFAULT_CHUTE_SECTION_WIDTH_DEG, section_pitch_deg - 0.01)

    if "first_section_offset_deg" in chute:
        first_section_offset_deg = _coerce_float(
            chute.get("first_section_offset_deg"), first_bin_center
        )
    else:
        first_section_offset_deg = first_bin_center

    home_pin_channel = _coerce_int(
        chute.get("home_pin_channel"), DEFAULT_CHUTE_HOME_PIN_CHANNEL
    )
    live_home_pin_channel = _pin_channel(getattr(live_chute, "home_pin", None))
    if live_home_pin_channel is not None:
        home_pin_channel = live_home_pin_channel

    return {
        "num_sections": num_sections,
        "section_width_deg": round(section_width_deg, 4),
        "first_section_offset_deg": round(first_section_offset_deg, 4),
        "section_pitch_deg": round(section_pitch_deg, 4),
        "pillar_width_deg": round(section_pitch_deg - section_width_deg, 4),
        "first_bin_center": first_bin_center,
        "endstop_active_high": endstop_active_high,
        "operating_speed_microsteps_per_second": operating_speed_microsteps_per_second,
        "home_pin_channel": home_pin_channel,
        "max_angle_deg": CHUTE_MAX_ANGLE,
    }


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
        "endstop_active_high": getattr(chute, "endstop_active_high", DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH),
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
    first_bin_center = float(payload.first_bin_center)
    pillar_width_deg = float(payload.pillar_width_deg)
    endstop_active_high = bool(payload.endstop_active_high)
    operating_speed_microsteps_per_second = int(payload.operating_speed_microsteps_per_second)
    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        raise HTTPException(
            status_code=400,
            detail="pillar_width_deg must be between 0 and less than 60 degrees",
        )
    if operating_speed_microsteps_per_second <= 0:
        raise HTTPException(
            status_code=400,
            detail="operating_speed_microsteps_per_second must be greater than 0",
        )

    with machine_toml.edit() as config:
        chute_config = config.get("chute", {})
        if not isinstance(chute_config, dict):
            chute_config = {}
        # Keep the canonical aiming keys in sync with this legacy save so the
        # newer chute-aiming page and this one never disagree about geometry.
        num_sections = _coerce_int(chute_config.get("num_sections"), DEFAULT_CHUTE_NUM_SECTIONS)
        if num_sections < 1:
            num_sections = DEFAULT_CHUTE_NUM_SECTIONS
        section_pitch_deg = 360.0 / num_sections
        config["chute"] = {
            **chute_config,
            "first_bin_center": first_bin_center,
            "pillar_width_deg": pillar_width_deg,
            "num_sections": num_sections,
            "section_width_deg": round(section_pitch_deg - pillar_width_deg, 4),
            "first_section_offset_deg": first_bin_center,
            "endstop_active_high": endstop_active_high,
            "operating_speed_microsteps_per_second": operating_speed_microsteps_per_second,
        }

    applied_live = False
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        chute = getattr(shared_state.controller_ref.irl, "chute", None)
        if chute is not None and hasattr(chute, "setCalibration"):
            try:
                chute.setCalibration(first_bin_center, pillar_width_deg, endstop_active_high)
                if hasattr(chute, "setOperatingSpeed"):
                    chute.setOperatingSpeed(operating_speed_microsteps_per_second)
                stepper = getattr(shared_state.controller_ref.irl, "chute_stepper", None)
                if stepper is not None:
                    stepper.set_speed_limits(16, operating_speed_microsteps_per_second)
                applied_live = True
            except Exception:
                applied_live = False

    return {
        "ok": True,
        "settings": _chute_settings_from_config(config),
        "applied_live": applied_live,
        "message": (
            "Chute settings saved and applied live."
            if applied_live
            else "Chute settings saved."
        ),
    }


@router.get("/api/hardware-config/chute/live")
def get_live_chute_status() -> Dict[str, Any]:
    return _live_chute_status()


@router.post("/api/hardware-config/chute/calibrate/find-endstop")
def calibrate_chute_find_endstop() -> Dict[str, Any]:
    _ensure_not_homing("home the chute")
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Open the Motion or Endstops step to power on the steppers first.")

    chute = getattr(irl, "chute", None)
    if chute is None or not hasattr(chute, "home"):
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")

    try:
        homed = bool(chute.home())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find chute endstop: {e}")
    if not homed:
        raise HTTPException(
            status_code=409,
            detail="Chute homing stopped before the endstop triggered. It's possible that the switch is not making good contact with the chute. Try moving it closer to the chute.",
        )

    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": "Step 1 complete. Chute moved slowly until the endstop was found and then moved to bin 1.",
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
    _ensure_not_homing("move the chute")
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Initialize or home the system first.")
    chute = getattr(irl, "chute", None)
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
    # angle lands inside the chute's reachable arc [0, CHUTE_MAX_ANGLE].
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
                if angle < 0 or angle > CHUTE_MAX_ANGLE:
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


def _persist_and_apply_chute_aiming(
    num_sections: int,
    section_width_deg: float,
    first_section_offset_deg: float,
    endstop_active_high: Optional[bool] = None,
    operating_speed_microsteps_per_second: Optional[int] = None,
) -> Dict[str, Any]:
    section_pitch_deg = 360.0 / num_sections
    with machine_toml.edit() as config:
        chute_config = config.get("chute", {})
        if not isinstance(chute_config, dict):
            chute_config = {}
        new_chute: Dict[str, Any] = {
            **chute_config,
            "num_sections": num_sections,
            "section_width_deg": round(section_width_deg, 4),
            "first_section_offset_deg": round(first_section_offset_deg, 4),
            # Keep legacy keys in sync for the old page / older readers.
            "pillar_width_deg": round(section_pitch_deg - section_width_deg, 4),
            "first_bin_center": round(first_section_offset_deg, 4),
        }
        if endstop_active_high is not None:
            new_chute["endstop_active_high"] = bool(endstop_active_high)
        if operating_speed_microsteps_per_second is not None:
            new_chute["operating_speed_microsteps_per_second"] = int(operating_speed_microsteps_per_second)
        config["chute"] = new_chute

    applied_live = False
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        chute = getattr(shared_state.controller_ref.irl, "chute", None)
        if chute is not None and hasattr(chute, "setAimingCalibration"):
            try:
                chute.setAimingCalibration(
                    num_sections,
                    section_width_deg,
                    first_section_offset_deg,
                    endstop_active_high,
                )
                if operating_speed_microsteps_per_second is not None and hasattr(chute, "setOperatingSpeed"):
                    chute.setOperatingSpeed(operating_speed_microsteps_per_second)
                    stepper = getattr(shared_state.controller_ref.irl, "chute_stepper", None)
                    if stepper is not None:
                        stepper.set_speed_limits(16, int(operating_speed_microsteps_per_second))
                applied_live = True
            except Exception:
                applied_live = False

    return {
        "ok": True,
        "settings": _chute_settings_from_config(config),
        "reachability": _chute_reachability(num_sections, section_width_deg, first_section_offset_deg),
        "applied_live": applied_live,
    }


@router.post("/api/hardware-config/chute/aiming")
def save_chute_aiming_config(payload: ChuteAimingSettingsPayload) -> Dict[str, Any]:
    num_sections = int(payload.num_sections)
    if num_sections < 1:
        raise HTTPException(status_code=400, detail="num_sections must be >= 1.")
    section_pitch_deg = 360.0 / num_sections
    section_width_deg = float(payload.section_width_deg)
    if section_width_deg <= 0 or section_width_deg >= section_pitch_deg:
        raise HTTPException(
            status_code=400,
            detail=f"section_width_deg must be between 0 and the section pitch ({section_pitch_deg:.2f}°).",
        )
    if (
        payload.operating_speed_microsteps_per_second is not None
        and payload.operating_speed_microsteps_per_second <= 0
    ):
        raise HTTPException(
            status_code=400,
            detail="operating_speed_microsteps_per_second must be greater than 0.",
        )

    result = _persist_and_apply_chute_aiming(
        num_sections,
        section_width_deg,
        float(payload.first_section_offset_deg),
        payload.endstop_active_high,
        payload.operating_speed_microsteps_per_second,
    )
    _record_calibration_instance(
        label=payload.label or "Manual edit",
        num_sections=num_sections,
        section_width_deg=section_width_deg,
        first_section_offset_deg=float(payload.first_section_offset_deg),
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

    result = _persist_and_apply_chute_aiming(
        num_sections, section_width_deg, first_section_offset_deg
    )
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
    result = _persist_and_apply_chute_aiming(
        int(instance["num_sections"]),
        float(instance["section_width_deg"]),
        float(instance["first_section_offset_deg"]),
    )
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
