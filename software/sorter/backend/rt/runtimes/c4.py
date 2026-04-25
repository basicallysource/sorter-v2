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
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from rt.contracts.admission import AdmissionStrategy
from rt.contracts.classification import Classifier, ClassifierResult
from rt.contracts.ejection import EjectionTimingStrategy
from rt.contracts.events import Event, EventBus
from rt.contracts.feed import FeedFrame
from rt.contracts.handoff import HandoffPort
from rt.contracts.purge import PurgeCounts, PurgePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.topics import (
    PERCEPTION_ROTATION,
    PIECE_CLASSIFIED,
    PIECE_REGISTERED,
    PIECE_TRANSIT_LINKED,
    RUNTIME_HANDOFF_BURST,
)
from rt.perception.track_policy import action_track, admission_basis, is_visible_track
from rt.pieces.identity import new_piece_uuid, new_tracker_epoch, tracklet_payload
from rt.services.track_transit import TrackTransitRegistry, TransitCandidate
from rt.services.transport_velocity import TransportVelocityObserver

from ._handoff_diagnostics import HandoffDiagnostics
from ._move_events import publish_move_completed
from ._strategies import (
    C4Admission,
    C4EjectionTiming,
    C4StartupPurgeState,
    C4StartupPurgeStrategy,
)
from ._zones import TrackAngularExtent, ZoneManager
from .base import BaseRuntime, HwWorker


DEFAULT_CLASSIFY_ANGLE_DEG = 90.0
DEFAULT_EXIT_ANGLE_DEG = 270.0
DEFAULT_ANGLE_TOLERANCE_DEG = 12.0
# C4 can classify before the final point-of-no-return so the distributor
# can preposition while the piece is still travelling toward the exit.
DEFAULT_CLASSIFY_PRETRIGGER_EXIT_LEAD_DEG = 72.0
DEFAULT_SHIMMY_STEP_DEG = 4.0
DEFAULT_SHIMMY_STALL_MS = 800
DEFAULT_SHIMMY_COOLDOWN_MS = 1200
DEFAULT_INTAKE_HALF_WIDTH_DEG = 18.0
DEFAULT_TRANSPORT_STEP_DEG = 3.0
DEFAULT_TRANSPORT_MAX_STEP_DEG = 8.0
DEFAULT_TRANSPORT_TARGET_RPM = 0.7
DEFAULT_EXIT_APPROACH_ANGLE_DEG = 36.0
DEFAULT_EXIT_APPROACH_STEP_DEG = 3.0
DEFAULT_EXIT_BBOX_OVERLAP_RATIO = 0.5
# Minimum angular separation that must exist between the matched ejecting
# piece and any other owned track behind it (in the direction opposite to
# rotation) before the exit-release shimmy is allowed to fire. Without
# this guard, a trailing piece sitting inside the chute opening can be
# nudged off by the same shimmy motion and fall into the bin positioned
# for the previous piece. Live observation on 2026-04-25 confirmed the
# failure mode. Tuned slightly larger than the chute drop tolerance so a
# trailing piece is decisively outside the chute mouth before we shake.
DEFAULT_EXIT_TRAILING_SAFETY_DEG = 14.0
# Conservative default: C4 is a gear-driven channel and should advance with
# small, smooth moves unless live tuning intentionally pushes throughput.
DEFAULT_TRANSPORT_COOLDOWN_MS = 180
DEFAULT_TRACK_STALE_S = 0.5
DEFAULT_RECOVER_MIN_HIT_COUNT = 2
DEFAULT_RECOVER_MIN_SCORE = 0.35
DEFAULT_RECOVER_MIN_AGE_S = 0.2
DEFAULT_IDLE_JOG_STEP_DEG = 2.0
DEFAULT_IDLE_JOG_COOLDOWN_MS = 500
DEFAULT_UNJAM_STALL_MS = 2500
DEFAULT_UNJAM_MIN_PROGRESS_DEG = 2.0
DEFAULT_UNJAM_COOLDOWN_MS = 3000
DEFAULT_UNJAM_REVERSE_DEG = 3.0
DEFAULT_UNJAM_FORWARD_DEG = 9.0
DEFAULT_SAMPLE_TRANSPORT_TARGET_INTERVAL_S = 0.25
DEFAULT_SAMPLE_TRANSPORT_MAX_STEP_DEG = 45.0
DEFAULT_TRACKLET_TRANSIT_TTL_S = 1.25
DEFAULT_TRACKLET_TRANSIT_MAX_ANGLE_DELTA_DEG = 45.0
DEFAULT_DELIVERED_TRACK_SUPPRESS_S = 15.0


class _C4State(str, Enum):
    RUNNING = "running"
    STARTUP_PURGE = "startup_purge"
    CLASSIFY_PENDING = "classify_pending"
    EXIT_SHIMMY = "exit_shimmy"
    DROP_COMMIT = "drop_commit"
    TRANSPORT_UNJAM = "transport_unjam"


@dataclass(slots=True)
class _PieceDossier:
    piece_uuid: str
    global_id: int | None
    tracklet_id: str | None
    feed_id: str
    tracker_key: str
    tracker_epoch: str
    raw_track_id: int | None
    intake_ts: float
    angle_at_intake_deg: float
    last_seen_mono: float
    classified_ts: float | None = None
    classify_future: "Future[ClassifierResult] | None" = None
    result: ClassifierResult | None = None
    reject_reason: str | None = None
    handoff_requested: bool = False
    distributor_ready: bool = False
    eject_enqueued: bool = False
    eject_committed: bool = False
    appearance_embedding: tuple[float, ...] | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    # Monotonic timestamp of the last distributor_busy rejection; blocks
    # repeat ``handoff_request`` attempts for ``_handoff_retry_cooldown_s``
    # so we don't spam the distributor at tick rate (10 Hz). Measured on
    # live hardware: pre-backoff was 5 accepted vs 185 distributor_busy.
    last_handoff_attempt_at: float = 0.0


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
        transport_move_command: Callable[[float], bool] | None = None,
        sample_transport_move_command: Callable[[float, int | None, int | None], bool] | None = None,
        startup_purge_move_command: Callable[[float], bool] | None = None,
        wiggle_move_command: Callable[[float], bool] | None = None,
        unjam_move_command: Callable[[float], bool] | None = None,
        startup_purge_mode_command: Callable[[bool], bool] | None = None,
        eject_command: Callable[[], bool] | None = None,
        crop_provider: Callable[[FeedFrame, Track], Any] | None = None,
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        event_bus: EventBus | None = None,
        track_transit: TrackTransitRegistry | None = None,
        runtime_id: str = "c4",
        feed_id: str = "c4_feed",
        tracker_key: str | None = None,
        tracker_epoch: str | None = None,
        classify_angle_deg: float = DEFAULT_CLASSIFY_ANGLE_DEG,
        classify_pretrigger_exit_lead_deg: float = DEFAULT_CLASSIFY_PRETRIGGER_EXIT_LEAD_DEG,
        exit_angle_deg: float = DEFAULT_EXIT_ANGLE_DEG,
        angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
        intake_half_width_deg: float = DEFAULT_INTAKE_HALF_WIDTH_DEG,
        shimmy_step_deg: float = DEFAULT_SHIMMY_STEP_DEG,
        shimmy_stall_ms: int = DEFAULT_SHIMMY_STALL_MS,
        shimmy_cooldown_ms: int = DEFAULT_SHIMMY_COOLDOWN_MS,
        post_commit_cooldown_ms: int | None = None,
        transport_step_deg: float = DEFAULT_TRANSPORT_STEP_DEG,
        transport_max_step_deg: float = DEFAULT_TRANSPORT_MAX_STEP_DEG,
        transport_target_rpm: float = DEFAULT_TRANSPORT_TARGET_RPM,
        transport_cooldown_ms: int = DEFAULT_TRANSPORT_COOLDOWN_MS,
        exit_approach_angle_deg: float = DEFAULT_EXIT_APPROACH_ANGLE_DEG,
        exit_approach_step_deg: float = DEFAULT_EXIT_APPROACH_STEP_DEG,
        exit_bbox_overlap_ratio: float = DEFAULT_EXIT_BBOX_OVERLAP_RATIO,
        exit_trailing_safety_deg: float = DEFAULT_EXIT_TRAILING_SAFETY_DEG,
        track_stale_s: float = DEFAULT_TRACK_STALE_S,
        reconcile_min_hit_count: int = DEFAULT_RECOVER_MIN_HIT_COUNT,
        reconcile_min_score: float = DEFAULT_RECOVER_MIN_SCORE,
        reconcile_min_age_s: float = DEFAULT_RECOVER_MIN_AGE_S,
        idle_jog_enabled: bool = True,
        idle_jog_step_deg: float = DEFAULT_IDLE_JOG_STEP_DEG,
        idle_jog_cooldown_ms: int = DEFAULT_IDLE_JOG_COOLDOWN_MS,
        unjam_enabled: bool = True,
        unjam_stall_ms: int = DEFAULT_UNJAM_STALL_MS,
        unjam_min_progress_deg: float = DEFAULT_UNJAM_MIN_PROGRESS_DEG,
        unjam_cooldown_ms: int = DEFAULT_UNJAM_COOLDOWN_MS,
        unjam_reverse_deg: float = DEFAULT_UNJAM_REVERSE_DEG,
        unjam_forward_deg: float = DEFAULT_UNJAM_FORWARD_DEG,
        state_observer: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(
            runtime_id,
            feed_id=feed_id,
            logger=logger,
            hw_worker=hw_worker,
            state_observer=state_observer,
        )
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
        # Wrap carousel move commands so every motor-commanded rotation
        # automatically publishes a PERCEPTION_ROTATION window — the tracker
        # uses this to decide if a stationary track is a ghost or just
        # pre-rotation. Start/end timestamps are wall-clock (matches
        # FeedFrame.timestamp), plus a short pad on each side.
        _raw_carousel_move = carousel_move_command or (lambda _deg: True)
        _raw_transport_move = transport_move_command or _raw_carousel_move
        _raw_sample_transport_move = sample_transport_move_command or _raw_transport_move
        _raw_startup_purge_move = startup_purge_move_command or _raw_carousel_move
        _raw_wiggle_move = wiggle_move_command or _raw_carousel_move
        _raw_unjam_move = unjam_move_command or _raw_carousel_move
        self._carousel_move = self._wrap_rotation_command(
            _raw_carousel_move, "c4_carousel"
        )
        self._transport_move = self._wrap_rotation_command(
            _raw_transport_move, "c4_transport"
        )
        self._sample_transport_move = self._wrap_direct_rotation_command(
            _raw_sample_transport_move, "c4_sample_transport"
        )
        self._startup_purge_move = self._wrap_rotation_command(
            _raw_startup_purge_move, "c4_startup_purge"
        )
        self._wiggle_move = self._wrap_rotation_command(
            _raw_wiggle_move, "c4_wiggle"
        )
        self._unjam_move = self._wrap_rotation_command(
            _raw_unjam_move, "c4_unjam"
        )
        self._startup_purge_mode = startup_purge_mode_command or (lambda _enabled: True)
        self._eject = eject_command or (lambda: True)
        self._crop_provider = crop_provider
        self._classify_angle_deg = float(classify_angle_deg)
        self._classify_pretrigger_exit_lead_deg = max(
            0.0,
            float(classify_pretrigger_exit_lead_deg),
        )
        self._exit_angle_deg = float(exit_angle_deg)
        self._angle_tol_deg = float(angle_tolerance_deg)
        self._intake_half_width_deg = float(intake_half_width_deg)
        self._shimmy_step_deg = float(shimmy_step_deg)
        self._shimmy_stall_s = float(shimmy_stall_ms) / 1000.0
        self._shimmy_cooldown_s = float(shimmy_cooldown_ms) / 1000.0
        self._transport_step_deg = float(transport_step_deg)
        self._transport_max_step_deg = max(
            self._transport_step_deg,
            float(transport_max_step_deg),
        )
        self._sample_transport_step_deg = self._transport_step_deg
        self._sample_transport_max_speed: int | None = None
        self._sample_transport_acceleration: int | None = None
        self._transport_cooldown_s = float(transport_cooldown_ms) / 1000.0
        self._exit_approach_angle_deg = max(0.0, float(exit_approach_angle_deg))
        self._exit_approach_step_deg = max(0.1, float(exit_approach_step_deg))
        self._exit_bbox_overlap_ratio = max(
            0.0,
            min(1.0, float(exit_bbox_overlap_ratio)),
        )
        self._exit_trailing_safety_deg = max(0.0, float(exit_trailing_safety_deg))
        self._track_stale_s = max(0.0, float(track_stale_s))
        self._reconcile_min_hit_count = max(1, int(reconcile_min_hit_count))
        self._reconcile_min_score = float(reconcile_min_score)
        self._reconcile_min_age_s = max(0.0, float(reconcile_min_age_s))
        self._idle_jog_enabled = bool(idle_jog_enabled)
        self._idle_jog_step_deg = max(0.1, float(idle_jog_step_deg))
        self._idle_jog_cooldown_s = max(0.1, float(idle_jog_cooldown_ms) / 1000.0)
        self._unjam_enabled = bool(unjam_enabled)
        self._unjam_stall_s = max(0.25, float(unjam_stall_ms) / 1000.0)
        self._unjam_min_progress_deg = max(0.1, float(unjam_min_progress_deg))
        self._unjam_cooldown_s = max(0.5, float(unjam_cooldown_ms) / 1000.0)
        self._unjam_reverse_deg = max(0.1, float(unjam_reverse_deg))
        self._unjam_forward_deg = max(0.1, float(unjam_forward_deg))
        self._transport_velocity = TransportVelocityObserver(
            channel="c4",
            exit_angle_deg=self._exit_angle_deg,
            target_rpm=transport_target_rpm,
        )
        # Per-dossier cooldown after a distributor_busy rejection. 250 ms is
        # comfortably above the distributor's chute-move → ready cycle so we
        # don't starve handoffs, but small enough to keep throughput healthy.
        self._handoff_retry_cooldown_s = 0.25
        cooldown_ms = (
            self._ejection.timing_for({}).fall_time_ms
            if post_commit_cooldown_ms is None
            else float(post_commit_cooldown_ms)
        )
        self._post_commit_cooldown_s = cooldown_ms / 1000.0
        self._bus = event_bus
        self._track_transit = track_transit
        self._tracker_key = str(tracker_key or "unknown")
        self._tracker_epoch = (
            tracker_epoch.strip()
            if isinstance(tracker_epoch, str) and tracker_epoch.strip()
            else new_tracker_epoch()
        )
        self._handoff: HandoffPort | None = None
        self._pieces: dict[str, _PieceDossier] = {}
        self._track_to_piece: dict[int, str] = {}
        self._recently_delivered_piece_until: dict[str, float] = {}
        self._recently_delivered_track_until: dict[int, float] = {}
        self._fsm: _C4State = _C4State.RUNNING
        self._raw_detection_count: int = 0
        self._transit_link_count: int = 0
        self._latest_frame: FeedFrame | None = None
        self._classify_debug_counts: dict[str, int] = {}
        self._last_classify_skip: str | None = None
        self._handoff_debug_counts: dict[str, int] = {}
        self._last_handoff_skip: str | None = None
        self._exit_stall_since: float | None = None
        self._next_shimmy_at: float = 0.0
        self._next_accept_at: float = 0.0
        self._next_transport_at: float = 0.0
        self._next_idle_jog_at: float = 0.0
        self._idle_jog_count: int = 0
        self._last_idle_jog_at: float | None = None
        self._transport_progress_started_at: float | None = None
        self._transport_progress_baseline: dict[int, float] = {}
        self._last_transport_progress_deg: float | None = None
        self._next_unjam_at: float = 0.0
        self._last_unjam_at: float | None = None
        self._unjam_count: int = 0
        self._startup_purge_state = C4StartupPurgeState()
        self._handoff_diagnostics = HandoffDiagnostics(
            runtime_id=self.runtime_id,
            feed_id=self.feed_id,
            logger=self._logger,
        )

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

    def set_handoff_port(self, port: HandoffPort | None) -> None:
        """Bind the downstream handoff surface (typically the distributor)."""
        self._handoff = port

    def set_tracker_identity(
        self,
        *,
        tracker_key: str | None,
        tracker_epoch: str | None,
    ) -> None:
        """Attach the currently active perception-runner tracker identity."""

        if isinstance(tracker_key, str) and tracker_key.strip():
            self._tracker_key = tracker_key.strip()
        if isinstance(tracker_epoch, str) and tracker_epoch.strip():
            self._tracker_epoch = tracker_epoch.strip()

    def on_distributor_ready(self, piece_uuid: str) -> None:
        """Distributor positioned the chute; the next exit tick may eject."""
        dossier = self._pieces.get(piece_uuid)
        if dossier is None:
            self._logger.warning(
                "RuntimeC4: distributor ready for unknown piece=%s",
                piece_uuid,
            )
            return
        dossier.distributor_ready = True

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
        abort_handoff: bool = False,
        abort_reason: str = "handoff_aborted",
    ) -> None:
        dossier = self._pieces.pop(piece_uuid, None)
        if dossier is not None and arm_cooldown and now_mono is not None:
            self._remember_delivered_piece(dossier, now_mono)
        if dossier is not None and abort_reason == "track_lost":
            self._park_lost_piece_transit(dossier, now_mono=now_mono)
            self._publish_piece_lost(dossier, now_mono=now_mono)
        if dossier is not None:
            self._track_to_piece = {
                gid: mapped_piece_uuid
                for gid, mapped_piece_uuid in self._track_to_piece.items()
                if mapped_piece_uuid != dossier.piece_uuid
            }
        self._zone_manager.remove_zone(piece_uuid)
        if abort_handoff and dossier is not None and dossier.handoff_requested:
            port = self._handoff
            if port is not None:
                ts = time.monotonic() if now_mono is None else now_mono
                try:
                    port.handoff_abort(
                        piece_uuid,
                        reason=abort_reason,
                        now_mono=ts,
                    )
                except Exception:
                    self._logger.exception(
                        "RuntimeC4: distributor handoff_abort raised for piece=%s",
                        piece_uuid,
                    )
        self._downstream_slot.release()
        if arm_cooldown and now_mono is not None:
            self._next_accept_at = now_mono + self._post_commit_cooldown_s
        if self._fsm is _C4State.DROP_COMMIT:
            self._fsm = _C4State.RUNNING
            self._set_state(self._fsm.value)

    def _publish_piece_lost(
        self,
        dossier: _PieceDossier,
        *,
        now_mono: float | None,
    ) -> None:
        status = "pending"
        if dossier.result is not None:
            status = "classified" if dossier.result.part_id else "unknown"
        now_wall = time.time()
        last_angle_deg = self._dossier_last_angle_deg(dossier)
        self._publish(
            PIECE_REGISTERED,
            {
                "piece_uuid": dossier.piece_uuid,
                "tracked_global_id": dossier.global_id,
                **self._dossier_tracklet_payload(dossier),
                "stage": "registered",
                "classification_status": status,
                "classification_channel_zone_state": "lost",
                "classification_channel_zone_center_deg": last_angle_deg,
                "classification_channel_lost_at": now_wall,
                "updated_at": now_wall,
                "dossier": {
                    "piece_uuid": dossier.piece_uuid,
                    "tracked_global_id": dossier.global_id,
                    **self._dossier_tracklet_payload(dossier),
                    "classification_channel_zone_state": "lost",
                    "classification_channel_lost_at": now_wall,
                    "classification_channel_zone_center_deg": last_angle_deg,
                    "classification_channel_exit_deg": self._exit_angle_deg,
                },
            },
            now_mono if now_mono is not None else time.monotonic(),
        )

    def _park_lost_piece_transit(
        self,
        dossier: _PieceDossier,
        *,
        now_mono: float | None,
    ) -> None:
        registry = self._track_transit
        if registry is None:
            return
        now = time.monotonic() if now_mono is None else float(now_mono)
        zone = self._zone_manager.zone_for(dossier.piece_uuid)
        source_angle_deg = (
            float(zone.center_deg)
            if zone is not None
            else self._dossier_last_angle_deg(dossier)
        )
        registry.begin(
            source_runtime=self.runtime_id,
            source_feed=self.feed_id,
            source_global_id=dossier.global_id,
            target_runtime=self.runtime_id,
            now_mono=now,
            ttl_s=DEFAULT_TRACKLET_TRANSIT_TTL_S,
            piece_uuid=dossier.piece_uuid,
            source_angle_deg=source_angle_deg,
            relation="track_split",
            payload={
                "previous_tracked_global_id": dossier.global_id,
                "previous_tracklet_id": dossier.tracklet_id,
                **self._dossier_tracklet_payload(dossier),
                "dossier_result": dossier.result,
                "classified_ts": dossier.classified_ts,
                "reject_reason": dossier.reject_reason,
                "extras": dict(dossier.extras),
            },
            source_embedding=dossier.appearance_embedding,
        )

    def dossier_count(self) -> int:
        return len(self._pieces)

    def dossier_for(self, piece_uuid: str) -> _PieceDossier | None:
        return self._pieces.get(piece_uuid)

    def fsm_state(self) -> str:
        return self._fsm.value

    def debug_snapshot(self) -> dict[str, Any]:
        """Compact live snapshot for operator diagnostics and API status."""
        frame_raw = getattr(self._latest_frame, "raw", None)
        frame_shape = list(frame_raw.shape[:2]) if hasattr(frame_raw, "shape") else None
        dossier_preview: list[dict[str, Any]] = []
        for dossier in list(self._pieces.values())[:5]:
            zone = self._zone_manager.zone_for(dossier.piece_uuid)
            angle = float(zone.center_deg) if zone is not None else None
            dossier_preview.append(
                {
                    "piece_uuid": dossier.piece_uuid,
                    "global_id": dossier.global_id,
                    "tracklet_id": dossier.tracklet_id,
                    "tracker_key": dossier.tracker_key,
                    "tracker_epoch": dossier.tracker_epoch,
                    "angle_deg": angle,
                    "classify_delta_deg": (
                        _wrap_deg(angle - self._classify_angle_deg)
                        if angle is not None
                        else None
                    ),
                    "exit_delta_deg": (
                        _wrap_deg(angle - self._exit_angle_deg)
                        if angle is not None
                        else None
                    ),
                    "has_result": dossier.result is not None,
                    "future_pending": dossier.classify_future is not None,
                    "handoff_requested": dossier.handoff_requested,
                    "distributor_ready": dossier.distributor_ready,
                    "eject_enqueued": dossier.eject_enqueued,
                    "eject_committed": dossier.eject_committed,
                    "recovered": bool(dossier.extras.get("recovered")),
                }
            )
        admission_state = self._admission_state_snapshot()
        admission_decision = self._admission.can_admit(
            inbound_piece_hint={},
            runtime_state=admission_state,
        )
        return {
            "fsm_state": self._fsm.value,
            "startup_purge_armed": bool(self._startup_purge_state.armed),
            "startup_purge_prime_moves": int(self._startup_purge_state.prime_moves),
            "startup_purge_commit_piece_uuid": self._startup_purge_state.commit_piece_uuid,
            "raw_detection_count": int(self._raw_detection_count),
            "transit_link_count": int(self._transit_link_count),
            "tracker_identity": {
                "feed_id": self.feed_id,
                "tracker_key": self._tracker_key,
                "tracker_epoch": self._tracker_epoch,
            },
            "transit_candidates": (
                self._track_transit.snapshot(time.monotonic())
                if self._track_transit is not None
                else []
            ),
            "dossier_count": len(self._pieces),
            "track_to_piece_count": len(self._track_to_piece),
            "zone_count": self._zone_manager.zone_count(),
            "recently_delivered_suppressed": {
                "pieces": len(self._recently_delivered_piece_until),
                "tracks": len(self._recently_delivered_track_until),
            },
            "admission_debug": {
                "allowed": bool(admission_decision.allowed),
                "reason": admission_decision.reason,
                "state": admission_state,
            },
            "hw_busy": bool(self._hw.busy()),
            "hw_pending": int(self._hw.pending()),
            "angles": {
                "intake_deg": self._zone_manager.intake_angle_deg,
                "classify_deg": self._classify_angle_deg,
                "classify_pretrigger_exit_lead_deg": self._classify_pretrigger_exit_lead_deg,
                "exit_deg": self._exit_angle_deg,
                "drop_deg": self._zone_manager.drop_angle_deg,
                "tolerance_deg": self._angle_tol_deg,
            },
            "latest_frame": {
                "present": self._latest_frame is not None,
                "raw_shape_hw": frame_shape,
                "frame_seq": getattr(self._latest_frame, "frame_seq", None),
            },
            "classify_debug": {
                "counts": dict(sorted(self._classify_debug_counts.items())),
                "last_skip": self._last_classify_skip,
            },
            "handoff_debug": {
                "port_wired": self._handoff is not None,
                "counts": dict(sorted(self._handoff_debug_counts.items())),
                "last_skip": self._last_handoff_skip,
            },
            "idle_jog": {
                "enabled": bool(self._idle_jog_enabled),
                "step_deg": float(self._idle_jog_step_deg),
                "cooldown_s": float(self._idle_jog_cooldown_s),
                "next_at_mono": float(self._next_idle_jog_at),
                "last_at_mono": self._last_idle_jog_at,
                "count": int(self._idle_jog_count),
            },
            "transport_velocity": self._transport_velocity.snapshot.as_dict(),
            "handoff_burst_diagnostics": self._handoff_diagnostics.snapshot(),
            "transport_unjam": {
                "enabled": bool(self._unjam_enabled),
                "stall_s": float(self._unjam_stall_s),
                "min_progress_deg": float(self._unjam_min_progress_deg),
                "cooldown_s": float(self._unjam_cooldown_s),
                "reverse_deg": float(self._unjam_reverse_deg),
                "forward_deg": float(self._unjam_forward_deg),
                "watch_started_at_mono": self._transport_progress_started_at,
                "last_progress_deg": self._last_transport_progress_deg,
                "next_at_mono": float(self._next_unjam_at),
                "last_at_mono": self._last_unjam_at,
                "count": int(self._unjam_count),
            },
            "dossier_preview": dossier_preview,
        }

    def inspect_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        """Step-debugger view: full dossier list with every per-piece field.

        ``debug_snapshot`` caps at five dossiers because the live dashboard
        polls it. The step debugger needs the complete picture so an
        operator can see exactly which piece is stuck where without
        spelunking private fields.
        """
        ts = time.monotonic() if now_mono is None else float(now_mono)
        dossiers: list[dict[str, Any]] = []
        for dossier in self._pieces.values():
            zone = self._zone_manager.zone_for(dossier.piece_uuid)
            angle = float(zone.center_deg) if zone is not None else None
            result = dossier.result
            dossiers.append(
                {
                    "piece_uuid": dossier.piece_uuid,
                    "global_id": dossier.global_id,
                    "tracklet_id": dossier.tracklet_id,
                    "tracker_key": dossier.tracker_key,
                    "tracker_epoch": dossier.tracker_epoch,
                    "raw_track_id": dossier.raw_track_id,
                    "intake_age_s": ts - dossier.intake_ts,
                    "angle_at_intake_deg": dossier.angle_at_intake_deg,
                    "angle_deg": angle,
                    "classify_delta_deg": (
                        _wrap_deg(angle - self._classify_angle_deg)
                        if angle is not None
                        else None
                    ),
                    "exit_delta_deg": (
                        _wrap_deg(angle - self._exit_angle_deg)
                        if angle is not None
                        else None
                    ),
                    "last_seen_age_s": ts - dossier.last_seen_mono,
                    "classified_age_s": (
                        ts - dossier.classified_ts
                        if dossier.classified_ts is not None
                        else None
                    ),
                    "classify_future_pending": dossier.classify_future is not None,
                    "result_part_id": getattr(result, "part_id", None) if result else None,
                    "result_category": (
                        getattr(result, "category", None) if result else None
                    ),
                    "reject_reason": dossier.reject_reason,
                    "handoff_requested": bool(dossier.handoff_requested),
                    "distributor_ready": bool(dossier.distributor_ready),
                    "eject_enqueued": bool(dossier.eject_enqueued),
                    "eject_committed": bool(dossier.eject_committed),
                    "last_handoff_attempt_age_s": (
                        ts - dossier.last_handoff_attempt_at
                        if dossier.last_handoff_attempt_at
                        else None
                    ),
                    "extras": dict(dossier.extras),
                }
            )
        # Sort by exit_delta closest-to-exit first so the operator reads the
        # next-to-eject candidate at the top.
        dossiers.sort(
            key=lambda d: (
                d.get("exit_delta_deg") is None,
                abs(d.get("exit_delta_deg") or 1e9),
            )
        )
        return {
            "fsm_state": self._fsm.value,
            "dossier_count": len(self._pieces),
            "dossiers": dossiers,
            "track_to_piece": dict(self._track_to_piece),
            "next_accept_in_s": max(0.0, self._next_accept_at - ts),
            "angles": {
                "intake_deg": self._zone_manager.intake_angle_deg,
                "classify_deg": self._classify_angle_deg,
                "exit_deg": self._exit_angle_deg,
                "drop_deg": self._zone_manager.drop_angle_deg,
            },
        }

    def arm_startup_purge(self) -> None:
        strategy = self._startup_purge
        if strategy is None or not strategy.enabled:
            self._startup_purge_state.armed = False
            return
        self._startup_purge_state.arm()

    @property
    def startup_purge_armed(self) -> bool:
        """Public read of the startup-purge arm flag (introspection hook)."""
        return self._startup_purge_state.armed

    def purge_port(self) -> PurgePort:
        return _C4PurgePort(self)

    def sample_transport_port(self) -> "_C4SampleTransportPort":
        return _C4SampleTransportPort(self)

    def _tick_inner(self, inbox: RuntimeInbox, now_mono: float) -> None:
        self._sweep_recently_delivered(now_mono)
        raw_tracks = self._fresh_tracks(inbox.tracks)
        visible_tracks = [t for t in raw_tracks if is_visible_track(t)]
        self._raw_detection_count = len(visible_tracks)
        owned_tracks = self._sync_owned_tracks(visible_tracks, now_mono)
        if self._run_startup_purge(visible_tracks, owned_tracks, now_mono):
            return
        intake_candidates = [
            t
            for t in visible_tracks
            if action_track(t, min_hits=self._reconcile_min_hit_count)
        ]
        self._admit_new_tracks(intake_candidates, now_mono)
        if now_mono >= self._next_accept_at:
            self._reconcile_visible_tracks(visible_tracks, now_mono)
        owned_tracks = self._owned_tracks(visible_tracks)
        self._transport_velocity.update(
            owned_tracks,
            now_mono=now_mono,
            base_step_deg=self._transport_step_deg,
            max_step_deg=self._transport_max_step_deg,
            exit_slow_zone_deg=self._exit_approach_angle_deg,
        )
        self._submit_classifications(owned_tracks, now_mono)
        self._poll_classifier_futures(now_mono)
        self._request_pending_handoffs(now_mono)
        self._handle_exit(owned_tracks, inbox, now_mono)
        unjam_active = self._maybe_unjam_transport(owned_tracks, now_mono)
        transport_active = False
        if not unjam_active:
            transport_active = self._maybe_advance_transport(owned_tracks, now_mono)
        idle_jog_active = False
        if not transport_active and not unjam_active:
            idle_jog_active = self._maybe_idle_jog(now_mono)
        self._refresh_fsm_label(
            transport_active=transport_active,
            idle_jog_active=idle_jog_active,
            unjam_active=unjam_active,
        )

    # -- Helpers ------------------------------------------------------

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
        return bool(
            strategy is not None
            and strategy.enabled
            and self._startup_purge_state.armed
        )

    def _enter_startup_purge(self) -> None:
        state = self._startup_purge_state
        if not state.mode_active:
            try:
                state.mode_active = bool(self._startup_purge_mode(True))
            except Exception:
                self._logger.exception("RuntimeC4: enabling startup purge mode raised")
        self._fsm = _C4State.STARTUP_PURGE

    def _exit_startup_purge(self) -> None:
        state = self._startup_purge_state
        if state.mode_active:
            try:
                self._startup_purge_mode(False)
            except Exception:
                self._logger.exception("RuntimeC4: disabling startup purge mode raised")
            state.mode_active = False
        self._fsm = _C4State.RUNNING

    def _owned_tracks(self, tracks: list[Track]) -> list[Track]:
        return [t for t in tracks if self._piece_uuid_for_track(t) is not None]

    def _sync_owned_tracks(self, tracks: list[Track], now_mono: float) -> list[Track]:
        extents: list[TrackAngularExtent] = []
        for track in tracks:
            if track.global_id is None:
                continue
            piece_uuid = self._piece_uuid_for_track(track)
            if piece_uuid is None:
                continue
            dossier = self._pieces.get(piece_uuid)
            angle_deg = math.degrees(track.angle_rad or 0.0)
            if dossier is not None:
                dossier.last_seen_mono = now_mono
                dossier.extras["last_angle_deg"] = angle_deg
                if track.appearance_embedding is not None:
                    dossier.appearance_embedding = track.appearance_embedding
            extents.append(
                TrackAngularExtent(
                    piece_uuid=piece_uuid,
                    global_id=track.global_id,
                    center_deg=angle_deg,
                    half_width_deg=self._intake_half_width_deg,
                    last_seen_mono=now_mono,
                )
            )
        evicted = self._zone_manager.update_from_tracks(extents, now_mono=now_mono)
        for piece_uuid in evicted:
            if piece_uuid in self._pieces:
                self._logger.info(
                    "RuntimeC4: pruning dossier piece=%s (zone evicted, track_lost)",
                    piece_uuid,
                )
                self._finalize_piece(
                    piece_uuid,
                    now_mono=now_mono,
                    arm_cooldown=False,
                    abort_handoff=True,
                    abort_reason="track_lost",
                )
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
            self._startup_purge_state,
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
            if self._piece_uuid_for_track(track) is not None:
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
        # Restart/re-home recovery: rebuild ownership from stable visible
        # tracks so the runtime can continue. This must be partial, not just
        # empty-tray only: after a restart/recovery one already-owned piece
        # must not prevent the rest of the visible C4 queue from becoming
        # operator-visible dossiers.
        if self._zone_manager.zone_count() >= self._zone_manager.max_zones:
            return
        candidates: list[Track] = []
        for track in tracks:
            if track.global_id is None or track.angle_rad is None:
                continue
            gid = int(track.global_id)
            if self._piece_uuid_for_track(track) is not None:
                continue
            if not action_track(
                track,
                min_hits=self._reconcile_min_hit_count,
                min_score=self._reconcile_min_score,
            ):
                continue
            track_age_s = max(0.0, float(track.last_seen_ts) - float(track.first_seen_ts))
            if track_age_s < self._reconcile_min_age_s and not bool(track.confirmed_real):
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
        if self._is_recently_delivered_track(track, now_mono):
            return False
        gid = int(track.global_id)
        if self._piece_uuid_for_track(track) is not None:
            return False
        angle_deg = math.degrees(track.angle_rad)
        tracklet = self._tracklet_payload_for_gid(gid)
        transit = self._claim_transit_for_track(
            track,
            now_mono=now_mono,
            allow_cross_channel=(
                not recovered
                or self._should_claim_recovered_cross_channel(now_mono)
            ),
        )
        piece_uuid = (
            transit.piece_uuid
            if transit and transit.piece_uuid
            else (
                track.piece_uuid
                if isinstance(track.piece_uuid, str) and track.piece_uuid.strip()
                else new_piece_uuid()
            )
        )
        if self._recently_delivered_piece_until.get(piece_uuid, 0.0) > now_mono:
            return False
        if not self._zone_manager.add_zone(
            piece_uuid=piece_uuid,
            angle_deg=angle_deg,
            half_width_deg=self._intake_half_width_deg,
            global_id=gid,
            now_mono=now_mono,
        ):
            return False
        extras = self._extras_for_registration(
            track,
            recovered=recovered,
            transit=transit,
        )
        result = self._result_from_transit(transit)
        classified_ts = self._classified_ts_from_transit(transit)
        reject_reason = self._reject_reason_from_transit(transit)
        dossier = _PieceDossier(
            piece_uuid=piece_uuid,
            global_id=gid,
            tracklet_id=(
                str(tracklet["tracklet_id"])
                if isinstance(tracklet.get("tracklet_id"), str)
                else None
            ),
            feed_id=str(tracklet.get("feed_id") or self.feed_id),
            tracker_key=str(tracklet.get("tracker_key") or self._tracker_key),
            tracker_epoch=str(tracklet.get("tracker_epoch") or self._tracker_epoch),
            raw_track_id=gid,
            intake_ts=now_mono,
            angle_at_intake_deg=angle_deg,
            last_seen_mono=now_mono,
            classified_ts=classified_ts,
            result=result,
            reject_reason=reject_reason,
            appearance_embedding=track.appearance_embedding,
            extras=extras,
        )
        self._pieces[piece_uuid] = dossier
        self._track_to_piece[gid] = piece_uuid
        release_upstream_now = bool(release_upstream)
        if (
            not release_upstream_now
            and recovered
            and transit is not None
            and transit.relation == "cross_channel"
            and transit.source_runtime == "c3"
        ):
            release_upstream_now = True
        if release_upstream_now:
            self._upstream_slot.release()
        self._record_dropzone_arrival(
            track=track,
            dossier=dossier,
            now_mono=now_mono,
            release_upstream=release_upstream_now,
            recovered=recovered,
        )
        result_payload = self._classification_payload(result)
        classification_status = (
            "classified" if result is not None and result.part_id else "pending"
        )
        transit_payload = self._transit_payload(transit)
        self._publish(
            PIECE_REGISTERED,
            {
                "piece_uuid": piece_uuid,
                "tracked_global_id": gid,
                "current_tracklet_id": tracklet.get("tracklet_id"),
                **tracklet,
                "angle_at_intake_deg": angle_deg,
                "intake_ts_mono": now_mono,
                "confirmed_real": True,
                "stage": "registered",
                "classification_status": classification_status,
                "classification_channel_zone_state": "active",
                "recovered": recovered,
                "admission_basis": dossier.extras.get("admission_basis"),
                **transit_payload,
                "dossier": {
                    "piece_uuid": piece_uuid,
                    "tracked_global_id": gid,
                    "current_tracklet_id": tracklet.get("tracklet_id"),
                    **tracklet,
                    "classification_channel_zone_state": "active",
                    "classification_channel_zone_center_deg": angle_deg,
                    "classification_channel_exit_deg": self._exit_angle_deg,
                    "first_carousel_seen_ts": now_mono,
                    "recovered": recovered,
                    "admission_basis": dossier.extras.get("admission_basis"),
                    **result_payload,
                    **transit_payload,
                },
            },
            now_mono,
        )
        if transit is not None:
            self._publish_transit_link(piece_uuid, gid, transit, now_mono=now_mono)
        return True

    def _remember_delivered_piece(
        self,
        dossier: _PieceDossier,
        now_mono: float,
    ) -> None:
        until = float(now_mono) + DEFAULT_DELIVERED_TRACK_SUPPRESS_S
        self._recently_delivered_piece_until[dossier.piece_uuid] = until
        if dossier.raw_track_id is not None:
            self._recently_delivered_track_until[int(dossier.raw_track_id)] = until
        elif dossier.global_id is not None:
            self._recently_delivered_track_until[int(dossier.global_id)] = until

    def _is_recently_delivered_track(self, track: Track, now_mono: float) -> bool:
        piece_uuid = track.piece_uuid
        if (
            isinstance(piece_uuid, str)
            and self._recently_delivered_piece_until.get(piece_uuid, 0.0)
            > now_mono
        ):
            return True
        if track.global_id is None:
            return False
        try:
            gid = int(track.global_id)
        except (TypeError, ValueError):
            return False
        return self._recently_delivered_track_until.get(gid, 0.0) > now_mono

    def _sweep_recently_delivered(self, now_mono: float) -> None:
        self._recently_delivered_piece_until = {
            piece_uuid: until
            for piece_uuid, until in self._recently_delivered_piece_until.items()
            if until > now_mono
        }
        self._recently_delivered_track_until = {
            global_id: until
            for global_id, until in self._recently_delivered_track_until.items()
            if until > now_mono
        }

    def _tracklet_payload_for_gid(self, gid: int) -> dict[str, Any]:
        return tracklet_payload(
            feed_id=self.feed_id or "c4_feed",
            tracker_key=self._tracker_key,
            tracker_epoch=self._tracker_epoch,
            raw_track_id=int(gid),
        )

    def _dossier_tracklet_payload(self, dossier: _PieceDossier) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "feed_id": dossier.feed_id,
            "tracker_key": dossier.tracker_key,
            "tracker_epoch": dossier.tracker_epoch,
            "raw_track_id": dossier.raw_track_id,
        }
        if dossier.tracklet_id:
            payload["tracklet_id"] = dossier.tracklet_id
            payload["current_tracklet_id"] = dossier.tracklet_id
        return payload

    def _dossier_last_angle_deg(self, dossier: _PieceDossier) -> float:
        value = dossier.extras.get("last_angle_deg")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        return float(dossier.angle_at_intake_deg)

    def _claim_transit_for_track(
        self,
        track: Track,
        *,
        now_mono: float,
        allow_cross_channel: bool,
    ) -> TransitCandidate | None:
        registry = self._track_transit
        if registry is None:
            return None
        allowed_relations = None if allow_cross_channel else ("track_split",)
        transit = registry.claim(
            target_runtime=self.runtime_id,
            track=track,
            now_mono=now_mono,
            max_age_s=8.0,
            allowed_relations=allowed_relations,
            relation_angle_limits_deg={
                "track_split": DEFAULT_TRACKLET_TRANSIT_MAX_ANGLE_DELTA_DEG,
            },
        )
        if transit is not None:
            self._transit_link_count += 1
        return transit

    def _should_claim_recovered_cross_channel(self, now_mono: float) -> bool:
        return self._upstream_slot.taken(now_mono=now_mono) > 0

    def _piece_uuid_for_track(self, track: Track) -> str | None:
        if track.global_id is not None:
            try:
                gid = int(track.global_id)
            except (TypeError, ValueError):
                gid = None
            else:
                piece_uuid = self._track_to_piece.get(gid)
                if piece_uuid in self._pieces:
                    return piece_uuid
        if isinstance(track.piece_uuid, str) and track.piece_uuid in self._pieces:
            if track.global_id is not None:
                try:
                    self._track_to_piece[int(track.global_id)] = track.piece_uuid
                except (TypeError, ValueError):
                    pass
            return track.piece_uuid
        return None

    def _extras_for_registration(
        self,
        track: Track,
        *,
        recovered: bool,
        transit: TransitCandidate | None,
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        if transit is not None and isinstance(transit.payload.get("extras"), dict):
            extras.update(transit.payload["extras"])
        extras.update(
            {
                "recovered": recovered,
                "admission_basis": admission_basis(
                    track,
                    min_hits=self._reconcile_min_hit_count,
                    min_score=self._reconcile_min_score,
                    min_age_s=self._reconcile_min_age_s if recovered else 0.0,
                ),
            }
        )
        if transit is not None:
            extras.update(self._transit_payload(transit))
        return extras

    def _result_from_transit(
        self,
        transit: TransitCandidate | None,
    ) -> ClassifierResult | None:
        if transit is None:
            return None
        result = transit.payload.get("dossier_result")
        return result if isinstance(result, ClassifierResult) else None

    def _classified_ts_from_transit(self, transit: TransitCandidate | None) -> float | None:
        if transit is None:
            return None
        value = transit.payload.get("classified_ts")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        return None

    def _reject_reason_from_transit(self, transit: TransitCandidate | None) -> str | None:
        if transit is None:
            return None
        value = transit.payload.get("reject_reason")
        return value if isinstance(value, str) and value.strip() else None

    def _transit_payload(self, transit: TransitCandidate | None) -> dict[str, Any]:
        if transit is None:
            return {}
        return {
            "track_stitched": True,
            "transit_id": transit.transit_id,
            "transit_relation": transit.relation,
            "transit_source_runtime": transit.source_runtime,
            "transit_source_feed": transit.source_feed,
            "transit_source_global_id": transit.source_global_id,
            "previous_tracked_global_id": transit.payload.get(
                "previous_tracked_global_id",
                transit.source_global_id,
            ),
            "previous_tracklet_id": transit.payload.get("previous_tracklet_id"),
        }

    def _classification_payload(
        self,
        result: ClassifierResult | None,
    ) -> dict[str, Any]:
        if result is None:
            return {}
        meta = result.meta if isinstance(result.meta, dict) else {}
        return {
            "part_id": result.part_id,
            "part_name": meta.get("name"),
            "color_id": result.color_id,
            "color_name": meta.get("color_name"),
            "part_category": result.category,
            "category": result.category,
            "confidence": result.confidence,
            "algorithm": result.algorithm,
            "latency_ms": result.latency_ms,
            "brickognize_preview_url": meta.get("preview_url") or meta.get("img_url"),
        }

    def _publish_transit_link(
        self,
        piece_uuid: str,
        tracked_global_id: int,
        transit: TransitCandidate,
        *,
        now_mono: float,
    ) -> None:
        self._publish(
            PIECE_TRANSIT_LINKED,
            {
                "piece_uuid": piece_uuid,
                "tracked_global_id": tracked_global_id,
                **self._tracklet_payload_for_gid(tracked_global_id),
                "stage": "registered",
                **self._transit_payload(transit),
            },
            now_mono,
        )

    def _submit_classifications(self, tracks: list[Track], now_mono: float) -> None:
        if self._latest_frame is None and self._crop_provider is None:
            # No crop source wired yet (Phase-5 wiring).
            self._mark_classify_skip("no_frame_or_crop_provider")
            return
        for track in tracks:
            if track.global_id is None:
                self._mark_classify_skip("track_without_global_id")
                continue
            piece_uuid = self._piece_uuid_for_track(track)
            if piece_uuid is None:
                self._mark_classify_skip("unowned_track")
                continue
            dossier = self._pieces.get(piece_uuid)
            if dossier is None:
                self._mark_classify_skip("missing_dossier")
                continue
            if dossier.result is not None or dossier.classify_future is not None:
                self._mark_classify_skip("already_classifying_or_classified")
                continue
            angle_deg = math.degrees(track.angle_rad or 0.0)
            at_classify = self._near_angle(angle_deg, self._classify_angle_deg)
            at_pretrigger = self._in_classify_pretrigger(angle_deg)
            at_exit = self._near_angle(angle_deg, self._exit_angle_deg)
            if not at_classify and not at_pretrigger and not at_exit:
                self._mark_classify_skip("not_at_classify_angle")
                continue
            crop = self._build_crop(track)
            if crop is None:
                self._mark_classify_skip("no_crop")
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
                self._mark_classify_skip("classify_async_raised")
                continue
            dossier.classify_future = future
            dossier.last_seen_mono = now_mono
            self._mark_classify_skip(
                "submitted"
                if at_classify
                else "submitted_early"
                if at_pretrigger
                else "submitted_late_exit"
            )

    def _in_classify_pretrigger(self, angle_deg: float) -> bool:
        lead_deg = float(self._classify_pretrigger_exit_lead_deg)
        if lead_deg <= 0.0:
            return False
        if self._near_angle(angle_deg, self._zone_manager.intake_angle_deg):
            return False
        intake_guard = (
            self._intake_half_width_deg
            + float(getattr(self._zone_manager, "guard_angle_deg", 0.0))
        )
        if abs(_wrap_deg(angle_deg - self._zone_manager.intake_angle_deg)) <= intake_guard:
            return False
        if self._near_angle(angle_deg, self._exit_angle_deg):
            return False
        return abs(_wrap_deg(angle_deg - self._exit_angle_deg)) <= lead_deg

    def _mark_classify_skip(self, reason: str) -> None:
        self._last_classify_skip = reason
        self._classify_debug_counts[reason] = self._classify_debug_counts.get(reason, 0) + 1

    def _mark_handoff(self, reason: str) -> None:
        self._last_handoff_skip = reason
        self._handoff_debug_counts[reason] = self._handoff_debug_counts.get(reason, 0) + 1

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
            result_meta = result.meta if result and isinstance(result.meta, dict) else {}
            payload: dict[str, Any] = {
                "piece_uuid": dossier.piece_uuid,
                "tracked_global_id": dossier.global_id,
                **self._dossier_tracklet_payload(dossier),
                "classified_ts_mono": now_mono,
                "confirmed_real": True,
                "stage": "classified",
                "classification_status": "classified"
                if result and result.part_id
                else "unknown",
                "classification_channel_zone_state": "active",
                "dossier": {
                    "piece_uuid": dossier.piece_uuid,
                    "tracked_global_id": dossier.global_id,
                    **self._dossier_tracklet_payload(dossier),
                    "classification_channel_zone_state": "active",
                    "part_id": result.part_id if result else None,
                    "part_name": result_meta.get("name"),
                    "color_id": result.color_id if result else None,
                    "color_name": result_meta.get("color_name"),
                    "part_category": result.category if result else None,
                    "category": result.category if result else None,
                    "confidence": result.confidence if result else None,
                    "algorithm": result.algorithm if result else None,
                    "latency_ms": result.latency_ms if result else None,
                    "brickognize_preview_url": result_meta.get("preview_url")
                    or result_meta.get("img_url"),
                    "classified_at": now_mono,
                },
            }
            self._publish(PIECE_CLASSIFIED, payload, now_mono)

    def _request_pending_handoffs(self, now_mono: float) -> None:
        if self._handoff is None:
            self._mark_handoff("request_not_wired")
            return
        dossier = self._next_handoff_candidate()
        if dossier is None:
            return
        self._request_distributor_handoff(dossier, now_mono)

    def _next_handoff_candidate(self) -> _PieceDossier | None:
        for dossier in self._dossiers_by_exit_distance():
            if dossier.handoff_requested:
                self._mark_handoff("front_already_requested")
                return None
            if dossier.result is None:
                self._mark_handoff("front_not_classified")
                return None
            return dossier
        return None

    def _dossiers_by_exit_distance(self) -> list[_PieceDossier]:
        dossiers = list(self._pieces.values())
        dossiers.sort(key=self._dossier_exit_distance)
        return dossiers

    def _dossier_exit_distance(self, dossier: _PieceDossier) -> float:
        zone = self._zone_manager.zone_for(dossier.piece_uuid)
        if zone is None:
            return 9999.0
        return abs(_wrap_deg(float(zone.center_deg) - self._exit_angle_deg))

    def _request_distributor_handoff(
        self,
        dossier: _PieceDossier,
        now_mono: float,
    ) -> bool:
        port = self._handoff
        result = dossier.result
        if port is None or result is None:
            self._mark_handoff("request_not_ready")
            return False
        if dossier.handoff_requested:
            self._mark_handoff("already_requested")
            return True
        # Backoff: after a distributor_busy rejection, wait before hitting
        # the port again so the distributor has time to complete its
        # chute-move → ready → eject cycle. Without this, C4 spams
        # handoff_request at tick rate and the busy counter explodes.
        if (
            dossier.last_handoff_attempt_at > 0.0
            and now_mono - dossier.last_handoff_attempt_at < self._handoff_retry_cooldown_s
        ):
            self._mark_handoff("retry_cooldown")
            return False
        # Cheap, non-blocking probe: if the distributor has no free slot
        # there's no point reserving the c4_to_distributor slot either.
        try:
            port_slots = int(port.available_slots())
        except Exception:
            port_slots = 1  # assume capacity; the full request path will reject if busy
        if port_slots <= 0:
            dossier.last_handoff_attempt_at = now_mono
            self._mark_handoff("distributor_busy")
            return False
        if not self._downstream_slot.try_claim(now_mono=now_mono, hold_time_s=15.0):
            self._set_state("drop_commit", blocked_reason="downstream_full")
            self._mark_handoff("downstream_full")
            return False
        try:
            accepted = bool(
                port.handoff_request(
                    piece_uuid=dossier.piece_uuid,
                    classification=result,
                    dossier=self._handoff_dossier_payload(dossier),
                    now_mono=now_mono,
                )
            )
        except Exception:
            self._downstream_slot.release()
            self._logger.exception(
                "RuntimeC4: distributor handoff_request raised for piece=%s",
                dossier.piece_uuid,
            )
            self._mark_handoff("callback_raised")
            return False
        if not accepted:
            self._downstream_slot.release()
            self._set_state("drop_commit", blocked_reason="distributor_busy")
            self._mark_handoff("distributor_busy")
            dossier.last_handoff_attempt_at = now_mono
            return False
        dossier.handoff_requested = True
        self._record_handoff_move(
            now_mono=now_mono,
            source="c4_distributor_handoff_request",
            step_deg=None,
            use_exit_approach=None,
            track_count=len(self._pieces),
            dossier=dossier,
        )
        self._mark_handoff("accepted")
        return True

    def _abort_non_front_handoffs(
        self,
        front_piece_uuid: str,
        now_mono: float,
    ) -> None:
        for dossier in list(self._pieces.values()):
            if dossier.piece_uuid == front_piece_uuid:
                continue
            if not dossier.handoff_requested:
                continue
            self._abort_handoff_only(
                dossier,
                now_mono=now_mono,
                reason="out_of_order_exit",
                front_piece_uuid=front_piece_uuid,
            )

    def _abort_handoff_only(
        self,
        dossier: _PieceDossier,
        *,
        now_mono: float,
        reason: str,
        front_piece_uuid: str | None = None,
    ) -> bool:
        if not dossier.handoff_requested:
            return False
        port = self._handoff
        if port is not None:
            try:
                port.handoff_abort(
                    dossier.piece_uuid,
                    reason=reason,
                    now_mono=now_mono,
                )
            except Exception:
                self._logger.exception(
                    "RuntimeC4: distributor handoff_abort raised for piece=%s",
                    dossier.piece_uuid,
                )
        self._downstream_slot.release()
        dossier.handoff_requested = False
        dossier.distributor_ready = False
        dossier.eject_enqueued = False
        dossier.eject_committed = False
        dossier.last_handoff_attempt_at = now_mono
        self._mark_handoff(f"aborted_{reason}")
        self._record_handoff_move(
            now_mono=now_mono,
            source=f"c4_handoff_abort_{reason}",
            step_deg=None,
            use_exit_approach=None,
            track_count=len(self._pieces),
            dossier=dossier,
            extra={"front_piece_uuid": front_piece_uuid},
        )
        self._logger.warning(
            "RuntimeC4: aborted distributor handoff for piece=%s reason=%s front=%s",
            dossier.piece_uuid,
            reason,
            front_piece_uuid,
        )
        return True

    def _handoff_dossier_payload(self, dossier: _PieceDossier) -> dict[str, Any]:
        result = dossier.result
        result_meta = result.meta if result and isinstance(result.meta, dict) else {}
        return {
            "piece_uuid": dossier.piece_uuid,
            "tracked_global_id": dossier.global_id,
            **self._dossier_tracklet_payload(dossier),
            "angle_at_intake_deg": dossier.angle_at_intake_deg,
            "intake_ts_mono": dossier.intake_ts,
            "classified_ts_mono": dossier.classified_ts,
            "part_id": result.part_id if result else None,
            "part_name": result_meta.get("name"),
            "color_id": result.color_id if result else None,
            "color_name": result_meta.get("color_name"),
            "part_category": result.category if result else None,
            "category": result.category if result else None,
            "confidence": result.confidence if result else None,
            "classification_channel_exit_deg": self._exit_angle_deg,
            "algorithm": result.algorithm if result else None,
            "brickognize_preview_url": result_meta.get("preview_url")
            or result_meta.get("img_url"),
            "classification_status": "classified"
            if result and result.part_id
            else "unknown",
            **dossier.extras,
        }

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

        piece_uuid = self._piece_uuid_for_track(exit_track)
        if piece_uuid is None:
            return
        dossier = self._pieces.get(piece_uuid)
        self._abort_non_front_handoffs(piece_uuid, now_mono)
        if dossier is None or dossier.result is None:
            if inbox.capacity_downstream <= 0:
                self._maybe_shimmy(now_mono)
            return
        if dossier.eject_enqueued:
            self._set_state("drop_commit", blocked_reason="eject_in_flight")
            return

        if self._handoff is not None:
            if not dossier.handoff_requested:
                self._request_distributor_handoff(dossier, now_mono)
                return
            if not dossier.distributor_ready:
                self._set_state("drop_commit", blocked_reason="waiting_distributor")
                return
            if self._hw.busy():
                self._set_state("drop_commit", blocked_reason="hw_busy")
                return
            if self._has_trailing_piece_within_safety(exit_track, tracks):
                # A second owned track is sitting close enough behind the
                # matched piece that the exit-release shimmy could nudge
                # both off the carousel into the bin positioned for the
                # matched piece's classification. Hold the eject; the next
                # tick will re-evaluate after transport advances.
                self._set_state("drop_commit", blocked_reason="trailing_piece_in_chute")
                return
            self._enqueue_eject(piece_uuid, claim_downstream=False)
            return

        if inbox.capacity_downstream <= 0:
            self._maybe_shimmy(now_mono)
            return
        if self._hw.busy():
            self._set_state("drop_commit", blocked_reason="hw_busy")
            return
        if not self._downstream_slot.try_claim(
            now_mono=now_mono, hold_time_s=5.0
        ):
            self._set_state("drop_commit", blocked_reason="downstream_full")
            return

        self._enqueue_eject(piece_uuid, claim_downstream=True)

    def _record_dropzone_arrival(
        self,
        *,
        track: Track,
        dossier: _PieceDossier,
        now_mono: float,
        release_upstream: bool,
        recovered: bool,
    ) -> None:
        if not release_upstream:
            return
        anomaly = self._handoff_diagnostics.record_arrivals(
            now_mono=now_mono,
            arrivals=[
                {
                    "piece_uuid": dossier.piece_uuid,
                    "global_id": dossier.global_id,
                    "track_id": track.track_id,
                    "angle_deg": self._track_angle_deg(track),
                    "release_upstream": bool(release_upstream),
                    "recovered": bool(recovered),
                    "transit_relation": dossier.extras.get("transit_relation"),
                    "transit_source_runtime": dossier.extras.get(
                        "transit_source_runtime"
                    ),
                    "score": float(track.score),
                    "hit_count": int(track.hit_count),
                    "confirmed_real": bool(track.confirmed_real),
                }
            ],
            context={
                "dossier_count": len(self._pieces),
                "zone_count": self._zone_manager.zone_count(),
                "raw_detection_count": self._raw_detection_count,
                "upstream_taken": self._upstream_slot.taken(),
                "downstream_taken": self._downstream_slot.taken(),
            },
        )
        if anomaly is not None:
            self._publish_handoff_burst(anomaly, now_mono)

    def _record_handoff_move(
        self,
        *,
        now_mono: float,
        source: str,
        step_deg: float | None,
        use_exit_approach: bool | None,
        track_count: int,
        dossier: _PieceDossier | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        front = self._dossiers_by_exit_distance()[0] if self._pieces else None
        payload: dict[str, Any] = {
            "source": source,
            "step_deg": step_deg,
            "use_exit_approach": use_exit_approach,
            "track_count": int(track_count),
            "dossier_count": len(self._pieces),
            "zone_count": self._zone_manager.zone_count(),
            "upstream_taken": int(self._upstream_slot.taken()),
            "downstream_taken": int(self._downstream_slot.taken()),
        }
        if front is not None:
            payload.update({
                "front_piece_uuid": front.piece_uuid,
                "front_global_id": front.global_id,
                "front_exit_distance_deg": self._dossier_exit_distance(front),
            })
        if dossier is not None:
            payload.update({
                "piece_uuid": dossier.piece_uuid,
                "global_id": dossier.global_id,
                "exit_distance_deg": self._dossier_exit_distance(dossier),
                "handoff_requested": dossier.handoff_requested,
                "distributor_ready": dossier.distributor_ready,
                "has_result": dossier.result is not None,
            })
        if extra:
            payload.update(extra)
        return self._handoff_diagnostics.record_move(
            now_mono=now_mono,
            **payload,
        )

    def _publish_handoff_burst(
        self,
        anomaly: dict[str, Any],
        now_mono: float,
    ) -> None:
        self._publish(RUNTIME_HANDOFF_BURST, anomaly, now_mono)

    def _track_angle_deg(self, track: Track) -> float | None:
        if track.angle_rad is None:
            return None
        return math.degrees(float(track.angle_rad))

    def _enqueue_eject(self, piece_uuid: str, *, claim_downstream: bool) -> bool:
        dossier = self._pieces.get(piece_uuid)
        if dossier is not None:
            if dossier.eject_enqueued:
                self._set_state("drop_commit", blocked_reason="eject_in_flight")
                return False
            dossier.eject_enqueued = True

        def _do_eject() -> None:
            try:
                ok = bool(self._eject())
            except Exception:
                self._logger.exception("RuntimeC4: eject_command raised")
                ok = False
            if not ok:
                live_dossier = self._pieces.get(piece_uuid)
                if live_dossier is not None:
                    live_dossier.eject_enqueued = False
                self._downstream_slot.release()
                return
            port = self._handoff
            if port is not None:
                try:
                    committed = bool(port.handoff_commit(piece_uuid, now_mono=time.monotonic()))
                except Exception:
                    self._logger.exception(
                        "RuntimeC4: distributor handoff_commit raised for piece=%s",
                        piece_uuid,
                    )
                    committed = False
                live_dossier = self._pieces.get(piece_uuid)
                if live_dossier is not None:
                    live_dossier.eject_committed = committed
                if not committed:
                    self._logger.warning(
                        "RuntimeC4: distributor handoff_commit rejected for piece=%s",
                        piece_uuid,
                    )

        if not self._hw.enqueue(_do_eject, label="c4_eject"):
            if dossier is not None:
                dossier.eject_enqueued = False
            if claim_downstream:
                self._downstream_slot.release()
            self._set_state("drop_commit", blocked_reason="hw_queue_full")
            return False
        self._record_handoff_move(
            now_mono=time.monotonic(),
            source="c4_eject",
            step_deg=None,
            use_exit_approach=None,
            track_count=len(self._pieces),
            dossier=dossier,
            extra={"claim_downstream": bool(claim_downstream)},
        )
        self._fsm = _C4State.DROP_COMMIT
        self._set_state(self._fsm.value)
        self._exit_stall_since = None
        return True

    def _maybe_shimmy(self, now_mono: float) -> bool:
        if self._exit_stall_since is None:
            self._exit_stall_since = now_mono
            return False
        stall = now_mono - self._exit_stall_since
        if stall < self._shimmy_stall_s:
            return False
        if now_mono < self._next_shimmy_at:
            return False
        if self._hw_busy_or_backlogged():
            return False
        step = self._shimmy_step_deg

        def _do_shimmy() -> None:
            try:
                self._wiggle_move(step)
                self._wiggle_move(-step)
            except Exception:
                self._logger.exception("RuntimeC4: shimmy move raised")

        if self._hw.enqueue(_do_shimmy, label="c4_exit_shimmy"):
            self._next_shimmy_at = now_mono + self._shimmy_cooldown_s
            self._fsm = _C4State.EXIT_SHIMMY
            self._set_state(self._fsm.value)
            return True
        return False

    def _has_trailing_piece_within_safety(
        self, matched_track: Track, tracks: list[Track]
    ) -> bool:
        """True if any other owned track is closer than the safety arc to the
        matched ejecting piece.

        We measure the absolute angular gap and check both directions: a piece
        ahead in rotation (already past the matched piece) and a piece behind
        (about to enter the chute). Either one within the safety arc means the
        chute opening currently spans more than one piece, and the shimmy
        could carry both off the tray.
        """
        if self._exit_trailing_safety_deg <= 0.0:
            return False
        matched_uuid = self._piece_uuid_for_track(matched_track)
        if matched_uuid is None:
            return False
        matched_angle = math.degrees(matched_track.angle_rad or 0.0)
        for t in tracks:
            if t.angle_rad is None or t.global_id is None:
                continue
            if t is matched_track:
                continue
            other_uuid = self._piece_uuid_for_track(t)
            if other_uuid is None or other_uuid == matched_uuid:
                continue
            other_angle = math.degrees(t.angle_rad)
            gap = abs(_wrap_deg(other_angle - matched_angle))
            if gap <= self._exit_trailing_safety_deg:
                return True
        return False

    def _pick_exit_track(self, tracks: list[Track]) -> Track | None:
        best: Track | None = None
        best_score: tuple[float, float] | None = None
        for t in tracks:
            if t.angle_rad is None or t.global_id is None:
                continue
            if self._piece_uuid_for_track(t) is None:
                continue
            delta = abs(_wrap_deg(math.degrees(t.angle_rad) - self._exit_angle_deg))
            overlap = self._exit_zone_bbox_overlap_ratio(t)
            ready = (
                delta <= self._angle_tol_deg
                if overlap is None
                else overlap >= self._exit_bbox_overlap_ratio
            )
            if not ready:
                continue
            score = (overlap if overlap is not None else 1.0, -delta)
            if best_score is None or score > best_score:
                best = t
                best_score = score
        return best

    def _owned_track_angles(self, tracks: list[Track]) -> dict[int, float]:
        angles: dict[int, float] = {}
        for track in tracks:
            if track.angle_rad is None or track.global_id is None:
                continue
            gid = int(track.global_id)
            if self._piece_uuid_for_track(track) is None:
                continue
            angles[gid] = math.degrees(float(track.angle_rad))
        return angles

    def _reset_transport_progress_watch(self) -> None:
        self._transport_progress_started_at = None
        self._transport_progress_baseline = {}
        self._last_transport_progress_deg = None

    def _hw_busy_or_backlogged(self) -> bool:
        return bool(self._hw.busy() or self._hw.pending() > 0)

    def _transport_waiting_on_ready_exit(self, tracks: list[Track]) -> bool:
        exit_track = self._pick_exit_track(tracks)
        if exit_track is None or exit_track.global_id is None:
            return False
        piece_uuid = self._piece_uuid_for_track(exit_track)
        dossier = self._pieces.get(piece_uuid) if piece_uuid is not None else None
        return dossier is not None

    def _maybe_unjam_transport(self, tracks: list[Track], now_mono: float) -> bool:
        if not self._unjam_enabled:
            self._reset_transport_progress_watch()
            return False
        if not self._pieces or not tracks:
            self._reset_transport_progress_watch()
            return False
        if self._startup_purge_pending() or self._startup_purge_state.mode_active:
            self._reset_transport_progress_watch()
            return False
        if self._fsm in (
            _C4State.STARTUP_PURGE,
            _C4State.DROP_COMMIT,
            _C4State.EXIT_SHIMMY,
            _C4State.TRANSPORT_UNJAM,
        ):
            return False
        if self._transport_waiting_on_ready_exit(tracks):
            self._reset_transport_progress_watch()
            return False

        angles = self._owned_track_angles(tracks)
        if not angles:
            self._reset_transport_progress_watch()
            return False
        if not self._transport_progress_baseline:
            self._transport_progress_baseline = dict(angles)
            self._transport_progress_started_at = now_mono
            self._last_transport_progress_deg = 0.0
            return False

        common_ids = set(angles).intersection(self._transport_progress_baseline)
        if not common_ids:
            self._transport_progress_baseline = dict(angles)
            self._transport_progress_started_at = now_mono
            self._last_transport_progress_deg = 0.0
            return False

        progress = max(
            abs(_wrap_deg(angles[gid] - self._transport_progress_baseline[gid]))
            for gid in common_ids
        )
        self._last_transport_progress_deg = progress
        if progress >= self._unjam_min_progress_deg:
            self._transport_progress_baseline = dict(angles)
            self._transport_progress_started_at = now_mono
            return False

        started_at = self._transport_progress_started_at
        if started_at is None:
            self._transport_progress_started_at = now_mono
            return False
        if (now_mono - started_at) < self._unjam_stall_s:
            return False
        if now_mono < self._next_unjam_at or self._hw_busy_or_backlogged():
            return False

        reverse_deg = self._unjam_reverse_deg
        forward_deg = self._unjam_forward_deg

        def _do_unjam() -> None:
            try:
                self._unjam_move(-reverse_deg)
                self._unjam_move(forward_deg)
            except Exception:
                self._logger.exception("RuntimeC4: transport unjam move raised")

        if self._hw.enqueue(_do_unjam, label="c4_transport_unjam"):
            self._next_unjam_at = now_mono + self._unjam_cooldown_s
            self._last_unjam_at = now_mono
            self._unjam_count += 1
            self._transport_progress_baseline = dict(angles)
            self._transport_progress_started_at = now_mono
            self._fsm = _C4State.TRANSPORT_UNJAM
            self._set_state(self._fsm.value)
            return True
        return False

    def _maybe_advance_transport(
        self,
        tracks: list[Track],
        now_mono: float,
        *,
        move_command: Callable[[float], bool] | None = None,
    ) -> bool:
        if not self._pieces or not tracks:
            return False
        if self._fsm in (
            _C4State.DROP_COMMIT,
            _C4State.EXIT_SHIMMY,
            _C4State.TRANSPORT_UNJAM,
        ):
            return False
        if self._hw_busy_or_backlogged() or now_mono < self._next_transport_at:
            return False
        if self._transport_waiting_on_ready_exit(tracks):
            return False

        use_exit_approach = move_command is None and any(
            self._track_in_exit_approach(track) for track in tracks
        )
        recommended_step = self._transport_velocity.snapshot.recommended_step_deg
        step = (
            min(self._transport_step_deg, self._exit_approach_step_deg)
            if use_exit_approach
            else float(recommended_step or self._transport_step_deg)
        )
        if not use_exit_approach:
            step = max(self._transport_step_deg, min(self._transport_max_step_deg, step))
        move = move_command or (
            self._carousel_move if use_exit_approach else self._transport_move
        )

        def _do_move() -> None:
            try:
                move(step)
            except Exception:
                self._logger.exception("RuntimeC4: transport move raised")

        if self._hw.enqueue(_do_move, label="c4_transport"):
            self._record_handoff_move(
                now_mono=now_mono,
                source="c4_transport",
                step_deg=step,
                use_exit_approach=use_exit_approach,
                track_count=len(tracks),
            )
            self._next_transport_at = now_mono + self._transport_cooldown_s
            return True
        return False

    def _dispatch_sample_transport_step(self, now_mono: float) -> bool:
        """Rotate C4 without classification, admission, or distributor handoff."""
        if self._hw_busy_or_backlogged():
            self._set_state("sample_transport", blocked_reason="hw_busy")
            return False
        step = self._sample_transport_step_deg

        def _do_move() -> None:
            try:
                self._sample_transport_move(
                    step,
                    self._sample_transport_max_speed,
                    self._sample_transport_acceleration,
                )
            except Exception:
                self._logger.exception("RuntimeC4: sample transport move raised")

        if not self._hw.enqueue(_do_move, label="c4_sample_transport"):
            self._set_state("sample_transport", blocked_reason="hw_queue_full")
            return False
        self._next_transport_at = now_mono + self._transport_cooldown_s
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
            self._sample_transport_step_deg = self._transport_step_deg
            return
        target_degrees_per_second = max(0.0, float(target_rpm)) * 6.0
        step = target_degrees_per_second * DEFAULT_SAMPLE_TRANSPORT_TARGET_INTERVAL_S
        self._sample_transport_step_deg = max(
            self._transport_step_deg,
            min(DEFAULT_SAMPLE_TRANSPORT_MAX_STEP_DEG, step),
        )

    def _maybe_idle_jog(self, now_mono: float) -> bool:
        if not self._idle_jog_enabled:
            return False
        if self._pieces:
            return False
        if self._startup_purge_pending() or self._startup_purge_state.mode_active:
            return False
        if self._fsm in (
            _C4State.STARTUP_PURGE,
            _C4State.DROP_COMMIT,
            _C4State.EXIT_SHIMMY,
            _C4State.TRANSPORT_UNJAM,
        ):
            return False
        if self._hw_busy_or_backlogged() or now_mono < self._next_idle_jog_at:
            return False
        if now_mono < self._next_accept_at:
            return False

        def _do_idle_jog() -> None:
            try:
                self._carousel_move(self._idle_jog_step_deg)
            except Exception:
                self._logger.exception("RuntimeC4: idle jog move raised")

        if self._hw.enqueue(_do_idle_jog, label="c4_idle_jog"):
            self._next_idle_jog_at = now_mono + self._idle_jog_cooldown_s
            self._last_idle_jog_at = now_mono
            self._idle_jog_count += 1
            return True
        return False

    def _track_in_exit_approach(self, track: Track) -> bool:
        if track.angle_rad is None or track.global_id is None:
            return False
        if self._piece_uuid_for_track(track) is None:
            return False
        center_delta = abs(_wrap_deg(math.degrees(track.angle_rad) - self._exit_angle_deg))
        if center_delta <= self._exit_approach_angle_deg:
            return True
        overlap = self._exit_zone_bbox_overlap_ratio(track)
        return bool(overlap is not None and overlap > 0.0)

    def _exit_zone_bbox_overlap_ratio(self, track: Track) -> float | None:
        if track.angle_rad is None:
            return None
        bbox = getattr(track, "bbox_xyxy", None)
        radius = getattr(track, "radius_px", None)
        if bbox is None or radius is None:
            return None
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
            radius_f = float(radius)
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1 or radius_f <= 0.0:
            return None

        center_angle = float(track.angle_rad)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        origin_x = center_x - radius_f * math.cos(center_angle)
        origin_y = center_y - radius_f * math.sin(center_angle)
        deltas: list[float] = []
        for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2)):
            corner_angle = math.degrees(math.atan2(y - origin_y, x - origin_x))
            deltas.append(_wrap_deg(corner_angle - math.degrees(center_angle)))
        if not deltas:
            return None

        start = min(deltas)
        end = max(deltas)
        width = max(0.0, end - start)
        exit_delta = _wrap_deg(self._exit_angle_deg - math.degrees(center_angle))
        window_start = exit_delta - self._angle_tol_deg
        window_end = exit_delta + self._angle_tol_deg
        if width <= 1e-6:
            return 1.0 if window_start <= 0.0 <= window_end else 0.0
        overlap = max(0.0, min(end, window_end) - max(start, window_start))
        return max(0.0, min(1.0, overlap / width))

    def _refresh_fsm_label(
        self,
        *,
        transport_active: bool = False,
        idle_jog_active: bool = False,
        unjam_active: bool = False,
    ) -> None:
        if self._fsm in (_C4State.DROP_COMMIT, _C4State.EXIT_SHIMMY):
            self._set_state(self._fsm.value)
            return
        if unjam_active and self._fsm is _C4State.TRANSPORT_UNJAM:
            self._set_state(self._fsm.value)
            return
        inflight = any(d.classify_future is not None for d in self._pieces.values())
        self._fsm = _C4State.CLASSIFY_PENDING if inflight else _C4State.RUNNING
        if transport_active and self._fsm is _C4State.RUNNING:
            self._set_state("rotate_pipeline")
            return
        if idle_jog_active and self._fsm is _C4State.RUNNING:
            self._set_state("idle_jog")
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

    def _wrap_rotation_command(
        self,
        command: Callable[[float], bool],
        source_label: str,
    ) -> Callable[[float], bool]:
        feed_id = self.feed_id
        pad_s = _C4_ROTATION_WINDOW_PAD_S
        est_duration_s = _C4_MOVE_ESTIMATED_DURATION_S

        def _wrapped(deg: float) -> bool:
            now_wall = time.time()
            if self._bus is not None:
                try:
                    self._bus.publish(
                        Event(
                            topic=PERCEPTION_ROTATION,
                            payload={
                                "feed_id": feed_id,
                                "start_ts": float(now_wall - pad_s),
                                "end_ts": float(now_wall + est_duration_s + pad_s),
                                "source": source_label,
                            },
                            source=self.runtime_id,
                            ts_mono=time.monotonic(),
                        )
                    )
                except Exception:
                    self._logger.exception(
                        "RuntimeC4: rotation-window publish failed (source=%s)",
                        source_label,
                    )
            ok = False
            try:
                ok = bool(command(deg))
                return ok
            finally:
                publish_move_completed(
                    self._bus,
                    self._logger,
                    runtime_id=self.runtime_id,
                    feed_id=feed_id,
                    source=source_label,
                    ok=ok,
                    degrees=deg,
                )

        return _wrapped

    def _wrap_direct_rotation_command(
        self,
        command: Callable[..., bool],
        source_label: str,
    ) -> Callable[[float, int | None, int | None], bool]:
        def _call(deg: float) -> bool:
            try:
                return bool(
                    command(
                        deg,
                        self._sample_transport_max_speed,
                        self._sample_transport_acceleration,
                    )
                )
            except TypeError:
                return bool(command(deg))

        publish_wrapped = self._wrap_rotation_command(_call, source_label)

        def _wrapped(
            deg: float,
            max_speed: int | None = None,
            acceleration: int | None = None,
        ) -> bool:
            self._sample_transport_max_speed = max_speed
            self._sample_transport_acceleration = acceleration
            return publish_wrapped(deg)

        return _wrapped


# Carousel moves take a variable amount of time depending on step size and
# speed; the window errs long enough (plus pad) to include the following
# frame(s) so the ghost-gating tracker reliably counts them as during
# rotation. Over-generous windows are cheap: idle ticks don't produce
# samples that alter ghost verdicts, only stationary ones do.
_C4_ROTATION_WINDOW_PAD_S = 0.15
_C4_MOVE_ESTIMATED_DURATION_S = 0.6


def _synthetic_frame(*, feed_id: str, now_mono: float) -> FeedFrame:
    """Placeholder FeedFrame for pre-Phase-5 unit tests."""
    return FeedFrame(
        feed_id=feed_id, camera_id="synthetic", raw=None, gray=None,
        timestamp=now_mono, monotonic_ts=now_mono, frame_seq=0,
    )


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


class _C4PurgePort:
    """PurgePort binding for RuntimeC4.

    C4 already drives its own drain loop inside the normal tick path
    (``_run_startup_purge``). The port just arms/disarms the flag and
    exposes counts; ``drain_step`` is a no-op that reports whether the
    runtime is still working.
    """

    key = "c4"

    def __init__(self, runtime: RuntimeC4) -> None:
        self._runtime = runtime

    def arm(self) -> None:
        self._runtime.arm_startup_purge()

    def disarm(self) -> None:
        self._runtime._startup_purge_state.armed = False
        self._runtime._exit_startup_purge()

    def counts(self) -> PurgeCounts:
        return PurgeCounts(
            piece_count=int(self._runtime._raw_detection_count),
            owned_count=len(self._runtime._pieces),
            pending_detections=0,
        )

    def drain_step(self, now_mono: float) -> bool:
        return bool(self._runtime._startup_purge_state.armed)


class _C4SampleTransportPort:
    key = "c4"

    def __init__(self, runtime: RuntimeC4) -> None:
        self._runtime = runtime

    def step(self, now_mono: float) -> bool:
        return self._runtime._dispatch_sample_transport_step(now_mono)

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
        return float(self._runtime._sample_transport_step_deg)


__all__ = ["RuntimeC4"]
