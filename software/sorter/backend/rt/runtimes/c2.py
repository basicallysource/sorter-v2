"""RuntimeC2 — separation seed shuttle.

Reads ``TrackBatch`` from ``c2_feed`` (PolarTracker output), gates forward
pulses on the C2->C3 capacity slot, and triggers an exit-zone wiggle when a
piece is stuck at the exit but downstream is closed. Port of:

* ``subsystems/channels/c2_separation.py`` — pulse dispatch + exit-wiggle
* ``subsystems/feeder/analysis.py``        — track-to-action mapping

Pulse modes mirror C3:
* PRECISE — track is inside the approach or exit arc; uses
  ``second_rotor_precision`` for small, slow steps so pieces ease into the
  C2→C3 transition one at a time.
* NORMAL  — ring carries pieces but none is near the exit; uses
  ``second_rotor_normal`` for fast advance so material reaches the exit
  zone quickly.

The runtime keeps the AdmissionStrategy hook from §2.11 so the interface
matches Phase 4/5 runtimes; for C2 the default ``AlwaysAdmit`` is fine.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from rt.contracts.admission import AdmissionStrategy
from rt.contracts.ejection import EjectionTimingStrategy
from rt.contracts.events import Event, EventBus
from rt.contracts.purge import PurgeCounts, PurgePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.topics import PERCEPTION_ROTATION, RUNTIME_HANDOFF_BURST
from rt.hardware.motion_profiles import (
    PROFILE_CONTINUOUS,
    PROFILE_GENTLE,
    PROFILE_PURGE,
    PROFILE_TRANSPORT,
)
from rt.perception.track_policy import action_track, is_visible_track
from rt.services.transport_velocity import TransportVelocityObserver

from ._handoff_diagnostics import HandoffDiagnostics
from ._move_events import publish_move_completed
from ._strategies import AlwaysAdmit, ConstantPulseEjection
from .base import BaseRuntime, HwWorker


# Exit-zone wiggle defaults (output-shaft degrees). Mirror legacy
# ``base.EXIT_WIGGLE_*`` constants.
DEFAULT_EXIT_ZONE_NEAR_ARC_RAD = math.radians(30.0)
# Deceleration zone in front of the exit. Once a confirmed-real track is
# inside this arc but not yet in the commit zone, C2 switches to small
# precision pulses so pieces are fed gently into the C2→C3 transition
# rather than blasted through in batches.
DEFAULT_APPROACH_NEAR_ARC_RAD = math.radians(45.0)
DEFAULT_INTAKE_ZONE_NEAR_ARC_RAD = math.radians(30.0)
DEFAULT_MAX_PIECE_COUNT = 5
DEFAULT_PULSE_COOLDOWN_S = 0.12
DEFAULT_WIGGLE_STALL_MS = 600
DEFAULT_WIGGLE_COOLDOWN_MS = 1200
DEFAULT_TRACK_STALE_S = 0.5
# Idle cadence for the advance pulse: when the ring carries tracks but none
# is in the exit near-arc, pulse periodically to (a) bring real pieces
# toward the exit and (b) give the ghost-gating tracker enough rotation
# windows to declare stationary phantoms.
DEFAULT_ADVANCE_INTERVAL_S = 1.2
ACTION_TRACK_MIN_HITS = 2
# Extra seconds on either side of a pulse window so the next few frames
# (hardware latency, frame-capture jitter) still count as "during rotation".
_ROTATION_WINDOW_PAD_S = 0.15
DEFAULT_SAMPLE_TRANSPORT_TARGET_INTERVAL_S = 0.75
DEFAULT_SAMPLE_TRANSPORT_MIN_STEP_DEG = 15.0
DEFAULT_SAMPLE_TRANSPORT_MAX_STEP_DEG = 90.0
DEFAULT_TRANSPORT_TARGET_RPM = 1.2
DEFAULT_DOWNSTREAM_CLAIM_HOLD_S = 3.0
DEFAULT_EXIT_HANDOFF_MIN_INTERVAL_S = 0.85
DEFAULT_HANDOFF_RETRY_ESCALATE_AFTER = 2
DEFAULT_HANDOFF_RETRY_MAX_PULSES = 2


class _PulseMode(Enum):
    NORMAL = "normal"
    PRECISE = "precise"


@dataclass(slots=True)
class _PieceBookkeeping:
    # Tracks we've already credited as 'arrived' (so we can release the
    # upstream slot exactly once per piece).
    seen_global_ids: set[int]
    exit_stall_since: float | None = None
    next_wiggle_at: float = 0.0
    next_advance_at: float = 0.0


class RuntimeC2(BaseRuntime):
    """Separation rotor: pulses pieces from the C2 ring to C3."""

    PulseMode = _PulseMode

    def __init__(
        self,
        *,
        upstream_slot: CapacitySlot,
        downstream_slot: CapacitySlot,
        pulse_command: Callable[..., bool],
        wiggle_command: Callable[[], bool],
        sample_transport_command: Callable[[float, int | None, int | None], bool] | None = None,
        admission: AdmissionStrategy | None = None,
        ejection_timing: EjectionTimingStrategy | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        event_bus: EventBus | None = None,
        max_piece_count: int = DEFAULT_MAX_PIECE_COUNT,
        exit_zone_near_arc_rad: float = DEFAULT_EXIT_ZONE_NEAR_ARC_RAD,
        approach_zone_near_arc_rad: float = DEFAULT_APPROACH_NEAR_ARC_RAD,
        intake_zone_near_arc_rad: float = DEFAULT_INTAKE_ZONE_NEAR_ARC_RAD,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
        wiggle_stall_ms: int = DEFAULT_WIGGLE_STALL_MS,
        wiggle_cooldown_ms: int = DEFAULT_WIGGLE_COOLDOWN_MS,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        advance_interval_s: float = DEFAULT_ADVANCE_INTERVAL_S,
        exit_handoff_min_interval_s: float = DEFAULT_EXIT_HANDOFF_MIN_INTERVAL_S,
        handoff_retry_escalate_after: int = DEFAULT_HANDOFF_RETRY_ESCALATE_AFTER,
        handoff_retry_max_pulses: int = DEFAULT_HANDOFF_RETRY_MAX_PULSES,
        feed_id: str = "c2_feed",
        state_observer: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(
            "c2", feed_id=feed_id, logger=logger, hw_worker=hw_worker,
            state_observer=state_observer,
        )
        self._upstream_slot = upstream_slot
        self._downstream_slot = downstream_slot
        self._pulse_command = pulse_command
        self._wiggle_command = wiggle_command
        self._sample_transport_command = sample_transport_command
        self._admission = admission or AlwaysAdmit()
        self._ejection = ejection_timing or ConstantPulseEjection()
        self._bus = event_bus
        self._max_piece_count = max(1, int(max_piece_count))
        self._exit_near_arc = float(exit_zone_near_arc_rad)
        self._approach_near_arc = max(
            float(exit_zone_near_arc_rad),
            float(approach_zone_near_arc_rad),
        )
        self._intake_near_arc = float(intake_zone_near_arc_rad)
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._wiggle_stall_s = float(wiggle_stall_ms) / 1000.0
        self._wiggle_cooldown_s = float(wiggle_cooldown_ms) / 1000.0
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._advance_interval_s = max(0.0, float(advance_interval_s))
        self._exit_handoff_min_interval_s = max(
            0.0,
            float(exit_handoff_min_interval_s),
        )
        self._handoff_retry_escalate_after = max(
            1,
            int(handoff_retry_escalate_after),
        )
        self._handoff_retry_max_pulses = max(1, int(handoff_retry_max_pulses))
        self._bookkeeping = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._next_exit_handoff_at: float = 0.0
        self._piece_count: int = 0
        self._admission_piece_count: int = 0
        self._visible_track_count: int = 0
        self._pending_track_count: int = 0
        self._pending_downstream_claims: dict[int, float] = {}
        self._pending_downstream_claim_retries: dict[int, int] = {}
        self._arrival_diagnostics_armed: bool = False
        self._purge_mode: bool = False
        self._sample_transport_step_deg: float | None = None
        self._sample_transport_max_speed: int | None = None
        self._sample_transport_acceleration: int | None = None
        self._transport_velocity = TransportVelocityObserver(
            channel="c2",
            exit_angle_deg=0.0,
            target_rpm=DEFAULT_TRANSPORT_TARGET_RPM,
        )
        self._handoff_diagnostics = HandoffDiagnostics(
            runtime_id=self.runtime_id,
            feed_id=self.feed_id,
            logger=self._logger,
        )

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        """Whether C1 may push another piece downstream.

        Unlike C3 (whose cap was decoupled from this gate), C2's cap is
        the only signal C1 has telling it the bulk feeder is overrunning
        the C2 ring. Without this gate C1's jam-recovery logic falsely
        fires when C2 is already too full for new pieces to make
        operator-visible progress, and C1 ends up paused with
        ``jam_recovery_exhausted`` on a perfectly healthy hopper.
        """
        if self._purge_mode:
            return 0
        if self._admission_piece_count >= self._max_piece_count:
            return 0
        return 1

    def debug_snapshot(self) -> dict[str, Any]:
        snap = super().debug_snapshot()
        snap.update({
            "piece_count": int(self._piece_count),
            "admission_piece_count": int(self._admission_piece_count),
            "visible_track_count": int(self._visible_track_count),
            "pending_track_count": int(self._pending_track_count),
            "max_piece_count": int(self._max_piece_count),
            "available_slots": int(self.available_slots()),
            "upstream_taken": int(self._upstream_slot.taken()),
            "downstream_taken": int(self._downstream_slot.taken()),
            "pending_downstream_claims": len(self._pending_downstream_claims),
            "pending_downstream_retry_max": max(
                self._pending_downstream_claim_retries.values(),
                default=0,
            ),
            "handoff_retry_escalate_after": int(
                self._handoff_retry_escalate_after
            ),
            "handoff_retry_max_pulses": int(self._handoff_retry_max_pulses),
            "seen_global_ids": len(self._bookkeeping.seen_global_ids),
            "exit_stall_active": self._bookkeeping.exit_stall_since is not None,
            "exit_handoff_spacing_s": max(0.0, self._next_exit_handoff_at - time.monotonic()),
            "exit_handoff_min_interval_s": float(self._exit_handoff_min_interval_s),
            "transport_velocity": self._transport_velocity.snapshot.as_dict(),
            "handoff_burst_diagnostics": self._handoff_diagnostics.snapshot(),
        })
        return snap

    def inspect_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        claims = [
            {
                "global_id": int(gid),
                "deadline_age_s": float(deadline) - ts,
                "retry_count": int(self._pending_downstream_claim_retries.get(gid, 0)),
            }
            for gid, deadline in self._pending_downstream_claims.items()
        ]
        claims.sort(key=lambda c: c["deadline_age_s"])
        return {
            "piece_count": int(self._piece_count),
            "visible_track_count": int(self._visible_track_count),
            "pending_track_count": int(self._pending_track_count),
            "upstream_slot_taken": int(self._upstream_slot.taken(now_mono=ts)),
            "downstream_slot_taken": int(self._downstream_slot.taken(now_mono=ts)),
            "pending_downstream_claims": claims,
            "next_pulse_in_s": max(0.0, self._next_pulse_at - ts),
            "next_exit_handoff_in_s": max(0.0, self._next_exit_handoff_at - ts),
            "exit_handoff_min_interval_s": float(self._exit_handoff_min_interval_s),
            "exit_near_arc_deg": math.degrees(self._exit_near_arc),
            "approach_near_arc_deg": math.degrees(self._approach_near_arc),
            "exit_stall_active": self._bookkeeping.exit_stall_since is not None,
            "max_piece_count": int(self._max_piece_count),
        }

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            self._sweep_pending_downstream_claims(now_mono)
            tracks = self._fresh_tracks(inbox.tracks)
            visible_tracks = [t for t in tracks if is_visible_track(t)]
            action_tracks = [
                t for t in visible_tracks if action_track(t, min_hits=ACTION_TRACK_MIN_HITS)
            ]
            self._visible_track_count = len(visible_tracks)
            self._pending_track_count = max(0, self._visible_track_count - len(action_tracks))
            self._piece_count = len(action_tracks)
            self._admission_piece_count = len(action_tracks)
            self._transport_velocity.update(action_tracks, now_mono=now_mono)
            if not self._purge_mode:
                self._credit_new_arrivals(action_tracks, now_mono)
            exit_track = self._pick_exit_track(visible_tracks)
            approach_track = self._pick_approach_track(visible_tracks)
            if self._hw.busy():
                self._set_state("pulsing", blocked_reason="hw_busy")
                return
            if now_mono < self._next_pulse_at:
                self._set_state("pulsing", blocked_reason="cooldown")
                return
            if self._purge_mode:
                self._dispatch_purge_pulse(now_mono)
                return
            if exit_track is not None and self._has_pending_downstream_claim(
                exit_track, now_mono
            ):
                if now_mono < self._next_exit_handoff_at:
                    self._bookkeeping.exit_stall_since = None
                    self._set_state(
                        "handoff_wait",
                        blocked_reason="awaiting_downstream_arrival",
                    )
                else:
                    self._dispatch_exit_retry_pulse(exit_track, now_mono)
                return
            if (
                now_mono < self._next_exit_handoff_at
                and (exit_track is not None or approach_track is not None)
            ):
                self._bookkeeping.exit_stall_since = None
                self._set_state("handoff_spacing", blocked_reason="exit_spacing")
                return
            if inbox.capacity_downstream <= 0:
                self._bookkeeping.exit_stall_since = None
                self._set_state("idle", blocked_reason="downstream_full")
                return
            if exit_track is not None:
                self._dispatch_exit_pulse(exit_track, now_mono)
                return
            self._bookkeeping.exit_stall_since = None
            if approach_track is not None:
                # Track is decelerating into the exit zone — fire small
                # precision pulses without claiming a downstream slot so the
                # piece eases up to the drop edge instead of being slammed
                # off the ring.
                self._dispatch_approach_pulse(approach_track, now_mono)
                return
            if visible_tracks and now_mono >= self._bookkeeping.next_advance_at:
                # Nothing close to the exit yet — advance the ring at full
                # transport speed so real pieces migrate toward the exit
                # and the ghost-gating tracker accumulates rotation
                # evidence for stationary phantoms.
                self._dispatch_advance_pulse(now_mono)
            else:
                self._set_state("idle")
        finally:
            self._tick_end(start)

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # C3 confirms it accepted a piece from us — release the upstream
        # slot so C1 sees headroom.
        self._upstream_slot.release()

    def sample_transport_port(self) -> "_C2SampleTransportPort":
        return _C2SampleTransportPort(self)

    # ------------------------------------------------------------------
    # Internals

    def _fresh_tracks(self, batch: TrackBatch | None) -> list[Track]:
        if batch is None:
            return []
        batch_ts = float(batch.timestamp)
        return [
            t
            for t in batch.tracks
            if self._is_track_fresh(t, batch_ts)
        ]

    def _is_track_fresh(self, track: Track, batch_ts: float) -> bool:
        last_seen_ts = float(track.last_seen_ts)
        if batch_ts <= 0.0 or last_seen_ts <= 0.0:
            return True
        return (batch_ts - last_seen_ts) <= self._track_stale_s

    def _credit_new_arrivals(self, tracks: list[Track], now_mono: float) -> None:
        seen = self._bookkeeping.seen_global_ids
        arrivals: list[dict[str, Any]] = []
        for t in tracks:
            if t.global_id is None:
                continue
            if t.global_id in seen:
                continue
            seen.add(t.global_id)
            arrivals.append(self._track_diagnostics(t))
            # A new confirmed piece entered C2's ring — release the upstream
            # slot reservation so C1 sees headroom.
            self._upstream_slot.release()
        if arrivals and self._arrival_diagnostics_armed:
            self._record_arrival_burst(arrivals, now_mono)
        elif arrivals:
            self._arrival_diagnostics_armed = True

    def _pick_exit_track(self, tracks: list[Track]) -> Track | None:
        # Commit zone: stable tracks within ``exit_near_arc``. The detector
        # is the primary signal — rotation-window confirmation is strong
        # evidence but stable non-ghost detections may commit before it
        # catches up.
        return self._closest_actionable_within(tracks, self._exit_near_arc)

    def _pick_approach_track(self, tracks: list[Track]) -> Track | None:
        # Deceleration zone: stable tracks inside ``approach_near_arc`` but
        # not yet inside the commit arc. Drives small precise pulses
        # without claiming a downstream slot.
        approach = self._closest_actionable_within(tracks, self._approach_near_arc)
        if approach is None:
            return None
        if abs(_wrap_rad(approach.angle_rad or 0.0)) <= self._exit_near_arc:
            return None
        return approach

    def _closest_actionable_within(
        self, tracks: list[Track], arc: float
    ) -> Track | None:
        candidates = [
            t for t in tracks
            if t.angle_rad is not None and action_track(t, min_hits=ACTION_TRACK_MIN_HITS)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: abs(_wrap_rad(t.angle_rad or 0.0)))
        head = candidates[0]
        if abs(_wrap_rad(head.angle_rad or 0.0)) > arc:
            return None
        return head

    def _dispatch_exit_pulse(self, track: Track, now_mono: float) -> None:
        # Give the downstream handoff ~3 s to resolve (C3 registers the
        # arriving piece or the slot auto-releases so the ring can keep
        # flowing if the pulse never produced a visible arrival).
        claim_key = self._downstream_claim_key(track)
        if claim_key is not None and self._has_pending_downstream_claim(
            track, now_mono
        ):
            self._set_state(
                "handoff_wait",
                blocked_reason="awaiting_downstream_arrival",
            )
            return
        claimed = self._downstream_slot.try_claim(
            now_mono=now_mono,
            hold_time_s=DEFAULT_DOWNSTREAM_CLAIM_HOLD_S,
        )
        if not claimed:
            self._set_state("idle", blocked_reason="downstream_full")
            return
        if claim_key is not None:
            self._pending_downstream_claims[claim_key] = (
                now_mono + DEFAULT_DOWNSTREAM_CLAIM_HOLD_S
            )
            self._pending_downstream_claim_retries[claim_key] = 0
        self._next_exit_handoff_at = now_mono + self._exit_handoff_min_interval_s
        self._bookkeeping.exit_stall_since = None
        self._fire_pulse(
            track=track,
            mode=_PulseMode.PRECISE,
            now_mono=now_mono,
            commit_to_downstream=claimed,
            downstream_claim_key=claim_key if claimed else None,
            source="c2_pulse",
            label="c2_pulse",
            state="pulsing",
        )

    def _dispatch_exit_retry_pulse(self, track: Track, now_mono: float) -> None:
        self._next_exit_handoff_at = now_mono + self._exit_handoff_min_interval_s
        self._bookkeeping.exit_stall_since = None
        retry_count = self._bump_downstream_retry_count(track)
        repeat_count = self._handoff_retry_repeat_count(retry_count)
        self._fire_pulse(
            track=track,
            mode=_PulseMode.PRECISE,
            now_mono=now_mono,
            commit_to_downstream=False,
            source="c2_exit_retry_pulse",
            label="c2_exit_retry_pulse",
            state="handoff_retry",
            repeat_count=repeat_count,
        )

    def _dispatch_approach_pulse(self, track: Track, now_mono: float) -> None:
        """Slow precision pulse for a track decelerating into the exit zone."""
        self._fire_pulse(
            track=track,
            mode=_PulseMode.PRECISE,
            now_mono=now_mono,
            commit_to_downstream=False,
            source="c2_approach_pulse",
            label="c2_approach_pulse",
            state="approaching",
        )

    def _dispatch_advance_pulse(self, now_mono: float) -> None:
        """Rotate the ring without claiming a slot.

        Fired when the ring carries tracks but none is in the approach or
        exit zone. A single far-away piece can still advance quickly; a
        loaded ring uses precise pulses so C2 does not dump a short train
        into C3 before the exit gate has a chance to singulate it.
        """
        mode = _PulseMode.PRECISE if self._piece_count >= 2 else _PulseMode.NORMAL
        self._fire_pulse(
            track=None,
            mode=mode,
            now_mono=now_mono,
            commit_to_downstream=False,
            source="c2_advance_pulse",
            label="c2_advance_pulse",
            state="advancing",
        )
        self._bookkeeping.next_advance_at = now_mono + self._advance_interval_s

    def _fire_pulse(
        self,
        *,
        track: Track | None,
        mode: _PulseMode,
        now_mono: float,
        commit_to_downstream: bool,
        source: str,
        label: str,
        state: str,
        downstream_claim_key: int | None = None,
        repeat_count: int = 1,
    ) -> None:
        repeat_count = max(1, int(repeat_count))
        ejection_ctx: dict[str, Any] = {"mode": mode.value}
        if track is not None:
            ejection_ctx["track_id"] = track.track_id
        if mode is _PulseMode.NORMAL and track is None:
            ejection_ctx["advance"] = True
        timing = self._ejection.timing_for(ejection_ctx)
        profile_name = (
            PROFILE_GENTLE if mode is _PulseMode.PRECISE else PROFILE_TRANSPORT
        )
        move_context = self._record_handoff_move(
            now_mono=now_mono,
            source=source,
            mode=mode.value,
            repeat_count=repeat_count,
            commit_to_downstream=commit_to_downstream,
            track=track,
        )

        def _run_pulse() -> None:
            ok = False
            completed_count = 0
            try:
                ok = True
                for _ in range(repeat_count):
                    if not bool(self._pulse_command(mode, timing.pulse_ms, profile_name)):
                        ok = False
                        break
                    completed_count += 1
            except Exception:
                ok = False
                self._logger.exception("RuntimeC2: pulse command raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source=source,
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms * repeat_count,
                    extra={
                        "mode": mode.value,
                        "repeat_count": repeat_count,
                        "completed_count": completed_count,
                        "commit_to_downstream": bool(commit_to_downstream),
                        "piece_count": int(self._piece_count),
                        "visible_track_count": int(self._visible_track_count),
                        "track_global_id": move_context.get("track_global_id"),
                        "track_angle_deg": move_context.get("track_angle_deg"),
                    },
                )
            if not ok and commit_to_downstream:
                self._downstream_slot.release()
                if downstream_claim_key is not None:
                    self._pending_downstream_claims.pop(downstream_claim_key, None)
                    self._pending_downstream_claim_retries.pop(
                        downstream_claim_key,
                        None,
                    )

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label=label)
        if not enqueued:
            if commit_to_downstream:
                self._downstream_slot.release()
                if downstream_claim_key is not None:
                    self._pending_downstream_claims.pop(downstream_claim_key, None)
                    self._pending_downstream_claim_retries.pop(
                        downstream_claim_key,
                        None,
                    )
            self._set_state(state, blocked_reason="hw_queue_full")
            return
        self._publish_rotation_window(
            (timing.pulse_ms * repeat_count) / 1000.0,
            now_mono,
        )
        self._set_state(state)

    def _dispatch_sample_transport_pulse(self, now_mono: float) -> bool:
        """Rotate C2 without admission or downstream slot gating."""
        if self._hw.busy() or self._hw.pending() > 0:
            self._set_state("sample_transport", blocked_reason="hw_busy")
            return False
        mode = _PulseMode.NORMAL
        timing = self._ejection.timing_for(
            {"sample_transport": True, "mode": mode.value}
        )

        def _run_pulse() -> None:
            ok = False
            try:
                if (
                    self._sample_transport_command is not None
                    and self._sample_transport_step_deg
                ):
                    ok = bool(
                        self._sample_transport_command(
                            self._sample_transport_step_deg,
                            self._sample_transport_max_speed,
                            self._sample_transport_acceleration,
                        )
                    )
                else:
                    ok = bool(
                        self._pulse_command(
                            mode,
                            timing.pulse_ms,
                            PROFILE_CONTINUOUS,
                        )
                    )
            except Exception:
                self._logger.exception("RuntimeC2: sample transport pulse raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source="c2_sample_transport",
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms,
                    extra={"sample_transport": True},
                )

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c2_sample_transport")
        if not enqueued:
            self._set_state("sample_transport", blocked_reason="hw_queue_full")
            return False
        self._publish_rotation_window(timing.pulse_ms / 1000.0, now_mono)
        self._set_state("sample_transport")
        return True

    def _configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self._sample_transport_max_speed = direct_max_speed_usteps_per_s
        self._sample_transport_acceleration = direct_acceleration_usteps_per_s2
        if target_rpm is None:
            self._sample_transport_step_deg = None
            return
        target_degrees_per_second = max(0.0, float(target_rpm)) * 6.0
        step = target_degrees_per_second * DEFAULT_SAMPLE_TRANSPORT_TARGET_INTERVAL_S
        self._sample_transport_step_deg = max(
            DEFAULT_SAMPLE_TRANSPORT_MIN_STEP_DEG,
            min(DEFAULT_SAMPLE_TRANSPORT_MAX_STEP_DEG, step),
        )

    def _dispatch_purge_pulse(self, now_mono: float) -> None:
        """Pulse the ring without gating on downstream capacity or exit_track.

        Used during C2 purge: rotate the platter so pieces fall through the
        C2->C3 transition regardless of whether C3 is full. Does not claim a
        downstream slot.
        """
        mode = _PulseMode.NORMAL
        timing = self._ejection.timing_for({"purge": True, "mode": mode.value})

        def _run_pulse() -> None:
            ok = False
            try:
                ok = bool(self._pulse_command(mode, timing.pulse_ms, PROFILE_PURGE))
            except Exception:
                self._logger.exception("RuntimeC2: purge pulse command raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source="c2_purge_pulse",
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms,
                )

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c2_purge_pulse")
        if not enqueued:
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._publish_rotation_window(timing.pulse_ms / 1000.0, now_mono)
        self._set_state("pulsing", blocked_reason="purge")

    def _publish_rotation_window(self, duration_s: float, now_mono: float) -> None:
        # Tell the perception tracker that the ring is rotating around *now*
        # for ``duration_s`` seconds — a padded window so the following few
        # frames count as during-rotation. Timestamps are wall-clock so they
        # match FeedFrame.timestamp in the tracker.
        if self._bus is None:
            return
        now_wall = time.time()
        start = now_wall - _ROTATION_WINDOW_PAD_S
        end = now_wall + float(duration_s) + _ROTATION_WINDOW_PAD_S
        try:
            self._bus.publish(
                Event(
                    topic=PERCEPTION_ROTATION,
                    payload={
                        "feed_id": self.feed_id,
                        "start_ts": float(start),
                        "end_ts": float(end),
                        "source": "c2_pulse",
                    },
                    source=self.runtime_id,
                    ts_mono=float(now_mono),
                )
            )
        except Exception:
            self._logger.exception("RuntimeC2: rotation-window publish failed")

    def purge_port(self) -> PurgePort:
        return _C2PurgePort(self)

    def _reset_bookkeeping(self) -> None:
        self._bookkeeping = _PieceBookkeeping(seen_global_ids=set())
        self._piece_count = 0
        self._admission_piece_count = 0
        self._visible_track_count = 0
        self._pending_track_count = 0
        self._pending_downstream_claims.clear()
        self._pending_downstream_claim_retries.clear()
        self._arrival_diagnostics_armed = False
        self._next_pulse_at = 0.0
        self._next_exit_handoff_at = 0.0
        self._handoff_diagnostics.reset()

    def _downstream_claim_key(self, track: Track) -> int | None:
        if track.global_id is None:
            return None
        try:
            return int(track.global_id)
        except (TypeError, ValueError):
            return None

    def _has_pending_downstream_claim(self, track: Track, now_mono: float) -> bool:
        key = self._downstream_claim_key(track)
        if key is None:
            return False
        return self._pending_downstream_claims.get(key, 0.0) > now_mono

    def _sweep_pending_downstream_claims(self, now_mono: float) -> None:
        expired = [
            global_id for global_id, deadline in self._pending_downstream_claims.items()
            if deadline <= now_mono
        ]
        for global_id in expired:
            self._pending_downstream_claims.pop(global_id, None)
            self._pending_downstream_claim_retries.pop(global_id, None)

    def _bump_downstream_retry_count(self, track: Track) -> int:
        key = self._downstream_claim_key(track)
        if key is None:
            return 1
        count = self._pending_downstream_claim_retries.get(key, 0) + 1
        self._pending_downstream_claim_retries[key] = count
        return count

    def _handoff_retry_repeat_count(self, retry_count: int) -> int:
        if retry_count >= self._handoff_retry_escalate_after:
            return self._handoff_retry_max_pulses
        return 1

    def _record_handoff_move(
        self,
        *,
        now_mono: float,
        source: str,
        mode: str,
        repeat_count: int,
        commit_to_downstream: bool,
        track: Track | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": source,
            "mode": mode,
            "repeat_count": int(repeat_count),
            "commit_to_downstream": bool(commit_to_downstream),
            "piece_count": int(self._piece_count),
            "visible_track_count": int(self._visible_track_count),
            "pending_downstream_claims": len(self._pending_downstream_claims),
            "upstream_taken": int(self._upstream_slot.taken()),
            "downstream_taken": int(self._downstream_slot.taken()),
        }
        if track is not None:
            payload.update({
                "track_global_id": track.global_id,
                "track_angle_deg": self._track_angle_deg(track),
            })
        return self._handoff_diagnostics.record_move(
            now_mono=now_mono,
            **payload,
        )

    def _record_arrival_burst(
        self,
        arrivals: list[dict[str, Any]],
        now_mono: float,
    ) -> None:
        anomaly = self._handoff_diagnostics.record_arrivals(
            now_mono=now_mono,
            arrivals=arrivals,
            context={
                "piece_count": self._piece_count,
                "visible_track_count": self._visible_track_count,
                "pending_track_count": self._pending_track_count,
                "upstream_taken": self._upstream_slot.taken(),
                "downstream_taken": self._downstream_slot.taken(),
                "pending_downstream_claims": len(self._pending_downstream_claims),
            },
        )
        if anomaly is not None:
            self._publish_handoff_burst(anomaly, now_mono)

    def _publish_handoff_burst(
        self,
        anomaly: dict[str, Any],
        now_mono: float,
    ) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(
                Event(
                    topic=RUNTIME_HANDOFF_BURST,
                    payload=anomaly,
                    source=self.runtime_id,
                    ts_mono=float(now_mono),
                )
            )
        except Exception:
            self._logger.exception("RuntimeC2: handoff-burst publish failed")

    def _track_diagnostics(self, track: Track) -> dict[str, Any]:
        return {
            "track_id": track.track_id,
            "global_id": track.global_id,
            "piece_uuid": track.piece_uuid,
            "angle_deg": self._track_angle_deg(track),
            "score": float(track.score),
            "hit_count": int(track.hit_count),
            "confirmed_real": bool(track.confirmed_real),
        }

    def _track_angle_deg(self, track: Track) -> float | None:
        if track.angle_rad is None:
            return None
        return math.degrees(float(track.angle_rad))

    def _maybe_wiggle(self, exit_track: Track | None, now_mono: float) -> bool:
        if exit_track is None:
            self._bookkeeping.exit_stall_since = None
            return False
        if self._bookkeeping.exit_stall_since is None:
            self._bookkeeping.exit_stall_since = now_mono
            return False
        stall = now_mono - self._bookkeeping.exit_stall_since
        if stall < self._wiggle_stall_s:
            return False
        if now_mono < self._bookkeeping.next_wiggle_at:
            return False
        if self._hw.busy():
            return False

        def _run_wiggle() -> None:
            try:
                self._wiggle_command()
            except Exception:
                self._logger.exception("RuntimeC2: wiggle command raised")

        enqueued = self._hw.enqueue(_run_wiggle, label="c2_exit_wiggle")
        if enqueued:
            self._bookkeeping.next_wiggle_at = now_mono + self._wiggle_cooldown_s
            self._set_state("exit_wiggle")
            return True
        return False

def _wrap_rad(angle: float) -> float:
    """Wrap to [-pi, pi]."""
    a = (angle + math.pi) % (2.0 * math.pi) - math.pi
    return a


class _C2PurgePort:
    """PurgePort binding for RuntimeC2.

    Arm flips ``_purge_mode`` so the normal tick path pulses regardless of
    downstream capacity and stops accepting new admission. Disarm clears
    state and flushes in-memory bookkeeping so the next run starts fresh.
    """

    key = "c2"

    def __init__(self, runtime: RuntimeC2) -> None:
        self._runtime = runtime

    def arm(self) -> None:
        self._runtime._purge_mode = True

    def disarm(self) -> None:
        self._runtime._purge_mode = False
        self._runtime._reset_bookkeeping()

    def counts(self) -> PurgeCounts:
        return PurgeCounts(
            piece_count=int(self._runtime._visible_track_count),
            owned_count=0,
            pending_detections=0,
        )

    def drain_step(self, now_mono: float) -> bool:
        return bool(self._runtime._purge_mode)


class _C2SampleTransportPort:
    key = "c2"

    def __init__(self, runtime: RuntimeC2) -> None:
        self._runtime = runtime

    def step(self, now_mono: float) -> bool:
        return self._runtime._dispatch_sample_transport_pulse(now_mono)

    def configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self._runtime._configure_sample_transport(
            target_rpm=target_rpm,
            direct_max_speed_usteps_per_s=direct_max_speed_usteps_per_s,
            direct_acceleration_usteps_per_s2=direct_acceleration_usteps_per_s2,
        )

    def nominal_degrees_per_step(self) -> float | None:
        if self._runtime._sample_transport_step_deg is not None:
            return float(self._runtime._sample_transport_step_deg)
        fn = getattr(self._runtime._pulse_command, "nominal_degrees_per_step", None)
        if callable(fn):
            value = fn()
            return float(value) if isinstance(value, (int, float)) and value > 0 else None
        return None


__all__ = ["RuntimeC2"]
