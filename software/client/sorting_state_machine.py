from typing import Dict
from defs.sorting_state import SortingState
from states import IStateMachine, Idle, Feeding, SharedVariables
from irl.config import IRLInterface
from global_config import GlobalConfig


class SortingStateMachine:
    def __init__(self, irl: IRLInterface, gc: GlobalConfig):
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = SharedVariables()
        self.current_state = SortingState.IDLE
        self.states_map: Dict[SortingState, IStateMachine] = {
            SortingState.IDLE: Idle(irl, gc, self.shared),
            SortingState.FEEDING: Feeding(irl, gc, self.shared),
        }

    def step(self) -> None:
        next_state = self.states_map[self.current_state].step()

        if next_state and next_state != self.current_state:
            self.logger.info(
                f"State transition: {self.current_state.value} -> {next_state.value}"
            )
            self.states_map[self.current_state].cleanup()
            self.current_state = next_state

    def cleanup(self) -> None:
        self.states_map[self.current_state].cleanup()
