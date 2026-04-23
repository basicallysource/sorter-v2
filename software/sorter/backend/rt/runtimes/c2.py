"""RuntimeC2 — separation seed shuttle.

Reads ``TrackBatch`` from ``c2_feed`` (PolarTracker output), gates forward
pulses on the C2->C3 capacity slot, and triggers an exit-zone wiggle when a
piece is stuck at the exit but downstream is closed. Port of:

* ``subsystems/channels/c2_separation.py`` — pulse dispatch + exit-wiggle
* ``subsystems/feeder/analysis.py``        — track-to-action mapping

The runtime keeps the AdmissionStrategy hook from §2.11 so the interface
matches Phase 4/5 runtimes; for C2 the default ``AlwaysAdmit`` is fine.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Callable

from rt.contracts.admission import AdmissionStrategy
from rt.contracts.ejection import EjectionTimingStrategy
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot

from ._strategies import AlwaysAdmit, ConstantPulseEjection
from .base import BaseRuntime, HwWorker


# Exit-zone wiggle defaults (output-shaft degrees). Mirror legacy
# ``base.EXIT_WIGGLE_*`` constants.
DEFAULT_EXIT_ZONE_NEAR_ARC_RAD = math.radians(30.0)
DEFAULT_INTAKE_ZONE_NEAR_ARC_RAD = math.radians(30.0)
DEFAULT_MAX_RING_COUNT = 5
DEFAULT_PULSE_COOLDOWN_S = 0.12
DEFAULT_WIGGLE_STALL_MS = 600
DEFAULT_WIGGLE_COOLDOWN_MS = 1200
DEFAULT_TRACK_STALE_S = 0.5


@dataclass(slots=True)
class _PieceBookkeeping:
    # Tracks we've already credited as 'arrived' (so we can release the
    # upstream slot exactly once per piece).
    seen_global_ids: set[int]
    exit_stall_since: float | None = None
    next_wiggle_at: float = 0.0


class RuntimeC2(BaseRuntime):
    """Separation rotor: pulses pieces from the C2 ring to C3."""

    def __init__(
        self,
        *,
        upstream_slot: CapacitySlot,
        downstream_slot: CapacitySlot,
        pulse_command: Callable[[float], bool],
        wiggle_command: Callable[[], bool],
        admission: AdmissionStrategy | None = None,
        ejection_timing: EjectionTimingStrategy | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        max_ring_count: int = DEFAULT_MAX_RING_COUNT,
        exit_zone_near_arc_rad: float = DEFAULT_EXIT_ZONE_NEAR_ARC_RAD,
        intake_zone_near_arc_rad: float = DEFAULT_INTAKE_ZONE_NEAR_ARC_RAD,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
        wiggle_stall_ms: int = DEFAULT_WIGGLE_STALL_MS,
        wiggle_cooldown_ms: int = DEFAULT_WIGGLE_COOLDOWN_MS,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        feed_id: str = "c2_feed",
    ) -> None:
        super().__init__("c2", feed_id=feed_id, logger=logger, hw_worker=hw_worker)
        self._upstream_slot = upstream_slot
        self._downstream_slot = downstream_slot
        self._pulse_command = pulse_command
        self._wiggle_command = wiggle_command
        self._admission = admission or AlwaysAdmit()
        self._ejection = ejection_timing or ConstantPulseEjection()
        self._max_ring_count = max(1, int(max_ring_count))
        self._exit_near_arc = float(exit_zone_near_arc_rad)
        self._intake_near_arc = float(intake_zone_near_arc_rad)
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._wiggle_stall_s = float(wiggle_stall_ms) / 1000.0
        self._wiggle_cooldown_s = float(wiggle_cooldown_ms) / 1000.0
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._bookkeeping = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._ring_count: int = 0

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        if self._ring_count >= self._max_ring_count:
            return 0
        # Delegate to AdmissionStrategy so Phase 4+ can plug a real gate in.
        decision = self._admission.can_admit(
            inbound_piece_hint={},
            runtime_state={
                "ring_count": self._ring_count,
                "max_ring_count": self._max_ring_count,
            },
        )
        return 1 if decision.allowed else 0

    def debug_snapshot(self) -> dict[str, Any]:
        snap = super().debug_snapshot()
        snap.update({
            "ring_count": int(self._ring_count),
            "max_ring_count": int(self._max_ring_count),
            "available_slots": int(self.available_slots()),
            "upstream_taken": int(self._upstream_slot.taken()),
            "downstream_taken": int(self._downstream_slot.taken()),
            "seen_global_ids": len(self._bookkeeping.seen_global_ids),
            "exit_stall_active": self._bookkeeping.exit_stall_since is not None,
        })
        return snap

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            tracks = self._fresh_tracks(inbox.tracks)
            self._credit_new_arrivals(tracks, now_mono)
            self._ring_count = len(tracks)
            exit_track = self._pick_exit_track(tracks)
            if self._hw.busy():
                self._set_state("pulsing", blocked_reason="hw_busy")
                return
            if now_mono < self._next_pulse_at:
                self._set_state("pulsing", blocked_reason="cooldown")
                return
            if inbox.capacity_downstream <= 0:
                wiggled = self._maybe_wiggle(exit_track, now_mono)
                if not wiggled:
                    self._set_state("idle", blocked_reason="downstream_full")
                return
            if exit_track is None:
                # Nothing at the exit, nothing to pulse.
                self._bookkeeping.exit_stall_since = None
                self._set_state("idle")
                return
            self._dispatch_exit_pulse(exit_track, now_mono)
        finally:
            self._tick_end(start)

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # C3 confirms it accepted a piece from us — release the upstream
        # slot so C1 sees headroom.
        self._upstream_slot.release()

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
        for t in tracks:
            if t.global_id is None:
                continue
            if t.global_id in seen:
                continue
            seen.add(t.global_id)
            # A new confirmed piece entered C2's ring — release the upstream
            # slot reservation so C1 sees headroom.
            self._upstream_slot.release()

    def _pick_exit_track(self, tracks: list[Track]) -> Track | None:
        # Prefer the track closest to angle 0 (exit) — proxy for 'at exit'.
        candidates = [t for t in tracks if t.angle_rad is not None]
        if not candidates:
            return None
        candidates.sort(key=lambda t: abs(_wrap_rad(t.angle_rad or 0.0)))
        head = candidates[0]
        if abs(_wrap_rad(head.angle_rad or 0.0)) > self._exit_near_arc:
            return None
        return head

    def _dispatch_exit_pulse(self, track: Track, now_mono: float) -> None:
        claimed = self._downstream_slot.try_claim()
        if not claimed:
            self._set_state("idle", blocked_reason="downstream_full")
            return
        timing = self._ejection.timing_for({"track_id": track.track_id})
        self._bookkeeping.exit_stall_since = None

        def _run_pulse() -> None:
            try:
                ok = self._pulse_command(timing.pulse_ms)
            except Exception:
                self._logger.exception("RuntimeC2: pulse command raised")
                ok = False
            if not ok:
                self._downstream_slot.release()

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c2_pulse")
        if not enqueued:
            self._downstream_slot.release()
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._set_state("pulsing")

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


__all__ = ["RuntimeC2"]
