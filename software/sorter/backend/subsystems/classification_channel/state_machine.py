from global_config import GlobalConfig
from irl.config import ClassificationChannelMode, IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from subsystems.base_subsystem import BaseSubsystem
from subsystems.classification_channel.detecting import Detecting
from subsystems.classification_channel.ejecting import Ejecting
from subsystems.classification_channel.idle import Idle
from subsystems.classification_channel.running import Running
from subsystems.classification_channel.simple_state_machine_rev01 import (
    buildRev01StatesMap,
)
from subsystems.classification_channel.snapping import Snapping
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables

# =============================================================================
# CLASSIFICATION CHANNEL PATHS
# =============================================================================
# SIMPLE_STATE_MACHINE_REV01  (the one that pairs with GO_TO_ANGLE_REV01 feeder)
#   - The rev01 package (simple_state_machine_rev01/) is the relevant one for
#     current Rev04 + jitter work on the classification side.
#   - Has its own perception vs legacy vision branches inside the rev01 states.
#
# Everything else (DYNAMIC + the old classification/ package states) is the
# legacy path and is not the focus when working on go-to-angle feeder jitter.
# =============================================================================


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
        self._mode: ClassificationChannelMode = getattr(
            irl_config.classification_channel_config,
            "mode",
            ClassificationChannelMode.DYNAMIC,
        )
        self._dynamic_mode = self._mode == ClassificationChannelMode.DYNAMIC
        if self._dynamic_mode:
            self.transport.configureDynamicMode(irl_config.classification_channel_config)
        self.current_state = ClassificationChannelState.IDLE
        if self._mode == ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01:
            self.states_map = buildRev01StatesMap(
                irl=irl,
                irl_config=irl_config,
                gc=gc,
                shared=shared,
                transport=transport,
                vision=vision,
                event_queue=event_queue,
            )
        else:
            self.states_map = {
                ClassificationChannelState.IDLE: Idle(
                    irl, irl_config, gc, shared, transport, vision
                ),
            }
            if self._dynamic_mode:
                self.states_map[ClassificationChannelState.RUNNING] = Running(
                    irl,
                    irl_config,
                    gc,
                    shared,
                    transport,
                    vision,
                    event_queue,
                )
            else:
                self.states_map.update(
                    {
                        ClassificationChannelState.DETECTING: Detecting(
                            irl, gc, shared, transport, vision, event_queue
                        ),
                        ClassificationChannelState.SNAPPING: Snapping(
                            irl, gc, shared, transport, vision, event_queue
                        ),
                        ClassificationChannelState.EJECTING: Ejecting(
                            irl, irl_config, gc, shared, transport, vision, event_queue
                        ),
                    }
                )
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
        if self._dynamic_mode and hasattr(self.transport, "resetDynamicState"):
            self.transport.resetDynamicState()
        # Reset to IDLE so the next resume / start re-runs the chamber
        # purge check instead of resuming mid-cycle.
        self.current_state = ClassificationChannelState.IDLE
