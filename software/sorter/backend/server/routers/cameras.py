"""Router for camera-related endpoints.

Covers camera config, listing, streaming, assignment, picture settings,
device settings, and baseline capture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from blob_manager import BLOB_DIR, getCameraSetup, getChannelPolygons, getClassificationPolygons
from vision.channel_alignment import (
    alignmentRotationDeg,
    dropStartAngleForRole,
    rotateImageBgr,
)
from hardware.macos_camera_registry import refresh_macos_cameras
from irl.bin_layout import getBinLayout
from irl.config import (
    cameraDeviceSettingsToDict,
    cameraPictureSettingsToDict,
    parseCameraDeviceSettings,
    parseCameraPictureSettings,
)
# Max width of the MJPEG preview stream (annotated frame is downscaled to
# this before JPEG encoding). Annotation still runs at full capture resolution;
# this only shrinks the encoded-and-transmitted frame. 0 disables the resize.
PREVIEW_MAX_WIDTH = int(os.environ.get("SORTER_PREVIEW_MAX_WIDTH", "960"))

from server import shared_state
from server.camera_discovery import getDiscoveredCameraStreams

router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMERA_SETUP_ROLES = {
    "feeder",
    "c_channel_2",
    "c_channel_3",
    "classification_channel",
    "carousel",
    "classification_top",
    "classification_bottom",
}

_DASHBOARD_CROP_PADDING_FACTOR = 0.14
_DASHBOARD_CROP_MIN_PADDING_PX = 48.0
_DASHBOARD_MASK_BACKGROUND_BGR = (230, 230, 230)
_DASHBOARD_QUAD_PADDING_FACTOR = 0.1

logger = logging.getLogger(__name__)


from server.config_helpers import (
    machine_params_path as _camera_params_path,
    read_machine_params_config as _read_machine_params_config,
    toml_value as _toml_value,
    write_machine_params_config as _write_machine_params_config,
)


# ---------------------------------------------------------------------------
# Camera helper functions
# ---------------------------------------------------------------------------


def _get_picture_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    picture_settings = config.get("camera_picture_settings", {})
    return picture_settings if isinstance(picture_settings, dict) else {}


def _get_camera_device_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    device_settings = config.get("camera_device_settings", {})
    return device_settings if isinstance(device_settings, dict) else {}


def _camera_source_for_role(config: Dict[str, Any], role: str) -> int | str | None:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    def _normalized_source(value: Any) -> int | str | None:
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized or normalized.lower() in {"none", "null", "-1"}:
                return None
            return normalized
        return None

    cameras = config.get("cameras", {})
    if isinstance(cameras, dict):
        source = _normalized_source(cameras.get(role))
        if source is not None:
            return source
        if role == "classification_channel":
            source = _normalized_source(cameras.get("carousel"))
            if source is not None:
                return source
        if role == "carousel":
            source = _normalized_source(cameras.get("classification_channel"))
            if source is not None:
                return source

    if role in {"feeder", "classification_top", "classification_bottom"}:
        camera_setup = getCameraSetup()
        if isinstance(camera_setup, dict):
            fallback_source = _normalized_source(camera_setup.get(role))
            if fallback_source is not None:
                return fallback_source
    return None


def _camera_config_role_for_role(config: Dict[str, Any], role: str) -> str:
    cameras = config.get("cameras", {})
    cameras_section = cameras if isinstance(cameras, dict) else {}
    if (
        role == "carousel"
        and cameras_section.get("carousel") is None
        and cameras_section.get("classification_channel") is not None
    ):
        return "classification_channel"
    if (
        role == "classification_channel"
        and cameras_section.get("classification_channel") is None
        and cameras_section.get("carousel") is not None
    ):
        return "carousel"
    return role


def _camera_physical_source_key(source: int | str | None) -> str | None:
    if isinstance(source, int):
        return f"video:{source}"
    if isinstance(source, str):
        return f"url:{source}"
    return None


def _android_camera_base_url(source: int | str | None) -> str | None:
    if not isinstance(source, str):
        return None
    try:
        parsed = urllib_parse.urlparse(source)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _android_camera_request(
    source: int | str | None,
    path: str,
    *,
    method: str = "GET",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    base_url = _android_camera_base_url(source)
    if base_url is None:
        raise HTTPException(status_code=400, detail="Camera source is not an Android camera app URL.")

    url = f"{base_url}{path}"
    data = None
    headers: Dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=detail or f"Android camera app returned HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Android camera app: {exc}")

    try:
        parsed = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Android camera app returned invalid JSON: {exc}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Android camera app returned an unexpected response.")

    return parsed


def _android_camera_bytes_request(source: int | str | None, path: str) -> bytes:
    base_url = _android_camera_base_url(source)
    if base_url is None:
        raise HTTPException(status_code=400, detail="Camera source is not an Android camera app URL.")

    url = f"{base_url}{path}"
    request = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            return response.read()
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=detail or f"Android camera app returned HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Android camera app: {exc}")


def _camera_service_usb_device_controls(
    role: str,
    source: int,
    saved_settings: Dict[str, int | float | bool],
) -> tuple[List[Dict[str, Any]], Dict[str, int | float | bool]]:
    svc = shared_state.camera_service
    if svc is not None and hasattr(svc, "inspect_device_controls_for_role"):
        try:
            controls, live_settings = svc.inspect_device_controls_for_role(role, source, saved_settings)
            return controls, cameraDeviceSettingsToDict(live_settings or saved_settings)
        except Exception:
            pass
    return [], cameraDeviceSettingsToDict(saved_settings)


def _apply_live_usb_device_settings(
    role: str,
    parsed: Dict[str, int | float | bool],
    *,
    persist: bool,
) -> tuple[Dict[str, int | float | bool], bool]:
    svc = shared_state.camera_service
    if svc is not None and hasattr(svc, "set_device_settings_for_role"):
        try:
            live_result = svc.set_device_settings_for_role(role, parsed, persist=persist)
            if live_result is not None:
                return cameraDeviceSettingsToDict(live_result), True
        except Exception:
            pass

    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setDeviceSettingsForRole"):
        try:
            live_result = shared_state.vision_manager.setDeviceSettingsForRole(role, parsed, persist=persist)
            if live_result is not None:
                return cameraDeviceSettingsToDict(live_result), True
        except Exception:
            pass

    # No service owns this camera yet (e.g. the setup wizard before the runtime
    # is up). V4L2 controls are global to the device node, so push them straight
    # to /dev/video{source} via v4l2-ctl — the same authoritative path the live
    # camera uses — instead of only persisting and leaving the sensor untouched.
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if platform.system() == "Linux" and isinstance(source, int):
        try:
            from vision.camera import apply_device_settings_via_v4l2

            applied = apply_device_settings_via_v4l2(source, parsed)
            return cameraDeviceSettingsToDict(applied), True
        except Exception:
            pass

    return dict(parsed), False


def _default_camera_device_settings_from_controls(
    controls: List[Dict[str, Any]],
) -> Dict[str, int | float | bool]:
    settings: Dict[str, int | float | bool] = {}
    for control in controls:
        key = control.get("key")
        if not isinstance(key, str):
            continue
        if control.get("kind") == "button" or control.get("readonly"):
            continue
        value = control.get("default")
        if isinstance(value, bool):
            settings[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            settings[key] = float(value)
    return settings


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _picture_settings_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    picture_settings = _get_picture_settings_table(config)
    return cameraPictureSettingsToDict(parseCameraPictureSettings(picture_settings.get(role)))


# ---------------------------------------------------------------------------
# Live frame helpers
# ---------------------------------------------------------------------------


def _camera_source_matches(
    capture: Any,
    source: int | str | None,
) -> bool:
    if source is None:
        return True
    getter = getattr(capture, "getCameraSource", None)
    if not callable(getter):
        return True
    try:
        return getter() == source
    except Exception:
        return True


def _frame_pixels(frame_obj: Any) -> tuple[np.ndarray, float] | None:
    if frame_obj is None:
        return None
    frame = getattr(frame_obj, "raw", None)
    if not isinstance(frame, np.ndarray) or frame.size <= 0:
        return None
    timestamp = float(getattr(frame_obj, "timestamp", 0.0) or 0.0)
    return frame.copy(), timestamp


def _grab_running_capture_frame_entry(
    role: str,
    source: int | str | None,
    *,
    after_timestamp: float | None = None,
    timeout: float = 1.0,
    max_age_s: float = 2.0,
    allow_stale: bool = True,
) -> tuple[np.ndarray, float] | None:
    """Return pixels from an already-running capture pipeline."""

    def candidates() -> list[Any]:
        out: list[Any] = []
        svc = shared_state.camera_service
        if svc is not None:
            try:
                feed = svc.get_feed(role) if hasattr(svc, "get_feed") else None
            except Exception:
                feed = None
            if feed is not None:
                out.append(("feed", feed))
            try:
                capture = (
                    svc.get_capture_thread_for_role(role)
                    if hasattr(svc, "get_capture_thread_for_role")
                    else None
                )
            except Exception:
                capture = None
            if capture is not None:
                out.append(("capture", capture))

        vm = shared_state.vision_manager
        if vm is not None and hasattr(vm, "getCaptureThreadForRole"):
            try:
                capture = vm.getCaptureThreadForRole(role)
            except Exception:
                capture = None
            if capture is not None:
                out.append(("capture", capture))
        return out

    def read_candidate(candidate: Any) -> tuple[np.ndarray, float] | None:
        kind, obj = candidate
        if kind == "feed":
            capture = getattr(getattr(obj, "device", None), "capture_thread", None)
            if capture is not None and not _camera_source_matches(capture, source):
                return None
            getter = getattr(obj, "get_frame", None)
            if not callable(getter):
                return None
            try:
                frame_obj = getter(annotated=False)
            except TypeError:
                frame_obj = getter(False)
            except Exception:
                return None
        else:
            if not _camera_source_matches(obj, source):
                return None
            frame_obj = getattr(obj, "latest_frame", None)
        pixels = _frame_pixels(frame_obj)
        if pixels is None:
            return None
        frame, timestamp = pixels
        if after_timestamp is not None and timestamp < float(after_timestamp):
            return None
        if timestamp > 0 and time.time() - timestamp > max_age_s:
            return None
        return frame, timestamp

    deadline = time.time() + max(0.0, timeout)
    stale_candidate: tuple[np.ndarray, float] | None = None
    while True:
        for candidate in candidates():
            current = read_candidate(candidate)
            if current is not None:
                return current
            if allow_stale:
                kind, obj = candidate
                if kind == "feed":
                    capture = getattr(getattr(obj, "device", None), "capture_thread", None)
                    if capture is not None and not _camera_source_matches(capture, source):
                        continue
                elif not _camera_source_matches(obj, source):
                    continue
                frame_obj = None
                if kind == "feed":
                    getter = getattr(obj, "get_frame", None)
                    try:
                        frame_obj = getter(annotated=False) if callable(getter) else None
                    except Exception:
                        frame_obj = None
                else:
                    frame_obj = getattr(obj, "latest_frame", None)
                pixels = _frame_pixels(frame_obj)
                if pixels is not None:
                    stale_candidate = pixels
        if time.time() >= deadline:
            return stale_candidate
        time.sleep(0.03)


def _grab_live_frame(
    role: str,
    after_timestamp: float,
    timeout: float = 1.0,
    *,
    allow_stale: bool = True,
) -> np.ndarray | None:
    """Grab a frame from the running CaptureThread, waiting for one newer than after_timestamp."""
    entry = _grab_running_capture_frame_entry(
        role,
        None,
        after_timestamp=after_timestamp,
        timeout=timeout,
        allow_stale=allow_stale,
    )
    if entry is None:
        return None
    frame, _ = entry
    return frame

# ---------------------------------------------------------------------------
# Camera opening helpers
# ---------------------------------------------------------------------------


def _open_camera(index: int) -> cv2.VideoCapture:
    if platform.system() == "Darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def _open_camera_source(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int):
        return _open_camera(source)
    return cv2.VideoCapture(source)


def _normalized_capture_mode_entry(entry: Any) -> Dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    width = entry.get("width")
    height = entry.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return None
    mode: Dict[str, Any] = {
        "width": int(width),
        "height": int(height),
    }
    fps = entry.get("fps")
    if isinstance(fps, int) and fps > 0:
        mode["fps"] = int(fps)
    fourcc = entry.get("fourcc")
    if isinstance(fourcc, str) and fourcc.strip():
        mode["fourcc"] = fourcc.strip().upper()[:4]
    return mode


def _preferred_capture_mode(modes: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    def normalized_modes() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for mode in modes:
            normalized = _normalized_capture_mode_entry(mode)
            if normalized is not None:
                out.append(normalized)
        return out

    candidates = normalized_modes()
    if not candidates:
        return None

    def fourcc(mode: Dict[str, Any]) -> str:
        value = mode.get("fourcc")
        return value.upper() if isinstance(value, str) else ""

    def fps(mode: Dict[str, Any]) -> int:
        value = mode.get("fps")
        return int(value) if isinstance(value, int) and value > 0 else 0

    def best(filtered: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not filtered:
            return None
        return max(filtered, key=lambda m: (fps(m) <= 30, fps(m)))

    preferred_720 = [
        mode
        for mode in candidates
        if mode["width"] == 1280 and mode["height"] == 720 and fourcc(mode) == "MJPG"
    ]
    picked = best(preferred_720)
    if picked is not None:
        return picked

    modest_mjpg = [
        mode
        for mode in candidates
        if fourcc(mode) == "MJPG" and mode["width"] <= 1280 and mode["height"] <= 720
    ]
    if modest_mjpg:
        return max(modest_mjpg, key=lambda m: (m["width"] * m["height"], fps(m) <= 30, fps(m)))

    mjpg = [mode for mode in candidates if fourcc(mode) == "MJPG"]
    if mjpg:
        return min(mjpg, key=lambda m: (m["width"] * m["height"], -fps(m)))

    return min(candidates, key=lambda m: (m["width"] * m["height"], -fps(m)))


def _capture_mode_for_role(config: Dict[str, Any], role: str, source: int | str | None) -> Dict[str, Any]:
    saved_section = config.get("camera_capture_modes", {})
    if isinstance(saved_section, dict):
        saved = _normalized_capture_mode_entry(saved_section.get(role))
        if saved is not None:
            return saved

    if isinstance(source, int):
        modes, _ = _capture_modes_for_source(source)
        preferred = _preferred_capture_mode(modes)
        if preferred is not None:
            return preferred

    return {"width": 1280, "height": 720, "fps": 30, "fourcc": "MJPG"}


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


def _run_v4l2_ctl(index: int, *args: str, timeout: float = 2.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{index}", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None


def _v4l2_formats_include_video_capture(output: str) -> bool:
    return bool(re.search(r"^\s*\[\d+\]:", output or "", re.MULTILINE))


def _v4l2_size_from_output(output: str) -> tuple[int, int]:
    match = re.search(r"Width/Height\s*:\s*(\d+)\s*/\s*(\d+)", output or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _linux_video_indices() -> list[int]:
    indices: list[int] = []
    for path in Path("/sys/class/video4linux").glob("video[0-9]*"):
        suffix = path.name.removeprefix("video")
        if suffix.isdigit():
            indices.append(int(suffix))
    return sorted(set(indices))


def _linux_v4l2_capture_info(index: int) -> dict[str, Any] | None:
    formats = _run_v4l2_ctl(index, "--list-formats-ext")
    if formats is None or formats.returncode != 0:
        return None
    if not _v4l2_formats_include_video_capture(formats.stdout):
        # UVC metadata side-channel nodes report no real video formats. Listing
        # them in the picker makes the backend try to stream from a non-frame
        # endpoint and can leave OpenCV file descriptors around after failure.
        return None

    width = height = 0
    current = _run_v4l2_ctl(index, "--get-fmt-video")
    if current is not None and current.returncode == 0:
        width, height = _v4l2_size_from_output(current.stdout)
    if width <= 0 or height <= 0:
        details = _run_v4l2_ctl(index, "--all")
        if details is not None and details.returncode == 0:
            width, height = _v4l2_size_from_output(details.stdout)

    name = _v4l2_camera_name(index)
    if _is_ignored_camera_name(name):
        return None
    return {
        "kind": "usb",
        "index": index,
        "name": name,
        "width": width,
        "height": height,
        "preview_available": width > 0 and height > 0,
    }


def _list_linux_v4l2_cameras(active: dict[int, tuple[int, int]]) -> list[dict[str, Any]]:
    # The picker stores whatever ``index`` we emit here straight into the camera
    # config (see /api/cameras/assign). That stored value is later resolved by
    # vision.camera._resolve_linux_video_index, which treats EVEN values as
    # *logical slots* (0, 2, 4 → 1st/2nd/3rd capture camera, looked up via the
    # stable /dev/v4l/by-path *index0 nodes) so the assignment survives USB
    # re-enumeration across reboots. Emitting the raw /dev/videoN number here
    # broke that: an even one (e.g. /dev/video4) gets silently reinterpreted as a
    # slot and points at the wrong camera. So emit the logical slot — keeping the
    # picker, the persisted config, and the resolver speaking the same language.
    from vision.camera import _linux_index0_video_indices

    raw_to_slot = {raw: 2 * pos for pos, raw in enumerate(_linux_index0_video_indices())}
    cameras: list[dict[str, Any]] = []
    for index in _linux_video_indices():
        info = _linux_v4l2_capture_info(index)
        if info is None:
            continue
        slot = raw_to_slot.get(index, index)
        info["index"] = slot
        if slot in active:
            width, height = active[slot]
            if width > 0 and height > 0:
                info["width"] = width
                info["height"] = height
                info["preview_available"] = True
        cameras.append(info)
    return cameras


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

    if platform.system() == "Linux":
        return _list_linux_v4l2_cameras(active)

    # Non-macOS: probe indices 0-15, skip active ones
    indices_to_probe = [i for i in range(16) if i not in active]
    probed_map: dict[int, dict] = {}
    if indices_to_probe:
        with ThreadPoolExecutor(max_workers=min(4, len(indices_to_probe))) as pool:
            futs = {pool.submit(_probe_camera_index, idx): idx for idx in indices_to_probe}
            for fut in as_completed(futs):
                idx = futs[fut]
                result = fut.result()
                if result is not None:
                    probed_map[idx] = result

    usb_cameras: List[Dict[str, Any]] = []
    for i in range(16):
        if i in active:
            w, h = active[i]
            if w > 0 or h > 0:
                usb_cameras.append({
                    "kind": "usb",
                    "index": i,
                    "name": _v4l2_camera_name(i),
                    "width": w,
                    "height": h,
                    "preview_available": True,
                })
        elif i in probed_map:
            usb_cameras.append(probed_map[i])
    return usb_cameras


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CameraAssignment(BaseModel):
    layout: Optional[str] = None
    feeder: Optional[int | str] = None
    c_channel_2: Optional[int | str] = None
    c_channel_3: Optional[int | str] = None
    classification_channel: Optional[int | str] = None
    carousel: Optional[int | str] = None
    classification_top: Optional[int | str] = None
    classification_bottom: Optional[int | str] = None


class CameraLayoutPayload(BaseModel):
    layout: str


class CameraPictureSettingsPayload(BaseModel):
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


class CameraWebRtcOfferPayload(BaseModel):
    type: str
    sdp: str


# ===================================================================
# Routes
# ===================================================================


# ---------------------------------------------------------------------------
# Video feed (MJPEG from VisionManager)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Camera config / list / stream / feed / assign
# ---------------------------------------------------------------------------


@router.get("/api/cameras/health")
def get_camera_health() -> Dict[str, Any]:
    """Return per-role camera health status."""
    import server.shared_state as shared_state

    if shared_state.camera_service is None:
        raise HTTPException(status_code=500, detail="Camera service not initialized")
    return shared_state.camera_service.get_health_status()


def _legacy_mjpeg_client_snapshot() -> Dict[str, Any]:
    with shared_state.camera_legacy_mjpeg_clients_lock:
        return {
            key: dict(value)
            for key, value in shared_state.camera_legacy_mjpeg_clients.items()
            if isinstance(value, dict)
        }


def _legacy_mjpeg_stream_key(record: Dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def _track_legacy_mjpeg_stream(chunks: Any, record: Dict[str, Any]):
    key = _legacy_mjpeg_stream_key(record)
    now = time.time()
    with shared_state.camera_legacy_mjpeg_clients_lock:
        entry = shared_state.camera_legacy_mjpeg_clients.get(key)
        if not isinstance(entry, dict):
            entry = dict(record)
            entry["active_clients"] = 0
            entry["started_count"] = 0
            entry["first_opened_at"] = now
            shared_state.camera_legacy_mjpeg_clients[key] = entry
        entry["active_clients"] = int(entry.get("active_clients", 0) or 0) + 1
        entry["started_count"] = int(entry.get("started_count", 0) or 0) + 1
        entry["last_opened_at"] = now
    try:
        yield from chunks
    finally:
        with shared_state.camera_legacy_mjpeg_clients_lock:
            entry = shared_state.camera_legacy_mjpeg_clients.get(key)
            if isinstance(entry, dict):
                entry["active_clients"] = max(0, int(entry.get("active_clients", 0) or 0) - 1)
                entry["last_closed_at"] = time.time()


@router.get("/api/cameras/media-plane")
def get_camera_media_plane() -> Dict[str, Any]:
    """Return the active camera media-plane topology and encoder readiness."""
    from vision.media_plane import describe_media_plane

    return describe_media_plane(
        shared_state.camera_service,
        legacy_mjpeg_streams=_legacy_mjpeg_client_snapshot(),
    )


@router.get("/api/cameras/webrtc/sessions")
def get_camera_webrtc_sessions() -> Dict[str, Any]:
    """Return target WebRTC media sessions, one per physical camera source."""
    from vision.webrtc_transport import get_camera_webrtc_registry

    return get_camera_webrtc_registry().describe(shared_state.camera_service)


@router.post("/api/cameras/webrtc/offer/{role}")
async def create_camera_webrtc_offer(role: str, payload: CameraWebRtcOfferPayload) -> Dict[str, Any]:
    """Negotiate a browser WebRTC media session for a camera role.

    The target transport forbids software H.264 fallbacks. On hosts where the
    Rockchip hardware path is not ready, this route returns a structured 503
    that names the failing gates instead of silently opening another MJPEG or
    software-encoded stream.
    """
    from vision.webrtc_transport import WebRtcTransportError, get_camera_webrtc_registry

    try:
        return await get_camera_webrtc_registry().prepare_offer(
            role,
            sdp=payload.sdp,
            offer_type=payload.type,
            camera_service=shared_state.camera_service,
            metadata_provider=lambda metadata_role: _camera_feed_metadata_payload(
                metadata_role,
                show_regions=True,
            ),
        )
    except WebRtcTransportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_http_detail())


def _camera_feed_metadata_payload(role: str, show_regions: bool = True) -> Dict[str, Any]:
    from vision.media_plane import describe_feed_metadata

    _, raw = _read_machine_params_config(require_exists=True)
    config_role = _camera_config_role_for_role(raw, role)
    source = _camera_source_for_role(raw, role)
    if source is None:
        raise HTTPException(404, f"Camera role '{role}' not configured")

    service = shared_state.camera_service
    if service is None:
        raise HTTPException(503, "Camera service is not running")

    feed = service.get_feed(role)
    feed_role = role
    if feed is None and config_role != role:
        feed = service.get_feed(config_role)
        feed_role = config_role
    if feed is None:
        raise HTTPException(404, f"Camera feed '{role}' is not active")

    exclude_categories = frozenset({"regions"}) if not show_regions else None
    latest = getattr(getattr(feed, "device", None), "latest_frame", None)
    frame = getattr(latest, "raw", None)
    crop_metadata = None
    if isinstance(frame, np.ndarray) and frame.size > 0:
        frame_h, frame_w = frame.shape[:2]
        crop_metadata = _dashboard_crop_metadata(role, frame_w, frame_h)
    return describe_feed_metadata(
        str(getattr(feed, "role", feed_role)),
        feed,
        requested_role=role,
        config_role=config_role,
        physical_source=_camera_physical_source_key(source),
        exclude_categories=exclude_categories,
        crop=crop_metadata,
    )


@router.get("/api/cameras/feed-metadata")
def camera_feed_metadata_all(show_regions: bool = True) -> Dict[str, Any]:
    """Return metadata-only overlay/control-plane state for active feeds."""
    from vision.media_plane import camera_metadata_data_channel_spec, describe_feed_metadata

    service = shared_state.camera_service
    if service is None:
        return {
            "ok": True,
            "active": False,
            "roles": {},
            "control_plane": {
                "transport_target": "websocket_or_webrtc_datachannel",
                "browser_side_render_target": True,
                "payload_contains_pixels": False,
                "data_channel": camera_metadata_data_channel_spec(),
            },
        }

    _, raw = _read_machine_params_config(require_exists=True)
    exclude_categories = frozenset({"regions"}) if not show_regions else None
    roles: dict[str, Any] = {}
    for feed_role, feed in sorted(getattr(service, "feeds", {}).items()):
        feed_role_str = str(feed_role)
        config_role = _camera_config_role_for_role(raw, feed_role_str)
        try:
            source = _camera_source_for_role(raw, feed_role_str)
        except HTTPException:
            source = None
        latest = getattr(getattr(feed, "device", None), "latest_frame", None)
        frame = getattr(latest, "raw", None)
        crop_metadata = None
        if isinstance(frame, np.ndarray) and frame.size > 0:
            frame_h, frame_w = frame.shape[:2]
            crop_metadata = _dashboard_crop_metadata(feed_role_str, frame_w, frame_h)
        roles[feed_role_str] = describe_feed_metadata(
            str(getattr(feed, "role", feed_role_str)),
            feed,
            requested_role=feed_role_str,
            config_role=config_role,
            physical_source=_camera_physical_source_key(source),
            exclude_categories=exclude_categories,
            crop=crop_metadata,
        )

    return {
        "ok": True,
        "active": True,
        "roles": roles,
        "control_plane": {
            "transport_target": "websocket_or_webrtc_datachannel",
            "browser_side_render_target": True,
            "payload_contains_pixels": False,
            "data_channel": camera_metadata_data_channel_spec(),
        },
    }


@router.get("/api/cameras/feed-metadata/{role}")
def camera_feed_metadata_by_role(role: str, show_regions: bool = True) -> Dict[str, Any]:
    """Return metadata-only overlay/control-plane state for one feed role."""
    return _camera_feed_metadata_payload(role, show_regions=show_regions)


@router.websocket("/ws/cameras/feed-metadata/{role}")
async def camera_feed_metadata_ws(websocket: WebSocket, role: str) -> None:
    """Stream metadata-only overlay/control-plane state for browser rendering."""
    from server.security import describe_origin_decision, websocket_connection_allowed

    client_host = websocket.client.host if websocket.client is not None else None
    if not websocket_connection_allowed(websocket.headers.get("Origin"), client_host):
        if shared_state.gc_ref is not None:
            shared_state.gc_ref.logger.info(
                f"[WS camera metadata reject] client_host={client_host!r} "
                f"{describe_origin_decision(websocket.headers.get('Origin'))}"
            )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="WebSocket origin not allowed.",
        )
        return

    def _truthy_query(name: str, default: bool) -> bool:
        value = websocket.query_params.get(name)
        if value is None:
            return default
        return value.strip().lower() not in {"0", "false", "no", "off"}

    def _interval_s() -> float:
        raw = websocket.query_params.get("interval_ms")
        try:
            interval_ms = float(raw) if raw is not None else 100.0
        except (TypeError, ValueError):
            interval_ms = 100.0
        return max(0.033, min(1.0, interval_ms / 1000.0))

    await websocket.accept()
    show_regions = _truthy_query("show_regions", True)
    interval_s = _interval_s()
    last_frame_ts: float | None = None

    try:
        while True:
            try:
                payload = _camera_feed_metadata_payload(role, show_regions=show_regions)
            except HTTPException as exc:
                await websocket.send_json(
                    {
                        "ok": False,
                        "role": role,
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                    }
                )
                await asyncio.sleep(interval_s)
                continue

            frame = payload.get("frame") if isinstance(payload, dict) else None
            frame_ts = (
                float(frame.get("timestamp"))
                if isinstance(frame, dict) and isinstance(frame.get("timestamp"), (int, float))
                else None
            )
            if frame_ts is None or frame_ts != last_frame_ts:
                await websocket.send_json(payload)
                last_frame_ts = frame_ts
            await asyncio.sleep(interval_s)
    except WebSocketDisconnect:
        return


@router.get("/api/cameras/config")
def get_camera_config() -> Dict[str, Any]:
    """Return current camera assignments from TOML."""
    try:
        _, raw = _read_machine_params_config()
        cameras = raw.get("cameras", {}) if isinstance(raw, dict) else {}
        if not isinstance(cameras, dict):
            cameras = {}
        return {
            "layout": cameras.get("layout", "default"),
            "feeder": _camera_source_for_role(raw, "feeder"),
            "c_channel_2": _camera_source_for_role(raw, "c_channel_2"),
            "c_channel_3": _camera_source_for_role(raw, "c_channel_3"),
            "classification_channel": _camera_source_for_role(raw, "classification_channel"),
            "carousel": _camera_source_for_role(raw, "carousel"),
            "classification_top": _camera_source_for_role(raw, "classification_top"),
            "classification_bottom": _camera_source_for_role(raw, "classification_bottom"),
        }
    except HTTPException:
        return {
            "layout": "default",
            "feeder": None,
            "c_channel_2": None,
            "c_channel_3": None,
            "classification_channel": None,
            "carousel": None,
            "classification_top": None,
            "classification_bottom": None,
        }


@router.post("/api/cameras/layout")
def save_camera_layout(payload: CameraLayoutPayload) -> Dict[str, Any]:
    if payload.layout not in {"default", "split_feeder"}:
        raise HTTPException(
            status_code=400,
            detail="layout must be 'default' or 'split_feeder'.",
        )

    params_path, config = _read_machine_params_config()
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict):
        cameras = {}
    cameras["layout"] = payload.layout
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    result = get_camera_config()
    shared_state.publishCamerasConfig(result)
    current_state = "initializing"
    if shared_state.controller_ref is not None:
        current_state = getattr(shared_state.controller_ref.state, "value", current_state)
    shared_state.publishSorterState(current_state, payload.layout)
    return result


@router.get("/api/cameras/list")
def list_cameras() -> Dict[str, Any]:
    """List local USB cameras plus discovered network camera streams."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        usb_fut = pool.submit(_list_usb_cameras)
        net_fut = pool.submit(getDiscoveredCameraStreams)
        return {
            "usb": usb_fut.result(),
            "network": net_fut.result(),
        }


def _device_capturing_index(index: int):
    """Return the camera-service device already capturing ``index``, if any.

    The picker streams cameras by device index. When that index is assigned to
    a role, the camera service's capture thread already holds /dev/videoN open;
    opening a second VideoCapture on it fights the live pipeline for frames and
    spikes USB/CPU. Reusing the running capture thread avoids the duplicate open.
    """
    service = shared_state.camera_service
    if service is None:
        return None
    seen: set[int] = set()
    for device in service.devices.values():
        if id(device) in seen:
            continue
        seen.add(id(device))
        try:
            if device.capture_thread.getCameraSource() == index:
                return device
        except Exception:
            continue
    return None


@router.get("/api/cameras/stream/{index}")
def camera_stream(index: int):
    """MJPEG thumbnail stream for a single camera by index.

    Served from the running capture thread when the index is already owned by a
    role; only falls back to a direct device open when nothing else holds it.
    """
    def _encode_thumb(frame: np.ndarray) -> bytes:
        thumb = cv2.resize(frame, (426, 240))
        ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if not ok:
            return b""
        return (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        )

    shared_device = _device_capturing_index(index)

    if shared_device is not None:
        def generate_shared():
            while True:
                frame_obj = shared_device.latest_frame
                if frame_obj is None or frame_obj.raw is None:
                    time.sleep(0.05)
                    continue
                chunk = _encode_thumb(frame_obj.raw)
                if chunk:
                    yield chunk
                time.sleep(0.1)

        return StreamingResponse(
            generate_shared(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    def generate_direct():
        cap = _open_camera_for_probe(index)
        if not cap.isOpened():
            return
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                chunk = _encode_thumb(frame)
                if chunk:
                    yield chunk
        finally:
            cap.release()

    return StreamingResponse(
        generate_direct(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _dashboard_polygon_resolution(saved: Dict[str, Any] | None) -> tuple[float, float]:
    if not isinstance(saved, dict):
        return (1920.0, 1080.0)
    return _dashboard_saved_resolution(saved.get("resolution"), (1920.0, 1080.0))


def _dashboard_saved_resolution(
    resolution: Any,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        width = _as_number(resolution[0])
        height = _as_number(resolution[1])
        if width and width > 0 and height and height > 0:
            return (width, height)
    return fallback


def _dashboard_channel_angle_key(polygon_key: str) -> str | None:
    return {
        "second_channel": "second",
        "third_channel": "third",
        "classification_channel": "classification_channel",
    }.get(polygon_key)


def _dashboard_channel_resolution(
    saved: Dict[str, Any],
    polygon_key: str,
) -> tuple[float, float]:
    fallback = _dashboard_polygon_resolution(saved)
    angle_key = _dashboard_channel_angle_key(polygon_key)
    arc_params = saved.get("arc_params") if isinstance(saved.get("arc_params"), dict) else {}
    if angle_key is not None:
        raw_arc = arc_params.get(angle_key)
        if isinstance(raw_arc, dict):
            return _dashboard_saved_resolution(raw_arc.get("resolution"), fallback)
    quad_params = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
    raw_quad = quad_params.get(polygon_key)
    if isinstance(raw_quad, dict):
        return _dashboard_saved_resolution(raw_quad.get("resolution"), fallback)
    return fallback


def _dashboard_classification_resolution(
    saved: Dict[str, Any],
    quad_key: str,
) -> tuple[float, float]:
    fallback = _dashboard_polygon_resolution(saved)
    quad_params = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
    raw_quad = quad_params.get(quad_key)
    if isinstance(raw_quad, dict):
        return _dashboard_saved_resolution(raw_quad.get("resolution"), fallback)
    return fallback


def _dashboard_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, (list, tuple)):
        return []
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = _as_number(point[0])
        y = _as_number(point[1])
        if x is None or y is None:
            continue
        points.append((float(x), float(y)))
    return points


def _dashboard_quad_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, dict):
        return []
    return _dashboard_points(raw.get("corners"))


def _scale_dashboard_points(
    points: list[tuple[float, float]],
    source_resolution: tuple[float, float],
    frame_w: int,
    frame_h: int,
) -> np.ndarray | None:
    if len(points) < 3:
        return None
    src_w, src_h = source_resolution
    if src_w <= 0 or src_h <= 0 or frame_w <= 0 or frame_h <= 0:
        return None
    scaled = np.array(points, dtype=np.float32)
    scaled[:, 0] *= float(frame_w) / float(src_w)
    scaled[:, 1] *= float(frame_h) / float(src_h)
    return scaled


def _dashboard_channel_crop_polygon(
    saved: Dict[str, Any],
    polygon_key: str,
    polygons_table: Dict[str, Any],
    frame_w: int,
    frame_h: int,
) -> np.ndarray | None:
    angle_key = _dashboard_channel_angle_key(polygon_key)
    if angle_key is not None:
        try:
            from subsystems.feeder.analysis import channelArcCropPolygon, parseSavedChannelArcZones

            arc = parseSavedChannelArcZones(
                angle_key,
                saved.get("channel_angles") if isinstance(saved.get("channel_angles"), dict) else {},
                saved.get("arc_params") if isinstance(saved.get("arc_params"), dict) else {},
            )
            if arc is not None and arc.outer_radius > arc.inner_radius > 0:
                # Match what the live region overlay does (handdrawn_region_provider
                # ._scaledChannelMask): scale the center separately for x/y so it
                # tracks the frame, but apply a *uniform* radius_scale so the arc
                # stays a true circle. Building the polygon and then squashing
                # x/y independently produces an oval crop that doesn't match the
                # zone the operator drew.
                src_w, src_h = _dashboard_channel_resolution(saved, polygon_key)
                if src_w > 0 and src_h > 0 and frame_w > 0 and frame_h > 0:
                    sx = float(frame_w) / float(src_w)
                    sy = float(frame_h) / float(src_h)
                    cx = arc.center[0] * sx
                    cy = arc.center[1] * sy
                    r_scale = (sx + sy) / 2.0
                    polygon = channelArcCropPolygon(
                        arc, center=(cx, cy), radius_scale=r_scale
                    )
                    return polygon.astype(np.float32)
        except Exception:
            pass
    # Fallback: scale a manually drawn polygon from saved resolution to frame.
    points = _dashboard_points(polygons_table.get(polygon_key))
    return _scale_dashboard_points(
        points,
        _dashboard_channel_resolution(saved, polygon_key),
        frame_w,
        frame_h,
    )


def _dashboard_padded_bbox(
    polygons: list[np.ndarray],
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int] | None:
    if not polygons:
        return None
    merged = np.concatenate(polygons, axis=0)
    min_x = float(np.min(merged[:, 0]))
    min_y = float(np.min(merged[:, 1]))
    max_x = float(np.max(merged[:, 0]))
    max_y = float(np.max(merged[:, 1]))
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)
    pad_x = max(_DASHBOARD_CROP_MIN_PADDING_PX, width * _DASHBOARD_CROP_PADDING_FACTOR)
    pad_y = max(_DASHBOARD_CROP_MIN_PADDING_PX, height * _DASHBOARD_CROP_PADDING_FACTOR)
    x1 = max(0, int(np.floor(min_x - pad_x)))
    y1 = max(0, int(np.floor(min_y - pad_y)))
    x2 = min(frame_w, int(np.ceil(max_x + pad_x)))
    y2 = min(frame_h, int(np.ceil(max_y + pad_y)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _dashboard_masked_polygons_crop(
    frame: np.ndarray,
    polygons: list[np.ndarray],
) -> np.ndarray | None:
    valid = [polygon for polygon in polygons if len(polygon) >= 3]
    if not valid:
        return None

    frame_h, frame_w = frame.shape[:2]
    merged = np.concatenate(valid, axis=0)
    x1 = max(0, int(np.floor(float(np.min(merged[:, 0])))))
    y1 = max(0, int(np.floor(float(np.min(merged[:, 1])))))
    x2 = min(frame_w, int(np.ceil(float(np.max(merged[:, 0])))))
    y2 = min(frame_h, int(np.ceil(float(np.max(merged[:, 1])))))
    if x2 <= x1 or y2 <= y1:
        return None

    crop = np.ascontiguousarray(frame[y1:y2, x1:x2])
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    for polygon in valid:
        points = np.round(polygon).astype(np.int32).copy()
        points[:, 0] -= x1
        points[:, 1] -= y1
        cv2.fillPoly(mask, [points], 255)
    masked = np.full_like(crop, _DASHBOARD_MASK_BACKGROUND_BGR)
    masked[mask == 255] = crop[mask == 255]
    return np.ascontiguousarray(masked)


def _dashboard_expand_quad(quad: np.ndarray) -> np.ndarray:
    # Expand the quad along its *own* local axes (width direction = u, height
    # direction = v) rather than radially from the centroid. Radial expansion
    # gives non-uniform padding on the two axes for non-square quads – a tall
    # quad ends up with far less horizontal padding than vertical, which is
    # why classification previews appeared clipped on the left/right sides.
    width_top_vec = quad[1] - quad[0]
    width_bottom_vec = quad[2] - quad[3]
    height_right_vec = quad[2] - quad[1]
    height_left_vec = quad[3] - quad[0]

    avg_width_vec = (width_top_vec + width_bottom_vec) / 2.0
    avg_height_vec = (height_right_vec + height_left_vec) / 2.0
    avg_width_len = float(np.linalg.norm(avg_width_vec))
    avg_height_len = float(np.linalg.norm(avg_height_vec))

    if avg_width_len <= 1e-6 or avg_height_len <= 1e-6:
        return quad.astype(np.float32)

    padding = max(
        _DASHBOARD_CROP_MIN_PADDING_PX,
        max(avg_width_len, avg_height_len) * _DASHBOARD_QUAD_PADDING_FACTOR,
    )

    u = (avg_width_vec / avg_width_len).astype(np.float32)
    v = (avg_height_vec / avg_height_len).astype(np.float32)

    # Each corner moves `padding` pixels outward along both local axes.
    signs = np.array(
        [
            [-1.0, -1.0],  # top-left
            [+1.0, -1.0],  # top-right
            [+1.0, +1.0],  # bottom-right
            [-1.0, +1.0],  # bottom-left
        ],
        dtype=np.float32,
    )

    expanded = quad.astype(np.float32).copy()
    for index in range(4):
        s_u, s_v = signs[index]
        expanded[index] = expanded[index] + (s_u * padding) * u + (s_v * padding) * v
    return expanded


def _dashboard_quad_size(quad: np.ndarray) -> tuple[int, int]:
    width_top = float(np.linalg.norm(quad[1] - quad[0]))
    width_bottom = float(np.linalg.norm(quad[2] - quad[3]))
    height_right = float(np.linalg.norm(quad[2] - quad[1]))
    height_left = float(np.linalg.norm(quad[3] - quad[0]))
    width = max(1, int(round(max(width_top, width_bottom))))
    height = max(1, int(round(max(height_right, height_left))))
    return (width, height)


def _dashboard_channel_rotation_deg(role: str, saved: Dict[str, Any] | None) -> float:
    """Rotation (degrees, CCW positive) needed so the drop-zone start of the
    given role sits at 6 o'clock in the rendered dashboard tile. Returns 0
    when the role has no arc-zone configuration."""
    return alignmentRotationDeg(dropStartAngleForRole(role, saved))


def _dashboard_crop_spec(role: str, frame_w: int, frame_h: int) -> Dict[str, Any] | None:
    if role in {"feeder", "c_channel_2", "c_channel_3", "carousel", "classification_channel"}:
        saved = getChannelPolygons() or {}
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        classification_channel_setup = bool(
            shared_state.vision_manager is not None
            and hasattr(shared_state.vision_manager, "_usesClassificationChannelSetup")
            and shared_state.vision_manager._usesClassificationChannelSetup()
        )
        carousel_polygon_key = "classification_channel" if classification_channel_setup else "carousel"

        if role == "carousel" and not classification_channel_setup:
            quad_points = _dashboard_quad_points(quad_table.get("carousel"))
            if len(quad_points) != 4:
                quad_points = _dashboard_points(polygons_table.get(carousel_polygon_key))
            scaled_quad = (
                _scale_dashboard_points(
                    quad_points,
                    _dashboard_channel_resolution(saved, carousel_polygon_key),
                    frame_w,
                    frame_h,
                )
                if len(quad_points) == 4 else None
            )
            if scaled_quad is not None and len(scaled_quad) == 4:
                expanded_quad = _dashboard_expand_quad(scaled_quad)
                target_w, target_h = _dashboard_quad_size(expanded_quad)
                destination = np.array(
                    [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
                    dtype=np.float32,
                )
                return {
                    "kind": "rectified",
                    "matrix": cv2.getPerspectiveTransform(expanded_quad.astype(np.float32), destination),
                    "size": (target_w, target_h),
                    "rotation_deg": _dashboard_channel_rotation_deg(role, saved),
                }

        polygon_keys = {
            "feeder": ["second_channel", "third_channel", carousel_polygon_key],
            "c_channel_2": ["second_channel"],
            "c_channel_3": ["third_channel"],
            "carousel": [carousel_polygon_key],
            "classification_channel": ["classification_channel"],
        }.get(role, [])
        scaled_polygons = [
            scaled
            for key in polygon_keys
            for scaled in [
                _dashboard_channel_crop_polygon(saved, key, polygons_table, frame_w, frame_h)
            ]
            if scaled is not None
        ]
        if not scaled_polygons:
            return None
        # The combined "feeder" view shows all channels at once — rotating it
        # would smear their reference frames against each other, so we keep it
        # un-rotated and only align single-channel views.
        single_channel = role in {
            "c_channel_2", "c_channel_3", "carousel", "classification_channel",
        }
        rotation_deg = _dashboard_channel_rotation_deg(role, saved) if single_channel else 0.0
        return {
            "kind": "bbox_masked",
            "polygons": scaled_polygons,
            "rotation_deg": rotation_deg,
        }

    if role in {"classification_top", "classification_bottom"}:
        saved = getClassificationPolygons() or {}
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        quad_key = "class_top" if role == "classification_top" else "class_bottom"
        polygon_key = "top" if role == "classification_top" else "bottom"
        quad_points = _dashboard_quad_points(quad_table.get(quad_key))
        if len(quad_points) != 4:
            quad_points = _dashboard_points(polygons_table.get(polygon_key))
        scaled_quad = (
            _scale_dashboard_points(
                quad_points,
                _dashboard_classification_resolution(saved, quad_key),
                frame_w,
                frame_h,
            )
            if len(quad_points) == 4 else None
        )
        if scaled_quad is not None and len(scaled_quad) == 4:
            expanded_quad = _dashboard_expand_quad(scaled_quad)
            target_w, target_h = _dashboard_quad_size(expanded_quad)
            destination = np.array(
                [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
                dtype=np.float32,
            )
            return {
                "kind": "rectified",
                "matrix": cv2.getPerspectiveTransform(expanded_quad.astype(np.float32), destination),
                "size": (target_w, target_h),
                "square": True,
            }

        scaled_polygon = _scale_dashboard_points(
            _dashboard_points(polygons_table.get(polygon_key)),
            _dashboard_classification_resolution(saved, quad_key),
            frame_w,
            frame_h,
        )
        bbox = _dashboard_padded_bbox([scaled_polygon], frame_w, frame_h) if scaled_polygon is not None else None
        return {"kind": "bbox", "bbox": bbox, "square": True} if bbox is not None else None

    return None


def _dashboard_pad_square(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0 or height == width:
        return frame
    target = max(height, width)
    pad_y = target - height
    pad_x = target - width
    top = pad_y // 2
    bottom = pad_y - top
    left = pad_x // 2
    right = pad_x - left
    return cv2.copyMakeBorder(frame, top, bottom, left, right, cv2.BORDER_REPLICATE)


def _apply_dashboard_crop(frame: np.ndarray, spec: Dict[str, Any] | None) -> np.ndarray:
    if not spec:
        return frame

    processed = frame
    if spec.get("kind") == "rectified":
        size = spec.get("size")
        matrix = spec.get("matrix")
        if not isinstance(size, tuple) or matrix is None:
            return frame
        processed = cv2.warpPerspective(
            frame,
            matrix,
            size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    elif spec.get("kind") == "bbox_masked":
        polygons = spec.get("polygons")
        if not isinstance(polygons, list):
            return frame
        processed = _dashboard_masked_polygons_crop(frame, polygons)
        if processed is None:
            return frame
    else:
        bbox = spec.get("bbox")
        if not isinstance(bbox, tuple) or len(bbox) != 4:
            return frame
        x1, y1, x2, y2 = [int(value) for value in bbox]
        if x2 <= x1 or y2 <= y1:
            return frame
        processed = frame[y1:y2, x1:x2]

    if spec.get("square"):
        processed = _dashboard_pad_square(processed)

    rotation_deg = float(spec.get("rotation_deg") or 0.0)
    if abs(rotation_deg) >= 1e-2:
        processed = rotateImageBgr(processed, rotation_deg)
    return processed


def _dashboard_crop_viewport_from_bbox(
    bbox: tuple[int, int, int, int] | None,
    frame_w: int,
    frame_h: int,
) -> Dict[str, Any] | None:
    if not isinstance(bbox, tuple) or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = [int(value) for value in bbox]
    x1 = max(0, min(frame_w, x1))
    x2 = max(0, min(frame_w, x2))
    y1 = max(0, min(frame_h, y1))
    y2 = max(0, min(frame_h, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return {
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
        "bbox": [x1, y1, x2, y2],
    }


def _dashboard_crop_viewport_from_polygons(
    polygons: list[np.ndarray],
    frame_w: int,
    frame_h: int,
) -> Dict[str, Any] | None:
    valid = [polygon for polygon in polygons if isinstance(polygon, np.ndarray) and len(polygon) >= 3]
    if not valid:
        return None
    merged = np.concatenate(valid, axis=0)
    bbox = (
        int(np.floor(float(np.min(merged[:, 0])))),
        int(np.floor(float(np.min(merged[:, 1])))),
        int(np.ceil(float(np.max(merged[:, 0])))),
        int(np.ceil(float(np.max(merged[:, 1])))),
    )
    return _dashboard_crop_viewport_from_bbox(bbox, frame_w, frame_h)


def _dashboard_points_json(points: np.ndarray) -> list[list[float]]:
    return [
        [round(float(point[0]), 3), round(float(point[1]), 3)]
        for point in points.tolist()
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]


def _dashboard_crop_output_frame(
    viewport: Dict[str, Any],
    *,
    square: bool,
    size: tuple[int, int] | None = None,
) -> Dict[str, int]:
    if isinstance(size, tuple) and len(size) == 2:
        width = max(1, int(size[0]))
        height = max(1, int(size[1]))
    else:
        width = max(1, int(viewport.get("width") or 1))
        height = max(1, int(viewport.get("height") or 1))
    if square:
        width = height = max(width, height)
    return {"width": width, "height": height}


def _dashboard_crop_metadata_from_spec(
    spec: Dict[str, Any] | None,
    frame_w: int,
    frame_h: int,
) -> Dict[str, Any] | None:
    """Serialize dashboard crop geometry for browser-side rendering.

    The legacy stream applies these specs server-side. The target media plane
    ships a single raw video track and lets the browser turn the same metadata
    into viewports, masks, rotations, and future perspective rectification.
    """
    if not spec or frame_w <= 0 or frame_h <= 0:
        return None

    kind = str(spec.get("kind") or "bbox")
    square = bool(spec.get("square"))
    rotation_deg = float(spec.get("rotation_deg") or 0.0)
    polygons_json: list[list[list[float]]] = []
    source_quad_json: list[list[float]] | None = None
    matrix_json: list[list[float]] | None = None
    rectified_size: tuple[int, int] | None = None
    viewport: Dict[str, Any] | None = None

    if kind == "rectified":
        size = spec.get("size")
        matrix = spec.get("matrix")
        if isinstance(size, tuple) and len(size) == 2:
            rectified_size = (int(size[0]), int(size[1]))
        if isinstance(matrix, np.ndarray) and matrix.shape == (3, 3) and rectified_size is not None:
            matrix_json = [
                [round(float(value), 8) for value in row]
                for row in matrix.tolist()
            ]
            try:
                target_w, target_h = rectified_size
                destination = np.array(
                    [[[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]]],
                    dtype=np.float32,
                )
                source_quad = cv2.perspectiveTransform(destination, np.linalg.inv(matrix))[0]
                source_quad_json = _dashboard_points_json(source_quad)
                viewport = _dashboard_crop_viewport_from_polygons([source_quad], frame_w, frame_h)
            except Exception:
                viewport = None
    elif kind == "bbox_masked":
        polygons = spec.get("polygons")
        if isinstance(polygons, list):
            valid_polygons = [
                polygon
                for polygon in polygons
                if isinstance(polygon, np.ndarray) and len(polygon) >= 3
            ]
            viewport = _dashboard_crop_viewport_from_polygons(valid_polygons, frame_w, frame_h)
            polygons_json = [_dashboard_points_json(polygon) for polygon in valid_polygons]
    else:
        viewport = _dashboard_crop_viewport_from_bbox(spec.get("bbox"), frame_w, frame_h)

    if viewport is None:
        return None

    return {
        "available": True,
        "kind": kind,
        "input_frame": {"width": int(frame_w), "height": int(frame_h)},
        "viewport": viewport,
        "output_frame": _dashboard_crop_output_frame(
            viewport,
            square=square,
            size=rectified_size,
        ),
        "rotation_deg": round(rotation_deg, 3),
        "square": square,
        "polygons": polygons_json,
        "source_quad": source_quad_json,
        "perspective_matrix": matrix_json,
    }


def _dashboard_crop_metadata(role: str, frame_w: int, frame_h: int) -> Dict[str, Any] | None:
    try:
        spec = _dashboard_crop_spec(role, frame_w, frame_h)
    except Exception:
        return None
    return _dashboard_crop_metadata_from_spec(spec, frame_w, frame_h)


@router.get("/api/cameras/feed/{role}")
def camera_feed_by_role(
    role: str,
    annotated: bool = True,
    layer: str = "annotated",
    direct: bool = False,
    dashboard: bool = False,
    show_regions: bool = True,
):
    """MJPEG stream for a camera role.

    ``layer`` controls annotation: ``"annotated"`` (default) or ``"raw"``.
    The legacy ``annotated`` bool param is supported for backward compat.
    ``show_regions=false`` keeps detections but hides zone polygons/labels.
    """
    from vision.camera import (
        _open_capture_source,
        apply_camera_device_settings,
        apply_picture_settings,
    )
    from vision.outputs.mjpeg import MjpegOutput
    from perception.service import is_perception_role

    # Resolve layer — legacy `annotated` param maps into `layer`
    want_annotated = layer == "annotated" and annotated
    exclude_categories = frozenset({"regions"}) if not show_regions else None
    _, raw = _read_machine_params_config(require_exists=True)
    config_role = _camera_config_role_for_role(raw, role)

    picture_settings = parseCameraPictureSettings(_get_picture_settings_table(raw).get(config_role))
    saved_device_settings = parseCameraDeviceSettings(
        _get_camera_device_settings_table(raw).get(config_role)
    )
    preview_device_settings = (
        shared_state.camera_device_preview_overrides.get(role)
        or shared_state.camera_device_preview_overrides.get(config_role)
    )
    device_settings = cameraDeviceSettingsToDict(
        preview_device_settings if preview_device_settings is not None else saved_device_settings
    )
    source = _camera_source_for_role(raw, role)
    if source is None:
        raise HTTPException(404, f"Camera role '{role}' not configured")

    encoder = MjpegOutput()

    def _legacy_mjpeg_record(stack: str) -> Dict[str, Any]:
        return {
            "transport": "legacy_mjpeg",
            "codec": "mjpeg",
            "stack": stack,
            "role": role,
            "config_role": config_role,
            "physical_source": _camera_physical_source_key(source),
            "layer": "annotated" if want_annotated else "raw",
            "direct": bool(direct),
            "dashboard": bool(dashboard),
            "show_regions": bool(show_regions),
            "preview_max_width": PREVIEW_MAX_WIDTH,
            "per_client_encode": True,
            "target_replacement": "webrtc_media_track",
        }

    cached_dashboard_shape: tuple[int, int] | None = None
    cached_dashboard_spec: Dict[str, Any] | None = None

    def _dashboard_frame(frame: np.ndarray) -> np.ndarray:
        nonlocal cached_dashboard_shape, cached_dashboard_spec
        if not dashboard:
            return frame
        frame_h, frame_w = frame.shape[:2]
        shape = (frame_w, frame_h)
        if cached_dashboard_shape != shape:
            cached_dashboard_spec = _dashboard_crop_spec(role, frame_w, frame_h)
            cached_dashboard_shape = shape
        return _apply_dashboard_crop(frame, cached_dashboard_spec)

    # ---- Stack decision: made ONCE, statically, no crossing ------------------
    # A camera role is on exactly one stack:
    #   * PERCEPTION stack   -> generate_perception_stack (below)
    #   * VISIONMANAGER/live -> generate_live
    # ``is_perception_role`` is a STATIC registry fact — it does NOT depend on
    # the perception service being built yet. So a perception role is routed to
    # the perception generator even on a fresh boot before perception is ready;
    # the generator shows raw video until perception comes up and then upgrades
    # to its overlay in-place. A perception role can NEVER land on the
    # VisionManager overlay (the old stack), at boot or any other time.
    if not direct and is_perception_role(role):
        prof = shared_state.gc_ref.profiler if shared_state.gc_ref is not None else None

        def generate_perception_stack():
            last_frame_ts: float | None = None
            while True:
                # Re-read the service each loop so a connection opened before
                # perception finished initializing upgrades from raw -> overlay
                # without a reconnect.
                ps = (
                    getattr(shared_state.gc_ref, "perception_service", None)
                    if shared_state.gc_ref is not None
                    else None
                )
                channel_id = ps.channel_id_for_role(role) if ps is not None else None
                result = None
                if want_annotated and ps is not None and channel_id is not None:
                    # preview_frame renders the overlay at preview width at most
                    # once per inference cycle (cached + shared across clients).
                    result = ps.preview_frame(channel_id, PREVIEW_MAX_WIDTH)
                if result is not None:
                    frame, frame_ts = result
                else:
                    # Annotations off, or perception not ready yet: raw pixels
                    # from the SAME shared capture thread — never a VisionManager
                    # overlay.
                    feed = (
                        shared_state.camera_service.get_feed(role)
                        if shared_state.camera_service is not None
                        else None
                    )
                    frame_obj = feed.get_frame(annotated=False) if feed is not None else None
                    if frame_obj is None:
                        time.sleep(0.05)
                        continue
                    frame_ts = frame_obj.timestamp
                    frame = frame_obj.raw
                    if PREVIEW_MAX_WIDTH > 0 and frame.shape[1] > PREVIEW_MAX_WIDTH:
                        scale = PREVIEW_MAX_WIDTH / float(frame.shape[1])
                        frame = cv2.resize(
                            frame,
                            (PREVIEW_MAX_WIDTH, int(round(frame.shape[0] * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                if last_frame_ts == frame_ts:
                    time.sleep(0.01)
                    continue
                last_frame_ts = frame_ts
                shared_state.gc_ref.runtime_stats.observePerfMs(
                    f"preview.{role}.frame_age_ms",
                    max(0.0, (time.time() - float(frame_ts)) * 1000.0),
                )
                frame = _dashboard_frame(frame)
                if prof is not None:
                    prof.hit(f"encode.{role}.frames")
                    prof.mark(f"encode.{role}.interval_ms")
                    with prof.timer(f"encode.{role}.encode_ms"):
                        chunk = encoder.encode_chunk(frame, quality=55)
                else:
                    chunk = encoder.encode_chunk(frame, quality=55)
                yield chunk

        return StreamingResponse(
            _track_legacy_mjpeg_stream(
                generate_perception_stack(),
                _legacy_mjpeg_record("perception_stack"),
            ),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # Live / VisionManager stack — NON-perception roles only.
    if not direct and shared_state.camera_service is not None:
        feed = shared_state.camera_service.get_feed(role)
        if feed is not None:
            vm_annotated = want_annotated
            prof = shared_state.gc_ref.profiler if shared_state.gc_ref is not None else None

            def generate_live():
                last_frame_ts: float | None = None
                while True:
                    fetch_started = time.perf_counter()
                    frame_obj = feed.get_frame(
                        annotated=vm_annotated,
                        exclude_categories=exclude_categories,
                    )
                    shared_state.gc_ref.runtime_stats.observePerfMs(
                        f"preview.{role}.get_frame_ms",
                        (time.perf_counter() - fetch_started) * 1000.0,
                    )
                    if frame_obj is None:
                        time.sleep(0.05)
                        continue
                    if last_frame_ts == frame_obj.timestamp:
                        time.sleep(0.01)
                        continue
                    last_frame_ts = frame_obj.timestamp
                    frame = (
                        frame_obj.annotated
                        if vm_annotated and frame_obj.annotated is not None
                        else frame_obj.raw
                    )
                    shared_state.gc_ref.runtime_stats.observePerfMs(
                        f"preview.{role}.frame_age_ms",
                        max(0.0, (time.time() - float(frame_obj.timestamp)) * 1000.0),
                    )
                    process_started = time.perf_counter()
                    # Downscale FIRST. The dashboard crop is a warpPerspective
                    # (or polygon mask) on the input frame — on a 4K camera that
                    # cost ~400 ms/frame, capping the stream at ~2 fps. Doing
                    # the cheap cv2.resize first means the expensive crop runs
                    # on a ~960-px frame. _dashboard_frame's spec cache keys on
                    # the input shape and recomputes from the (smaller) WxH —
                    # _dashboard_crop_spec already takes (role, frame_w,
                    # frame_h), so it produces a correctly-scaled spec for the
                    # downscaled frame automatically.
                    if PREVIEW_MAX_WIDTH > 0 and frame.shape[1] > PREVIEW_MAX_WIDTH:
                        scale = PREVIEW_MAX_WIDTH / float(frame.shape[1])
                        frame = cv2.resize(
                            frame,
                            (PREVIEW_MAX_WIDTH, int(round(frame.shape[0] * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    frame = _dashboard_frame(frame)
                    shared_state.gc_ref.runtime_stats.observePerfMs(
                        f"preview.{role}.process_ms",
                        (time.perf_counter() - process_started) * 1000.0,
                    )
                    if prof is not None:
                        prof.hit(f"encode.{role}.frames")
                        prof.mark(f"encode.{role}.interval_ms")
                        with prof.timer(f"encode.{role}.encode_ms"):
                            encode_started = time.perf_counter()
                            chunk = encoder.encode_chunk(frame, quality=55)
                            shared_state.gc_ref.runtime_stats.observePerfMs(
                                f"preview.{role}.encode_ms",
                                (time.perf_counter() - encode_started) * 1000.0,
                            )
                    else:
                        encode_started = time.perf_counter()
                        chunk = encoder.encode_chunk(frame, quality=55)
                        shared_state.gc_ref.runtime_stats.observePerfMs(
                            f"preview.{role}.encode_ms",
                            (time.perf_counter() - encode_started) * 1000.0,
                        )
                    yield chunk

            return StreamingResponse(
                _track_legacy_mjpeg_stream(
                    generate_live(),
                    _legacy_mjpeg_record("camera_service_live"),
                ),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

    # Direct setup feed while the runtime already owns the camera. Reuse the
    # existing CaptureThread instead of opening /dev/videoN a second time; the
    # latter fails with busy/black frames once the split dashboard is visible.
    if direct and shared_state.camera_service is not None:
        feed = shared_state.camera_service.get_feed(role) or shared_state.camera_service.get_feed(config_role)
        if feed is not None:
            prof = shared_state.gc_ref.profiler if shared_state.gc_ref is not None else None

            def generate_shared_direct():
                last_frame_ts: float | None = None
                while True:
                    frame_obj = feed.get_frame(annotated=False)
                    if frame_obj is None:
                        time.sleep(0.05)
                        continue
                    if last_frame_ts == frame_obj.timestamp:
                        time.sleep(0.01)
                        continue
                    last_frame_ts = frame_obj.timestamp
                    frame = frame_obj.raw
                    if PREVIEW_MAX_WIDTH > 0 and frame.shape[1] > PREVIEW_MAX_WIDTH:
                        scale = PREVIEW_MAX_WIDTH / float(frame.shape[1])
                        frame = cv2.resize(
                            frame,
                            (PREVIEW_MAX_WIDTH, int(round(frame.shape[0] * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    frame = _dashboard_frame(frame)
                    if prof is not None:
                        prof.hit(f"encode.{role}.shared_direct.frames")
                        prof.mark(f"encode.{role}.shared_direct.interval_ms")
                    yield encoder.encode_chunk(frame, quality=70)

            return StreamingResponse(
                _track_legacy_mjpeg_stream(
                    generate_shared_direct(),
                    _legacy_mjpeg_record("shared_direct_capture"),
                ),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

    def generate_direct():
        def open_direct_capture() -> cv2.VideoCapture:
            capture_mode = _capture_mode_for_role(raw, config_role, source)
            if isinstance(source, int):
                return _open_capture_source(
                    source,
                    width=capture_mode.get("width"),
                    height=capture_mode.get("height"),
                    fps=capture_mode.get("fps"),
                    fourcc=capture_mode.get("fourcc"),
                )
            return _open_camera_source(source)

        while True:
            cap = open_direct_capture()
            if not cap.isOpened():
                cap.release()
                time.sleep(0.25)
                continue

            try:
                if isinstance(source, int) and device_settings:
                    apply_camera_device_settings(cap, device_settings, source=source)
                read_failures = 0
                while True:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        read_failures += 1
                        if read_failures >= 3:
                            break
                        time.sleep(0.03)
                        continue
                    read_failures = 0
                    frame = apply_picture_settings(frame, picture_settings)
                    frame = _dashboard_frame(frame)
                    yield encoder.encode_chunk(frame, quality=70)
            finally:
                cap.release()
            time.sleep(0.15)

    return StreamingResponse(
        _track_legacy_mjpeg_stream(
            generate_direct(),
            _legacy_mjpeg_record("direct_capture"),
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/api/cameras/assign")
def assign_cameras(assignment: CameraAssignment) -> Dict[str, Any]:
    """Save camera role assignments to the machine TOML config."""
    params_path, config = _read_machine_params_config()

    # Update cameras section
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict):
        cameras = {}
    updates = assignment.model_dump(exclude_unset=True)
    layout = updates.pop("layout", None)
    if layout is not None:
        if layout not in {"default", "split_feeder"}:
            raise HTTPException(
                status_code=400,
                detail="layout must be 'default' or 'split_feeder'.",
            )
        cameras["layout"] = layout
    elif "layout" not in cameras:
        if "feeder" in updates:
            cameras["layout"] = "default"
        elif any(role in updates for role in ("c_channel_2", "c_channel_3", "carousel", "classification_channel")):
            cameras["layout"] = "split_feeder"
    for key, value in updates.items():
        if value is None:
            cameras.pop(key, None)
        else:
            cameras[key] = value
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live: Dict[str, bool] = {}
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setCameraSourceForRole"):
        for key, value in updates.items():
            try:
                applied_live[key] = bool(shared_state.vision_manager.setCameraSourceForRole(key, value))
            except Exception:
                applied_live[key] = False

    assignment = {
        "layout": cameras.get("layout", "default"),
        "feeder": cameras.get("feeder"),
        "c_channel_2": cameras.get("c_channel_2"),
        "c_channel_3": cameras.get("c_channel_3"),
        "classification_channel": cameras.get("classification_channel"),
        "carousel": cameras.get("carousel"),
        "classification_top": cameras.get("classification_top"),
        "classification_bottom": cameras.get("classification_bottom"),
    }
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


# ---------------------------------------------------------------------------
# Picture settings
# ---------------------------------------------------------------------------


@router.get("/api/cameras/picture-settings/{role}")
def get_camera_picture_settings(role: str) -> Dict[str, Any]:
    """Return persisted picture settings for a camera role."""
    _, config = _read_machine_params_config()
    return {
        "role": role,
        "settings": _picture_settings_for_role(config, role),
    }


@router.post("/api/cameras/picture-settings/{role}")
def save_camera_picture_settings(
    role: str,
    payload: CameraPictureSettingsPayload,
) -> Dict[str, Any]:
    """Save and live-apply picture settings for a camera role when possible."""
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    params_path, config = _read_machine_params_config()
    picture_settings = _get_picture_settings_table(config)
    parsed = parseCameraPictureSettings(payload.model_dump())
    picture_settings[role] = cameraPictureSettingsToDict(parsed)
    config["camera_picture_settings"] = picture_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live = False
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setPictureSettingsForRole"):
        try:
            applied_live = bool(shared_state.vision_manager.setPictureSettingsForRole(role, parsed))
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "settings": cameraPictureSettingsToDict(parsed),
        "applied_live": applied_live,
        "message": "Feed orientation saved.",
    }


# ---------------------------------------------------------------------------
# Live histogram
# ---------------------------------------------------------------------------

_HISTOGRAM_BINS = 64


@router.get("/api/cameras/{role}/histogram")
def get_camera_histogram(role: str) -> Dict[str, Any]:
    """Return live RGB histogram (64 bins)."""
    frame = _grab_live_frame(role, after_timestamp=0.0, timeout=0.3)
    if frame is None:
        return {
            "ok": True,
            "waiting": True,
            "bins": _HISTOGRAM_BINS,
            "r": [],
            "g": [],
            "b": [],
        }

    # Downsample large frames for speed
    h, w = frame.shape[:2]
    if h * w > 640 * 480:
        scale = (640 * 480 / (h * w)) ** 0.5
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    bins = _HISTOGRAM_BINS
    bin_edges = np.linspace(0, 256, bins + 1)

    channels: Dict[str, list] = {}
    for idx, ch_name in enumerate(("b", "g", "r")):
        hist = cv2.calcHist([frame], [idx], None, [bins], [0, 256]).flatten()
        peak = float(hist.max()) if hist.max() > 0 else 1.0
        channels[ch_name] = (hist / peak).tolist()

    return {
        "ok": True,
        "waiting": False,
        "bins": bins,
        **channels,
    }


# ---------------------------------------------------------------------------
# Device settings
# ---------------------------------------------------------------------------


@router.get("/api/cameras/device-settings/{role}")
def get_camera_device_settings(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "provider": "none",
            "settings": {},
            "controls": [],
            "supported": False,
            "message": "No camera is assigned to this role.",
        }

    if isinstance(source, str):
        try:
            android_data = _android_camera_request(source, "/camera-settings")
        except HTTPException as exc:
            return {
                "ok": True,
                "role": role,
                "source": source,
                "provider": "network-stream",
                "settings": {},
                "controls": [],
                "supported": False,
                "message": str(exc.detail),
            }

        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": android_data.get("provider", "android-camera-app"),
            "settings": android_data.get("settings", {}),
            "capabilities": android_data.get("capabilities", {}),
            "controls": [],
            "supported": True,
        }

    saved_settings = cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(_get_camera_device_settings_table(config).get(role))
    )
    controls, live_settings = _camera_service_usb_device_controls(role, source, saved_settings)
    current_settings = live_settings or saved_settings
    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": current_settings,
        "controls": controls,
        "supported": bool(controls),
        "message": (
            "Real USB camera controls are available for this camera."
            if controls
            else (
                "This USB camera does not expose adjustable UVC controls on this macOS setup."
                if platform.system() == "Darwin"
                else "This USB camera does not expose adjustable controls through the current capture backend."
            )
        ),
    }


@router.post("/api/cameras/device-settings/{role}/preview")
def preview_camera_device_settings(role: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        proxied = _android_camera_request(
            source,
            "/camera-settings/preview",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": False,
            "applied_live": True,
        }

    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    shared_state.camera_device_preview_overrides[role] = dict(parsed)
    applied_settings, applied_live = _apply_live_usb_device_settings(role, parsed, persist=False)
    shared_state.camera_device_preview_overrides[role] = dict(applied_settings)

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "persisted": False,
        "applied_live": applied_live,
    }


@router.post("/api/cameras/device-settings/{role}")
def save_camera_device_settings(role: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        proxied = _android_camera_request(
            source,
            "/camera-settings",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": True,
            "applied_live": True,
        }

    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    device_settings = _get_camera_device_settings_table(config)
    if parsed:
        device_settings[role] = dict(parsed)
    else:
        device_settings.pop(role, None)
    config["camera_device_settings"] = device_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    shared_state.camera_device_preview_overrides[role] = dict(parsed)
    applied_settings, applied_live = _apply_live_usb_device_settings(role, parsed, persist=True)
    shared_state.camera_device_preview_overrides[role] = dict(applied_settings)

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "persisted": True,
        "applied_live": applied_live,
        "message": "Camera device settings saved.",
    }


@router.post("/api/cameras/device-settings/{role}/reset-defaults")
def reset_camera_device_settings_to_defaults(role: str) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        payload = {
            "exposure_compensation": 0,
            "ae_lock": False,
            "awb_lock": False,
            "white_balance_mode": "auto",
            "processing_mode": "standard",
        }
        proxied = _android_camera_request(
            source,
            "/camera-settings",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": True,
            "applied_live": True,
            "message": "Camera settings reset to defaults.",
        }

    controls, _ = _camera_service_usb_device_controls(role, source, {})
    default_settings = _default_camera_device_settings_from_controls(controls)

    device_settings = _get_camera_device_settings_table(config)
    device_settings.pop(role, None)
    config["camera_device_settings"] = device_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    shared_state.camera_device_preview_overrides.pop(role, None)
    applied_settings, applied_live = _apply_live_usb_device_settings(role, default_settings, persist=False)
    svc = shared_state.camera_service
    if svc is not None and hasattr(svc, "clear_persisted_device_settings_for_role"):
        try:
            svc.clear_persisted_device_settings_for_role(role)
        except Exception:
            pass

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "controls": controls,
        "persisted": False,
        "applied_live": applied_live,
        "message": "Camera settings reset to defaults.",
    }


def _latest_frame_sample_for_role(role: str):
    """Newest (BGR frame, wall-clock timestamp) for a role, or None."""
    svc = shared_state.camera_service
    if svc is None:
        return None
    feed = svc.get_feed(role)
    if feed is None:
        _, config = _read_machine_params_config()
        config_role = _camera_config_role_for_role(config, role)
        if config_role != role:
            feed = svc.get_feed(config_role)
    if feed is None:
        return None
    device = getattr(feed, "device", None)
    frame = getattr(device, "latest_frame", None)
    raw = getattr(frame, "raw", None)
    timestamp = getattr(frame, "timestamp", None)
    if raw is None or not getattr(raw, "size", 0) or not isinstance(timestamp, (int, float)):
        return None
    return raw, float(timestamp)


@router.post("/api/cameras/device-settings/{role}/calibrate-picture")
def calibrate_camera_picture(role: str) -> Dict[str, Any]:
    """One-click picture calibration: lock AE/AWB, converge exposure/gain on
    the target brightness and white balance on a neutral scene, then persist
    the result as this role's saved device settings. Run with an empty
    channel — the tray background is the neutral reference.
    """
    from vision.picture_calibration import calibrate_picture

    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if isinstance(source, str):
        raise HTTPException(
            status_code=400,
            detail="Picture calibration is only available for USB cameras.",
        )

    saved_settings = cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(_get_camera_device_settings_table(config).get(role))
    )
    controls, _ = _camera_service_usb_device_controls(role, source, saved_settings)
    if not controls:
        raise HTTPException(
            status_code=400,
            detail="This camera does not expose adjustable device controls.",
        )
    if _latest_frame_sample_for_role(role) is None:
        raise HTTPException(
            status_code=409,
            detail="The camera is not delivering frames; start the feed first.",
        )

    def _apply(settings: Dict[str, int | float | bool]) -> Dict[str, int | float | bool]:
        applied, _ = _apply_live_usb_device_settings(role, settings, persist=False)
        return applied

    report = calibrate_picture(
        controls=controls,
        apply_settings=_apply,
        get_frame=lambda: _latest_frame_sample_for_role(role),
    )

    persisted = False
    if report.ok and report.settings:
        merged = dict(saved_settings)
        merged.update(report.settings)
        parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(merged))
        device_settings = _get_camera_device_settings_table(config)
        device_settings[role] = dict(parsed)
        config["camera_device_settings"] = device_settings
        try:
            _write_machine_params_config(params_path, config)
            persisted = True
        except Exception as exc:
            report.reason = f"Calibrated, but persisting failed: {exc}"
        shared_state.camera_device_preview_overrides[role] = dict(parsed)
        _apply_live_usb_device_settings(role, parsed, persist=True)

    return {
        "ok": report.ok,
        "role": role,
        "source": source,
        "persisted": persisted,
        "report": report.to_dict(),
    }


# ---------------------------------------------------------------------------
# Drift detection (device settings)
# ---------------------------------------------------------------------------


def _device_setting_diff(
    key: str,
    saved_value: Any,
    live_value: Any,
    control: Dict[str, Any] | None,
) -> Dict[str, Any] | None:
    if saved_value is None:
        return None
    if live_value is None:
        return None

    if isinstance(saved_value, bool) or isinstance(live_value, bool):
        if bool(saved_value) == bool(live_value):
            return None
        return {"key": key, "saved": bool(saved_value), "live": bool(live_value), "kind": "boolean"}

    try:
        saved_num = float(saved_value)
        live_num = float(live_value)
    except (TypeError, ValueError):
        return None

    step = 1.0
    tol_pct = 0.01
    if isinstance(control, dict):
        step_raw = control.get("step")
        if isinstance(step_raw, (int, float)) and step_raw > 0:
            step = float(step_raw)
        min_raw = control.get("min")
        max_raw = control.get("max")
        if isinstance(min_raw, (int, float)) and isinstance(max_raw, (int, float)) and max_raw > min_raw:
            tol_pct = max(tol_pct, 0.01 * (float(max_raw) - float(min_raw)))
    tolerance = max(step, abs(saved_num) * 0.01, tol_pct * 0.01)
    if abs(saved_num - live_num) <= tolerance:
        return None
    return {"key": key, "saved": saved_num, "live": live_num, "kind": "number"}


@router.get("/api/cameras/device-settings/{role}/diff")
def get_camera_device_settings_diff(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "supported": False,
            "saved": {},
            "live": {},
            "diffs": [],
            "message": "No camera is assigned to this role.",
        }

    saved_settings = cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(_get_camera_device_settings_table(config).get(role))
    )

    controls: List[Dict[str, Any]] = []
    live_settings: Dict[str, Any] = {}
    if isinstance(source, int):
        controls, live_settings = _camera_service_usb_device_controls(role, source, saved_settings)
    else:
        # Network-stream (Android) — proxied read
        try:
            android_data = _android_camera_request(source, "/camera-settings")
            raw_settings = android_data.get("settings") or {}
            if isinstance(raw_settings, dict):
                live_settings = {k: v for k, v in raw_settings.items() if isinstance(v, (int, float, bool))}
        except HTTPException as exc:
            return {
                "ok": True,
                "role": role,
                "source": source,
                "supported": False,
                "saved": saved_settings,
                "live": {},
                "diffs": [],
                "message": str(exc.detail),
            }

    controls_by_key: Dict[str, Dict[str, Any]] = {}
    for control in controls:
        key = control.get("key")
        if isinstance(key, str):
            controls_by_key[key] = control

    diffs: List[Dict[str, Any]] = []
    keys = set(saved_settings.keys()) | set(live_settings.keys())
    for key in sorted(keys):
        diff = _device_setting_diff(
            key,
            saved_settings.get(key),
            live_settings.get(key),
            controls_by_key.get(key),
        )
        if diff is not None:
            diffs.append(diff)

    return {
        "ok": True,
        "role": role,
        "source": source,
        "supported": bool(controls) or bool(live_settings),
        "saved": saved_settings,
        "live": live_settings,
        "diffs": diffs,
    }


# ---------------------------------------------------------------------------
# Capture modes (resolution / fps)
# ---------------------------------------------------------------------------


def _capture_modes_for_source(source: int | str | None) -> tuple[List[Dict[str, Any]], str]:
    """Return (modes, backend) for a given source. Modes: {width,height,fps,fourcc,label}."""
    if not isinstance(source, int):
        return [], "none"

    common = [
        (640, 480),
        (800, 600),
        (1024, 768),
        (1280, 720),
        (1280, 960),
        (1600, 1200),
        (1920, 1080),
        (2048, 1536),
        (2560, 1440),
        (2592, 1944),
        (3840, 2160),
    ]
    fallback_modes = [
        {"width": w, "height": h, "fps": 30, "fourcc": "MJPG", "native_fourcc": "MJPG"}
        for (w, h) in common
    ]

    if platform.system() == "Darwin":
        try:
            from hardware.macos_camera_modes import list_modes_for_unique_id
            from hardware.macos_camera_registry import refresh_macos_cameras as _refresh

            cam = next((c for c in _refresh() if c.index == source), None)
            unique_id = cam.path if (cam is not None and isinstance(cam.path, str)) else None
            if unique_id:
                modes = list_modes_for_unique_id(unique_id)
                if modes:
                    return (
                        [
                            {
                                "width": m.width,
                                "height": m.height,
                                "fps": int(round(m.max_fps)),
                                "fourcc": _avf_to_opencv_fourcc(m.fourcc),
                                "native_fourcc": m.fourcc,
                            }
                            for m in modes
                        ],
                        "avfoundation",
                    )
        except Exception:
            pass

    if platform.system() == "Linux":
        # `source` is the logical camera index used in machine config; the
        # capture layer maps it to the actual /dev/video node. Enumerating
        # modes on the raw index can hit a *different* physical camera and
        # offer resolutions the mapped device cannot deliver.
        from vision.camera import _resolve_linux_video_index

        actual = _resolve_linux_video_index(source)
        v4l2_modes = _list_v4l2_modes(actual if actual is not None else source)
        if v4l2_modes:
            return (v4l2_modes, "v4l2")

    # Fallback: allow common USB modes when format enumeration fails.
    # Some UVC devices still stream fine even when the discovery API
    # returns an empty format list.
    return (fallback_modes, "probe-fallback")


def _list_v4l2_modes(source: int) -> List[Dict[str, Any]]:
    """Enumerate (fourcc, width, height, fps) tuples for /dev/videoN.

    Parses `v4l2-ctl --list-formats-ext` output. Returns one entry per
    unique (fourcc, width, height, fps) combination. Empty list on failure.
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", "--list-formats-ext"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    seen: set[tuple[str, int, int, int]] = set()
    modes: List[Dict[str, Any]] = []
    current_fourcc: str | None = None
    current_size: tuple[int, int] | None = None
    fmt_pat = re.compile(r"\]\s*:\s*'([A-Za-z0-9]{4})'")
    size_pat = re.compile(r"Size:\s*Discrete\s+(\d+)x(\d+)")
    interval_pat = re.compile(r"\(\s*([0-9.]+)\s*fps\s*\)")

    for raw in result.stdout.splitlines():
        line = raw.strip()
        m = fmt_pat.search(line)
        if m:
            current_fourcc = m.group(1).upper()
            current_size = None
            continue
        m = size_pat.search(line)
        if m and current_fourcc is not None:
            current_size = (int(m.group(1)), int(m.group(2)))
            continue
        m = interval_pat.search(line)
        if m and current_fourcc is not None and current_size is not None:
            try:
                fps_val = int(round(float(m.group(1))))
            except ValueError:
                continue
            key = (current_fourcc, current_size[0], current_size[1], fps_val)
            if key not in seen:
                seen.add(key)
                modes.append({
                    "width": current_size[0],
                    "height": current_size[1],
                    "fps": fps_val,
                    "fourcc": current_fourcc,
                    "native_fourcc": current_fourcc,
                })

    return modes


def _avf_to_opencv_fourcc(native: str) -> str | None:
    """AVFoundation subtype -> optional OpenCV fourcc hint.

    AVFoundation often reports uncompressed pixel formats such as ``420v``.
    Forcing those to ``MJPG`` can make OpenCV open the device but never
    deliver frames on cameras like the Logitech StreamCam, so only return a
    hint for real compressed/native OpenCV-style formats.
    """
    normalized = (native or "").strip().upper()
    if normalized in {"MJPG", "MJPEG"}:
        return "MJPG"
    if normalized in {"YUY2", "YUYV"}:
        return "YUYV"
    return None


class CaptureModePayload(BaseModel):
    width: int
    height: int
    fps: int | None = None
    fourcc: str | None = None


@router.get("/api/cameras/capture-modes/{role}")
def get_camera_capture_modes(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
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

    modes, backend = _capture_modes_for_source(source)
    svc = shared_state.camera_service
    current: Dict[str, Any] | None = None
    if svc is not None and hasattr(svc, "get_capture_mode_for_role"):
        current = svc.get_capture_mode_for_role(role)
    if current is None:
        saved_section = config.get("camera_capture_modes", {}) if isinstance(config.get("camera_capture_modes"), dict) else {}
        saved_entry = saved_section.get(role) if isinstance(saved_section, dict) else None
        current = _normalized_capture_mode_entry(saved_entry)

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

    if current is None and live is None:
        current = _preferred_capture_mode(modes)

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
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    if payload.width <= 0 or payload.height <= 0:
        raise HTTPException(status_code=400, detail="Width and height must be positive.")

    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if not isinstance(source, int):
        raise HTTPException(status_code=400, detail="Resolution selection requires a USB camera.")

    modes, _ = _capture_modes_for_source(source)
    matching_modes = [
        m
        for m in modes
        if m["width"] == payload.width
        and m["height"] == payload.height
        and (payload.fps is None or int(m.get("fps") or 0) == int(payload.fps))
    ]
    if not matching_modes:
        matching_modes = [
            m for m in modes if m["width"] == payload.width and m["height"] == payload.height
        ]
    if not matching_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Resolution {payload.width}x{payload.height} is not supported by this camera.",
        )

    preferred_mode = next(
        (m for m in matching_modes if str(m.get("fourcc") or "").upper() == "MJPG"),
        matching_modes[0],
    )
    fps = int(payload.fps) if payload.fps else int(preferred_mode["fps"])
    raw_fourcc = payload.fourcc if payload.fourcc is not None else preferred_mode.get("fourcc")
    fourcc = raw_fourcc.strip().upper()[:4] if isinstance(raw_fourcc, str) and raw_fourcc.strip() else None

    entry: Dict[str, Any] = {"width": int(payload.width), "height": int(payload.height), "fps": fps}
    if fourcc:
        entry["fourcc"] = fourcc
    capture_modes = config.get("camera_capture_modes", {})
    if not isinstance(capture_modes, dict):
        capture_modes = {}
    capture_modes[role] = entry
    config["camera_capture_modes"] = capture_modes

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

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
