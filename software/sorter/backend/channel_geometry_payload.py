from __future__ import annotations

from typing import Any

from perception.channel import CHANNEL_REGISTRY, REVERSE_TRAVEL_CHANNELS

# source_role -> (saved-polygon key, channel_angles/arc_params key, channel_id),
# derived from the single source of truth in perception.channel. C4 is filmed by
# the carousel camera (role "carousel") but is also addressable by its own role
# name in some capture paths, so alias classification_channel to the same keys.
_ROLE_TO_KEYS: dict[str, tuple[str, str, int]] = {
    role: (poly_key, angle_key, ch_id)
    for ch_id, (role, poly_key, angle_key) in CHANNEL_REGISTRY.items()
}
_ROLE_TO_KEYS.setdefault("classification_channel", ("classification_channel", "classification_channel", 4))

_ZONE_WIRE = (("drop", "drop_zone"), ("exit", "exit_zone"), ("precise", "precise_zone"))


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _point_list(raw: Any) -> list[list[float]] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    out: list[list[float]] = []
    for point in raw:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            x = _num(point[0])
            y = _num(point[1])
            if x is not None and y is not None:
                out.append([x, y])
    return out or None


def buildChannelGeometryForRole(role: str) -> dict[str, Any] | None:
    # The channel-region geometry the user defined for this source_role, in the
    # wire shape Hive parses into sample_channel_geometry: mask polygon +
    # annulus/arc model. Reads the live channel_polygons blob so a recalibration
    # is reflected on the next sample (per-sample geometry, no versioning).
    keys = _ROLE_TO_KEYS.get(role)
    if keys is None:
        return None
    poly_key, angle_key, channel_id = keys

    from blob_manager import getChannelPolygons

    blob = getChannelPolygons() or {}
    polygons = blob.get("polygons") or {}
    channel_angles = blob.get("channel_angles") or {}
    arc_params = blob.get("arc_params") or {}

    arc = arc_params.get(poly_key)
    if not isinstance(arc, dict):
        arc = arc_params.get(angle_key)
    if not isinstance(arc, dict):
        arc = {}

    polygon = _point_list(polygons.get(poly_key))

    frame_width = frame_height = None
    resolution = arc.get("resolution")
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        frame_width = _num(resolution[0])
        frame_height = _num(resolution[1])

    center_out = None
    center = arc.get("center")
    if isinstance(center, (list, tuple)) and len(center) == 2:
        cx = _num(center[0])
        cy = _num(center[1])
        if cx is not None and cy is not None:
            center_out = [cx, cy]

    arc_zones: list[dict[str, Any]] = []
    for zone_type, zone_key in _ZONE_WIRE:
        raw_zone = arc.get(zone_key)
        if not isinstance(raw_zone, dict):
            continue
        arc_zones.append(
            {
                "zone_type": zone_type,
                "start_outer_angle": _num(raw_zone.get("start_outer_angle", raw_zone.get("start_angle"))),
                "end_outer_angle": _num(raw_zone.get("end_outer_angle", raw_zone.get("end_angle"))),
                "start_inner_angle": _num(raw_zone.get("start_inner_angle")),
                "end_inner_angle": _num(raw_zone.get("end_inner_angle")),
            }
        )

    geometry: dict[str, Any] = {
        "source_role": role,
        "frame_width": int(frame_width) if frame_width else None,
        "frame_height": int(frame_height) if frame_height else None,
        "polygon": polygon,
        "center": center_out,
        "inner_radius": _num(arc.get("inner_radius")),
        "outer_radius": _num(arc.get("outer_radius")),
        "exit_outer_radius": _num(arc.get("exit_outer_radius")),
        "section_zero_angle_deg": _num(channel_angles.get(angle_key)),
        "reverse": channel_id in REVERSE_TRAVEL_CHANNELS,
        "arc_zones": arc_zones,
    }

    if polygon is None and center_out is None and geometry["outer_radius"] is None:
        return None
    return geometry
