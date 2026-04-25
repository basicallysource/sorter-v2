"""Live tuning surface for rt runtime flow and motion parameters.

The values exposed here are deliberately the same runtime/config fields the
machine already uses. Updates are in-memory and take effect on the next tick or
move; they do not persist back to TOML.
"""

from __future__ import annotations

import math
from typing import Any


_CHANNEL_ALIASES = {
    "feeder": "c1",
    "c_channel_1": "c1",
    "c_channel_2": "c2",
    "second_channel": "c2",
    "c_channel_3": "c3",
    "third_channel": "c3",
    "carousel": "c4",
    "classification_channel": "c4",
    "dist": "distributor",
    "chute": "distributor",
}

_SLOT_ALIASES = {
    "c4_to_distributor": "c4_to_distributor",
    "c4_to_dist": "c4_to_distributor",
    "c1_to_c2": "c1_to_c2",
    "c2_to_c3": "c2_to_c3",
    "c3_to_c4": "c3_to_c4",
}

_SLOT_EDGE_BY_KEY = {
    "c1_to_c2": ("c1", "c2"),
    "c2_to_c3": ("c2", "c3"),
    "c3_to_c4": ("c3", "c4"),
    "c4_to_distributor": ("c4", "distributor"),
}


def snapshot(handle: Any) -> dict[str, Any]:
    """Return current live tuning values for UI/API consumers."""

    irl = getattr(handle, "irl", None)
    feeder_cfg = _feeder_cfg(irl)
    class_cfg = _classification_cfg(irl)
    c1 = getattr(handle, "c1", None)
    c2 = getattr(handle, "c2", None)
    c3 = getattr(handle, "c3", None)
    c4 = getattr(handle, "c4", None)
    distributor = getattr(handle, "distributor", None)
    return {
        "version": 1,
        "channels": {
            "c1": _c1_snapshot(c1, feeder_cfg),
            "c2": _c2_snapshot(c2, feeder_cfg),
            "c3": _c3_snapshot(c3, feeder_cfg),
            "c4": _c4_snapshot(c4, class_cfg, feeder_cfg),
            "distributor": _distributor_snapshot(distributor),
        },
        "slots": _slot_snapshot(handle),
    }


def apply_patch(handle: Any, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial live tuning patch and return the new snapshot."""

    if not isinstance(patch, dict):
        raise ValueError("tuning payload must be an object")

    channels_patch: dict[str, Any] = {}
    raw_channels = patch.get("channels")
    if raw_channels is not None:
        if not isinstance(raw_channels, dict):
            raise ValueError("channels must be an object")
        channels_patch.update(raw_channels)

    # Convenience for scripts: allow {"c4": {...}} as shorthand.
    for key in ("c1", "c2", "c3", "c4", "distributor", *_CHANNEL_ALIASES.keys()):
        if key in patch:
            channels_patch[key] = patch[key]

    for raw_key, values in channels_patch.items():
        key = _channel_key(raw_key)
        if not isinstance(values, dict):
            raise ValueError(f"channels.{raw_key} must be an object")
        if key == "c1":
            _apply_c1(handle, values)
        elif key == "c2":
            _apply_c2(handle, values)
        elif key == "c3":
            _apply_c3(handle, values)
        elif key == "c4":
            _apply_c4(handle, values)
        elif key == "distributor":
            _apply_distributor(handle, values)
        else:
            raise ValueError(f"unsupported channel {raw_key!r}")

    slots_patch = patch.get("slots")
    if slots_patch is not None:
        if not isinstance(slots_patch, dict):
            raise ValueError("slots must be an object")
        _apply_slots(handle, slots_patch)

    return snapshot(handle)


def _c1_snapshot(runtime: Any, feeder_cfg: Any) -> dict[str, Any]:
    return {
        "transport": _rotor_snapshot(getattr(feeder_cfg, "first_rotor", None)),
        "sample_transport_step_deg": _runtime_attr(runtime, "_sample_transport_step_deg"),
        "pulse_cooldown_s": _runtime_attr(runtime, "_pulse_cooldown_s"),
        "jam_timeout_s": _runtime_attr(runtime, "_jam_timeout_s"),
        "jam_min_pulses": _runtime_attr(runtime, "_jam_min_pulses"),
        "jam_cooldown_s": _runtime_attr(runtime, "_jam_cooldown_s"),
        "max_recovery_cycles": _runtime_attr(runtime, "_max_recovery_cycles"),
    }


def _c2_snapshot(runtime: Any, feeder_cfg: Any) -> dict[str, Any]:
    return {
        "max_piece_count": _runtime_attr(runtime, "_max_piece_count"),
        "pulse_cooldown_s": _runtime_attr(runtime, "_pulse_cooldown_s"),
        "advance_interval_s": _runtime_attr(runtime, "_advance_interval_s"),
        "track_stale_s": _runtime_attr(runtime, "_track_stale_s"),
        "exit_near_arc_deg": _rad_attr_deg(runtime, "_exit_near_arc"),
        "approach_near_arc_deg": _rad_attr_deg(runtime, "_approach_near_arc"),
        "intake_near_arc_deg": _rad_attr_deg(runtime, "_intake_near_arc"),
        "wiggle_stall_ms": _seconds_attr_ms(runtime, "_wiggle_stall_s"),
        "wiggle_cooldown_ms": _seconds_attr_ms(runtime, "_wiggle_cooldown_s"),
        "exit_handoff_min_interval_s": _runtime_attr(
            runtime,
            "_exit_handoff_min_interval_s",
        ),
        "handoff_retry_escalate_after": _runtime_attr(
            runtime,
            "_handoff_retry_escalate_after",
        ),
        "handoff_retry_max_pulses": _runtime_attr(
            runtime,
            "_handoff_retry_max_pulses",
        ),
        "transport_target_rpm": _transport_target_rpm(runtime),
        "normal": _rotor_snapshot(getattr(feeder_cfg, "second_rotor_normal", None)),
        "precision": _rotor_snapshot(getattr(feeder_cfg, "second_rotor_precision", None)),
    }


def _c3_snapshot(runtime: Any, feeder_cfg: Any) -> dict[str, Any]:
    return {
        "max_piece_count": _runtime_attr(runtime, "_max_piece_count"),
        "pulse_cooldown_s": _runtime_attr(runtime, "_pulse_cooldown_s"),
        "track_stale_s": _runtime_attr(runtime, "_track_stale_s"),
        "exit_near_arc_deg": _rad_attr_deg(runtime, "_exit_near_arc"),
        "approach_near_arc_deg": _rad_attr_deg(runtime, "_approach_near_arc"),
        "wiggle_stall_ms": _seconds_attr_ms(runtime, "_wiggle_stall_s"),
        "wiggle_cooldown_ms": _seconds_attr_ms(runtime, "_wiggle_cooldown_s"),
        "holdover_ms": _seconds_attr_ms(runtime, "_holdover_s"),
        "exit_handoff_min_interval_s": _runtime_attr(
            runtime,
            "_exit_handoff_min_interval_s",
        ),
        "handoff_retry_escalate_after": _runtime_attr(
            runtime,
            "_handoff_retry_escalate_after",
        ),
        "handoff_retry_max_pulses": _runtime_attr(
            runtime,
            "_handoff_retry_max_pulses",
        ),
        "transport_target_rpm": _transport_target_rpm(runtime),
        "normal": _rotor_snapshot(getattr(feeder_cfg, "third_rotor_normal", None)),
        "precision": _rotor_snapshot(getattr(feeder_cfg, "third_rotor_precision", None)),
    }


def _c4_snapshot(runtime: Any, class_cfg: Any, feeder_cfg: Any) -> dict[str, Any]:
    zone_mgr = getattr(runtime, "_zone_manager", None)
    admission = getattr(runtime, "_admission", None)
    return {
        "max_zones": _safe_int(getattr(zone_mgr, "max_zones", None)),
        "max_raw_detections": _safe_int(getattr(admission, "max_raw_detections", None)),
        "intake_body_half_width_deg": _safe_float(
            getattr(zone_mgr, "_default_half_width", None)
        ),
        "intake_guard_deg": _safe_float(
            getattr(zone_mgr, "_guard_deg", getattr(zone_mgr, "guard_angle_deg", None))
        ),
        "transport_step_deg": _runtime_attr(runtime, "_transport_step_deg"),
        "transport_max_step_deg": _runtime_attr(runtime, "_transport_max_step_deg"),
        "transport_cooldown_s": _runtime_attr(runtime, "_transport_cooldown_s"),
        "transport_target_rpm": _transport_target_rpm(runtime),
        "classify_pretrigger_exit_lead_deg": _runtime_attr(
            runtime,
            "_classify_pretrigger_exit_lead_deg",
        ),
        "exit_approach_angle_deg": _runtime_attr(runtime, "_exit_approach_angle_deg"),
        "exit_approach_step_deg": _runtime_attr(runtime, "_exit_approach_step_deg"),
        "transport_speed_scale": _safe_float(
            getattr(class_cfg, "transport_speed_scale", None)
        ),
        "stepper_degrees_per_tray_degree": _safe_float(
            getattr(class_cfg, "stepper_degrees_per_tray_degree", None)
        ),
        "transport_acceleration_usteps_per_s2": _safe_int(
            getattr(class_cfg, "transport_acceleration_microsteps_per_second_sq", None)
        ),
        "startup_purge_speed_scale": _safe_float(
            getattr(class_cfg, "startup_purge_speed_scale", None)
        ),
        "startup_purge_acceleration_usteps_per_s2": _safe_int(
            getattr(class_cfg, "startup_purge_acceleration_microsteps_per_second_sq", None)
        ),
        "exit_release_shimmy_amplitude_deg": _safe_float(
            getattr(class_cfg, "exit_release_shimmy_amplitude_deg", None)
        ),
        "exit_release_shimmy_cycles": _safe_int(
            getattr(class_cfg, "exit_release_shimmy_cycles", None)
        ),
        "exit_release_shimmy_speed_usteps_per_s": _safe_int(
            getattr(class_cfg, "exit_release_shimmy_microsteps_per_second", None)
        ),
        "exit_release_shimmy_acceleration_usteps_per_s2": _safe_int(
            getattr(
                class_cfg,
                "exit_release_shimmy_acceleration_microsteps_per_second_sq",
                None,
            )
        ),
        "exit_trailing_safety_deg": _runtime_attr(
            runtime, "_exit_trailing_safety_deg"
        ),
        "idle_jog_enabled": _runtime_attr(runtime, "_idle_jog_enabled"),
        "idle_jog_step_deg": _runtime_attr(runtime, "_idle_jog_step_deg"),
        "idle_jog_cooldown_s": _runtime_attr(runtime, "_idle_jog_cooldown_s"),
        "unjam_enabled": _runtime_attr(runtime, "_unjam_enabled"),
        "unjam_stall_s": _runtime_attr(runtime, "_unjam_stall_s"),
        "unjam_min_progress_deg": _runtime_attr(runtime, "_unjam_min_progress_deg"),
        "unjam_cooldown_s": _runtime_attr(runtime, "_unjam_cooldown_s"),
        "unjam_reverse_deg": _runtime_attr(runtime, "_unjam_reverse_deg"),
        "unjam_forward_deg": _runtime_attr(runtime, "_unjam_forward_deg"),
        "track_stale_s": _runtime_attr(runtime, "_track_stale_s"),
        "reconcile_min_hit_count": _runtime_attr(runtime, "_reconcile_min_hit_count"),
        "reconcile_min_score": _runtime_attr(runtime, "_reconcile_min_score"),
        "reconcile_min_age_s": _runtime_attr(runtime, "_reconcile_min_age_s"),
        "eject": _rotor_snapshot(
            getattr(feeder_cfg, "classification_channel_eject", None)
        ),
    }


def _distributor_snapshot(runtime: Any) -> dict[str, Any]:
    return {
        "simulate_chute": _runtime_attr(runtime, "_simulate_chute"),
        "simulated_chute_move_s": _runtime_attr(runtime, "_simulated_chute_move_s"),
        "chute_settle_s": _runtime_attr(runtime, "_chute_settle_s"),
        "fall_time_s": _runtime_attr(runtime, "_fall_time_s"),
        "position_timeout_s": _runtime_attr(runtime, "_position_timeout_s"),
        "ready_timeout_s": _runtime_attr(runtime, "_ready_timeout_s"),
    }


def _apply_c1(handle: Any, values: dict[str, Any]) -> None:
    runtime = getattr(handle, "c1", None)
    feeder_cfg = _feeder_cfg(getattr(handle, "irl", None))
    allowed = {
        "transport",
        "pulse_cooldown_s",
        "pulse_cooldown_ms",
        "jam_timeout_s",
        "jam_timeout_ms",
        "jam_min_pulses",
        "jam_cooldown_s",
        "jam_cooldown_ms",
        "max_recovery_cycles",
    }
    _reject_unknown("c1", values, allowed)
    _set_runtime_seconds(runtime, "_pulse_cooldown_s", values, "pulse_cooldown_s", "pulse_cooldown_ms", 0.0, 30.0)
    _set_runtime_seconds(runtime, "_jam_timeout_s", values, "jam_timeout_s", "jam_timeout_ms", 0.25, 120.0)
    _set_runtime_int(
        runtime,
        "_jam_min_pulses",
        values,
        "jam_min_pulses",
        min_value=1,
        max_value=100,
    )
    _set_runtime_seconds(
        runtime,
        "_jam_cooldown_s",
        values,
        "jam_cooldown_s",
        "jam_cooldown_ms",
        0.0,
        120.0,
    )
    _set_runtime_int(
        runtime,
        "_max_recovery_cycles",
        values,
        "max_recovery_cycles",
        min_value=1,
        max_value=100,
    )
    if "transport" in values:
        _apply_rotor_patch(getattr(feeder_cfg, "first_rotor", None), values["transport"], "c1.transport")


def _apply_c2(handle: Any, values: dict[str, Any]) -> None:
    runtime = getattr(handle, "c2", None)
    feeder_cfg = _feeder_cfg(getattr(handle, "irl", None))
    allowed = {
        "max_piece_count",
        "pulse_cooldown_s",
        "pulse_cooldown_ms",
        "advance_interval_s",
        "track_stale_s",
        "exit_near_arc_deg",
        "approach_near_arc_deg",
        "intake_near_arc_deg",
        "wiggle_stall_ms",
        "wiggle_cooldown_ms",
        "exit_handoff_min_interval_s",
        "exit_handoff_min_interval_ms",
        "handoff_retry_escalate_after",
        "handoff_retry_max_pulses",
        "transport_target_rpm",
        "normal",
        "precision",
    }
    _reject_unknown("c2", values, allowed)
    _set_runtime_int(
        runtime, "_max_piece_count", values, "max_piece_count", min_value=1, max_value=30
    )
    _set_runtime_seconds(
        runtime,
        "_pulse_cooldown_s",
        values,
        "pulse_cooldown_s",
        "pulse_cooldown_ms",
        0.0,
        10.0,
    )
    _set_runtime_float(
        runtime,
        "_advance_interval_s",
        values,
        "advance_interval_s",
        min_value=0.0,
        max_value=30.0,
    )
    _set_runtime_float(
        runtime, "_track_stale_s", values, "track_stale_s", min_value=0.0, max_value=30.0
    )
    _set_runtime_radians(
        runtime, "_exit_near_arc", values, "exit_near_arc_deg", 0.1, 180.0
    )
    _set_runtime_radians(
        runtime, "_approach_near_arc", values, "approach_near_arc_deg", 0.1, 180.0
    )
    _set_runtime_radians(
        runtime, "_intake_near_arc", values, "intake_near_arc_deg", 0.1, 180.0
    )
    _set_runtime_seconds(
        runtime, "_wiggle_stall_s", values, None, "wiggle_stall_ms", 0.0, 30.0
    )
    _set_runtime_seconds(
        runtime,
        "_wiggle_cooldown_s",
        values,
        None,
        "wiggle_cooldown_ms",
        0.0,
        30.0,
    )
    _set_runtime_seconds(
        runtime,
        "_exit_handoff_min_interval_s",
        values,
        "exit_handoff_min_interval_s",
        "exit_handoff_min_interval_ms",
        0.0,
        10.0,
    )
    _set_runtime_int(
        runtime,
        "_handoff_retry_escalate_after",
        values,
        "handoff_retry_escalate_after",
        min_value=1,
        max_value=20,
    )
    _set_runtime_int(
        runtime,
        "_handoff_retry_max_pulses",
        values,
        "handoff_retry_max_pulses",
        min_value=1,
        max_value=5,
    )
    _set_transport_target_rpm(runtime, values)
    if "normal" in values:
        _apply_rotor_patch(getattr(feeder_cfg, "second_rotor_normal", None), values["normal"], "c2.normal")
    if "precision" in values:
        _apply_rotor_patch(getattr(feeder_cfg, "second_rotor_precision", None), values["precision"], "c2.precision")
    _ensure_approach_at_least_exit(runtime)


def _apply_c3(handle: Any, values: dict[str, Any]) -> None:
    runtime = getattr(handle, "c3", None)
    feeder_cfg = _feeder_cfg(getattr(handle, "irl", None))
    allowed = {
        "max_piece_count",
        "pulse_cooldown_s",
        "pulse_cooldown_ms",
        "track_stale_s",
        "exit_near_arc_deg",
        "approach_near_arc_deg",
        "wiggle_stall_ms",
        "wiggle_cooldown_ms",
        "holdover_ms",
        "exit_handoff_min_interval_s",
        "exit_handoff_min_interval_ms",
        "handoff_retry_escalate_after",
        "handoff_retry_max_pulses",
        "transport_target_rpm",
        "normal",
        "precision",
    }
    _reject_unknown("c3", values, allowed)
    _set_runtime_int(
        runtime, "_max_piece_count", values, "max_piece_count", min_value=1, max_value=30
    )
    _set_runtime_seconds(
        runtime,
        "_pulse_cooldown_s",
        values,
        "pulse_cooldown_s",
        "pulse_cooldown_ms",
        0.0,
        10.0,
    )
    _set_runtime_float(
        runtime, "_track_stale_s", values, "track_stale_s", min_value=0.0, max_value=30.0
    )
    _set_runtime_radians(
        runtime, "_exit_near_arc", values, "exit_near_arc_deg", 0.1, 180.0
    )
    _set_runtime_radians(
        runtime, "_approach_near_arc", values, "approach_near_arc_deg", 0.1, 180.0
    )
    _set_runtime_seconds(
        runtime, "_wiggle_stall_s", values, None, "wiggle_stall_ms", 0.0, 30.0
    )
    _set_runtime_seconds(
        runtime,
        "_wiggle_cooldown_s",
        values,
        None,
        "wiggle_cooldown_ms",
        0.0,
        30.0,
    )
    _set_runtime_seconds(
        runtime, "_holdover_s", values, None, "holdover_ms", 0.0, 30.0
    )
    _set_runtime_seconds(
        runtime,
        "_exit_handoff_min_interval_s",
        values,
        "exit_handoff_min_interval_s",
        "exit_handoff_min_interval_ms",
        0.0,
        10.0,
    )
    _set_runtime_int(
        runtime,
        "_handoff_retry_escalate_after",
        values,
        "handoff_retry_escalate_after",
        min_value=1,
        max_value=20,
    )
    _set_runtime_int(
        runtime,
        "_handoff_retry_max_pulses",
        values,
        "handoff_retry_max_pulses",
        min_value=1,
        max_value=5,
    )
    _set_transport_target_rpm(runtime, values)
    if "normal" in values:
        _apply_rotor_patch(getattr(feeder_cfg, "third_rotor_normal", None), values["normal"], "c3.normal")
    if "precision" in values:
        _apply_rotor_patch(getattr(feeder_cfg, "third_rotor_precision", None), values["precision"], "c3.precision")
    _ensure_approach_at_least_exit(runtime)


def _apply_c4(handle: Any, values: dict[str, Any]) -> None:
    runtime = getattr(handle, "c4", None)
    irl = getattr(handle, "irl", None)
    class_cfg = _classification_cfg(irl)
    feeder_cfg = _feeder_cfg(irl)
    allowed = {
        "max_zones",
        "max_raw_detections",
        "intake_body_half_width_deg",
        "intake_guard_deg",
        "transport_step_deg",
        "transport_max_step_deg",
        "transport_cooldown_s",
        "transport_cooldown_ms",
        "transport_target_rpm",
        "classify_pretrigger_exit_lead_deg",
        "exit_approach_angle_deg",
        "exit_approach_step_deg",
        "transport_speed_scale",
        "transport_acceleration_usteps_per_s2",
        "startup_purge_speed_scale",
        "startup_purge_acceleration_usteps_per_s2",
        "exit_release_shimmy_amplitude_deg",
        "exit_release_shimmy_cycles",
        "exit_release_shimmy_speed_usteps_per_s",
        "exit_release_shimmy_acceleration_usteps_per_s2",
        "exit_trailing_safety_deg",
        "idle_jog_enabled",
        "idle_jog_step_deg",
        "idle_jog_cooldown_s",
        "idle_jog_cooldown_ms",
        "unjam_enabled",
        "unjam_stall_s",
        "unjam_stall_ms",
        "unjam_min_progress_deg",
        "unjam_cooldown_s",
        "unjam_cooldown_ms",
        "unjam_reverse_deg",
        "unjam_forward_deg",
        "track_stale_s",
        "reconcile_min_hit_count",
        "reconcile_min_score",
        "reconcile_min_age_s",
        "eject",
    }
    _reject_unknown("c4", values, allowed)
    if "max_zones" in values:
        max_zones = _int(values["max_zones"], "c4.max_zones", min_value=1, max_value=30)
        zone_mgr = getattr(runtime, "_zone_manager", None)
        if zone_mgr is not None:
            setattr(zone_mgr, "_max_zones", max_zones)
        admission = getattr(runtime, "_admission", None)
        if admission is not None:
            setattr(admission, "_max_zones", max_zones)
        if class_cfg is not None:
            setattr(class_cfg, "max_zones", max_zones)
        _set_slot_capacity(handle, "c3_to_c4", max_zones)
    if "max_raw_detections" in values:
        raw_value = values["max_raw_detections"]
        max_raw = None if raw_value is None else _int(raw_value, "c4.max_raw_detections", min_value=0, max_value=200)
        if max_raw is not None and max_raw <= 0:
            max_raw = None
        admission = getattr(runtime, "_admission", None)
        if admission is not None:
            setattr(admission, "_max_raw_detections", max_raw)
        if class_cfg is not None:
            setattr(class_cfg, "max_raw_detections", max_raw)
    if "intake_body_half_width_deg" in values:
        half_width = _float(
            values["intake_body_half_width_deg"],
            "c4.intake_body_half_width_deg",
            min_value=1.0,
            max_value=60.0,
        )
        zone_mgr = getattr(runtime, "_zone_manager", None)
        if zone_mgr is not None:
            setattr(zone_mgr, "_default_half_width", half_width)
        if runtime is not None:
            setattr(runtime, "_intake_half_width_deg", half_width)
        if class_cfg is not None:
            setattr(class_cfg, "intake_body_half_width_deg", half_width)
    if "intake_guard_deg" in values:
        guard = _float(
            values["intake_guard_deg"],
            "c4.intake_guard_deg",
            min_value=0.0,
            max_value=90.0,
        )
        zone_mgr = getattr(runtime, "_zone_manager", None)
        if zone_mgr is not None:
            setattr(zone_mgr, "_guard_deg", guard)
        admission = getattr(runtime, "_admission", None)
        if admission is not None:
            setattr(admission, "_guard_angle_deg", guard)
        if class_cfg is not None:
            setattr(class_cfg, "intake_guard_deg", guard)
    _set_runtime_float(runtime, "_transport_step_deg", values, "transport_step_deg", min_value=0.1, max_value=90.0)
    _set_runtime_float(runtime, "_transport_max_step_deg", values, "transport_max_step_deg", min_value=0.1, max_value=180.0)
    if runtime is not None:
        step = getattr(runtime, "_transport_step_deg", None)
        max_step = getattr(runtime, "_transport_max_step_deg", None)
        if isinstance(step, (int, float)) and isinstance(max_step, (int, float)):
            setattr(runtime, "_transport_max_step_deg", max(float(step), float(max_step)))
    _set_runtime_seconds(runtime, "_transport_cooldown_s", values, "transport_cooldown_s", "transport_cooldown_ms", 0.0, 10.0)
    _set_transport_target_rpm(runtime, values)
    _set_runtime_float(
        runtime,
        "_classify_pretrigger_exit_lead_deg",
        values,
        "classify_pretrigger_exit_lead_deg",
        min_value=0.0,
        max_value=180.0,
    )
    _set_runtime_float(runtime, "_exit_approach_angle_deg", values, "exit_approach_angle_deg", min_value=0.0, max_value=90.0)
    _set_runtime_float(runtime, "_exit_approach_step_deg", values, "exit_approach_step_deg", min_value=0.1, max_value=24.0)
    _set_runtime_bool(runtime, "_idle_jog_enabled", values, "idle_jog_enabled")
    _set_runtime_float(runtime, "_idle_jog_step_deg", values, "idle_jog_step_deg", min_value=0.1, max_value=45.0)
    _set_runtime_seconds(runtime, "_idle_jog_cooldown_s", values, "idle_jog_cooldown_s", "idle_jog_cooldown_ms", 0.0, 30.0)
    _set_runtime_bool(runtime, "_unjam_enabled", values, "unjam_enabled")
    _set_runtime_seconds(runtime, "_unjam_stall_s", values, "unjam_stall_s", "unjam_stall_ms", 0.25, 60.0)
    _set_runtime_float(runtime, "_unjam_min_progress_deg", values, "unjam_min_progress_deg", min_value=0.1, max_value=45.0)
    _set_runtime_seconds(runtime, "_unjam_cooldown_s", values, "unjam_cooldown_s", "unjam_cooldown_ms", 0.5, 60.0)
    _set_runtime_float(runtime, "_unjam_reverse_deg", values, "unjam_reverse_deg", min_value=0.1, max_value=90.0)
    _set_runtime_float(runtime, "_unjam_forward_deg", values, "unjam_forward_deg", min_value=0.1, max_value=180.0)
    _set_runtime_float(runtime, "_track_stale_s", values, "track_stale_s", min_value=0.0, max_value=30.0)
    _set_runtime_int(runtime, "_reconcile_min_hit_count", values, "reconcile_min_hit_count", min_value=1, max_value=50)
    _set_runtime_float(runtime, "_reconcile_min_score", values, "reconcile_min_score", min_value=0.0, max_value=1.0)
    _set_runtime_float(runtime, "_reconcile_min_age_s", values, "reconcile_min_age_s", min_value=0.0, max_value=30.0)
    if class_cfg is not None:
        _set_cfg_float(class_cfg, "transport_speed_scale", values, "transport_speed_scale", 0.1, 64.0)
        _set_cfg_optional_int(class_cfg, "transport_acceleration_microsteps_per_second_sq", values, "transport_acceleration_usteps_per_s2", 1, 1_000_000)
        _set_cfg_float(class_cfg, "positioning_window_deg", values, "exit_approach_angle_deg", 0.0, 90.0)
        _set_cfg_float(class_cfg, "exit_approach_step_deg", values, "exit_approach_step_deg", 0.1, 24.0)
        _set_cfg_float(class_cfg, "startup_purge_speed_scale", values, "startup_purge_speed_scale", 0.1, 64.0)
        _set_cfg_optional_int(class_cfg, "startup_purge_acceleration_microsteps_per_second_sq", values, "startup_purge_acceleration_usteps_per_s2", 1, 1_000_000)
        _set_cfg_float(class_cfg, "exit_release_shimmy_amplitude_deg", values, "exit_release_shimmy_amplitude_deg", 0.1, 12.0)
        _set_cfg_optional_int(class_cfg, "exit_release_shimmy_cycles", values, "exit_release_shimmy_cycles", 1, 8)
        _set_cfg_optional_int(class_cfg, "exit_release_shimmy_microsteps_per_second", values, "exit_release_shimmy_speed_usteps_per_s", 1, 1_000_000)
        _set_cfg_optional_int(
            class_cfg,
            "exit_release_shimmy_acceleration_microsteps_per_second_sq",
            values,
            "exit_release_shimmy_acceleration_usteps_per_s2",
            1,
            1_000_000,
        )
    if runtime is not None and "exit_release_shimmy_amplitude_deg" in values:
        setattr(
            runtime,
            "_shimmy_step_deg",
            _float(
                values["exit_release_shimmy_amplitude_deg"],
                "c4.exit_release_shimmy_amplitude_deg",
                min_value=0.1,
                max_value=12.0,
            ),
        )
    if runtime is not None and "exit_trailing_safety_deg" in values:
        setattr(
            runtime,
            "_exit_trailing_safety_deg",
            _float(
                values["exit_trailing_safety_deg"],
                "c4.exit_trailing_safety_deg",
                min_value=0.0,
                max_value=90.0,
            ),
        )
    if "eject" in values:
        _apply_rotor_patch(getattr(feeder_cfg, "classification_channel_eject", None), values["eject"], "c4.eject")


def _apply_distributor(handle: Any, values: dict[str, Any]) -> None:
    runtime = getattr(handle, "distributor", None)
    allowed = {
        "simulate_chute",
        "simulated_chute_move_s",
        "simulated_chute_move_ms",
        "chute_settle_s",
        "chute_settle_ms",
        "fall_time_s",
        "fall_time_ms",
        "position_timeout_s",
        "position_timeout_ms",
        "ready_timeout_s",
        "ready_timeout_ms",
    }
    _reject_unknown("distributor", values, allowed)
    _set_runtime_bool(runtime, "_simulate_chute", values, "simulate_chute")
    _set_runtime_seconds(
        runtime,
        "_simulated_chute_move_s",
        values,
        "simulated_chute_move_s",
        "simulated_chute_move_ms",
        0.0,
        30.0,
    )
    _set_runtime_seconds(
        runtime,
        "_chute_settle_s",
        values,
        "chute_settle_s",
        "chute_settle_ms",
        0.0,
        30.0,
    )
    _set_runtime_seconds(
        runtime,
        "_fall_time_s",
        values,
        "fall_time_s",
        "fall_time_ms",
        0.0,
        30.0,
    )
    _set_runtime_seconds(
        runtime,
        "_position_timeout_s",
        values,
        "position_timeout_s",
        "position_timeout_ms",
        0.0,
        300.0,
    )
    _set_runtime_seconds(
        runtime,
        "_ready_timeout_s",
        values,
        "ready_timeout_s",
        "ready_timeout_ms",
        0.0,
        600.0,
    )


def _apply_slots(handle: Any, values: dict[str, Any]) -> None:
    for raw_key, raw_value in values.items():
        key = _slot_key(raw_key)
        _set_slot_capacity(
            handle,
            key,
            _int(raw_value, f"slots.{raw_key}", min_value=0, max_value=50),
        )


def _slot_snapshot(handle: Any) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for key in _SLOT_EDGE_BY_KEY:
        out[key] = _slot_capacity(handle, key)
    return out


def _slot_capacity(handle: Any, key: str) -> int | None:
    slot = _slot(handle, key)
    if slot is None:
        return None
    capacity = getattr(slot, "capacity", None)
    if callable(capacity):
        try:
            return int(capacity())
        except Exception:
            return None
    return None


def _set_slot_capacity(handle: Any, key: str, capacity: int) -> None:
    slot = _slot(handle, key)
    if slot is None:
        return
    fn = getattr(slot, "set_capacity", None)
    if callable(fn):
        fn(int(capacity))


def _slot(handle: Any, key: str) -> Any | None:
    edge = _SLOT_EDGE_BY_KEY.get(_slot_key(key))
    if edge is None:
        return None
    orch = getattr(handle, "orchestrator", None)
    slots = getattr(orch, "_slots", None)
    return slots.get(edge) if isinstance(slots, dict) else None


def _apply_rotor_patch(cfg: Any, values: Any, prefix: str) -> None:
    if cfg is None:
        return
    if not isinstance(values, dict):
        raise ValueError(f"{prefix} must be an object")
    allowed = {
        "steps_per_pulse",
        "microsteps_per_second",
        "delay_between_pulse_ms",
        "acceleration_microsteps_per_second_sq",
        "acceleration_usteps_per_s2",
    }
    _reject_unknown(prefix, values, allowed)
    if "steps_per_pulse" in values:
        cfg.steps_per_pulse = _int(values["steps_per_pulse"], f"{prefix}.steps_per_pulse", min_value=1, max_value=200_000)
    if "microsteps_per_second" in values:
        cfg.microsteps_per_second = _int(values["microsteps_per_second"], f"{prefix}.microsteps_per_second", min_value=1, max_value=100_000)
    if "delay_between_pulse_ms" in values:
        cfg.delay_between_pulse_ms = _int(values["delay_between_pulse_ms"], f"{prefix}.delay_between_pulse_ms", min_value=0, max_value=60_000)
    accel_key = (
        "acceleration_microsteps_per_second_sq"
        if "acceleration_microsteps_per_second_sq" in values
        else "acceleration_usteps_per_s2"
        if "acceleration_usteps_per_s2" in values
        else None
    )
    if accel_key is not None:
        raw = values[accel_key]
        cfg.acceleration_microsteps_per_second_sq = (
            None
            if raw is None
            else _int(raw, f"{prefix}.{accel_key}", min_value=1, max_value=1_000_000)
        )


def _rotor_snapshot(cfg: Any) -> dict[str, Any] | None:
    if cfg is None:
        return None
    return {
        "steps_per_pulse": _safe_int(getattr(cfg, "steps_per_pulse", None)),
        "microsteps_per_second": _safe_int(getattr(cfg, "microsteps_per_second", None)),
        "delay_between_pulse_ms": _safe_int(getattr(cfg, "delay_between_pulse_ms", None)),
        "acceleration_microsteps_per_second_sq": _safe_int(
            getattr(cfg, "acceleration_microsteps_per_second_sq", None)
        ),
    }


def _feeder_cfg(irl: Any) -> Any | None:
    return getattr(irl, "feeder_config", None) or getattr(
        getattr(irl, "irl_config", None), "feeder_config", None
    )


def _classification_cfg(irl: Any) -> Any | None:
    return getattr(irl, "classification_channel_config", None) or getattr(
        getattr(irl, "irl_config", None), "classification_channel_config", None
    )


def _runtime_attr(runtime: Any, attr: str) -> Any:
    if runtime is None:
        return None
    value = getattr(runtime, attr, None)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def _rad_attr_deg(runtime: Any, attr: str) -> float | None:
    value = _runtime_attr(runtime, attr)
    return math.degrees(float(value)) if isinstance(value, (int, float)) else None


def _seconds_attr_ms(runtime: Any, attr: str) -> float | None:
    value = _runtime_attr(runtime, attr)
    return float(value) * 1000.0 if isinstance(value, (int, float)) else None


def _transport_target_rpm(runtime: Any) -> float | None:
    observer = getattr(runtime, "_transport_velocity", None)
    return _safe_float(getattr(observer, "target_rpm", None))


def _set_transport_target_rpm(runtime: Any, values: dict[str, Any]) -> None:
    if "transport_target_rpm" not in values:
        return
    observer = getattr(runtime, "_transport_velocity", None)
    if observer is None:
        return
    observer.target_rpm = _float(
        values["transport_target_rpm"],
        "transport_target_rpm",
        min_value=0.0,
        max_value=30.0,
    )


def _set_runtime_float(
    runtime: Any,
    attr: str,
    values: dict[str, Any],
    key: str,
    *,
    min_value: float,
    max_value: float,
) -> None:
    if key in values and runtime is not None:
        setattr(runtime, attr, _float(values[key], key, min_value=min_value, max_value=max_value))


def _set_runtime_int(
    runtime: Any,
    attr: str,
    values: dict[str, Any],
    key: str,
    *,
    min_value: int,
    max_value: int,
) -> None:
    if key in values and runtime is not None:
        setattr(runtime, attr, _int(values[key], key, min_value=min_value, max_value=max_value))


def _set_runtime_bool(runtime: Any, attr: str, values: dict[str, Any], key: str) -> None:
    if key in values and runtime is not None:
        value = values[key]
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        setattr(runtime, attr, bool(value))


def _set_runtime_seconds(
    runtime: Any,
    attr: str,
    values: dict[str, Any],
    seconds_key: str | None,
    ms_key: str | None,
    min_value: float,
    max_value: float,
) -> None:
    if runtime is None:
        return
    if seconds_key and seconds_key in values:
        setattr(runtime, attr, _float(values[seconds_key], seconds_key, min_value=min_value, max_value=max_value))
    if ms_key and ms_key in values:
        setattr(
            runtime,
            attr,
            _float(values[ms_key], ms_key, min_value=min_value * 1000.0, max_value=max_value * 1000.0) / 1000.0,
        )


def _set_runtime_radians(
    runtime: Any,
    attr: str,
    values: dict[str, Any],
    key: str,
    min_deg: float,
    max_deg: float,
) -> None:
    if key in values and runtime is not None:
        setattr(
            runtime,
            attr,
            math.radians(_float(values[key], key, min_value=min_deg, max_value=max_deg)),
        )


def _set_cfg_float(
    cfg: Any,
    attr: str,
    values: dict[str, Any],
    key: str,
    min_value: float,
    max_value: float,
) -> None:
    if key in values:
        setattr(cfg, attr, _float(values[key], key, min_value=min_value, max_value=max_value))


def _set_cfg_optional_int(
    cfg: Any,
    attr: str,
    values: dict[str, Any],
    key: str,
    min_value: int,
    max_value: int,
) -> None:
    if key not in values:
        return
    raw = values[key]
    setattr(
        cfg,
        attr,
        None if raw is None else _int(raw, key, min_value=min_value, max_value=max_value),
    )


def _ensure_approach_at_least_exit(runtime: Any) -> None:
    if runtime is None:
        return
    exit_arc = getattr(runtime, "_exit_near_arc", None)
    approach = getattr(runtime, "_approach_near_arc", None)
    if isinstance(exit_arc, (int, float)) and isinstance(approach, (int, float)):
        setattr(runtime, "_approach_near_arc", max(float(exit_arc), float(approach)))


def _channel_key(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("channel key must be a non-empty string")
    key = raw.strip()
    return _CHANNEL_ALIASES.get(key, key)


def _slot_key(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("slot key must be a non-empty string")
    key = raw.strip()
    if key not in _SLOT_ALIASES:
        raise ValueError(f"unsupported slot {raw!r}")
    return _SLOT_ALIASES[key]


def _reject_unknown(prefix: str, values: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(values).difference(allowed))
    if unknown:
        raise ValueError(f"unsupported tuning field(s) for {prefix}: {', '.join(unknown)}")


def _float(raw: Any, name: str, *, min_value: float, max_value: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(raw)
    if not math.isfinite(value) or value < min_value or value > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")
    return value


def _int(raw: Any, name: str, *, min_value: int, max_value: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = int(round(float(raw)))
    if value < min_value or value > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")
    return value


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = ["apply_patch", "snapshot"]
