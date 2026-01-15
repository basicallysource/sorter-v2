from defs.sorter_controller import SorterLifecycle
from defs.sorting_state import SortingState
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_state_machine import SortingStateMachine


class SorterController:
    def __init__(self, irl: IRLInterface, gc: GlobalConfig):
        self.state = SorterLifecycle.INITIALIZING
        self.irl = irl
        self.gc = gc
        self.sorting_state_machine = SortingStateMachine(irl, gc)

    def start(self) -> None:
        self.state = SorterLifecycle.RUNNING
        self.sorting_state_machine.states_map[SortingState.IDLE].triggerStart()

    def pause(self) -> None:
        self.sorting_state_machine.cleanup()
        self.state = SorterLifecycle.PAUSED

    def stop(self) -> None:
        self.sorting_state_machine.cleanup()
        self.state = SorterLifecycle.READY

    def step(self) -> None:
        if self.state == SorterLifecycle.RUNNING:
            self.sorting_state_machine.step()
