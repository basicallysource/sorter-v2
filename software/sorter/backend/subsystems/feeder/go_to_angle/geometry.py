from typing import Tuple

import numpy as np

from defs.channel import PolygonChannel
from defs.consts import CHANNEL_SECTION_DEG
from subsystems.feeder.analysis import _orderedCircularSections, normalizeAngle


def pieceRelativeAngle(bbox: Tuple[int, int, int, int], channel: PolygonChannel) -> float:
    """Angle of a detection's center relative to the channel's reference radius.

    Same convention as the section math: forward (camera-clockwise / forward
    motor) motion increases this angle. 0 == the calibrated radius1 reference.
    """
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    dx = cx - channel.center[0]
    dy = cy - channel.center[1]
    image_angle = float(np.degrees(np.arctan2(dy, dx)))
    return normalizeAngle(image_angle - channel.radius1_angle_image)


def forwardDistance(from_angle: float, to_angle: float) -> float:
    """Degrees to travel in the forward (increasing relative angle) direction."""
    return (normalizeAngle(to_angle) - normalizeAngle(from_angle) + 360.0) % 360.0


def sectionSetForwardEdge(sections: set[int]) -> float | None:
    """Relative angle of the forward-most edge of a section set, or None.

    Sections wrap circularly; ``_orderedCircularSections`` walks them starting
    after the largest gap, so the last entry is the most-forward slice. The
    forward edge is one section width past it.
    """
    ordered = _orderedCircularSections(sections)
    if not ordered:
        return None
    return normalizeAngle((ordered[-1] + 1) * CHANNEL_SECTION_DEG)


def sectionForRelativeAngle(angle: float) -> int:
    section_count = int(round(360.0 / CHANNEL_SECTION_DEG))
    return int(normalizeAngle(angle) / CHANNEL_SECTION_DEG) % section_count
