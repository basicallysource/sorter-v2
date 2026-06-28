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
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

# Lone exception to the standalone rule above: the C4 travel-direction flag is a
# pure boolean shared with the feeder/SM sites so all three can never disagree.
# defs.consts is a neutral pure-constant leaf, not the legacy stack.
from defs.consts import CLASSIFICATION_CHANNEL_CLOCKWISE


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


# Zone-type vocabulary for secondary zones. A secondary zone is a labeled
# polygon a camera sees that belongs to ANOTHER channel (e.g. the carousel
# camera can see C3's exit). It is display-/tag-only: it never feeds into the
# primary ``mask`` or the arc section sets the cascade reads, so the subsystem
# keeps acting on its own channel exactly as before.
SECONDARY_ZONE_TYPES: frozenset[str] = frozenset({"drop", "exit", "precise"})


# Channels whose piece travel runs REVERSE (decreasing relative angle / negative
# motor degrees) toward the exit instead of forward. C4 (the carousel
# classification channel) reverse-converges a piece a short distance to the
# precise zone and then into the fall-off; C2/C3 feeder ejects stay forward. The
# flag rides on ChannelDef so the forward-distance arc math (``arcs.py``) and the
# eject/discharge consumers stay per-channel — see ``arcs._leadingExitApproach``.
# C4 travels reverse only in the counter-clockwise build; clockwise makes it
# forward like C2/C3. Driven by the single source of truth in defs.consts.
REVERSE_TRAVEL_CHANNELS: frozenset[int] = (
    frozenset() if CLASSIFICATION_CHANNEL_CLOCKWISE else frozenset({4})
)


@dataclass(frozen=True)
class SecondaryZone:
    """A foreign channel's zone, annotated in THIS camera's frame.

    ``mask`` is the filled polygon at the live capture resolution (already
    rescaled from the editor resolution, same transform as the primary
    polygon). Membership is a single center-in-mask index — no arc/section
    math, since a foreign zone projected into this camera does not share this
    channel's rotation center."""

    id: str
    source_channel: int
    zone_type: str
    mask: np.ndarray


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
    # Foreign zones this camera observes — display/tag only, never acted on.
    secondary_zones: tuple[SecondaryZone, ...] = ()
    # When True the piece travels REVERSE (decreasing relative angle) toward the
    # exit, so the forward-distance arc math measures the gap to the FAR edge of
    # the exit-only arc instead of the near edge (see ``arcs._leadingExitApproach``).
    # Set per channel from ``REVERSE_TRAVEL_CHANNELS``; C2/C3 stay forward.
    reverse: bool = False

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
# Secondary-zone parsing (host-keyed blob → filled masks)
# ---------------------------------------------------------------------------


def _build_secondary_zones(
    zone_entries: Sequence[Mapping[str, Any]] | None,
    *,
    frame_shape: tuple[int, int],
    scale_x: float,
    scale_y: float,
) -> tuple[SecondaryZone, ...]:
    """Turn the saved per-host list of ``{id, source_channel, zone_type,
    points}`` into filled-mask ``SecondaryZone`` objects, rescaling the polygon
    pixels by the SAME (scale_x, scale_y) the primary polygon uses so a zone
    drawn at editor resolution lands on the right pixels at capture resolution.
    Malformed / degenerate entries are skipped rather than raising."""
    if not zone_entries:
        return ()
    h, w = frame_shape
    out: list[SecondaryZone] = []
    for idx, entry in enumerate(zone_entries):
        if not isinstance(entry, Mapping):
            continue
        points = entry.get("points")
        if not isinstance(points, (list, tuple)) or len(points) < 3:
            continue
        try:
            poly = np.asarray(points, dtype=np.float64).reshape(-1, 2).copy()
        except Exception:
            continue
        poly[:, 0] *= scale_x
        poly[:, 1] *= scale_y
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
        zone_type = str(entry.get("zone_type") or "exit")
        if zone_type not in SECONDARY_ZONE_TYPES:
            zone_type = "exit"
        try:
            source_channel = int(entry.get("source_channel"))
        except (TypeError, ValueError):
            source_channel = 0
        zone_id = str(entry.get("id") or f"sz_{source_channel}_{zone_type}_{idx}")
        out.append(
            SecondaryZone(
                id=zone_id,
                source_channel=source_channel,
                zone_type=zone_type,
                mask=mask,
            )
        )
    return tuple(out)


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
    secondary_zone_entries: Sequence[Mapping[str, Any]] | None = None,
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

    secondary_zones = _build_secondary_zones(
        secondary_zone_entries,
        frame_shape=(h, w),
        scale_x=scale_x,
        scale_y=scale_y,
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
        secondary_zones=secondary_zones,
        reverse=channel_id in REVERSE_TRAVEL_CHANNELS,
    )


def channelDefFromBlob(
    channel_id: int,
    *,
    saved_polygons: Mapping[str, np.ndarray],
    channel_angles: Mapping[str, float],
    arc_params: Mapping[str, Mapping[str, Any]],
    frame_shape: tuple[int, int] | None,
    secondary_zones: Mapping[str, Any] | None = None,
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
    secondary_entries = None
    if isinstance(secondary_zones, Mapping):
        raw = secondary_zones.get(polygon_key)
        if isinstance(raw, (list, tuple)):
            secondary_entries = raw
    # The classification channel travels the WHOLE ring; its saved freeform polygon
    # is an unreliable partial wedge (measured ~48% — half the ring wrongly filtered
    # out). Build its on-channel region from the SAME arc crop the dashboard uses
    # (subsystems.feeder.analysis.channelArcCropPolygon): the forward arc from the
    # drop zone to the end of the exit, with the lowered-radius exit cutout dropped
    # — i.e. ~95% of the ring, only the small output-guide slice removed.
    if polygon_key == "classification_channel":
        try:
            from subsystems.feeder.analysis import (
                channelArcCropPolygon,
                parseSavedChannelArcZones,
            )

            _zones = parseSavedChannelArcZones(
                polygon_key, dict(channel_angles), dict(arc_params)
            )
            if _zones is not None:
                polygon = channelArcCropPolygon(_zones)
                _span = (_zones.exit_end_angle - _zones.drop_start_angle) % 360.0
                print(
                    f"[perception] classification-channel crop = {_span / 360.0 * 100:.0f}% of "
                    f"the ring arc kept (arc {_span:.0f}deg, exit cutout dropped)"
                )
        except Exception as _exc:  # noqa: BLE001 — fall back to the saved polygon
            print(f"[perception] classification arc-crop failed, using saved polygon: {_exc}")
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
        secondary_zone_entries=secondary_entries,
    )


def loadChannelDefs(
    *,
    saved_polygons: Mapping[str, np.ndarray],
    channel_angles: Mapping[str, float],
    arc_params: Mapping[str, Mapping[str, Any]],
    frame_shape_by_role: Mapping[str, tuple[int, int]],
    secondary_zones: Mapping[str, Any] | None = None,
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
            secondary_zones=secondary_zones,
        )
        if cd is not None:
            out[channel_id] = cd
    return out
