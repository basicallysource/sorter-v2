"""RuntimeC2 — separation seed shuttle.

Reads ``TrackBatch`` from ``c2_feed`` and gates forward pulses on the C2->C3
capacity slot. Port of:

* ``subsystems/channels/c2_separation.py`` — pulse dispatch
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
from rt.contracts.events import EventBus
from rt.contracts.landing_lease import LandingLeasePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track
from rt.coupling.slots import CapacitySlot
from rt.hardware.motion_profiles import (
    PROFILE_CONTINUOUS,
    PROFILE_GENTLE,
    PROFILE_TRANSPORT,
)
from rt.perception.track_policy import action_track, is_visible_track
from rt.services.transport_velocity import TransportVelocityObserver

from ._handoff_diagnostics import (
    HandoffDiagnostics,
    record_ring_arrival_burst,
    record_ring_handoff_move,
)
from ._move_events import publish_move_completed
from ._ring_ports import (
    RingPurgePort,
    RingSampleTransportPort,
    publish_ring_rotation_window,
)
from ._ring_tracks import (
    closest_actionable_within,
    fresh_ring_tracks,
    track_diagnostics,
    wrap_rad as _wrap_rad,
)
from ._strategies import AlwaysAdmit, ConstantPulseEjection
from .base import BaseRuntime, HwWorker


DEFAULT_EXIT_ZONE_NEAR_ARC_RAD = math.radians(30.0)
# Deceleration zone in front of the exit. Once a confirmed-real track is
# inside this arc but not yet in the commit zone, C2 switches to small
# precision pulses so pieces are fed gently into the C2→C3 transition
# rather than blasted through in batches.
DEFAULT_APPROACH_NEAR_ARC_RAD = math.radians(45.0)
DEFAULT_INTAKE_ZONE_NEAR_ARC_RAD = math.radians(30.0)
DEFAULT_MAX_PIECE_COUNT = 5
DEFAULT_PULSE_COOLDOWN_S = 0.12
DEFAULT_TRACK_STALE_S = 0.5
# Idle cadence for the advance pulse: when the ring carries tracks but none
# is in the exit near-arc, pulse periodically to (a) bring real pieces
# toward the exit and (b) give the ghost-gating tracker enough rotation
# windows to declare stationary phantoms.
DEFAULT_ADVANCE_INTERVAL_S = 1.2
ACTION_TRACK_MIN_HITS = 2
DEFAULT_TRANSPORT_TARGET_RPM = 1.2
DEFAULT_DOWNSTREAM_CLAIM_HOLD_S = 3.0
DEFAULT_EXIT_HANDOFF_MIN_INTERVAL_S = 0.85
DEFAULT_HANDOFF_RETRY_ESCALATE_AFTER = 2
DEFAULT_HANDOFF_RETRY_MAX_PULSES = 2
_DENSITY_CLUSTER_WINDOW_RAD = math.radians(60.0)
_DENSITY_CLOSE_SPACING_RAD = math.radians(30.0)


class _PulseMode(Enum):
    NORMAL = "normal"
    PRECISE = "precise"


@dataclass(slots=True)
class _PieceBookkeeping:
    # Tracks we've already credited as 'arrived' (so we can release the
    # upstream slot exactly once per piece).
    seen_global_ids: set[int]
    exit_stall_since: float | None = None
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
        sample_transport_command: Callable[[float, int | None, int | None], bool] | None = None,
        upstream_progress_callback: Callable[[float], None] | None = None,
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
        self._sample_transport_command = sample_transport_command
        self._upstream_progress_callback = upstream_progress_callback
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
        # See ``_dispatch_exit_retry_pulse``: after this many failed
        # precision retries on the same track, switch to a NORMAL-mode
        # pulse to dislodge a piece that is likely stuck on the ring.
        self._stuck_retry_threshold: int = 5
        self._bookkeeping = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._next_exit_handoff_at: float = 0.0
        self._piece_count: int = 0
        self._admission_piece_count: int = 0
        self._visible_track_count: int = 0
        self._pending_track_count: int = 0
        self._density_snapshot: dict[str, Any] = self._empty_density_snapshot()
        self._pending_downstream_claims: dict[int, float] = {}
        self._pending_downstream_claim_retries: dict[int, int] = {}
        # Software escapement to C3, same pattern as C3 -> C4.
        # No lease, no exit pulse — keeps C2 from dumping into a
        # C3 drop zone that already has a piece sitting in it.
        self._landing_lease_port: "LandingLeasePort | None" = None
        self._active_lease_by_track: dict[int, str] = {}
        self._lease_min_spacing_deg: float = 60.0
        self._lease_transit_estimate_s: float = 0.5
        self._lease_ttl_s: float = 1.5
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

    def capacity_debug_snapshot(self) -> dict[str, Any]:
        if self._purge_mode:
            reason = "purge"
            available = 0
        elif self._admission_piece_count >= self._max_piece_count:
            reason = "piece_cap"
            available = 0
        else:
            reason = "ok"
            available = 1
        return {
            "available": int(available),
            "reason": reason,
            "piece_count": int(self._piece_count),
            "admission_piece_count": int(self._admission_piece_count),
            "visible_track_count": int(self._visible_track_count),
            "max_piece_count": int(self._max_piece_count),
            "purge_mode": bool(self._purge_mode),
            "density": dict(self._density_snapshot),
        }

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
            "density": dict(self._density_snapshot),
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
            tracks = fresh_ring_tracks(inbox.tracks, track_stale_s=self._track_stale_s)
            visible_tracks = [t for t in tracks if is_visible_track(t)]
            action_tracks = [
                t for t in visible_tracks if action_track(t, min_hits=ACTION_TRACK_MIN_HITS)
            ]
            self._visible_track_count = len(visible_tracks)
            self._pending_track_count = max(0, self._visible_track_count - len(action_tracks))
            self._piece_count = len(action_tracks)
            self._admission_piece_count = len(action_tracks)
            self._density_snapshot = self._compute_density_snapshot(
                visible_tracks=visible_tracks,
                action_tracks=action_tracks,
            )
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
                self.purge_port().dispatch_pulse(now_mono)
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

    def set_landing_lease_port(self, port: LandingLeasePort | None) -> None:
        """Bind the downstream's (C3) landing-lease gate. ``None`` falls
        back to the legacy slot-based gate."""
        self._landing_lease_port = port

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # C3 confirms it accepted a piece from us — release the upstream
        # slot so C1 sees headroom.
        self._upstream_slot.release()

    def sample_transport_port(self) -> "RingSampleTransportPort":
        return RingSampleTransportPort(
            self,
            key="c2",
            mode=_PulseMode.NORMAL,
            pulse_method="_pulse_command",
        )

    # ------------------------------------------------------------------
    # Internals

    def _empty_density_snapshot(self) -> dict[str, Any]:
        return {
            "c2_occupancy_area_px": 0.0,
            "c2_piece_count_estimate": 0,
            "c2_clump_score": 0.0,
            "c2_free_arc_fraction": 1.0,
            "c2_exit_queue_length": 0,
            "occupancy_area_px": 0.0,
            "piece_count_estimate": 0,
            "clump_score": 0.0,
            "free_arc_fraction": 1.0,
            "exit_queue_length": 0,
            "action_piece_count": 0,
            "visible_track_count": 0,
            "pending_track_count": 0,
            "min_spacing_deg": None,
            "largest_gap_deg": 360.0,
            "max_cluster_count_60deg": 0,
            "max_bbox_area_px": 0.0,
        }

    def _compute_density_snapshot(
        self,
        *,
        visible_tracks: list[Track],
        action_tracks: list[Track],
    ) -> dict[str, Any]:
        visible_count = len(visible_tracks)
        action_count = len(action_tracks)
        angles = sorted(
            float(t.angle_rad) % (2.0 * math.pi)
            for t in visible_tracks
            if t.angle_rad is not None
        )
        bbox_areas = [self._bbox_area_px(t) for t in visible_tracks]
        occupancy_area_px = float(sum(bbox_areas))
        max_bbox_area_px = float(max(bbox_areas, default=0.0))
        exit_queue_length = sum(
            1
            for t in action_tracks
            if t.angle_rad is not None
            and abs(_wrap_rad(float(t.angle_rad))) <= self._approach_near_arc
        )

        min_spacing_rad: float | None = None
        largest_gap_rad = 2.0 * math.pi
        max_cluster_count = len(angles)
        if len(angles) >= 2:
            gaps = [
                angles[idx + 1] - angles[idx]
                for idx in range(len(angles) - 1)
            ]
            gaps.append((angles[0] + 2.0 * math.pi) - angles[-1])
            min_spacing_rad = min(gaps)
            largest_gap_rad = max(gaps)
            max_cluster_count = self._max_cluster_count(
                angles,
                window_rad=_DENSITY_CLUSTER_WINDOW_RAD,
            )
        elif len(angles) == 1:
            max_cluster_count = 1

        spacing_pressure = 0.0
        if min_spacing_rad is not None:
            spacing_pressure = max(
                0.0,
                min(1.0, 1.0 - (min_spacing_rad / _DENSITY_CLOSE_SPACING_RAD)),
            )
        cluster_pressure = 0.0
        if len(angles) >= 3:
            cluster_pressure = max(
                0.0,
                min(1.0, (max_cluster_count - 1) / max(1, len(angles) - 1)),
            )
        clump_score = max(spacing_pressure, cluster_pressure)
        free_arc_fraction = max(
            0.0,
            min(1.0, largest_gap_rad / (2.0 * math.pi)),
        )
        piece_count_estimate = max(visible_count, action_count)

        min_spacing_deg = (
            None if min_spacing_rad is None else math.degrees(min_spacing_rad)
        )
        largest_gap_deg = math.degrees(largest_gap_rad)
        snap = {
            "c2_occupancy_area_px": occupancy_area_px,
            "c2_piece_count_estimate": int(piece_count_estimate),
            "c2_clump_score": float(clump_score),
            "c2_free_arc_fraction": float(free_arc_fraction),
            "c2_exit_queue_length": int(exit_queue_length),
            "occupancy_area_px": occupancy_area_px,
            "piece_count_estimate": int(piece_count_estimate),
            "clump_score": float(clump_score),
            "free_arc_fraction": float(free_arc_fraction),
            "exit_queue_length": int(exit_queue_length),
            "action_piece_count": int(action_count),
            "visible_track_count": int(visible_count),
            "pending_track_count": int(max(0, visible_count - action_count)),
            "min_spacing_deg": min_spacing_deg,
            "largest_gap_deg": float(largest_gap_deg),
            "max_cluster_count_60deg": int(max_cluster_count),
            "max_bbox_area_px": max_bbox_area_px,
        }
        return snap

    def _max_cluster_count(self, angles: list[float], *, window_rad: float) -> int:
        if not angles:
            return 0
        extended = angles + [a + 2.0 * math.pi for a in angles]
        best = 1
        end = 0
        for start in range(len(angles)):
            end = max(end, start)
            while (
                end + 1 < start + len(angles)
                and extended[end + 1] - extended[start] <= window_rad
            ):
                end += 1
            best = max(best, end - start + 1)
        return best

    def _bbox_area_px(self, track: Track) -> float:
        try:
            x1, y1, x2, y2 = (float(v) for v in track.bbox_xyxy)
        except Exception:
            return 0.0
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def _credit_new_arrivals(self, tracks: list[Track], now_mono: float) -> None:
        seen = self._bookkeeping.seen_global_ids
        arrivals: list[dict[str, Any]] = []
        for t in tracks:
            if t.global_id is None:
                continue
            if t.global_id in seen:
                continue
            seen.add(t.global_id)
            arrivals.append(track_diagnostics(t))
            # A new confirmed piece entered C2's ring — release the upstream
            # slot reservation so C1 sees headroom.
            self._upstream_slot.release()
        if arrivals and self._arrival_diagnostics_armed:
            record_ring_arrival_burst(self, arrivals, now_mono)
        elif arrivals:
            self._arrival_diagnostics_armed = True
        if arrivals and self._upstream_progress_callback is not None:
            try:
                self._upstream_progress_callback(now_mono)
            except Exception:
                self._logger.exception(
                    "RuntimeC2: upstream progress callback raised"
                )

    def _pick_exit_track(self, tracks: list[Track]) -> Track | None:
        # Commit zone: stable tracks within ``exit_near_arc``. The detector
        # is the primary signal — rotation-window confirmation is strong
        # evidence but stable non-ghost detections may commit before it
        # catches up.
        return closest_actionable_within(
            tracks,
            self._exit_near_arc,
            min_hits=ACTION_TRACK_MIN_HITS,
        )

    def _pick_approach_track(self, tracks: list[Track]) -> Track | None:
        # Deceleration zone: stable tracks inside ``approach_near_arc`` but
        # not yet inside the commit arc. Drives small precise pulses
        # without claiming a downstream slot.
        approach = closest_actionable_within(
            tracks,
            self._approach_near_arc,
            min_hits=ACTION_TRACK_MIN_HITS,
        )
        if approach is None:
            return None
        if abs(_wrap_rad(approach.angle_rad or 0.0)) <= self._exit_near_arc:
            return None
        return approach

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
        # Software escapement: ask C3's landing-lease port whether its
        # drop zone is clear. No lease, no pulse — same pattern as the
        # C3->C4 lease. Operator observation 2026-04-25: C2 was pushing
        # pieces onto C3 even when C3 already had one parked under the
        # drop, which then cluster onto each other and break C3
        # singulation downstream.
        if self._landing_lease_port is not None and claim_key is not None:
            lease_id = self._landing_lease_port.request_lease(
                predicted_arrival_in_s=self._lease_transit_estimate_s,
                min_spacing_deg=self._lease_min_spacing_deg,
                now_mono=now_mono,
                track_global_id=claim_key,
            )
            if lease_id is None:
                self._set_state("idle", blocked_reason="lease_denied")
                return
            self._active_lease_by_track[claim_key] = lease_id
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
        # Stuck-piece escalation: same idea as C3 — after several
        # precision retries on the same track, switch to a NORMAL-mode
        # pulse. Helps when a rubber tire or tangled piece sits in C2's
        # exit zone and the precision micro-pulses are not enough to
        # carry it across the drop edge.
        if retry_count >= self._stuck_retry_threshold:
            self._logger.warning(
                "RuntimeC2: track gid=%s appears stuck after %d retries — "
                "firing aggressive NORMAL nudge",
                int(track.global_id) if track.global_id is not None else -1,
                retry_count,
            )
            self._fire_pulse(
                track=track,
                mode=_PulseMode.NORMAL,
                now_mono=now_mono,
                commit_to_downstream=False,
                source="c2_stuck_recovery_pulse",
                label="c2_stuck_recovery_pulse",
                state="stuck_recovery",
                repeat_count=1,
            )
            return
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
        move_context = record_ring_handoff_move(
            self,
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
        publish_ring_rotation_window(
            self,
            (timing.pulse_ms * repeat_count) / 1000.0,
            now_mono,
            "c2_pulse",
        )
        self._set_state(state)

    def purge_port(self) -> RingPurgePort:
        return RingPurgePort(
            self,
            key="c2",
            visible_count_attr="_visible_track_count",
            mode=_PulseMode.NORMAL,
            pulse_method="_pulse_command",
        )

    def _reset_bookkeeping(self) -> None:
        self._bookkeeping = _PieceBookkeeping(seen_global_ids=set())
        self._piece_count = 0
        self._admission_piece_count = 0
        self._visible_track_count = 0
        self._pending_track_count = 0
        self._density_snapshot = self._empty_density_snapshot()
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

__all__ = ["RuntimeC2"]
