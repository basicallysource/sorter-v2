from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import time
from typing import Optional, TYPE_CHECKING

from defs.known_object import (
    CarouselMotionSample,
    ClassificationStatus,
    KnownObject,
    PieceStage,
)

if TYPE_CHECKING:
    from irl.config import ClassificationChannelConfig
    from subsystems.classification_channel.zone_manager import (
        TrackAngularExtent,
        ZoneManager,
    )


MOTION_SYNC_EMA_ALPHA = 0.35
MOTION_SYNC_LOW_RATIO = 0.85
MOTION_SYNC_HIGH_RATIO = 1.15
MOTION_SYNC_MAX_ABS_RATIO = 3.0
MOTION_SYNC_MIN_DT_S = 0.05
MOTION_SYNC_MIN_PLATTER_DELTA_DEG = 0.75
MOTION_SYNC_SAMPLE_LIMIT = 24
MOTION_SYNC_RESET_CAROUSEL_JUMP_DEG = 120.0


def _normalize_deg(value: float) -> float:
    normalized = float(value) % 360.0
    if normalized < 0.0:
        normalized += 360.0
    return normalized


def _circular_diff_deg(a: float, b: float) -> float:
    return (_normalize_deg(a) - _normalize_deg(b) + 540.0) % 360.0 - 180.0


@dataclass(frozen=True)
class TransportAdvanceResult:
    exiting_piece: KnownObject | None
    piece_at_classification: KnownObject | None
    piece_for_distribution_drop: KnownObject | None


class PieceTransport(ABC):
    @abstractmethod
    def registerIncomingPiece(
        self,
        *,
        tracked_global_id: int | None = None,
    ) -> KnownObject:
        """Create and stage a new piece at this setup's classification input."""

    @abstractmethod
    def advanceTransport(
        self,
        dropped_uuid: str | None = None,
    ) -> TransportAdvanceResult:
        """Advance the hardware transport after its stepper movement completed."""

    @abstractmethod
    def getPieceAtClassification(self) -> KnownObject | None:
        """Return the piece currently occupying the classification station."""

    @abstractmethod
    def getPieceForDistributionPositioning(self) -> KnownObject | None:
        """Return the piece whose target bin should be prepared next."""

    @abstractmethod
    def getPieceForDistributionDrop(self) -> KnownObject | None:
        """Return the piece that has already dropped into the distribution chute."""

    @abstractmethod
    def markPendingClassification(self, obj: KnownObject) -> None:
        """Mark a piece as waiting for asynchronous classification completion."""

    @abstractmethod
    def resolveClassification(
        self,
        uuid: str,
        part_id: Optional[str],
        color_id: str,
        color_name: str,
        confidence: Optional[float] = None,
        *,
        part_name: Optional[str] = None,
        part_category: Optional[str] = None,
    ) -> bool:
        """Write an asynchronous classification result back onto a tracked piece."""

    def getActivePieceCount(self) -> int:
        """Return the number of pieces still staged in this transport."""
        return 0


class ClassificationChannelTransport(PieceTransport):
    """Two-stage transport for the dedicated classification C-channel.

    A single classification-channel pulse advances every staged piece by one
    logical slot:

    - classification hood -> wait zone
    - wait zone -> distribution drop

    This lets the machine free the hood for the next part while a previously
    classified part is already parked near the exit.
    """

    def __init__(self) -> None:
        self._dynamic_mode = False
        self._dynamic_config: "ClassificationChannelConfig | None" = None
        self._zone_manager: ZoneManager | None = None
        self._classification_piece: KnownObject | None = None
        self._wait_piece: KnownObject | None = None
        self._exit_piece: KnownObject | None = None
        self._pending_classifications: dict[str, KnownObject] = {}
        self._active_pieces: dict[str, KnownObject] = {}
        self._piece_uuid_by_track_id: dict[int, str] = {}
        self._recently_dropped_track_origins: dict[int, float] = {}
        self._hood_piece_uuid: str | None = None
        self._positioning_piece_uuid: str | None = None

    @property
    def dynamic_mode(self) -> bool:
        return self._dynamic_mode

    @property
    def zone_manager(self) -> ZoneManager | None:
        return self._zone_manager

    def configureDynamicMode(self, config: "ClassificationChannelConfig") -> None:
        if self._dynamic_mode:
            return
        from subsystems.classification_channel.zone_manager import ZoneManager

        self._dynamic_mode = True
        self._dynamic_config = config
        self._zone_manager = ZoneManager(config)
        self.resetDynamicState()

    def resetDynamicState(self) -> None:
        if not self._dynamic_mode:
            return
        self._classification_piece = None
        self._wait_piece = None
        self._exit_piece = None
        self._pending_classifications = {}
        self._active_pieces = {}
        self._piece_uuid_by_track_id = {}
        self._recently_dropped_track_origins = {}
        self._hood_piece_uuid = None
        self._positioning_piece_uuid = None
        if self._zone_manager is not None:
            self._zone_manager = type(self._zone_manager)(self._dynamic_config)

    def registerIncomingPiece(
        self,
        *,
        tracked_global_id: int | None = None,
    ) -> KnownObject:
        if self._dynamic_mode:
            obj = KnownObject(tracked_global_id=tracked_global_id)
            self._active_pieces[obj.uuid] = obj
            self._hood_piece_uuid = obj.uuid
            if tracked_global_id is not None:
                self._piece_uuid_by_track_id[int(tracked_global_id)] = obj.uuid
            if self._zone_manager is not None:
                self._zone_manager.register_provisional_piece(
                    piece_uuid=obj.uuid,
                    track_global_id=tracked_global_id,
                    classification_status=obj.classification_status,
                    now_mono=time.monotonic(),
                )
            return obj
        obj = KnownObject()
        self._classification_piece = obj
        return obj

    def advanceTransport(
        self,
        dropped_uuid: str | None = None,
    ) -> TransportAdvanceResult:
        if self._dynamic_mode:
            exiting = self._exit_piece
            dropped_piece = None
            if dropped_uuid is not None:
                dropped_piece = self.removePiece(dropped_uuid)
                if dropped_piece is not None and dropped_piece.tracked_global_id is not None:
                    origin_ts = (
                        dropped_piece.feeding_started_at
                        or dropped_piece.carousel_detected_confirmed_at
                        or dropped_piece.first_carousel_seen_ts
                        or dropped_piece.created_at
                        or time.time()
                    )
                    self._recently_dropped_track_origins[
                        int(dropped_piece.tracked_global_id)
                    ] = float(origin_ts)
            self._exit_piece = dropped_piece
            self._hood_piece_uuid = None
            if self._positioning_piece_uuid == dropped_uuid:
                self._positioning_piece_uuid = None
            return TransportAdvanceResult(
                exiting_piece=exiting,
                piece_at_classification=self.getPieceAtClassification(),
                piece_for_distribution_drop=self._exit_piece,
            )
        exiting = self._exit_piece
        self._exit_piece = self._wait_piece
        self._wait_piece = self._classification_piece
        self._classification_piece = None
        return TransportAdvanceResult(
            exiting_piece=exiting,
            piece_at_classification=None,
            piece_for_distribution_drop=self._exit_piece,
        )

    def getPieceAtClassification(self) -> KnownObject | None:
        if self._dynamic_mode:
            if self._hood_piece_uuid is None:
                return None
            return self._active_pieces.get(self._hood_piece_uuid)
        return self._classification_piece

    def getPieceAtWaitZone(self) -> KnownObject | None:
        if self._dynamic_mode:
            if self._positioning_piece_uuid is None:
                return None
            return self._active_pieces.get(self._positioning_piece_uuid)
        return self._wait_piece

    def getPieceForDistributionPositioning(self) -> KnownObject | None:
        if self._dynamic_mode:
            return self.getPieceAtWaitZone()
        return self._wait_piece

    def getPieceForDistributionDrop(self) -> KnownObject | None:
        return self._exit_piece

    def getActivePieceCount(self) -> int:
        if self._dynamic_mode:
            return len(self._active_pieces)
        # ``_exit_piece`` represents a piece that has already been dropped
        # into the distribution chute — it's no longer physically in the
        # classification channel and must not block the feeder's
        # admission gate. The slot only lingers until the next advance
        # overwrites it.
        return sum(
            1
            for piece in (
                self._classification_piece,
                self._wait_piece,
            )
            if piece is not None
        )

    def markPendingClassification(self, obj: KnownObject) -> None:
        self._pending_classifications[obj.uuid] = obj

    def isPendingClassification(self, uuid: str) -> bool:
        return uuid in self._pending_classifications

    def hasPendingClassifications(self) -> bool:
        return bool(self._pending_classifications)

    def resolveClassification(
        self,
        uuid: str,
        part_id: Optional[str],
        color_id: str,
        color_name: str,
        confidence: Optional[float] = None,
        *,
        part_name: Optional[str] = None,
        part_category: Optional[str] = None,
    ) -> bool:
        obj = self._pending_classifications.pop(uuid, None)
        if obj is None:
            return False

        obj.part_id = part_id
        obj.part_name = part_name
        obj.part_category = part_category
        obj.color_id = color_id
        obj.color_name = color_name
        obj.confidence = confidence
        obj.classification_status = (
            ClassificationStatus.classified if part_id else ClassificationStatus.unknown
        )
        obj.classified_at = time.time()
        obj.updated_at = time.time()
        return True

    def resolveFallbackClassification(
        self,
        uuid: str,
        *,
        status: ClassificationStatus,
    ) -> bool:
        obj = self._pending_classifications.pop(uuid, None)
        if obj is None:
            obj = self._active_pieces.get(uuid)
        if obj is None:
            return False
        if obj.classification_status not in {
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        }:
            return False
        obj.part_id = None
        obj.part_name = None
        obj.part_category = None
        obj.color_id = "any_color"
        obj.color_name = "Any Color"
        obj.category_id = None
        obj.destination_bin = None
        obj.confidence = None
        obj.classification_status = status
        obj.classified_at = time.time()
        obj.updated_at = time.time()
        return True

    def activePieces(self) -> list[KnownObject]:
        if not self._dynamic_mode:
            return [
                piece
                for piece in (
                    self._classification_piece,
                    self._wait_piece,
                )
                if piece is not None
            ]
        return sorted(self._active_pieces.values(), key=lambda piece: piece.created_at)

    def pieceForTrack(self, track_global_id: int) -> KnownObject | None:
        piece_uuid = self._piece_uuid_by_track_id.get(int(track_global_id))
        if piece_uuid is None:
            return None
        return self._active_pieces.get(piece_uuid)

    def shouldIgnoreRecoveredTrack(
        self,
        track_global_id: int,
        *,
        first_seen_ts: float | None,
        first_seen_grace_s: float = 1.0,
    ) -> bool:
        """Return True when ``track_global_id`` still belongs to a just-dropped piece.

        Dynamic-mode recovery may try to "adopt" a still-visible tracker extent
        after we removed the original KnownObject from ``_active_pieces`` during
        drop commit. If that lingering extent still carries the same
        ``first_seen_ts`` as the just-dropped track, re-adopting it creates a
        duplicate KnownObject that can deadlock ``Sending`` forever.

        Once the tracker reuses the numeric id for a truly new piece, its
        ``first_seen_ts`` jumps forward and we release the guard automatically.
        """
        origin_ts = self._recently_dropped_track_origins.get(int(track_global_id))
        if origin_ts is None:
            return False
        if not isinstance(first_seen_ts, (int, float)):
            return True
        if float(first_seen_ts) <= float(origin_ts) + max(0.0, float(first_seen_grace_s)):
            return True
        self._recently_dropped_track_origins.pop(int(track_global_id), None)
        return False

    def updateTrackedPieces(
        self,
        track_extents: list[TrackAngularExtent],
        *,
        carousel_angle_deg: float | None = None,
    ) -> tuple[list, list[KnownObject]]:
        if not self._dynamic_mode or self._zone_manager is None:
            return [], []
        pieces_by_track_id = {
            int(track_id): (piece_uuid, piece.classification_status)
            for track_id, piece_uuid in self._piece_uuid_by_track_id.items()
            for piece in [self._active_pieces.get(piece_uuid)]
            if piece is not None
        }
        zones = self._zone_manager.update_from_tracks(
            track_extents=track_extents,
            pieces_by_track_id=pieces_by_track_id,
            now_mono=time.monotonic(),
        )
        tracked_piece_uuids = {zone.piece_uuid for zone in zones}
        expired_piece_uuids = [
            piece_uuid
            for piece_uuid in list(self._active_pieces.keys())
            if piece_uuid not in tracked_piece_uuids
        ]
        expired_pieces: list[KnownObject] = []
        for piece_uuid in expired_piece_uuids:
            piece = self._active_pieces.get(piece_uuid)
            if piece is not None:
                # A zone expiry means tracking truth was lost, not that the
                # piece physically exited. Keep the lifecycle state intact so
                # downstream persistence and throughput metrics do not misread
                # a tracker glitch as a successful distribution.
                now_wall = time.time()
                piece.classification_channel_zone_state = "lost"
                piece.updated_at = now_wall
            removed = self.removePiece(piece_uuid)
            if removed is not None:
                expired_pieces.append(removed)
        for zone in zones:
            piece = self._active_pieces.get(zone.piece_uuid)
            if piece is None:
                continue
            # ``zones`` always derive from the carousel polar tracker — any
            # piece appearing here has at least one carousel-source
            # observation this tick. Record the first such timestamp so the
            # recognizer can gate on "piece has actually been on C4 for a
            # minimum dwell" rather than only on hood_dwell from intake.
            if piece.first_carousel_seen_ts is None:
                piece.first_carousel_seen_ts = time.time()
            # Stamp the angular position alongside the timestamp so the
            # recognizer can gate on angular traversal (viewing-angle
            # diversity) independently of wall-clock dwell.
            if piece.first_carousel_seen_angle_deg is None:
                piece.first_carousel_seen_angle_deg = float(zone.center_deg)
            piece.classification_channel_size_class = zone.size_class
            piece.classification_channel_zone_state = (
                "hard_collision" if zone.hard_collision else ("stale" if zone.stale else "tracked")
            )
            piece.classification_channel_zone_center_deg = zone.center_deg
            piece.classification_channel_zone_half_width_deg = zone.body_half_width_deg
            piece.classification_channel_soft_guard_deg = zone.soft_guard_deg
            piece.classification_channel_hard_guard_deg = zone.hard_guard_deg
            if carousel_angle_deg is not None and zone.track_global_id is not None:
                extent = next(
                    (
                        item
                        for item in track_extents
                        if int(getattr(item, "global_id", -1)) == int(zone.track_global_id)
                    ),
                    None,
                )
                observed_at = (
                    float(extent.last_seen_ts)
                    if extent is not None and isinstance(extent.last_seen_ts, (int, float))
                    else time.time()
                )
                piece.updated_at = observed_at
                self._observeCarouselMotionSync(
                    piece,
                    piece_angle_deg=float(zone.center_deg),
                    carousel_angle_deg=float(carousel_angle_deg),
                    observed_at=observed_at,
                )
            else:
                piece.updated_at = time.time()
        return zones, expired_pieces

    def _observeCarouselMotionSync(
        self,
        piece: KnownObject,
        *,
        piece_angle_deg: float,
        carousel_angle_deg: float,
        observed_at: float,
    ) -> None:
        last_piece_angle = piece._carousel_motion_last_piece_angle_deg
        last_carousel_angle = piece._carousel_motion_last_carousel_angle_deg
        last_observed_at = piece._carousel_motion_last_observed_at

        piece._carousel_motion_last_piece_angle_deg = float(piece_angle_deg)
        piece._carousel_motion_last_carousel_angle_deg = float(carousel_angle_deg)
        piece._carousel_motion_last_observed_at = float(observed_at)

        if last_piece_angle is None or last_carousel_angle is None or last_observed_at is None:
            return

        dt_s = float(observed_at) - float(last_observed_at)
        if not math.isfinite(dt_s) or dt_s < MOTION_SYNC_MIN_DT_S:
            return

        carousel_delta_deg = float(carousel_angle_deg) - float(last_carousel_angle)
        if not math.isfinite(carousel_delta_deg):
            return
        if abs(carousel_delta_deg) >= MOTION_SYNC_RESET_CAROUSEL_JUMP_DEG:
            return
        if abs(carousel_delta_deg) < MOTION_SYNC_MIN_PLATTER_DELTA_DEG:
            return

        piece_delta_deg = _circular_diff_deg(float(piece_angle_deg), float(last_piece_angle))
        if not math.isfinite(piece_delta_deg):
            return

        ratio = piece_delta_deg / carousel_delta_deg
        if not math.isfinite(ratio) or abs(ratio) > MOTION_SYNC_MAX_ABS_RATIO:
            return

        piece_speed = piece_delta_deg / dt_s
        carousel_speed = carousel_delta_deg / dt_s
        if not math.isfinite(piece_speed) or not math.isfinite(carousel_speed):
            return

        piece.carousel_motion_sample_count = int(piece.carousel_motion_sample_count or 0) + 1
        if ratio < MOTION_SYNC_LOW_RATIO:
            piece.carousel_motion_under_sync_sample_count = int(
                piece.carousel_motion_under_sync_sample_count or 0
            ) + 1
        if ratio > MOTION_SYNC_HIGH_RATIO:
            piece.carousel_motion_over_sync_sample_count = int(
                piece.carousel_motion_over_sync_sample_count or 0
            ) + 1

        piece.carousel_motion_piece_speed_deg_per_s = float(piece_speed)
        piece.carousel_motion_platter_speed_deg_per_s = float(carousel_speed)

        prev_ratio = piece.carousel_motion_sync_ratio
        if isinstance(prev_ratio, (int, float)) and math.isfinite(float(prev_ratio)):
            piece.carousel_motion_sync_ratio = (
                MOTION_SYNC_EMA_ALPHA * float(ratio)
                + (1.0 - MOTION_SYNC_EMA_ALPHA) * float(prev_ratio)
            )
        else:
            piece.carousel_motion_sync_ratio = float(ratio)

        piece.carousel_motion_sync_ratio_min = (
            float(ratio)
            if piece.carousel_motion_sync_ratio_min is None
            else min(float(piece.carousel_motion_sync_ratio_min), float(ratio))
        )
        piece.carousel_motion_sync_ratio_max = (
            float(ratio)
            if piece.carousel_motion_sync_ratio_max is None
            else max(float(piece.carousel_motion_sync_ratio_max), float(ratio))
        )

        piece._carousel_motion_piece_delta_sum_deg += float(piece_delta_deg)
        piece._carousel_motion_platter_delta_sum_deg += float(carousel_delta_deg)
        if abs(piece._carousel_motion_platter_delta_sum_deg) >= MOTION_SYNC_MIN_PLATTER_DELTA_DEG:
            piece.carousel_motion_sync_ratio_avg = (
                piece._carousel_motion_piece_delta_sum_deg
                / piece._carousel_motion_platter_delta_sum_deg
            )

        samples = list(piece.carousel_motion_samples or [])
        samples.append(
            CarouselMotionSample(
                observed_at=float(observed_at),
                piece_angle_deg=float(piece_angle_deg),
                carousel_angle_deg=float(carousel_angle_deg),
                piece_speed_deg_per_s=float(piece_speed),
                carousel_speed_deg_per_s=float(carousel_speed),
                sync_ratio=float(ratio),
            )
        )
        if len(samples) > MOTION_SYNC_SAMPLE_LIMIT:
            samples = samples[-MOTION_SYNC_SAMPLE_LIMIT:]
        piece.carousel_motion_samples = samples

    def setPositioningPiece(self, piece_uuid: str | None) -> None:
        self._positioning_piece_uuid = piece_uuid

    def removePiece(self, piece_uuid: str) -> KnownObject | None:
        if not self._dynamic_mode:
            return None
        piece = self._active_pieces.pop(piece_uuid, None)
        if piece is None:
            return None
        if piece.tracked_global_id is not None:
            self._piece_uuid_by_track_id.pop(int(piece.tracked_global_id), None)
        self._pending_classifications.pop(piece_uuid, None)
        if self._hood_piece_uuid == piece_uuid:
            self._hood_piece_uuid = None
        if self._positioning_piece_uuid == piece_uuid:
            self._positioning_piece_uuid = None
        if self._zone_manager is not None:
            self._zone_manager.remove_piece(piece_uuid)
        return piece
