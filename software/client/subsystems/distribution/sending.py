import time
import queue
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from irl.config import IRLInterface
from global_config import GlobalConfig
from utils.event import knownObjectToEvent

CHUTE_SETTLE_MS = 500


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
            self.piece = self.shared.pending_piece
            self.start_time = time.time()

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < CHUTE_SETTLE_MS:
            return None

        if self.piece:
            if self.piece.destination_bin is not None:
                layer_index = self.piece.destination_bin[0]
                self.irl.servos[layer_index].open()
            self.piece.status = "distributed"
            self.piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(self.piece))
        self.shared.pending_piece = None
        self.shared.distribution_ready = True
        return DistributionState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.piece = None
        self.start_time = 0.0
