from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .idle import Idle
from .feeding import Feeding
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager


class FeederStateMachine(BaseSubsystem):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
    ):
        super().__init__()
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.current_state = FeederState.IDLE
        self.states_map = {
            FeederState.IDLE: Idle(irl, gc, shared),
            FeederState.FEEDING: Feeding(irl, irl_config, gc, shared, vision),
        }
        self.gc.profiler.enterState("feeder", self.current_state.value)

    def step(self) -> None:
        self.gc.profiler.hit("feeder.state_machine.step.calls")
        with self.gc.profiler.timer(
            f"feeder.state_machine.state_step_ms.{self.current_state.value}"
        ):
            next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            self.logger.info(
                f"Feeder: {self.current_state.value} -> {next_state.value}"
            )
            self.gc.profiler.hit(
                f"feeder.state_machine.transition.{self.current_state.value}->{next_state.value}"
            )
            self.states_map[self.current_state].cleanup()
            self.current_state = next_state
            self.gc.profiler.enterState("feeder", self.current_state.value)

    def cleanup(self) -> None:
        self.gc.profiler.exitState("feeder")
        self.states_map[self.current_state].cleanup()
