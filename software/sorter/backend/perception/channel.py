"""Immutable per-channel definition consumed by the perception package.

A `ChannelDef` is built once at boot from the saved polygon blob and a few
config dicts. It carries everything an `InferenceWorker` needs to turn a
bbox into (`in_drop`, `in_exit`): the polygon mask the bbox must overlap,
the channel's center + reference angle, and the section sets that name the
drop and exit arcs.

This module imports numpy and cv2 only. It does NOT import from
``vision_manager``, ``subsystems.feeder.*``, ``vision.tracking.*``, or
anything else from the legacy stack. The arc-zone parsing is intentionally
re-implemented here from the saved-blob schema rather than reused from
``subsystems.feeder.analysis`` — perception is meant to stand alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import cv2
import numpy as np


# Match the legacy section discretization so saved arcs continue to load
# (360 single-degree sections around the channel center).
SECTION_COUNT = 360
SECTION_DEG = 360.0 / SECTION_COUNT


# Map perception channel_id -> (camera_role, saved-polygon key,
# channel_angles key). The cameras emit `frame.source_id == camera_role`,
# and the saved blob keys come from the existing UI / persistence layer.
CHANNEL_REGISTRY: dict[int, tuple[str, str, str]] = {
    2: ("c_channel_2", "second_channel", "second"),
    3: ("c_channel_3", "third_channel", "third"),
    4: ("carousel", "classification_channel", "classification_channel"),
}


@dataclass(frozen=True)
class ChannelDef:
    channel_id: int
    camera_source_id: str
    center: tuple[float, float]
    radius1_angle_image: float
    mask: np.ndarray
    drop_sections: frozenset[int]
    # ``exit_sections`` unions the exit and precise arcs — this is what the
    # cascade reads as "in_exit" and what gates the precise-pulse decision.
    # ``precise_sections`` is the precise sub-arc on its own, kept separate so
    # callers that need "exit but not precise" (e.g. jitter-unstick dwell) can
    # tell the two apart.
    exit_sections: frozenset[int]
    precise_sections: frozenset[int] = frozenset()

    @property
    def has_zones(self) -> bool:
        return bool(self.drop_sections) and bool(self.exit_sections)


# ---------------------------------------------------------------------------
# Arc-zone parsing (saved-blob schema → drop/exit section sets)
# ---------------------------------------------------------------------------


def _normalize_angle(angle: float) -> float:
    return float(angle) % 360.0


def _section_set_for_arc(
    start_angle: float, end_angle: float, section_zero_angle: float
) -> frozenset[int]:
    """Sections (0..359) that fall inside the arc, expressed relative to the
    channel's section-zero reference angle. Inclusive of start, exclusive of
    end, wraps around 360."""
    start_rel = _normalize_angle(start_angle - section_zero_angle)
    end_rel = _normalize_angle(end_angle - section_zero_angle)
    if start_rel == end_rel:
        return frozenset()
    out: set[int] = set()
    section = int(start_rel // SECTION_DEG)
    end_section = int(end_rel // SECTION_DEG)
    while section != end_section:
        out.add(section % SECTION_COUNT)
        section = (section + 1) % SECTION_COUNT
    return frozenset(out)


def _parse_arc(
    arc_params_entry: Mapping[str, Any] | None, zone_key: str
) -> tuple[float, float] | None:
    if not isinstance(arc_params_entry, Mapping):
        return None
    raw_zone = arc_params_entry.get(zone_key)
    if not isinstance(raw_zone, Mapping):
        return None
    start = raw_zone.get("start_outer_angle", raw_zone.get("start_angle"))
    end = raw_zone.get("end_outer_angle", raw_zone.get("end_angle"))
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return float(start), float(end)


def _parse_arc_center(
    arc_params_entry: Mapping[str, Any] | None,
) -> tuple[float, float] | None:
    """The arc center from the saved blob — the radial pivot the saved angles
    are measured from. THIS is the angle reference, not the polygon centroid.
    The UI's zone overlay (``handdrawn_region_provider._channelMask``) uses
    ``arc.center`` for the exact same reason; perception must match or its
    section→pixel mapping silently drifts."""
    if not isinstance(arc_params_entry, Mapping):
        return None
    raw = arc_params_entry.get("center")
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    cx, cy = raw[0], raw[1]
    if not isinstance(cx, (int, float)) or not isinstance(cy, (int, float)):
        return None
    return float(cx), float(cy)


def _parse_resolution(
    arc_params_entry: Mapping[str, Any] | None,
) -> tuple[float, float] | None:
    """The (width, height) the polygon + arc were drawn against in the UI
    zone editor. The saved pixel coordinates are in this space; perception
    (like ``handdrawn_region_provider._scaleForFrame``) must rescale them to
    the live capture resolution or every zone lands off-frame when the camera
    delivers a different size than the editor used (e.g. zones saved at 4K,
    camera now streaming 720p)."""
    if not isinstance(arc_params_entry, Mapping):
        return None
    raw = arc_params_entry.get("resolution")
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    w, h = raw[0], raw[1]
    if not isinstance(w, (int, float)) or not isinstance(h, (int, float)):
        return None
    if w <= 0 or h <= 0:
        return None
    return float(w), float(h)


# ---------------------------------------------------------------------------
# ChannelDef construction
# ---------------------------------------------------------------------------


def buildChannelDef(
    *,
    channel_id: int,
    polygon: np.ndarray,
    frame_shape: tuple[int, int],
    section_zero_angle: float,
    drop_arc: tuple[float, float] | None,
    exit_arc: tuple[float, float] | None,
    precise_arc: tuple[float, float] | None,
    arc_center: tuple[float, float] | None = None,
    saved_resolution: tuple[float, float] | None = None,
) -> ChannelDef:
    """Pure builder. Used directly by tests; the on-disk loader below is the
    production entry point but defers to this for the actual construction.

    ``arc_center`` is the radial pivot the saved arc start/end angles are
    measured from — the carousel/channel rotation center in image space. The
    UI overlay draws zones using this same point, so passing it here keeps
    perception's section→pixel mapping in lock-step with the UI. If omitted,
    the polygon centroid is used as a fallback (kept for unit tests that
    don't load arc_params), but production callers MUST pass arc_center; an
    empty/missing arc_center on the loader path is logged loudly and is the
    most common silent-drift footgun for this subsystem.

    ``saved_resolution`` is the (width, height) the polygon + arc_center were
    drawn against in the zone editor. When it differs from ``frame_shape`` the
    pixel coordinates are rescaled by ``(frame_w/saved_w, frame_h/saved_h)`` —
    the same transform ``handdrawn_region_provider._scaleForFrame`` applies on
    the legacy preview path. Section angles are resolution-independent, so only
    the polygon mask and the center pivot are scaled. Tests that already pass
    frame-space coordinates omit it and get the identity transform.
    """
    if channel_id not in CHANNEL_REGISTRY:
        raise ValueError(f"unknown perception channel_id={channel_id}")
    camera_source_id, _polygon_key, _angle_key = CHANNEL_REGISTRY[channel_id]

    h, w = frame_shape
    scale_x = scale_y = 1.0
    if saved_resolution is not None:
        saved_w, saved_h = saved_resolution
        if saved_w > 0 and saved_h > 0:
            scale_x = float(w) / float(saved_w)
            scale_y = float(h) / float(saved_h)

    mask = np.zeros((h, w), dtype=np.uint8)
    polygon_centroid: tuple[float, float] | None = None
    if polygon is not None and len(polygon) >= 3:
        scaled_polygon = np.asarray(polygon, dtype=np.float64).copy()
        scaled_polygon[:, 0] *= scale_x
        scaled_polygon[:, 1] *= scale_y
        cv2.fillPoly(mask, [scaled_polygon.astype(np.int32)], 255)
        polygon_centroid = (
            float(np.mean(scaled_polygon[:, 0])),
            float(np.mean(scaled_polygon[:, 1])),
        )
    if arc_center is not None:
        center = (float(arc_center[0]) * scale_x, float(arc_center[1]) * scale_y)
    elif polygon_centroid is not None:
        center = polygon_centroid
    else:
        center = (w / 2.0, h / 2.0)

    drop_sections = (
        _section_set_for_arc(drop_arc[0], drop_arc[1], section_zero_angle)
        if drop_arc is not None
        else frozenset()
    )
    exit_sections = (
        _section_set_for_arc(exit_arc[0], exit_arc[1], section_zero_angle)
        if exit_arc is not None
        else frozenset()
    )
    precise_sections = (
        _section_set_for_arc(precise_arc[0], precise_arc[1], section_zero_angle)
        if precise_arc is not None
        else frozenset()
    )

    return ChannelDef(
        channel_id=channel_id,
        camera_source_id=camera_source_id,
        center=(float(center[0]), float(center[1])),
        radius1_angle_image=float(section_zero_angle),
        mask=mask,
        drop_sections=drop_sections,
        exit_sections=exit_sections | precise_sections,
        precise_sections=precise_sections,
    )


def channelDefFromBlob(
    channel_id: int,
    *,
    saved_polygons: Mapping[str, np.ndarray],
    channel_angles: Mapping[str, float],
    arc_params: Mapping[str, Mapping[str, Any]],
    frame_shape: tuple[int, int] | None,
) -> ChannelDef | None:
    """Build one channel's ChannelDef from the saved blobs, or ``None`` when
    the polygon or the live frame shape is unavailable.

    Single-channel entry point shared by the boot loader (``loadChannelDefs``)
    and the runtime reconciler in ``service.py`` — both must produce identical
    defs so a channel rewired live matches one wired at boot.
    """
    if channel_id not in CHANNEL_REGISTRY:
        return None
    _camera_source_id, polygon_key, angle_key = CHANNEL_REGISTRY[channel_id]
    polygon = saved_polygons.get(polygon_key)
    if polygon is None or len(polygon) < 3 or frame_shape is None:
        return None
    section_zero_angle = float(channel_angles.get(angle_key, 0.0))
    arc_entry = arc_params.get(polygon_key) or arc_params.get(angle_key)
    return buildChannelDef(
        channel_id=channel_id,
        polygon=np.asarray(polygon),
        frame_shape=frame_shape,
        section_zero_angle=section_zero_angle,
        drop_arc=_parse_arc(arc_entry, "drop_zone"),
        exit_arc=_parse_arc(arc_entry, "exit_zone"),
        precise_arc=_parse_arc(arc_entry, "precise_zone"),
        arc_center=_parse_arc_center(arc_entry),
        saved_resolution=_parse_resolution(arc_entry),
    )


def loadChannelDefs(
    *,
    saved_polygons: Mapping[str, np.ndarray],
    channel_angles: Mapping[str, float],
    arc_params: Mapping[str, Mapping[str, Any]],
    frame_shape_by_role: Mapping[str, tuple[int, int]],
) -> dict[int, ChannelDef]:
    """Build a ChannelDef per registered perception channel.

    Inputs are the same three blobs the legacy code reads from
    ``local_state`` / ``blob_manager``:
    - ``saved_polygons``  → keys like ``"second_channel"`` / ``"third_channel"``
                             / ``"classification_channel"``
    - ``channel_angles``  → keys ``"second"`` / ``"third"`` / ``"classification_channel"``
    - ``arc_params``      → per-channel dict with ``"drop_zone"`` / ``"exit_zone"``

    A channel is included in the output dict only when its polygon AND its
    frame shape are present. Missing arcs → empty section sets (perception
    will report ``in_drop=False, in_exit=False`` for every detection; the
    cascade will treat the channel as always-clear). The test suite has a
    regression guard against silently running with empty section sets.
    """
    out: dict[int, ChannelDef] = {}
    for channel_id, (camera_source_id, _polygon_key, _angle_key) in CHANNEL_REGISTRY.items():
        cd = channelDefFromBlob(
            channel_id,
            saved_polygons=saved_polygons,
            channel_angles=channel_angles,
            arc_params=arc_params,
            frame_shape=frame_shape_by_role.get(camera_source_id),
        )
        if cd is not None:
            out[channel_id] = cd
    return out
