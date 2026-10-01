"""Router for which camera films which role: the saved assignment, the USB
cameras this machine can see to choose from, and assigning them.

The other camera routers (camera_feeds, camera_picture_settings,
camera_device_settings and camera_capture_modes) share the role helpers here.
"""

from __future__ import annotations

import platform
from typing import Any, Dict, List, Optional

import cv2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

import machine_toml
from hardware.macos_camera_registry import refresh_macos_cameras
from irl.config import cameraSourceForRole
from server import shared_state
from vision.camera_modes import default_capture_mode, list_v4l2_modes

router = APIRouter()


# ---------------------------------------------------------------------------
# Camera roles
# ---------------------------------------------------------------------------

CAMERA_SETUP_ROLES = {
    "c_channel_2",
    "c_channel_3",
    "classification_channel",
    "carousel",
}


def _require_camera_role(role: str) -> None:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")


def _camera_source_for_role(config: Dict[str, Any], role: str) -> int | str | None:
    _require_camera_role(role)
    return cameraSourceForRole(config.get("cameras"), role)


def _settings_role(role: str) -> str:
    """The key a role's settings are saved under. C4's camera answers to both
    "carousel" and "classification_channel"; its settings are saved under the
    second."""
    return "classification_channel" if role == "carousel" else role


# ---------------------------------------------------------------------------
# USB cameras
# ---------------------------------------------------------------------------


def _open_camera_for_probe(index: int) -> cv2.VideoCapture:
    # On Linux a UVC camera defaults to uncompressed YUYV, which is ~10x the
    # bus bandwidth of MJPEG. With several cameras on one shared USB 2.0 bus
    # that saturates the bus, so probing one camera makes concurrent probes of
    # the others fail their first read ("No preview"). Negotiate MJPEG here.
    if platform.system() == "Darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    try:
        from vision.camera import _open_capture_source

        return _open_capture_source(index, fourcc="MJPG")
    except Exception:
        return cv2.VideoCapture(index)


def _v4l2_camera_name(index: int) -> str:
    try:
        with open(f"/sys/class/video4linux/video{index}/name") as f:
            return f.read().strip()
    except OSError:
        return f"USB Camera {index}"


def _probe_camera_index(index: int) -> Optional[Dict[str, Any]]:
    cap = _open_camera_for_probe(index)
    if not cap.isOpened():
        cap.release()
        return None

    try:
        ret, frame = cap.read()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if ret and frame is not None:
            height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            return None
        return {
            "kind": "usb",
            "index": index,
            "name": _v4l2_camera_name(index),
            "width": width,
            "height": height,
            "preview_available": bool(ret and frame is not None),
        }
    finally:
        cap.release()


def _active_camera_indices() -> dict[int, tuple[int, int]]:
    """Return {index: (width, height)} for cameras already open in CameraService."""
    svc = shared_state.camera_service
    if svc is None:
        return {}
    result: dict[int, tuple[int, int]] = {}
    for device in svc.devices.values():
        source = device.capture_thread.getCameraSource()
        if not isinstance(source, int):
            continue
        frame = device.latest_frame
        if frame is not None and frame.raw is not None:
            h, w = frame.raw.shape[:2]
            result[source] = (w, h)
        else:
            result[source] = (0, 0)
    return result


def _is_ignored_camera_name(name: str) -> bool:
    normalized = " ".join(str(name or "").replace("\u00a0", " ").casefold().split())
    if not normalized:
        return False
    if "macbook" in normalized and ("camera" in normalized or "kamera" in normalized):
        return True
    if normalized in {"facetime hd camera", "built-in retina camera"}:
        return True
    return False


def _list_usb_cameras() -> List[Dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    active = _active_camera_indices()

    if platform.system() == "Darwin":
        enumerated = [
            camera
            for camera in refresh_macos_cameras()
            if not _is_ignored_camera_name(str(camera.name))
        ]
        if enumerated:
            indices_to_probe = [
                int(c.index) for c in enumerated if int(c.index) not in active
            ]
            probed_map: dict[int, dict] = {}
            if indices_to_probe:
                with ThreadPoolExecutor(max_workers=min(4, len(indices_to_probe))) as pool:
                    futs = {pool.submit(_probe_camera_index, idx): idx for idx in indices_to_probe}
                    for fut in as_completed(futs):
                        idx = futs[fut]
                        probed_map[idx] = fut.result() or {}

            cameras: List[Dict[str, Any]] = []
            for camera in enumerated:
                idx = int(camera.index)
                if idx in active:
                    w, h = active[idx]
                    info = {"width": w, "height": h, "preview_available": w > 0 and h > 0}
                else:
                    info = probed_map.get(idx, {})
                cameras.append(
                    {
                        "kind": "usb",
                        "index": idx,
                        "name": str(camera.name),
                        "width": int(info.get("width", 0)),
                        "height": int(info.get("height", 0)),
                        "preview_available": bool(info.get("preview_available", False)),
                    }
                )
            return cameras

    # Linux: a capture camera is a node with pixel formats. Asking for them does
    # not open a stream, so a camera already streaming a preview (or a probe
    # running in a parallel request) is still listed; opening every camera to
    # probe it made the list come back with a different subset each time.
    usb_cameras: List[Dict[str, Any]] = []
    for i in range(16):
        if i in active and active[i] != (0, 0):
            w, h = active[i]
        else:
            modes = list_v4l2_modes(i)
            if not modes:
                continue
            mode = default_capture_mode(modes) or modes[0]
            w, h = int(mode["width"]), int(mode["height"])
        usb_cameras.append({
            "kind": "usb",
            "index": i,
            "name": _v4l2_camera_name(i),
            "width": w,
            "height": h,
            "preview_available": True,
        })
    return usb_cameras


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class CameraAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    c_channel_2: Optional[int | str] = None
    c_channel_3: Optional[int | str] = None
    classification_channel: Optional[int | str] = None
    carousel: Optional[int | str] = None


@router.get("/api/cameras/config")
def get_camera_config() -> Dict[str, Any]:
    """Return current camera assignments from TOML."""
    try:
        raw = machine_toml.read()
        return {role: _camera_source_for_role(raw, role) for role in CAMERA_SETUP_ROLES}
    except HTTPException:
        return dict.fromkeys(CAMERA_SETUP_ROLES)


@router.get("/api/cameras/list")
def list_cameras() -> Dict[str, Any]:
    """List the USB cameras this machine can see."""
    return {"usb": _list_usb_cameras()}


@router.post("/api/cameras/assign")
def assign_cameras(assignment: CameraAssignment) -> Dict[str, Any]:
    """Save camera role assignments to the machine TOML config."""
    with machine_toml.edit() as config:

        # Update cameras section
        cameras = config.get("cameras", {})
        if not isinstance(cameras, dict):
            cameras = {}
        cameras = {role: value for role, value in cameras.items() if role in CAMERA_SETUP_ROLES}
        updates = assignment.model_dump(exclude_unset=True)
        # A capture mode saved for a role belonged to the camera it had; a new
        # camera starts from its own default mode.
        capture_modes = config.get("camera_capture_modes")
        for key, value in updates.items():
            previous_source = cameraSourceForRole(cameras, key)
            if key in {"classification_channel", "carousel"}:
                alias = "carousel" if key == "classification_channel" else "classification_channel"
                cameras.pop(alias, None)
                if isinstance(capture_modes, dict) and previous_source != value:
                    capture_modes.pop(alias, None)
            if isinstance(capture_modes, dict) and previous_source != value:
                capture_modes.pop(key, None)
            if value is None:
                cameras.pop(key, None)
            else:
                cameras[key] = value
        config["cameras"] = cameras

    applied_live: Dict[str, bool] = {}
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setCameraSourceForRole"):
        for key, value in updates.items():
            try:
                applied_live[key] = bool(shared_state.vision_manager.setCameraSourceForRole(key, value))
            except Exception:
                applied_live[key] = False

    assignment = {role: _camera_source_for_role(config, role) for role in CAMERA_SETUP_ROLES}
    shared_state.publishCamerasConfig(assignment)

    # Perception (rev04 mode pair) binds each channel to a camera role's
    # capture thread. A reassignment swaps which physical camera (and which
    # resolution) backs a role; poke the reconciler so it rebinds the affected
    # channels within a couple seconds instead of needing a restart.
    _ps = getattr(shared_state.gc_ref, "perception_service", None)
    if _ps is not None:
        try:
            _ps.request_reconcile()
        except Exception:
            pass

    return {
        "ok": True,
        "assignment": assignment,
        "applied_live": applied_live,
        "message": (
            "Camera assignment updated live."
            if updates and all(applied_live.get(key, False) for key in updates.keys())
            else "Camera assignment saved."
        ),
    }
