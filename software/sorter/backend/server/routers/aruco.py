"""Router for ArUco tag configuration endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from server import shared_state
from server.shared_state import auto_calibrate

router = APIRouter()


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------


@router.get("/aruco", response_class=HTMLResponse)
def get_aruco_config_page() -> str:
    """Serve the ArUco tag configuration page"""
    template_path = Path(__file__).parent.parent / "templates" / "aruco_config.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    return template_path.read_text()


@router.get("/feeder-calibration", response_class=HTMLResponse)
def get_feeder_calibration_page() -> str:
    """Serve the feeder calibration page."""
    return get_aruco_config_page()


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/api/aruco/config")
def get_aruco_config() -> Dict[str, Any]:
    """Get full ArUco configuration"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return shared_state.aruco_manager.get_config_dict()


@router.get("/api/aruco/categories")
def get_aruco_categories() -> Dict[str, Any]:
    """Get all categories with their tag assignments"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    config = shared_state.aruco_manager.get_config_dict()
    return config["categories"]


@router.get("/api/aruco/tags/unassigned")
def get_unassigned_tags() -> List[int]:
    """Get list of unassigned tag IDs"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return shared_state.aruco_manager.get_unassigned_tags()


@router.get("/api/aruco/tags/all")
def get_all_tags() -> List[int]:
    """Get all known tag IDs"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return shared_state.aruco_manager.get_all_tags()


@router.post("/api/aruco/assign")
def assign_tag(tag_id: int, category: str, role: str) -> Dict[str, Any]:
    """Assign a tag to a specific category and role"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    assigned = shared_state.aruco_manager.assign_tag(tag_id, category, role)
    if not assigned:
        raise HTTPException(status_code=400, detail="Invalid category or role for assignment")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"Tag {tag_id} assigned to {category}/{role}",
        "calibration": calibration,
    }


@router.post("/api/aruco/unassign")
def unassign_tag(tag_id: int) -> Dict[str, Any]:
    """Unassign a tag and move it back to unassigned"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    unassigned = shared_state.aruco_manager.unassign_tag(tag_id)
    if not unassigned:
        raise HTTPException(status_code=400, detail="Unable to unassign tag")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"Tag {tag_id} moved to unassigned",
        "calibration": calibration,
    }


@router.post("/api/aruco/radius-multiplier")
def set_radius_multiplier(category: str, value: float) -> Dict[str, Any]:
    """Set per-channel radius multiplier for feeder calibration."""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    updated = shared_state.aruco_manager.set_radius_multiplier(category, value)
    if not updated:
        raise HTTPException(status_code=400, detail="Invalid category or multiplier value")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"Radius multiplier for {category} set to {value}",
        "calibration": calibration,
    }


@router.get("/api/aruco/smoothing-time")
def get_aruco_smoothing_time() -> Dict[str, Any]:
    """Get ArUco smoothing time in seconds."""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return {"aruco_smoothing_time_s": shared_state.aruco_manager.get_aruco_smoothing_time_s()}


@router.post("/api/aruco/smoothing-time")
def set_aruco_smoothing_time(value: float) -> Dict[str, Any]:
    """Set ArUco smoothing time in seconds (0 disables smoothing)."""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    updated = shared_state.aruco_manager.set_aruco_smoothing_time_s(value)
    if not updated:
        raise HTTPException(status_code=400, detail="Invalid smoothing time")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"ArUco smoothing time set to {value} seconds",
        "calibration": calibration,
    }


@router.get("/api/aruco/category/{name}")
def get_category(name: str) -> Dict[str, Any]:
    """Get specific category details"""
    if shared_state.aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    try:
        return shared_state.aruco_manager.get_category(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/aruco/recalibrate")
def recalibrate_aruco() -> Dict[str, Any]:
    """Manually force runtime ArUco sync + geometry recalculation."""
    calibration = auto_calibrate()
    if not calibration.get("ok"):
        raise HTTPException(status_code=500, detail=calibration)
    return calibration
