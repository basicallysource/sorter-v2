from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from defs.known_object import ClassificationStatus, PieceStage
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
        if piece is None:
            return None

        can_distribute = piece.part_id is not None or piece.classification_status in (
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
        )
        is_unhandled = piece.stage != PieceStage.distributing

        if can_distribute and is_unhandled:
            self.logger.info(
                f"Idle: preparing distribution for intermediate piece {piece.uuid[:8]}"
            )
            self.shared.distribution_ready = False
            return DistributionState.POSITIONING

        if can_distribute and not is_unhandled:
            self.logger.info(
                f"Idle: intermediate piece {piece.uuid[:8]} already prepared"
            )
        return None

    def cleanup(self) -> None:
        super().cleanup()
