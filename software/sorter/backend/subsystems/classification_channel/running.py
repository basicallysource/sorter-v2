from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np

from defs.known_object import ClassificationStatus, KnownObject
from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.bus import StationId
from subsystems.classification_channel.recognition import (
    ClassificationChannelRecognizer,
)
from subsystems.classification_channel.incidents import (
    publish_classification_intake_timeout_incident,
    publish_classification_fallback_incident,
    publish_classification_track_lost_incident,
)
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.classification_channel.zone_manager import (
    ExclusionZone,
    TrackAngularExtent,
    _circular_diff_deg,
)
from subsystems.sample_collection_speed import (
    microsteps_from_stepper_config,
    sample_collection_effective_speed_microsteps_per_second,
)
from subsystems.shared_variables import SharedVariables
from utils.event import knownObjectToEvent

INTAKE_REQUEST_TIMEOUT_S = 2.0
# Max time to defer a piece's drop-deadline fallback while a Brickognize
# response is still outstanding. The 10×60 s baseline campaign on the 5-wall
# platter showed Brickognize commonly answers in <1 s when it answers at all,
# so 2 s is comfortable headroom without permanently parking a piece in the
# hood if the request never returns.
PENDING_CLASSIFICATION_GRACE_S = 2.0
# Drop-moment snapshot: max longest edge of the encoded JPEG. Keeps the event
# payload bounded (~80-120 kB per frame) while still being legible on the
# piece detail page next to the Brickognize reference thumbnail.
DROP_SNAPSHOT_MAX_EDGE_PX = 1024
DROP_SNAPSHOT_JPEG_QUALITY = 78
MIN_INTAKE_TRACK_HITS = 2
RECOVERY_MIN_TRACK_HITS = 4
RECOVERY_MIN_TRACK_AGE_S = 0.35
RECOGNITION_RETRY_INTERVAL_S = 0.10
INTAKE_FRESHNESS_GRACE_S = 0.35
SAMPLE_MODE_TEACHER_CAPTURE_MIN_INTERVAL_S = 0.8
SAMPLE_MODE_EMPTY_STATE_CAPTURE_INTERVAL_S = 5.0
DEFAULT_EXIT_RELEASE_STEPPER_PER_OUTPUT_DEG = 130.0 / 12.0


@dataclass(frozen=True)
class _ExitReleaseStage:
    name: str
    amplitude_output_deg: float
    cycles: int
    speed: int
    acceleration: int
    settle_ms: int


@dataclass(frozen=True)
class _ExitReleaseStroke:
    label: str
    move_deg: float
    speed: int | None
    acceleration: int | None
    settle_s: float


@dataclass
class _ExitReleaseReview:
    piece_uuid: str
    stage_index: int
    stage_count: int
    stage: _ExitReleaseStage
    plan: list[_ExitReleaseStroke]
    trigger: dict[str, float | bool]
    triggered_at_wall: float
    approved: bool = False


DEFAULT_EXIT_RELEASE_STAGES: tuple[_ExitReleaseStage, ...] = (
    _ExitReleaseStage("contact-break-micro", 0.25, 2, 700, 1800, 300),
    _ExitReleaseStage("low-rock", 0.50, 2, 950, 2600, 300),
    _ExitReleaseStage("medium-rock", 0.85, 3, 1250, 3600, 350),
    _ExitReleaseStage("firm-rock", 1.25, 3, 1600, 4800, 400),
    _ExitReleaseStage("last-resort-small-kick", 1.75, 2, 1900, 6000, 450),
)


class Running(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision=None,
        event_queue=None,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.vision = vision
        self.event_queue = event_queue
        self._recognizer = ClassificationChannelRecognizer(
            gc=gc,
            logger=self.logger,
            vision=vision,
            transport=transport,
            event_queue=event_queue,
        )
        self._pulse_in_flight = False
        self._pending_drop_uuid: str | None = None
        self._exit_release_drop_uuid: str | None = None
        self._exit_release_plan: list[_ExitReleaseStroke] = []
        self._exit_release_next_move_not_before_mono = 0.0
        self._exit_release_attempt_by_uuid: dict[str, int] = {}
        self._exit_release_review: _ExitReleaseReview | None = None
        self._exit_release_manual_test = False
        self._awaiting_intake_piece = False
        self._intake_requested_at_mono: float | None = None
        self._intake_requested_at_wall: float | None = None
        self._occupancy_state: str | None = None
        self._recognition_retry_not_before_by_uuid: dict[str, float] = {}
        # Track when we first deferred a piece's deadline because Brickognize
        # was still in flight, so we can time it out instead of waiting
        # forever if the response never arrives.
        self._deadline_defer_started_at_by_uuid: dict[str, float] = {}
        self._sample_teacher_capture_last_queued_mono: float | None = None
        self._sample_empty_state_last_captured_mono: float | None = None

    @property
    def _config(self):
        return self.irl_config.classification_channel_config

    def _setOccupancyState(self, state_name: str) -> None:
        if self._occupancy_state == state_name:
            return
        prev_state = self._occupancy_state
        self._occupancy_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            "classification.occupancy",
            prev_state,
            state_name,
        )

    def step(self) -> Optional[ClassificationChannelState]:
        now_wall = time.time()
        now_mono = time.monotonic()
        sample_mode = self._sampleCollectionMode()

        if self._pulse_in_flight:
            if not self.irl.carousel_stepper.stopped:
                self._setOccupancyState(
                    "classification_channel.wait_transport_motion_complete"
                )
                return None
            self._finalizePulse(now_mono)
            return None

        if self._exit_release_drop_uuid is not None:
            if not self.irl.carousel_stepper.stopped:
                self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None
            if now_mono < self._exit_release_next_move_not_before_mono:
                self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None
            if self._advanceExitReleaseShimmy(now_mono):
                self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None
            drop_uuid = self._exit_release_drop_uuid
            self._exit_release_drop_uuid = None
            if self._exit_release_manual_test:
                self._exit_release_manual_test = False
                review = self._exit_release_review
                if review is not None:
                    review.approved = False
                    self._publishExitReleaseIncident(review, status="waiting_for_operator")
                self._setOccupancyState("classification_channel.exit_incident_review")
                return None
            if drop_uuid is not None:
                if self._sendPulse(drop_uuid):
                    self._setOccupancyState("classification_channel.drop_commit")
            return None

        if self._holdForExitReleaseIncidentReview():
            return None

        track_extents = self._getTrackExtents()
        self._registerNewIntakePiece(track_extents, now_wall, now_mono)
        self._recoverExistingTrackedPieces(track_extents, now_wall)
        zones, expired_pieces = self.transport.updateTrackedPieces(track_extents)
        self._refreshLatestCapturedCrops(now_wall)
        self._emitExpiredPieceEvents(expired_pieces)
        if sample_mode:
            self._maybeCaptureSampleModeEmptyState(track_extents, zones, now_mono)

        self._resolveDeadlines(zones, now_wall)
        self._refreshPositioningPiece()
        self._updateIntakeGate(now_mono)

        # Recognition fires Brickognize async (no stepper conflict), so
        # always attempt it before the drop-pulse path. Otherwise, when
        # pieces flow fast (post-T3 retry-budget unlock), a piece is
        # constantly in the drop window and step() returns early at
        # _sendPulse(drop_uuid) — the *other* piece in the hood never gets
        # a chance to fire recognition. Calling it here lets the hood piece
        # accumulate fires while the drop piece is still being committed.
        if not sample_mode:
            self._fireRecognition(now_wall)

        drop_uuid = self._pickDropCandidate()
        if drop_uuid is not None:
            if not self.shared.distribution_ready:
                self._setOccupancyState(
                    "classification_channel.wait_distribution_ready"
                )
                self.gc.runtime_stats.observeBlockedReason(
                    "classification", "waiting_distribution_ready"
                )
                return None
            if not sample_mode and self._startExitReleaseShimmyIfNeeded(
                drop_uuid,
                review_allowed=False,
            ):
                if self._exit_release_review is not None and not self._exit_release_review.approved:
                    self._setOccupancyState("classification_channel.exit_incident_review")
                else:
                    self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None
            if self._sendPulse(drop_uuid):
                self._setOccupancyState("classification_channel.drop_commit")
            return None

        release_uuid = None if sample_mode else self._pickExitReleaseCandidate()
        if release_uuid is not None:
            if not self.shared.distribution_ready:
                self._setOccupancyState(
                    "classification_channel.wait_distribution_ready_exit_obstruction"
                )
                self.gc.runtime_stats.observeBlockedReason(
                    "classification", "waiting_distribution_ready_exit_obstruction"
                )
                return None
            if self._startExitReleaseShimmyIfNeeded(release_uuid):
                if self._exit_release_review is not None and not self._exit_release_review.approved:
                    self._setOccupancyState("classification_channel.exit_incident_review")
                else:
                    self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None

        hood_piece = self.transport.getPieceAtClassification()
        if not sample_mode and self._shouldHoldForHoodDwell(hood_piece, now_wall):
            self._setOccupancyState("classification_channel.hood_dwell")
            return None

        # Recognition was already attempted at the top of step() — no need
        # to repeat here.

        active_pieces = self.transport.activePieces()
        if not active_pieces:
            self.transport.setPositioningPiece(None)
            self._setOccupancyState("classification_channel.wait_piece_trigger")
            return None

        if not self.shared.distribution_ready and self.transport.getPieceForDistributionDrop() is not None:
            self._setOccupancyState("classification_channel.wait_distribution_ready")
            return None

        if self._sendPulse(None):
            self._setOccupancyState("classification_channel.rotate_pipeline")
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self._pulse_in_flight = False
        self._pending_drop_uuid = None
        self._exit_release_drop_uuid = None
        self._exit_release_plan = []
        self._exit_release_next_move_not_before_mono = 0.0
        self._exit_release_attempt_by_uuid = {}
        self._exit_release_manual_test = False
        self._clearExitReleaseIncident()
        self._awaiting_intake_piece = False
        self._intake_requested_at_mono = None
        self._intake_requested_at_wall = None
        self._occupancy_state = None
        self._recognition_retry_not_before_by_uuid = {}
        self._sample_teacher_capture_last_queued_mono = None
        self._sample_empty_state_last_captured_mono = None
        self.shared.set_classification_gate(False, reason="cleanup")

    def _sampleCollectionMode(self) -> bool:
        return bool(getattr(self.shared, "sample_collection_mode", False))

    def _getTrackExtents(self) -> list[TrackAngularExtent]:
        if self.vision is None:
            return []
        try:
            return list(
                self.vision.getFeederTrackAngularExtents(
                    "carousel",
                    force_detection=True,
                )
            )
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: could not update carousel track extents: {exc}"
            )
            return []

    def _registerNewIntakePiece(
        self,
        track_extents: list[TrackAngularExtent],
        now_wall: float,
        now_mono: float,
    ) -> None:
        if self.transport.zone_manager is None:
            return
        if not self._awaiting_intake_piece:
            return

        candidate_window_deg = (
            float(self._config.intake_body_half_width_deg)
            + float(self._config.intake_guard_deg)
            + 8.0
        )
        unmatched = [
            extent
            for extent in track_extents
            if self.transport.pieceForTrack(extent.global_id) is None
            and int(extent.hit_count) >= MIN_INTAKE_TRACK_HITS
            and (
                self._intake_requested_at_wall is None
                or float(extent.first_seen_ts)
                >= (self._intake_requested_at_wall - INTAKE_FRESHNESS_GRACE_S)
            )
            and abs(
                _circular_diff_deg(extent.center_deg, self._config.intake_angle_deg)
            )
            <= candidate_window_deg
        ]
        if not unmatched:
            return
        unmatched.sort(
            key=lambda extent: abs(
                _circular_diff_deg(extent.center_deg, self._config.intake_angle_deg)
            )
        )
        if len(self.transport.activePieces()) >= int(self._config.max_zones):
            return

        extent = unmatched[0]
        obj = self.transport.registerIncomingPiece(tracked_global_id=extent.global_id)
        obj.feeding_started_at = now_wall
        obj.carousel_detected_confirmed_at = now_wall
        obj.tracked_global_id = extent.global_id
        obj.updated_at = now_wall
        # "Fashion-shoot" burst: drain ring-buffered frames from C3 + carousel
        # right now (pre-event) and schedule post-event frames 2 s out. Runs
        # before the legacy drop-snapshot / trigger so even a slow snapshot
        # call can't delay the ring-buffer drain past a few frames of drift.
        if self.vision is not None and hasattr(self.vision, "captureBurst") and extent.global_id is not None:
            try:
                self.vision.captureBurst(int(extent.global_id))
            except Exception as exc:
                self.logger.debug(
                    f"burst capture failed for piece {obj.uuid[:8]}: {exc}"
                )
        # Snapshot the chamber the instant the piece is first seen on C4 —
        # i.e. right as it falls in from C3. This beats the old drop-moment
        # capture because the piece is still isolated at the intake angle.
        self._captureDropSnapshot(obj.uuid)
        # Trigger ±2s burst capture via the carousel camera YOLO detector.
        if self.vision is not None and hasattr(self.vision, "triggerDropZoneBurst") and extent.global_id is not None:
            try:
                self.vision.triggerDropZoneBurst(int(extent.global_id))
            except Exception:
                pass
        _zones, expired = self.transport.updateTrackedPieces(track_extents)
        self._emitExpiredPieceEvents(expired)
        self._awaiting_intake_piece = False
        self._intake_requested_at_mono = None
        self._intake_requested_at_wall = None
        self.shared.set_classification_gate(False, reason="piece_in_hood")
        self._refreshLatestCapturedCrop(obj, now_wall=now_wall, emit=False)
        if self.event_queue is not None:
            self.event_queue.put(knownObjectToEvent(obj))
        self.logger.info(
            "ClassificationChannel: registered intake piece %s from track %s at %.1f deg"
            % (obj.uuid[:8], extent.global_id, extent.center_deg)
        )

    def _recoverExistingTrackedPieces(
        self,
        track_extents: list[TrackAngularExtent],
        now_wall: float,
    ) -> None:
        if self.transport.zone_manager is None:
            return

        available_slots = int(self._config.max_zones) - len(self.transport.activePieces())
        if available_slots <= 0:
            return
        available_slots = min(1, available_slots)

        candidates: list[TrackAngularExtent] = []
        for extent in track_extents:
            if self.transport.pieceForTrack(extent.global_id) is not None:
                continue
            if int(extent.hit_count) < RECOVERY_MIN_TRACK_HITS:
                continue
            if (
                isinstance(extent.first_seen_ts, (int, float))
                and float(extent.first_seen_ts) > 0.0
                and (now_wall - float(extent.first_seen_ts)) < RECOVERY_MIN_TRACK_AGE_S
            ):
                continue
            candidates.append(extent)

        if not candidates:
            return

        candidates.sort(
            key=lambda extent: (
                abs(
                    _circular_diff_deg(
                        extent.center_deg,
                        self._config.drop_angle_deg,
                    )
                ),
                float(extent.first_seen_ts) if float(extent.first_seen_ts) > 0.0 else now_wall,
                -int(extent.hit_count),
            )
        )

        adopted = 0
        for extent in candidates[:available_slots]:
            obj = self.transport.registerIncomingPiece(tracked_global_id=extent.global_id)
            obj.tracked_global_id = extent.global_id
            confirmed_at = (
                float(extent.first_seen_ts)
                if isinstance(extent.first_seen_ts, (int, float)) and float(extent.first_seen_ts) > 0.0
                else now_wall
            )
            obj.feeding_started_at = confirmed_at
            obj.carousel_detected_confirmed_at = confirmed_at
            obj.first_carousel_seen_ts = confirmed_at
            obj.first_carousel_seen_angle_deg = float(extent.center_deg)
            obj.classification_channel_zone_state = "tracked"
            obj.classification_channel_zone_center_deg = float(extent.center_deg)
            obj.classification_channel_zone_half_width_deg = float(extent.half_width_deg)
            obj.classification_channel_exit_offset_deg = _circular_diff_deg(
                float(extent.center_deg),
                float(self._config.drop_angle_deg),
            )
            self._refreshLatestCapturedCrop(obj, now_wall=now_wall, emit=False)
            obj.updated_at = now_wall
            if self.event_queue is not None:
                self.event_queue.put(knownObjectToEvent(obj))
            adopted += 1

        if adopted <= 0:
            return

        _zones, expired = self.transport.updateTrackedPieces(track_extents)
        self._emitExpiredPieceEvents(expired)
        self._awaiting_intake_piece = False
        self._intake_requested_at_mono = None
        self._intake_requested_at_wall = None
        self.shared.set_classification_gate(False, reason="recover_existing_piece")
        self.logger.info(
            "ClassificationChannel: recovered %d existing track(s) already present in chamber"
            % adopted
        )

    def _refreshLatestCapturedCrops(self, now_wall: float) -> None:
        for piece in self.transport.activePieces():
            self._refreshLatestCapturedCrop(piece, now_wall=now_wall, emit=True)

    def _refreshLatestCapturedCrop(
        self,
        piece: KnownObject,
        *,
        now_wall: float,
        emit: bool,
    ) -> bool:
        gid = getattr(piece, "tracked_global_id", None)
        if not isinstance(gid, int):
            return False
        if self.vision is None or not hasattr(self.vision, "getLatestFeederTrackPieceCrop"):
            return False
        try:
            crop_payload = self.vision.getLatestFeederTrackPieceCrop(int(gid))
        except Exception:
            return False
        if not isinstance(crop_payload, dict):
            return False
        crop_b64 = crop_payload.get("jpeg_b64")
        if not isinstance(crop_b64, str) or not crop_b64:
            return False
        captured_ts_raw = crop_payload.get("captured_ts")
        captured_ts = (
            float(captured_ts_raw)
            if isinstance(captured_ts_raw, (int, float))
            else now_wall
        )
        previous_ts = getattr(piece, "latest_captured_crop_ts", None)
        if isinstance(previous_ts, (int, float)) and captured_ts < float(previous_ts):
            return False
        if (
            isinstance(previous_ts, (int, float))
            and captured_ts == float(previous_ts)
            and piece.latest_captured_crop == crop_b64
        ):
            return False
        piece.latest_captured_crop = crop_b64
        piece.latest_captured_crop_ts = captured_ts
        piece.updated_at = now_wall
        if emit and self.event_queue is not None:
            self.event_queue.put(knownObjectToEvent(piece))
        return True

    def _emitExpiredPieceEvents(self, expired_pieces: list[KnownObject]) -> None:
        """Broadcast a terminal KnownObject event for each stale-zone drop.

        The transport has already flipped ``stage`` to ``distributed`` and
        stamped ``distributed_at`` — all we do here is emit a single event per
        expired piece so the frontend removes the stale uuid from the upcoming
        list when the same physical piece is re-acquired under a fresh
        ``global_id`` after occlusion. Counter bump feeds the diagnostics
        snapshot so we can measure how often this happens.
        """
        if not expired_pieces:
            return
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        for piece in expired_pieces:
            self._refreshLatestCapturedCrop(piece, now_wall=time.time(), emit=False)
            if runtime_stats is not None and hasattr(
                runtime_stats, "observeClassificationZoneLost"
            ):
                runtime_stats.observeClassificationZoneLost()
            # Only emit terminal event for pieces the frontend has actually
            # seen as meaningful: classified (has part_id or classified_at) or
            # at least one captured image. Never-classified zone-expiry ghosts
            # with no visual evidence have nothing useful to show.
            was_meaningful = bool(
                getattr(piece, "part_id", None)
                or getattr(piece, "classified_at", None)
                or getattr(piece, "thumbnail", None)
                or getattr(piece, "latest_captured_crop", None)
                or getattr(piece, "top_image", None)
                or getattr(piece, "bottom_image", None)
                or getattr(piece, "drop_snapshot", None)
            )
            if self.event_queue is not None and was_meaningful:
                publish_classification_track_lost_incident(
                    self.gc,
                    piece=piece,
                    reason="stale_zone_expired",
                )
                self.event_queue.put(knownObjectToEvent(piece))
            self.logger.info(
                "ClassificationChannel: expired stale-zone piece %s (track=%s, emitted=%s)"
                % (piece.uuid[:8], getattr(piece, "tracked_global_id", None), was_meaningful)
            )

    def _updateIntakeGate(self, now_mono: float) -> None:
        zone_manager = self.transport.zone_manager
        if zone_manager is None:
            self.shared.set_classification_gate(False, reason="no_zone_manager")
            return

        if self._awaiting_intake_piece:
            if (
                self._intake_requested_at_mono is not None
                and now_mono - self._intake_requested_at_mono > INTAKE_REQUEST_TIMEOUT_S
            ):
                elapsed_s = now_mono - self._intake_requested_at_mono
                if publish_classification_intake_timeout_incident(
                    self.gc,
                    elapsed_s=elapsed_s,
                ):
                    self.logger.warning(
                        "ClassificationChannel: intake request timed out after %.1fs; "
                        "publishing incident"
                        % elapsed_s
                    )
                    self._awaiting_intake_piece = False
                    self._intake_requested_at_mono = None
                    self._intake_requested_at_wall = None
                    self.shared.set_classification_gate(
                        False,
                        reason="intake_request_timeout_incident",
                    )
                    return
                self.logger.warning(
                    "ClassificationChannel: intake request timed out after %.1fs; reopening gate"
                    % elapsed_s
                )
                self._awaiting_intake_piece = False
                self._intake_requested_at_mono = None
                self._intake_requested_at_wall = None
            else:
                self.shared.set_classification_gate(False, reason="awaiting_piece")
                return

        if self._dropApproachBusy():
            self.shared.set_classification_gate(False, reason="drop_approach_busy")
            return

        # The intake guard is wider (90°) than the drop-to-intake distance
        # (85°), so a piece at or near drop would otherwise overlap the
        # intake clearance window and freeze the gate. Drop-committed
        # pieces are physically about to leave the platter via the chute,
        # so exclude their zones from the clearance check AND from the
        # max_zones cap — otherwise max_zones=2 caps at one resident piece
        # whenever there's also a piece in the drop window, defeating the
        # whole point of the cap (one in classification + one at intake).
        active_pieces = self.transport.activePieces()
        drop_committed_uuids = {
            piece.uuid for piece in active_pieces if self._isDropCommitted(piece)
        }
        resident_count = sum(
            1 for piece in active_pieces if piece.uuid not in drop_committed_uuids
        )
        can_request = (
            resident_count < int(self._config.max_zones)
            and zone_manager.is_arc_clear(
                center_deg=self._config.intake_angle_deg,
                body_half_width_deg=self._config.intake_body_half_width_deg,
                hard_guard_deg=self._config.intake_guard_deg,
                ignore_piece_uuids=drop_committed_uuids,
            )
        )
        if not can_request:
            self.shared.set_classification_gate(False, reason="intake_blocked")
            return

        self.shared.set_classification_gate(True, reason=None)
        self.shared.publish_piece_request(
            source=StationId.CLASSIFICATION,
            target=StationId.C3,
            sent_at_mono=now_mono,
        )
        self._awaiting_intake_piece = True
        self._intake_requested_at_mono = now_mono
        self._intake_requested_at_wall = time.time()

    def _shouldHoldForHoodDwell(
        self,
        piece: KnownObject | None,
        now_wall: float,
    ) -> bool:
        if piece is None:
            return False
        if piece.classification_status != ClassificationStatus.pending:
            return False
        start_ts = piece.carousel_detected_confirmed_at or piece.created_at
        return (now_wall - start_ts) * 1000.0 < float(self._config.hood_dwell_ms)

    def _fireRecognition(self, now_wall: float) -> None:
        # Removed the global hasPendingClassifications() short-circuit: with
        # max_zones≥2 it serialised recognition (one in flight at a time)
        # so the second piece on C4 typically rotated past its
        # point_of_no_return before Brickognize was even attempted. The
        # per-piece isPendingClassification check below still prevents the
        # *same* piece from being fired twice. Brickognize is async via
        # background workers and tolerates concurrent calls.

        # Fire as soon as hood_dwell_ms elapsed AND the piece has enough
        # carousel-source crops AND has dwelled on the carousel for at least
        # ``min_carousel_dwell_ms``. The drop-angle deadline in
        # _resolveDeadlines still flips un-classified pieces to unknown as a
        # safety net if they never qualify.
        candidates: list[tuple[float, KnownObject]] = []
        for piece in self.transport.activePieces():
            if piece.classification_status != ClassificationStatus.pending:
                self._recognition_retry_not_before_by_uuid.pop(piece.uuid, None)
                continue
            if self.transport.isPendingClassification(piece.uuid):
                continue
            start_ts = piece.carousel_detected_confirmed_at or piece.created_at
            if (now_wall - start_ts) * 1000.0 < float(self._config.hood_dwell_ms):
                continue
            retry_not_before = self._recognition_retry_not_before_by_uuid.get(piece.uuid)
            if retry_not_before is not None and now_wall < retry_not_before:
                continue
            candidates.append((float(start_ts), piece))

        # Oldest-pending-first so saturated chambers don't starve early arrivals.
        candidates.sort(key=lambda item: item[0])
        if not candidates:
            return

        _start_ts, piece = candidates[0]
        if not self._carouselRecognitionGateClear(piece, now_wall):
            self._recognition_retry_not_before_by_uuid[piece.uuid] = (
                now_wall + RECOGNITION_RETRY_INTERVAL_S
            )
            return

        if piece.carousel_snapping_started_at is None:
            piece.carousel_snapping_started_at = now_wall
        fired = self._recognizer.fire(piece)
        if fired:
            piece.carousel_snapping_completed_at = now_wall
            self._recognition_retry_not_before_by_uuid.pop(piece.uuid, None)
        else:
            self._recognition_retry_not_before_by_uuid[piece.uuid] = (
                now_wall + RECOGNITION_RETRY_INTERVAL_S
            )

    def _carouselRecognitionGateClear(
        self,
        piece: KnownObject,
        now_wall: float,
    ) -> bool:
        """Return True if ``piece`` satisfies the "actually on C4" gate.

        Enforces four checks on top of hood_dwell / cooldown:
          1. Upstream liveness: if the vision layer knows the carousel-side
             ``global_id`` is still alive on ``c_channel_3``, the piece
             hasn't really handed off yet. Skipped if the probe isn't
             available (keeps the gate permissive for hardware setups that
             don't expose ``live_global_ids``).
          2. Carousel crop quota: at least
             ``min_carousel_crops_for_recognize`` crops from the ``carousel``
             source must be available.
          3. Carousel dwell: at least ``min_carousel_dwell_ms`` must have
             elapsed since the first carousel-source observation of this
             piece — guards against a just-spawned carousel track that
             happens to have 2+ history crops inherited via handoff but
             isn't yet stable on the C4 tray.
          4. Carousel traversal: the piece must have moved at least
             ``min_carousel_traversal_deg`` around the carousel since it
             was first seen there. Time-based dwell doesn't guarantee
             viewing-angle diversity when the carousel rotates fast; this
             gate guarantees the accumulated crops cover physically
             distinct sides. Degrades gracefully (skipped) if the current
             or first-seen angle is unavailable so it can't stall forever.
        """
        # TODO: consolidate this liveness probe with the handoff-probe fix
        # once both land on main; right now both go through
        # ``vision.getFeederTrackerLiveGlobalIds`` which already wraps
        # ``PolarFeederTracker.live_global_ids``.
        tracked_gid = getattr(piece, "tracked_global_id", None)
        if (
            isinstance(tracked_gid, int)
            and self.vision is not None
            and hasattr(self.vision, "getFeederTrackerLiveGlobalIds")
        ):
            try:
                c3_live = self.vision.getFeederTrackerLiveGlobalIds("c_channel_3")
                carousel_live = self.vision.getFeederTrackerLiveGlobalIds("carousel")
            except Exception:
                c3_live = set()
                carousel_live = set()
            if int(tracked_gid) in c3_live and int(tracked_gid) not in carousel_live:
                self.gc.runtime_stats.observeRecognizerCounter(
                    "recognize_skipped_not_on_carousel"
                )
                return False

        min_crops = int(
            getattr(self._config, "min_carousel_crops_for_recognize", 2)
        )
        if min_crops > 0:
            carousel_count = self._recognizer.countCarouselCrops(piece)
            if carousel_count < min_crops:
                self.gc.runtime_stats.observeRecognizerCounter(
                    "recognize_skipped_carousel_quota"
                )
                return False

        min_dwell_ms = float(
            getattr(self._config, "min_carousel_dwell_ms", 0)
        )
        if min_dwell_ms > 0.0:
            first_seen = getattr(piece, "first_carousel_seen_ts", None)
            if not isinstance(first_seen, (int, float)):
                self.gc.runtime_stats.observeRecognizerCounter(
                    "recognize_skipped_carousel_dwell"
                )
                return False
            if (now_wall - float(first_seen)) * 1000.0 < min_dwell_ms:
                self.gc.runtime_stats.observeRecognizerCounter(
                    "recognize_skipped_carousel_dwell"
                )
                return False

        min_traversal_deg = float(
            getattr(self._config, "min_carousel_traversal_deg", 0.0)
        )
        if min_traversal_deg > 0.0:
            first_angle = getattr(piece, "first_carousel_seen_angle_deg", None)
            current_angle = getattr(
                piece, "classification_channel_zone_center_deg", None
            )
            # Degrade gracefully: if either angle is missing (tracker dropped
            # or piece just registered this tick), skip the check rather
            # than blocking forever — the point_of_no_return deadline in
            # _resolveDeadlines is the safety net that flips unclassified
            # pieces to unknown if they never pass the gate.
            if isinstance(first_angle, (int, float)) and isinstance(
                current_angle, (int, float)
            ):
                traversal = abs(
                    _circular_diff_deg(
                        float(current_angle),
                        float(first_angle),
                    )
                )
                if traversal < min_traversal_deg:
                    self.gc.runtime_stats.observeRecognizerCounter(
                        "recognize_skipped_carousel_traversal"
                    )
                    return False

        return True

    def _resolveDeadlines(
        self,
        zones: list[ExclusionZone],
        now_wall: float,
    ) -> None:
        point_of_no_return_deg = float(self._config.point_of_no_return_deg)
        drop_clearance_deg = self._dropClearanceWindowDeg()
        zone_manager = self.transport.zone_manager
        for zone in zones:
            piece = self._pieceForUUID(zone.piece_uuid)
            if piece is None:
                continue
            near_drop_deadline = abs(
                _circular_diff_deg(zone.center_deg, self._config.drop_angle_deg)
            ) <= (
                point_of_no_return_deg
                + zone.body_half_width_deg
            )
            if near_drop_deadline:
                # T9 fix for persistent-ghost-at-drop: only pin the track
                # against the stagnant-false-track filter while the piece
                # is still a viable classification candidate. An
                # ``unknown`` piece (POR-expired without recognition) is
                # about to be dumped anyway; if the underlying track was
                # a ghost (camera sees a static feature at drop angle, no
                # physical piece), pinning it here lets the ghost survive
                # the drop pulse and re-spawn forever — the static feature
                # gets re-detected every frame, the polar tracker creates
                # a fresh global_id, the state machine marks it pending,
                # repeat. Leaving unknown pieces unprotected lets the
                # stagnant filter purge the ghost track and the ghost
                # cycle breaks.
                gid = getattr(piece, "tracked_global_id", None)
                if (
                    isinstance(gid, int)
                    and self.vision is not None
                    and piece.classification_status != ClassificationStatus.unknown
                ):
                    marker = getattr(self.vision, "markCarouselPendingDrop", None)
                    if marker is not None:
                        marker(gid)
            interferers: list[tuple[str, float]] = []
            if zone_manager is not None:
                interferers = zone_manager.pieces_in_body_window_with_offsets(
                    center_deg=self._config.drop_angle_deg,
                    tolerance_deg=drop_clearance_deg,
                    ignore_piece_uuid=zone.piece_uuid,
                )
            drop_conflict = bool(interferers)
            if near_drop_deadline and drop_conflict:
                leader_offset = _circular_diff_deg(
                    zone.center_deg, self._config.drop_angle_deg
                )
                if self._leaderWinsAllowed(piece, leader_offset, interferers):
                    self.gc.runtime_stats.observeMultiDropLeaderWins(
                        reason="point_of_no_return_collision"
                    )
                    # Leader still gets dropped; trailer stays pending for
                    # its own cycle. Skip the collision fail for both.
                    continue
                self._applyFallback(
                    piece,
                    ClassificationStatus.multi_drop_fail,
                    now_wall=now_wall,
                    reason="point_of_no_return_collision",
                )
                continue
            if (
                piece.classification_status
                in {ClassificationStatus.pending, ClassificationStatus.classifying}
                and near_drop_deadline
            ):
                self._applyFallback(
                    piece,
                    ClassificationStatus.unknown,
                    now_wall=now_wall,
                    reason="point_of_no_return_unclassified",
                )

    def _refreshPositioningPiece(self) -> None:
        candidates: list[tuple[float, float, str]] = []
        for piece in self.transport.activePieces():
            if piece.classification_status not in {
                ClassificationStatus.classified,
                ClassificationStatus.unknown,
                ClassificationStatus.not_found,
                ClassificationStatus.multi_drop_fail,
            }:
                continue
            center_deg = piece.classification_channel_zone_center_deg
            if center_deg is None:
                continue
            distance = abs(_circular_diff_deg(center_deg, self._config.drop_angle_deg))
            if distance > float(self._config.positioning_window_deg):
                continue
            candidates.append((distance, piece.uuid))
        candidates.sort(key=lambda item: item[0])
        self.transport.setPositioningPiece(candidates[0][1] if candidates else None)

    def _pickDropCandidate(self) -> str | None:
        zone_manager = self.transport.zone_manager
        if zone_manager is None:
            return None
        candidate_uuids = zone_manager.pieces_centered_in_window(
            center_deg=self._config.drop_angle_deg,
            tolerance_deg=self._config.drop_tolerance_deg,
        )
        if not candidate_uuids:
            return None
        piece_uuid = zone_manager.closest_piece_to_angle(
            center_deg=self._config.drop_angle_deg,
            max_distance_deg=self._config.drop_tolerance_deg,
        )
        if piece_uuid is None:
            return None

        zone = zone_manager.zone_for_piece(piece_uuid)
        piece = self._pieceForUUID(piece_uuid)
        if zone is None or piece is None:
            return None
        interferers = zone_manager.pieces_in_body_window_with_offsets(
            center_deg=self._config.drop_angle_deg,
            tolerance_deg=self._dropClearanceWindowDeg(),
            ignore_piece_uuid=piece_uuid,
        )
        if interferers:
            leader_offset = _circular_diff_deg(
                zone.center_deg, self._config.drop_angle_deg
            )
            if self._leaderWinsAllowed(piece, leader_offset, interferers):
                self.gc.runtime_stats.observeMultiDropLeaderWins(
                    reason="drop_window_collision"
                )
                # Fall through to the classified/unknown gate below; the
                # trailer keeps its current status and gets its own cycle.
            else:
                self._applyFallback(
                    piece,
                    ClassificationStatus.multi_drop_fail,
                    now_wall=time.time(),
                    reason="drop_window_collision",
                )
                for interfering_uuid, _offset in interferers:
                    interfering_piece = self._pieceForUUID(interfering_uuid)
                    if interfering_piece is None:
                        continue
                    self._applyFallback(
                        interfering_piece,
                        ClassificationStatus.multi_drop_fail,
                        now_wall=time.time(),
                        reason="drop_window_collision",
                    )
        if piece.classification_status in {
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        }:
            self._applyFallback(
                piece,
                ClassificationStatus.unknown,
                now_wall=time.time(),
                reason="drop_deadline_unclassified",
            )
        if piece.classification_status not in {
            ClassificationStatus.classified,
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
            ClassificationStatus.multi_drop_fail,
        }:
            return None
        # Pin the carousel track against the stagnant-false-track filter so
        # the piece — which will stop at the drop zone for up to a few
        # seconds waiting for distribution_ready — is not culled mid-wait.
        gid = getattr(piece, "tracked_global_id", None)
        if isinstance(gid, int) and self.vision is not None:
            marker = getattr(self.vision, "markCarouselPendingDrop", None)
            if marker is not None:
                marker(gid)
        return piece_uuid

    def _applyFallback(
        self,
        piece: KnownObject,
        status: ClassificationStatus,
        *,
        now_wall: float,
        reason: str,
    ) -> None:
        if piece.classification_status == status:
            return
        if status != ClassificationStatus.multi_drop_fail and piece.classification_status in {
            ClassificationStatus.classified,
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
            ClassificationStatus.multi_drop_fail,
        }:
            return
        if (
            status == ClassificationStatus.multi_drop_fail
            and piece.classification_status == ClassificationStatus.multi_drop_fail
        ):
            return
        if not self.transport.resolveFallbackClassification(piece.uuid, status=status):
            return
        self._recognition_retry_not_before_by_uuid.pop(piece.uuid, None)
        # Release the pending-drop protection on the underlying carousel
        # track when the piece becomes a non-pending terminal (unknown /
        # multi_drop_fail). If the track was actually a ghost from a static
        # platter feature, this lets the stagnant-false-track filter purge
        # it instead of letting the ghost survive each drop pulse and
        # re-spawn with a fresh global_id forever.
        if status in {ClassificationStatus.unknown, ClassificationStatus.multi_drop_fail}:
            gid = getattr(piece, "tracked_global_id", None)
            if isinstance(gid, int) and self.vision is not None:
                unmarker = getattr(self.vision, "unmarkCarouselPendingDrop", None)
                if unmarker is not None:
                    try:
                        unmarker(gid)
                    except Exception:
                        pass
        piece.updated_at = now_wall
        self.gc.runtime_stats.observeBlockedReason("classification", reason)
        publish_classification_fallback_incident(
            self.gc,
            piece=piece,
            status=status,
            reason=reason,
        )
        if self.event_queue is not None:
            self.event_queue.put(knownObjectToEvent(piece))
        self.logger.warning(
            "ClassificationChannel: %s -> %s (%s)"
            % (piece.uuid[:8], status.value, reason)
        )

    def _dropApproachWindowDeg(self) -> float:
        """Half-width of the drop-approach window — the angular distance
        from drop within which a piece is considered close enough to drop
        that the intake gate should react to it.
        """
        return max(
            float(self._config.point_of_no_return_deg) + 8.0,
            float(self._config.positioning_window_deg) * 0.7,
        )

    def _isDropCommitted(self, piece) -> bool:
        """A piece is drop-committed once its center has entered the
        point-of-no-return window of the drop angle. From that moment on
        braking can no longer cancel the drop — the only outcomes are
        pulse-drop, exit-release shimmy, or multi_drop_fail. Drop-
        committed pieces must NOT block intake: drop-to-intake distance
        is only 85°, less than the 90° intake_guard alone, so a piece
        committed to dropping would otherwise serialise the platter to
        one piece at a time (matches the config comment in
        ``ClassificationChannelConfig`` that promised this exclusion).

        Uses ``point_of_no_return_deg`` as the symmetric threshold so the
        window stays narrower than ``_dropApproachWindowDeg`` — pieces in
        the wider approach band ``(PoNR, approach]`` are still
        "approaching but not yet committed" and continue to hold intake.
        """
        center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
        if not isinstance(center_deg, (int, float)):
            return False
        distance = abs(
            _circular_diff_deg(float(center_deg), self._config.drop_angle_deg)
        )
        return distance <= float(self._config.point_of_no_return_deg)

    def _dropApproachBusy(self) -> bool:
        approach_window_deg = self._dropApproachWindowDeg()
        for piece in self.transport.activePieces():
            center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
            if not isinstance(center_deg, (int, float)):
                continue
            # Already-committed pieces are handled by the intake-arc
            # clearance exclusion below; only freshly-approaching pieces
            # (not yet past point-of-no-return) should hold intake.
            if self._isDropCommitted(piece):
                continue
            if (
                abs(_circular_diff_deg(float(center_deg), self._config.drop_angle_deg))
                <= approach_window_deg
            ):
                return True
        return False

    def _dropClearanceWindowDeg(self) -> float:
        return max(5.0, min(float(self._config.drop_tolerance_deg) * 0.5, 8.0))

    def _leaderWinsAllowed(
        self,
        leader: KnownObject,
        leader_offset_deg: float,
        interferers: list[tuple[str, float]],
    ) -> bool:
        """Return True if the leader may drop alone, sparing the trailer(s).

        Conditions (all must hold):
          * ``leader_wins_policy`` config is enabled
          * If ``leader_wins_requires_classified`` is set, the leader must
            have ``classification_status == classified`` with a ``part_id``
          * Exactly one interferer
          * Interferer is strictly BEHIND the leader (more negative offset
            w.r.t. drop, i.e. still on the approach side in carousel
            rotation direction)
          * Interferer does not share the leader's body within a tight
            "shared body overlap" of half the drop-clearance window — this
            guards against a trailer that's effectively kissing the leader
            where one carousel pulse would bump both.
        """
        cfg = self._config
        if not bool(getattr(cfg, "leader_wins_policy", True)):
            return False
        if bool(getattr(cfg, "leader_wins_requires_classified", True)):
            if leader.classification_status != ClassificationStatus.classified:
                return False
            if not getattr(leader, "part_id", None):
                return False
        if len(interferers) != 1:
            return False
        _interferer_uuid, interferer_offset = interferers[0]
        relative = float(interferer_offset) - float(leader_offset_deg)
        # Interferer must be strictly behind leader (approach side = more
        # negative offset relative to drop angle).
        if relative >= 0.0:
            return False
        shared_body_overlap_deg = self._dropClearanceWindowDeg() * 0.5
        if abs(relative) < shared_body_overlap_deg:
            return False
        return True

    def _pickExitReleaseCandidate(self) -> str | None:
        """Pick a stuck-at-exit piece that needs active release.

        ``_pickDropCandidate`` only considers pieces whose center is inside
        the configured drop tolerance. Sticky tires can roll just past that
        line without falling; this scan keeps the exit obstruction in the C4
        state machine and lets the shimmy path shake it loose.
        """
        droppable_statuses = {
            ClassificationStatus.classified,
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
            ClassificationStatus.multi_drop_fail,
        }
        candidates: list[tuple[float, str]] = []
        for piece in self.transport.activePieces():
            if piece.classification_status not in droppable_statuses:
                continue
            meta = self._exitReleaseTriggerMeta(piece)
            if meta is None:
                continue
            offset = abs(float(meta["center_offset_deg"]))
            overlap = float(meta["overlap_ratio"])
            center_crossed_bonus = 1.0 if bool(meta["center_crossed"]) else 0.0
            candidates.append((-(center_crossed_bonus + overlap), offset, piece.uuid))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _exitReleaseTriggerMeta(self, piece: KnownObject) -> dict[str, float | bool] | None:
        center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
        half_width_deg = self._exitReleaseHalfWidthDeg(piece)
        if not isinstance(center_deg, (int, float)) or half_width_deg is None:
            return None
        center_offset = _circular_diff_deg(float(center_deg), self._config.drop_angle_deg)
        body_half = max(0.0, float(half_width_deg))
        obstruction_horizon = max(
            float(self._config.drop_tolerance_deg),
            float(self._config.point_of_no_return_deg) + body_half,
        )
        if abs(center_offset) > obstruction_horizon:
            return None
        overlap_ratio = self._dropBodyOverlapRatio(piece)
        overlap_trigger = overlap_ratio >= float(self._config.exit_release_overlap_ratio)
        center_crossed = center_offset >= 0.0
        if not overlap_trigger and not center_crossed:
            return None
        return {
            "center_offset_deg": center_offset,
            "overlap_ratio": overlap_ratio,
            "center_crossed": center_crossed,
        }

    def _exitReleaseHalfWidthDeg(self, piece: KnownObject) -> float | None:
        zone_manager = self.transport.zone_manager
        if zone_manager is not None and hasattr(zone_manager, "zone_for_piece"):
            try:
                zone = zone_manager.zone_for_piece(piece.uuid)
            except Exception:
                zone = None
            measured = getattr(zone, "measured_half_width_deg", None)
            if isinstance(measured, (int, float)) and float(measured) > 0.0:
                return float(measured)
        half_width_deg = getattr(piece, "classification_channel_zone_half_width_deg", None)
        if isinstance(half_width_deg, (int, float)):
            return float(half_width_deg)
        return None

    def _dropBodyOverlapRatio(self, piece: KnownObject) -> float:
        center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
        half_width_deg = self._exitReleaseHalfWidthDeg(piece)
        if not isinstance(center_deg, (int, float)) or half_width_deg is None:
            return 0.0
        body_half = max(0.0, float(half_width_deg))
        if body_half <= 0.0:
            return 0.0
        center_rel = _circular_diff_deg(float(center_deg), self._config.drop_angle_deg)
        body_start = center_rel - body_half
        body_end = center_rel + body_half
        window_half = max(0.0, float(self._config.drop_tolerance_deg))
        window_start = -window_half
        window_end = window_half
        overlap = max(0.0, min(body_end, window_end) - max(body_start, window_start))
        return overlap / max(body_half * 2.0, 1e-6)

    def _exitReleaseStages(self) -> tuple[_ExitReleaseStage, ...]:
        raw_stages = getattr(self._config, "exit_release_shimmy_stages", None)
        stages: list[_ExitReleaseStage] = []
        if isinstance(raw_stages, (list, tuple)):
            for index, stage in enumerate(raw_stages):
                name = str(getattr(stage, "name", f"stage-{index + 1}"))
                amplitude = getattr(stage, "amplitude_output_deg", None)
                cycles = getattr(stage, "cycles", None)
                speed = getattr(stage, "microsteps_per_second", None)
                acceleration = getattr(
                    stage,
                    "acceleration_microsteps_per_second_sq",
                    None,
                )
                settle_ms = getattr(stage, "settle_ms", None)
                if not isinstance(amplitude, (int, float)) or float(amplitude) <= 0.0:
                    continue
                if not isinstance(cycles, int) or cycles <= 0:
                    continue
                if not isinstance(speed, int) or speed <= 0:
                    continue
                if not isinstance(acceleration, int) or acceleration <= 0:
                    continue
                if not isinstance(settle_ms, int) or settle_ms < 0:
                    continue
                stages.append(
                    _ExitReleaseStage(
                        name=name,
                        amplitude_output_deg=float(amplitude),
                        cycles=int(cycles),
                        speed=int(speed),
                        acceleration=int(acceleration),
                        settle_ms=int(settle_ms),
                    )
                )
        return tuple(stages) or DEFAULT_EXIT_RELEASE_STAGES

    def _buildExitReleasePlan(
        self,
        piece_uuid: str,
    ) -> tuple[int, _ExitReleaseStage, list[_ExitReleaseStroke]]:
        stages = self._exitReleaseStages()
        attempt = max(0, int(self._exit_release_attempt_by_uuid.get(piece_uuid, 0)))
        stage_index = min(attempt, len(stages) - 1)
        stage = stages[stage_index]
        stepper_per_output = getattr(
            self._config,
            "exit_release_shimmy_stepper_per_output_deg",
            DEFAULT_EXIT_RELEASE_STEPPER_PER_OUTPUT_DEG,
        )
        if not isinstance(stepper_per_output, (int, float)) or float(stepper_per_output) <= 0.0:
            stepper_per_output = DEFAULT_EXIT_RELEASE_STEPPER_PER_OUTPUT_DEG
        amplitude_deg = float(stage.amplitude_output_deg) * float(stepper_per_output)
        strokes: list[_ExitReleaseStroke] = []
        for cycle in range(1, int(stage.cycles) + 1):
            for suffix, move_deg in (
                ("cw", amplitude_deg),
                ("ccw-cross", -2.0 * amplitude_deg),
                ("cw-return", amplitude_deg),
            ):
                strokes.append(
                    _ExitReleaseStroke(
                        label=f"{stage.name}.{cycle}.{suffix}",
                        move_deg=float(move_deg),
                        speed=int(stage.speed),
                        acceleration=int(stage.acceleration),
                        settle_s=max(0.0, float(stage.settle_ms) / 1000.0),
                    )
                )
        return stage_index, stage, strokes

    def _exitReleaseReviewEnabled(self) -> bool:
        return bool(getattr(self._config, "exit_release_review_pause_enabled", False)) and not self._exitReleaseIncidentOff()

    def _exitReleaseIncidentOff(self) -> bool:
        try:
            from toml_config import incidentHandlingOff

            return bool(incidentHandlingOff("classification_exit_release"))
        except Exception:
            return False

    def _exitReleaseIncidentAutomatic(self) -> bool:
        try:
            from toml_config import incidentHandlingAutomatic

            return bool(incidentHandlingAutomatic("classification_exit_release"))
        except Exception:
            return False

    def _exitReleaseIncidentPayload(
        self,
        review: _ExitReleaseReview,
        *,
        status: str,
    ) -> dict[str, Any]:
        stage = review.stage
        first_stroke = review.plan[0] if review.plan else None
        drop_angle = float(getattr(self._config, "drop_angle_deg", 0.0))
        drop_tolerance = max(0.0, float(getattr(self._config, "drop_tolerance_deg", 0.0)))
        return {
            "kind": "exit_stuck",
            "source_kind": "classification_exit_release",
            "severity": "critical",
            "status": status,
            "awaiting_operator": status == "waiting_for_operator",
            "scope": "classification",
            "channel": "c4",
            "role": "classification_channel",
            "channel_label": "C4",
            "piece_uuid": review.piece_uuid,
            "piece_short_uuid": review.piece_uuid[:8],
            "triggered_at": review.triggered_at_wall,
            "exit_midpoint_deg": drop_angle % 360.0,
            "exit_window_start_deg": (drop_angle - drop_tolerance) % 360.0,
            "exit_window_end_deg": (drop_angle + drop_tolerance) % 360.0,
            "center_offset_deg": float(review.trigger.get("center_offset_deg", 0.0)),
            "overlap_ratio": float(review.trigger.get("overlap_ratio", 0.0)),
            "center_crossed": bool(review.trigger.get("center_crossed", False)),
            "stage_index": int(review.stage_index),
            "stage_count": int(review.stage_count),
            "stage_number": int(review.stage_index) + 1,
            "stage_name": stage.name,
            "amplitude_output_deg": float(stage.amplitude_output_deg),
            "cycles": int(stage.cycles),
            "microsteps_per_second": int(stage.speed),
            "acceleration_microsteps_per_second_sq": int(stage.acceleration),
            "settle_ms": int(stage.settle_ms),
            "first_stroke_stepper_deg": float(first_stroke.move_deg) if first_stroke else None,
            "plan_preview_stepper_deg": [
                float(stroke.move_deg)
                for stroke in review.plan[: min(6, len(review.plan))]
            ],
            "plan_stroke_count": len(review.plan),
        }

    def _publishExitReleaseIncident(
        self,
        review: _ExitReleaseReview,
        *,
        status: str,
    ) -> None:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
            return
        runtime_stats.setActiveIncident(
            self._exitReleaseIncidentPayload(review, status=status)
        )

    def _beginExitReleaseIncidentReview(
        self,
        piece_uuid: str,
        trigger: dict[str, float | bool],
        stage_index: int,
        stage: _ExitReleaseStage,
        plan: list[_ExitReleaseStroke],
    ) -> bool:
        existing = self._exit_release_review
        automatic = self._exitReleaseIncidentAutomatic()
        if (
            existing is not None
            and existing.piece_uuid == piece_uuid
            and existing.stage_index == stage_index
        ):
            existing.trigger = dict(trigger)
            if automatic:
                existing.approved = True
            self._publishExitReleaseIncident(
                existing,
                status="approved" if existing.approved else "waiting_for_operator",
            )
        else:
            review = _ExitReleaseReview(
                piece_uuid=piece_uuid,
                stage_index=stage_index,
                stage_count=len(self._exitReleaseStages()),
                stage=stage,
                plan=list(plan),
                trigger=dict(trigger),
                triggered_at_wall=time.time(),
                approved=automatic,
            )
            self._exit_release_review = review
            self.logger.warning(
                "ClassificationChannel: exit incident for %s; %s release "
                "stage %d/%d %s (offset %.1f deg, overlap %.2f)"
                % (
                    piece_uuid[:8],
                    "auto-approving" if automatic else "waiting before",
                    stage_index + 1,
                    review.stage_count,
                    stage.name,
                    float(trigger["center_offset_deg"]),
                    float(trigger["overlap_ratio"]),
                )
            )
            self._publishExitReleaseIncident(
                review,
                status="approved" if automatic else "waiting_for_operator",
            )
        self.shared.set_classification_gate(False, reason="exit_incident_review")
        return True

    def _holdForExitReleaseIncidentReview(self) -> bool:
        review = self._exit_release_review
        if review is None:
            return False

        self.shared.set_classification_gate(False, reason="exit_incident_review")
        self.gc.runtime_stats.observeBlockedReason(
            "classification",
            "exit_incident_review",
        )
        if review.approved:
            if self._startExitReleaseShimmyIfNeeded(review.piece_uuid):
                if self._exit_release_review is None:
                    self._setOccupancyState("classification_channel.exit_release_shimmy")
                else:
                    self._setOccupancyState("classification_channel.exit_incident_review")
                return True

            review.approved = False

        self._publishExitReleaseIncident(review, status="waiting_for_operator")
        self._setOccupancyState("classification_channel.exit_incident_review")
        return True

    def _clearExitReleaseIncident(self, piece_uuid: str | None = None) -> None:
        review = self._exit_release_review
        active_piece_uuid = piece_uuid or (review.piece_uuid if review is not None else None)
        self._exit_release_review = None
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
            runtime_stats.clearActiveIncident(
                kind="exit_stuck",
                piece_uuid=active_piece_uuid,
            )

    def exitReleaseIncidentSnapshot(self) -> dict[str, Any] | None:
        review = self._exit_release_review
        if review is None:
            return None
        return self._exitReleaseIncidentPayload(
            review,
            status="approved" if review.approved else "waiting_for_operator",
        )

    def approveExitReleaseIncident(self, piece_uuid: str | None = None) -> dict[str, Any]:
        review = self._exit_release_review
        if review is None:
            raise RuntimeError("No classification-channel exit incident is waiting.")
        if piece_uuid is not None and piece_uuid != review.piece_uuid:
            raise ValueError("The active exit incident belongs to a different piece.")
        review.approved = True
        self._publishExitReleaseIncident(review, status="approved")
        return self._exitReleaseIncidentPayload(review, status="approved")

    def testExitReleaseIncident(
        self,
        *,
        piece_uuid: str | None = None,
        amplitude_output_deg: float,
        microsteps_per_second: int,
        cycles: int = 1,
        acceleration_microsteps_per_second_sq: int | None = None,
    ) -> dict[str, Any]:
        review = self._exit_release_review
        if review is None:
            raise RuntimeError("No classification-channel exit incident is waiting.")
        if piece_uuid is not None and piece_uuid != review.piece_uuid:
            raise ValueError("The active exit incident belongs to a different piece.")
        if self._exit_release_drop_uuid is not None or self._exit_release_plan:
            raise RuntimeError("An exit-release motion is already running.")
        if not self.irl.carousel_stepper.stopped:
            raise RuntimeError("The classification-channel stepper is still moving.")

        amplitude_output = float(amplitude_output_deg)
        if amplitude_output < 0.1 or amplitude_output > 12.0:
            raise ValueError("amplitude_output_deg must be between 0.1 and 12.0.")
        speed = int(microsteps_per_second)
        if speed < 100 or speed > 16000:
            raise ValueError("microsteps_per_second must be between 100 and 16000.")
        cycle_count = int(cycles)
        if cycle_count < 1 or cycle_count > 20:
            raise ValueError("cycles must be between 1 and 20.")
        if acceleration_microsteps_per_second_sq is None:
            acceleration = max(1000, min(48000, int(round(speed * 3.0))))
        else:
            acceleration = int(acceleration_microsteps_per_second_sq)
            if acceleration < 1000 or acceleration > 48000:
                raise ValueError(
                    "acceleration_microsteps_per_second_sq must be between 1000 and 48000."
                )

        stepper_per_output = getattr(
            self._config,
            "exit_release_shimmy_stepper_per_output_deg",
            DEFAULT_EXIT_RELEASE_STEPPER_PER_OUTPUT_DEG,
        )
        if not isinstance(stepper_per_output, (int, float)) or float(stepper_per_output) <= 0.0:
            stepper_per_output = DEFAULT_EXIT_RELEASE_STEPPER_PER_OUTPUT_DEG
        amplitude_stepper = amplitude_output * float(stepper_per_output)
        plan: list[_ExitReleaseStroke] = []
        for cycle in range(1, cycle_count + 1):
            is_last_cycle = cycle == cycle_count
            plan.extend(
                [
                    _ExitReleaseStroke(
                        f"manual-test.{cycle}.cw",
                        amplitude_stepper,
                        speed,
                        acceleration,
                        0.12,
                    ),
                    _ExitReleaseStroke(
                        f"manual-test.{cycle}.ccw-cross",
                        -2.0 * amplitude_stepper,
                        speed,
                        acceleration,
                        0.12,
                    ),
                    _ExitReleaseStroke(
                        f"manual-test.{cycle}.cw-return",
                        amplitude_stepper,
                        speed,
                        acceleration,
                        0.0 if is_last_cycle else 0.12,
                    ),
                ]
            )
        self._exit_release_plan = plan
        self._exit_release_drop_uuid = review.piece_uuid
        self._exit_release_manual_test = True
        self._exit_release_next_move_not_before_mono = 0.0
        self._publishExitReleaseIncident(review, status="manual_test_running")
        self.logger.info(
            "ClassificationChannel: manual exit-release test for %s output_amp %.2f deg "
            "cycles %d speed %d usteps/s"
            % (review.piece_uuid[:8], amplitude_output, cycle_count, speed)
        )
        return {
            "piece_uuid": review.piece_uuid,
            "amplitude_output_deg": amplitude_output,
            "cycles": cycle_count,
            "first_stroke_stepper_deg": amplitude_stepper,
            "microsteps_per_second": speed,
            "acceleration_microsteps_per_second_sq": acceleration,
            "stroke_count": len(self._exit_release_plan),
        }

    def clearExitReleaseIncident(self, piece_uuid: str | None = None) -> dict[str, Any]:
        review = self._exit_release_review
        if review is None:
            runtime_stats = getattr(self.gc, "runtime_stats", None)
            if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
                runtime_stats.clearActiveIncident(kind="exit_stuck")
            return {"ok": True, "cleared": False, "reason": "no_active_incident"}
        if piece_uuid is not None and piece_uuid != review.piece_uuid:
            raise ValueError("The active exit incident belongs to a different piece.")
        cleared_uuid = review.piece_uuid
        self._clearExitReleaseIncident(cleared_uuid)
        return {"ok": True, "cleared": True, "piece_uuid": cleared_uuid}

    def _startExitReleaseShimmyIfNeeded(
        self,
        piece_uuid: str,
        *,
        review_allowed: bool = True,
    ) -> bool:
        if self._sampleCollectionMode():
            return False
        piece = self._pieceForUUID(piece_uuid)
        if piece is None:
            return False
        trigger = self._exitReleaseTriggerMeta(piece)
        if trigger is None:
            return False
        if self._exit_release_drop_uuid == piece_uuid or self._exit_release_plan:
            return True
        stage_index, stage, plan = self._buildExitReleasePlan(piece_uuid)
        if not plan:
            return False
        review = self._exit_release_review
        if review_allowed and self._exitReleaseReviewEnabled():
            if review is not None and review.piece_uuid == piece_uuid and review.approved:
                stage_index = review.stage_index
                stage = review.stage
                plan = list(review.plan)
                self._publishExitReleaseIncident(review, status="running")
                self._exit_release_review = None
            else:
                return self._beginExitReleaseIncidentReview(
                    piece_uuid,
                    trigger,
                    stage_index,
                    stage,
                    plan,
                )
        self._exit_release_drop_uuid = piece_uuid
        self._exit_release_plan = plan
        self._exit_release_next_move_not_before_mono = 0.0
        self._exit_release_attempt_by_uuid[piece_uuid] = stage_index + 1
        self.logger.info(
            "ClassificationChannel: exit-release shimmy stage %d/%d %s for %s "
            "(output_amp %.2f deg, cycles %d, offset %.1f deg, overlap %.2f, center_crossed=%s)"
            % (
                stage_index + 1,
                len(self._exitReleaseStages()),
                stage.name,
                piece_uuid[:8],
                float(stage.amplitude_output_deg),
                int(stage.cycles),
                float(trigger["center_offset_deg"]),
                float(trigger["overlap_ratio"]),
                bool(trigger["center_crossed"]),
            )
        )
        return self._advanceExitReleaseShimmy()

    def _advanceExitReleaseShimmy(self, now_mono: float | None = None) -> bool:
        if self._sampleCollectionMode():
            self._exit_release_plan = []
            return False
        if not self._exit_release_plan:
            return False
        stroke = self._exit_release_plan.pop(0)
        speed = stroke.speed
        if isinstance(speed, int) and speed > 0:
            try:
                self.irl.carousel_stepper.set_speed_limits(16, int(speed))
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not apply exit-release speed: {exc}"
                )
        acceleration = stroke.acceleration
        if isinstance(acceleration, int) and acceleration > 0 and hasattr(
            self.irl.carousel_stepper, "set_acceleration"
        ):
            try:
                self.irl.carousel_stepper.set_acceleration(int(acceleration))
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not apply exit-release acceleration: {exc}"
                )
        if not self.irl.carousel_stepper.move_degrees(stroke.move_deg):
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "classification_channel_exit_release_rejected"
            )
            self._exit_release_plan = []
            self._exit_release_drop_uuid = None
            self._exit_release_manual_test = False
            review = self._exit_release_review
            if review is not None:
                self._publishExitReleaseIncident(review, status="waiting_for_operator")
            return False
        now = time.monotonic() if now_mono is None else now_mono
        self._exit_release_next_move_not_before_mono = now + stroke.settle_s
        self.logger.info(
            "ClassificationChannel: exit-release move %s %.2f deg"
            % (stroke.label, stroke.move_deg)
        )
        return True

    def _captureDropSnapshot(self, drop_uuid: str) -> None:
        """Capture the full classification-chamber frame at drop instant.

        Fires once per piece: if ``drop_snapshot`` is already set we skip so
        the second drop-commit path (exit-release-shimmy finalization vs.
        normal drop) doesn't overwrite a tighter earlier capture. Downsizes
        to ``DROP_SNAPSHOT_MAX_EDGE_PX`` on the longest edge so the WS event
        payload stays reasonable. Silent on any failure — the snapshot is a
        UX nicety, not a correctness requirement.
        """
        piece = self._pieceForUUID(drop_uuid)
        if piece is None or piece.drop_snapshot is not None:
            return
        if self.vision is None:
            return
        capture = getattr(self.vision, "_carousel_capture", None)
        if capture is None:
            return
        latest = getattr(capture, "latest_frame", None)
        raw = getattr(latest, "raw", None) if latest is not None else None
        if raw is None or not isinstance(raw, np.ndarray) or raw.size == 0:
            return
        try:
            frame = raw.copy()
            h, w = frame.shape[:2]
            longest = max(h, w)
            if longest > DROP_SNAPSHOT_MAX_EDGE_PX:
                scale = DROP_SNAPSHOT_MAX_EDGE_PX / float(longest)
                frame = cv2.resize(
                    frame,
                    (int(round(w * scale)), int(round(h * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, DROP_SNAPSHOT_JPEG_QUALITY],
            )
            if not ok:
                return
            piece.drop_snapshot = base64.b64encode(buffer).decode("utf-8")
        except Exception as exc:
            self.logger.debug(
                "ClassificationChannel: drop snapshot capture failed for %s: %s"
                % (drop_uuid[:8], exc)
            )

    def _maybeCaptureSampleModeEmptyState(
        self,
        track_extents: list[TrackAngularExtent],
        zones: list[object],
        now_mono: float,
    ) -> None:
        if track_extents or zones or self.transport.activePieces():
            return
        if (
            self._sample_empty_state_last_captured_mono is not None
            and now_mono - self._sample_empty_state_last_captured_mono
            < SAMPLE_MODE_EMPTY_STATE_CAPTURE_INTERVAL_S
        ):
            return
        if self.vision is None or not hasattr(
            self.vision, "saveClassificationChannelEmptyStateCapture"
        ):
            return
        try:
            if self.vision.saveClassificationChannelEmptyStateCapture():
                self._sample_empty_state_last_captured_mono = now_mono
        except Exception as exc:
            self.logger.warning(
                "ClassificationChannel: could not archive empty-state sample: %s"
                % exc
            )

    def _scheduleSampleModeTeacherCapture(self, pulse_degrees: float) -> None:
        if self.vision is None or not hasattr(
            self.vision, "scheduleClassificationChannelTeacherCaptureAfterMove"
        ):
            return

        now_mono = time.monotonic()
        if (
            self._sample_teacher_capture_last_queued_mono is not None
            and now_mono - self._sample_teacher_capture_last_queued_mono
            < SAMPLE_MODE_TEACHER_CAPTURE_MIN_INTERVAL_S
        ):
            return

        delay_s = 0.0
        estimate_fn = getattr(self.irl.carousel_stepper, "estimateMoveDegreesMs", None)
        if callable(estimate_fn):
            try:
                delay_s = max(0.0, float(estimate_fn(pulse_degrees)) / 1000.0)
            except Exception:
                delay_s = 0.0

        try:
            self.vision.scheduleClassificationChannelTeacherCaptureAfterMove(
                delay_s=delay_s,
                move_label="sample_c4_pulse",
                pulse_degrees=float(pulse_degrees),
            )
            self._sample_teacher_capture_last_queued_mono = now_mono
        except Exception as exc:
            self.logger.warning(
                "ClassificationChannel: could not queue sample teacher capture: %s"
                % exc
            )

    def _sendPulse(self, drop_uuid: str | None) -> bool:
        if self._pulse_in_flight:
            return False
        cfg = self.irl_config.feeder_config.classification_channel_eject
        pulse_degrees = self.irl.carousel_stepper.degrees_for_microsteps(
            cfg.steps_per_pulse
        )
        try:
            speed = sample_collection_effective_speed_microsteps_per_second(
                "classification_channel",
                default_microsteps_per_second=int(cfg.microsteps_per_second),
                microsteps=microsteps_from_stepper_config(
                    getattr(self.irl_config, "c_channel_4_rotor_stepper", None)
                    or getattr(self.irl_config, "carousel_stepper", None),
                    fallback=getattr(self.irl.carousel_stepper, "_microsteps", 8),
                ),
                enabled=bool(getattr(self.shared, "sample_collection_mode", False)),
            )
            self.irl.carousel_stepper.set_speed_limits(
                16, int(speed or cfg.microsteps_per_second)
            )
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: could not apply rotation speed: {exc}"
            )
        acceleration = getattr(
            cfg,
            "acceleration_microsteps_per_second_sq",
            None,
        )
        if acceleration is not None and hasattr(
            self.irl.carousel_stepper,
            "set_acceleration",
        ):
            try:
                self.irl.carousel_stepper.set_acceleration(int(acceleration))
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not apply rotation acceleration: {exc}"
                )
        if not self.irl.carousel_stepper.move_degrees(pulse_degrees):
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "classification_channel_eject_rejected"
            )
            return False
        self._scheduleSampleModeTeacherCapture(pulse_degrees)
        self._pulse_in_flight = True
        self._pending_drop_uuid = drop_uuid
        if drop_uuid is not None:
            self.logger.info(
                "ClassificationChannel: pulse %.1f deg for drop candidate %s"
                % (pulse_degrees, drop_uuid[:8])
            )
        return True

    def _finalizePulse(self, now_mono: float) -> None:
        result = self.transport.advanceTransport(dropped_uuid=self._pending_drop_uuid)
        dropped_piece = result.piece_for_distribution_drop
        if dropped_piece is not None:
            self._recognition_retry_not_before_by_uuid.pop(dropped_piece.uuid, None)
            self._exit_release_attempt_by_uuid.pop(dropped_piece.uuid, None)
            runtime_stats = getattr(self.gc, "runtime_stats", None)
            global_id = getattr(dropped_piece, "tracked_global_id", None)
            if runtime_stats is not None and hasattr(runtime_stats, "observeChannelExit"):
                runtime_stats.observeChannelExit(
                    "classification_channel",
                    exited_at=time.time(),
                    piece_uuid=dropped_piece.uuid,
                    global_id=global_id,
                    classification_status=str(dropped_piece.classification_status.value),
                )
            # The piece is physically gone via the drop chute now. Force the
            # carousel tracker to release the global_id immediately so the
            # next detection in the freed sector doesn't accumulate crops
            # under the dropped piece's identity.
            if global_id is not None and self.vision is not None and hasattr(
                self.vision, "forceKillCarouselTrack"
            ):
                try:
                    self.vision.forceKillCarouselTrack(int(global_id))
                except Exception as exc:
                    self.logger.warning(
                        "ClassificationChannel: force_kill_track(%s) failed: %s"
                        % (global_id, exc)
                    )
            if dropped_piece.carousel_rotated_at is None:
                dropped_piece.carousel_rotated_at = time.time()
            self.logger.info(
                "ClassificationChannel: piece %s dropped into distributor path"
                % dropped_piece.uuid[:8]
            )
            self.shared.set_distribution_gate(False, reason="piece_in_flight")
            self.shared.publish_piece_delivered(
                source=StationId.CLASSIFICATION,
                target=StationId.DISTRIBUTION,
                delivered_at_mono=now_mono,
            )
        self._pulse_in_flight = False
        self._pending_drop_uuid = None

    def _pieceForUUID(self, piece_uuid: str) -> KnownObject | None:
        for piece in self.transport.activePieces():
            if piece.uuid == piece_uuid:
                return piece
        return None
