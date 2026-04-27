from __future__ import annotations

import cv2
import numpy as np
import pytest

from rt.perception.c4_wall_phase import detect_c4_wall_phase, phase_delta_deg


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
