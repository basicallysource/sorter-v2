"""Limits each Hive target sets for what this machine sends it.

Every heartbeat reply carries the target's current limits (Hive admins change
them live). They are both the defaults and the ceilings: a machine may be set
to capture less often, keep less on disk or upload less than Hive allows, never
more. The last limits each target sent are kept in local state, so a restart
with Hive unreachable still obeys them; a target that never sent any gets
DEFAULT_LIMITS, which match Hive's own defaults.

Machine-wide limits (how often to capture, how much to keep on disk) take the
strictest value across the enabled targets; upload budgets are per target.
"""

from __future__ import annotations

import time
from typing import Any

DEFAULT_LIMITS: dict[str, float | int] = {
    # Fastest a camera may be sampled (seconds between captures); also the
    # burst interval right after the capture schedule is reset.
    "sample_burst_interval_s": 10.0,
    # Steady-state interval the schedule slows to, and how long it takes.
    "sample_floor_interval_s": 3600.0,
    "sample_ramp_hours": 72.0,
    # Most the local sample store may hold.
    "sample_store_max_bytes": 1024 * 1024 * 1024,
    # Per-target budget for every upload that carries a file (samples, piece
    # images, channel crops, control data). Table rows are not counted.
    "upload_bytes_per_minute": 30_000_000,
    "upload_files_per_minute": 120,
}

_FLOAT_KEYS = ("sample_burst_interval_s", "sample_floor_interval_s", "sample_ramp_hours")
_INT_KEYS = ("sample_store_max_bytes", "upload_bytes_per_minute", "upload_files_per_minute")


def normalizeLimits(raw: Any) -> dict[str, float | int] | None:
    """The limits in a heartbeat reply, or None when it carries none. Missing
    or invalid values fall back to the defaults."""
    if not isinstance(raw, dict):
        return None
    limits: dict[str, float | int] = dict(DEFAULT_LIMITS)
    for key in _FLOAT_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            limits[key] = float(value)
    for key in _INT_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            limits[key] = int(value)
    limits["sample_floor_interval_s"] = max(
        float(limits["sample_floor_interval_s"]), float(limits["sample_burst_interval_s"])
    )
    return limits


def setTargetLimits(target_id: str, raw: Any) -> dict[str, float | int] | None:
    """Store the limits a target's heartbeat reply carried. A reply without any
    (an older Hive) leaves what was stored before."""
    limits = normalizeLimits(raw)
    if limits is None:
        return None
    from local_state import get_hive_limits_state, set_hive_limits_state

    state = get_hive_limits_state() or {}
    previous = state.get(target_id) if isinstance(state.get(target_id), dict) else {}
    if previous.get("limits") != limits:
        state[target_id] = {"limits": limits, "received_at": time.time()}
        set_hive_limits_state(state)
    return limits


def targetLimits(target_id: str) -> dict[str, float | int]:
    from local_state import get_hive_limits_state

    entry = (get_hive_limits_state() or {}).get(target_id)
    limits = normalizeLimits(entry.get("limits")) if isinstance(entry, dict) else None
    return limits or dict(DEFAULT_LIMITS)


def _enabledTargetIds() -> list[str]:
    from local_state import get_hive_config

    config = get_hive_config()
    targets = config.get("targets") if isinstance(config, dict) else None
    if not isinstance(targets, list):
        return []
    return [
        target["id"]
        for target in targets
        if isinstance(target, dict) and isinstance(target.get("id"), str) and target.get("enabled")
    ]


def machineLimits() -> dict[str, float | int]:
    """The strictest limits across the enabled targets (the defaults with none)."""
    per_target = [targetLimits(target_id) for target_id in _enabledTargetIds()]
    if not per_target:
        return dict(DEFAULT_LIMITS)
    return {
        "sample_burst_interval_s": max(float(l["sample_burst_interval_s"]) for l in per_target),
        "sample_floor_interval_s": max(float(l["sample_floor_interval_s"]) for l in per_target),
        "sample_ramp_hours": min(float(l["sample_ramp_hours"]) for l in per_target),
        "sample_store_max_bytes": min(int(l["sample_store_max_bytes"]) for l in per_target),
        "upload_bytes_per_minute": min(int(l["upload_bytes_per_minute"]) for l in per_target),
        "upload_files_per_minute": min(int(l["upload_files_per_minute"]) for l in per_target),
    }
