from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Dict, Tuple, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from global_config import GlobalConfig

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
    drop_start_angle: float
    drop_end_angle: float
    wait_start_angle: float | None
    wait_end_angle: float | None
    exit_start_angle: float
    exit_end_angle: float


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
        drop_start_angle=normalizeAngle(section_zero_angle + drop_sections.start * CHANNEL_SECTION_DEG),
        drop_end_angle=normalizeAngle(section_zero_angle + drop_sections.stop * CHANNEL_SECTION_DEG),
        wait_start_angle=None,
        wait_end_angle=None,
        exit_start_angle=normalizeAngle(section_zero_angle + exit_sections.start * CHANNEL_SECTION_DEG),
        exit_end_angle=normalizeAngle(section_zero_angle + exit_sections.stop * CHANNEL_SECTION_DEG),
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

    def _zone(zone_key: str, legacy_sections: range) -> tuple[float, float]:
        raw_zone = raw.get(zone_key)
        if isinstance(raw_zone, dict):
            start_angle = raw_zone.get("start_angle")
            end_angle = raw_zone.get("end_angle")
            if isinstance(start_angle, (int, float)) and isinstance(end_angle, (int, float)):
                return normalizeAngle(float(start_angle)), normalizeAngle(float(end_angle))
        return (
            normalizeAngle(section_zero_angle + legacy_sections.start * CHANNEL_SECTION_DEG),
            normalizeAngle(section_zero_angle + legacy_sections.stop * CHANNEL_SECTION_DEG),
        )

    def _optional_zone(zone_key: str) -> tuple[float, float] | None:
        raw_zone = raw.get(zone_key)
        if not isinstance(raw_zone, dict):
            return None
        start_angle = raw_zone.get("start_angle")
        end_angle = raw_zone.get("end_angle")
        if isinstance(start_angle, (int, float)) and isinstance(end_angle, (int, float)):
            return normalizeAngle(float(start_angle)), normalizeAngle(float(end_angle))
        return None

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
        return ChannelArcZones(
            center=(float(center[0]), float(center[1])),
            inner_radius=float(inner_radius),
            outer_radius=float(outer_radius),
            drop_start_angle=drop_zone[0],
            drop_end_angle=drop_zone[1],
            wait_start_angle=wait_zone[0] if wait_zone is not None else None,
            wait_end_angle=wait_zone[1] if wait_zone is not None else None,
            exit_start_angle=exit_zone[0],
            exit_end_angle=exit_zone[1],
        )

    drop_start, drop_end = _zone("drop_zone", legacy_drop)
    wait_zone = _optional_zone("wait_zone")
    exit_start, exit_end = _zone("exit_zone", legacy_exit)
    return ChannelArcZones(
        center=(float(center[0]), float(center[1])),
        inner_radius=float(inner_radius),
        outer_radius=float(outer_radius),
        drop_start_angle=drop_start,
        drop_end_angle=drop_end,
        wait_start_angle=wait_zone[0] if wait_zone is not None else None,
        wait_end_angle=wait_zone[1] if wait_zone is not None else None,
        exit_start_angle=exit_start,
        exit_end_angle=exit_end,
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


class FeederAnalysis:
    def __init__(self) -> None:
        self.ch2_action = ChannelAction.IDLE
        self.ch3_action = ChannelAction.IDLE
        self.ch3_dropzone_occupied = False
        self.ch2_dropzone_occupied = False


def analyzeFeederChannels(
    gc: "GlobalConfig",
    detections: List[ChannelDetection],
) -> FeederAnalysis:
    result = FeederAnalysis()

    for det in detections:
        sections = getBboxSections(det.bbox, det.channel)

        if det.channel_id == 3:
            if sections & det.channel.dropzone_sections:
                result.ch3_dropzone_occupied = True
            if sections & det.channel.exit_sections:
                result.ch3_action = ChannelAction.PULSE_PRECISE
            elif result.ch3_action == ChannelAction.IDLE:
                result.ch3_action = ChannelAction.PULSE_NORMAL
        elif det.channel_id == 2:
            if sections & det.channel.dropzone_sections:
                result.ch2_dropzone_occupied = True
            if sections & det.channel.exit_sections:
                result.ch2_action = ChannelAction.PULSE_PRECISE
            elif result.ch2_action == ChannelAction.IDLE:
                result.ch2_action = ChannelAction.PULSE_NORMAL

    return result
