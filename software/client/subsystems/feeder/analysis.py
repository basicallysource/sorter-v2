from enum import Enum
from typing import List
from vision.types import VisionResult
from vision.regions import RegionName, Region

OBJECT_DETECTION_CONFIDENCE_THRESHOLD = 0.4


class FeederAnalysisState(Enum):
    OBJECT_IN_3_DROPZONE_PRECISE = "object_in_3_dropzone_precise"
    OBJECT_IN_3_DROPZONE = "object_in_3_dropzone"
    OBJECT_IN_2_DROPZONE_PRECISE = "object_in_2_dropzone_precise"
    OBJECT_IN_2_DROPZONE = "object_in_2_dropzone"
    CLEAR = "clear"


def analyzeFeederState(
    object_detections: List[VisionResult],
    regions: dict[RegionName, Region],
) -> FeederAnalysisState:
    if not object_detections:
        return FeederAnalysisState.CLEAR

    high_confidence_objects = [
        detection
        for detection in object_detections
        if detection.confidence >= OBJECT_DETECTION_CONFIDENCE_THRESHOLD
    ]

    if not high_confidence_objects:
        return FeederAnalysisState.CLEAR

    ch3_precise = regions.get(RegionName.CHANNEL_3_PRECISE)
    ch3_dropzone = regions.get(RegionName.CHANNEL_3_DROPZONE)
    ch2_precise = regions.get(RegionName.CHANNEL_2_PRECISE)
    ch2_dropzone = regions.get(RegionName.CHANNEL_2_DROPZONE)

    has_3_precise = False
    has_3_dropzone = False
    has_2_precise = False
    has_2_dropzone = False

    for detection in high_confidence_objects:
        if detection.bbox is None:
            continue
        x1, y1, x2, y2 = detection.bbox
        cx = int((x1 + x2) / 2.0)
        cy = int((y1 + y2) / 2.0)

        # check channel 3 (inner) first — higher priority
        if ch3_precise and ch3_precise.containsPoint(cx, cy):
            has_3_precise = True
        elif ch3_dropzone and ch3_dropzone.containsPoint(cx, cy):
            has_3_dropzone = True
        elif ch2_precise and ch2_precise.containsPoint(cx, cy):
            has_2_precise = True
        elif ch2_dropzone and ch2_dropzone.containsPoint(cx, cy):
            has_2_dropzone = True

    if has_3_precise:
        return FeederAnalysisState.OBJECT_IN_3_DROPZONE_PRECISE
    if has_3_dropzone:
        return FeederAnalysisState.OBJECT_IN_3_DROPZONE
    if has_2_precise:
        return FeederAnalysisState.OBJECT_IN_2_DROPZONE_PRECISE
    if has_2_dropzone:
        return FeederAnalysisState.OBJECT_IN_2_DROPZONE

    return FeederAnalysisState.CLEAR
