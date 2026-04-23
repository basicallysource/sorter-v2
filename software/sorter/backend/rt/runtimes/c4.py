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
from rt.contracts.events import Event, EventBus
from rt.contracts.feed import FeedFrame
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.topics import PIECE_CLASSIFIED, PIECE_REGISTERED

from ._strategies import C4Admission, C4EjectionTiming, C4StartupPurgeStrategy
from ._zones import TrackAngularExtent, ZoneManager
from .base import BaseRuntime, HwWorker


DEFAULT_CLASSIFY_ANGLE_DEG = 90.0
DEFAULT_EXIT_ANGLE_DEG = 270.0
DEFAULT_ANGLE_TOLERANCE_DEG = 12.0
DEFAULT_SHIMMY_STEP_DEG = 4.0
DEFAULT_SHIMMY_STALL_MS = 800
DEFAULT_SHIMMY_COOLDOWN_MS = 1200
DEFAULT_INTAKE_HALF_WIDTH_DEG = 18.0
DEFAULT_TRANSPORT_STEP_DEG = 6.0
DEFAULT_TRANSPORT_COOLDOWN_MS = 250
DEFAULT_TRACK_STALE_S = 0.5
DEFAULT_RECOVER_MIN_HIT_COUNT = 4
DEFAULT_RECOVER_MIN_SCORE = 0.55
DEFAULT_RECOVER_MIN_AGE_S = 0.6


class _C4State(str, Enum):
    RUNNING = "running"
    STARTUP_PURGE = "startup_purge"
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
        startup_purge: C4StartupPurgeStrategy | None = None,
        startup_purge_detection_count_provider: Callable[[], int] | None = None,
        carousel_move_command: Callable[[float], bool] | None = None,
        startup_purge_move_command: Callable[[float], bool] | None = None,
        startup_purge_mode_command: Callable[[bool], bool] | None = None,
        eject_command: Callable[[], bool] | None = None,
        crop_provider: Callable[[FeedFrame, Track], Any] | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        event_bus: EventBus | None = None,
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
        transport_step_deg: float = DEFAULT_TRANSPORT_STEP_DEG,
        transport_cooldown_ms: int = DEFAULT_TRANSPORT_COOLDOWN_MS,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        reconcile_min_hit_count: int = DEFAULT_RECOVER_MIN_HIT_COUNT,
        reconcile_min_score: float = DEFAULT_RECOVER_MIN_SCORE,
        reconcile_min_age_s: float = DEFAULT_RECOVER_MIN_AGE_S,
    ) -> None:
        super().__init__(runtime_id, feed_id=feed_id, logger=logger, hw_worker=hw_worker)
        self._upstream_slot = upstream_slot
        self._downstream_slot = downstream_slot
        self._zone_manager = zone_manager
        self._classifier = classifier
        self._admission = admission or C4Admission(max_zones=zone_manager.max_zones)
        self._ejection = ejection or C4EjectionTiming()
        self._startup_purge = startup_purge
        self._startup_purge_detection_count_provider = (
            startup_purge_detection_count_provider
        )
        self._carousel_move = carousel_move_command or (lambda _deg: True)
        self._startup_purge_move = startup_purge_move_command or self._carousel_move
        self._startup_purge_mode = startup_purge_mode_command or (lambda _enabled: True)
        self._eject = eject_command or (lambda: True)
        self._crop_provider = crop_provider
        self._classify_angle_deg = float(classify_angle_deg)
        self._exit_angle_deg = float(exit_angle_deg)
        self._angle_tol_deg = float(angle_tolerance_deg)
        self._intake_half_width_deg = float(intake_half_width_deg)
        self._shimmy_step_deg = float(shimmy_step_deg)
        self._shimmy_stall_s = float(shimmy_stall_ms) / 1000.0
        self._shimmy_cooldown_s = float(shimmy_cooldown_ms) / 1000.0
        self._transport_step_deg = float(transport_step_deg)
        self._transport_cooldown_s = float(transport_cooldown_ms) / 1000.0
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._reconcile_min_hit_count = max(1, int(reconcile_min_hit_count))
        self._reconcile_min_score = float(reconcile_min_score)
        self._reconcile_min_age_s = max(0.0, float(reconcile_min_age_s))
        cooldown_ms = (
            self._ejection.timing_for({}).fall_time_ms
            if post_commit_cooldown_ms is None
            else float(post_commit_cooldown_ms)
        )
        self._post_commit_cooldown_s = cooldown_ms / 1000.0
        self._bus = event_bus
        self._pieces: dict[str, _PieceDossier] = {}
        self._track_to_piece: dict[int, str] = {}
        self._fsm: _C4State = _C4State.RUNNING
        self._raw_detection_count: int = 0
        self._latest_frame: FeedFrame | None = None
        self._exit_stall_since: float | None = None
        self._next_shimmy_at: float = 0.0
        self._next_accept_at: float = 0.0
        self._next_transport_at: float = 0.0
        self._startup_purge_armed: bool = False
        self._startup_purge_prime_moves: int = 0
        self._startup_purge_next_prime_at: float = 0.0
        self._startup_purge_clear_since: float | None = None
        self._startup_purge_commit_piece_uuid: str | None = None
        self._startup_purge_commit_deadline: float | None = None
        self._startup_purge_eject_ok: bool | None = None
        self._startup_purge_mode_active: bool = False

    def available_slots(self) -> int:
        if self._startup_purge_pending():
            return 0
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

    def debug_snapshot(self) -> dict[str, Any]:
        """Compact live snapshot for operator diagnostics and API status."""
        return {
            "fsm_state": self._fsm.value,
            "startup_purge_armed": bool(self._startup_purge_armed),
            "startup_purge_prime_moves": int(self._startup_purge_prime_moves),
            "startup_purge_commit_piece_uuid": self._startup_purge_commit_piece_uuid,
            "raw_detection_count": int(self._raw_detection_count),
            "dossier_count": len(self._pieces),
            "track_to_piece_count": len(self._track_to_piece),
            "zone_count": self._zone_manager.zone_count(),
            "hw_busy": bool(self._hw.busy()),
            "hw_pending": int(self._hw.pending()),
        }

    def arm_startup_purge(self) -> None:
        strategy = self._startup_purge
        if strategy is None or not strategy.enabled:
            self._startup_purge_armed = False
            return
        self._startup_purge_armed = True
        self._startup_purge_prime_moves = 0
        self._startup_purge_next_prime_at = 0.0
        self._startup_purge_clear_since = None
        self._startup_purge_commit_piece_uuid = None
        self._startup_purge_commit_deadline = None
        self._startup_purge_eject_ok = None

    def _tick_inner(self, inbox: RuntimeInbox, now_mono: float) -> None:
        raw_tracks = self._fresh_tracks(inbox.tracks, require_confirmed=False)
        self._raw_detection_count = len(raw_tracks)
        owned_tracks = self._sync_owned_tracks(raw_tracks, now_mono)
        if self._run_startup_purge(raw_tracks, owned_tracks, now_mono):
            return
        confirmed_tracks = [t for t in raw_tracks if t.confirmed_real]
        self._admit_new_tracks(confirmed_tracks, now_mono)
        self._reconcile_visible_tracks(raw_tracks, now_mono)
        owned_tracks = self._owned_tracks(raw_tracks)
        self._submit_classifications(owned_tracks, now_mono)
        self._poll_classifier_futures(now_mono)
        self._handle_exit(owned_tracks, inbox, now_mono)
        transport_active = self._maybe_advance_transport(owned_tracks, now_mono)
        self._refresh_fsm_label(transport_active=transport_active)

    # -- Helpers ------------------------------------------------------

    def _fresh_tracks(
        self,
        batch: TrackBatch | None,
        *,
        require_confirmed: bool,
    ) -> list[Track]:
        if batch is None:
            return []
        batch_ts = float(batch.timestamp)
        return [
            t
            for t in batch.tracks
            if (t.confirmed_real or not require_confirmed)
            and self._is_track_fresh(t, batch_ts)
        ]

    def _is_track_fresh(self, track: Track, batch_ts: float) -> bool:
        last_seen_ts = float(track.last_seen_ts)
        if batch_ts <= 0.0 or last_seen_ts <= 0.0:
            return True
        return (batch_ts - last_seen_ts) <= self._track_stale_s

    def _admission_state_snapshot(self) -> dict[str, Any]:
        arc_clear = self._zone_manager.is_arc_clear(
            self._zone_manager.intake_angle_deg,
            half_width_deg=self._intake_half_width_deg,
        )
        return {
            "raw_detection_count": self._raw_detection_count,
            "zone_count": self._zone_manager.zone_count(),
            "dropzone_clear": self._zone_manager.is_dropzone_clear(),
            "arc_clear": arc_clear,
            "transport_count": len(self._pieces),
            "cooldown_active": time.monotonic() < self._next_accept_at,
            "startup_purge_active": self._startup_purge_pending(),
        }

    def _startup_purge_pending(self) -> bool:
        strategy = self._startup_purge
        return bool(strategy is not None and strategy.enabled and self._startup_purge_armed)

    def _enter_startup_purge(self) -> None:
        if not self._startup_purge_mode_active:
            try:
                self._startup_purge_mode_active = bool(self._startup_purge_mode(True))
            except Exception:
                self._logger.exception("RuntimeC4: enabling startup purge mode raised")
        self._fsm = _C4State.STARTUP_PURGE

    def _exit_startup_purge(self) -> None:
        if self._startup_purge_mode_active:
            try:
                self._startup_purge_mode(False)
            except Exception:
                self._logger.exception("RuntimeC4: disabling startup purge mode raised")
            self._startup_purge_mode_active = False
        self._fsm = _C4State.RUNNING

    def _owned_tracks(self, tracks: list[Track]) -> list[Track]:
        return [
            t
            for t in tracks
            if t.global_id is not None and int(t.global_id) in self._track_to_piece
        ]

    def _sync_owned_tracks(self, tracks: list[Track], now_mono: float) -> list[Track]:
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
        return self._owned_tracks(tracks)

    def _run_startup_purge(
        self,
        raw_tracks: list[Track],
        owned_tracks: list[Track],
        now_mono: float,
    ) -> bool:
        strategy = self._startup_purge
        if strategy is None:
            return False
        return strategy.run(
            self,
            raw_tracks,
            owned_tracks,
            self._startup_purge_visible_detection_count(raw_tracks),
            now_mono,
        )

    def _startup_purge_visible_detection_count(self, raw_tracks: list[Track]) -> int:
        provider = self._startup_purge_detection_count_provider
        if callable(provider):
            try:
                value = int(provider())
            except Exception:
                self._logger.exception(
                    "RuntimeC4: startup purge detection-count provider raised"
                )
            else:
                return max(0, value)
        return len(raw_tracks)

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
            self._register_piece_for_track(
                track,
                now_mono=now_mono,
                release_upstream=True,
                recovered=False,
            )

    def _reconcile_visible_tracks(self, tracks: list[Track], now_mono: float) -> None:
        # Restart/re-home recovery: if the tray already contains visible parts,
        # rebuild ownership from stable tracks so the runtime can continue.
        if self._pieces or self._zone_manager.zone_count() > 0:
            return
        candidates: list[Track] = []
        for track in tracks:
            if track.global_id is None or track.angle_rad is None:
                continue
            gid = int(track.global_id)
            if gid in self._track_to_piece:
                continue
            if int(track.hit_count) < self._reconcile_min_hit_count:
                continue
            if float(track.score) < self._reconcile_min_score:
                continue
            track_age_s = max(0.0, float(track.last_seen_ts) - float(track.first_seen_ts))
            if track_age_s < self._reconcile_min_age_s:
                continue
            candidates.append(track)
        candidates.sort(key=lambda t: (float(t.score), int(t.hit_count)), reverse=True)
        for track in candidates:
            if self._zone_manager.zone_count() >= self._zone_manager.max_zones:
                break
            self._register_piece_for_track(
                track,
                now_mono=now_mono,
                release_upstream=False,
                recovered=True,
            )

    def _register_piece_for_track(
        self,
        track: Track,
        *,
        now_mono: float,
        release_upstream: bool,
        recovered: bool,
    ) -> bool:
        if track.global_id is None or track.angle_rad is None:
            return False
        gid = int(track.global_id)
        if gid in self._track_to_piece:
            return False
        angle_deg = math.degrees(track.angle_rad)
        piece_uuid = uuid.uuid4().hex[:12]
        if not self._zone_manager.add_zone(
            piece_uuid=piece_uuid,
            angle_deg=angle_deg,
            half_width_deg=self._intake_half_width_deg,
            global_id=gid,
            now_mono=now_mono,
        ):
            return False
        dossier = _PieceDossier(
            piece_uuid=piece_uuid,
            global_id=gid,
            intake_ts=now_mono,
            angle_at_intake_deg=angle_deg,
            last_seen_mono=now_mono,
            extras={"recovered": recovered},
        )
        self._pieces[piece_uuid] = dossier
        self._track_to_piece[gid] = piece_uuid
        if release_upstream:
            self._upstream_slot.release()
        self._publish(
            PIECE_REGISTERED,
            {
                "piece_uuid": piece_uuid,
                "tracked_global_id": gid,
                "angle_at_intake_deg": angle_deg,
                "intake_ts_mono": now_mono,
                "confirmed_real": True,
                "stage": "registered",
                "classification_status": "pending",
                "recovered": recovered,
                "dossier": {
                    "piece_uuid": piece_uuid,
                    "tracked_global_id": gid,
                    "classification_channel_zone_center_deg": angle_deg,
                    "first_carousel_seen_ts": now_mono,
                    "recovered": recovered,
                },
            },
            now_mono,
        )
        return True

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
            result = dossier.result
            payload: dict[str, Any] = {
                "piece_uuid": dossier.piece_uuid,
                "tracked_global_id": dossier.global_id,
                "classified_ts_mono": now_mono,
                "confirmed_real": True,
                "stage": "classified",
                "classification_status": "classified"
                if result and result.part_id
                else "unknown",
                "dossier": {
                    "piece_uuid": dossier.piece_uuid,
                    "tracked_global_id": dossier.global_id,
                    "part_id": result.part_id if result else None,
                    "color_id": result.color_id if result else None,
                    "category": result.category if result else None,
                    "confidence": result.confidence if result else None,
                    "algorithm": result.algorithm if result else None,
                    "latency_ms": result.latency_ms if result else None,
                    "classified_at": now_mono,
                },
            }
            self._publish(PIECE_CLASSIFIED, payload, now_mono)

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

    def _maybe_advance_transport(
        self,
        tracks: list[Track],
        now_mono: float,
        *,
        move_command: Callable[[float], bool] | None = None,
    ) -> bool:
        if not self._pieces or not tracks:
            return False
        if self._fsm in (_C4State.DROP_COMMIT, _C4State.EXIT_SHIMMY):
            return False
        if self._hw.busy() or now_mono < self._next_transport_at:
            return False
        exit_track = self._pick_exit_track(tracks)
        if exit_track is not None and exit_track.global_id is not None:
            piece_uuid = self._track_to_piece.get(int(exit_track.global_id))
            dossier = self._pieces.get(piece_uuid) if piece_uuid is not None else None
            if dossier is not None and dossier.result is not None:
                return False

        step = self._transport_step_deg
        move = move_command or self._carousel_move

        def _do_move() -> None:
            try:
                move(step)
            except Exception:
                self._logger.exception("RuntimeC4: transport move raised")

        if self._hw.enqueue(_do_move, label="c4_transport"):
            self._next_transport_at = now_mono + self._transport_cooldown_s
            return True
        return False

    def _refresh_fsm_label(self, *, transport_active: bool = False) -> None:
        if self._fsm in (_C4State.DROP_COMMIT, _C4State.EXIT_SHIMMY):
            self._set_state(self._fsm.value)
            return
        inflight = any(d.classify_future is not None for d in self._pieces.values())
        self._fsm = _C4State.CLASSIFY_PENDING if inflight else _C4State.RUNNING
        if transport_active and self._fsm is _C4State.RUNNING:
            self._set_state("rotate_pipeline")
            return
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

    def _publish(self, topic: str, payload: dict[str, Any], now_mono: float) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(
                Event(
                    topic=topic,
                    payload=payload,
                    source=self.runtime_id,
                    ts_mono=now_mono,
                )
            )
        except Exception:
            self._logger.exception(
                "RuntimeC4: event publish failed for topic=%s (piece=%s)",
                topic,
                payload.get("piece_uuid"),
            )


def _synthetic_frame(*, feed_id: str, now_mono: float) -> FeedFrame:
    """Placeholder FeedFrame for pre-Phase-5 unit tests."""
    return FeedFrame(
        feed_id=feed_id, camera_id="synthetic", raw=None, gray=None,
        timestamp=now_mono, monotonic_ts=now_mono, frame_seq=0,
    )


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["RuntimeC4"]
