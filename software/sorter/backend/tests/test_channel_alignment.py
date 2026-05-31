from __future__ import annotations

import math

import numpy as np
import pytest

from vision import channel_alignment as ca


def test_polygon_key_for_role() -> None:
    assert ca.polygonKeyForRole("c_channel_2") == "second_channel"
    assert ca.polygonKeyForRole("c_channel_3") == "third_channel"
    assert ca.polygonKeyForRole("carousel") == "classification_channel"
    assert ca.polygonKeyForRole("classification_channel") == "classification_channel"
    assert ca.polygonKeyForRole("unknown") is None


def test_drop_start_angle_for_role() -> None:
    saved = {
        "arc_params": {
            "second": {"drop_start_angle": 47.0},
            "third": {"drop_start_angle": 132.0},
            "classification_channel": {"drop_start_angle": 305.0},
        }
    }
    assert ca.dropStartAngleForRole("c_channel_2", saved) == 47.0
    assert ca.dropStartAngleForRole("c_channel_3", saved) == 132.0
    assert ca.dropStartAngleForRole("carousel", saved) == 305.0


def test_drop_start_angle_returns_none_for_unknown_role() -> None:
    assert ca.dropStartAngleForRole("nonsense", None) is None
    assert ca.dropStartAngleForRole("nonsense", {"arc_params": {"second": {}}}) is None


def test_drop_start_angle_falls_back_to_legacy_zones() -> None:
    """When arc_params has no explicit drop_zone, the legacy section-based
    drop zone is still resolved via parseSavedChannelArcZones."""
    angle = ca.dropStartAngleForRole("c_channel_2", {})
    assert angle is not None
    assert 0.0 <= angle < 360.0


def test_drop_start_angle_reads_nested_drop_zone() -> None:
    saved = {
        "arc_params": {
            "second": {
                "center": [100, 100],
                "inner_radius": 50,
                "outer_radius": 100,
                "drop_zone": {"start_outer_angle": 47.5, "end_outer_angle": 110.0},
                "exit_zone": {"start_outer_angle": 250.0, "end_outer_angle": 320.0},
            },
        },
    }
    assert ca.dropStartAngleForRole("c_channel_2", saved) == pytest.approx(47.5)


@pytest.mark.parametrize(
    "drop_start, expected",
    [
        (270.0, 0.0),   # already at 12 o'clock
        (0.0, 90.0),    # 3 o'clock → rotate CCW 90°
        (180.0, -90.0), # 9 o'clock → rotate clockwise 90°
        (60.0, 150.0),
        (359.0, 89.0),
        (271.0, 1.0),
    ],
)
def test_alignment_rotation_deg(drop_start: float, expected: float) -> None:
    assert ca.alignmentRotationDeg(drop_start) == pytest.approx(expected)


def test_alignment_rotation_deg_180_equivalence() -> None:
    """drop_start=90° rotates the image by half a turn — sign of 180 is irrelevant."""
    assert abs(ca.alignmentRotationDeg(90.0)) == pytest.approx(180.0)


def test_alignment_rotation_deg_handles_none() -> None:
    assert ca.alignmentRotationDeg(None) == 0.0


def test_rotation_matrix_expands_canvas_for_45_deg() -> None:
    _, (new_w, new_h) = ca.rotationMatrixForImage(100, 100, 45.0)
    expected = int(math.ceil(100 * math.sqrt(2)))
    assert new_w == expected
    assert new_h == expected


def test_rotate_image_bgr_zero_returns_input_unchanged() -> None:
    image = np.random.randint(0, 255, (32, 48, 3), dtype=np.uint8)
    rotated = ca.rotateImageBgr(image, 0.0)
    assert rotated is image


def test_rotate_image_bgr_90_swaps_dimensions() -> None:
    image = np.zeros((30, 50, 3), dtype=np.uint8)
    image[5, 10] = [255, 0, 0]
    rotated = ca.rotateImageBgr(image, 90.0)
    # 90° rotation flips the aspect ratio. Bounds may grow by ±1 px from
    # rounding the affine matrix, so we only assert the flipped orientation.
    assert rotated.shape[0] >= 50 and rotated.shape[1] >= 30
    assert rotated.shape[0] > rotated.shape[1]
    blue_pixels = int(np.count_nonzero(rotated[..., 0] > 200))
    assert blue_pixels > 0


def test_rotate_image_bgr_uses_fill_color() -> None:
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    rotated = ca.rotateImageBgr(image, 45.0, fill=(123, 45, 67))
    corner = rotated[0, 0]
    assert tuple(int(value) for value in corner) == (123, 45, 67)


def test_drop_start_at_12_oclock_yields_no_rotation() -> None:
    """drop_start=270° already points to 12 o'clock — image should be unchanged."""
    image = np.random.randint(0, 255, (16, 16, 3), dtype=np.uint8)
    rotation = ca.alignmentRotationDeg(270.0)
    rotated = ca.rotateImageBgr(image, rotation)
    assert rotated is image
