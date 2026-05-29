from subsystems.base_subsystem import BaseSubsystem
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .idle import Idle
from .feeding import Feeding
from irl.config import IRLInterface, IRLConfig, FeederMode
from global_config import GlobalConfig
from vision import VisionManager

# =============================================================================
# FEEDER CONTROL PATHS — ONLY ONE MATTERS FOR CURRENT WORK
# =============================================================================
# GO_TO_ANGLE_REV01  (the only path Spencer cares about right now for jitter,
#                    Rev04 perception, exit-region dwell logic, etc.)
#   - Instantiates GoToAngleFeeding for the FEEDING state.
#   - This is completely separate from the legacy reactive system.
#   - Paired (for full Rev04) with ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01
#     + the perception service owning detections.
#
# DROP_ZONE_REACTIVE_REV01  (legacy — do not touch for go-to-angle / Rev04 jitter work)
#   - Instantiates the big Feeding class (pulses, C1/C2/C3 stations, jam recovery,
#     dropzone incidents, ch2 separation, etc.).
#   - All the old subsystems/channels/* , feeder/strategies/* , feeder/dropzone_incidents.py
#     etc. are ONLY used by this path.
#
# The mode comes from machine.toml [feeder] mode = "go_to_angle_rev01"
# (or the IRLConfig default). See also main.py:_perceptionModeActive and
# vision_manager.py for the wider Rev04 pair guards.
# =============================================================================


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
        self._mode: FeederMode = getattr(
            irl_config.feeder_config,
            "mode",
            FeederMode.DROP_ZONE_REACTIVE_REV01,
        )
        self.current_state = FeederState.IDLE
        if self._mode == FeederMode.DROP_ZONE_REACTIVE_REV01:
            self.states_map = {
                FeederState.IDLE: Idle(irl, gc, shared),
                FeederState.FEEDING: Feeding(irl, irl_config, gc, shared, vision),
            }
        elif self._mode == FeederMode.GO_TO_ANGLE_REV01:
            from .go_to_angle.flow import GoToAngleFeeding
            self.states_map = {
                FeederState.IDLE: Idle(irl, gc, shared),
                FeederState.FEEDING: GoToAngleFeeding(irl, irl_config, gc, shared, vision),
            }
        else:
            raise ValueError(f"Unsupported feeder mode: {self._mode}")
        self.gc.profiler.enterState("feeder", self.current_state.value)
        if hasattr(self.gc, "runtime_stats"):
            self.gc.runtime_stats.observeStateTransition(
                "feeder", None, self.current_state.value
            )

    def step(self) -> None:
        self.gc.profiler.hit("feeder.state_machine.step.calls")
        with self.gc.profiler.timer(
            f"feeder.state_machine.state_step_ms.{self.current_state.value}"
        ):
            next_state = self.states_map[self.current_state].step()
        if next_state and next_state != self.current_state:
            prev_state = self.current_state
            self.logger.info(
                f"Feeder: {prev_state.value} -> {next_state.value}"
            )
            self.gc.profiler.hit(
                f"feeder.state_machine.transition.{prev_state.value}->{next_state.value}"
            )
            self.states_map[prev_state].cleanup()
            self.current_state = next_state
            if hasattr(self.gc, "runtime_stats"):
                self.gc.runtime_stats.observeStateTransition(
                    "feeder", prev_state.value, next_state.value
                )
            self.gc.profiler.enterState("feeder", self.current_state.value)

    def cleanup(self) -> None:
        self.gc.profiler.exitState("feeder")
        self.states_map[self.current_state].cleanup()
