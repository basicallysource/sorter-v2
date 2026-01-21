from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from .idle import Idle
from .sending import Sending
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_profile import SortingProfile


class DistributionStateMachine(BaseSubsystem):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        sorting_profile: SortingProfile,
    ):
        super().__init__()
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.sorting_profile = sorting_profile
        self.current_state = DistributionState.IDLE
        self.states_map = {
            DistributionState.IDLE: Idle(irl, gc, shared),
            DistributionState.SENDING: Sending(irl, gc, shared, sorting_profile),
        }

    def step(self) -> None:
        next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            self.logger.info(
                f"Distribution: {self.current_state.value} -> {next_state.value}"
            )
            self.states_map[self.current_state].cleanup()
            self.current_state = next_state

    def cleanup(self) -> None:
        self.states_map[self.current_state].cleanup()
