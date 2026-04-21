from __future__ import annotations

import base64
import time
from typing import Optional

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
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.classification_channel.zone_manager import (
    ExclusionZone,
    TrackAngularExtent,
    _circular_diff_deg,
)
from subsystems.shared_variables import SharedVariables
from utils.event import knownObjectToEvent

INTAKE_REQUEST_TIMEOUT_S = 2.0
# Drop-moment snapshot: max longest edge of the encoded JPEG. Keeps the event
# payload bounded (~80-120 kB per frame) while still being legible on the
# piece detail page next to the Brickognize reference thumbnail.
DROP_SNAPSHOT_MAX_EDGE_PX = 1024
DROP_SNAPSHOT_JPEG_QUALITY = 78
MIN_INTAKE_TRACK_HITS = 2
RECOVERY_MIN_TRACK_HITS = 4
RECOVERY_MIN_TRACK_AGE_S = 0.35
RECOGNITION_RETRY_INTERVAL_S = 0.75
INTAKE_FRESHNESS_GRACE_S = 0.35


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
        self._exit_release_plan_deg: list[float] = []
        self._awaiting_intake_piece = False
        self._intake_requested_at_mono: float | None = None
        self._intake_requested_at_wall: float | None = None
        self._occupancy_state: str | None = None
        self._recognition_retry_not_before_by_uuid: dict[str, float] = {}

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
            if self._advanceExitReleaseShimmy():
                self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None
            drop_uuid = self._exit_release_drop_uuid
            self._exit_release_drop_uuid = None
            if drop_uuid is not None:
                if self._sendPulse(drop_uuid):
                    self._setOccupancyState("classification_channel.drop_commit")
            return None

        track_extents = self._getTrackExtents()
        self._registerNewIntakePiece(track_extents, now_wall, now_mono)
        self._recoverExistingTrackedPieces(track_extents, now_wall)
        zones, expired_pieces = self.transport.updateTrackedPieces(track_extents)
        self._emitExpiredPieceEvents(expired_pieces)
        self._publishOverlay(zones)

        self._resolveDeadlines(zones, now_wall)
        self._refreshPositioningPiece()
        self._updateIntakeGate(now_mono)

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
            if self._startExitReleaseShimmyIfNeeded(drop_uuid):
                self._setOccupancyState("classification_channel.exit_release_shimmy")
                return None
            if self._sendPulse(drop_uuid):
                self._setOccupancyState("classification_channel.drop_commit")
            return None

        hood_piece = self.transport.getPieceAtClassification()
        if self._shouldHoldForHoodDwell(hood_piece, now_wall):
            self._setOccupancyState("classification_channel.hood_dwell")
            return None

        self._fireRecognition(now_wall)

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
        self._exit_release_plan_deg = []
        self._awaiting_intake_piece = False
        self._intake_requested_at_mono = None
        self._intake_requested_at_wall = None
        self._occupancy_state = None
        self._recognition_retry_not_before_by_uuid = {}
        if self.vision is not None and hasattr(
            self.vision, "setClassificationChannelZoneOverlay"
        ):
            self.vision.setClassificationChannelZoneOverlay([])
        self.shared.set_classification_gate(False, reason="cleanup")

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
            if runtime_stats is not None and hasattr(
                runtime_stats, "observeClassificationZoneLost"
            ):
                runtime_stats.observeClassificationZoneLost()
            # Only emit terminal event for pieces the frontend has actually
            # seen as meaningful: classified (has part_id or classified_at) or
            # at least thumbnail'd. Never-classified zone-expiry ghosts have
            # nothing interesting to show — they'd render as orphan "DISTRIBUTED"
            # rows with no crop, no name, no bin. Skip quietly.
            was_meaningful = bool(
                getattr(piece, "part_id", None)
                or getattr(piece, "classified_at", None)
                or getattr(piece, "thumbnail", None)
            )
            if self.event_queue is not None and was_meaningful:
                self.event_queue.put(knownObjectToEvent(piece))
            self.logger.info(
                "ClassificationChannel: expired stale-zone piece %s (track=%s, emitted=%s)"
                % (piece.uuid[:8], getattr(piece, "tracked_global_id", None), was_meaningful)
            )

    def _publishOverlay(self, zones: list[ExclusionZone]) -> None:
        if self.vision is None or not hasattr(
            self.vision, "setClassificationChannelZoneOverlay"
        ):
            return
        self.vision.setClassificationChannelZoneOverlay(
            [zone.to_overlay_payload() for zone in zones],
            intake_angle_deg=self._config.intake_angle_deg,
            drop_angle_deg=self._config.drop_angle_deg,
            drop_tolerance_deg=self._config.drop_tolerance_deg,
            point_of_no_return_deg=self._config.point_of_no_return_deg,
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
                self.logger.warning(
                    "ClassificationChannel: intake request timed out after %.1fs; reopening gate"
                    % (now_mono - self._intake_requested_at_mono)
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

        can_request = (
            len(self.transport.activePieces()) < int(self._config.max_zones)
            and zone_manager.is_arc_clear(
                center_deg=self._config.intake_angle_deg,
                body_half_width_deg=self._config.intake_body_half_width_deg,
                hard_guard_deg=self._config.intake_guard_deg,
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
        if self.transport.hasPendingClassifications():
            return

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
        candidates: list[tuple[float, str]] = []
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
        piece.updated_at = now_wall
        self.gc.runtime_stats.observeBlockedReason("classification", reason)
        if self.event_queue is not None:
            self.event_queue.put(knownObjectToEvent(piece))
        self.logger.warning(
            "ClassificationChannel: %s -> %s (%s)"
            % (piece.uuid[:8], status.value, reason)
        )

    def _dropApproachBusy(self) -> bool:
        active_pieces = self.transport.activePieces()
        if not active_pieces:
            return False
        approach_window_deg = max(
            float(self._config.point_of_no_return_deg) + 8.0,
            float(self._config.positioning_window_deg) * 0.7,
        )
        for piece in active_pieces:
            center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
            if not isinstance(center_deg, (int, float)):
                continue
            if abs(_circular_diff_deg(float(center_deg), self._config.drop_angle_deg)) <= approach_window_deg:
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

    def _dropBodyOverlapRatio(self, piece: KnownObject) -> float:
        center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
        half_width_deg = getattr(piece, "classification_channel_zone_half_width_deg", None)
        if not isinstance(center_deg, (int, float)) or not isinstance(
            half_width_deg, (int, float)
        ):
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

    def _startExitReleaseShimmyIfNeeded(self, piece_uuid: str) -> bool:
        piece = self._pieceForUUID(piece_uuid)
        if piece is None:
            return False
        overlap_ratio = self._dropBodyOverlapRatio(piece)
        if overlap_ratio < float(self._config.exit_release_overlap_ratio):
            return False
        amplitude_deg = float(self._config.exit_release_shimmy_amplitude_deg)
        cycles = int(self._config.exit_release_shimmy_cycles)
        if amplitude_deg <= 0.0 or cycles <= 0:
            return False
        if self._exit_release_drop_uuid == piece_uuid or self._exit_release_plan_deg:
            return True
        self._exit_release_drop_uuid = piece_uuid
        self._exit_release_plan_deg = []
        for _ in range(cycles):
            self._exit_release_plan_deg.extend(
                [-amplitude_deg, amplitude_deg * 2.0, -amplitude_deg]
            )
        self.logger.info(
            "ClassificationChannel: exit-release shimmy for %s (overlap %.2f)"
            % (piece_uuid[:8], overlap_ratio)
        )
        return self._advanceExitReleaseShimmy()

    def _advanceExitReleaseShimmy(self) -> bool:
        if not self._exit_release_plan_deg:
            return False
        move_deg = float(self._exit_release_plan_deg.pop(0))
        cfg = self._config
        speed = getattr(cfg, "exit_release_shimmy_microsteps_per_second", None)
        if isinstance(speed, int) and speed > 0:
            try:
                self.irl.carousel_stepper.set_speed_limits(16, int(speed))
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not apply exit-release speed: {exc}"
                )
        acceleration = getattr(
            cfg,
            "exit_release_shimmy_acceleration_microsteps_per_second_sq",
            None,
        )
        if isinstance(acceleration, int) and acceleration > 0 and hasattr(
            self.irl.carousel_stepper, "set_acceleration"
        ):
            try:
                self.irl.carousel_stepper.set_acceleration(int(acceleration))
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not apply exit-release acceleration: {exc}"
                )
        if not self.irl.carousel_stepper.move_degrees(move_deg):
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "classification_channel_exit_release_rejected"
            )
            self._exit_release_plan_deg = []
            self._exit_release_drop_uuid = None
            return False
        self.logger.info(
            "ClassificationChannel: exit-release move %.2f deg"
            % move_deg
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

    def _sendPulse(self, drop_uuid: str | None) -> bool:
        if self._pulse_in_flight:
            return False
        cfg = self.irl_config.feeder_config.classification_channel_eject
        pulse_degrees = self.irl.carousel_stepper.degrees_for_microsteps(
            cfg.steps_per_pulse
        )
        try:
            self.irl.carousel_stepper.set_speed_limits(
                16, int(cfg.microsteps_per_second)
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
            runtime_stats = getattr(self.gc, "runtime_stats", None)
            if runtime_stats is not None and hasattr(runtime_stats, "observeChannelExit"):
                runtime_stats.observeChannelExit(
                    "classification_channel",
                    exited_at=time.time(),
                    piece_uuid=dropped_piece.uuid,
                    global_id=getattr(dropped_piece, "tracked_global_id", None),
                    classification_status=str(dropped_piece.classification_status.value),
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
