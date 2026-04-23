"""Channel-scoped config readers used at rt bootstrap and rebuild.

Maps rt role slugs (``"c2"`` / ``"c3"`` / ``"c4"``) to the legacy
camera-service role names and to the polygon / arc-param blob keys the
UI writes, then exposes readers for:

- the saved perception polygon (scaled to the target frame resolution)
- the saved polar tracker geometry (same scaling)
- the device-configured capture resolution

Pure readers — no side effects, no runtime state. Every function takes
enough context (role, camera_service, …) to answer on its own.
"""

from __future__ import annotations

from typing import Any

from utils.polygon_resolution import saved_polygon_resolution


# Mapping rt-side role slug -> legacy camera_service role name.
ROLE_TO_LEGACY_CAMERA: dict[str, str] = {
    "c2": "c_channel_2",
    "c3": "c_channel_3",
    "c4": "carousel",
}


def channel_polygon_key_for_role(role: str) -> str | None:
    """Translate a legacy camera role to its ``channel_polygons`` blob key."""
    if role == "c_channel_2":
        return "second_channel"
    if role == "c_channel_3":
        return "third_channel"
    if role == "carousel":
        return "classification_channel"
    return None


def channel_angle_key_for_polygon_key(polygon_key: str) -> str | None:
    """Translate a polygon blob key to its arc-params blob key."""
    if polygon_key == "second_channel":
        return "second"
    if polygon_key == "third_channel":
        return "third"
    if polygon_key == "classification_channel":
        return "classification_channel"
    return None


def arc_params_key_for_role(role: str) -> str | None:
    """Translate an rt role slug directly to its arc-params blob key."""
    legacy_role = ROLE_TO_LEGACY_CAMERA.get(role, role)
    if legacy_role == "c_channel_2":
        return "second"
    if legacy_role == "c_channel_3":
        return "third"
    if legacy_role in {"carousel", "classification_channel"}:
        return "classification_channel"
    return None


def saved_resolution_for_channel(saved: dict, channel_key: str | None) -> list:
    """Return the capture resolution a polygon was saved at.

    Light wrapper so callers stay simple while the resolution lookup logic
    lives in one shared place.
    """
    return list(saved_polygon_resolution(saved, channel_key=channel_key))


def load_saved_polygon(key: str, target_w: int, target_h: int) -> Any:
    """Read + scale a polygon from ``blob_manager.getChannelPolygons()``."""
    import numpy as np  # local — keeps module import fast

    try:
        from blob_manager import getChannelPolygons
    except Exception:
        return None
    saved = getChannelPolygons()
    if not isinstance(saved, dict):
        return None
    polygon_data = saved.get("polygons") or {}
    pts = polygon_data.get(key)
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    channel_key_for_res = channel_angle_key_for_polygon_key(key) or key
    saved_res = saved_resolution_for_channel(saved, channel_key_for_res)
    try:
        src_w, src_h = int(saved_res[0]), int(saved_res[1])
    except (TypeError, ValueError):
        return None
    if src_w <= 0 or src_h <= 0:
        return None
    sx = float(target_w) / float(src_w)
    sy = float(target_h) / float(src_h)
    try:
        return np.array(
            [[float(p[0]) * sx, float(p[1]) * sy] for p in pts],
            dtype=np.int32,
        )
    except (TypeError, ValueError):
        return None


def load_arc_tracker_params(
    role: str,
    *,
    target_w: int,
    target_h: int,
) -> dict[str, Any]:
    """Load scaled polar geometry for the tracker from channel arc params.

    Arc channels keep two distinct concerns:
    - polygon zone: mask / crop / overlay
    - polar geometry: center + radius range for angle-aware tracking

    The UI already stores both in the channel_polygons blob; bootstrap
    must carry both into the perception pipeline.
    """
    try:
        from blob_manager import getChannelPolygons
    except Exception:
        return {}
    saved = getChannelPolygons()
    if not isinstance(saved, dict):
        return {}
    arc_params = saved.get("arc_params")
    if not isinstance(arc_params, dict):
        return {}
    channel_key = arc_params_key_for_role(role)
    if channel_key is None:
        return {}
    raw = arc_params.get(channel_key)
    if not isinstance(raw, dict):
        return {}
    center = raw.get("center")
    try:
        center_x = float(center[0])
        center_y = float(center[1])
        inner_radius = float(raw["inner_radius"])
        outer_radius = float(raw["outer_radius"])
    except Exception:
        return {}
    if inner_radius < 0.0 or outer_radius <= inner_radius:
        return {}
    saved_res = saved_resolution_for_channel(saved, channel_key)
    try:
        src_w, src_h = int(saved_res[0]), int(saved_res[1])
    except (TypeError, ValueError):
        return {}
    if src_w <= 0 or src_h <= 0:
        return {}
    sx = float(target_w) / float(src_w)
    sy = float(target_h) / float(src_h)
    radius_scale = (abs(sx) + abs(sy)) / 2.0
    return {
        "polar_center": (center_x * sx, center_y * sy),
        "polar_radius_range": (
            inner_radius * radius_scale,
            outer_radius * radius_scale,
        ),
    }


def configured_resolution_for_role(
    camera_service: Any,
    legacy_role: str,
) -> tuple[int, int] | None:
    """Resolve ``(width, height)`` from the device config — no frame needed.

    Returns ``None`` only if the camera_service has no device for the role,
    or if the device has no configured capture resolution. Falls back to
    a live frame probe as a last resort for test harnesses that don't
    wire a real device graph.
    """
    w: int | None = None
    h: int | None = None

    get_device = getattr(camera_service, "get_device", None)
    if callable(get_device):
        try:
            device = get_device(legacy_role)
        except Exception:
            device = None
        config = getattr(device, "config", None) if device is not None else None
        cfg_w = getattr(config, "width", None)
        cfg_h = getattr(config, "height", None)
        if isinstance(cfg_w, int) and isinstance(cfg_h, int) and cfg_w > 0 and cfg_h > 0:
            w, h = cfg_w, cfg_h

    if w is None or h is None:
        # Fallback: probe the latest frame. Only exercised in tests or on
        # exotic setups where the device doesn't expose a config object.
        get_capture = getattr(camera_service, "get_capture_thread_for_role", None)
        if callable(get_capture):
            try:
                capture = get_capture(legacy_role)
            except Exception:
                capture = None
            frame = getattr(capture, "latest_frame", None) if capture is not None else None
            raw = getattr(frame, "raw", None)
            if raw is not None and hasattr(raw, "shape"):
                h, w = int(raw.shape[0]), int(raw.shape[1])

    if w is None or h is None:
        return None
    return int(w), int(h)


__all__ = [
    "ROLE_TO_LEGACY_CAMERA",
    "arc_params_key_for_role",
    "channel_angle_key_for_polygon_key",
    "channel_polygon_key_for_role",
    "configured_resolution_for_role",
    "load_arc_tracker_params",
    "load_saved_polygon",
    "saved_resolution_for_channel",
]
