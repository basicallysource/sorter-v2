from dataclasses import dataclass
from typing import Tuple
import numpy as np


@dataclass
class PolygonChannel:
    channel_id: int
    polygon: np.ndarray
    center: Tuple[float, float]
    radius1_angle_image: float
    mask: np.ndarray


@dataclass
class ChannelGeometry:
    second_channel: PolygonChannel | None
    third_channel: PolygonChannel | None


@dataclass
class ChannelDetection:
    bbox: Tuple[int, int, int, int]
    channel_id: int
    channel: PolygonChannel
