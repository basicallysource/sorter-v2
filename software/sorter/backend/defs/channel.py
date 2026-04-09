from dataclasses import dataclass, field
from typing import Tuple
import numpy as np


@dataclass
class PolygonChannel:
    channel_id: int
    polygon: np.ndarray
    center: Tuple[float, float]
    radius1_angle_image: float
    mask: np.ndarray
    dropzone_sections: set[int] = field(default_factory=set)
    exit_sections: set[int] = field(default_factory=set)
    inner_polygon: np.ndarray | None = None


@dataclass
class ChannelGeometry:
    second_channel: PolygonChannel | None
    third_channel: PolygonChannel | None


@dataclass
class ChannelDetection:
    bbox: Tuple[int, int, int, int]
    channel_id: int
    channel: PolygonChannel
