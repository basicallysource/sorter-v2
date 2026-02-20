from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from defs.known_object import ClassificationStatus
from irl.config import IRLInterface
from global_config import GlobalConfig


class Idle(BaseState):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(irl, gc)
        self.shared = shared

    def step(self) -> Optional[DistributionState]:
        carousel = self.shared.carousel
        if carousel is None:
            return None
        piece = carousel.getPieceAtIntermediate()
        if piece is not None and (
            piece.part_id is not None
            or piece.classification_status
            in (ClassificationStatus.unknown, ClassificationStatus.not_found)
        ):
            self.shared.distribution_ready = False
            return DistributionState.POSITIONING
        return None

    def cleanup(self) -> None:
        super().cleanup()
