"""RuntimeC3 — separation seed shuttle with precise exit handoff.

Reads ``TrackBatch`` from ``c3_feed``, gates forward pulses on the C3->C4
capacity slot, and runs a 2 s holdover window where normal pulses are
promoted to precise pulses after a precise detection (port of
``subsystems/feeder/strategies/c3_holdover.py``). The exit-zone wiggle is
the same shape as C2 but fires when C3->C4 is closed and a piece is stuck.

Two pulse types:
* precise — piece is within the exit-zone near arc
* normal  — piece is elsewhere on the ring

The ``EjectionTimingStrategy`` decides the pulse_ms per piece context; the
default ``ConstantPulseEjection`` wraps the legacy hard-coded ms values.
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
from rt.contracts.landing_lease import LandingLeasePort
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
from rt.services.track_transit import TrackTransitRegistry
from rt.services.transport_velocity import TransportVelocityObserver

from ._handoff_diagnostics import HandoffDiagnostics
from ._move_events import publish_move_completed
from ._strategies import AlwaysAdmit, ConstantPulseEjection
from .base import BaseRuntime, HwWorker


DEFAULT_EXIT_ZONE_NEAR_ARC_RAD = math.radians(20.0)
# Deceleration zone: once a stable track enters this arc but is not yet
# inside the commit zone, C3 switches to precise (slow) pulses so the
# piece eases into the C3→C4 transition instead of being slammed at
# normal-pulse velocity. Pulses outside this arc run at full transport
# speed so material reaches the exit quickly.
DEFAULT_APPROACH_NEAR_ARC_RAD = math.radians(45.0)
# Controlled-density target: 10 PPM lab tuning settled on ~8 visible
# pieces on C3 as the upper end where singulation still works. Lower
# values (the previous 3) starved C4 because admission immediately
# refused upstream handoffs whenever C3 carried >3 visible tracks,
# which it routinely does after a C1 burst.
DEFAULT_MAX_PIECE_COUNT = 8
DEFAULT_PULSE_COOLDOWN_S = 0.12
DEFAULT_WIGGLE_STALL_MS = 600
DEFAULT_WIGGLE_COOLDOWN_MS = 1200
DEFAULT_HOLDOVER_MS = 2000  # Mirror legacy CH3_PRECISE_HOLDOVER_MS.
DEFAULT_TRACK_STALE_S = 0.5
DEFAULT_SAMPLE_TRANSPORT_TARGET_INTERVAL_S = 0.75
DEFAULT_SAMPLE_TRANSPORT_MIN_STEP_DEG = 15.0
DEFAULT_SAMPLE_TRANSPORT_MAX_STEP_DEG = 90.0
DEFAULT_TRANSPORT_TARGET_RPM = 1.2
DEFAULT_DOWNSTREAM_CLAIM_HOLD_S = 3.0
DEFAULT_EXIT_HANDOFF_MIN_INTERVAL_S = 0.85
DEFAULT_HANDOFF_RETRY_ESCALATE_AFTER = 2
DEFAULT_HANDOFF_RETRY_MAX_PULSES = 2
ACTION_TRACK_MIN_HITS = 2
# Padding on either side of a pulse window so frame-capture jitter still
# lands inside the rotation window for the ghost-gating tracker.
_ROTATION_WINDOW_PAD_S = 0.15


class _PulseMode(Enum):
    NORMAL = "normal"
    PRECISE = "precise"


@dataclass(slots=True)
class _PieceBookkeeping:
    seen_global_ids: set[int]
    exit_stall_since: float | None = None
    next_wiggle_at: float = 0.0
    last_precise_at: float | None = None


class RuntimeC3(BaseRuntime):
    """Precise-exit rotor: normal/precise pulses with 2 s holdover."""

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
        track_transit: TrackTransitRegistry | None = None,
        max_piece_count: int = DEFAULT_MAX_PIECE_COUNT,
        exit_zone_near_arc_rad: float = DEFAULT_EXIT_ZONE_NEAR_ARC_RAD,
        approach_zone_near_arc_rad: float = DEFAULT_APPROACH_NEAR_ARC_RAD,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
        wiggle_stall_ms: int = DEFAULT_WIGGLE_STALL_MS,
        wiggle_cooldown_ms: int = DEFAULT_WIGGLE_COOLDOWN_MS,
        holdover_ms: int = DEFAULT_HOLDOVER_MS,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        exit_handoff_min_interval_s: float = DEFAULT_EXIT_HANDOFF_MIN_INTERVAL_S,
        handoff_retry_escalate_after: int = DEFAULT_HANDOFF_RETRY_ESCALATE_AFTER,
        handoff_retry_max_pulses: int = DEFAULT_HANDOFF_RETRY_MAX_PULSES,
        feed_id: str = "c3_feed",
        state_observer: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(
            "c3", feed_id=feed_id, logger=logger, hw_worker=hw_worker,
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
        self._track_transit = track_transit
        self._max_piece_count = max(1, int(max_piece_count))
        self._exit_near_arc = float(exit_zone_near_arc_rad)
        self._approach_near_arc = max(
            float(exit_zone_near_arc_rad),
            float(approach_zone_near_arc_rad),
        )
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._wiggle_stall_s = float(wiggle_stall_ms) / 1000.0
        self._wiggle_cooldown_s = float(wiggle_cooldown_ms) / 1000.0
        self._holdover_s = float(holdover_ms) / 1000.0
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._exit_handoff_min_interval_s = max(
            0.0,
            float(exit_handoff_min_interval_s),
        )
        self._handoff_retry_escalate_after = max(
            1,
            int(handoff_retry_escalate_after),
        )
        self._handoff_retry_max_pulses = max(1, int(handoff_retry_max_pulses))
        # See ``_dispatch_handoff_retry_pulse``: after this many failed
        # precision retries on the same track, switch to a NORMAL-mode
        # pulse to dislodge a piece that is likely stuck on the ring
        # (rubber, tangle).
        self._stuck_retry_threshold: int = 5
        self._book = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._next_exit_handoff_at: float = 0.0
        self._piece_count: int = 0
        self._admission_piece_count: int = 0
        self._visible_track_count: int = 0
        self._pending_track_count: int = 0
        self._pending_downstream_claims: dict[int, float] = {}
        self._pending_downstream_claim_retries: dict[int, int] = {}
        # Software escapement that C3 *exposes* to its upstream (C2). C2
        # asks "is C3's drop zone clear so I can push another piece?"
        # before each exit pulse. Mirrors the same lease pattern that
        # C4 already exposes to C3, but lighter: C3 has no PieceTrackBank,
        # so the lease check just inspects the latest visible action-track
        # angles. Pending leases are kept here with a TTL so a C2 pulse
        # that fails to deliver does not orphan the slot.
        self._latest_visible_angles_rad: list[float] = []
        self._upstream_pending_leases: dict[str, float] = {}
        self._upstream_lease_arc_center_rad: float = math.radians(180.0)
        self._upstream_lease_min_spacing_rad: float = math.radians(60.0)
        # Software escapement to C4. Set at bootstrap via
        # ``set_landing_lease_port``. When present, every C3 exit pulse
        # is gated through ``request_lease`` — no lease, no pulse. Live
        # lease ids by track global_id so a retry pulse for the same
        # track does not request a second lease while the first is
        # still in flight.
        self._landing_lease_port: "LandingLeasePort | None" = None
        self._active_lease_by_track: dict[int, str] = {}
        # Configurable knobs for the escapement. ``min_spacing_deg`` is
        # what the doc calls S_min — distance the new piece must be from
        # every existing C4 piece's predicted angle at arrival time.
        # ``transit_estimate_s`` is how long C3 -> C4 takes physically.
        self._lease_min_spacing_deg: float = 30.0
        self._lease_transit_estimate_s: float = 0.6
        self._lease_ttl_s: float = 1.5
        self._arrival_diagnostics_armed: bool = False
        self._purge_mode: bool = False
        self._sample_transport_step_deg: float | None = None
        self._sample_transport_max_speed: int | None = None
        self._sample_transport_acceleration: int | None = None
        self._transport_velocity = TransportVelocityObserver(
            channel="c3",
            exit_angle_deg=0.0,
            target_rpm=DEFAULT_TRANSPORT_TARGET_RPM,
        )
        self._handoff_diagnostics = HandoffDiagnostics(
            runtime_id=self.runtime_id,
            feed_id=self.feed_id,
            logger=self._logger,
        )

    # Expose mode enum for tests / callers without re-importing.
    PulseMode = _PulseMode

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        """Whether C2 may push another piece downstream.

        Mirrors ``RuntimeC2.available_slots``: the cap is the only
        backpressure surface that tells C2 to stop pushing into a C3
        ring that the tracker can no longer keep up with. Removing this
        gate caused live overflow — C3 visibly carried 25+ pieces in
        clumps that the perception tracker could not separate, which
        made every downstream singulation worse, not better. Keep the
        gate; the actual fix for the false 'downstream_full' symptom is
        further downstream in C4's admission strategy.
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
            "seen_global_ids": len(self._book.seen_global_ids),
            "exit_stall_active": self._book.exit_stall_since is not None,
            "holdover_active": self.in_holdover(time.monotonic()),
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
            "exit_stall_active": self._book.exit_stall_since is not None,
            "holdover_active": self.in_holdover(ts),
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
            # Snapshot for the upstream landing-lease port.
            self._latest_visible_angles_rad = [
                float(t.angle_rad)
                for t in visible_tracks
                if t.angle_rad is not None
            ]
            self._piece_count = len(action_tracks)
            self._admission_piece_count = len(action_tracks)
            self._transport_velocity.update(action_tracks, now_mono=now_mono)
            if not self._purge_mode:
                self._credit_new_arrivals(action_tracks, now_mono)
            exit_track = self._pick_exit_track(visible_tracks)
            if self._hw.busy():
                self._set_state("pulsing", blocked_reason="hw_busy")
                return
            if now_mono < self._next_pulse_at:
                self._set_state("pulsing", blocked_reason="cooldown")
                return
            if self._purge_mode:
                self._dispatch_purge_pulse(now_mono)
                return
            approach_track = self._pick_approach_track(visible_tracks)
            if exit_track is not None and self._has_pending_downstream_claim(
                exit_track, now_mono
            ):
                if now_mono < self._next_exit_handoff_at:
                    self._book.exit_stall_since = None
                    self._set_state(
                        "handoff_wait",
                        blocked_reason="awaiting_downstream_arrival",
                    )
                else:
                    self._dispatch_handoff_retry_pulse(exit_track, now_mono)
                return
            if (
                now_mono < self._next_exit_handoff_at
                and (exit_track is not None or approach_track is not None)
            ):
                self._book.exit_stall_since = None
                self._set_state("handoff_spacing", blocked_reason="exit_spacing")
                return
            if inbox.capacity_downstream <= 0:
                self._book.exit_stall_since = None
                self._set_state("idle", blocked_reason="downstream_full")
                return
            if not visible_tracks:
                self._book.exit_stall_since = None
                self._set_state("idle")
                return
            mode = self._resolve_mode(exit_track, approach_track, now_mono)
            target_track = exit_track or approach_track or visible_tracks[0]
            # Only pieces inside the commit zone (exit_near_arc) are
            # allowed to claim a downstream slot. Tracks in the wider
            # approach zone get slow pulses too, but don't grab c3_to_c4
            # capacity until they actually reach the drop point.
            self._dispatch_pulse(
                target_track,
                mode,
                now_mono,
                commit_to_downstream=exit_track is not None,
            )
        finally:
            self._tick_end(start)

    def landing_lease_port(self) -> LandingLeasePort:
        """Expose this C3's drop-zone gate to the upstream C2.

        Wired at bootstrap: ``c2.set_landing_lease_port(c3.landing_lease_port())``.
        """
        return _C3LandingLeasePort(self)

    def _upstream_lease_drop_zone_clear(
        self, *, min_spacing_rad: float, now_mono: float
    ) -> bool:
        """Refuse leases when a visible track sits inside the drop arc."""
        # Sweep expired leases first so a failed C2 pulse cannot orphan
        # a slot indefinitely.
        expired = [
            lease_id
            for lease_id, expires_at in self._upstream_pending_leases.items()
            if expires_at <= now_mono
        ]
        for lease_id in expired:
            self._upstream_pending_leases.pop(lease_id, None)
        center = self._upstream_lease_arc_center_rad
        spacing = max(min_spacing_rad, self._upstream_lease_min_spacing_rad)
        for ang in self._latest_visible_angles_rad:
            if abs(_wrap_rad(float(ang) - center)) < spacing:
                return False
        return len(self._upstream_pending_leases) == 0

    def _grant_upstream_lease(
        self, *, lease_ttl_s: float, now_mono: float
    ) -> str:
        import uuid as _uuid

        lease_id = _uuid.uuid4().hex[:12]
        self._upstream_pending_leases[lease_id] = float(now_mono) + float(lease_ttl_s)
        return lease_id

    def _consume_upstream_lease(self, lease_id: str) -> None:
        self._upstream_pending_leases.pop(lease_id, None)

    def set_landing_lease_port(self, port: LandingLeasePort | None) -> None:
        """Bind the downstream's landing-lease gate.

        ``None`` disables the escapement and falls back to the legacy
        slot-based gate (only used in tests that do not exercise the
        port path)."""
        self._landing_lease_port = port

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # C4 confirms it accepted the piece — release C3 slot upstream.
        self._upstream_slot.release()

    def sample_transport_port(self) -> "_C3SampleTransportPort":
        return _C3SampleTransportPort(self)

    # ------------------------------------------------------------------
    # Helpers for tests

    def in_holdover(self, now_mono: float) -> bool:
        if self._book.last_precise_at is None:
            return False
        return (now_mono - self._book.last_precise_at) < self._holdover_s

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
        seen = self._book.seen_global_ids
        arrivals: list[dict[str, Any]] = []
        for t in tracks:
            if t.global_id is None:
                continue
            if t.global_id in seen:
                continue
            seen.add(t.global_id)
            arrivals.append(self._track_diagnostics(t))
            # A new confirmed piece entered C3's ring — release upstream slot.
            self._upstream_slot.release()
        if arrivals and self._arrival_diagnostics_armed:
            self._record_arrival_burst(arrivals, now_mono)
        elif arrivals:
            self._arrival_diagnostics_armed = True

    def _pick_exit_track(self, tracks: list[Track]) -> Track | None:
        # Commit zone: stable non-ghost tracks within exit_near_arc (~20°).
        # ``confirmed_real`` is still preferred evidence, but no longer the
        # only way a reliable detector track can move downstream.
        return self._closest_actionable_within(tracks, self._exit_near_arc)

    def _pick_approach_track(self, tracks: list[Track]) -> Track | None:
        # Deceleration zone: stable non-ghost tracks within approach_near_arc
        # (~60°) but not yet in the commit zone. Drives precise pulses
        # without grabbing a downstream slot — gives a piece a gentle
        # approach instead of slamming it off the ring at normal-pulse
        # velocity.
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

    def _resolve_mode(
        self,
        exit_track: Track | None,
        approach_track: Track | None,
        now_mono: float,
    ) -> _PulseMode:
        # PRECISE in the approach + exit arcs (gentle hand-off into C4),
        # NORMAL outside so material reaches the exit zone quickly. A
        # holdover window keeps the gear in PRECISE for ~holdover_s after
        # the last commit so a piece arriving right behind it does not
        # eat one normal pulse before the zone gating engages.
        if exit_track is not None:
            self._book.last_precise_at = now_mono
            return _PulseMode.PRECISE
        if approach_track is not None:
            return _PulseMode.PRECISE
        if self.in_holdover(now_mono):
            return _PulseMode.PRECISE
        if self._piece_count >= 2:
            return _PulseMode.PRECISE
        return _PulseMode.NORMAL

    def _dispatch_pulse(
        self,
        track: Track,
        mode: _PulseMode,
        now_mono: float,
        *,
        commit_to_downstream: bool,
        repeat_count: int = 1,
        source: str | None = None,
    ) -> None:
        repeat_count = max(1, int(repeat_count))
        # Only pieces inside the commit zone (passed in as
        # ``commit_to_downstream=True``) reserve a c3_to_c4 slot. Precise
        # approach pulses and normal pulses just rotate the ring.
        claim = None
        if commit_to_downstream:
            claim_key = (
                int(track.global_id)
                if isinstance(track.global_id, int)
                else None
            )
            if (
                claim_key is not None
                and self._pending_downstream_claims.get(claim_key, 0.0) > now_mono
            ):
                self._set_state(
                    "handoff_wait",
                    blocked_reason="awaiting_downstream_arrival",
                )
                return
            else:
                # Software escapement: ask the downstream's landing
                # lease port whether the C4 landing arc will be clear
                # when this piece arrives. No lease, no pulse — keep the
                # piece on C3 until separation actually exists. Replaces
                # the old time-based slot.try_claim gate, which fired on
                # an empty arc just because nothing else had claimed it
                # in the last 3 s.
                if (
                    self._landing_lease_port is not None
                    and claim_key is not None
                ):
                    lease_id = self._landing_lease_port.request_lease(
                        predicted_arrival_in_s=self._lease_transit_estimate_s,
                        min_spacing_deg=self._lease_min_spacing_deg,
                        now_mono=now_mono,
                        track_global_id=claim_key,
                    )
                    if lease_id is None:
                        self._set_state(
                            "pulsing", blocked_reason="downstream_full"
                        )
                        return
                    self._active_lease_by_track[claim_key] = lease_id
                claim = self._downstream_slot.try_claim(
                    now_mono=now_mono,
                    hold_time_s=DEFAULT_DOWNSTREAM_CLAIM_HOLD_S,
                )
                if not claim:
                    self._set_state("pulsing", blocked_reason="downstream_full")
                    return
                if claim_key is not None:
                    self._pending_downstream_claims[claim_key] = (
                        now_mono + DEFAULT_DOWNSTREAM_CLAIM_HOLD_S
                    )
                    self._pending_downstream_claim_retries[claim_key] = 0
                self._next_exit_handoff_at = (
                    now_mono + self._exit_handoff_min_interval_s
                )
        else:
            claim_key = None
        timing = self._ejection.timing_for(
            {"mode": mode.value, "track_id": track.track_id}
        )

        mode_for_worker = mode
        commits_slot = claim is True
        profile_name = PROFILE_GENTLE if mode is _PulseMode.PRECISE else PROFILE_TRANSPORT
        move_source = source or f"c3_pulse_{mode_for_worker.value}"
        move_context = self._record_handoff_move(
            now_mono=now_mono,
            source=move_source,
            mode=mode_for_worker.value,
            repeat_count=repeat_count,
            commit_to_downstream=commits_slot,
            track=track,
        )

        def _run_pulse() -> None:
            ok = False
            completed_count = 0
            try:
                ok = True
                for _ in range(repeat_count):
                    if not self._call_pulse_command(
                        mode_for_worker,
                        timing.pulse_ms,
                        profile_name,
                    ):
                        ok = False
                        break
                    completed_count += 1
            except Exception:
                ok = False
                self._logger.exception("RuntimeC3: pulse command raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source=move_source,
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms * repeat_count,
                    extra={
                        "mode": mode_for_worker.value,
                        "repeat_count": repeat_count,
                        "completed_count": completed_count,
                        "commit_to_downstream": bool(commits_slot),
                        "piece_count": int(self._piece_count),
                        "visible_track_count": int(self._visible_track_count),
                        "track_global_id": move_context.get("track_global_id"),
                        "track_angle_deg": move_context.get("track_angle_deg"),
                    },
                )
                if ok and commits_slot:
                    self._publish_transit_candidate(track, now_mono)
            if not ok and commits_slot:
                self._downstream_slot.release()
                if claim_key is not None:
                    self._pending_downstream_claims.pop(claim_key, None)
                    self._pending_downstream_claim_retries.pop(claim_key, None)

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        label = "c3_pulse_precise" if mode is _PulseMode.PRECISE else "c3_pulse_normal"
        enqueued = self._hw.enqueue(_run_pulse, label=label)
        if not enqueued:
            if commits_slot:
                self._downstream_slot.release()
                if claim_key is not None:
                    self._pending_downstream_claims.pop(claim_key, None)
                    self._pending_downstream_claim_retries.pop(claim_key, None)
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._publish_rotation_window(
            (timing.pulse_ms * repeat_count) / 1000.0,
            now_mono,
        )
        self._set_state(f"pulsing_{mode.value}")

    def _dispatch_handoff_retry_pulse(self, track: Track, now_mono: float) -> None:
        self._next_exit_handoff_at = now_mono + self._exit_handoff_min_interval_s
        self._book.exit_stall_since = None
        retry_count = self._bump_downstream_retry_count(track)
        repeat_count = self._handoff_retry_repeat_count(retry_count)
        # Stuck-piece escalation: a piece that has not reached the
        # downstream after several precision retries is most likely
        # stuck on the ring (rubber tire, tangled axle). Switch the
        # pulse mode to NORMAL — bigger step at full transport speed —
        # to dislodge it. Threshold default 5 retries, lab-tunable via
        # ``stuck_retry_threshold``.
        if retry_count >= self._stuck_retry_threshold:
            self._logger.warning(
                "RuntimeC3: track gid=%s appears stuck after %d retries — "
                "firing aggressive NORMAL nudge",
                int(track.global_id) if track.global_id is not None else -1,
                retry_count,
            )
            self._dispatch_pulse(
                track,
                _PulseMode.NORMAL,
                now_mono,
                commit_to_downstream=False,
                repeat_count=1,
                source="c3_stuck_recovery_pulse",
            )
            return
        self._dispatch_pulse(
            track,
            _PulseMode.PRECISE,
            now_mono,
            commit_to_downstream=False,
            repeat_count=repeat_count,
            source="c3_handoff_retry_pulse",
        )

    def _dispatch_sample_transport_pulse(self, now_mono: float) -> bool:
        """Rotate C3 without admission or downstream slot gating."""
        if self._hw.busy() or self._hw.pending() > 0:
            self._set_state("sample_transport", blocked_reason="hw_busy")
            return False
        mode = _PulseMode.PRECISE
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
                        self._call_pulse_command(
                            mode,
                            timing.pulse_ms,
                            PROFILE_CONTINUOUS,
                        )
                    )
            except Exception:
                self._logger.exception("RuntimeC3: sample transport pulse raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source="c3_sample_transport",
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms,
                    extra={"mode": mode.value, "sample_transport": True},
                )

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c3_sample_transport")
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
        """Pulse the ring without gating on downstream capacity.

        Used during C3 purge: rotate so pieces fall through the C3->C4
        transition even if C4 is still draining. Uses PRECISE pulse so
        pieces commit off the ring cleanly; does not claim a downstream
        slot since we're not handing pieces to C4 for tracking.
        """
        mode = _PulseMode.PRECISE
        timing = self._ejection.timing_for({"purge": True, "mode": mode.value})

        def _run_pulse() -> None:
            ok = False
            try:
                ok = self._call_pulse_command(
                    mode,
                    timing.pulse_ms,
                    PROFILE_PURGE,
                )
            except Exception:
                self._logger.exception("RuntimeC3: purge pulse command raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source="c3_purge_pulse",
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms,
                    extra={"mode": mode.value},
                )

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c3_purge_pulse")
        if not enqueued:
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._publish_rotation_window(timing.pulse_ms / 1000.0, now_mono)
        self._set_state("pulsing", blocked_reason="purge")

    def _publish_rotation_window(self, duration_s: float, now_mono: float) -> None:
        # Mirror of RuntimeC2._publish_rotation_window — tells the perception
        # tracker the C3 ring is rotating around now, so the ghost-gating
        # tracker counts the next frames as during-rotation evidence.
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
                        "source": "c3_pulse",
                    },
                    source=self.runtime_id,
                    ts_mono=float(now_mono),
                )
            )
        except Exception:
            self._logger.exception("RuntimeC3: rotation-window publish failed")

    def _publish_transit_candidate(self, track: Track, now_mono: float) -> None:
        registry = self._track_transit
        if registry is None or track.global_id is None:
            return
        angle_deg = (
            math.degrees(float(track.angle_rad))
            if isinstance(track.angle_rad, (int, float))
            else None
        )
        registry.begin(
            source_runtime=self.runtime_id,
            source_feed=self.feed_id,
            source_global_id=int(track.global_id),
            target_runtime="c4",
            now_mono=now_mono,
            ttl_s=4.0,
            piece_uuid=track.piece_uuid,
            source_angle_deg=angle_deg,
            source_radius_px=track.radius_px,
            relation="cross_channel",
            payload={
                "handoff": "c3_to_c4",
                "source_track_id": track.track_id,
                "source_piece_uuid": track.piece_uuid,
                "source_score": float(track.score),
            },
            source_embedding=track.appearance_embedding,
        )

    def purge_port(self) -> PurgePort:
        return _C3PurgePort(self)

    def _reset_bookkeeping(self) -> None:
        self._book = _PieceBookkeeping(seen_global_ids=set())
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
            self._logger.exception("RuntimeC3: handoff-burst publish failed")

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
            self._book.exit_stall_since = None
            return False
        if self._book.exit_stall_since is None:
            self._book.exit_stall_since = now_mono
            return False
        stall = now_mono - self._book.exit_stall_since
        if stall < self._wiggle_stall_s:
            return False
        if now_mono < self._book.next_wiggle_at:
            return False
        if self._hw.busy():
            return False

        def _run_wiggle() -> None:
            try:
                self._wiggle_command()
            except Exception:
                self._logger.exception("RuntimeC3: wiggle command raised")

        enqueued = self._hw.enqueue(_run_wiggle, label="c3_exit_wiggle")
        if enqueued:
            self._book.next_wiggle_at = now_mono + self._wiggle_cooldown_s
            self._set_state("exit_wiggle")
            return True
        return False

    def _call_pulse_command(
        self,
        mode: _PulseMode,
        pulse_ms: float,
        profile_name: str,
    ) -> bool:
        try:
            return bool(self._pulse_command(mode, pulse_ms, profile_name))
        except TypeError:
            return bool(self._pulse_command(mode, pulse_ms))


def _wrap_rad(angle: float) -> float:
    a = (angle + math.pi) % (2.0 * math.pi) - math.pi
    return a


class _C3PurgePort:
    """PurgePort binding for RuntimeC3.

    Same shape as C2's port — arm flips purge mode, tick starts pulsing in
    PRECISE mode regardless of downstream capacity so pieces fall through
    the C3->C4 transition while C4 is still draining.
    """

    key = "c3"

    def __init__(self, runtime: RuntimeC3) -> None:
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


class _C3SampleTransportPort:
    key = "c3"

    def __init__(self, runtime: RuntimeC3) -> None:
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


class _C3LandingLeasePort:
    """LandingLeasePort exposed by C3 to the upstream C2.

    Same contract as ``_C4LandingLeasePort`` but lighter — C3 has no
    PieceTrackBank, so the spacing check inspects visible action-track
    angles directly. A lease is granted iff no visible track sits
    within ``min_spacing_deg`` of C3's drop-zone arc center AND no
    other lease is currently held.
    """

    key = "c3"

    def __init__(self, runtime: RuntimeC3) -> None:
        self._runtime = runtime

    def request_lease(
        self,
        *,
        predicted_arrival_in_s: float,
        min_spacing_deg: float,
        now_mono: float,
        track_global_id: int | None = None,
    ) -> str | None:
        spacing = math.radians(max(0.0, float(min_spacing_deg)))
        if not self._runtime._upstream_lease_drop_zone_clear(
            min_spacing_rad=spacing, now_mono=now_mono
        ):
            return None
        return self._runtime._grant_upstream_lease(
            lease_ttl_s=1.5, now_mono=now_mono
        )

    def consume_lease(self, lease_id: str) -> None:
        self._runtime._consume_upstream_lease(lease_id)


__all__ = ["RuntimeC3"]
