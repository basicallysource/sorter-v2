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
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from rt.contracts.admission import AdmissionStrategy
from rt.contracts.ejection import EjectionTimingStrategy
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
        self._book = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._ring_count: int = 0

    # Expose mode enum for tests / callers without re-importing.
    PulseMode = _PulseMode

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
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

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            tracks = self._confirmed_tracks(inbox.tracks)
            self._credit_new_arrivals(tracks)
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

    def _confirmed_tracks(self, batch: TrackBatch | None) -> list[Track]:
        if batch is None:
            return []
        return [t for t in batch.tracks if t.confirmed_real]

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


__all__ = ["RuntimeC3"]
