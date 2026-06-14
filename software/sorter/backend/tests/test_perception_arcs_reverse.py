"""Direction-awareness tests for the exit/precise converge math.

C4 (the carousel classification channel) travels REVERSE — the piece approaches
the exit from the high-relative-angle side, so the forward-distance helpers must
measure the gap to the FAR edge of the exit-only arc, not the near edge. C2/C3
feeder ejects stay FORWARD and must be byte-for-byte unchanged. The flag rides on
``ChannelDef.reverse`` (set per ``REVERSE_TRAVEL_CHANNELS`` — channel 4 only).

Geometry (section_zero = 0, so relative angle == image angle):
  exit_only arc = [120, 160)   precise arc = [160, 190)
Forward near edge of exit_only = 120; reverse (far) entry edge = 159.
Precise centre ≈ 175.
"""

import math

import numpy as np

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


def _make_channel(channel_id: int):
    # Full-frame polygon → every bbox center is "on channel"; we are testing the
    # angle math, not the mask.
    poly = np.array([[0, 0], [400, 0], [400, 400], [0, 400]], dtype=np.float64)
    return buildChannelDef(
        channel_id=channel_id,
        polygon=poly,
        frame_shape=(400, 400),
        section_zero_angle=0.0,
        drop_arc=(200.0, 260.0),
        exit_arc=(120.0, 160.0),
        precise_arc=(160.0, 190.0),
        arc_center=CENTER,
    )


def test_reverse_flag_set_only_for_channel_4() -> None:
    assert _make_channel(4).reverse is True
    assert _make_channel(2).reverse is False
    assert _make_channel(3).reverse is False


def test_reverse_exit_gap_measures_to_far_edge() -> None:
    ch = _make_channel(4)
    # Piece short of the exit on the reverse approach (high relative angle).
    gap = exitComForwardDeg([_bbox_at(250.0)], ch)
    assert gap is not None
    assert abs(gap - (250.0 - 159.0)) < 3.0  # ~91° to the reverse (far) entry edge


def test_reverse_exit_gap_goes_negative_inside_exit_only() -> None:
    ch = _make_channel(4)
    # COM inside the exit-only arc reads as a small negative (past the entry edge).
    gap = exitComForwardDeg([_bbox_at(140.0)], ch)
    assert gap is not None
    assert -25.0 < gap < 0.0


def test_reverse_precise_gap_targets_entry_edge() -> None:
    ch = _make_channel(4)
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


def test_forward_channel_unchanged_uses_near_edge() -> None:
    # A forward channel (C2) with the SAME arcs measures to the NEAR edge (120),
    # exactly the legacy behavior — proving the reverse branch is isolated.
    fwd = _make_channel(2)
    gap = exitComForwardDeg([_bbox_at(100.0)], fwd)
    assert gap is not None
    assert abs(gap - (120.0 - 100.0)) < 3.0  # ~20° to the forward near edge

    # The identical piece on the reverse channel reads the far edge instead —
    # a distinctly different value, confirming direction drives the result.
    rev = _make_channel(4)
    rev_gap = exitComForwardDeg([_bbox_at(100.0)], rev)
    assert rev_gap is not None
    assert rev_gap > 250.0
