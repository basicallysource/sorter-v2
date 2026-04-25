from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from rt.coupling.slots import CapacitySlot
from rt.services import runtime_tuning


def _rotor(steps: int, speed: int, delay: int, accel: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        steps_per_pulse=steps,
        microsteps_per_second=speed,
        delay_between_pulse_ms=delay,
        acceleration_microsteps_per_second_sq=accel,
    )


def _handle() -> SimpleNamespace:
    feeder = SimpleNamespace(
        first_rotor=_rotor(100, 2000, 1000),
        second_rotor_normal=_rotor(1000, 5000, 250),
        second_rotor_precision=_rotor(400, 2500, 1000),
        third_rotor_normal=_rotor(2500, 12000, 120),
        third_rotor_precision=_rotor(300, 3000, 1000),
        classification_channel_eject=_rotor(1000, 3400, 400, 2500),
    )
    classification = SimpleNamespace(
        max_zones=4,
        intake_body_half_width_deg=10.0,
        intake_guard_deg=28.0,
        transport_speed_scale=4.0,
        stepper_degrees_per_tray_degree=36.0,
        transport_acceleration_microsteps_per_second_sq=4000,
        startup_purge_speed_scale=4.0,
        startup_purge_acceleration_microsteps_per_second_sq=20000,
        exit_release_shimmy_amplitude_deg=1.5,
        exit_release_shimmy_cycles=2,
        exit_release_shimmy_microsteps_per_second=4200,
        exit_release_shimmy_acceleration_microsteps_per_second_sq=9000,
    )
    c2 = SimpleNamespace(
        _max_piece_count=5,
        _pulse_cooldown_s=0.12,
        _advance_interval_s=1.2,
        _track_stale_s=0.5,
        _exit_near_arc=math.radians(30.0),
        _approach_near_arc=math.radians(45.0),
        _intake_near_arc=math.radians(30.0),
        _wiggle_stall_s=0.6,
        _wiggle_cooldown_s=1.2,
        _transport_velocity=SimpleNamespace(target_rpm=1.2),
    )
    c3 = SimpleNamespace(
        _max_piece_count=3,
        _pulse_cooldown_s=0.12,
        _track_stale_s=0.5,
        _exit_near_arc=math.radians(20.0),
        _approach_near_arc=math.radians(45.0),
        _wiggle_stall_s=0.6,
        _wiggle_cooldown_s=1.2,
        _holdover_s=2.0,
        _transport_velocity=SimpleNamespace(target_rpm=1.2),
    )
    c4 = SimpleNamespace(
        _zone_manager=SimpleNamespace(
            _max_zones=4,
            max_zones=4,
            _default_half_width=10.0,
            guard_angle_deg=28.0,
        ),
        _admission=SimpleNamespace(
            _max_zones=4,
            max_raw_detections=None,
            _guard_angle_deg=28.0,
        ),
        _intake_half_width_deg=10.0,
        _transport_step_deg=3.0,
        _transport_max_step_deg=8.0,
        _transport_cooldown_s=0.18,
        _transport_velocity=SimpleNamespace(target_rpm=0.7),
        _exit_approach_angle_deg=36.0,
        _exit_approach_step_deg=3.0,
        _shimmy_step_deg=1.5,
        _idle_jog_enabled=True,
        _idle_jog_step_deg=2.0,
        _idle_jog_cooldown_s=0.5,
        _unjam_enabled=True,
        _unjam_stall_s=2.5,
        _unjam_min_progress_deg=2.0,
        _unjam_cooldown_s=3.0,
        _unjam_reverse_deg=3.0,
        _unjam_forward_deg=9.0,
        _track_stale_s=0.5,
        _reconcile_min_hit_count=2,
        _reconcile_min_score=0.35,
        _reconcile_min_age_s=0.2,
    )
    slots = {
        ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
        ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        ("c3", "c4"): CapacitySlot("c3_to_c4", 4),
        ("c4", "distributor"): CapacitySlot("c4_to_dist", 1),
    }
    return SimpleNamespace(
        irl=SimpleNamespace(
            irl_config=SimpleNamespace(
                feeder_config=feeder,
                classification_channel_config=classification,
            )
        ),
        c1=SimpleNamespace(
            _sample_transport_step_deg=None,
            _pulse_cooldown_s=0.25,
            _jam_timeout_s=4.0,
            _jam_min_pulses=3,
            _jam_cooldown_s=1.5,
            _max_recovery_cycles=5,
        ),
        c2=c2,
        c3=c3,
        c4=c4,
        distributor=SimpleNamespace(
            _simulate_chute=False,
            _simulated_chute_move_s=0.8,
            _chute_settle_s=0.4,
            _fall_time_s=1.5,
            _position_timeout_s=6.0,
            _ready_timeout_s=60.0,
        ),
        orchestrator=SimpleNamespace(_slots=slots),
    )


def test_snapshot_reports_live_values() -> None:
    handle = _handle()

    payload = runtime_tuning.snapshot(handle)

    assert payload["channels"]["c4"]["transport_acceleration_usteps_per_s2"] == 4000
    assert payload["channels"]["c4"]["intake_body_half_width_deg"] == 10.0
    assert payload["channels"]["c4"]["intake_guard_deg"] == 28.0
    assert payload["channels"]["c4"]["exit_release_shimmy_amplitude_deg"] == 1.5
    assert payload["channels"]["c4"]["exit_release_shimmy_cycles"] == 2
    assert payload["channels"]["c1"]["pulse_cooldown_s"] == 0.25
    assert payload["channels"]["c1"]["jam_timeout_s"] == 4.0
    assert payload["channels"]["c2"]["normal"]["steps_per_pulse"] == 1000
    assert payload["channels"]["distributor"]["simulate_chute"] is False
    assert payload["channels"]["distributor"]["simulated_chute_move_s"] == 0.8
    assert payload["slots"]["c3_to_c4"] == 4


def test_update_c1_feed_and_jam_tuning_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c1": {
                    "pulse_cooldown_ms": 750,
                    "jam_timeout_s": 8.0,
                    "jam_min_pulses": 6,
                    "jam_cooldown_ms": 2500,
                    "max_recovery_cycles": 8,
                }
            }
        },
    )

    assert handle.c1._pulse_cooldown_s == pytest.approx(0.75)
    assert handle.c1._jam_timeout_s == pytest.approx(8.0)
    assert handle.c1._jam_min_pulses == 6
    assert handle.c1._jam_cooldown_s == pytest.approx(2.5)
    assert handle.c1._max_recovery_cycles == 8
    assert payload["channels"]["c1"]["pulse_cooldown_s"] == pytest.approx(0.75)
    assert payload["channels"]["c1"]["jam_timeout_s"] == pytest.approx(8.0)


def test_update_c4_motion_and_backpressure_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c4": {
                    "max_zones": 3,
                    "intake_body_half_width_deg": 8.0,
                    "intake_guard_deg": 8.0,
                    "transport_step_deg": 4.0,
                    "transport_max_step_deg": 12.0,
                    "transport_cooldown_ms": 140,
                    "transport_acceleration_usteps_per_s2": 60000,
                    "transport_target_rpm": 0.9,
                    "exit_approach_angle_deg": 24.0,
                    "exit_approach_step_deg": 4.5,
                    "exit_release_shimmy_amplitude_deg": 1.2,
                    "exit_release_shimmy_cycles": 3,
                }
            }
        },
    )

    assert handle.c4._zone_manager._max_zones == 3
    assert handle.c4._admission._max_zones == 3
    assert handle.c4._zone_manager._default_half_width == 8.0
    assert handle.c4._intake_half_width_deg == 8.0
    assert handle.c4._zone_manager._guard_deg == 8.0
    assert handle.c4._admission._guard_angle_deg == 8.0
    assert handle.orchestrator._slots[("c3", "c4")].capacity() == 3
    assert handle.c4._transport_step_deg == 4.0
    assert handle.c4._transport_cooldown_s == pytest.approx(0.14)
    assert handle.c4._exit_approach_angle_deg == 24.0
    assert handle.c4._exit_approach_step_deg == 4.5
    assert handle.c4._shimmy_step_deg == 1.2
    assert (
        handle.irl.irl_config.classification_channel_config.transport_acceleration_microsteps_per_second_sq
        == 60000
    )
    assert (
        handle.irl.irl_config.classification_channel_config.exit_release_shimmy_amplitude_deg
        == 1.2
    )
    assert handle.irl.irl_config.classification_channel_config.positioning_window_deg == 24.0
    assert handle.irl.irl_config.classification_channel_config.exit_approach_step_deg == 4.5
    assert handle.irl.irl_config.classification_channel_config.exit_release_shimmy_cycles == 3
    assert (
        handle.irl.irl_config.classification_channel_config.stepper_degrees_per_tray_degree
        == 36.0
    )
    assert payload["channels"]["c4"]["stepper_degrees_per_tray_degree"] == 36.0
    assert payload["channels"]["c4"]["transport_target_rpm"] == 0.9
    assert payload["channels"]["c4"]["exit_approach_angle_deg"] == 24.0
    assert payload["channels"]["c4"]["exit_approach_step_deg"] == 4.5
    assert payload["channels"]["c4"]["intake_body_half_width_deg"] == 8.0
    assert payload["channels"]["c4"]["intake_guard_deg"] == 8.0
    assert payload["channels"]["c4"]["exit_release_shimmy_amplitude_deg"] == 1.2
    assert payload["channels"]["c4"]["exit_release_shimmy_cycles"] == 3


def test_update_c4_rejects_gear_ratio_live_patch() -> None:
    handle = _handle()

    with pytest.raises(ValueError, match="unsupported tuning field"):
        runtime_tuning.apply_patch(
            handle,
            {"channels": {"c4": {"stepper_degrees_per_tray_degree": 42.0}}},
        )


def test_update_distributor_simulated_chute_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "distributor": {
                    "simulate_chute": True,
                    "simulated_chute_move_ms": 1200,
                    "chute_settle_ms": 250,
                    "fall_time_ms": 1600,
                    "position_timeout_s": 10.0,
                    "ready_timeout_s": 45.0,
                }
            }
        },
    )

    assert handle.distributor._simulate_chute is True
    assert handle.distributor._simulated_chute_move_s == pytest.approx(1.2)
    assert handle.distributor._chute_settle_s == pytest.approx(0.25)
    assert handle.distributor._fall_time_s == pytest.approx(1.6)
    assert handle.distributor._position_timeout_s == pytest.approx(10.0)
    assert handle.distributor._ready_timeout_s == pytest.approx(45.0)
    assert payload["channels"]["distributor"]["simulate_chute"] is True
    assert payload["channels"]["distributor"]["simulated_chute_move_s"] == pytest.approx(1.2)


def test_update_c2_flow_and_profile_live() -> None:
    handle = _handle()

    runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c2": {
                    "max_piece_count": 2,
                    "pulse_cooldown_ms": 240,
                    "exit_near_arc_deg": 24.0,
                    "approach_near_arc_deg": 36.0,
                    "normal": {
                        "steps_per_pulse": 700,
                        "microsteps_per_second": 4200,
                        "acceleration_usteps_per_s2": 60000,
                    },
                }
            }
        },
    )

    assert handle.c2._max_piece_count == 2
    assert handle.c2._pulse_cooldown_s == pytest.approx(0.24)
    assert math.degrees(handle.c2._exit_near_arc) == pytest.approx(24.0)
    assert handle.irl.irl_config.feeder_config.second_rotor_normal.steps_per_pulse == 700
    assert (
        handle.irl.irl_config.feeder_config.second_rotor_normal.acceleration_microsteps_per_second_sq
        == 60000
    )


def test_update_rejects_unknown_fields() -> None:
    handle = _handle()

    with pytest.raises(ValueError, match="unsupported tuning field"):
        runtime_tuning.apply_patch(handle, {"channels": {"c4": {"mystery": 1}}})
