"""RuntimeC4 — classification chamber (carousel + classifier + drop commit).

Owns a ZoneManager, a pluggable Classifier, a C4-tuned AdmissionStrategy and
EjectionTimingStrategy. State machine is private: RUNNING → CLASSIFY_PENDING
→ DROP_COMMIT, with EXIT_SHIMMY for stalled exits. Hardware is callable-
injected; no bridge imports.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from rt.contracts.admission import AdmissionStrategy
from rt.contracts.classification import Classifier, ClassifierResult
from rt.contracts.ejection import EjectionTimingStrategy
from rt.contracts.feed import FeedFrame
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot

from ._strategies import C4Admission, C4EjectionTiming
from ._zones import TrackAngularExtent, ZoneManager
from .base import BaseRuntime, HwWorker


DEFAULT_CLASSIFY_ANGLE_DEG = 90.0
DEFAULT_EXIT_ANGLE_DEG = 270.0
DEFAULT_ANGLE_TOLERANCE_DEG = 12.0
DEFAULT_SHIMMY_STEP_DEG = 4.0
DEFAULT_SHIMMY_STALL_MS = 800
DEFAULT_SHIMMY_COOLDOWN_MS = 1200
DEFAULT_INTAKE_HALF_WIDTH_DEG = 18.0


class _C4State(str, Enum):
    RUNNING = "running"
    CLASSIFY_PENDING = "classify_pending"
    EXIT_SHIMMY = "exit_shimmy"
    DROP_COMMIT = "drop_commit"


@dataclass(slots=True)
class _PieceDossier:
    piece_uuid: str
    global_id: int | None
    intake_ts: float
    angle_at_intake_deg: float
    last_seen_mono: float
    classified_ts: float | None = None
    classify_future: "Future[ClassifierResult] | None" = None
    result: ClassifierResult | None = None
    reject_reason: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class RuntimeC4(BaseRuntime):
    """Classification carousel runtime."""

    def __init__(
        self,
        *,
        upstream_slot: CapacitySlot,
        downstream_slot: CapacitySlot,
        zone_manager: ZoneManager,
        classifier: Classifier,
        admission: AdmissionStrategy | None = None,
        ejection: EjectionTimingStrategy | None = None,
        carousel_move_command: Callable[[float], bool] | None = None,
        eject_command: Callable[[], bool] | None = None,
        crop_provider: Callable[[FeedFrame, Track], Any] | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        runtime_id: str = "c4",
        feed_id: str = "c4_feed",
        classify_angle_deg: float = DEFAULT_CLASSIFY_ANGLE_DEG,
        exit_angle_deg: float = DEFAULT_EXIT_ANGLE_DEG,
        angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
        intake_half_width_deg: float = DEFAULT_INTAKE_HALF_WIDTH_DEG,
        shimmy_step_deg: float = DEFAULT_SHIMMY_STEP_DEG,
        shimmy_stall_ms: int = DEFAULT_SHIMMY_STALL_MS,
        shimmy_cooldown_ms: int = DEFAULT_SHIMMY_COOLDOWN_MS,
        post_commit_cooldown_ms: int | None = None,
    ) -> None:
        super().__init__(runtime_id, feed_id=feed_id, logger=logger, hw_worker=hw_worker)
        self._upstream_slot = upstream_slot
        self._downstream_slot = downstream_slot
        self._zone_manager = zone_manager
        self._classifier = classifier
        self._admission = admission or C4Admission(max_zones=zone_manager.max_zones)
        self._ejection = ejection or C4EjectionTiming()
        self._carousel_move = carousel_move_command or (lambda _deg: True)
        self._eject = eject_command or (lambda: True)
        self._crop_provider = crop_provider
        self._classify_angle_deg = float(classify_angle_deg)
        self._exit_angle_deg = float(exit_angle_deg)
        self._angle_tol_deg = float(angle_tolerance_deg)
        self._intake_half_width_deg = float(intake_half_width_deg)
        self._shimmy_step_deg = float(shimmy_step_deg)
        self._shimmy_stall_s = float(shimmy_stall_ms) / 1000.0
        self._shimmy_cooldown_s = float(shimmy_cooldown_ms) / 1000.0
        cooldown_ms = (
            self._ejection.timing_for({}).fall_time_ms
            if post_commit_cooldown_ms is None
            else float(post_commit_cooldown_ms)
        )
        self._post_commit_cooldown_s = cooldown_ms / 1000.0
        self._pieces: dict[str, _PieceDossier] = {}
        self._track_to_piece: dict[int, str] = {}
        self._fsm: _C4State = _C4State.RUNNING
        self._raw_detection_count: int = 0
        self._latest_frame: FeedFrame | None = None
        self._exit_stall_since: float | None = None
        self._next_shimmy_at: float = 0.0
        self._next_accept_at: float = 0.0

    def available_slots(self) -> int:
        decision = self._admission.can_admit(
            inbound_piece_hint={},
            runtime_state=self._admission_state_snapshot(),
        )
        return 1 if decision.allowed else 0

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            self._tick_inner(inbox, now_mono)
        except Exception:
            self._logger.exception("RuntimeC4: tick raised")
        finally:
            self._tick_end(start)

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        """Distributor accepted the piece — free slot, remove zone, pop dossier."""
        self._finalize_piece(piece_uuid, now_mono=now_mono, arm_cooldown=True)

    def on_piece_rejected(self, piece_uuid: str, reason: str) -> None:
        """Phase-5 stub: distributor signals the piece cannot be sorted."""
        self._logger.info("RuntimeC4: piece %s rejected (reason=%s)", piece_uuid, reason)
        dossier = self._pieces.get(piece_uuid)
        if dossier is not None:
            dossier.reject_reason = reason
        self._finalize_piece(piece_uuid, now_mono=None, arm_cooldown=False)

    def _finalize_piece(
        self,
        piece_uuid: str,
        *,
        now_mono: float | None,
        arm_cooldown: bool,
    ) -> None:
        dossier = self._pieces.pop(piece_uuid, None)
        if dossier is not None and dossier.global_id is not None:
            self._track_to_piece.pop(int(dossier.global_id), None)
        self._zone_manager.remove_zone(piece_uuid)
        self._downstream_slot.release()
        if arm_cooldown and now_mono is not None:
            self._next_accept_at = now_mono + self._post_commit_cooldown_s
        if self._fsm is _C4State.DROP_COMMIT:
            self._fsm = _C4State.RUNNING
            self._set_state(self._fsm.value)

    def dossier_count(self) -> int:
        return len(self._pieces)

    def dossier_for(self, piece_uuid: str) -> _PieceDossier | None:
        return self._pieces.get(piece_uuid)

    def fsm_state(self) -> str:
        return self._fsm.value

    def _tick_inner(self, inbox: RuntimeInbox, now_mono: float) -> None:
        tracks = self._confirmed_tracks(inbox.tracks)
        self._raw_detection_count = len(inbox.tracks.tracks) if inbox.tracks else 0
        extents = [
            TrackAngularExtent(
                piece_uuid=self._track_to_piece[int(t.global_id)],
                global_id=t.global_id,
                center_deg=math.degrees(t.angle_rad or 0.0),
                half_width_deg=self._intake_half_width_deg,
                last_seen_mono=now_mono,
            )
            for t in tracks
            if t.global_id is not None and int(t.global_id) in self._track_to_piece
        ]
        evicted = self._zone_manager.update_from_tracks(extents, now_mono=now_mono)
        for piece_uuid in evicted:
            if piece_uuid in self._pieces:
                self._logger.info(
                    "RuntimeC4: pruning dossier piece=%s (zone evicted, track_lost)",
                    piece_uuid,
                )
                self._finalize_piece(piece_uuid, now_mono=None, arm_cooldown=False)
        self._admit_new_tracks(tracks, now_mono)
        self._submit_classifications(tracks, now_mono)
        self._poll_classifier_futures(now_mono)
        self._handle_exit(tracks, inbox, now_mono)
        self._refresh_fsm_label()

    # -- Helpers ------------------------------------------------------

    def _confirmed_tracks(self, batch: TrackBatch | None) -> list[Track]:
        if batch is None:
            return []
        return [t for t in batch.tracks if t.confirmed_real]

    def _admission_state_snapshot(self) -> dict[str, Any]:
        arc_clear = self._zone_manager.is_arc_clear(
            self._zone_manager.intake_angle_deg,
            half_width_deg=self._intake_half_width_deg,
        )
        return {
            "raw_detection_count": self._raw_detection_count,
            "zone_count": self._zone_manager.zone_count(),
            "arc_clear": arc_clear,
            "transport_count": len(self._pieces),
            "cooldown_active": time.monotonic() < self._next_accept_at,
        }

    def _admit_new_tracks(self, tracks: list[Track], now_mono: float) -> None:
        if now_mono < self._next_accept_at:
            return
        for track in tracks:
            if track.global_id is None:
                continue
            gid = int(track.global_id)
            if gid in self._track_to_piece:
                continue
            angle_deg = math.degrees(track.angle_rad or 0.0)
            if not self._near_angle(angle_deg, self._zone_manager.intake_angle_deg):
                continue
            decision = self._admission.can_admit(
                inbound_piece_hint={"global_id": gid},
                runtime_state=self._admission_state_snapshot(),
            )
            if not decision.allowed:
                continue
            piece_uuid = uuid.uuid4().hex[:12]
            if not self._zone_manager.add_zone(
                piece_uuid=piece_uuid,
                angle_deg=angle_deg,
                half_width_deg=self._intake_half_width_deg,
                global_id=gid,
                now_mono=now_mono,
            ):
                continue
            dossier = _PieceDossier(
                piece_uuid=piece_uuid,
                global_id=gid,
                intake_ts=now_mono,
                angle_at_intake_deg=angle_deg,
                last_seen_mono=now_mono,
            )
            self._pieces[piece_uuid] = dossier
            self._track_to_piece[gid] = piece_uuid
            self._upstream_slot.release()

    def _submit_classifications(self, tracks: list[Track], now_mono: float) -> None:
        if self._latest_frame is None and self._crop_provider is None:
            # No crop source wired yet (Phase-5 wiring).
            return
        for track in tracks:
            if track.global_id is None:
                continue
            gid = int(track.global_id)
            piece_uuid = self._track_to_piece.get(gid)
            if piece_uuid is None:
                continue
            dossier = self._pieces.get(piece_uuid)
            if dossier is None:
                continue
            if dossier.result is not None or dossier.classify_future is not None:
                continue
            angle_deg = math.degrees(track.angle_rad or 0.0)
            if not self._near_angle(angle_deg, self._classify_angle_deg):
                continue
            crop = self._build_crop(track)
            if crop is None:
                continue
            frame = self._latest_frame or _synthetic_frame(
                feed_id=self.feed_id or "c4_feed",
                now_mono=now_mono,
            )
            try:
                future = self._classifier.classify_async(track, frame, crop)
            except Exception:
                self._logger.exception(
                    "RuntimeC4: classifier.classify_async raised for piece=%s",
                    piece_uuid,
                )
                continue
            dossier.classify_future = future
            dossier.last_seen_mono = now_mono

    def _poll_classifier_futures(self, now_mono: float) -> None:
        for dossier in self._pieces.values():
            future = dossier.classify_future
            if future is None or not future.done():
                continue
            dossier.classify_future = None
            try:
                dossier.result = future.result(timeout=0.0)
            except Exception:
                self._logger.exception(
                    "RuntimeC4: classifier future raised for piece=%s",
                    dossier.piece_uuid,
                )
                dossier.result = ClassifierResult(
                    part_id=None,
                    color_id=None,
                    category=None,
                    confidence=0.0,
                    algorithm=getattr(self._classifier, "key", "unknown"),
                    latency_ms=0.0,
                    meta={"error": "future_raised"},
                )
            dossier.classified_ts = now_mono

    def _handle_exit(
        self,
        tracks: list[Track],
        inbox: RuntimeInbox,
        now_mono: float,
    ) -> None:
        exit_track = self._pick_exit_track(tracks)
        if exit_track is None:
            self._exit_stall_since = None
            if self._fsm is _C4State.EXIT_SHIMMY:
                self._fsm = _C4State.RUNNING
            return

        gid = int(exit_track.global_id) if exit_track.global_id is not None else -1
        piece_uuid = self._track_to_piece.get(gid)
        if piece_uuid is None:
            return
        dossier = self._pieces.get(piece_uuid)
        if dossier is None or dossier.result is None:
            if inbox.capacity_downstream <= 0:
                self._maybe_shimmy(now_mono)
            return

        if inbox.capacity_downstream <= 0:
            self._maybe_shimmy(now_mono)
            return
        if self._hw.busy():
            self._set_state("drop_commit", blocked_reason="hw_busy")
            return
        if not self._downstream_slot.try_claim():
            self._set_state("drop_commit", blocked_reason="downstream_full")
            return

        def _do_eject() -> None:
            try:
                ok = bool(self._eject())
            except Exception:
                self._logger.exception("RuntimeC4: eject_command raised")
                ok = False
            if not ok:
                self._downstream_slot.release()

        if not self._hw.enqueue(_do_eject, label="c4_eject"):
            self._downstream_slot.release()
            self._set_state("drop_commit", blocked_reason="hw_queue_full")
            return
        self._fsm = _C4State.DROP_COMMIT
        self._set_state(self._fsm.value)
        self._exit_stall_since = None

    def _maybe_shimmy(self, now_mono: float) -> bool:
        if self._exit_stall_since is None:
            self._exit_stall_since = now_mono
            return False
        stall = now_mono - self._exit_stall_since
        if stall < self._shimmy_stall_s:
            return False
        if now_mono < self._next_shimmy_at:
            return False
        if self._hw.busy():
            return False
        step = self._shimmy_step_deg

        def _do_shimmy() -> None:
            try:
                self._carousel_move(step)
                self._carousel_move(-step)
            except Exception:
                self._logger.exception("RuntimeC4: shimmy move raised")

        if self._hw.enqueue(_do_shimmy, label="c4_exit_shimmy"):
            self._next_shimmy_at = now_mono + self._shimmy_cooldown_s
            self._fsm = _C4State.EXIT_SHIMMY
            self._set_state(self._fsm.value)
            return True
        return False

    def _pick_exit_track(self, tracks: list[Track]) -> Track | None:
        best: Track | None = None
        best_delta = float("inf")
        for t in tracks:
            if t.angle_rad is None or t.global_id is None:
                continue
            if int(t.global_id) not in self._track_to_piece:
                continue
            delta = abs(_wrap_deg(math.degrees(t.angle_rad) - self._exit_angle_deg))
            if delta < best_delta and delta <= self._angle_tol_deg:
                best = t
                best_delta = delta
        return best

    def _refresh_fsm_label(self) -> None:
        if self._fsm in (_C4State.DROP_COMMIT, _C4State.EXIT_SHIMMY):
            self._set_state(self._fsm.value)
            return
        inflight = any(d.classify_future is not None for d in self._pieces.values())
        self._fsm = _C4State.CLASSIFY_PENDING if inflight else _C4State.RUNNING
        self._set_state(self._fsm.value)

    def _build_crop(self, track: Track) -> Any | None:
        if self._crop_provider is None or self._latest_frame is None:
            return None
        try:
            return self._crop_provider(self._latest_frame, track)
        except Exception:
            self._logger.exception(
                "RuntimeC4: crop_provider raised for track=%s",
                track.track_id,
            )
            return None

    def _near_angle(self, actual_deg: float, target_deg: float) -> bool:
        return abs(_wrap_deg(actual_deg - target_deg)) <= self._angle_tol_deg

    def set_latest_frame(self, frame: FeedFrame | None) -> None:
        """Inject the latest frame for crop extraction (wired in Phase 5)."""
        self._latest_frame = frame


def _synthetic_frame(*, feed_id: str, now_mono: float) -> FeedFrame:
    """Placeholder FeedFrame for pre-Phase-5 unit tests."""
    return FeedFrame(
        feed_id=feed_id, camera_id="synthetic", raw=None, gray=None,
        timestamp=now_mono, monotonic_ts=now_mono, frame_seq=0,
    )


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["RuntimeC4"]
