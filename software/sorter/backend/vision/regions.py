from enum import Enum
from typing import Protocol
import numpy as np


class RegionName(Enum):
    CHANNEL_2 = "channel_2"
    CHANNEL_3 = "channel_3"
    CHANNEL_2_DROPZONE = "channel_2_dropzone"
    CHANNEL_2_PRECISE = "channel_2_precise"
    CHANNEL_3_DROPZONE = "channel_3_dropzone"
    CHANNEL_3_PRECISE = "channel_3_precise"
    CAROUSEL_PLATFORM = "carousel_platform"


class Region:
    name: RegionName
    mask: np.ndarray

    def __init__(self, name: RegionName, mask: np.ndarray):
        self.name = name
        self.mask = mask

    def overlapCount(self, other_mask: np.ndarray) -> int:
        return int(np.count_nonzero(self.mask & other_mask))

    def overlapFraction(self, other_mask: np.ndarray) -> float:
        other_count = int(np.count_nonzero(other_mask))
        if other_count == 0:
            return 0.0
        return self.overlapCount(other_mask) / other_count

    def containsPoint(self, x: int, y: int) -> bool:
        if 0 <= y < self.mask.shape[0] and 0 <= x < self.mask.shape[1]:
            return bool(self.mask[y, x])
        return False


class RegionProvider(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def getRegions(self, frame: np.ndarray) -> dict[RegionName, Region]: ...
    def annotateFrame(self, frame: np.ndarray) -> np.ndarray: ...
