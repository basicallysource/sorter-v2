from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Dict, Tuple
import numpy as np

from defs.consts import (
    CHANNEL_SECTION_DEG,
    CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
    CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
)
from defs.channel import PolygonChannel, ChannelGeometry, ChannelDetection


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
        )

    drop_start, drop_end, drop_start_inner, drop_end_inner = _zone_with_inner("drop_zone", legacy_drop)
    wait_zone = _optional_zone("wait_zone")
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
        points.append(_polarPoint(cx, cy, zones.exit_outer_radius, angle, radius_scale))
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
    """Return the physical channel surface, excluding the exit-to-drop gap.

    The operator draws ``Exit End`` and ``Drop Start`` as the two boundaries of
    the output-guide opening. Pixels in that angular gap are outside the local
    channel even if they are inside the nominal outer circle.
    """
    cx, cy = zones.center if center is None else center
    outer_start = normalizeAngle(zones.drop_start_angle)
    outer_span = positiveAngleSpan(zones.drop_start_angle, zones.exit_end_angle)
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

    inner_start = normalizeAngle(zones.drop_start_inner_angle)
    inner_span = positiveAngleSpan(zones.drop_start_inner_angle, zones.exit_end_inner_angle)
    inner_segments = max(16, int(round((inner_span / 360.0) * float(segment_count))))
    for i in range(inner_segments, -1, -1):
        angle = inner_start + (inner_span * i) / inner_segments
        points.append(_polarPoint(cx, cy, zones.inner_radius, angle, radius_scale))

    return np.array(points, dtype=np.int32)


def channelArcInnerPolygon(
    zones: ChannelArcZones,
    *,
    segment_count: int = 96,
    center: Tuple[float, float] | None = None,
    radius_scale: float = 1.0,
) -> np.ndarray:
    cx, cy = zones.center if center is None else center
    inner_radius = float(zones.inner_radius) * float(radius_scale)
    return np.array(
        [
            [
                int(round(cx + inner_radius * np.cos((2 * np.pi * i) / segment_count))),
                int(round(cy + inner_radius * np.sin((2 * np.pi * i) / segment_count))),
            ]
            for i in range(segment_count)
        ],
        dtype=np.int32,
    )


def zoneSectionsForChannel(
    channel_id: int,
    section_zero_angle: float,
    zones: ChannelArcZones | None,
) -> tuple[set[int], set[int]]:
    if zones is None:
        return legacyChannelZoneSections(channel_id)
    return (
        sectionsForAngleRange(zones.drop_start_angle, zones.drop_end_angle, section_zero_angle),
        sectionsForAngleRange(zones.exit_start_angle, zones.exit_end_angle, section_zero_angle),
    )


class ChannelAction(Enum):
    IDLE = "idle"
    PULSE_NORMAL = "normal"
    PULSE_PRECISE = "precise"


def computeChannelGeometry(
    saved_polygons: Dict[str, np.ndarray],
    channel_angles: Dict[str, float],
    channel_masks: Dict[str, np.ndarray],
    channel_arc_params: Dict[str, Any] | None = None,
) -> ChannelGeometry:
    geometry = ChannelGeometry(second_channel=None, third_channel=None)

    second_poly = saved_polygons.get("second_channel")
    if second_poly is not None and len(second_poly) >= 3:
        center = tuple(np.mean(second_poly, axis=0).tolist())
        r1_angle = channel_angles.get("second", 0.0)
        second_zones = parseSavedChannelArcZones("second", channel_angles, channel_arc_params)
        second_drop_sections, second_exit_sections = zoneSectionsForChannel(2, r1_angle, second_zones)
        geometry.second_channel = PolygonChannel(
            channel_id=2,
            polygon=second_poly,
            center=center,
            radius1_angle_image=r1_angle,
            mask=channel_masks["second_channel"],
            dropzone_sections=second_drop_sections,
            exit_sections=second_exit_sections,
        )

    third_poly = saved_polygons.get("third_channel")
    if third_poly is not None and len(third_poly) >= 3:
        center = tuple(np.mean(third_poly, axis=0).tolist())
        r1_angle = channel_angles.get("third", 0.0)
        third_zones = parseSavedChannelArcZones("third", channel_angles, channel_arc_params)
        third_drop_sections, third_exit_sections = zoneSectionsForChannel(3, r1_angle, third_zones)
        geometry.third_channel = PolygonChannel(
            channel_id=3,
            polygon=third_poly,
            center=center,
            radius1_angle_image=r1_angle,
            mask=channel_masks["third_channel"],
            dropzone_sections=third_drop_sections,
            exit_sections=third_exit_sections,
        )

    return geometry


def _isInChannel(point: Tuple[float, float], ch: PolygonChannel) -> bool:
    x, y = int(point[0]), int(point[1])
    if 0 <= y < ch.mask.shape[0] and 0 <= x < ch.mask.shape[1]:
        return ch.mask[y, x] > 0
    return False


def determineObjectChannel(
    obj_center_image: Tuple[float, float],
    geometry: ChannelGeometry,
) -> PolygonChannel | None:
    if geometry.third_channel and _isInChannel(obj_center_image, geometry.third_channel):
        return geometry.third_channel
    if geometry.second_channel and _isInChannel(obj_center_image, geometry.second_channel):
        return geometry.second_channel
    return None


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


def _sectionForPoint(px: float, py: float, channel: PolygonChannel) -> int:
    dx = px - channel.center[0]
    dy = py - channel.center[1]
    angle = np.degrees(np.arctan2(dy, dx))
    relative = (angle - channel.radius1_angle_image) % 360
    return int(relative / CHANNEL_SECTION_DEG)


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


def bboxCenterCrossedSectionMidpoint(
    bbox: Tuple[int, int, int, int],
    channel: PolygonChannel,
    sections: set[int],
) -> bool:
    """Return True once a bbox center reaches the latter half of a section arc."""
    ordered_sections = _orderedCircularSections(sections)
    if not ordered_sections:
        return False
    x1, y1, x2, y2 = bbox
    center_section = _sectionForPoint((x1 + x2) / 2.0, (y1 + y2) / 2.0, channel)
    midpoint_index = max(0, len(ordered_sections) // 2)
    return center_section in set(ordered_sections[midpoint_index:])


def bboxSectionOverlapRatio(
    bbox: Tuple[int, int, int, int],
    channel: PolygonChannel,
    sections: set[int],
    *,
    samples_per_axis: int = 5,
) -> float:
    """Approximate how much of a bbox lies inside a channel section set."""
    if not sections:
        return 0.0
    x1, y1, x2, y2 = bbox
    left, right = sorted((float(x1), float(x2)))
    top, bottom = sorted((float(y1), float(y2)))
    if right <= left or bottom <= top or samples_per_axis <= 0:
        return 0.0

    total = 0
    inside_sections = 0
    for py in np.linspace(top, bottom, samples_per_axis):
        for px in np.linspace(left, right, samples_per_axis):
            if not _isInChannel((px, py), channel):
                continue
            total += 1
            if _sectionForPoint(float(px), float(py), channel) in sections:
                inside_sections += 1

    if total <= 0:
        return 0.0
    return float(inside_sections) / float(total)


def _bboxExitOverlapRatio(
    bbox: Tuple[int, int, int, int],
    channel: PolygonChannel,
    *,
    samples_per_axis: int = 5,
) -> float:
    """Approximate how much of a bbox lies inside the channel exit zone."""
    return bboxSectionOverlapRatio(
        bbox,
        channel,
        channel.exit_sections,
        samples_per_axis=samples_per_axis,
    )


class FeederAnalysis:
    def __init__(self) -> None:
        self.ch2_action = ChannelAction.IDLE
        self.ch3_action = ChannelAction.IDLE
        self.ch3_dropzone_occupied = False
        self.ch2_dropzone_occupied = False
        # Max sampled bbox area overlap-ratio of any detection in the channel.
        # Used by the exit-zone incident guard to spot pieces that are parked
        # inside the exit zone instead of falling through.
        self.ch2_exit_overlap_max: float = 0.0
        self.ch3_exit_overlap_max: float = 0.0
        self.ch2_exit_center_crossed: bool = False
        self.ch3_exit_center_crossed: bool = False
        self.ch2_dropzone_overlap_max: float = 0.0
        self.ch3_dropzone_overlap_max: float = 0.0


def _exitOverlapRatio(sections: set[int], exit_sections: set[int]) -> float:
    if not sections or not exit_sections:
        return 0.0
    return float(len(sections & exit_sections)) / float(len(sections))


def analyzeFeederChannels(
    detections: List[ChannelDetection],
    ignored_dropzone_detection_ids: set[tuple[int, int]] | None = None,
) -> FeederAnalysis:
    result = FeederAnalysis()
    ignored_dropzone_detection_ids = ignored_dropzone_detection_ids or set()

    for det in detections:
        sections = getBboxSections(det.bbox, det.channel)
        global_id = getattr(det, "global_id", None)
        ignore_dropzone = (
            isinstance(global_id, int)
            and (int(det.channel_id), int(global_id)) in ignored_dropzone_detection_ids
        )

        if det.channel_id == 3:
            drop_overlap = bboxSectionOverlapRatio(det.bbox, det.channel, det.channel.dropzone_sections)
            if drop_overlap > result.ch3_dropzone_overlap_max:
                result.ch3_dropzone_overlap_max = drop_overlap
            if not ignore_dropzone and sections & det.channel.dropzone_sections:
                result.ch3_dropzone_occupied = True
            overlap = _bboxExitOverlapRatio(det.bbox, det.channel)
            if overlap > result.ch3_exit_overlap_max:
                result.ch3_exit_overlap_max = overlap
            if bboxCenterCrossedSectionMidpoint(
                det.bbox,
                det.channel,
                det.channel.exit_sections,
            ):
                result.ch3_exit_center_crossed = True
            if overlap > 0.0 or result.ch3_exit_center_crossed:
                result.ch3_action = ChannelAction.PULSE_PRECISE
            elif result.ch3_action == ChannelAction.IDLE:
                result.ch3_action = ChannelAction.PULSE_NORMAL
        elif det.channel_id == 2:
            drop_overlap = bboxSectionOverlapRatio(det.bbox, det.channel, det.channel.dropzone_sections)
            if drop_overlap > result.ch2_dropzone_overlap_max:
                result.ch2_dropzone_overlap_max = drop_overlap
            if not ignore_dropzone and sections & det.channel.dropzone_sections:
                result.ch2_dropzone_occupied = True
            overlap = _bboxExitOverlapRatio(det.bbox, det.channel)
            if overlap > result.ch2_exit_overlap_max:
                result.ch2_exit_overlap_max = overlap
            if bboxCenterCrossedSectionMidpoint(
                det.bbox,
                det.channel,
                det.channel.exit_sections,
            ):
                result.ch2_exit_center_crossed = True
            if overlap > 0.0 or result.ch2_exit_center_crossed:
                result.ch2_action = ChannelAction.PULSE_PRECISE
            elif result.ch2_action == ChannelAction.IDLE:
                result.ch2_action = ChannelAction.PULSE_NORMAL

    return result
