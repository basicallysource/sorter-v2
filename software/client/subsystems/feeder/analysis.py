from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, TYPE_CHECKING
import numpy as np
from vision.utils import maskCenterOfMass
from vision.types import DetectedMask

if TYPE_CHECKING:
    from irl.config import ArucoTagConfig

OBJECT_DETECTION_CONFIDENCE_THRESHOLD = 0.4


class FeederAnalysisState(Enum):
    OBJECT_IN_3_DROPZONE_PRECISE = "object_in_3_dropzone_precise"
    OBJECT_IN_3_DROPZONE = "object_in_3_dropzone"
    OBJECT_IN_2_DROPZONE_PRECISE = "object_in_2_dropzone_precise"
    OBJECT_IN_2_DROPZONE = "object_in_2_dropzone"
    CLEAR = "clear"


@dataclass
class CircularChannel:
    channel_id: int
    center: Tuple[float, float]
    radius: float
    radius1_angle_image: float  # angle to radius1 tag in image space


@dataclass
class ChannelGeometry:
    second_channel: Optional[CircularChannel]
    third_channel: Optional[CircularChannel]


def computeChannelGeometry(
    aruco_tags: Dict[int, Tuple[float, float]],
    aruco_config: "ArucoTagConfig",
) -> ChannelGeometry:
    geometry = ChannelGeometry(second_channel=None, third_channel=None)

    # compute channel 2 - circle from two radius tags (diameter endpoints)
    second_r1 = aruco_tags.get(aruco_config.second_c_channel_radius1_id)
    second_r2 = aruco_tags.get(aruco_config.second_c_channel_radius2_id)

    if second_r1 and second_r2:
        # center is midpoint between the two radius tags
        center_x = (second_r1[0] + second_r2[0]) / 2.0
        center_y = (second_r1[1] + second_r2[1]) / 2.0
        center = (center_x, center_y)

        # radius is half the distance between the two tags
        radius = float(np.linalg.norm(np.array(second_r1) - np.array(second_r2)) / 2.0)

        # angle to radius1 in image space
        v1 = np.array(second_r1) - np.array(center)
        r1_angle_img = float(np.degrees(np.arctan2(v1[1], v1[0])))

        geometry.second_channel = CircularChannel(
            channel_id=2,
            center=center,
            radius=radius,
            radius1_angle_image=r1_angle_img,
        )

    # compute channel 3 - circle from two radius tags (diameter endpoints)
    third_r1 = aruco_tags.get(aruco_config.third_c_channel_radius1_id)
    third_r2 = aruco_tags.get(aruco_config.third_c_channel_radius2_id)

    if third_r1 and third_r2:
        # center is midpoint between the two radius tags
        center_x = (third_r1[0] + third_r2[0]) / 2.0
        center_y = (third_r1[1] + third_r2[1]) / 2.0
        center = (center_x, center_y)

        # radius is half the distance between the two tags
        radius = float(np.linalg.norm(np.array(third_r1) - np.array(third_r2)) / 2.0)

        # angle to radius1 in image space
        v1 = np.array(third_r1) - np.array(center)
        r1_angle_img = float(np.degrees(np.arctan2(v1[1], v1[0])))

        geometry.third_channel = CircularChannel(
            channel_id=3,
            center=center,
            radius=radius,
            radius1_angle_image=r1_angle_img,
        )

    return geometry


def isPointInCircle(
    point: Tuple[float, float],
    center: Tuple[float, float],
    radius: float,
) -> bool:
    distance = np.linalg.norm(np.array(point) - np.array(center))
    return distance <= radius


def determineObjectChannelAndQuadrant(
    obj_center_image: Tuple[float, float],
    geometry: ChannelGeometry,
) -> Optional[Tuple[int, int]]:
    # check channel 3 first (innermost)
    if geometry.third_channel:
        if isPointInCircle(
            obj_center_image,
            geometry.third_channel.center,
            geometry.third_channel.radius,
        ):
            # calculate angle in image space relative to radius1
            dx = obj_center_image[0] - geometry.third_channel.center[0]
            dy = obj_center_image[1] - geometry.third_channel.center[1]
            obj_angle = np.degrees(np.arctan2(dy, dx))

            # relative angle from radius1
            relative_angle = obj_angle - geometry.third_channel.radius1_angle_image
            while relative_angle < 0:
                relative_angle += 360
            while relative_angle >= 360:
                relative_angle -= 360

            quadrant = int(relative_angle / 90.0)
            return (3, quadrant)

    # check channel 2
    if geometry.second_channel:
        if isPointInCircle(
            obj_center_image,
            geometry.second_channel.center,
            geometry.second_channel.radius,
        ):
            # calculate angle in image space relative to radius1
            dx = obj_center_image[0] - geometry.second_channel.center[0]
            dy = obj_center_image[1] - geometry.second_channel.center[1]
            obj_angle = np.degrees(np.arctan2(dy, dx))

            # relative angle from radius1
            relative_angle = obj_angle - geometry.second_channel.radius1_angle_image
            while relative_angle < 0:
                relative_angle += 360
            while relative_angle >= 360:
                relative_angle -= 360

            quadrant = int(relative_angle / 90.0)
            return (2, quadrant)

    return None


def analyzeFeederState(
    object_detected_masks: List[DetectedMask],
    geometry: ChannelGeometry,
) -> FeederAnalysisState:
    if not object_detected_masks:
        return FeederAnalysisState.CLEAR

    # filter objects by confidence threshold
    high_confidence_objects = [
        dm
        for dm in object_detected_masks
        if dm.confidence >= OBJECT_DETECTION_CONFIDENCE_THRESHOLD
    ]

    if not high_confidence_objects:
        return FeederAnalysisState.CLEAR

    has_object_in_3_dropzone_precise = False
    has_object_in_3_dropzone = False
    has_object_in_2_dropzone_precise = False
    has_object_in_2_dropzone = False

    for obj_dm in high_confidence_objects:
        center = maskCenterOfMass(obj_dm.mask)
        if center is None:
            continue

        result = determineObjectChannelAndQuadrant(center, geometry)
        if result is None:
            continue

        channel_id, quadrant = result

        # check for precise mode (quadrant 3) and normal dropzone (quadrants 0, 1)
        if channel_id == 3:
            if quadrant == 3:
                has_object_in_3_dropzone_precise = True
            elif quadrant in [0, 1]:
                has_object_in_3_dropzone = True

        if channel_id == 2:
            if quadrant == 3:
                has_object_in_2_dropzone_precise = True
            elif quadrant in [0, 1]:
                has_object_in_2_dropzone = True

    # return in priority order
    if has_object_in_3_dropzone_precise:
        return FeederAnalysisState.OBJECT_IN_3_DROPZONE_PRECISE
    if has_object_in_3_dropzone:
        return FeederAnalysisState.OBJECT_IN_3_DROPZONE
    if has_object_in_2_dropzone_precise:
        return FeederAnalysisState.OBJECT_IN_2_DROPZONE_PRECISE
    if has_object_in_2_dropzone:
        return FeederAnalysisState.OBJECT_IN_2_DROPZONE

    return FeederAnalysisState.CLEAR
