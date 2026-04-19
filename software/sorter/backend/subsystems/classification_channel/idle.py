from typing import Optional

from global_config import GlobalConfig
from irl.config import IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables


class Idle(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.transport = transport

    def step(self) -> Optional[ClassificationChannelState]:
        piece = self.transport.getPieceAtClassification()
        if piece is None:
            return ClassificationChannelState.DETECTING
        return ClassificationChannelState.SNAPPING

    def cleanup(self) -> None:
        super().cleanup()
