from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import numpy as np
from vision.utils import maskEdgeProximity, maskCenterOfMass, maskMinDistance
from vision.types import DetectedMask
from global_config import FeederConfig


class FeederAnalysisState(Enum):
    OBJECT_ABOUT_TO_FALL = "object_about_to_fall"
    OBJECT_IN_3_2_DROPZONE = "object_in_3_2_dropzone"
    OBJECT_IN_2_1_DROPZONE = "object_in_2_1_dropzone"
    CLEAR = "clear"


@dataclass
class IdentifiedChannels:
    second_channel_mask: Optional[DetectedMask]
    third_channel_mask: Optional[DetectedMask]
    first_aruco_pos: Optional[Tuple[float, float]]
    second_aruco_pos: Optional[Tuple[float, float]]
    third_aruco_pos: Optional[Tuple[float, float]]


def identifyChannels(
    channel_masks: List[DetectedMask],
    aruco_tags: Dict[int, Tuple[float, float]],
    first_tag_id: int,
    second_tag_id: int,
    third_tag_id: int,
) -> IdentifiedChannels:
    first_pos = aruco_tags.get(first_tag_id)
    second_pos = aruco_tags.get(second_tag_id)
    third_pos = aruco_tags.get(third_tag_id)

    result = IdentifiedChannels(
        second_channel_mask=None,
        third_channel_mask=None,
        first_aruco_pos=first_pos,
        second_aruco_pos=second_pos,
        third_aruco_pos=third_pos,
    )

    if len(channel_masks) == 0:
        return result

    # channel masks should only come from current frame (not cached)
    # if more than 2 masks, pick the 2 biggest
    filtered_masks = channel_masks
    if len(channel_masks) > 2:
        masks_with_area = []
        for detected_mask in channel_masks:
            area = int(np.sum(detected_mask.mask))
            masks_with_area.append((area, detected_mask))
        masks_with_area.sort(key=lambda x: x[0], reverse=True)
        filtered_masks = [m[1] for m in masks_with_area[:2]]

    # find x positions of each detected mask
    masks_with_x = []
    for detected_mask in filtered_masks:
        center = maskCenterOfMass(detected_mask.mask)
        if center is not None:
            masks_with_x.append((center[0], detected_mask))

    if len(masks_with_x) == 0:
        return result

    # sort by x coordinate: leftmost is third, rightmost is second
    masks_with_x.sort(key=lambda x: x[0])

    # leftmost is third channel
    result.third_channel_mask = masks_with_x[0][1]

    # rightmost is second channel
    if len(masks_with_x) >= 2:
        result.second_channel_mask = masks_with_x[-1][1]

    return result


def determineObjectChannel(
    obj_detected_mask: DetectedMask,
    channels: IdentifiedChannels,
    proximity_threshold: float,
) -> Optional[int]:
    proximity_2 = 0.0
    proximity_3 = 0.0

    if channels.second_channel_mask is not None:
        proximity_2 = maskEdgeProximity(
            obj_detected_mask.mask,
            channels.second_channel_mask.mask,
            proximity_px=5,
        )

    if channels.third_channel_mask is not None:
        proximity_3 = maskEdgeProximity(
            obj_detected_mask.mask,
            channels.third_channel_mask.mask,
            proximity_px=5,
        )

    if proximity_2 < proximity_threshold and proximity_3 < proximity_threshold:
        return None

    if proximity_3 >= proximity_2:
        return 3 if proximity_3 >= proximity_threshold else None
    else:
        return 2 if proximity_2 >= proximity_threshold else None


def isObjectInDropzone(
    obj_detected_mask: DetectedMask,
    aruco_pos: Tuple[float, float],
    threshold_px: int,
) -> bool:
    center = maskCenterOfMass(obj_detected_mask.mask)
    if center is None:
        return False

    dist = np.sqrt((center[0] - aruco_pos[0]) ** 2 + (center[1] - aruco_pos[1]) ** 2)
    return dist <= threshold_px


def analyzeFeederState(
    object_detected_masks: List[DetectedMask],
    channels: IdentifiedChannels,
    carousel_detected_mask: Optional[DetectedMask],
    fc: FeederConfig,
) -> FeederAnalysisState:
    if not object_detected_masks:
        return FeederAnalysisState.CLEAR

    has_object_about_to_fall = False
    has_object_in_3_2_dropzone = False
    has_object_in_2_1_dropzone = False

    for obj_dm in object_detected_masks:
        channel_id = determineObjectChannel(
            obj_dm, channels, fc.object_channel_overlap_threshold
        )

        if channel_id is None:
            continue

        # check for "about to fall" (on 3rd, near carousel)
        if channel_id == 3 and carousel_detected_mask is not None:
            distance_px = maskMinDistance(obj_dm.mask, carousel_detected_mask.mask)
            if distance_px <= fc.carousel_proximity_threshold_px:
                has_object_about_to_fall = True

        # check for object in 3->2 dropzone (on 3rd, near 2nd's ArUco)
        if channel_id == 3 and channels.second_aruco_pos is not None:
            if isObjectInDropzone(
                obj_dm,
                channels.second_aruco_pos,
                fc.third_channel_dropzone_threshold_px,
                True,
            ):
                has_object_in_3_2_dropzone = True

        # check for object in 2->1 dropzone (on 2nd, near 1st's ArUco)
        if channel_id == 2 and channels.first_aruco_pos is not None:
            if isObjectInDropzone(
                obj_dm,
                channels.first_aruco_pos,
                fc.second_channel_dropzone_threshold_px,
                True,
            ):
                has_object_in_2_1_dropzone = True

    # return in priority order
    if has_object_about_to_fall:
        return FeederAnalysisState.OBJECT_ABOUT_TO_FALL
    if has_object_in_3_2_dropzone:
        return FeederAnalysisState.OBJECT_IN_3_2_DROPZONE
    if has_object_in_2_1_dropzone:
        return FeederAnalysisState.OBJECT_IN_2_1_DROPZONE

    return FeederAnalysisState.CLEAR
