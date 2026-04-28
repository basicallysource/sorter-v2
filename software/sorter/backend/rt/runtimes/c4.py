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
from rt.contracts.landing_lease import LandingLeasePort
from rt.contracts.purge import PurgePort
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track
from rt.coupling.slots import CapacitySlot
from rt.events.topics import (
    PERCEPTION_ROTATION,
    PIECE_REGISTERED,
)
from rt.perception.piece_track_bank import (
    CameraTrayCalibration,
    PieceLifecycleState,
    PieceTrackBank,
    PieceTrackBankConfig,
)
from rt.perception.track_policy import action_track, is_visible_track
from rt.pieces.identity import new_piece_uuid, new_tracker_epoch
from rt.services.track_transit import TrackTransitRegistry, TransitCandidate
from rt.services.transport_velocity import TransportVelocityObserver

from ._c4_bank_mirror import C4BankMirror
from ._c4_classification import C4ClassificationController
from ._c4_debug_snapshots import C4DebugSnapshots
from ._c4_exit_dispatch import C4ExitDispatcher
from ._c4_exit_geometry import C4ExitGeometry
from ._c4_handoff_debug import C4HandoffDebug
from ._c4_payloads import C4Payloads
from ._c4_piece_lifecycle import C4PieceLifecycle
from ._c4_ports import (
    C4LandingLeasePort,
    C4PurgePort,
    C4SampleTransportPort,
    C4SectorCarouselPort,
)
from ._c4_startup_purge import C4StartupPurgeController
from ._c4_transport_controller import C4TransportController
from ._handoff_diagnostics import HandoffDiagnostics
from ._move_events import publish_move_completed
from ._ring_tracks import fresh_ring_tracks
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
# Distributor pre-positioning should not start for pieces that are still far
# around the carousel. Early requests thrash when dense C4 WIP reorders near
# the exit; classification may happen early, handoff should stay near-exit.
DEFAULT_HANDOFF_REQUEST_HORIZON_DEG = 60.0
DEFAULT_SHIMMY_STEP_DEG = 4.0
DEFAULT_SHIMMY_STALL_MS = 800
DEFAULT_SHIMMY_COOLDOWN_MS = 1200
DEFAULT_INTAKE_HALF_WIDTH_DEG = 18.0
# Probabilistic zone widening. Each zone's half-width gets stretched by
# k * sigma_a from the bank's filter so uncertain tracks reserve a
# proportionally bigger arc; confident, freshly-observed tracks pack
# tighter. The cap prevents a runaway sigma (e.g. a long-lost track
# whose sigma_a is at the bank's max_state_sigma_a_rad cap of 30 deg)
# from claiming the whole ring.
DEFAULT_ZONE_SIGMA_K = 1.5
DEFAULT_ZONE_MAX_HALF_WIDTH_DEG = 22.0
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
DEFAULT_TRACKLET_TRANSIT_MAX_ANGLE_DELTA_DEG = 45.0
_UNSET = object()


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
        handoff_request_horizon_deg: float = DEFAULT_HANDOFF_REQUEST_HORIZON_DEG,
        exit_angle_deg: float = DEFAULT_EXIT_ANGLE_DEG,
        angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
        intake_half_width_deg: float = DEFAULT_INTAKE_HALF_WIDTH_DEG,
        zone_sigma_k: float = DEFAULT_ZONE_SIGMA_K,
        zone_max_half_width_deg: float = DEFAULT_ZONE_MAX_HALF_WIDTH_DEG,
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
        idle_jog_enabled: bool = False,
        idle_jog_step_deg: float = DEFAULT_IDLE_JOG_STEP_DEG,
        idle_jog_cooldown_ms: int = DEFAULT_IDLE_JOG_COOLDOWN_MS,
        unjam_enabled: bool = False,
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
        # Mode flag: when True, RuntimeC4 keeps doing perception +
        # admission + classifier submission + dossier bookkeeping but
        # *skips* its internal transport/handoff/eject decisions so an
        # external sector-carousel scheduler can own them without
        # both paths fighting for the C4 stepper. Off by default.
        self._carousel_mode_active = False
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
        self._handoff_request_horizon_deg = max(
            0.0,
            float(handoff_request_horizon_deg),
        )
        self._exit_angle_deg = float(exit_angle_deg)
        self._angle_tol_deg = float(angle_tolerance_deg)
        self._intake_half_width_deg = float(intake_half_width_deg)
        self._zone_sigma_k = float(zone_sigma_k)
        self._zone_max_half_width_deg = float(zone_max_half_width_deg)
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
        # Software encoder for the C4 carousel: cumulative angle (radians)
        # of every rotation we have commanded since last home/reset. We
        # are the only writer of motion, so our running total is the
        # authoritative tray angle. Used by the PieceTrackBank as the
        # ``carrier prior`` — measurements are stored in tray frame
        # (a = camera_angle - encoder), so a piece carried perfectly by
        # the tray has a constant ``a`` and the Kalman bridges silences
        # using ``adot`` only for genuine slip / drift.
        self._carousel_angle_rad: float = 0.0
        # Vision-corrected virtual-pocket bank (architecture stage 2). The
        # bank is the durable identity surface; ``_pieces`` keeps the
        # dispatch-side state (handoff_requested, eject_enqueued, etc).
        # The two are kept synchronised on the same piece_uuid; the bank
        # owns position / covariance / lifecycle, the dossier owns
        # eject-cycle bookkeeping. Stage 4 collapses them into one.
        self._bank = PieceTrackBank(
            PieceTrackBankConfig(
                channel="c4",
                # cx/cy are calibrated lazily from frame size on first
                # admit — production wiring lands in stage 3.
                calibration=CameraTrayCalibration(cx=0.0, cy=0.0),
            )
        )
        self._bank_mirror = C4BankMirror(self)
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
        self._startup_purge_controller = C4StartupPurgeController(self)
        self._handoff_diagnostics = HandoffDiagnostics(
            runtime_id=self.runtime_id,
            feed_id=self.feed_id,
            logger=self._logger,
        )
        self._debug_snapshots = C4DebugSnapshots(self)
        self._payloads = C4Payloads(self)
        self._classification_controller = C4ClassificationController(self)
        self._piece_lifecycle = C4PieceLifecycle(self)
        self._handoff_debug = C4HandoffDebug(self)
        self._exit_geometry = C4ExitGeometry(self)
        self._exit_dispatcher = C4ExitDispatcher(self)
        self._transport_controller = C4TransportController(self)

    def available_slots(self) -> int:
        return int(self.capacity_debug_snapshot()["available"])

    def capacity_debug_snapshot(self) -> dict[str, Any]:
        if self._startup_purge_controller.pending():
            return {
                "available": 0,
                "reason": "startup_purge",
                "state": self._admission_state_snapshot(),
            }
        admission_state = self._admission_state_snapshot()
        decision = self._admission.can_admit(
            inbound_piece_hint={},
            runtime_state=admission_state,
        )
        return {
            "available": 1 if decision.allowed else 0,
            "reason": decision.reason,
            "state": admission_state,
        }

    def set_carousel_mode_active(self, active: bool) -> None:
        """Toggle the external-scheduler bypass.

        When ``True`` the runtime keeps perception + admission +
        classifier submission + dossier bookkeeping live (so BoxMot
        piece UUIDs and image crops still flow), but skips its own
        handoff, exit-dispatch, transport-advance, and idle-jog hardware
        actions so an external sector-carousel handler can drive C4's
        hardware without a parallel writer.
        """
        self._carousel_mode_active = bool(active)

    def carousel_mode_active(self) -> bool:
        return bool(self._carousel_mode_active)

    def carousel_front_snapshot(self) -> dict[str, Any] | None:
        """One-shot view of the front-most piece for the carousel handler.

        Returns ``None`` when no dossiers exist. Angle is the live
        track angle (from the bank) when available — the zone center
        is a stale snapshot that doesn't reflect rotation between
        zone refreshes. Callers receive a plain dict — no internal
        references leak.
        """
        if not self._pieces:
            return None
        front = self._dossiers_by_exit_distance()[0]
        bank_track = self._bank.track(front.piece_uuid)
        angle_deg: float | None = None
        if bank_track is not None and bank_track.angle_rad is not None:
            angle_deg = math.degrees(float(bank_track.angle_rad))
        if angle_deg is None:
            zone = self._zone_manager.zone_for(front.piece_uuid)
            if zone is not None:
                angle_deg = float(zone.center_deg)
        result = front.result
        return {
            "piece_uuid": front.piece_uuid,
            "global_id": front.global_id,
            "angle_deg": angle_deg,
            "exit_distance_deg": self._dossier_exit_distance(front),
            "classification_present": result is not None,
            "classification": result,
            "dossier": {
                "piece_uuid": front.piece_uuid,
                "global_id": front.global_id,
                "handoff_requested": bool(front.handoff_requested),
                "distributor_ready": bool(front.distributor_ready),
                "eject_enqueued": bool(front.eject_enqueued),
                "eject_committed": bool(front.eject_committed),
            },
        }

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
        self._piece_lifecycle.on_piece_delivered(piece_uuid, now_mono)

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
        bank_track = self._bank.track(piece_uuid)
        if bank_track is not None:
            bank_track.distributor_ready = True

    def _sync_handoff_from_port(self, dossier: _PieceDossier) -> bool:
        """Mirror an already-pending distributor handoff back into C4 state."""
        port = self._handoff
        if port is None:
            return False
        pending_piece_uuid_fn = getattr(port, "pending_piece_uuid", None)
        if not callable(pending_piece_uuid_fn):
            return False
        try:
            pending_piece_uuid = pending_piece_uuid_fn()
        except Exception:
            return False
        if pending_piece_uuid != dossier.piece_uuid:
            return False
        ready = False
        pending_ready_fn = getattr(port, "pending_ready", None)
        if callable(pending_ready_fn):
            try:
                ready = bool(pending_ready_fn(dossier.piece_uuid))
            except Exception:
                ready = False
        dossier.handoff_requested = True
        dossier.distributor_ready = ready
        bank_track = self._bank.track(dossier.piece_uuid)
        if bank_track is not None:
            bank_track.handoff_requested = True
            bank_track.distributor_ready = ready
        return True

    def on_piece_rejected(self, piece_uuid: str, reason: str) -> None:
        """Phase-5 stub: distributor signals the piece cannot be sorted."""
        self._piece_lifecycle.on_piece_rejected(piece_uuid, reason)

    def dossier_count(self) -> int:
        return len(self._pieces)

    def dossier_for(self, piece_uuid: str) -> _PieceDossier | None:
        return self._pieces.get(piece_uuid)

    def fsm_state(self) -> str:
        return self._fsm.value

    @property
    def exit_angle_deg(self) -> float:
        """Operator-facing C4 chute/exit angle in camera-frame degrees."""
        return float(self._exit_angle_deg)

    def move_tray_degrees(self, degrees: float) -> bool:
        """Move the C4 tray by camera-frame degrees for calibration tools."""
        return bool(self._transport_move(float(degrees)))

    def configure_admission(
        self,
        *,
        max_zones: int | None = None,
        max_raw_detections: int | None | object = _UNSET,
        require_dropzone_clear: bool | None = None,
        intake_body_half_width_deg: float | None = None,
        intake_guard_deg: float | None = None,
    ) -> None:
        """Apply live C4 admission/zone tuning through the runtime boundary."""
        self._zone_manager.configure(
            max_zones=max_zones,
            default_half_width_deg=intake_body_half_width_deg,
            guard_angle_deg=intake_guard_deg,
        )
        admission_kwargs: dict[str, Any] = {
            "max_zones": max_zones,
            "guard_angle_deg": intake_guard_deg,
            "require_dropzone_clear": require_dropzone_clear,
        }
        if max_raw_detections is not _UNSET:
            admission_kwargs["max_raw_detections"] = max_raw_detections
        self._admission.configure(**admission_kwargs)
        if intake_body_half_width_deg is not None:
            self._intake_half_width_deg = float(intake_body_half_width_deg)

    def _dossier_debug_payload(
        self,
        dossier: _PieceDossier,
        *,
        detail_ts_mono: float | None = None,
    ) -> dict[str, Any]:
        return self._debug_snapshots.dossier_debug_payload(
            dossier,
            detail_ts_mono=detail_ts_mono,
        )

    def debug_snapshot(self) -> dict[str, Any]:
        return self._debug_snapshots.debug_snapshot()

    def inspect_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        return self._debug_snapshots.inspect_snapshot(now_mono=now_mono)

    def arm_startup_purge(self) -> None:
        self._startup_purge_controller.arm()

    @property
    def startup_purge_armed(self) -> bool:
        """Public read of the startup-purge arm flag (introspection hook)."""
        return self._startup_purge_controller.armed

    def purge_port(self) -> PurgePort:
        return C4PurgePort(self)

    def sample_transport_port(self) -> "C4SampleTransportPort":
        return C4SampleTransportPort(self)

    def sector_carousel_port(self) -> "C4SectorCarouselPort":
        return C4SectorCarouselPort(self)

    def _tick_inner(self, inbox: RuntimeInbox, now_mono: float) -> None:
        self._piece_lifecycle.sweep_recently_delivered(now_mono)
        # Propagate the bank's Kalman state forward — every tick, before
        # we touch new measurements. After this call the bank's tracks
        # are aligned to ``now_mono`` and the posterior-singleton query
        # answers correctly.
        self._bank_mirror.predict(now_mono)
        raw_tracks = fresh_ring_tracks(inbox.tracks, track_stale_s=self._track_stale_s)
        visible_tracks = [t for t in raw_tracks if is_visible_track(t)]
        self._raw_detection_count = len(visible_tracks)
        owned_tracks = self._sync_owned_tracks(visible_tracks, now_mono)
        if self._startup_purge_controller.run(visible_tracks, owned_tracks, now_mono):
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
        # Mirror this frame's owned tracks into the bank as Kalman
        # measurement updates. Births happen via ``_bank_mirror.admit_track``
        # in the admission/reconcile paths above; this step only updates
        # already-admitted pieces.
        self._bank_mirror.observe_tracks(owned_tracks, now_mono)
        self._transport_velocity.update(
            owned_tracks,
            now_mono=now_mono,
            base_step_deg=self._transport_step_deg,
            max_step_deg=self._transport_max_step_deg,
            exit_slow_zone_deg=self._exit_approach_angle_deg,
        )
        self._classification_controller.submit_classifications(
            owned_tracks,
            now_mono,
        )
        self._classification_controller.poll_futures(now_mono)
        if not self._carousel_mode_active:
            # Carousel mode delegates these to an external scheduler
            # (SectorCarouselHandler). Perception + admission +
            # classification still run above so dossiers stay live.
            self._exit_dispatcher.request_pending_handoffs(now_mono)
            self._exit_dispatcher.handle_exit(owned_tracks, inbox, now_mono)
        unjam_active = self._transport_controller.maybe_unjam_transport(
            owned_tracks,
            now_mono,
        )
        transport_active = False
        if not unjam_active and not self._carousel_mode_active:
            transport_active = self._transport_controller.maybe_advance_transport(
                owned_tracks,
                now_mono,
            )
        idle_jog_active = False
        if (
            not transport_active
            and not unjam_active
            and not self._carousel_mode_active
        ):
            idle_jog_active = self._transport_controller.maybe_idle_jog(now_mono)
        self._refresh_fsm_label(
            transport_active=transport_active,
            idle_jog_active=idle_jog_active,
            unjam_active=unjam_active,
        )

    # -- Helpers ------------------------------------------------------

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
            "startup_purge_active": self._startup_purge_controller.pending(),
        }

    def _owned_tracks(self, tracks: list[Track]) -> list[Track]:
        return [t for t in tracks if self._piece_uuid_for_track(t) is not None]

    def _zone_half_width_for(self, piece_uuid: str) -> float:
        """Half-width of the angular zone for a piece, widened by bank sigma.

        Returns the geometric base width inflated by ``k * sigma_a`` so a
        track whose Kalman state is uncertain (recently lost, freshly
        admitted, post-collision) reserves a proportionally larger arc;
        a confident, freshly-observed track packs at the geometric base.
        Capped at ``_zone_max_half_width_deg`` to keep one runaway sigma
        from blocking the whole ring.
        """
        base = self._intake_half_width_deg
        if self._zone_sigma_k <= 0.0:
            return base
        bank_track = self._bank.track(piece_uuid)
        if bank_track is None:
            return base
        var_a = float(bank_track.state_covariance[0, 0])
        if var_a <= 0.0:
            return base
        sigma_a_deg = math.degrees(math.sqrt(var_a))
        widened = base + self._zone_sigma_k * sigma_a_deg
        return min(widened, self._zone_max_half_width_deg)

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
                    half_width_deg=self._zone_half_width_for(piece_uuid),
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
                self._piece_lifecycle.finalize_piece(
                    piece_uuid,
                    now_mono=now_mono,
                    arm_cooldown=False,
                    abort_handoff=True,
                    abort_reason="track_lost",
                )
        return self._owned_tracks(tracks)

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
        if self._piece_lifecycle.is_recently_delivered_track(track, now_mono):
            return False
        gid = int(track.global_id)
        if self._piece_uuid_for_track(track) is not None:
            return False
        angle_deg = math.degrees(track.angle_rad)
        tracklet = self._payloads.tracklet_payload_for_gid(gid)
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
        extras = self._payloads.extras_for_registration(
            track,
            recovered=recovered,
            transit=transit,
        )
        result = self._payloads.result_from_transit(transit)
        classified_ts = self._payloads.classified_ts_from_transit(transit)
        reject_reason = self._payloads.reject_reason_from_transit(transit)
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
        # Mirror into the PieceTrackBank so the bank holds durable
        # identity + Kalman state for this physical piece. We feed the
        # camera-frame angle directly: stage 2 keeps tracking in
        # camera/world frame because C4 has no exposed tray encoder yet
        # (a stage-3 follow-up). The Kalman learns the carousel rotation
        # rate from successive observations, which is good enough for
        # the posterior-singleton dispatch check the bank exists for.
        self._bank_mirror.admit_track(
            piece_uuid=piece_uuid,
            track=track,
            angle_deg=angle_deg,
            now_mono=now_mono,
        )
        # Mirror the dispatch-side context from the dossier into the
        # bank's PieceTrack so future dispatch reads can go through the
        # bank as the single source of truth.
        bank_track = self._bank.track(piece_uuid)
        if bank_track is not None:
            bank_track.intake_ts = float(now_mono)
            bank_track.classified_ts = classified_ts
            bank_track.reject_reason = reject_reason
            bank_track.extras.update(extras)
        # If the upstream channel held a landing lease for this piece,
        # consume the oldest pending landing in FIFO order. The bank's
        # lease grant model is geometry-only (it does not know about
        # raw track ids), so the first-in lease pairs with the first
        # admitted arrival regardless of which raw_track_id ends up
        # carrying it. Recovered admissions skip this — those came from
        # restart reconciliation, not from a fresh upstream pulse.
        if not recovered:
            self._bank.consume_oldest_pending_landing()
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
        self._handoff_debug.record_dropzone_arrival(
            track=track,
            dossier=dossier,
            now_mono=now_mono,
            release_upstream=release_upstream_now,
            recovered=recovered,
        )
        result_payload = self._payloads.classification_payload(result)
        event_payload = self._payloads.dossier_event_payload(
            dossier,
            zone_state="active",
        )
        dossier_payload = self._payloads.dossier_event_payload(
            dossier,
            zone_state="active",
            center_deg=angle_deg,
            include_exit=True,
        )
        transit_payload = self._payloads.transit_payload(transit)
        self._publish(
            PIECE_REGISTERED,
            {
                **event_payload,
                "angle_at_intake_deg": angle_deg,
                "intake_ts_mono": now_mono,
                "confirmed_real": True,
                "stage": "registered",
                "classification_status": self._payloads.classification_status(result),
                "recovered": recovered,
                "admission_basis": dossier.extras.get("admission_basis"),
                **transit_payload,
                "dossier": {
                    **dossier_payload,
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

    def _publish_transit_link(
        self,
        piece_uuid: str,
        tracked_global_id: int,
        transit: TransitCandidate,
        *,
        now_mono: float,
    ) -> None:
        self._payloads.publish_transit_link(
            piece_uuid,
            tracked_global_id,
            transit,
            now_mono=now_mono,
        )

    def _mark_handoff(self, reason: str) -> None:
        self._last_handoff_skip = reason
        self._handoff_debug_counts[reason] = self._handoff_debug_counts.get(reason, 0) + 1

    def _dossiers_by_exit_distance(self) -> list[_PieceDossier]:
        dossiers = list(self._pieces.values())
        dossiers.sort(key=self._dossier_exit_distance)
        return dossiers

    def _dossier_exit_distance(self, dossier: _PieceDossier) -> float:
        zone = self._zone_manager.zone_for(dossier.piece_uuid)
        if zone is None:
            return 9999.0
        return abs(_wrap_deg(float(zone.center_deg) - self._exit_angle_deg))

    def landing_lease_port(self) -> LandingLeasePort:
        """Expose this C4's landing-lease gate to the upstream C3.

        Wired at bootstrap: ``c3.set_landing_lease_port(c4.landing_lease_port())``.
        """
        return C4LandingLeasePort(self)

    def _hw_busy_or_backlogged(self) -> bool:
        return bool(self._hw.busy() or self._hw.pending() > 0)

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
                # Software encoder: every successful rotation through
                # this wrapper contributes to the cumulative carousel
                # angle. Failed moves do not count — the hardware did
                # not actually advance.
                if ok:
                    self._carousel_angle_rad = math.radians(
                        math.degrees(self._carousel_angle_rad) + float(deg)
                    )
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


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["RuntimeC4"]
