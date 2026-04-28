from __future__ import annotations

import math
import time
from typing import Any, Callable

from rt.perception.c4_wall_phase import phase_delta_deg


DetectPhaseFn = Callable[[], dict[str, Any]]
MoveTrayDegreesFn = Callable[[float], bool]
ApplyPhaseFn = Callable[[dict[str, Any]], bool]


def phase_error_for_detection(
    detection: dict[str, Any],
    *,
    target_wall_angle_deg: float,
    sector_count: int,
) -> float | None:
    offset = detection.get("sector_offset_deg")
    if not detection.get("ok") or not isinstance(offset, (int, float)):
        return None
    return phase_delta_deg(
        current_offset_deg=float(offset),
        target_wall_angle_deg=float(target_wall_angle_deg),
        sector_count=int(sector_count),
    )


def run_c4_optical_home(
    *,
    detect_phase: DetectPhaseFn,
    move_tray_degrees: MoveTrayDegreesFn,
    target_wall_angle_deg: float,
    sector_count: int = 5,
    tolerance_deg: float = 2.5,
    max_iterations: int = 2,
    min_move_deg: float = 0.25,
    max_move_deg: float | None = 12.0,
    motion_sign: float = 1.0,
    probe_move_deg: float = 0.0,
    motion_response_gain: float | None = 1.0,
    execute_move: bool = True,
    settle_s: float = 0.20,
    apply_to_runtime: bool = True,
    apply_phase: ApplyPhaseFn | None = None,
) -> dict[str, Any]:
    """Closed-loop C4 optical home loop with injected I/O.

    The function is intentionally free of FastAPI/shared_state dependencies so
    the system home path and the debug endpoint cannot drift apart.
    """

    target = float(target_wall_angle_deg)
    sector_count = int(sector_count)
    tolerance = float(tolerance_deg)
    iterations: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    success = False
    move_sign = -1.0 if float(motion_sign) < 0.0 else 1.0

    initial = dict(detect_phase() or {})
    final = initial
    initial_error = phase_error_for_detection(
        initial,
        target_wall_angle_deg=target,
        sector_count=sector_count,
    )
    if initial_error is None:
        iterations.append(
            {
                "iteration": 0,
                "detection": initial,
                "move_deg": 0.0,
                "message": "phase detection failed",
            }
        )
        return {
            "ok": False,
            "execute_move": bool(execute_move),
            "applied_to_runtime": False,
            "target_wall_angle_deg": target,
            "tolerance_deg": tolerance,
            "motion_sign": move_sign,
            "motion_response_gain": None,
            "probe": None,
            "iterations": iterations,
            "final_detection": final,
        }
    if abs(initial_error) <= tolerance:
        success = True
        iterations.append(
            {
                "iteration": 0,
                "detection": initial,
                "target_wall_angle_deg": target,
                "phase_error_deg": initial_error,
                "move_deg": 0.0,
                "message": "target phase reached",
            }
        )
        applied_to_runtime = False
        if apply_to_runtime and apply_phase is not None:
            applied_to_runtime = bool(apply_phase(final))
            final["applied_to_runtime"] = applied_to_runtime
        return {
            "ok": success,
            "execute_move": bool(execute_move),
            "applied_to_runtime": bool(applied_to_runtime),
            "target_wall_angle_deg": target,
            "tolerance_deg": tolerance,
            "motion_sign": move_sign,
            "motion_response_gain": None,
            "probe": None,
            "iterations": iterations,
            "final_detection": final,
        }

    response_gain, probe = _estimate_motion_response_gain(
        detect_phase,
        move_tray_degrees,
        target_wall_angle_deg=target,
        sector_count=sector_count,
        move_sign=move_sign,
        provided_gain=motion_response_gain,
        execute_move=bool(execute_move),
        probe_move_deg=float(probe_move_deg),
        settle_s=float(settle_s),
        before_detection=initial,
    )
    response_gain_valid = response_gain is not None and 0.2 <= abs(response_gain) <= 8.0
    if response_gain is not None and not response_gain_valid:
        return {
            "ok": False,
            "execute_move": bool(execute_move),
            "applied_to_runtime": False,
            "target_wall_angle_deg": target,
            "tolerance_deg": tolerance,
            "motion_sign": move_sign,
            "motion_response_gain": response_gain,
            "probe": probe,
            "iterations": [],
            "final_detection": probe.get("after") if isinstance(probe, dict) else None,
            "message": "motion response probe was implausible; optical homing correction skipped",
        }

    for index in range(max(0, int(max_iterations)) + 1):
        detection = dict(detect_phase() or {})
        final = detection
        offset = detection.get("sector_offset_deg")
        if not detection.get("ok") or not isinstance(offset, (int, float)):
            iterations.append(
                {
                    "iteration": index,
                    "detection": detection,
                    "move_deg": 0.0,
                    "message": "phase detection failed",
                }
            )
            break

        delta = phase_delta_deg(
            current_offset_deg=float(offset),
            target_wall_angle_deg=target,
            sector_count=sector_count,
        )
        aligned = abs(delta) <= tolerance
        if aligned:
            success = True
            iterations.append(
                {
                    "iteration": index,
                    "detection": detection,
                    "target_wall_angle_deg": target,
                    "phase_error_deg": delta,
                    "move_deg": 0.0,
                    "message": "target phase reached",
                }
            )
            break

        if index >= max(0, int(max_iterations)) or abs(delta) < float(min_move_deg):
            iterations.append(
                {
                    "iteration": index,
                    "detection": detection,
                    "target_wall_angle_deg": target,
                    "phase_error_deg": delta,
                    "move_deg": 0.0,
                    "message": "no further correction attempted",
                }
            )
            break

        move_deg = delta * move_sign
        if response_gain is not None:
            move_deg = delta / response_gain
        unclamped_move_deg = float(move_deg)
        if max_move_deg is not None and float(max_move_deg) > 0.0:
            limit = abs(float(max_move_deg))
            if abs(move_deg) > limit:
                move_deg = limit if move_deg > 0.0 else -limit
        moved = bool(execute_move and move_tray_degrees(float(move_deg)))
        iterations.append(
            {
                "iteration": index,
                "detection": detection,
                "target_wall_angle_deg": target,
                "phase_error_deg": delta,
                "move_deg": move_deg if execute_move else 0.0,
                "planned_move_deg": move_deg,
                "unclamped_move_deg": unclamped_move_deg,
                "move_clamped": abs(unclamped_move_deg - float(move_deg)) > 1e-6,
                "moved": moved,
                "message": "correction move issued" if moved else "dry run correction planned",
            }
        )
        if not execute_move or not moved:
            break
        if settle_s > 0.0:
            time.sleep(float(settle_s))

    applied_to_runtime = False
    if success and apply_to_runtime and final is not None and apply_phase is not None:
        applied_to_runtime = bool(apply_phase(final))
        final["applied_to_runtime"] = applied_to_runtime

    return {
        "ok": success,
        "execute_move": bool(execute_move),
        "applied_to_runtime": bool(applied_to_runtime),
        "target_wall_angle_deg": target,
        "tolerance_deg": tolerance,
        "motion_sign": move_sign,
        "motion_response_gain": response_gain,
        "probe": probe,
        "iterations": iterations,
        "final_detection": final,
    }


def _estimate_motion_response_gain(
    detect_phase: DetectPhaseFn,
    move_tray_degrees: MoveTrayDegreesFn,
    *,
    target_wall_angle_deg: float,
    sector_count: int,
    move_sign: float,
    provided_gain: float | None,
    execute_move: bool,
    probe_move_deg: float,
    settle_s: float,
    before_detection: dict[str, Any] | None = None,
) -> tuple[float | None, dict[str, Any] | None]:
    if provided_gain is not None:
        return float(provided_gain), {
            "source": "payload",
            "motion_response_gain": float(provided_gain),
        }
    if not execute_move or probe_move_deg <= 0.0:
        return None, None

    before = dict(before_detection or detect_phase() or {})
    before_error = phase_error_for_detection(
        before,
        target_wall_angle_deg=target_wall_angle_deg,
        sector_count=sector_count,
    )
    if before_error is None:
        return None, {
            "source": "probe",
            "ok": False,
            "message": "probe skipped: initial phase detection failed",
            "before": before,
        }

    probe_command = float(probe_move_deg) * move_sign
    moved = bool(move_tray_degrees(probe_command))
    if settle_s > 0.0:
        time.sleep(float(settle_s))
    after = dict(detect_phase() or {})
    after_error = phase_error_for_detection(
        after,
        target_wall_angle_deg=target_wall_angle_deg,
        sector_count=sector_count,
    )
    if not moved or after_error is None:
        return None, {
            "source": "probe",
            "ok": False,
            "message": "probe failed",
            "probe_command_deg": probe_command,
            "moved": moved,
            "before": before,
            "after": after,
        }

    observed_phase_delta = before_error - after_error
    if abs(probe_command) < 1e-6 or abs(observed_phase_delta) < 1e-6:
        return None, {
            "source": "probe",
            "ok": False,
            "message": "probe produced no measurable phase change",
            "probe_command_deg": probe_command,
            "observed_phase_delta_deg": observed_phase_delta,
            "before": before,
            "after": after,
        }
    gain = float(observed_phase_delta / probe_command)
    if not math.isfinite(gain):
        return None, {
            "source": "probe",
            "ok": False,
            "message": "probe produced non-finite gain",
            "probe_command_deg": probe_command,
            "observed_phase_delta_deg": observed_phase_delta,
            "before": before,
            "after": after,
        }
    return gain, {
        "source": "probe",
        "ok": True,
        "probe_command_deg": probe_command,
        "observed_phase_delta_deg": observed_phase_delta,
        "motion_response_gain": gain,
        "before_error_deg": before_error,
        "after_error_deg": after_error,
        "before": before,
        "after": after,
    }


__all__ = [
    "phase_error_for_detection",
    "run_c4_optical_home",
]
