import math
from dataclasses import replace

import numpy as np
import pytest

from defs.consts import CLASSIFICATION_CHANNEL_CLOCKWISE
from perception.arcs import (
    comForwardToPreciseEntryDeg,
    comInPreciseZone,
    exitComForwardDeg,
)
from perception.channel import buildChannelDef

CENTER = (200.0, 200.0)
RADIUS = 150.0


def _bbox_at(theta_deg: float) -> tuple[int, int, int, int]:
    rad = math.radians(theta_deg)
    cx = CENTER[0] + RADIUS * math.cos(rad)
    cy = CENTER[1] + RADIUS * math.sin(rad)
    ix, iy = int(round(cx)), int(round(cy))
    return (ix - 1, iy - 1, ix + 1, iy + 1)


def _make_channel(channel_id: int, *, reverse: bool | None = None):
    # Full-frame polygon → every bbox center is "on channel"; we are testing the
    # angle math, not the mask.
    poly = np.array([[0, 0], [400, 0], [400, 400], [0, 400]], dtype=np.float64)
    channel = buildChannelDef(
        channel_id=channel_id,
        polygon=poly,
        frame_shape=(400, 400),
        section_zero_angle=0.0,
        drop_arc=(200.0, 260.0),
        exit_arc=(120.0, 160.0),
        precise_arc=(160.0, 190.0),
        arc_center=CENTER,
    )
    return channel if reverse is None else replace(channel, reverse=reverse)


def test_channel_defaults_follow_configured_hardware_direction() -> None:
    assert _make_channel(4).reverse is (not CLASSIFICATION_CHANNEL_CLOCKWISE)
    assert _make_channel(2).reverse is False
    assert _make_channel(3).reverse is False


def test_reverse_exit_gap_measures_to_far_edge() -> None:
    ch = _make_channel(4, reverse=True)
    # Piece short of the exit on the reverse approach (high relative angle).
    gap = exitComForwardDeg([_bbox_at(250.0)], ch)
    assert gap is not None
    assert abs(gap - (250.0 - 159.0)) < 3.0  # ~91° to the reverse (far) entry edge


@pytest.mark.parametrize("reverse", [False, True])
def test_exit_gap_goes_negative_inside_exit_only_in_both_directions(reverse: bool) -> None:
    ch = _make_channel(4, reverse=reverse)
    # COM inside the exit-only arc reads as a small negative (past the entry edge).
    gap = exitComForwardDeg([_bbox_at(140.0)], ch)
    assert gap is not None
    assert -25.0 < gap < 0.0


def test_reverse_precise_gap_targets_entry_edge() -> None:
    ch = _make_channel(4, reverse=True)
    # precise arc = [160,190); reverse travel ENTERS at the high edge (~189), so
    # the target is the BEGINNING of the band, not its centre.
    assert comInPreciseZone([_bbox_at(250.0)], ch) is False
    far = comForwardToPreciseEntryDeg([_bbox_at(250.0)], ch)
    assert far is not None
    assert abs(far - (250.0 - 189.0)) < 3.0  # ~61° to the precise ENTRY edge
    # Parked at the entry edge: in precise, gap ~ 0 (the beginning, not the centre).
    assert comInPreciseZone([_bbox_at(189.0)], ch) is True
    at = comForwardToPreciseEntryDeg([_bbox_at(189.0)], ch)
    assert at is not None
    assert abs(at) < 3.0


def test_forward_precise_gap_targets_near_entry_edge() -> None:
    channel = _make_channel(4, reverse=False)
    assert comInPreciseZone([_bbox_at(140.0)], channel) is False
    gap = comForwardToPreciseEntryDeg([_bbox_at(140.0)], channel)
    assert gap is not None
    assert abs(gap - 20.0) < 3.0
    assert comInPreciseZone([_bbox_at(161.0)], channel) is True
    inside_gap = comForwardToPreciseEntryDeg([_bbox_at(161.0)], channel)
    assert inside_gap is not None
    assert -3.0 < inside_gap <= 0.0


def test_direction_changes_entry_edge_for_the_same_channel_and_piece() -> None:
    fwd = _make_channel(4, reverse=False)
    gap = exitComForwardDeg([_bbox_at(100.0)], fwd)
    assert gap is not None
    assert abs(gap - (120.0 - 100.0)) < 3.0  # ~20° to the forward near edge

    # The identical piece on the reverse channel reads the far edge instead —
    # a distinctly different value, confirming direction drives the result.
    rev = _make_channel(4, reverse=True)
    rev_gap = exitComForwardDeg([_bbox_at(100.0)], rev)
    assert rev_gap is not None
    assert rev_gap > 250.0
