from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .idle import Idle
from global_config import GlobalConfig


class FeederStateMachine(BaseSubsystem):
    def __init__(self, gc: GlobalConfig, shared: SharedVariables):
        super().__init__()
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.current_state = FeederState.IDLE
        self.states_map = {
            FeederState.IDLE: Idle(gc, shared),
        }

    def step(self) -> None:
        next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            self.logger.info(
                f"Feeder: {self.current_state.value} -> {next_state.value}"
            )
            self.states_map[self.current_state].cleanup()
            self.current_state = next_state

    def cleanup(self) -> None:
        self.states_map[self.current_state].cleanup()
