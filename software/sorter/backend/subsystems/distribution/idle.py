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
        transport = self.shared.transport
        if transport is None:
            return None
        piece = transport.getPieceForDistributionPositioning()
        if piece is None:
            # No piece waiting → ensure the gate is open so C4 sees us as
            # ready to accept the next drop. Recovers from a stale gate=False
            # left behind when a Sending cycle was interrupted (pause/resume,
            # supervisor restart, etc.) before it could reopen the gate.
            if not self.shared.distribution_ready:
                self.shared.set_distribution_gate(True, reason=None)
            return None

        can_distribute = piece.part_id is not None or piece.classification_status in (
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
            ClassificationStatus.multi_drop_fail,
        )
        is_unhandled = piece.stage != PieceStage.distributing

        if can_distribute and is_unhandled:
            self.logger.info(
                f"Idle: preparing distribution for piece {piece.uuid[:8]}"
            )
            self.shared.set_distribution_gate(False, reason="positioning")
            return DistributionState.POSITIONING

        if can_distribute and not is_unhandled:
            self.logger.info(
                f"Idle: piece {piece.uuid[:8]} already prepared"
            )
        return None

    def cleanup(self) -> None:
        super().cleanup()
