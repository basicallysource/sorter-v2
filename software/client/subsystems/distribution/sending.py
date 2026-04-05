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
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.event_queue = event_queue
        self.piece = None
        self.start_time: float = 0.0
        self._occupancy_state: str | None = None

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
        if self.piece is None:
            carousel = self.shared.carousel
            self.piece = carousel.getPieceAtExit() if carousel else None
            self.start_time = time.time()

        elapsed_ms = (time.time() - self.start_time) * 1000
        self._setOccupancyState("sending.wait_chute_settle")
        if elapsed_ms < CHUTE_SETTLE_MS:
            return None

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
                tracker.record(self.piece.part_id, self.piece.color_id, self.piece.category_id)
                try:
                    from server.set_progress_sync import getSetProgressSyncWorker

                    getSetProgressSyncWorker().notify()
                except Exception:
                    pass
        self.shared.distribution_ready = True
        return DistributionState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.piece = None
        self.start_time = 0.0
