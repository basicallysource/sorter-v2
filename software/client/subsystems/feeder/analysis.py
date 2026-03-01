from enum import Enum
from typing import List, Dict, Tuple, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from global_config import GlobalConfig

from defs.consts import (
    CHANNEL_SECTION_DEG,
    CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
    CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
)
from defs.channel import PolygonChannel, ChannelGeometry, ChannelDetection


class ChannelAction(Enum):
    IDLE = "idle"
    PULSE_NORMAL = "normal"
    PULSE_PRECISE = "precise"


def computeChannelGeometry(
    saved_polygons: Dict[str, np.ndarray],
    channel_angles: Dict[str, float],
    channel_masks: Dict[str, np.ndarray],
) -> ChannelGeometry:
    geometry = ChannelGeometry(second_channel=None, third_channel=None)

    second_poly = saved_polygons.get("second_channel")
    if second_poly is not None and len(second_poly) >= 3:
        center = tuple(np.mean(second_poly, axis=0).tolist())
        r1_angle = channel_angles.get("second", 0.0)
        geometry.second_channel = PolygonChannel(
            channel_id=2,
            polygon=second_poly,
            center=center,
            radius1_angle_image=r1_angle,
            mask=channel_masks["second_channel"],
        )

    third_poly = saved_polygons.get("third_channel")
    if third_poly is not None and len(third_poly) >= 3:
        center = tuple(np.mean(third_poly, axis=0).tolist())
        r1_angle = channel_angles.get("third", 0.0)
        geometry.third_channel = PolygonChannel(
            channel_id=3,
            polygon=third_poly,
            center=center,
            radius1_angle_image=r1_angle,
            mask=channel_masks["third_channel"],
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


def getBboxSections(bbox: Tuple, channel: PolygonChannel) -> set:
    x1, y1, x2, y2 = bbox
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    points = [
        (x1, y1), (x2, y1), (x1, y2), (x2, y2),
        (mx, y1), (mx, y2), (x1, my), (x2, my),
        (mx, my),
    ]
    sections = set()
    for px, py in points:
        dx = px - channel.center[0]
        dy = py - channel.center[1]
        angle = np.degrees(np.arctan2(dy, dx))
        relative = (angle - channel.radius1_angle_image) % 360
        sections.add(int(relative / CHANNEL_SECTION_DEG))
    return sections


class FeederAnalysis:
    def __init__(self):
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
            if sections & set(CH3_DROPZONE_SECTIONS):
                result.ch3_dropzone_occupied = True
            if sections & set(CH3_PRECISE_SECTIONS):
                result.ch3_action = ChannelAction.PULSE_PRECISE
            elif result.ch3_action == ChannelAction.IDLE:
                result.ch3_action = ChannelAction.PULSE_NORMAL
        elif det.channel_id == 2:
            if sections & set(CH2_DROPZONE_SECTIONS):
                result.ch2_dropzone_occupied = True
            if sections & set(CH2_PRECISE_SECTIONS):
                result.ch2_action = ChannelAction.PULSE_PRECISE
            elif result.ch2_action == ChannelAction.IDLE:
                result.ch2_action = ChannelAction.PULSE_NORMAL

    return result
