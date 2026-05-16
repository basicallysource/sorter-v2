from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from subsystems.feeder.analysis import ChannelAction


# ---------------------------------------------------------------------------
# Exit-zone incident defaults. C2/C3 used to silently wiggle here; now the same
# condition becomes an operator-facing incident that pauses the process and lets
# us tune the release motion deliberately.
# ---------------------------------------------------------------------------
EXIT_STUCK_INCIDENT_KIND = "exit_stuck"
CHANNEL_EXIT_STUCK_SOURCE_KIND = "channel_exit_stuck"
CHANNEL_EXIT_STUCK_INCIDENT_KIND = EXIT_STUCK_INCIDENT_KIND
CHANNEL_DROPZONE_STUCK_INCIDENT_KIND = "channel_dropzone_stuck"
C2_SEPARATION_INCIDENT_KIND = "c2_separation_needed"
EXIT_WIGGLE_OVERLAP_THRESHOLD: float = 0.75
EXIT_WIGGLE_STALL_MS: int = 1000
EXIT_WIGGLE_REVERSE_DEG: float = 1.5
EXIT_WIGGLE_FORWARD_DEG: float = 2.0
EXIT_WIGGLE_COOLDOWN_MS: int = 800
EXIT_RELEASE_DEFAULT_OUTPUT_DEG: float = 1.0
EXIT_RELEASE_DEFAULT_SPEED_MICROSTEPS_PER_SECOND: int = 16000
EXIT_RELEASE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ: int = 40000
EXIT_RELEASE_DEFAULT_CYCLES: int = 3
EXIT_RELEASE_DEFAULT_MAX_AUTO_ATTEMPTS: int = 3


@dataclass
class FeederTickContext:
    now_mono: float
    detections: list
    analysis: Any
    ch2_action: ChannelAction
    ch3_action: ChannelAction
    can_run: bool
    ch3_held: bool
    classification_channel_block: bool
    classification_channel_piece_count: int
    ch1_pulse_intent: bool
    ch2_pulse_intent: bool
    ch3_pulse_intent: bool
    ch1_stepper_busy: bool
    ch2_stepper_busy: bool
    ch3_stepper_busy: bool
    wait_stepper_busy: bool
    pulse_intent: bool = False
    pulse_sent: bool = False
    ch1_jam_recovery_triggered: bool = False
    sample_collection_mode: bool = False
    abort_tick: bool = False


class BaseStation:
    def __init__(self, *, gc, machine_name: str) -> None:
        self.gc = gc
        self.logger = gc.logger
        self._machine_name = machine_name
        self._current_state: str | None = None

    @property
    def current_state(self) -> str | None:
        return self._current_state

    def set_state(self, state_name: str) -> None:
        if self._current_state == state_name:
            return
        prev_state = self._current_state
        self._current_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            self._machine_name,
            prev_state,
            state_name,
        )

    def cleanup(self) -> None:
        pass


def publish_channel_exit_stuck_incident(
    gc: Any,
    *,
    channel: str,
    role: str,
    channel_label: str,
    overlap_ratio: float,
    overlap_threshold: float,
    stall_ms: int,
    downstream_blocked: bool,
) -> bool:
    if _incident_handling_off(CHANNEL_EXIT_STUCK_INCIDENT_KIND):
        return False
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    if isinstance(active, dict):
        return (
            active.get("kind") == CHANNEL_EXIT_STUCK_INCIDENT_KIND
            and active.get("source_kind") == CHANNEL_EXIT_STUCK_SOURCE_KIND
            and active.get("channel") == channel
        )

    runtime_stats.setActiveIncident(
        {
            "kind": CHANNEL_EXIT_STUCK_INCIDENT_KIND,
            "source_kind": CHANNEL_EXIT_STUCK_SOURCE_KIND,
            "severity": "critical",
            "status": "waiting_for_operator",
            "awaiting_operator": True,
            "scope": "feeder",
            "channel": channel,
            "role": role,
            "channel_label": channel_label,
            "triggered_at": time.time(),
            "overlap_ratio": float(overlap_ratio),
            "overlap_threshold": float(overlap_threshold),
            "stall_ms": int(stall_ms),
            "downstream_blocked": bool(downstream_blocked),
            "rule": "bbox_exit_overlap_ge_three_quarters_for_stall",
            "amplitude_output_deg": EXIT_RELEASE_DEFAULT_OUTPUT_DEG,
            "cycles": EXIT_RELEASE_DEFAULT_CYCLES,
            "microsteps_per_second": EXIT_RELEASE_DEFAULT_SPEED_MICROSTEPS_PER_SECOND,
            "acceleration_microsteps_per_second_sq": EXIT_RELEASE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ,
            "auto_attempts_completed": 0,
            "auto_attempts_max": EXIT_RELEASE_DEFAULT_MAX_AUTO_ATTEMPTS,
        }
    )
    return True


def publish_channel_dropzone_stuck_incident(
    gc: Any,
    *,
    channel: str,
    role: str,
    channel_label: str,
    global_id: int,
    bbox: tuple[int, int, int, int],
    overlap_ratio: float,
    overlap_threshold: float,
    stall_ms: int,
) -> bool:
    if _incident_handling_off(CHANNEL_DROPZONE_STUCK_INCIDENT_KIND):
        return False
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    if isinstance(active, dict):
        return (
            active.get("kind") == CHANNEL_DROPZONE_STUCK_INCIDENT_KIND
            and active.get("channel") == channel
            and int(active.get("global_id") or -1) == int(global_id)
        )

    x1, y1, x2, y2 = bbox
    runtime_stats.setActiveIncident(
        {
            "kind": CHANNEL_DROPZONE_STUCK_INCIDENT_KIND,
            "severity": "warning",
            "status": "waiting_for_operator",
            "awaiting_operator": True,
            "scope": "feeder",
            "channel": channel,
            "role": role,
            "channel_label": channel_label,
            "global_id": int(global_id),
            "track_id": int(global_id),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "bbox_center": [(float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0],
            "triggered_at": time.time(),
            "overlap_ratio": float(overlap_ratio),
            "overlap_threshold": float(overlap_threshold),
            "stall_ms": int(stall_ms),
            "accumulated_motion_ms": int(stall_ms),
            "rule": "bbox_dropzone_overlap_ge_two_thirds_for_accumulated_channel_motion",
            "resolution": "operator_acknowledge_to_ignore_until_dropzone_clear",
        }
    )
    return True


def publish_c2_separation_incident(
    gc: Any,
    *,
    detection_count: int,
    ch2_action: str,
    downstream_busy: bool,
) -> bool:
    if _incident_handling_off(C2_SEPARATION_INCIDENT_KIND):
        return False
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    if isinstance(active, dict):
        return active.get("kind") == C2_SEPARATION_INCIDENT_KIND

    runtime_stats.setActiveIncident(
        {
            "kind": C2_SEPARATION_INCIDENT_KIND,
            "severity": "warning",
            "status": "waiting_for_operator",
            "awaiting_operator": True,
            "scope": "feeder",
            "channel": "c2",
            "role": "c_channel_2",
            "channel_label": "C-Channel 2",
            "triggered_at": time.time(),
            "strategy": "slip_stick_separation",
            "automated_motion_enabled": False,
            "detection_count": int(detection_count),
            "ch2_action": str(ch2_action),
            "downstream_busy": bool(downstream_busy),
            "reason": "c2_distribution_would_have_started_slip_stick",
        }
    )
    return True


__all__ = ["BaseStation", "FeederTickContext"]


def _incident_handling_off(kind: str) -> bool:
    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(kind))
    except Exception:
        return False
