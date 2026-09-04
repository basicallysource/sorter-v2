import time
import queue
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from irl.config import IRLInterface
from global_config import GlobalConfig
from utils.event import knownObjectToEvent
from defs.known_object import PieceStage
from subsystems.classification_channel.incidents import (
    CLASSIFICATION_TRACK_LOST_INCIDENT_KIND,
    publish_classification_track_lost_incident,
)

CHUTE_SETTLE_MS = 1500
SAMPLE_COLLECTION_CHUTE_SETTLE_MS = 400
MISSING_DROP_PIECE_GRACE_MS = 1500
PIECE_EXIT_INCIDENT_MS = 8000


class Sending(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        event_queue: queue.Queue,
        *,
        vision=None,
        post_distribute_cooldown_s: float = 0.0,
        chute_settle_ms: int = CHUTE_SETTLE_MS,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.event_queue = event_queue
        self.vision = vision
        self._cooldown_s = max(0.0, float(post_distribute_cooldown_s))
        self._settle_ms = max(0, int(chute_settle_ms))
        self.piece = None
        self.start_time: float = 0.0
        self._occupancy_state: str | None = None
        self._committed: bool = False
        self._exit_wait_incident_piece_uuid: str | None = None
        self._held_door: object | None = None
        self._door_hold_done = False

    def _setOccupancyState(self, state_name: str) -> None:
        if self._occupancy_state == state_name:
            return
        prev_state = self._occupancy_state
        self._occupancy_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            "distribution.occupancy",
            prev_state,
            state_name,
        )

    def step(self) -> Optional[DistributionState]:
        now = time.time()
        if self.piece is None and not self._committed:
            if self.start_time <= 0.0:
                self.start_time = now
            transport = self.shared.transport
            self.piece = (
                transport.getPieceForDistributionDrop()
                if transport is not None
                else None
            )
            if self.piece is None:
                elapsed_ms = (now - self.start_time) * 1000
                self._setOccupancyState("sending.wait_drop_piece")
                if elapsed_ms >= MISSING_DROP_PIECE_GRACE_MS:
                    self.logger.warning(
                        "Sending: no distribution-drop piece available after "
                        f"{elapsed_ms:.0f}ms; reopening distribution gate"
                    )
                    self.gc.runtime_stats.observeBlockedReason(
                        "distribution",
                        "sending_missing_drop_piece",
                    )
                    self.shared.set_distribution_gate(True, reason=None)
                    return DistributionState.IDLE
                return None

        if self.piece is not None and self._held_door is None and not self._door_hold_done:
            self._holdTargetDoor()
        elapsed_ms = (now - self.start_time) * 1000
        settle_ms = self._settleMs()
        self._setOccupancyState("sending.wait_chute_settle")
        if elapsed_ms < settle_ms:
            return None
        self._releaseHeldDoor()

        # Commit the piece once (stats, event, recorder) — must not repeat
        # even if we decide to hold the gate for additional cooldown below.
        if not self._committed:
            self.logger.info(f"Sending: settle complete ({elapsed_ms:.0f}ms)")
            self._setOccupancyState("sending.commit_piece")
            if self.piece:
                self.piece.stage = PieceStage.distributed
                self.piece.distributed_at = time.time()
                self.piece.updated_at = time.time()
                self.event_queue.put(knownObjectToEvent(self.piece))
                self.gc.run_recorder.recordPiece(self.piece)
                tracker = getattr(self.gc, 'set_progress_tracker', None)
                if tracker is not None:
                    tracker.record(
                        self.piece.part_id,
                        self.piece.color_id,
                        self.piece.category_id,
                    )
                    try:
                        from server.set_progress_sync import getSetProgressSyncWorker

                        getSetProgressSyncWorker().notify()
                    except Exception:
                        pass
            self._committed = True

        # Chute-settle timer elapsed and the piece has been committed. Now
        # gate the downstream reopen on either:
        #   (a) the carousel tracker no longer showing the dropped piece's
        #       global_id (physical exit confirmed by vision), or
        #   (b) a minimum cooldown after drop commit, used as a fallback
        #       when the tracker signal is unavailable.
        # Root cause of ~63% multi_drop_fail rate was a fixed 1500ms
        # wall-clock reopen that didn't wait for the piece to physically
        # leave the chute.
        if not self._shouldReopenGate():
            self._setOccupancyState("sending.wait_piece_exit")
            return None

        self.shared.set_distribution_gate(True, reason=None)
        return DistributionState.IDLE

    def _targetDoor(self):
        target = getattr(self.shared, "chute_target_bin", None)
        layer_index = getattr(target, "layer_index", None)
        servos = getattr(self.irl, "servos", None)
        if not isinstance(layer_index, int) or not servos or layer_index >= len(servos):
            return None
        servo = servos[layer_index]
        return servo if callable(getattr(servo, "hold", None)) else None

    def _holdTargetDoor(self) -> None:
        """Keep the target door energized from the drop until the settle
        elapsed: the piece must meet a powered flap, not one that was released
        seconds ago and yields to the impact."""
        self._door_hold_done = True
        if bool(getattr(self.gc, "disable_servos", False)):
            return
        door = self._targetDoor()
        if door is None:
            return
        try:
            door.hold()
        except Exception as exc:
            self.logger.warning(f"Sending: could not hold the target door: {exc}")
            return
        self._held_door = door

    def _releaseHeldDoor(self) -> None:
        door = self._held_door
        if door is None:
            return
        self._held_door = None
        try:
            door.release()
        except Exception as exc:
            self.logger.warning(f"Sending: could not release the held door: {exc}")

    def _shouldReopenGate(self) -> bool:
        if bool(getattr(self.shared, "sample_collection_mode", False)):
            return True

        piece = self.piece
        # When layer servos are disabled (simulated distributor) the chute
        # door never opens, so a piece that physically reaches the chute
        # stays parked there inside the carousel camera view. The tracker
        # then keeps reporting its global_id alive and the gate would never
        # reopen — pipeline deadlock after 1-2 pieces. Fall back to the
        # cooldown-only gate in that mode so distribution still ticks.
        track_id = getattr(piece, "tracked_global_id", None) if piece is not None else None
        if isinstance(track_id, int) and not self.gc.disable_servos:
            vision = self.vision
            if vision is not None and hasattr(vision, "getFeederTrackerLiveGlobalIds"):
                try:
                    live = vision.getFeederTrackerLiveGlobalIds("carousel")
                except Exception:
                    live = None
                if isinstance(live, (set, frozenset)) and int(track_id) in live:
                    # Piece still visible on the carousel tracker — hold
                    # the gate closed regardless of cooldown.
                    if self._pieceExitWaitTimedOut():
                        return self._handlePieceExitTimeout(int(track_id))
                    return False

        elapsed_since_drop = time.time() - self.start_time
        required_s = (self._settleMs() / 1000.0) + self._cooldown_s
        if elapsed_since_drop < required_s:
            return False
        return True

    def _pieceExitWaitTimedOut(self) -> bool:
        elapsed_ms = (time.time() - self.start_time) * 1000
        return elapsed_ms >= max(
            PIECE_EXIT_INCIDENT_MS,
            self._settleMs() + int(self._cooldown_s * 1000.0),
        )

    def _handlePieceExitTimeout(self, track_id: int) -> bool:
        piece = self.piece
        piece_uuid = str(getattr(piece, "uuid", "") or "")
        active = self._activeIncident()
        if self._exit_wait_incident_piece_uuid == piece_uuid:
            if (
                isinstance(active, dict)
                and active.get("kind") == CLASSIFICATION_TRACK_LOST_INCIDENT_KIND
                and active.get("piece_uuid") == piece_uuid
            ):
                self._setOccupancyState("sending.wait_piece_exit_incident")
                self.gc.runtime_stats.observeBlockedReason(
                    "distribution",
                    "sending_piece_exit_incident",
                )
                return False

            self.logger.warning(
                "Sending: C4 exit-wait incident for piece %s was cleared; "
                "reopening distribution gate"
                % (piece_uuid[:8] or "unknown")
            )
            self._forceKillLiveTrack(track_id)
            return True

        elapsed_ms = (time.time() - self.start_time) * 1000
        reason = f"distribution_drop_track_still_live_after_{int(elapsed_ms)}ms"
        published = False
        if piece is not None:
            published = publish_classification_track_lost_incident(
                self.gc,
                piece=piece,
                reason=reason,
            )
        if published:
            self._exit_wait_incident_piece_uuid = piece_uuid
            self._setOccupancyState("sending.wait_piece_exit_incident")
            self.logger.warning(
                "Sending: piece %s still visible on C4 tracker after %.0fms; "
                "waiting for operator incident"
                % (piece_uuid[:8] or "unknown", elapsed_ms)
            )
            return False

        self.logger.warning(
            "Sending: piece %s still visible on C4 tracker after %.0fms, "
            "but track-lost incidents are disabled/unavailable; reopening gate"
            % (piece_uuid[:8] or "unknown", elapsed_ms)
        )
        self.gc.runtime_stats.observeBlockedReason(
            "distribution",
            "sending_piece_exit_timeout_reopened",
        )
        self._forceKillLiveTrack(track_id)
        return True

    def _activeIncident(self) -> dict | None:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return None
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            return None
        return active if isinstance(active, dict) else None

    def _forceKillLiveTrack(self, track_id: int) -> None:
        vision = self.vision
        if vision is None or not hasattr(vision, "forceKillCarouselTrack"):
            return
        try:
            vision.forceKillCarouselTrack(int(track_id))
        except Exception:
            pass

    def _settleMs(self) -> int:
        if bool(getattr(self.shared, "sample_collection_mode", False)):
            return SAMPLE_COLLECTION_CHUTE_SETTLE_MS
        return self._settle_ms

    def cleanup(self) -> None:
        self._releaseHeldDoor()
        self._door_hold_done = False
        super().cleanup()
        self.piece = None
        self.start_time = 0.0
        self._committed = False
        self._exit_wait_incident_piece_uuid = None
