from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .idle import Idle
from .detecting import Detecting
from .rotating import Rotating
from .snapping import Snapping
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision import VisionManager
from telemetry import Telemetry
import queue


class ClassificationStateMachine(BaseSubsystem):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
        event_queue: queue.Queue,
        telemetry: Telemetry,
        carousel: Carousel,
    ):
        super().__init__()
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.vision = vision
        self.event_queue = event_queue
        self.carousel = carousel
        self.current_state = ClassificationState.IDLE

        self.states_map = {
            ClassificationState.IDLE: Idle(irl, gc, shared, self.carousel),
            ClassificationState.DETECTING: Detecting(
                irl, gc, shared, self.carousel, vision
            ),
            ClassificationState.ROTATING: Rotating(
                irl, gc, shared, self.carousel, irl.carousel_stepper, event_queue
            ),
            ClassificationState.SNAPPING: Snapping(
                irl, gc, shared, self.carousel, vision, event_queue, telemetry
            ),
        }
        self.gc.profiler.enterState("classification", self.current_state.value)

    def step(self) -> None:
        self.gc.profiler.hit("classification.state_machine.step.calls")
        with self.gc.profiler.timer(
            f"classification.state_machine.state_step_ms.{self.current_state.value}"
        ):
            next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            self.logger.info(
                f"Classification: {self.current_state.value} -> {next_state.value}"
            )
            self.gc.profiler.hit(
                f"classification.state_machine.transition.{self.current_state.value}->{next_state.value}"
            )
            self.states_map[self.current_state].cleanup()
            self.current_state = next_state
            self.gc.profiler.enterState("classification", self.current_state.value)

    def cleanup(self) -> None:
        self.gc.profiler.exitState("classification")
        self.states_map[self.current_state].cleanup()
