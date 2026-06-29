import time
import queue
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from irl.config import IRLInterface
from global_config import GlobalConfig
from utils.event import known_object_to_event
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

    def step(self) -> Optional[DistributionState]:
        if self.piece is None:
            carousel = self.shared.carousel
            self.piece = carousel.get_piece_at_exit() if carousel else None
            self.start_time = time.time()

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < CHUTE_SETTLE_MS:
            return None

        self.logger.info(f"Sending: settle complete ({elapsed_ms:.0f}ms)")
        if self.piece:
            self.piece.stage = PieceStage.distributed
            self.piece.distributed_at = time.time()
            self.piece.updated_at = time.time()
            self.event_queue.put(known_object_to_event(self.piece))
            self.gc.run_recorder.record_piece(self.piece)
        self.shared.distribution_ready = True
        return DistributionState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.piece = None
        self.start_time = 0.0
