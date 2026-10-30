from unittest.mock import patch

import pytest

from zones.model import ChannelZones, Ring, Span
from subsystems.classification_channel.two_piece.spoke_home import (
    Annulus,
    angleForPoint,
    computeForwardAlignmentDeltaDeg,
    loadSpokeHomeGeometry,
)


def test_computeForwardAlignmentDeltaDeg_wraps_to_next_spoke() -> None:
    assert computeForwardAlignmentDeltaDeg(10.0, 20.0) == pytest.approx(10.0)
    assert computeForwardAlignmentDeltaDeg(70.0, 5.0) == pytest.approx(7.0)


def _zones(reference_angle: float) -> ChannelZones:
    return ChannelZones(
        channel=4,
        frame=(400, 200),
        ring=Ring((200, 100), 20, 80, 80),
        drop=Span(10, 60),
        exit=Span(200, 240),
        reference_angle=reference_angle,
    )


def test_loadSpokeHomeGeometry_scales_the_ring_to_the_frame() -> None:
    with patch("zones.store.loadChannel", return_value=_zones(0.0)):
        geometry = loadSpokeHomeGeometry((100, 200))

    assert geometry is not None
    annulus, zero_point = geometry
    assert annulus == Annulus(center_x=100.0, center_y=50.0, inner_radius=10.0, outer_radius=40.0)
    assert zero_point == pytest.approx((140.0, 50.0))


def test_loadSpokeHomeGeometry_points_at_the_reference_angle() -> None:
    with patch("zones.store.loadChannel", return_value=_zones(90.0)):
        geometry = loadSpokeHomeGeometry((100, 200))

    assert geometry is not None
    annulus, zero_point = geometry
    assert annulus.center_x == pytest.approx(100.0)
    assert annulus.center_y == pytest.approx(50.0)
    assert angleForPoint(zero_point[0], zero_point[1], annulus.center_x, annulus.center_y) == pytest.approx(90.0)


def test_loadSpokeHomeGeometry_without_zones() -> None:
    with patch("zones.store.loadChannel", return_value=None):
        assert loadSpokeHomeGeometry((100, 200)) is None
