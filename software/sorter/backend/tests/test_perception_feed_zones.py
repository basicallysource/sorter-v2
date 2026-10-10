"""The live feed's zones as shapes: each zone where its sections are, in 0..1
of the frame, one zone to a pixel."""

from __future__ import annotations

import math
from types import SimpleNamespace

import cv2
import numpy as np

from perception.overlay import feedZoneShapes


def _angles(rings: list[list[float]]) -> tuple[float, float]:
    """The smallest and largest angle, clockwise from 3 o'clock about the
    channel's center, of a zone's corners, in the 400 x 200 frame's pixels."""
    points = np.concatenate([np.asarray(ring).reshape(-1, 2) for ring in rings]) * (400, 200)
    angles = [math.degrees(math.atan2(y - 100, x - 200)) % 360.0 for x, y in points]
    return min(angles), max(angles)


def _within(rings: list[list[float]], start: float, end: float) -> bool:
    """A zone spans start..end degrees, to within the pixels it is traced at."""
    low, high = _angles(rings)
    return abs(low - start) < 4 and abs(high - end) < 4


def test_zones_are_traced_where_their_sections_are() -> None:
    mask = np.zeros((200, 400), np.uint8)
    cv2.circle(mask, (200, 100), 90, 255, -1)
    cv2.circle(mask, (200, 100), 40, 0, -1)
    foreign = np.zeros_like(mask)
    foreign[10:30, 10:30] = 255
    channel = SimpleNamespace(
        mask=mask,
        center=(200.0, 100.0),
        radius1_angle_image=0.0,
        drop_sections=frozenset(range(1, 30)),
        exit_sections=frozenset(range(90, 150)),
        precise_sections=frozenset(range(120, 150)),
        exit_margin_mask=None,
        secondary_zones=[SimpleNamespace(zone_type="exit", mask=foreign)],
    )

    shapes = feedZoneShapes(channel, 200)

    every = [v for key in ("drop", "exit", "precise", "outline") for ring in shapes[key] for v in ring]
    assert every and all(0.0 <= v <= 1.0 for v in every)
    # Sections 1..29 (0 sits on the wrap, so start one in to keep min/max honest).
    assert _within(shapes["drop"], 1, 30)
    # The exit zone shows only where the precise zone does not.
    assert _within(shapes["exit"], 90, 120)
    assert _within(shapes["precise"], 120, 150)
    assert len(shapes["outline"]) == 1 and shapes["margin"] == []
    [secondary] = shapes["secondary"]
    assert secondary["type"] == "exit"
    assert max(secondary["rings"][0][0::2]) < 0.1
