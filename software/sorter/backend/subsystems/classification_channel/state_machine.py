from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from subsystems.base_subsystem import BaseSubsystem
from subsystems.classification_channel.detecting import Detecting
from subsystems.classification_channel.ejecting import Ejecting
from subsystems.classification_channel.idle import Idle
from subsystems.classification_channel.snapping import Snapping
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables
from telemetry import Telemetry


class ClassificationChannelStateMachine(BaseSubsystem):
    def __init__(
        self,
        *,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision,
        event_queue,
        telemetry: Telemetry,
        transport: ClassificationChannelTransport,
    ):
        super().__init__()
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.vision = vision
        self.event_queue = event_queue
        self.transport = transport
        self.current_state = ClassificationChannelState.IDLE
        self.states_map = {
            ClassificationChannelState.IDLE: Idle(irl, gc, shared, transport),
            ClassificationChannelState.DETECTING: Detecting(
                irl, gc, shared, transport, vision, event_queue
            ),
            ClassificationChannelState.SNAPPING: Snapping(
                irl, gc, shared, transport, vision, event_queue, telemetry
            ),
            ClassificationChannelState.EJECTING: Ejecting(
                irl, irl_config, gc, shared, transport
            ),
        }
        self.gc.profiler.enterState("classification", self.current_state.value)
        if hasattr(self.gc, "runtime_stats"):
            self.gc.runtime_stats.observeStateTransition(
                "classification", None, self.current_state.value
            )

    def step(self) -> None:
        self.gc.profiler.hit("classification.state_machine.step.calls")
        with self.gc.profiler.timer(
            f"classification.state_machine.state_step_ms.{self.current_state.value}"
        ):
            next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            prev_state = self.current_state
            self.logger.info(
                f"ClassificationChannel: {prev_state.value} -> {next_state.value}"
            )
            self.gc.profiler.hit(
                f"classification.state_machine.transition.{prev_state.value}->{next_state.value}"
            )
            self.states_map[prev_state].cleanup()
            self.current_state = next_state
            if hasattr(self.gc, "runtime_stats"):
                self.gc.runtime_stats.observeStateTransition(
                    "classification", prev_state.value, next_state.value
                )
            self.gc.profiler.enterState("classification", self.current_state.value)

    def cleanup(self) -> None:
        self.gc.profiler.exitState("classification")
        self.states_map[self.current_state].cleanup()
