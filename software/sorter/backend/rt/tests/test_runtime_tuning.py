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
        transport_speed_scale=8.0,
        stepper_degrees_per_tray_degree=36.0,
        transport_acceleration_microsteps_per_second_sq=80000,
        startup_purge_speed_scale=8.0,
        startup_purge_acceleration_microsteps_per_second_sq=80000,
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
        _zone_manager=SimpleNamespace(_max_zones=4, max_zones=4),
        _admission=SimpleNamespace(_max_zones=4, max_raw_detections=None),
        _transport_step_deg=6.0,
        _transport_max_step_deg=18.0,
        _transport_cooldown_s=0.08,
        _transport_velocity=SimpleNamespace(target_rpm=1.2),
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
        c1=SimpleNamespace(),
        c2=c2,
        c3=c3,
        c4=c4,
        orchestrator=SimpleNamespace(_slots=slots),
    )


def test_snapshot_reports_live_values() -> None:
    handle = _handle()

    payload = runtime_tuning.snapshot(handle)

    assert payload["channels"]["c4"]["transport_acceleration_usteps_per_s2"] == 80000
    assert payload["channels"]["c2"]["normal"]["steps_per_pulse"] == 1000
    assert payload["slots"]["c3_to_c4"] == 4


def test_update_c4_motion_and_backpressure_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c4": {
                    "max_zones": 3,
                    "transport_step_deg": 4.0,
                    "transport_max_step_deg": 12.0,
                    "transport_cooldown_ms": 140,
                    "transport_acceleration_usteps_per_s2": 60000,
                    "stepper_degrees_per_tray_degree": 42.0,
                    "transport_target_rpm": 0.9,
                }
            }
        },
    )

    assert handle.c4._zone_manager._max_zones == 3
    assert handle.c4._admission._max_zones == 3
    assert handle.orchestrator._slots[("c3", "c4")].capacity() == 3
    assert handle.c4._transport_step_deg == 4.0
    assert handle.c4._transport_cooldown_s == pytest.approx(0.14)
    assert (
        handle.irl.irl_config.classification_channel_config.transport_acceleration_microsteps_per_second_sq
        == 60000
    )
    assert (
        handle.irl.irl_config.classification_channel_config.stepper_degrees_per_tray_degree
        == 42.0
    )
    assert payload["channels"]["c4"]["stepper_degrees_per_tray_degree"] == 42.0
    assert payload["channels"]["c4"]["transport_target_rpm"] == 0.9


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
