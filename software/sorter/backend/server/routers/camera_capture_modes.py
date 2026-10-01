"""Router for the mode a camera role's USB camera captures in: resolution,
frame rate and pixel format."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import machine_toml
from irl.config import cameraSettingsForRole
from server import shared_state
from server.routers.cameras import _camera_source_for_role, _require_camera_role, _settings_role
from vision.camera_modes import capture_modes_for_source

router = APIRouter()


class CaptureModePayload(BaseModel):
    width: int
    height: int
    fps: int | None = None
    fourcc: str | None = None


@router.get("/api/cameras/capture-modes/{role}")
def get_camera_capture_modes(role: str) -> Dict[str, Any]:
    config = machine_toml.read()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "supported": False,
            "modes": [],
            "current": None,
            "message": "No camera is assigned to this role.",
        }

    if isinstance(source, str):
        return {
            "ok": True,
            "role": role,
            "source": source,
            "supported": False,
            "modes": [],
            "current": None,
            "message": "Resolution selection is not available for network-stream cameras.",
        }

    modes, backend = capture_modes_for_source(source)
    svc = shared_state.camera_service
    current: Dict[str, Any] | None = None
    if svc is not None and hasattr(svc, "get_capture_mode_for_role"):
        current = svc.get_capture_mode_for_role(role)
    if current is None:
        saved_section = config.get("camera_capture_modes", {}) if isinstance(config.get("camera_capture_modes"), dict) else {}
        saved_entry = cameraSettingsForRole(saved_section, role)
        if isinstance(saved_entry, dict):
            current = {
                "width": int(saved_entry.get("width", 0)) or None,
                "height": int(saved_entry.get("height", 0)) or None,
                "fps": int(saved_entry.get("fps", 0)) or None,
                "fourcc": saved_entry.get("fourcc") if isinstance(saved_entry.get("fourcc"), str) else None,
            }

    # Enrich current with actual live resolution from telemetry
    live: Dict[str, Any] | None = None
    if svc is not None:
        device = svc.get_device(role) if hasattr(svc, "get_device") else None
        if device is not None:
            try:
                telemetry = device.capture_thread.getTelemetrySnapshot()
                res = telemetry.get("resolution")
                if isinstance(res, tuple) and len(res) == 2:
                    live = {
                        "width": int(res[0]),
                        "height": int(res[1]),
                        "fps": int(round(float(telemetry.get("fps", 0)))) or None,
                    }
            except Exception:
                pass

    return {
        "ok": True,
        "role": role,
        "source": source,
        "supported": bool(modes),
        "backend": backend,
        "modes": modes,
        "current": current,
        "live": live,
    }


@router.post("/api/cameras/capture-modes/{role}")
def save_camera_capture_mode(role: str, payload: CaptureModePayload) -> Dict[str, Any]:
    _require_camera_role(role)
    if payload.width <= 0 or payload.height <= 0:
        raise HTTPException(status_code=400, detail="Width and height must be positive.")

    with machine_toml.edit() as config:
        source = _camera_source_for_role(config, role)
        if not isinstance(source, int):
            raise HTTPException(status_code=400, detail="Resolution selection requires a USB camera.")

        modes, _ = capture_modes_for_source(source)
        wanted_fourcc = (payload.fourcc or "MJPG").strip().upper()[:4]
        same_size = [m for m in modes if m["width"] == payload.width and m["height"] == payload.height]
        # Never fall into YUYV by accident: it fills the USB bus on its own.
        mode_match = next(
            (m for m in same_size if str(m.get("fourcc", "")).upper() == wanted_fourcc),
            same_size[0] if same_size else None,
        )
        if mode_match is None:
            raise HTTPException(
                status_code=400,
                detail=f"Resolution {payload.width}x{payload.height} is not supported by this camera.",
            )

        fps = int(payload.fps) if payload.fps else int(mode_match["fps"])
        raw_fourcc = payload.fourcc if payload.fourcc is not None else mode_match.get("fourcc")
        fourcc = raw_fourcc.strip().upper()[:4] if isinstance(raw_fourcc, str) and raw_fourcc.strip() else None

        entry: Dict[str, Any] = {"width": int(payload.width), "height": int(payload.height), "fps": fps}
        if fourcc:
            entry["fourcc"] = fourcc
        capture_modes = config.get("camera_capture_modes", {})
        if not isinstance(capture_modes, dict):
            capture_modes = {}
        capture_modes[_settings_role(role)] = entry
        config["camera_capture_modes"] = capture_modes

    svc = shared_state.camera_service
    applied_live = False
    if svc is not None and hasattr(svc, "set_capture_mode_for_role"):
        try:
            applied_live = svc.set_capture_mode_for_role(
                role, width=entry["width"], height=entry["height"], fps=fps, fourcc=fourcc
            )
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "source": source,
        "mode": entry,
        "persisted": True,
        "applied_live": applied_live,
        "message": "Capture mode saved. Camera will reopen at the new resolution.",
    }
