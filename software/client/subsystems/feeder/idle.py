from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from global_config import GlobalConfig


class Idle(BaseState):
    def __init__(self, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(None, gc)
        self.shared = shared

    def step(self) -> Optional[FeederState]:
        return None

    def cleanup(self) -> None:
        super().cleanup()
