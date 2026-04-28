from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rt.coupling.slots import CapacitySlot
from rt.services import runtime_tuning


class _FakeOrchestrator:
    def __init__(self, slots: dict) -> None:
        self._slots = slots
        self._vision_burst = {
            "name": "c1_c2_vision_burst",
            "target_low": 1,
            "target_high": 3,
            "clump_block_threshold": 0.65,
            "exit_queue_limit": 1,
        }
        self._c4_backpressure = {
            "name": "c1_c4_backpressure",
            "raw_high": 7,
            "dossier_high": 3,
        }
        self._recovery_admission = {
            "name": "c1_recovery_admission",
            "enabled": True,
            "c2_safe_capacity_eq": 14,
            "level_estimates_eq": [3, 6, 12, 25, 40],
            "last_decision": None,
        }

    def c1_c2_vision_controller_snapshot(self) -> dict:
        return dict(self._vision_burst)

    def update_c1_c2_vision_controller(self, **kwargs) -> dict:
        self._vision_burst.update(kwargs)
        return self.c1_c2_vision_controller_snapshot()

    def c1_c4_backpressure_snapshot(self) -> dict:
        return dict(self._c4_backpressure)

    def update_c1_c4_backpressure(self, **kwargs) -> dict:
        self._c4_backpressure.update(kwargs)
        return self.c1_c4_backpressure_snapshot()

    def c1_recovery_admission_snapshot(self) -> dict:
        return dict(self._recovery_admission)

    def update_c1_recovery_admission(self, **kwargs) -> dict:
        self._recovery_admission.update(kwargs)
        return self.c1_recovery_admission_snapshot()

    def c4_mode(self) -> str:
        return getattr(self, "_c4_mode", "runtime")

    def set_c4_mode(self, mode: str) -> str:
        if mode not in {"runtime", "sector_carousel"}:
            raise ValueError(f"bad c4_mode: {mode}")
        self._c4_mode = mode
        return mode

    def attach_sector_carousel_handler(self, handler: object) -> None:
        self._sector_carousel_handler = handler

    def sector_carousel_handler(self) -> object | None:
        return getattr(self, "_sector_carousel_handler", None)

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
        require_dropzone_clear_for_admission=True,
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
        _exit_handoff_min_interval_s=0.85,
        _transport_velocity=SimpleNamespace(target_rpm=1.2),
    )
    c3 = SimpleNamespace(
        _max_piece_count=3,
        _pulse_cooldown_s=0.12,
        _track_stale_s=0.5,
        _exit_near_arc=math.radians(20.0),
        _approach_near_arc=math.radians(45.0),
        _holdover_s=2.0,
        _exit_handoff_min_interval_s=0.85,
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
            require_dropzone_clear=True,
        ),
        _intake_half_width_deg=10.0,
        _transport_step_deg=3.0,
        _transport_max_step_deg=8.0,
        _transport_cooldown_s=0.18,
        _transport_velocity=SimpleNamespace(target_rpm=0.7),
        _classify_pretrigger_exit_lead_deg=72.0,
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
    c1 = SimpleNamespace(
        _sample_transport_step_deg=None,
        _pulse_cooldown_s=0.25,
        _startup_hold_s=2.0,
        _unconfirmed_pulse_limit=2,
        _observation_hold_s=12.0,
        _jam_timeout_s=4.0,
        _jam_min_pulses=3,
        _jam_cooldown_s=1.5,
        _max_recovery_cycles=5,
        _maintenance_pause_reason=None,
        arm_startup_hold=Mock(),
    )

    def pause_for_maintenance(reason: str = "maintenance") -> None:
        c1._maintenance_pause_reason = reason

    def resume_from_maintenance() -> None:
        c1._maintenance_pause_reason = None

    def c1_debug_snapshot() -> dict:
        return {
            "maintenance_pause_reason": c1._maintenance_pause_reason,
            "sample_transport_step_deg": c1._sample_transport_step_deg,
            "pulse_cooldown_s": c1._pulse_cooldown_s,
            "startup_hold_s": c1._startup_hold_s,
            "unconfirmed_pulse_limit": c1._unconfirmed_pulse_limit,
            "observation_hold_s": c1._observation_hold_s,
            "jam_timeout_s": c1._jam_timeout_s,
            "jam_min_pulses": c1._jam_min_pulses,
            "jam_cooldown_s": c1._jam_cooldown_s,
            "max_recovery_cycles": c1._max_recovery_cycles,
        }

    c1.pause_for_maintenance = pause_for_maintenance
    c1.resume_from_maintenance = resume_from_maintenance
    c1.debug_snapshot = c1_debug_snapshot

    return SimpleNamespace(
        irl=SimpleNamespace(
            irl_config=SimpleNamespace(
                feeder_config=feeder,
                classification_channel_config=classification,
            )
        ),
        c1=c1,
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
        orchestrator=_FakeOrchestrator(slots),
    )


def test_snapshot_reports_live_values() -> None:
    handle = _handle()

    payload = runtime_tuning.snapshot(handle)

    assert payload["channels"]["c4"]["transport_acceleration_usteps_per_s2"] == 4000
    assert payload["channels"]["c4"]["require_dropzone_clear_for_admission"] is True
    assert payload["channels"]["c4"]["intake_body_half_width_deg"] == 10.0
    assert payload["channels"]["c4"]["intake_guard_deg"] == 28.0
    assert payload["channels"]["c4"]["exit_release_shimmy_amplitude_deg"] == 1.5
    assert payload["channels"]["c4"]["exit_release_shimmy_cycles"] == 2
    assert payload["channels"]["c1"]["pulse_cooldown_s"] == 0.25
    assert payload["channels"]["c1"]["startup_hold_s"] == 2.0
    assert payload["channels"]["c1"]["unconfirmed_pulse_limit"] == 2
    assert payload["channels"]["c1"]["observation_hold_s"] == 12.0
    assert payload["channels"]["c1"]["jam_timeout_s"] == 4.0
    assert payload["channels"]["c1"]["vision_burst"]["target_low"] == 1
    assert payload["channels"]["c1"]["vision_burst"]["target_high"] == 3
    assert payload["channels"]["c1"]["vision_burst"]["exit_queue_limit"] == 1
    assert payload["channels"]["c1"]["c4_backpressure"]["raw_high"] == 7
    assert payload["channels"]["c1"]["c4_backpressure"]["dossier_high"] == 3
    assert payload["channels"]["c1"]["recovery_admission"]["enabled"] is True
    assert payload["channels"]["c1"]["recovery_admission"]["c2_safe_capacity_eq"] == 14
    assert payload["channels"]["c1"]["feed_inhibit"] is False
    assert payload["channels"]["c2"]["normal"]["steps_per_pulse"] == 1000
    assert payload["channels"]["c2"]["exit_handoff_min_interval_s"] == 0.85
    assert payload["channels"]["c3"]["exit_handoff_min_interval_s"] == 0.85
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
                    "startup_hold_s": 3.0,
                    "unconfirmed_pulse_limit": 3,
                    "observation_hold_s": 15.0,
                    "jam_timeout_s": 8.0,
                    "jam_min_pulses": 6,
                    "jam_cooldown_ms": 2500,
                    "max_recovery_cycles": 8,
                }
            }
        },
    )

    assert handle.c1._pulse_cooldown_s == pytest.approx(0.75)
    assert handle.c1._startup_hold_s == pytest.approx(3.0)
    handle.c1.arm_startup_hold.assert_called_once_with()
    assert handle.c1._unconfirmed_pulse_limit == 3
    assert handle.c1._observation_hold_s == pytest.approx(15.0)
    assert handle.c1._jam_timeout_s == pytest.approx(8.0)
    assert handle.c1._jam_min_pulses == 6
    assert handle.c1._jam_cooldown_s == pytest.approx(2.5)
    assert handle.c1._max_recovery_cycles == 8
    assert payload["channels"]["c1"]["pulse_cooldown_s"] == pytest.approx(0.75)
    assert payload["channels"]["c1"]["startup_hold_s"] == pytest.approx(3.0)
    assert payload["channels"]["c1"]["unconfirmed_pulse_limit"] == 3
    assert payload["channels"]["c1"]["observation_hold_s"] == pytest.approx(15.0)
    assert payload["channels"]["c1"]["jam_timeout_s"] == pytest.approx(8.0)


def test_update_c1_vision_burst_tuning_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c1": {
                    "vision_burst": {
                        "target_low": 2,
                        "target_high": 5,
                        "clump_block_threshold": 0.55,
                        "exit_queue_limit": 2,
                    }
                }
            }
        },
    )

    assert handle.orchestrator._vision_burst["target_low"] == 2
    assert handle.orchestrator._vision_burst["target_high"] == 5
    assert handle.orchestrator._vision_burst["clump_block_threshold"] == pytest.approx(0.55)
    assert handle.orchestrator._vision_burst["exit_queue_limit"] == 2
    assert payload["channels"]["c1"]["vision_burst"]["target_low"] == 2
    assert payload["channels"]["c1"]["vision_burst"]["target_high"] == 5


def test_update_c1_c4_backpressure_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c1": {
                    "c4_backpressure": {
                        "raw_high": 6,
                        "dossier_high": 4,
                        "raw_resume": 3,
                        "dossier_resume": 1,
                    }
                }
            }
        },
    )

    assert handle.orchestrator._c4_backpressure["raw_high"] == 6
    assert handle.orchestrator._c4_backpressure["dossier_high"] == 4
    assert handle.orchestrator._c4_backpressure["raw_resume"] == 3
    assert handle.orchestrator._c4_backpressure["dossier_resume"] == 1
    assert payload["channels"]["c1"]["c4_backpressure"]["raw_high"] == 6
    assert payload["channels"]["c1"]["c4_backpressure"]["dossier_high"] == 4
    assert payload["channels"]["c1"]["c4_backpressure"]["raw_resume"] == 3
    assert payload["channels"]["c1"]["c4_backpressure"]["dossier_resume"] == 1


def test_update_c1_recovery_admission_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c1": {
                    "recovery_admission": {
                        "enabled": False,
                        "c2_safe_capacity_eq": 18,
                        "level_estimates_eq": [2, 4, 9, 20, 35],
                    }
                }
            }
        },
    )

    snap = handle.orchestrator._recovery_admission
    assert snap["enabled"] is False
    assert snap["c2_safe_capacity_eq"] == 18
    assert snap["level_estimates_eq"] == [2, 4, 9, 20, 35]
    payload_admission = payload["channels"]["c1"]["recovery_admission"]
    assert payload_admission["enabled"] is False
    assert payload_admission["c2_safe_capacity_eq"] == 18


def test_update_c1_recovery_admission_rejects_invalid_estimates() -> None:
    handle = _handle()
    with pytest.raises(ValueError, match="level_estimates_eq"):
        runtime_tuning.apply_patch(
            handle,
            {
                "channels": {
                    "c1": {
                        "recovery_admission": {
                            "level_estimates_eq": [],
                        }
                    }
                }
            },
        )


def test_orchestrator_c4_mode_round_trip() -> None:
    from rt.services.sector_carousel import SectorCarouselHandler

    handle = _handle()
    handler = SectorCarouselHandler(
        c4_transport=lambda deg: True,
        c4_eject=lambda: True,
        distributor_port=type(
            "_D",
            (),
            {
                "handoff_request": lambda self, **kw: True,
                "handoff_commit": lambda self, *a, **kw: True,
                "pending_ready": lambda self, *a, **kw: False,
            },
        )(),
        rotation_chunk_settle_s=0.0,
    )
    handle.orchestrator.attach_sector_carousel_handler(handler)

    payload = runtime_tuning.apply_patch(
        handle,
        {"orchestrator": {"c4_mode": "sector_carousel"}},
    )
    assert handle.orchestrator._c4_mode == "sector_carousel"
    assert payload["orchestrator"]["c4_mode"] == "sector_carousel"

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "orchestrator": {
                "sector_carousel_handler": {
                    "timing": {
                        "settle_s": 0.5,
                        "rotate_cooldown_s": 8.0,
                        "sector_step_deg": 72.0,
                        "rotation_chunk_deg": 2.0,
                        "rotation_chunk_settle_s": 0.15,
                        "auto_rotate": True,
                    },
                }
            }
        },
    )
    snap = handler.snapshot()
    assert snap["timing"]["settle_s"] == pytest.approx(0.5)
    assert snap["timing"]["rotate_cooldown_s"] == pytest.approx(8.0)
    assert snap["sector_step_deg"] == pytest.approx(72.0)
    assert snap["timing"]["rotation_chunk_deg"] == pytest.approx(2.0)
    assert snap["timing"]["rotation_chunk_settle_s"] == pytest.approx(0.15)
    assert snap["auto_rotate"] is True
    sector = payload["orchestrator"]["sector_carousel_handler"]
    assert sector["timing"]["rotation_chunk_deg"] == pytest.approx(2.0)


def test_orchestrator_c4_mode_rejects_unknown_value() -> None:
    handle = _handle()
    for mode in ("magic", "carousel"):
        with pytest.raises(ValueError, match="c4_mode"):
            runtime_tuning.apply_patch(
                handle,
                {"orchestrator": {"c4_mode": mode}},
            )


def test_orchestrator_sector_carousel_tuning_rejects_unsafe_chunk() -> None:
    from rt.services.sector_carousel import SectorCarouselHandler

    handle = _handle()
    handle.orchestrator.attach_sector_carousel_handler(SectorCarouselHandler())
    with pytest.raises(ValueError, match="rotation_chunk_deg"):
        runtime_tuning.apply_patch(
            handle,
            {
                "orchestrator": {
                    "sector_carousel_handler": {
                        "timing": {"rotation_chunk_deg": 6.0}
                    }
                }
            },
        )


def test_update_c1_feed_inhibit_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {"channels": {"c1": {"feed_inhibit": True}}},
    )

    assert handle.c1._maintenance_pause_reason == "feed_inhibit"
    assert payload["channels"]["c1"]["feed_inhibit"] is True
    assert payload["channels"]["c1"]["feed_inhibit_reason"] == "feed_inhibit"

    payload = runtime_tuning.apply_patch(
        handle,
        {"channels": {"c1": {"feed_inhibit": False}}},
    )

    assert handle.c1._maintenance_pause_reason is None
    assert payload["channels"]["c1"]["feed_inhibit"] is False


def test_update_c4_motion_and_backpressure_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c4": {
                    "max_zones": 3,
                    "require_dropzone_clear_for_admission": False,
                    "intake_body_half_width_deg": 8.0,
                    "intake_guard_deg": 8.0,
                    "transport_step_deg": 4.0,
                    "transport_max_step_deg": 12.0,
                    "transport_cooldown_ms": 140,
                    "transport_acceleration_usteps_per_s2": 60000,
                    "transport_target_rpm": 0.9,
                    "stepper_degrees_per_tray_degree": 130.0 / 12.0,
                    "classify_pretrigger_exit_lead_deg": 80.0,
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
    assert handle.c4._admission._require_dropzone_clear is False
    assert (
        handle.irl.irl_config.classification_channel_config.require_dropzone_clear_for_admission
        is False
    )
    assert handle.c4._zone_manager._default_half_width == 8.0
    assert handle.c4._intake_half_width_deg == 8.0
    assert handle.c4._zone_manager._guard_deg == 8.0
    assert handle.c4._admission._guard_angle_deg == 8.0
    assert handle.orchestrator._slots[("c3", "c4")].capacity() == 3
    assert handle.c4._transport_step_deg == 4.0
    assert handle.c4._transport_cooldown_s == pytest.approx(0.14)
    assert handle.c4._classify_pretrigger_exit_lead_deg == 80.0
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
        == pytest.approx(130.0 / 12.0)
    )
    assert payload["channels"]["c4"]["stepper_degrees_per_tray_degree"] == pytest.approx(
        130.0 / 12.0
    )
    assert payload["channels"]["c4"]["transport_target_rpm"] == 0.9
    assert payload["channels"]["c4"]["require_dropzone_clear_for_admission"] is False
    assert payload["channels"]["c4"]["classify_pretrigger_exit_lead_deg"] == 80.0
    assert payload["channels"]["c4"]["exit_approach_angle_deg"] == 24.0
    assert payload["channels"]["c4"]["exit_approach_step_deg"] == 4.5
    assert payload["channels"]["c4"]["intake_body_half_width_deg"] == 8.0
    assert payload["channels"]["c4"]["intake_guard_deg"] == 8.0
    assert payload["channels"]["c4"]["exit_release_shimmy_amplitude_deg"] == 1.2
    assert payload["channels"]["c4"]["exit_release_shimmy_cycles"] == 3


def test_update_c4_rejects_unsafe_gear_ratio_live_patch() -> None:
    handle = _handle()

    with pytest.raises(ValueError, match="stepper_degrees_per_tray_degree"):
        runtime_tuning.apply_patch(
            handle,
            {"channels": {"c4": {"stepper_degrees_per_tray_degree": 0.2}}},
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
                    "exit_handoff_min_interval_ms": 950,
                    "handoff_retry_escalate_after": 3,
                    "handoff_retry_max_pulses": 2,
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
    assert handle.c2._exit_handoff_min_interval_s == pytest.approx(0.95)
    assert handle.c2._handoff_retry_escalate_after == 3
    assert handle.c2._handoff_retry_max_pulses == 2
    assert handle.irl.irl_config.feeder_config.second_rotor_normal.steps_per_pulse == 700
    assert (
        handle.irl.irl_config.feeder_config.second_rotor_normal.acceleration_microsteps_per_second_sq
        == 60000
    )


def test_update_c3_exit_handoff_spacing_live() -> None:
    handle = _handle()

    payload = runtime_tuning.apply_patch(
        handle,
        {
            "channels": {
                "c3": {
                    "exit_handoff_min_interval_s": 1.1,
                    "holdover_ms": 1200,
                    "handoff_retry_escalate_after": 4,
                    "handoff_retry_max_pulses": 3,
                }
            }
        },
    )

    assert handle.c3._exit_handoff_min_interval_s == pytest.approx(1.1)
    assert handle.c3._holdover_s == pytest.approx(1.2)
    assert handle.c3._handoff_retry_escalate_after == 4
    assert handle.c3._handoff_retry_max_pulses == 3
    assert payload["channels"]["c3"]["exit_handoff_min_interval_s"] == pytest.approx(1.1)
    assert payload["channels"]["c3"]["handoff_retry_max_pulses"] == 3


def test_update_rejects_unknown_fields() -> None:
    handle = _handle()

    with pytest.raises(ValueError, match="unsupported tuning field"):
        runtime_tuning.apply_patch(handle, {"channels": {"c4": {"mystery": 1}}})
