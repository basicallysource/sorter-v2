import time

from global_config import GlobalConfig
from irl.config import ClassificationChannelMode, IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from subsystems.base_subsystem import BaseSubsystem
from subsystems.classification_channel.detecting import Detecting
from subsystems.classification_channel.ejecting import Ejecting
from subsystems.classification_channel.idle import Idle
from subsystems.classification_channel.incidents import (
    CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND,
    clear_classification_exit_stuck_incident,
    publish_classification_exit_stuck_incident,
)

# General no-progress watchdog: if a piece is physically on the classification
# channel (perception n_pieces > 0) but the state machine makes NO transition
# for this long, the process is wedged — no matter WHICH state it's stuck in or
# which zone perception thinks the piece is in. Raise the operator exit-stuck
# incident (manual: dashboard pop-up + Resolve) so a stall is never silent. No
# auto-recovery — the operator clears the piece and Resolves to resume. The
# threshold is well above any normal single-state dwell (rotate/classify/
# discharge all transition within a few seconds).
_STALL_INCIDENT_MS = 30000.0
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
        # No-progress watchdog state: last time the SM made a transition (its
        # "progress" signal) and whether we've raised the stall incident.
        self._last_progress_at = time.monotonic()
        self._stall_incident_raised = False

    def step(self) -> None:
        import time as _time
        _t0 = _time.perf_counter()
        self.gc.profiler.hit("classification.state_machine.step.calls")
        _t1 = _time.perf_counter()
        next_state = self.states_map[self.current_state].step()
        _t2 = _time.perf_counter()
        _after_t0 = _time.perf_counter()
        if next_state and next_state != self.current_state:
            _cleanup_t0 = _time.perf_counter()
            prev_state = self.current_state
            # A state transition is the SM's "forward progress" signal.
            self._last_progress_at = _time.monotonic()
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
            self.gc.runtime_stats.observePerfMs(
                "classification.sm.transition_cleanup_ms",
                (_time.perf_counter() - _cleanup_t0) * 1000.0,
            )
        _t3 = _time.perf_counter()
        self.gc.runtime_stats.observePerfMs(
            f"classification.sm.state_step_ms.{self.current_state.value}",
            (_t2 - _t1) * 1000.0,
        )
        self.gc.runtime_stats.observePerfMs(
            "classification.sm.overhead_before_state_ms",
            (_t1 - _t0) * 1000.0,
        )
        self.gc.runtime_stats.observePerfMs(
            "classification.sm.overhead_after_state_ms",
            (_t3 - _after_t0) * 1000.0,
        )
        self.gc.runtime_stats.observePerfMs(
            "classification.sm.total_ms",
            (_t3 - _t0) * 1000.0,
        )
        self._checkStall(_time.monotonic())

    def _stallIncidentActive(self) -> bool:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return False
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            return False
        return (
            isinstance(active, dict)
            and active.get("kind") == CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND
        )

    def _checkStall(self, now: float) -> None:
        # Only the rev01 (active) path. Legacy/dynamic paths have their own flow.
        if self._mode != ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01:
            return

        # If we raised the incident and it's since been resolved (operator
        # cleared it), re-arm from now so we don't instantly re-fire on the next
        # step — give the resumed flow a fresh window to make progress.
        if self._stall_incident_raised and not self._stallIncidentActive():
            self._stall_incident_raised = False
            self._last_progress_at = now
            return

        perception_service = getattr(self.gc, "perception_service", None)
        occupied = False
        if perception_service is not None:
            try:
                occupied = int(perception_service.read_state(4).n_pieces) > 0
            except Exception:
                occupied = False

        if not occupied:
            # Channel clear -> not stuck. Re-arm and drop any raised incident
            # (the piece left / was removed).
            self._last_progress_at = now
            if self._stall_incident_raised:
                clear_classification_exit_stuck_incident(self.gc)
                self._stall_incident_raised = False
            return

        stalled_ms = (now - self._last_progress_at) * 1000.0
        if not self._stall_incident_raised and stalled_ms >= _STALL_INCIDENT_MS:
            published = publish_classification_exit_stuck_incident(
                self.gc,
                piece=None,
                jitter_attempts=0,
                converge_ms=stalled_ms,
            )
            self._stall_incident_raised = bool(published)
            self.logger.info(
                f"ClassificationChannel: STALLED in {self.current_state.value} for "
                f"{stalled_ms:.0f}ms with a piece on the channel — raised exit-stuck "
                f"incident (published={self._stall_incident_raised})"
            )

    def cleanup(self) -> None:
        self.gc.profiler.exitState("classification")
        self.states_map[self.current_state].cleanup()
        if self._dynamic_mode and hasattr(self.transport, "resetDynamicState"):
            self.transport.resetDynamicState()
        # Reset to IDLE so the next resume / start re-runs the chamber
        # purge check instead of resuming mid-cycle.
        self.current_state = ClassificationChannelState.IDLE
