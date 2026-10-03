"""A piece on the exit lip, mostly past the rotor's edge, is still on the
channel; elsewhere a box counts only when its center is inside."""

import math

from perception.arcs import bboxInsideChannelMask
from perception.tests.test_arcs import CENTER, RADIUS, _channel

OUTER = RADIUS + 30  # the test annulus' outer edge


def _box(angle_deg: float, center_radius: float, half: float = 14.0) -> tuple[int, int, int, int]:
    a = math.radians(angle_deg)
    cx = CENTER[0] + center_radius * math.cos(a)
    cy = CENTER[1] + center_radius * math.sin(a)
    return (int(cx - half), int(cy - half), int(cx + half), int(cy + half))


def test_a_box_straddling_the_edge_at_the_exit_is_on_the_channel() -> None:
    # exit arc 255-285: the box's center is past the edge, its inner side inside.
    assert bboxInsideChannelMask(_box(270.0, OUTER + 8), _channel())


def test_a_box_straddling_the_edge_elsewhere_is_not() -> None:
    assert not bboxInsideChannelMask(_box(90.0, OUTER + 8), _channel())


def test_a_box_wholly_past_the_edge_at_the_exit_is_not() -> None:
    assert not bboxInsideChannelMask(_box(270.0, OUTER + 30), _channel())


def test_the_classification_channel_keeps_the_center_rule() -> None:
    # Its exit drops into the chute: a piece on its lip has been ejected.
    assert not bboxInsideChannelMask(_box(270.0, OUTER + 8), _channel(channel_id=4))
