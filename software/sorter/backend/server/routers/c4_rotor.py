"""C4 optical rotor-phase calibration endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rt.perception.c4_wall_phase import detect_c4_wall_phase
from rt.services.c4_optical_home import run_c4_optical_home
from rt.services.sector_carousel import run_sector_carousel_ladder_selftest
from server import shared_state

router = APIRouter()


class C4RotorPhaseDetectPayload(BaseModel):
    feed_id: str = "c4_feed"
    sector_count: int = Field(default=5, ge=1, le=16)
    downscale: float = Field(default=0.4, gt=0.05, le=1.0)
    apply_to_runtime: bool = False


class C4RotorOpticalHomePayload(C4RotorPhaseDetectPayload):
    apply_to_runtime: bool = True
    target_wall_angle_deg: float | None = None
    tolerance_deg: float = Field(default=2.5, gt=0.1, le=20.0)
    max_iterations: int = Field(default=5, ge=0, le=8)
    min_move_deg: float = Field(default=0.25, ge=0.0, le=5.0)
    max_move_deg: float | None = Field(default=12.0, gt=0.0, le=36.0)
    motion_sign: float = Field(default=1.0, ge=-1.0, le=1.0)
    probe_move_deg: float = Field(default=0.0, ge=0.0, le=10.0)
    motion_response_gain: float | None = Field(default=1.0, ge=-20.0, le=20.0)
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


def _detect_without_runtime_apply(payload: C4RotorPhaseDetectPayload) -> Dict[str, Any]:
    return _detect(
        C4RotorPhaseDetectPayload(
            feed_id=payload.feed_id,
            sector_count=payload.sector_count,
            downscale=payload.downscale,
            apply_to_runtime=False,
        )
    )


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


@router.post("/api/c4/rotor-phase/detect")
def detect_c4_rotor_phase(payload: C4RotorPhaseDetectPayload) -> Dict[str, Any]:
    """Detect current 5-wall rotor phase from the latest C4 frame."""
    return _detect(payload)


@router.post("/api/c4/rotor-phase/optical-home")
def optical_home_c4_rotor(payload: C4RotorOpticalHomePayload) -> Dict[str, Any]:
    """Closed-loop optical homing: detect wall phase, move to target, verify."""
    target = _target_wall_angle(payload)
    return run_c4_optical_home(
        detect_phase=lambda: _detect_without_runtime_apply(payload),
        move_tray_degrees=_move_c4_tray_degrees,
        apply_phase=_apply_phase_to_runtime,
        target_wall_angle_deg=target,
        sector_count=payload.sector_count,
        tolerance_deg=payload.tolerance_deg,
        max_iterations=payload.max_iterations,
        min_move_deg=payload.min_move_deg,
        max_move_deg=payload.max_move_deg,
        motion_sign=payload.motion_sign,
        probe_move_deg=payload.probe_move_deg,
        motion_response_gain=payload.motion_response_gain,
        execute_move=payload.execute_move,
        settle_s=payload.settle_s,
        apply_to_runtime=payload.apply_to_runtime,
    )


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
