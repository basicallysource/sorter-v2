import time
import queue
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from irl.config import IRLInterface
from global_config import GlobalConfig
from defs.events import KnownObjectEvent, KnownObjectData, KnownObjectStatus

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

    def _emitObjectEvent(self, obj) -> None:
        event = KnownObjectEvent(
            tag="known_object",
            data=KnownObjectData(
                uuid=obj.uuid,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
                status=KnownObjectStatus(obj.status),
                part_id=obj.part_id,
                category_id=obj.category_id,
                confidence=obj.confidence,
                destination_bin=obj.destination_bin,
                thumbnail=obj.thumbnail,
                top_image=obj.top_image,
                bottom_image=obj.bottom_image,
            ),
        )
        self.event_queue.put(event)

    def step(self) -> Optional[DistributionState]:
        if self.piece is None:
            self.piece = self.shared.pending_piece
            self.start_time = time.time()

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < CHUTE_SETTLE_MS:
            return None

        if self.piece:
            self.piece.status = "distributed"
            self.piece.updated_at = time.time()
            self._emitObjectEvent(self.piece)
        self.shared.pending_piece = None
        self.shared.distribution_ready = True
        return DistributionState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.piece = None
        self.start_time = 0.0
