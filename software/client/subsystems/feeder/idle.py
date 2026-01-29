from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from irl.config import IRLInterface
from global_config import GlobalConfig


class Idle(BaseState):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(irl, gc)
        self.shared = shared

    def step(self) -> Optional[FeederState]:
        if self.shared.classification_ready:
            return FeederState.FEEDING
        return None

    def cleanup(self) -> None:
        super().cleanup()
