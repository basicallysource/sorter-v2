from __future__ import annotations

import pytest

from irl.config import mkIRLConfig
from subsystems.classification_channel.five_sector_platter import (
    C4FiveSectorPlatter,
    C4SectorDetection,
    C4SectorState,
    angle_deg_for_point,
)


def test_sector_motion_uses_c_channel_gear_ratio_and_microsteps() -> None:
    platter = C4FiveSectorPlatter()

    assert platter.sector_size_deg == pytest.approx(72.0)
    assert platter.motor_microsteps_per_output_revolution == pytest.approx(
        200 * 8 * (130 / 12)
    )
    assert platter.rounded_motor_microsteps_per_output_revolution == 17333

    move = platter.sector_move_plan(0, 1, direction="cw")

    assert move.sector_delta == 1
    assert move.output_delta_deg == pytest.approx(72.0)
    assert move.motor_microsteps == 3467
    assert move.motor_delta_deg == pytest.approx(780.075)
    assert platter.motor_microsteps_to_output_degrees(move.motor_microsteps) == (
        pytest.approx(72.006923, rel=1e-6)
    )


def test_adjacent_sector_rounding_uses_absolute_positions_without_turn_drift() -> None:
    platter = C4FiveSectorPlatter()

    adjacent_steps = [
        platter.sector_delta_microsteps(idx, (idx + 1) % 5, direction="cw")
        for idx in range(5)
    ]

    assert adjacent_steps == [3467, 3466, 3467, 3467, 3466]
    assert sum(adjacent_steps) == platter.rounded_motor_microsteps_per_output_revolution


def test_shortest_sector_move_can_choose_reverse_wraparound() -> None:
    platter = C4FiveSectorPlatter()

    reverse = platter.sector_move_plan(0, 4, direction="shortest")
    forward = platter.sector_move_plan(4, 0, direction="cw")

    assert reverse.sector_delta == -1
    assert reverse.output_delta_deg == pytest.approx(-72.0)
    assert reverse.motor_microsteps == -3466
    assert forward.sector_delta == 1
    assert forward.motor_microsteps == 3466


def test_sector_move_applies_profile_and_exact_microsteps_to_stepper() -> None:
    class Stepper:
        def __init__(self) -> None:
            self.speed_limits: list[tuple[int, int]] = []
            self.accelerations: list[int] = []
            self.moves: list[int] = []

        def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
            self.speed_limits.append((min_speed, max_speed))

        def set_acceleration(self, acceleration: int) -> None:
            self.accelerations.append(acceleration)

        def move_steps(self, steps: int) -> bool:
            self.moves.append(steps)
            return True

    platter = C4FiveSectorPlatter()
    stepper = Stepper()

    ok = platter.sector_move_plan(2, 3, direction="cw").apply_to_stepper(stepper)

    assert ok is True
    assert stepper.speed_limits == [(16, 4000)]
    assert stepper.accelerations == [2500]
    assert stepper.moves == [3467]


def test_angle_mapping_uses_wall_phase_as_sector_boundary() -> None:
    platter = C4FiveSectorPlatter()

    assert platter.sector_for_angle(36.0, wall_offset_deg=0.0) == 0
    assert platter.sector_for_angle(71.9, wall_offset_deg=0.0) == 0
    assert platter.sector_for_angle(72.0, wall_offset_deg=0.0) == 1
    assert platter.sector_for_angle(359.0, wall_offset_deg=0.0) == 4

    assert platter.sector_for_angle(45.0, wall_offset_deg=10.0) == 0
    assert platter.sector_for_angle(5.0, wall_offset_deg=10.0) == 4
    assert platter.sector_center_angle_deg(0, wall_offset_deg=10.0) == pytest.approx(46.0)


def test_bbox_detection_uses_existing_polar_angle_convention() -> None:
    center_xy = (100.0, 100.0)

    assert angle_deg_for_point(120.0, 100.0, center_xy=center_xy) == pytest.approx(0.0)
    assert angle_deg_for_point(100.0, 120.0, center_xy=center_xy) == pytest.approx(90.0)
    assert angle_deg_for_point(80.0, 100.0, center_xy=center_xy) == pytest.approx(180.0)
    assert angle_deg_for_point(100.0, 80.0, center_xy=center_xy) == pytest.approx(270.0)

    detection = C4SectorDetection.from_bbox(
        (110.0, 110.0, 130.0, 130.0),
        center_xy=center_xy,
        confidence=0.7,
        track_id=42,
    )

    assert detection.angle_deg == pytest.approx(45.0)
    assert detection.confidence == pytest.approx(0.7)
    assert detection.track_id == 42


def test_detections_roll_up_to_sector_occupancy() -> None:
    platter = C4FiveSectorPlatter()
    detections = [
        C4SectorDetection(angle_deg=36.0, confidence=0.9, track_id="a"),
        C4SectorDetection(angle_deg=40.0, confidence=0.8, track_id="b"),
        C4SectorDetection(angle_deg=145.0, confidence=0.2, track_id="ignored"),
        C4SectorDetection(angle_deg=180.0, confidence=0.75, track_id="c"),
    ]

    snapshot = platter.occupancy_from_detections(
        detections,
        min_confidence=0.5,
        handoff_sector=3,
        exit_sector=4,
    )

    assert [sector.state for sector in snapshot] == [
        C4SectorState.OCCUPIED,
        C4SectorState.FREE,
        C4SectorState.OCCUPIED,
        C4SectorState.HANDOFF,
        C4SectorState.EXIT,
    ]
    assert snapshot[0].detection_count == 2
    assert snapshot[0].max_confidence == pytest.approx(0.9)
    assert snapshot[0].track_ids == ("a", "b")
    assert snapshot[2].detection_count == 1
    assert snapshot[3].occupied is False
    assert snapshot[4].occupied is False


def test_from_irl_config_uses_classification_c_channel_axis(tmp_path, monkeypatch) -> None:
    machine_params_path = tmp_path / "machine_params.toml"
    machine_params_path.write_text(
        """
[machine_setup]
type = "classification_channel"

[cameras]
layout = "split_feeder"
c_channel_2 = 0
c_channel_3 = 1
classification_channel = 2
""".strip()
    )
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(machine_params_path))

    config = mkIRLConfig()
    platter = C4FiveSectorPlatter.from_irl_config(config)

    assert platter.sector_count == 5
    assert platter.gear_ratio == pytest.approx(130 / 12)
    assert platter.microsteps == 8
    assert platter.motor_steps_per_revolution == 200

    move = platter.sector_move_plan(0, 1, direction="cw")
    assert move.motor_microsteps == 3467
    assert move.motion_profile.max_speed_microsteps_per_second == 3400
    assert move.motion_profile.acceleration_microsteps_per_second_sq == 2500
