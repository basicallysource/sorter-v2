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

CHUTE_SETTLE_MS = 1500


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
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.event_queue = event_queue
        self.vision = vision
        self._cooldown_s = max(0.0, float(post_distribute_cooldown_s))
        self.piece = None
        self.start_time: float = 0.0
        self._occupancy_state: str | None = None
        self._committed: bool = False

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
        if self.piece is None and not self._committed:
            transport = self.shared.transport
            self.piece = (
                transport.getPieceForDistributionDrop()
                if transport is not None
                else None
            )
            self.start_time = time.time()

        elapsed_ms = (time.time() - self.start_time) * 1000
        self._setOccupancyState("sending.wait_chute_settle")
        if elapsed_ms < CHUTE_SETTLE_MS:
            return None

        # Chute-settle timer elapsed; now gate the downstream reopen on either:
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

        # Commit the piece once (stats, event, recorder) only after the
        # tracker/cooldown gate says the piece has physically exited.
        if not self._committed:
            self.logger.info(f"Sending: exit confirmed ({elapsed_ms:.0f}ms)")
            self._setOccupancyState("sending.commit_piece")
            if self.piece:
                now_wall = time.time()
                self.piece.stage = PieceStage.distributed
                self.piece.distributed_at = now_wall
                self.piece.updated_at = now_wall
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

        self.shared.set_distribution_gate(True, reason=None)
        return DistributionState.IDLE

    def _shouldReopenGate(self) -> bool:
        piece = self.piece
        track_id = getattr(piece, "tracked_global_id", None) if piece is not None else None
        if isinstance(track_id, int):
            vision = self.vision
            if vision is not None and hasattr(vision, "getFeederTrackerLiveGlobalIds"):
                try:
                    live = vision.getFeederTrackerLiveGlobalIds("carousel")
                except Exception:
                    live = None
                if isinstance(live, (set, frozenset)) and int(track_id) in live:
                    # Piece still visible on the carousel tracker — hold
                    # the gate closed regardless of cooldown.
                    return False

        elapsed_since_drop = time.time() - self.start_time
        required_s = (CHUTE_SETTLE_MS / 1000.0) + self._cooldown_s
        if elapsed_since_drop < required_s:
            return False
        return True

    def cleanup(self) -> None:
        super().cleanup()
        self.piece = None
        self.start_time = 0.0
        self._committed = False
