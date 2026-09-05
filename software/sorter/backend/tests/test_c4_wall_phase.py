from __future__ import annotations

import cv2
import numpy as np
import pytest
from pathlib import Path

from vision.c4_wall_phase import detect_c4_wall_phase, phase_delta_deg, wall_geometry_from_arc


def _synthetic_rotor(*, phase_deg: float = 18.0) -> np.ndarray:
    image = np.zeros((720, 720, 3), dtype=np.uint8)
    center = (360, 360)
    cv2.circle(image, center, 330, (210, 210, 210), -1)
    cv2.circle(image, center, 125, (0, 0, 0), -1)
    for i in range(5):
        angle = np.deg2rad(phase_deg + i * 72.0)
        inner = (
            int(round(center[0] + np.cos(angle) * 130)),
            int(round(center[1] + np.sin(angle) * 130)),
        )
        outer = (
            int(round(center[0] + np.cos(angle) * 300)),
            int(round(center[1] + np.sin(angle) * 300)),
        )
        cv2.line(image, inner, outer, (105, 105, 105), 10, cv2.LINE_AA)
        cv2.line(image, inner, outer, (245, 245, 245), 3, cv2.LINE_AA)
    cv2.rectangle(image, (330, 360), (395, 720), (0, 0, 0), -1)
    return image


def test_detect_c4_wall_phase_estimates_five_wall_offset() -> None:
    result = detect_c4_wall_phase(
        _synthetic_rotor(phase_deg=22.0),
        sector_count=5,
        downscale=0.5,
    )

    assert result.ok is True
    assert len(result.wall_angles_deg) >= 4
    assert result.sector_offset_deg == pytest.approx(22.0, abs=3.0)


def test_phase_delta_uses_repeating_sector_phase() -> None:
    assert phase_delta_deg(
        current_offset_deg=68.0,
        target_wall_angle_deg=270.0,
        sector_count=5,
    ) == pytest.approx(-14.0)
    assert phase_delta_deg(
        current_offset_deg=4.0,
        target_wall_angle_deg=70.0,
        sector_count=5,
    ) == pytest.approx(-6.0)


@pytest.mark.parametrize("phase", [0.5, 18, 43, 71.5])
def test_calibrated_off_center_rotor_on_bright_cluttered_table(phase):
    rotor = _synthetic_rotor(phase_deg=phase)
    image = np.full((850, 1100, 3), 180, np.uint8)
    # Rotation center is deliberately nowhere near the frame center.
    image[40:760, 60:780] = rotor
    cv2.rectangle(image, (800, 30), (1090, 780), (245, 245, 245), -1)
    result = detect_c4_wall_phase(image, center_xy=(420, 400), radius_px=330)
    assert result.ok
    assert result.geometry_source == "calibration"
    assert abs(phase_delta_deg(current_offset_deg=result.sector_offset_deg,
                              target_wall_angle_deg=phase)) < 2
    assert result.max_residual_deg < 3


def test_bright_background_does_not_become_a_valid_rotor():
    result = detect_c4_wall_phase(np.full((600, 900, 3), 180, np.uint8))
    assert not result.ok and result.sector_offset_deg is None
    assert "calibrated geometry required" in result.message


def test_blank_calibrated_disc_does_not_invent_dividers():
    image = np.full((720, 720, 3), 180, np.uint8)
    cv2.circle(image, (360, 360), 330, (220, 220, 220), 5)
    cv2.circle(image, (360, 360), 100, (40, 40, 40), -1)
    assert not detect_c4_wall_phase(image, center_xy=(360, 360), radius_px=330).ok


def test_two_visible_walls_are_not_enough():
    image = np.full((720, 720, 3), 210, np.uint8)
    for angle in (20, 92):
        a = np.deg2rad(angle)
        cv2.line(image, (360, 360), (round(360+300*np.cos(a)), round(360+300*np.sin(a))), (60, 60, 60), 8)
    assert not detect_c4_wall_phase(image, center_xy=(360, 360), radius_px=330).ok


def test_arc_scaling_preserves_pixel_coordinates_and_rejects_stretch():
    arc = {"center": [500, 260], "resolution": [960, 540], "outer_radius": 280}
    assert wall_geometry_from_arc(arc, (1080, 1920, 3)) == {"center_xy": (1000, 520), "radius_px": 560}
    with pytest.raises(ValueError, match="aspect ratio"):
        wall_geometry_from_arc(arc, (1000, 1000, 3))


def test_two_competing_five_wall_grids_are_ambiguous():
    from vision.c4_wall_phase import WallLine, _fit_sector_phase
    candidates = [WallLine(0, 0, 100, 100, angle, 100, 0, 100, 300)
                  for phase in (0, 20) for angle in (phase+i*72 for i in range(5))]
    assert _fit_sector_phase(candidates, sector_count=5) is None


def test_repeated_fragments_of_one_wall_do_not_outvote_the_grid():
    from vision.c4_wall_phase import WallLine, _fit_sector_phase
    def line(angle):
        return WallLine(0, 0, 100, 100, angle, 100, 0, 100, 300)
    candidates = [line(22+i*72) for i in range(5)] + [line(40)]*200
    assert _fit_sector_phase(candidates, sector_count=5) == pytest.approx(22, abs=0.5)


def test_real_rotor_on_workbench_has_five_consistent_walls():
    image = cv2.imread(str(Path(__file__).parent / "fixtures/c4_wall_phase/empty_rotor.jpg"))
    assert image is not None
    result = detect_c4_wall_phase(image, center_xy=(502.5, 257), radius_px=280)
    assert result.ok and len(result.wall_angles_deg) == 5
    assert result.max_residual_deg < 2
    assert abs(phase_delta_deg(current_offset_deg=result.sector_offset_deg, target_wall_angle_deg=0)) < 3
    assert not detect_c4_wall_phase(image).ok  # no made-up center from the table


@pytest.mark.parametrize("rotation", [-47, -15, 23, 68])
def test_real_rotor_known_image_rotations(rotation):
    image = cv2.imread(str(Path(__file__).parent / "fixtures/c4_wall_phase/empty_rotor.jpg"))
    center = (502.5, 257)
    base = detect_c4_wall_phase(image, center_xy=center, radius_px=280)
    transform = cv2.getRotationMatrix2D(center, rotation, 1.0)
    rotated = cv2.warpAffine(image, transform, (960, 540), borderValue=(180, 180, 180))
    result = detect_c4_wall_phase(rotated, center_xy=center, radius_px=280)
    assert result.ok and len(result.wall_angles_deg) >= 4
    assert abs(phase_delta_deg(current_offset_deg=result.sector_offset_deg,
                              target_wall_angle_deg=base.sector_offset_deg-rotation)) < 2
