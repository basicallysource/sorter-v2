from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .config import PulsePerceptionConfig
from subsystems.feeder.incidents import (
    clear_feeder_jam_incident,
    feeder_jam_incident_active,
    publish_feeder_jam_incident,
    record_feeder_jam_auto_resolved,
)

# Motor-shaft to channel-output gear ratio. One output (LEGO wheel) degree needs
# this many motor degrees. Duplicated across the feeder flows on purpose (see
# flow.CHANNEL_OUTPUT_GEAR_RATIO) — keep them in sync.
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0

# Stepper min-speed floor for nudge moves. MUST stay > 0 (see the identical
# constant in flow.py) — a 0 floor wedges the firmware distance move non-STOPPED.
# Duplicated to avoid a circular import with flow.py; keep in sync.
MIN_MOVE_SPEED_USTEPS_PER_S = 16


@dataclass
class _ChannelStuckState:
    # Leading-piece travel position (com_forward_to_exit_deg) at the last moment
    # we credited real forward progress. com DECREASES as a piece moves toward
    # the exit, so progress = ref - current >= epsilon.
    ref_pos_deg: Optional[float]
    # Monotonic time of the last credited progress (or the last tick the channel
    # was intentionally holding for a busy downstream — we pause, not accrue).
    last_progress_at: float
    # Upstream nudges already spent on the CURRENT stall. Reset on progress, on
    # the piece leaving, or once the operator resolves the raised jam.
    nudge_attempts: int
    # Monotonic time the current stall was first detected as stuck (the moment of
    # the first nudge). Drives the recorded duration of an auto-freed jam. None
    # until the first nudge; cleared on every _reset.
    stall_started_at: Optional[float] = None


class FeederStuckWatchdog:
    """Recover the feeder->feeder phantom hand-off jam.

    A downstream feeder channel (C2 or C3) can keep pulsing a piece it sees in
    its own drop zone while the piece never advances — it is physically hung at
    the upstream channel's exit lip (about to fall from C1 onto C2, say), so the
    downstream camera reads it as "arrived" when it is really still on the
    upstream rotor. Turning the downstream rotor does nothing to it.

    Per downstream channel: watch the leading piece's travel position while the
    channel is actively trying to advance it. If it makes no forward progress for
    ``stuck_no_progress_ms``, nudge the UPSTREAM rotor a couple output degrees to
    push (or free) the piece the rest of the way onto this channel, then give it
    a fresh window. After ``stuck_max_nudge_attempts`` failed nudges, raise the
    operator-facing feeder-jam incident. All state is per channel and lives only
    on the coordinator thread (the feeder step)."""

    def __init__(self, gc: Any) -> None:
        self.gc = gc
        self._trackers: dict[int, _ChannelStuckState] = {}

    def _reset(self, channel_id: int, now: float, pos: Optional[float]) -> None:
        self._trackers[channel_id] = _ChannelStuckState(
            ref_pos_deg=pos, last_progress_at=now, nudge_attempts=0
        )

    def observe(
        self,
        *,
        channel_id: int,
        channel_label: str,
        upstream_label: str,
        upstream_stepper: Any,
        upstream_enabled: bool,
        leading_pos_deg: Optional[float],
        wants_advance: bool,
        cfg: PulsePerceptionConfig,
        now: float,
    ) -> None:
        if not cfg.stuck_watchdog_enabled or _handling_off():
            # Feature disabled or the operator set this incident to "off": drop
            # any state and never raise. (An already-raised jam clears the next
            # time the piece moves via the branch below only while enabled, so if
            # it was just turned off, clear it here too.)
            if feeder_jam_incident_active(self.gc, channel_label=channel_label):
                clear_feeder_jam_incident(self.gc, channel_label=channel_label)
            self._trackers.pop(channel_id, None)
            return

        tracker = self._trackers.get(channel_id)
        if tracker is None:
            self._reset(channel_id, now, leading_pos_deg)
            tracker = self._trackers[channel_id]

        piece_present = leading_pos_deg is not None

        # A jam we already raised for this channel is held until the piece moves
        # (operator freed it) or leaves entirely (operator removed it).
        if feeder_jam_incident_active(self.gc, channel_label=channel_label):
            if not piece_present:
                clear_feeder_jam_incident(self.gc, channel_label=channel_label)
                self._reset(channel_id, now, leading_pos_deg)
                return
            if tracker.ref_pos_deg is None:
                tracker.ref_pos_deg = leading_pos_deg
                return
            advanced = tracker.ref_pos_deg - float(leading_pos_deg)
            if advanced >= cfg.stuck_progress_epsilon_deg:
                clear_feeder_jam_incident(self.gc, channel_label=channel_label)
                self._reset(channel_id, now, leading_pos_deg)
            return

        if not piece_present:
            # Channel clear -> nothing to be stuck on. If nudges preceded the
            # piece leaving, the nudge pushed it the rest of the way off: an
            # auto-resolved jam, same as forward progress.
            self._record_auto_resolved_if_nudged(
                tracker, channel_id, channel_label, upstream_label, now
            )
            self._reset(channel_id, now, leading_pos_deg)
            return

        if tracker.ref_pos_deg is None:
            tracker.ref_pos_deg = leading_pos_deg
            tracker.last_progress_at = now
            return

        advanced = tracker.ref_pos_deg - float(leading_pos_deg)
        if advanced >= cfg.stuck_progress_epsilon_deg:
            # Real forward progress: the channel is doing its job. If nudges got
            # it here, the automatic watchdog just freed a jam without ever
            # escalating — record it so it lands in the durable log / dashboard.
            self._record_auto_resolved_if_nudged(
                tracker, channel_id, channel_label, upstream_label, now
            )
            tracker.ref_pos_deg = leading_pos_deg
            tracker.last_progress_at = now
            tracker.nudge_attempts = 0
            tracker.stall_started_at = None
            return

        if not wants_advance:
            # A piece sits on the channel but we are intentionally holding it
            # (downstream busy) — this is not a stall. Pause the clock; keep any
            # nudge attempts so a resumed-then-restalled piece still escalates.
            tracker.last_progress_at = now
            return

        stalled_ms = (now - tracker.last_progress_at) * 1000.0
        if stalled_ms < float(cfg.stuck_no_progress_ms):
            return

        automatic = _handling_automatic()
        if automatic and upstream_enabled and tracker.nudge_attempts < int(
            cfg.stuck_max_nudge_attempts
        ):
            moved = self._nudge_upstream(upstream_stepper, cfg)
            if tracker.nudge_attempts == 0:
                # First nudge of this stall: remember when it started (monotonic)
                # so an auto-freed jam records its real duration.
                tracker.stall_started_at = now - stalled_ms / 1000.0
            tracker.nudge_attempts += 1
            tracker.last_progress_at = now
            tracker.ref_pos_deg = leading_pos_deg
            logger = getattr(self.gc, "logger", None)
            if logger is not None:
                logger.info(
                    f"FeederStuckWatchdog: {channel_label} pulsing but piece not "
                    f"advancing for {stalled_ms:.0f}ms — nudged {upstream_label} "
                    f"forward {cfg.stuck_nudge_output_deg:.1f}° "
                    f"(attempt {tracker.nudge_attempts}/"
                    f"{int(cfg.stuck_max_nudge_attempts)}, ack={moved})"
                )
            return

        # Automatic nudges exhausted (or manual mode / no upstream to nudge):
        # hand it to the operator.
        published = publish_feeder_jam_incident(
            self.gc,
            channel_id=channel_id,
            channel_label=channel_label,
            upstream_label=upstream_label,
            no_progress_ms=stalled_ms,
            nudge_attempts=tracker.nudge_attempts,
        )
        logger = getattr(self.gc, "logger", None)
        if logger is not None:
            logger.warning(
                f"FeederStuckWatchdog: {channel_label} jam not cleared by "
                f"{tracker.nudge_attempts} {upstream_label} nudge(s) — raised "
                f"operator incident (published={published})"
            )
        # Keep ref so the active-incident branch can detect the piece moving once
        # the operator frees it; don't reset the clock (incident now owns it).

    def _record_auto_resolved_if_nudged(
        self,
        tracker: _ChannelStuckState,
        channel_id: int,
        channel_label: str,
        upstream_label: str,
        now: float,
    ) -> None:
        if tracker.nudge_attempts <= 0:
            return
        if feeder_jam_incident_active(self.gc, channel_label=channel_label):
            # An operator-facing jam is active for this channel; its own clear
            # path records the resolution. Don't double-log.
            return
        no_progress_ms = (
            (now - tracker.stall_started_at) * 1000.0
            if tracker.stall_started_at is not None
            else 0.0
        )
        record_feeder_jam_auto_resolved(
            self.gc,
            channel_id=channel_id,
            channel_label=channel_label,
            upstream_label=upstream_label,
            nudge_attempts=tracker.nudge_attempts,
            no_progress_ms=no_progress_ms,
        )

    def _nudge_upstream(
        self, upstream_stepper: Any, cfg: PulsePerceptionConfig
    ) -> bool:
        if upstream_stepper is None:
            return False
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        motor_deg = sign * abs(float(cfg.stuck_nudge_output_deg)) * CHANNEL_OUTPUT_GEAR_RATIO
        speed = int(cfg.move_speed_usteps_per_s)
        try:
            upstream_stepper.enabled = True
        except Exception:
            pass
        try:
            # min_speed MUST stay > 0 — a 0 floor wedges the firmware distance
            # move in a non-STOPPED state. Matches the feeder pulse floor.
            upstream_stepper.set_speed_limits(
                MIN_MOVE_SPEED_USTEPS_PER_S, max(MIN_MOVE_SPEED_USTEPS_PER_S, speed)
            )
        except Exception:
            pass
        try:
            return bool(upstream_stepper.move_degrees(motor_deg))
        except Exception:
            return False


def _handling_off() -> bool:
    from subsystems.feeder.incidents import FEEDER_JAM_INCIDENT_KIND

    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(FEEDER_JAM_INCIDENT_KIND))
    except Exception:
        return False


def _handling_automatic() -> bool:
    from subsystems.feeder.incidents import FEEDER_JAM_INCIDENT_KIND

    try:
        from toml_config import incidentHandlingAutomatic

        return bool(incidentHandlingAutomatic(FEEDER_JAM_INCIDENT_KIND))
    except Exception:
        return True
