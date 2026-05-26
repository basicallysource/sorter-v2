from unittest.mock import patch

import pytest

from subsystems.classification_channel.simple_state_machine_rev01.spoke_home import (
    Annulus,
    angleForPoint,
    computeForwardAlignmentDeltaDeg,
    loadSpokeHomeGeometry,
)


def test_computeForwardAlignmentDeltaDeg_wraps_to_next_spoke() -> None:
    assert computeForwardAlignmentDeltaDeg(10.0, 20.0) == pytest.approx(10.0)
    assert computeForwardAlignmentDeltaDeg(70.0, 5.0) == pytest.approx(7.0)


def test_loadSpokeHomeGeometry_uses_classification_section_zero_point() -> None:
    saved = {
        "resolution": [400, 200],
        "channel_angles": {"classification_channel": 15.0},
        "section_zero_pts": {"classification_channel": [300, 100]},
        "arc_params": {
            "classification_channel": {
                "center": [200, 100],
                "inner_radius": 20,
                "outer_radius": 80,
                "resolution": [400, 200],
            }
        },
    }

    with patch(
        "subsystems.classification_channel.simple_state_machine_rev01.spoke_home.getChannelPolygons",
        return_value=saved,
    ):
        geometry = loadSpokeHomeGeometry((100, 200))

    assert geometry is not None
    annulus, zero_point = geometry
    assert annulus == Annulus(center_x=100.0, center_y=50.0, inner_radius=10.0, outer_radius=40.0)
    assert zero_point == (150.0, 50.0)


def test_loadSpokeHomeGeometry_falls_back_to_channel_angle() -> None:
    saved = {
        "resolution": [400, 200],
        "channel_angles": {"classification_channel": 90.0},
        "arc_params": {
            "classification_channel": {
                "center": [200, 100],
                "inner_radius": 20,
                "outer_radius": 80,
                "resolution": [400, 200],
            }
        },
    }

    with patch(
        "subsystems.classification_channel.simple_state_machine_rev01.spoke_home.getChannelPolygons",
        return_value=saved,
    ):
        geometry = loadSpokeHomeGeometry((100, 200))

    assert geometry is not None
    annulus, zero_point = geometry
    assert annulus.center_x == pytest.approx(100.0)
    assert annulus.center_y == pytest.approx(50.0)
    assert angleForPoint(zero_point[0], zero_point[1], annulus.center_x, annulus.center_y) == pytest.approx(90.0)
