"""C4 optical rotor-phase calibration endpoints."""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rt.perception.c4_wall_phase import detect_c4_wall_phase, phase_delta_deg
from rt.services.sector_carousel import run_sector_carousel_ladder_selftest
from server import shared_state

router = APIRouter()


class C4RotorPhaseDetectPayload(BaseModel):
    feed_id: str = "c4_feed"
    sector_count: int = Field(default=5, ge=1, le=16)
    downscale: float = Field(default=0.4, gt=0.05, le=1.0)
    apply_to_runtime: bool = True


class C4RotorOpticalHomePayload(C4RotorPhaseDetectPayload):
    target_wall_angle_deg: float | None = None
    tolerance_deg: float = Field(default=2.5, gt=0.1, le=20.0)
    max_iterations: int = Field(default=2, ge=0, le=5)
    min_move_deg: float = Field(default=0.25, ge=0.0, le=5.0)
    motion_sign: float = Field(default=1.0, ge=-1.0, le=1.0)
    probe_move_deg: float = Field(default=2.0, ge=0.0, le=10.0)
    motion_response_gain: float | None = Field(default=None, ge=-20.0, le=20.0)
    execute_move: bool = True
    settle_s: float = Field(default=0.20, ge=0.0, le=3.0)


class C4CarouselPhaseVerifyPayload(BaseModel):
    source: str = "operator"
    measured_offset_deg: float | None = None
    details: dict[str, Any] | None = None


class C4CarouselPhaseInvalidatePayload(BaseModel):
    reason: str = "operator_invalidated"


def _runtime_handle() -> Any:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    return handle


def _runner_for_feed(feed_id: str) -> Any:
    handle = _runtime_handle()
    accessor = getattr(handle, "runner_for_feed", None)
    runner = accessor(feed_id) if callable(accessor) else None
    if runner is None:
        for item in getattr(handle, "perception_runners", []) or []:
            pipeline = getattr(item, "_pipeline", None)
            feed = getattr(pipeline, "feed", None)
            if getattr(feed, "feed_id", None) == feed_id:
                runner = item
                break
    if runner is None:
        raise HTTPException(status_code=404, detail=f"perception runner '{feed_id}' not found")
    return runner


def _latest_frame_bgr(feed_id: str) -> Any:
    runner = _runner_for_feed(feed_id)
    pipeline = getattr(runner, "_pipeline", None)
    feed = getattr(pipeline, "feed", None)
    frame = feed.latest() if feed is not None and hasattr(feed, "latest") else None
    raw = getattr(frame, "raw", None)
    if raw is None:
        raise HTTPException(status_code=409, detail=f"no latest frame available for '{feed_id}'")
    return raw


def _target_wall_angle(payload: C4RotorOpticalHomePayload) -> float:
    if payload.target_wall_angle_deg is not None:
        return float(payload.target_wall_angle_deg)
    handle = _runtime_handle()
    c4 = getattr(handle, "c4", None)
    value = getattr(c4, "_exit_angle_deg", None)
    if isinstance(value, (int, float)):
        return float(value)
    return 270.0


def _apply_phase_to_runtime(result: Dict[str, Any]) -> bool:
    handle = _runtime_handle()
    orchestrator = getattr(handle, "orchestrator", None)
    handler = getattr(orchestrator, "_sector_carousel_handler", None)
    if handler is None:
        return False
    sector_count = result.get("sector_count")
    update_timing = getattr(handler, "update_timing", None)
    if not callable(update_timing) or not isinstance(sector_count, int) or sector_count <= 0:
        return False
    update_timing(sector_step_deg=360.0 / float(sector_count))
    verify = getattr(handler, "verify_phase", None)
    if callable(verify):
        verify(
            source="optical_wall_phase",
            measured_offset_deg=(
                float(result["sector_offset_deg"])
                if isinstance(result.get("sector_offset_deg"), (int, float))
                else None
            ),
            details=result,
        )
    return True


def _sector_handler() -> Any:
    handle = _runtime_handle()
    orchestrator = getattr(handle, "orchestrator", None)
    handler = getattr(orchestrator, "_sector_carousel_handler", None)
    if handler is None:
        raise HTTPException(
            status_code=409,
            detail="sector carousel handler is not attached",
        )
    return handler


def _detect(payload: C4RotorPhaseDetectPayload) -> Dict[str, Any]:
    image = _latest_frame_bgr(payload.feed_id)
    result = detect_c4_wall_phase(
        image,
        sector_count=payload.sector_count,
        downscale=payload.downscale,
    )
    out = result.as_dict(include_lines=True)
    out["feed_id"] = payload.feed_id
    if payload.apply_to_runtime and result.ok:
        out["applied_to_runtime"] = _apply_phase_to_runtime(out)
    else:
        out["applied_to_runtime"] = False
    return out


def _move_c4_tray_degrees(degrees: float) -> bool:
    handle = _runtime_handle()
    c4 = getattr(handle, "c4", None)
    if c4 is None:
        raise HTTPException(status_code=409, detail="C4 runtime is not available")
    move = getattr(c4, "_transport_move", None)
    if not callable(move):
        move = getattr(c4, "_carousel_move", None)
    if not callable(move):
        raise HTTPException(status_code=501, detail="C4 runtime does not expose a move command")
    try:
        return bool(move(float(degrees)))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"C4 move failed: {exc}") from exc


def _phase_error_for_detection(
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


def _estimate_motion_response_gain(
    payload: C4RotorOpticalHomePayload,
    *,
    target_wall_angle_deg: float,
    move_sign: float,
) -> tuple[float | None, dict[str, Any] | None]:
    if payload.motion_response_gain is not None:
        return float(payload.motion_response_gain), {
            "source": "payload",
            "motion_response_gain": float(payload.motion_response_gain),
        }
    if not payload.execute_move or payload.probe_move_deg <= 0.0:
        return None, None

    before = _detect(payload)
    before_error = _phase_error_for_detection(
        before,
        target_wall_angle_deg=target_wall_angle_deg,
        sector_count=payload.sector_count,
    )
    if before_error is None:
        return None, {
            "source": "probe",
            "ok": False,
            "message": "probe skipped: initial phase detection failed",
            "before": before,
        }
    probe_command = float(payload.probe_move_deg) * move_sign
    moved = _move_c4_tray_degrees(probe_command)
    if payload.settle_s > 0.0:
        time.sleep(float(payload.settle_s))
    after = _detect(payload)
    after_error = _phase_error_for_detection(
        after,
        target_wall_angle_deg=target_wall_angle_deg,
        sector_count=payload.sector_count,
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

    # Errors are target-current. If the commanded move increases the measured
    # phase, the error shrinks by that amount.
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


@router.post("/api/c4/rotor-phase/detect")
def detect_c4_rotor_phase(payload: C4RotorPhaseDetectPayload) -> Dict[str, Any]:
    """Detect current 5-wall rotor phase from the latest C4 frame."""
    return _detect(payload)


@router.post("/api/c4/rotor-phase/optical-home")
def optical_home_c4_rotor(payload: C4RotorOpticalHomePayload) -> Dict[str, Any]:
    """Closed-loop optical homing: detect wall phase, move to target, verify."""
    target = _target_wall_angle(payload)
    iterations: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    success = False
    move_sign = -1.0 if payload.motion_sign < 0.0 else 1.0
    response_gain, probe = _estimate_motion_response_gain(
        payload,
        target_wall_angle_deg=target,
        move_sign=move_sign,
    )
    response_gain_valid = response_gain is not None and 0.2 <= abs(response_gain) <= 8.0
    if response_gain is not None and not response_gain_valid:
        return {
            "ok": False,
            "execute_move": bool(payload.execute_move),
            "target_wall_angle_deg": target,
            "tolerance_deg": float(payload.tolerance_deg),
            "motion_sign": move_sign,
            "motion_response_gain": response_gain,
            "probe": probe,
            "iterations": [],
            "final_detection": probe.get("after") if isinstance(probe, dict) else None,
            "message": "motion response probe was implausible; optical homing correction skipped",
        }

    for index in range(payload.max_iterations + 1):
        detection = _detect(payload)
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
            sector_count=payload.sector_count,
        )
        aligned = abs(delta) <= float(payload.tolerance_deg)
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

        if index >= payload.max_iterations or abs(delta) < payload.min_move_deg:
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
        moved = bool(payload.execute_move and _move_c4_tray_degrees(move_deg))
        iterations.append(
            {
                "iteration": index,
                "detection": detection,
                "target_wall_angle_deg": target,
                "phase_error_deg": delta,
                "move_deg": move_deg if payload.execute_move else 0.0,
                "planned_move_deg": move_deg,
                "moved": moved,
                "message": "correction move issued" if moved else "dry run correction planned",
            }
        )
        if not payload.execute_move:
            break
        if not moved:
            break
        if payload.settle_s > 0.0:
            time.sleep(float(payload.settle_s))

    return {
        "ok": success,
        "execute_move": bool(payload.execute_move),
        "target_wall_angle_deg": target,
        "tolerance_deg": float(payload.tolerance_deg),
        "motion_sign": move_sign,
        "motion_response_gain": response_gain,
        "probe": probe,
        "iterations": iterations,
        "final_detection": final,
    }


@router.get("/api/c4/carousel/status")
def c4_carousel_status() -> Dict[str, Any]:
    handler = _sector_handler()
    status = getattr(handler, "status_snapshot", None)
    if callable(status):
        return {"ok": True, "carousel": dict(status() or {})}
    snapshot = getattr(handler, "snapshot", None)
    return {"ok": True, "carousel": dict(snapshot() or {}) if callable(snapshot) else {}}


@router.get("/api/c4/carousel/gates")
def c4_carousel_gates() -> Dict[str, Any]:
    handler = _sector_handler()
    gate_status = getattr(handler, "gate_status", None)
    if not callable(gate_status):
        raise HTTPException(
            status_code=501,
            detail="sector carousel gate status is not supported",
        )
    return {"ok": True, "gates": dict(gate_status() or {})}


@router.get("/api/c4/carousel/events")
def c4_carousel_events(limit: int = 50) -> Dict[str, Any]:
    handler = _sector_handler()
    recent = getattr(handler, "recent_events", None)
    if not callable(recent):
        raise HTTPException(
            status_code=501,
            detail="sector carousel event log is not supported",
        )
    return {"ok": True, "events": list(recent(limit=limit) or [])}


@router.post("/api/c4/carousel/selftest")
def c4_carousel_selftest() -> Dict[str, Any]:
    return {"ok": True, "selftest": run_sector_carousel_ladder_selftest()}


@router.post("/api/c4/carousel/phase/verify")
def verify_c4_carousel_phase(payload: C4CarouselPhaseVerifyPayload) -> Dict[str, Any]:
    handler = _sector_handler()
    verify = getattr(handler, "verify_phase", None)
    if not callable(verify):
        raise HTTPException(
            status_code=501,
            detail="sector carousel phase verification is not supported",
        )
    verify(
        source=payload.source,
        measured_offset_deg=payload.measured_offset_deg,
        details=payload.details,
    )
    snapshot = getattr(handler, "snapshot", None)
    return {"ok": True, "carousel": dict(snapshot() or {}) if callable(snapshot) else {}}


@router.post("/api/c4/carousel/phase/invalidate")
def invalidate_c4_carousel_phase(
    payload: C4CarouselPhaseInvalidatePayload,
) -> Dict[str, Any]:
    handler = _sector_handler()
    invalidate = getattr(handler, "invalidate_phase", None)
    if not callable(invalidate):
        raise HTTPException(
            status_code=501,
            detail="sector carousel phase invalidation is not supported",
        )
    invalidate(reason=payload.reason)
    snapshot = getattr(handler, "snapshot", None)
    return {"ok": True, "carousel": dict(snapshot() or {}) if callable(snapshot) else {}}
