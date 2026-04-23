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
import time
from dataclasses import dataclass
from typing import Any, Callable

from rt.contracts.admission import AdmissionStrategy
from rt.contracts.ejection import EjectionTimingStrategy
from rt.contracts.events import Event, EventBus
from rt.contracts.purge import PurgeCounts, PurgePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.topics import PERCEPTION_ROTATION

from ._strategies import AlwaysAdmit, ConstantPulseEjection
from .base import BaseRuntime, HwWorker


# Exit-zone wiggle defaults (output-shaft degrees). Mirror legacy
# ``base.EXIT_WIGGLE_*`` constants.
DEFAULT_EXIT_ZONE_NEAR_ARC_RAD = math.radians(30.0)
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
# Extra seconds on either side of a pulse window so the next few frames
# (hardware latency, frame-capture jitter) still count as "during rotation".
_ROTATION_WINDOW_PAD_S = 0.15


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
        event_bus: EventBus | None = None,
        max_piece_count: int = DEFAULT_MAX_PIECE_COUNT,
        exit_zone_near_arc_rad: float = DEFAULT_EXIT_ZONE_NEAR_ARC_RAD,
        intake_zone_near_arc_rad: float = DEFAULT_INTAKE_ZONE_NEAR_ARC_RAD,
        pulse_cooldown_s: float = DEFAULT_PULSE_COOLDOWN_S,
        wiggle_stall_ms: int = DEFAULT_WIGGLE_STALL_MS,
        wiggle_cooldown_ms: int = DEFAULT_WIGGLE_COOLDOWN_MS,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        advance_interval_s: float = DEFAULT_ADVANCE_INTERVAL_S,
        feed_id: str = "c2_feed",
    ) -> None:
        super().__init__("c2", feed_id=feed_id, logger=logger, hw_worker=hw_worker)
        self._upstream_slot = upstream_slot
        self._downstream_slot = downstream_slot
        self._pulse_command = pulse_command
        self._wiggle_command = wiggle_command
        self._admission = admission or AlwaysAdmit()
        self._ejection = ejection_timing or ConstantPulseEjection()
        self._bus = event_bus
        self._max_piece_count = max(1, int(max_piece_count))
        self._exit_near_arc = float(exit_zone_near_arc_rad)
        self._intake_near_arc = float(intake_zone_near_arc_rad)
        self._pulse_cooldown_s = float(pulse_cooldown_s)
        self._wiggle_stall_s = float(wiggle_stall_ms) / 1000.0
        self._wiggle_cooldown_s = float(wiggle_cooldown_ms) / 1000.0
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._advance_interval_s = max(0.0, float(advance_interval_s))
        self._bookkeeping = _PieceBookkeeping(seen_global_ids=set())
        self._next_pulse_at: float = 0.0
        self._piece_count: int = 0
        self._purge_mode: bool = False

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        if self._purge_mode:
            return 0
        if self._piece_count >= self._max_piece_count:
            return 0
        # Delegate to AdmissionStrategy so Phase 4+ can plug a real gate in.
        decision = self._admission.can_admit(
            inbound_piece_hint={},
            runtime_state={
                "piece_count": self._piece_count,
                "max_piece_count": self._max_piece_count,
            },
        )
        return 1 if decision.allowed else 0

    def debug_snapshot(self) -> dict[str, Any]:
        snap = super().debug_snapshot()
        snap.update({
            "piece_count": int(self._piece_count),
            "max_piece_count": int(self._max_piece_count),
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
            if not self._purge_mode:
                self._credit_new_arrivals(tracks, now_mono)
            self._piece_count = len(tracks)
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
            if exit_track is None:
                # Nothing at the exit but the ring carries tracks — advance
                # so real pieces migrate toward the exit and the ghost-gating
                # tracker gets rotation evidence for stationary phantoms.
                self._bookkeeping.exit_stall_since = None
                if tracks and now_mono >= self._bookkeeping.next_advance_at:
                    self._dispatch_advance_pulse(now_mono)
                else:
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
        # Only commit a downstream slot for tracks the tracker has
        # confirmed as real via rotation-windowed motion evidence. Pending
        # tracks (not yet judged) fall through to the advance-pulse path,
        # which rotates the ring without claiming a slot — so a phantom at
        # the exit cannot strand the downstream slot forever if C3 never
        # actually receives anything.
        candidates = [
            t for t in tracks
            if t.angle_rad is not None and bool(getattr(t, "confirmed_real", False))
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: abs(_wrap_rad(t.angle_rad or 0.0)))
        head = candidates[0]
        if abs(_wrap_rad(head.angle_rad or 0.0)) > self._exit_near_arc:
            return None
        return head

    def _dispatch_exit_pulse(self, track: Track, now_mono: float) -> None:
        # Give the downstream handoff ~3 s to resolve (C3 registers the
        # arriving piece or the slot auto-releases so the ring can keep
        # flowing if the pulse never produced a visible arrival).
        claimed = self._downstream_slot.try_claim(
            now_mono=now_mono, hold_time_s=3.0
        )
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
        self._publish_rotation_window(timing.pulse_ms / 1000.0, now_mono)
        self._set_state("pulsing")

    def _dispatch_advance_pulse(self, now_mono: float) -> None:
        """Rotate the ring without claiming a downstream slot.

        Fired when the ring carries tracks but none is near the exit — keeps
        the ring moving so real pieces eventually reach the exit and the
        ghost-gating tracker sees rotation-windowed samples for stationary
        phantoms.
        """
        timing = self._ejection.timing_for({"advance": True})

        def _run_pulse() -> None:
            try:
                self._pulse_command(timing.pulse_ms)
            except Exception:
                self._logger.exception("RuntimeC2: advance pulse command raised")

        self._next_pulse_at = now_mono + self._pulse_cooldown_s
        enqueued = self._hw.enqueue(_run_pulse, label="c2_advance_pulse")
        if not enqueued:
            self._set_state("idle", blocked_reason="hw_queue_full")
            return
        self._bookkeeping.next_advance_at = now_mono + self._advance_interval_s
        self._publish_rotation_window(timing.pulse_ms / 1000.0, now_mono)
        self._set_state("advancing")

    def _dispatch_purge_pulse(self, now_mono: float) -> None:
        """Pulse the ring without gating on downstream capacity or exit_track.

        Used during C2 purge: rotate the platter so pieces fall through the
        C2->C3 transition regardless of whether C3 is full. Does not claim a
        downstream slot.
        """
        timing = self._ejection.timing_for({"purge": True})

        def _run_pulse() -> None:
            try:
                self._pulse_command(timing.pulse_ms)
            except Exception:
                self._logger.exception("RuntimeC2: purge pulse command raised")

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
        self._next_pulse_at = 0.0

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
            piece_count=int(self._runtime._piece_count),
            owned_count=0,
            pending_detections=0,
        )

    def drain_step(self, now_mono: float) -> bool:
        return bool(self._runtime._purge_mode)


__all__ = ["RuntimeC2"]
