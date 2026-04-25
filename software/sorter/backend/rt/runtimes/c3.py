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
from rt.contracts.purge import PurgeCounts, PurgePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.topics import PERCEPTION_ROTATION
from rt.hardware.motion_profiles import (
    PROFILE_CONTINUOUS,
    PROFILE_GENTLE,
    PROFILE_PURGE,
    PROFILE_TRANSPORT,
)
from rt.perception.track_policy import action_track, is_visible_track
from rt.services.track_transit import TrackTransitRegistry
from rt.services.transport_velocity import TransportVelocityObserver

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
# Small queue of separated pieces on C3: as soon as a new piece lands
# in the intake zone C3 nudges it away so the next C2 drop has clear
# space; the queue drains piece by piece via the normal approach/exit
# pulses. 1 forced C2 to wait for C3 to fully clear before delivering
# the next piece, making the whole pipeline serial.
DEFAULT_MAX_PIECE_COUNT = 3
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
        self._book = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._next_exit_handoff_at: float = 0.0
        self._piece_count: int = 0
        self._admission_piece_count: int = 0
        self._visible_track_count: int = 0
        self._pending_track_count: int = 0
        self._pending_downstream_claims: dict[int, float] = {}
        self._purge_mode: bool = False
        self._sample_transport_step_deg: float | None = None
        self._sample_transport_max_speed: int | None = None
        self._sample_transport_acceleration: int | None = None
        self._transport_velocity = TransportVelocityObserver(
            channel="c3",
            exit_angle_deg=0.0,
            target_rpm=DEFAULT_TRANSPORT_TARGET_RPM,
        )

    # Expose mode enum for tests / callers without re-importing.
    PulseMode = _PulseMode

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        if self._purge_mode:
            return 0
        if self._admission_piece_count >= self._max_piece_count:
            return 0
        decision = self._admission.can_admit(
            inbound_piece_hint={},
            runtime_state={
                "piece_count": self._admission_piece_count,
                "max_piece_count": self._max_piece_count,
            },
        )
        return 1 if decision.allowed else 0

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
            "seen_global_ids": len(self._book.seen_global_ids),
            "exit_stall_active": self._book.exit_stall_since is not None,
            "holdover_active": self.in_holdover(time.monotonic()),
            "exit_handoff_spacing_s": max(0.0, self._next_exit_handoff_at - time.monotonic()),
            "exit_handoff_min_interval_s": float(self._exit_handoff_min_interval_s),
            "transport_velocity": self._transport_velocity.snapshot.as_dict(),
        })
        return snap

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
                self._credit_new_arrivals(action_tracks)
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

    def _credit_new_arrivals(self, tracks: list[Track]) -> None:
        seen = self._book.seen_global_ids
        for t in tracks:
            if t.global_id is None:
                continue
            if t.global_id in seen:
                continue
            seen.add(t.global_id)
            # A new confirmed piece entered C3's ring — release upstream slot.
            self._upstream_slot.release()

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
    ) -> None:
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

        def _run_pulse() -> None:
            ok = False
            try:
                ok = self._call_pulse_command(
                    mode_for_worker,
                    timing.pulse_ms,
                    profile_name,
                )
            except Exception:
                self._logger.exception("RuntimeC3: pulse command raised")
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=self.feed_id,
                    source=f"c3_pulse_{mode_for_worker.value}",
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms,
                    extra={"mode": mode_for_worker.value},
                )
                if ok and commits_slot:
                    self._publish_transit_candidate(track, now_mono)
            if not ok and commits_slot:
                self._downstream_slot.release()
                if claim_key is not None:
                    self._pending_downstream_claims.pop(claim_key, None)

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        label = "c3_pulse_precise" if mode is _PulseMode.PRECISE else "c3_pulse_normal"
        enqueued = self._hw.enqueue(_run_pulse, label=label)
        if not enqueued:
            if commits_slot:
                self._downstream_slot.release()
                if claim_key is not None:
                    self._pending_downstream_claims.pop(claim_key, None)
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._publish_rotation_window(timing.pulse_ms / 1000.0, now_mono)
        self._set_state(f"pulsing_{mode.value}")

    def _dispatch_handoff_retry_pulse(self, track: Track, now_mono: float) -> None:
        self._next_exit_handoff_at = now_mono + self._exit_handoff_min_interval_s
        self._book.exit_stall_since = None
        self._dispatch_pulse(
            track,
            _PulseMode.PRECISE,
            now_mono,
            commit_to_downstream=False,
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
        self._next_pulse_at = 0.0
        self._next_exit_handoff_at = 0.0

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


__all__ = ["RuntimeC3"]
