from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from runtime_variables import RuntimeVariables
from .states import FeederState
from .idle import Idle
from .feeding import Feeding
from .v3_dispensing import V3Dispensing
from .v3_dispensing_slow import V3DispensingSlow
from .v2_loading import V2Loading
from .v1_loading import V1Loading
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision.vision_manager import VisionManager


class FeederStateMachine(BaseSubsystem):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
        rv: RuntimeVariables,
    ):
        super().__init__()
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.vision = vision
        self.current_state = FeederState.IDLE
        self.states_map = {
            FeederState.IDLE: Idle(irl, gc, shared, vision),
            FeederState.FEEDING: Feeding(irl, gc, shared),
            FeederState.V3_DISPENSING: V3Dispensing(irl, gc, shared, vision, rv),
            FeederState.V3_DISPENSING_SLOW: V3DispensingSlow(
                irl, gc, shared, vision, rv
            ),
            FeederState.V2_LOADING: V2Loading(irl, gc, shared, vision, rv),
            FeederState.V1_LOADING: V1Loading(irl, gc, shared, vision, rv),
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
