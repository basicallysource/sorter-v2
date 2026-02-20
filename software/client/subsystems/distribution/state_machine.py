from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from .idle import Idle
from .positioning import Positioning
from .ready import Ready
from .sending import Sending
from irl.bin_layout import DistributionLayout
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_profile import SortingProfile
import queue


class DistributionStateMachine(BaseSubsystem):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        sorting_profile: SortingProfile,
        layout: DistributionLayout,
        event_queue: queue.Queue,
    ):
        super().__init__()
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.sorting_profile = sorting_profile
        self.layout = layout
        self.event_queue = event_queue
        self.chute = irl.chute
        self.current_state = DistributionState.IDLE
        self.states_map = {
            DistributionState.IDLE: Idle(irl, gc, shared),
            DistributionState.POSITIONING: Positioning(
                irl, gc, shared, self.chute, layout, sorting_profile, event_queue
            ),
            DistributionState.READY: Ready(irl, gc, shared),
            DistributionState.SENDING: Sending(irl, gc, shared, event_queue),
        }
        self.gc.profiler.enterState("distribution", self.current_state.value)

    def step(self) -> None:
        self.gc.profiler.hit("distribution.state_machine.step.calls")
        with self.gc.profiler.timer(
            f"distribution.state_machine.state_step_ms.{self.current_state.value}"
        ):
            next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            self.logger.info(
                f"Distribution: {self.current_state.value} -> {next_state.value}"
            )
            self.gc.profiler.hit(
                f"distribution.state_machine.transition.{self.current_state.value}->{next_state.value}"
            )
            self.states_map[self.current_state].cleanup()
            self.current_state = next_state
            self.gc.profiler.enterState("distribution", self.current_state.value)

    def cleanup(self) -> None:
        self.gc.profiler.exitState("distribution")
        self.states_map[self.current_state].cleanup()
