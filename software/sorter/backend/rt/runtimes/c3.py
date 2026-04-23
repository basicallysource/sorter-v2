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
from rt.contracts.purge import PurgeCounts, PurgePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot

from ._strategies import AlwaysAdmit, ConstantPulseEjection
from .base import BaseRuntime, HwWorker


DEFAULT_EXIT_ZONE_NEAR_ARC_RAD = math.radians(20.0)
DEFAULT_MAX_RING_COUNT = 1
DEFAULT_PULSE_COOLDOWN_S = 0.12
DEFAULT_WIGGLE_STALL_MS = 600
DEFAULT_WIGGLE_COOLDOWN_MS = 1200
DEFAULT_HOLDOVER_MS = 2000  # Mirror legacy CH3_PRECISE_HOLDOVER_MS.
DEFAULT_TRACK_STALE_S = 0.5


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
        pulse_command: Callable[[_PulseMode, float], bool],
        wiggle_command: Callable[[], bool],
        admission: AdmissionStrategy | None = None,
        ejection_timing: EjectionTimingStrategy | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        max_ring_count: int = DEFAULT_MAX_RING_COUNT,
        exit_zone_near_arc_rad: float = DEFAULT_EXIT_ZONE_NEAR_ARC_RAD,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
        wiggle_stall_ms: int = DEFAULT_WIGGLE_STALL_MS,
        wiggle_cooldown_ms: int = DEFAULT_WIGGLE_COOLDOWN_MS,
        holdover_ms: int = DEFAULT_HOLDOVER_MS,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        feed_id: str = "c3_feed",
    ) -> None:
        super().__init__("c3", feed_id=feed_id, logger=logger, hw_worker=hw_worker)
        self._upstream_slot = upstream_slot
        self._downstream_slot = downstream_slot
        self._pulse_command = pulse_command
        self._wiggle_command = wiggle_command
        self._admission = admission or AlwaysAdmit()
        self._ejection = ejection_timing or ConstantPulseEjection()
        self._max_ring_count = max(1, int(max_ring_count))
        self._exit_near_arc = float(exit_zone_near_arc_rad)
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._wiggle_stall_s = float(wiggle_stall_ms) / 1000.0
        self._wiggle_cooldown_s = float(wiggle_cooldown_ms) / 1000.0
        self._holdover_s = float(holdover_ms) / 1000.0
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._book = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._ring_count: int = 0
        self._purge_mode: bool = False

    # Expose mode enum for tests / callers without re-importing.
    PulseMode = _PulseMode

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        if self._purge_mode:
            return 0
        if self._ring_count >= self._max_ring_count:
            return 0
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
            "seen_global_ids": len(self._book.seen_global_ids),
            "exit_stall_active": self._book.exit_stall_since is not None,
            "holdover_active": self.in_holdover(time.monotonic()),
        })
        return snap

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            tracks = self._fresh_tracks(inbox.tracks)
            if not self._purge_mode:
                self._credit_new_arrivals(tracks)
            self._ring_count = len(tracks)
            exit_track = self._pick_exit_track(tracks)
            if self._hw.busy():
                self._set_state("pulsing", blocked_reason="hw_busy")
                return
            if now_mono < self._next_pulse_at:
                self._set_state("pulsing", blocked_reason="cooldown")
                return
            if self._purge_mode:
                self._dispatch_purge_pulse(now_mono)
                return
            if inbox.capacity_downstream <= 0:
                wiggled = self._maybe_wiggle(exit_track, now_mono)
                if not wiggled:
                    self._set_state("idle", blocked_reason="downstream_full")
                return
            if not tracks:
                self._book.exit_stall_since = None
                self._set_state("idle")
                return
            mode = self._resolve_mode(exit_track, now_mono)
            target_track = exit_track if exit_track is not None else tracks[0]
            self._dispatch_pulse(target_track, mode, now_mono)
        finally:
            self._tick_end(start)

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        # C4 confirms it accepted the piece — release C3 slot upstream.
        self._upstream_slot.release()

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
        candidates = [t for t in tracks if t.angle_rad is not None]
        if not candidates:
            return None
        candidates.sort(key=lambda t: abs(_wrap_rad(t.angle_rad or 0.0)))
        head = candidates[0]
        if abs(_wrap_rad(head.angle_rad or 0.0)) > self._exit_near_arc:
            return None
        return head

    def _resolve_mode(self, exit_track: Track | None, now_mono: float) -> _PulseMode:
        if exit_track is not None:
            self._book.last_precise_at = now_mono
            return _PulseMode.PRECISE
        if self.in_holdover(now_mono):
            # Stick to precise during holdover even without a fresh precise
            # detection (reduces thrashing at the exit boundary).
            return _PulseMode.PRECISE
        return _PulseMode.NORMAL

    def _dispatch_pulse(
        self,
        track: Track,
        mode: _PulseMode,
        now_mono: float,
    ) -> None:
        # Only precise pulses commit a piece downstream; normal pulses
        # advance the ring but do not exit the channel.
        claim = None
        if mode is _PulseMode.PRECISE:
            claim = self._downstream_slot.try_claim()
            if not claim:
                self._set_state("pulsing", blocked_reason="downstream_full")
                return
        timing = self._ejection.timing_for(
            {"mode": mode.value, "track_id": track.track_id}
        )

        mode_for_worker = mode
        commits_slot = claim is True

        def _run_pulse() -> None:
            try:
                ok = self._pulse_command(mode_for_worker, timing.pulse_ms)
            except Exception:
                self._logger.exception("RuntimeC3: pulse command raised")
                ok = False
            if not ok and commits_slot:
                self._downstream_slot.release()

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        label = "c3_pulse_precise" if mode is _PulseMode.PRECISE else "c3_pulse_normal"
        enqueued = self._hw.enqueue(_run_pulse, label=label)
        if not enqueued:
            if commits_slot:
                self._downstream_slot.release()
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._set_state(f"pulsing_{mode.value}")

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
            try:
                self._pulse_command(mode, timing.pulse_ms)
            except Exception:
                self._logger.exception("RuntimeC3: purge pulse command raised")

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c3_purge_pulse")
        if not enqueued:
            self._set_state("pulsing", blocked_reason="hw_queue_full")
            return
        self._set_state("pulsing", blocked_reason="purge")

    def purge_port(self) -> PurgePort:
        return _C3PurgePort(self)

    def _reset_bookkeeping(self) -> None:
        self._book = _PieceBookkeeping(seen_global_ids=set())
        self._ring_count = 0
        self._next_pulse_at = 0.0

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
            ring_count=int(self._runtime._ring_count),
            owned_count=0,
            pending_detections=0,
        )

    def drain_step(self, now_mono: float) -> bool:
        return bool(self._runtime._purge_mode)


__all__ = ["RuntimeC3"]
