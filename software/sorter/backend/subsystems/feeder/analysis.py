from dataclasses import dataclass
from typing import Any, Dict, Tuple
import numpy as np

from defs.consts import (
    CHANNEL_SECTION_DEG,
    CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
    CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
    CLASSIFICATION_CHANNEL_CLOCKWISE,
)
from defs.channel import PolygonChannel


@dataclass(frozen=True)
class ChannelArcZones:
    center: Tuple[float, float]
    inner_radius: float
    outer_radius: float
    exit_outer_radius: float
    drop_start_angle: float
    drop_end_angle: float
    drop_start_inner_angle: float
    drop_end_inner_angle: float
    wait_start_angle: float | None
    wait_end_angle: float | None
    exit_start_angle: float
    exit_end_angle: float
    exit_start_inner_angle: float
    exit_end_inner_angle: float
    # The precise zone is an arc adjacent to the exit. It is stored and rendered
    # separately (it has no exit-style outer-radius cut), but everything that
    # reads "the exit" as a section set unions it with the exit arc — see
    # ``zoneSectionsForChannel``. ``None`` (or zero width) when not configured,
    # in which case the union is just the exit arc and behavior is unchanged.
    precise_start_angle: float | None = None
    precise_end_angle: float | None = None
    # Counterclockwise channels (the classification carousel) travel from the
    # exit side back to the drop side, so the crop must sweep exit_start ->
    # drop_end instead of drop_start -> exit_end. See ``channelArcCropPolygon``.
    ccw: bool = False


def normalizeAngle(angle: float) -> float:
    return (float(angle) % 360.0 + 360.0) % 360.0


def positiveAngleSpan(start_angle: float, end_angle: float) -> float:
    span = (normalizeAngle(end_angle) - normalizeAngle(start_angle) + 360.0) % 360.0
    return span if span > 0.0 else 360.0


def _angleWithinSpan(angle: float, start_angle: float, span: float) -> bool:
    rel = (normalizeAngle(angle) - normalizeAngle(start_angle) + 360.0) % 360.0
    return rel < span or abs(rel - span) < 1e-6


def sectionsForAngleRange(
    start_angle: float,
    end_angle: float,
    section_zero_angle: float,
) -> set[int]:
    span = positiveAngleSpan(start_angle, end_angle)
    sections: set[int] = set()
    for section in range(int(round(360.0 / CHANNEL_SECTION_DEG))):
        mid_angle = normalizeAngle(section_zero_angle + (section + 0.5) * CHANNEL_SECTION_DEG)
        if _angleWithinSpan(mid_angle, start_angle, span):
            sections.add(section)
    return sections


def legacyChannelZoneSections(channel_id: int) -> tuple[set[int], set[int]]:
    if channel_id == 3:
        return set(CH3_DROPZONE_SECTIONS), set(CH3_PRECISE_SECTIONS)
    if channel_id == 2:
        return set(CH2_DROPZONE_SECTIONS), set(CH2_PRECISE_SECTIONS)
    return set(), set()


def legacyChannelArcZones(channel_key: str, section_zero_angle: float) -> ChannelArcZones | None:
    if channel_key == "third":
        drop_sections = CH3_DROPZONE_SECTIONS
        exit_sections = CH3_PRECISE_SECTIONS
    elif channel_key == "second":
        drop_sections = CH2_DROPZONE_SECTIONS
        exit_sections = CH2_PRECISE_SECTIONS
    else:
        return None

    return ChannelArcZones(
        center=(0.0, 0.0),
        inner_radius=0.0,
        outer_radius=0.0,
        exit_outer_radius=0.0,
        drop_start_angle=normalizeAngle(section_zero_angle + drop_sections.start * CHANNEL_SECTION_DEG),
        drop_end_angle=normalizeAngle(section_zero_angle + drop_sections.stop * CHANNEL_SECTION_DEG),
        drop_start_inner_angle=normalizeAngle(section_zero_angle + drop_sections.start * CHANNEL_SECTION_DEG),
        drop_end_inner_angle=normalizeAngle(section_zero_angle + drop_sections.stop * CHANNEL_SECTION_DEG),
        wait_start_angle=None,
        wait_end_angle=None,
        exit_start_angle=normalizeAngle(section_zero_angle + exit_sections.start * CHANNEL_SECTION_DEG),
        exit_end_angle=normalizeAngle(section_zero_angle + exit_sections.stop * CHANNEL_SECTION_DEG),
        exit_start_inner_angle=normalizeAngle(section_zero_angle + exit_sections.start * CHANNEL_SECTION_DEG),
        exit_end_inner_angle=normalizeAngle(section_zero_angle + exit_sections.stop * CHANNEL_SECTION_DEG),
    )


def parseSavedChannelArcZones(
    channel_key: str,
    channel_angles: Dict[str, float],
    arc_params: Dict[str, Any] | None,
) -> ChannelArcZones | None:
    section_zero_angle = float(channel_angles.get(channel_key, 0.0))
    raw = arc_params.get(channel_key) if isinstance(arc_params, dict) else None
    if not isinstance(raw, dict):
        return legacyChannelArcZones(channel_key, section_zero_angle)

    center = raw.get("center")
    inner_radius = raw.get("inner_radius")
    outer_radius = raw.get("outer_radius")
    if (
        not isinstance(center, list)
        or len(center) != 2
        or not isinstance(center[0], (int, float))
        or not isinstance(center[1], (int, float))
        or not isinstance(inner_radius, (int, float))
        or not isinstance(outer_radius, (int, float))
    ):
        return legacyChannelArcZones(channel_key, section_zero_angle)

    inner_radius_f = float(inner_radius)
    outer_radius_f = float(outer_radius)

    def _zone_edges(raw_zone: Any) -> tuple[float, float, float, float] | None:
        if not isinstance(raw_zone, dict):
            return None
        start_outer = raw_zone.get("start_outer_angle")
        end_outer = raw_zone.get("end_outer_angle")
        if isinstance(start_outer, (int, float)) and isinstance(end_outer, (int, float)):
            start_outer_norm = normalizeAngle(float(start_outer))
            end_outer_norm = normalizeAngle(float(end_outer))
            start_inner = raw_zone.get("start_inner_angle")
            end_inner = raw_zone.get("end_inner_angle")
            return (
                start_outer_norm,
                end_outer_norm,
                normalizeAngle(float(start_inner)) if isinstance(start_inner, (int, float)) else start_outer_norm,
                normalizeAngle(float(end_inner)) if isinstance(end_inner, (int, float)) else end_outer_norm,
            )

        start_angle = raw_zone.get("start_angle")
        end_angle = raw_zone.get("end_angle")
        if isinstance(start_angle, (int, float)) and isinstance(end_angle, (int, float)):
            start = normalizeAngle(float(start_angle))
            end = normalizeAngle(float(end_angle))
            return start, end, start, end
        return None

    def _zone(zone_key: str, legacy_sections: range) -> tuple[float, float]:
        raw_zone = raw.get(zone_key)
        parsed = _zone_edges(raw_zone)
        if parsed is not None:
            return parsed[0], parsed[1]
        return (
            normalizeAngle(section_zero_angle + legacy_sections.start * CHANNEL_SECTION_DEG),
            normalizeAngle(section_zero_angle + legacy_sections.stop * CHANNEL_SECTION_DEG),
        )

    def _zone_with_inner(zone_key: str, legacy_sections: range) -> tuple[float, float, float, float]:
        parsed = _zone_edges(raw.get(zone_key))
        if parsed is not None:
            return parsed
        start = normalizeAngle(section_zero_angle + legacy_sections.start * CHANNEL_SECTION_DEG)
        end = normalizeAngle(section_zero_angle + legacy_sections.stop * CHANNEL_SECTION_DEG)
        return start, end, start, end

    def _optional_zone(zone_key: str) -> tuple[float, float] | None:
        parsed = _zone_edges(raw.get(zone_key))
        return (parsed[0], parsed[1]) if parsed is not None else None

    exit_outer_raw = raw.get("exit_outer_radius")
    if not isinstance(exit_outer_raw, (int, float)):
        exit_zone_raw = raw.get("exit_zone")
        if isinstance(exit_zone_raw, dict):
            exit_outer_raw = exit_zone_raw.get("outer_radius")
    exit_outer_radius_f = (
        float(exit_outer_raw)
        if isinstance(exit_outer_raw, (int, float))
        else outer_radius_f
    )
    if (
        not np.isfinite(exit_outer_radius_f)
        or exit_outer_radius_f <= inner_radius_f
    ):
        exit_outer_radius_f = outer_radius_f
    exit_outer_radius_f = min(outer_radius_f, max(inner_radius_f + 1.0, exit_outer_radius_f))

    if channel_key == "third":
        legacy_drop = CH3_DROPZONE_SECTIONS
        legacy_exit = CH3_PRECISE_SECTIONS
    elif channel_key == "second":
        legacy_drop = CH2_DROPZONE_SECTIONS
        legacy_exit = CH2_PRECISE_SECTIONS
    else:
        drop_zone = _optional_zone("drop_zone")
        exit_zone = _optional_zone("exit_zone")
        if drop_zone is None or exit_zone is None:
            return None
        wait_zone = _optional_zone("wait_zone")
        precise_zone = _optional_zone("precise_zone")
        drop_zone_edges = _zone_edges(raw.get("drop_zone"))
        exit_zone_edges = _zone_edges(raw.get("exit_zone"))
        if drop_zone_edges is None or exit_zone_edges is None:
            return None
        return ChannelArcZones(
            center=(float(center[0]), float(center[1])),
            inner_radius=inner_radius_f,
            outer_radius=outer_radius_f,
            exit_outer_radius=exit_outer_radius_f,
            drop_start_angle=drop_zone_edges[0],
            drop_end_angle=drop_zone_edges[1],
            drop_start_inner_angle=drop_zone_edges[2],
            drop_end_inner_angle=drop_zone_edges[3],
            wait_start_angle=wait_zone[0] if wait_zone is not None else None,
            wait_end_angle=wait_zone[1] if wait_zone is not None else None,
            exit_start_angle=exit_zone_edges[0],
            exit_end_angle=exit_zone_edges[1],
            exit_start_inner_angle=exit_zone_edges[2],
            exit_end_inner_angle=exit_zone_edges[3],
            precise_start_angle=precise_zone[0] if precise_zone is not None else None,
            precise_end_angle=precise_zone[1] if precise_zone is not None else None,
            ccw=(channel_key == "classification_channel" and not CLASSIFICATION_CHANNEL_CLOCKWISE),
        )

    drop_start, drop_end, drop_start_inner, drop_end_inner = _zone_with_inner("drop_zone", legacy_drop)
    wait_zone = _optional_zone("wait_zone")
    precise_zone = _optional_zone("precise_zone")
    exit_start, exit_end, exit_start_inner, exit_end_inner = _zone_with_inner("exit_zone", legacy_exit)
    return ChannelArcZones(
        center=(float(center[0]), float(center[1])),
        inner_radius=inner_radius_f,
        outer_radius=outer_radius_f,
        exit_outer_radius=exit_outer_radius_f,
        drop_start_angle=drop_start,
        drop_end_angle=drop_end,
        drop_start_inner_angle=drop_start_inner,
        drop_end_inner_angle=drop_end_inner,
        wait_start_angle=wait_zone[0] if wait_zone is not None else None,
        wait_end_angle=wait_zone[1] if wait_zone is not None else None,
        exit_start_angle=exit_start,
        exit_end_angle=exit_end,
        exit_start_inner_angle=exit_start_inner,
        exit_end_inner_angle=exit_end_inner,
        precise_start_angle=precise_zone[0] if precise_zone is not None else None,
        precise_end_angle=precise_zone[1] if precise_zone is not None else None,
        ccw=(channel_key == "classification_channel" and not CLASSIFICATION_CHANNEL_CLOCKWISE),
    )


def angleWithinChannelExit(angle: float, zones: ChannelArcZones) -> bool:
    span = positiveAngleSpan(zones.exit_start_angle, zones.exit_end_angle)
    return _angleWithinSpan(angle, zones.exit_start_angle, span)


def channelOuterRadiusForAngle(angle: float, zones: ChannelArcZones) -> float:
    if zones.exit_outer_radius < zones.outer_radius and angleWithinChannelExit(angle, zones):
        return float(zones.exit_outer_radius)
    return float(zones.outer_radius)


def angularDistance(a: float, b: float) -> float:
    delta = abs(normalizeAngle(a) - normalizeAngle(b))
    return min(delta, 360.0 - delta)


def _polarPoint(
    cx: float,
    cy: float,
    radius: float,
    angle: float,
    radius_scale: float,
) -> list[int]:
    scaled_radius = float(radius) * float(radius_scale)
    angle_rad = np.deg2rad(normalizeAngle(angle))
    return [
        int(round(cx + scaled_radius * np.cos(angle_rad))),
        int(round(cy + scaled_radius * np.sin(angle_rad))),
    ]


def _appendChannelOuterBoundaryPoint(
    points: list[list[int]],
    zones: ChannelArcZones,
    cx: float,
    cy: float,
    angle: float,
    radius_scale: float,
) -> None:
    angle = normalizeAngle(angle)
    has_exit_cut = zones.exit_outer_radius < zones.outer_radius - 1e-6
    if has_exit_cut and angularDistance(angle, zones.exit_start_angle) < 1e-6:
        points.append(_polarPoint(cx, cy, zones.outer_radius, angle, radius_scale))
        points.append(_polarPoint(cx, cy, zones.exit_outer_radius, angle, radius_scale))
        return
    if has_exit_cut and angularDistance(angle, zones.exit_end_angle) < 1e-6:
        points.append(_polarPoint(cx, cy, zones.exit_outer_radius, angle, radius_scale))
        points.append(_polarPoint(cx, cy, zones.outer_radius, angle, radius_scale))
        return
    points.append(_polarPoint(cx, cy, channelOuterRadiusForAngle(angle, zones), angle, radius_scale))


def _appendChannelCropBoundaryPoint(
    points: list[list[int]],
    zones: ChannelArcZones,
    cx: float,
    cy: float,
    angle: float,
    radius_scale: float,
) -> None:
    angle = normalizeAngle(angle)
    has_exit_cut = zones.exit_outer_radius < zones.outer_radius - 1e-6
    if has_exit_cut and angularDistance(angle, zones.exit_start_angle) < 1e-6:
        points.append(_polarPoint(cx, cy, zones.outer_radius, angle, radius_scale))
        points.append(_polarPoint(cx, cy, zones.exit_outer_radius, angle, radius_scale))
        return
    if has_exit_cut and angularDistance(angle, zones.exit_end_angle) < 1e-6:
        # Step back UP to the full radius radially, AT the exit edge — mirror of
        # the step-down at exit_start. Without the second point the boundary
        # climbs to full radius only at the next swept angle, so it slants
        # diagonally instead of running straight out from the center.
        points.append(_polarPoint(cx, cy, zones.exit_outer_radius, angle, radius_scale))
        points.append(_polarPoint(cx, cy, zones.outer_radius, angle, radius_scale))
        return
    points.append(_polarPoint(cx, cy, channelOuterRadiusForAngle(angle, zones), angle, radius_scale))


def channelArcOuterPolygon(
    zones: ChannelArcZones,
    *,
    segment_count: int = 96,
    center: Tuple[float, float] | None = None,
    radius_scale: float = 1.0,
) -> np.ndarray:
    cx, cy = zones.center if center is None else center
    angles = {
        normalizeAngle((360.0 * i) / segment_count)
        for i in range(segment_count)
    }
    angles.add(normalizeAngle(zones.exit_start_angle))
    angles.add(normalizeAngle(zones.exit_end_angle))
    points: list[list[int]] = []
    for angle in sorted(angles):
        _appendChannelOuterBoundaryPoint(points, zones, cx, cy, angle, radius_scale)
    return np.array(points, dtype=np.int32)


def _addBoundaryAngleWithin(
    angles: set[float],
    boundary_angle: float,
    start_angle: float,
    end_angle: float,
) -> None:
    angle = normalizeAngle(boundary_angle)
    start = float(start_angle)
    end = float(end_angle)
    while angle < start - 1e-6:
        angle += 360.0
    while angle <= end + 1e-6:
        angles.add(angle)
        angle += 360.0


def channelArcCropPolygon(
    zones: ChannelArcZones,
    *,
    segment_count: int = 96,
    center: Tuple[float, float] | None = None,
    radius_scale: float = 1.0,
) -> np.ndarray:
    """Return the physical channel surface the piece travels, excluding the arc
    it never crosses.

    Clockwise channels keep ``drop_start -> exit_end`` and crop the output-guide
    opening between exit-end and drop-start. The counterclockwise classification
    carousel travels the other way, so it keeps ``exit_start -> drop_end`` (the
    arc the piece actually crosses) and crops the empty far side instead. The
    operator draws the same zone boundaries either way; ``zones.ccw`` only decides
    which end is the sweep beginning vs end.
    """
    cx, cy = zones.center if center is None else center
    if getattr(zones, "ccw", False):
        outer_from, outer_to = zones.exit_start_angle, zones.drop_end_angle
        inner_from, inner_to = zones.exit_start_inner_angle, zones.drop_end_inner_angle
    else:
        outer_from, outer_to = zones.drop_start_angle, zones.exit_end_angle
        inner_from, inner_to = zones.drop_start_inner_angle, zones.exit_end_inner_angle

    outer_start = normalizeAngle(outer_from)
    outer_span = positiveAngleSpan(outer_from, outer_to)
    outer_end = outer_start + outer_span
    outer_segments = max(16, int(round((outer_span / 360.0) * float(segment_count))))

    outer_angles = {
        outer_start + (outer_span * i) / outer_segments
        for i in range(outer_segments + 1)
    }
    _addBoundaryAngleWithin(outer_angles, zones.exit_start_angle, outer_start, outer_end)
    _addBoundaryAngleWithin(outer_angles, zones.exit_end_angle, outer_start, outer_end)

    points: list[list[int]] = []
    for angle in sorted(outer_angles):
        _appendChannelCropBoundaryPoint(points, zones, cx, cy, angle, radius_scale)

    inner_start = normalizeAngle(inner_from)
    inner_span = positiveAngleSpan(inner_from, inner_to)
    inner_segments = max(16, int(round((inner_span / 360.0) * float(segment_count))))
    for i in range(inner_segments, -1, -1):
        angle = inner_start + (inner_span * i) / inner_segments
        points.append(_polarPoint(cx, cy, zones.inner_radius, angle, radius_scale))

    return np.array(points, dtype=np.int32)


def zoneSectionsForChannel(
    channel_id: int,
    section_zero_angle: float,
    zones: ChannelArcZones | None,
) -> tuple[set[int], set[int]]:
    if zones is None:
        return legacyChannelZoneSections(channel_id)
    # The exit section set unions the exit and precise arcs — this is the
    # legacy counterpart to perception's buildChannelDef. The two arcs stay
    # separate in the schema/geometry; they are merged only here, where arcs
    # become the section set that the rest of the pipeline treats as "exit".
    exit_sections = sectionsForAngleRange(
        zones.exit_start_angle, zones.exit_end_angle, section_zero_angle
    )
    if (
        zones.precise_start_angle is not None
        and zones.precise_end_angle is not None
        # Zero-width precise (the default for older saved configs that predate
        # the precise zone) must union to nothing. sectionsForAngleRange treats
        # a zero span as a full 360° circle, so guard it out explicitly.
        and angularDistance(zones.precise_start_angle, zones.precise_end_angle) > 1e-6
    ):
        exit_sections = exit_sections | sectionsForAngleRange(
            zones.precise_start_angle, zones.precise_end_angle, section_zero_angle
        )
    return (
        sectionsForAngleRange(zones.drop_start_angle, zones.drop_end_angle, section_zero_angle),
        exit_sections,
    )


def getBboxSections(bbox: Tuple[int, int, int, int], channel: PolygonChannel) -> set[int]:
    x1, y1, x2, y2 = bbox
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    points = [
        (x1, y1), (x2, y1), (x1, y2), (x2, y2),
        (mx, y1), (mx, y2), (x1, my), (x2, my),
        (mx, my),
    ]
    sections: set[int] = set()
    for px, py in points:
        dx = px - channel.center[0]
        dy = py - channel.center[1]
        angle = np.degrees(np.arctan2(dy, dx))
        relative = (angle - channel.radius1_angle_image) % 360
        sections.add(int(relative / CHANNEL_SECTION_DEG))
    return sections


def _orderedCircularSections(sections: set[int]) -> list[int]:
    if not sections:
        return []
    section_count = int(round(360.0 / CHANNEL_SECTION_DEG))
    normalized = sorted({int(section) % section_count for section in sections})
    if len(normalized) <= 1 or len(normalized) >= section_count:
        return normalized

    largest_gap_index = 0
    largest_gap = -1
    for index, section in enumerate(normalized):
        next_section = normalized[(index + 1) % len(normalized)]
        gap = (next_section - section) % section_count
        if gap > largest_gap:
            largest_gap = gap
            largest_gap_index = index

    start = normalized[(largest_gap_index + 1) % len(normalized)]
    return sorted(normalized, key=lambda section: (section - start) % section_count)


