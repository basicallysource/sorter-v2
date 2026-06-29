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
        self.irl_config = irl_config
        self._mode: ClassificationChannelMode = getattr(
            irl_config.classification_channel_config,
            "mode",
            ClassificationChannelMode.DYNAMIC,
        )
        self._dynamic_mode = self._mode == ClassificationChannelMode.DYNAMIC
        if self._dynamic_mode:
            self.transport.configureDynamicMode(irl_config.classification_channel_config)
        self.current_state = ClassificationChannelState.IDLE
        # The two-piece codepath is a single self-contained controller (not a
        # states_map); step()/cleanup() delegate to it when this mode is active.
        self._two_piece = None
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
        elif self._mode == ClassificationChannelMode.TWO_PIECE_STATE_MACHINE_REV01:
            from subsystems.classification_channel.two_piece import (
                TwoPieceClassificationChannel,
            )
            from subsystems.classification_channel.simple_state_machine_rev01.context import (
                SimpleStateMachineRev01Context,
            )
            self.states_map = {}
            self._two_piece = TwoPieceClassificationChannel(
                irl,
                irl_config,
                gc,
                shared,
                transport,
                vision,
                event_queue,
                SimpleStateMachineRev01Context(),
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
        if self._two_piece is not None:
            self._two_piece.step()
            self._checkStall(time.monotonic())
            return
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

    def _progressMono(self) -> float:
        # The "last forward progress" timestamp, sourced per active mode: the
        # two-piece controller owns its own (phase changes / healthy waiting),
        # the single-piece SM uses state transitions (_last_progress_at).
        if self._two_piece is not None:
            return self._two_piece.last_progress_mono
        return self._last_progress_at

    def _rearmProgress(self, now: float) -> None:
        self._last_progress_at = now
        if self._two_piece is not None:
            self._two_piece.markProgress(now)

    def _stallStateLabel(self) -> str:
        if self._two_piece is not None:
            return f"two_piece:{self._two_piece.phase_label}"
        return self.current_state.value

    def _checkStall(self, now: float) -> None:
        # The active paths only: single-piece rev01 and two-piece. Legacy/dynamic
        # paths have their own flow.
        if self._mode not in (
            ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01,
            ClassificationChannelMode.TWO_PIECE_STATE_MACHINE_REV01,
        ):
            return

        # If we raised the incident and it's since been resolved (operator
        # cleared it), re-arm from now so we don't instantly re-fire on the next
        # step — give the resumed flow a fresh window to make progress.
        if self._stall_incident_raised and not self._stallIncidentActive():
            self._stall_incident_raised = False
            self._rearmProgress(now)
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
            self._rearmProgress(now)
            if self._stall_incident_raised:
                clear_classification_exit_stuck_incident(self.gc)
                self._stall_incident_raised = False
            return

        stalled_ms = (now - self._progressMono()) * 1000.0
        if self._stall_incident_raised or stalled_ms < _STALL_INCIDENT_MS:
            return

        # Watchdog disabled for this incident kind -> leave it alone (re-arm so we
        # don't re-evaluate the same stall every tick).
        from toml_config import incidentHandlingOff

        if incidentHandlingOff(CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND):
            self._rearmProgress(now)
            return

        # Always try to clear the channel ourselves first: rotate forward until
        # the pieces are gone (clearChannelByAdvancing, capped at 720°). Only if
        # that budget is exhausted without clearing do we stop for an operator.
        if self._tryAutoResolveStall(stalled_ms):
            return

        published = publish_classification_exit_stuck_incident(
            self.gc,
            piece=None,
            jitter_attempts=0,
            converge_ms=stalled_ms,
        )
        self._stall_incident_raised = bool(published)
        self.logger.info(
            f"ClassificationChannel: STALLED in {self._stallStateLabel()} for "
            f"{stalled_ms:.0f}ms with a piece on the channel — auto-clear failed, "
            f"raised exit-stuck incident (published={self._stall_incident_raised})"
        )

    def _tryAutoResolveStall(self, stalled_ms: float) -> bool:
        from subsystems.classification_channel.simple_state_machine_rev01.channel_clear import (
            clearChannelByAdvancing,
        )

        self.logger.info(
            f"ClassificationChannel: STALLED in {self._stallStateLabel()} for "
            f"{stalled_ms:.0f}ms — advancing the channel to clear the piece(s)"
        )
        result = clearChannelByAdvancing(
            self.gc, self.irl, self.irl_config, vision=self.vision
        )
        if result.cleared:
            now = time.monotonic()
            # The two-piece controller still holds tracked pieces / a phase that
            # the forced rotation just invalidated — reset it to a clean WAITING.
            if self._two_piece is not None:
                self._two_piece.cleanup()
            # Re-arm fresh: the blocking clear consumed real time, so the window
            # restarts from now, not from the pre-clear timestamp.
            self._rearmProgress(now)
            self.logger.info(
                f"ClassificationChannel: auto-resolve cleared the channel after advancing "
                f"{result.output_deg_moved:.0f}° — resuming feeding"
            )
            return True
        self.logger.warning(
            f"ClassificationChannel: auto-resolve advanced {result.output_deg_moved:.0f}° but the "
            f"channel is still occupied ({result.reason}) — falling back to the operator alert"
        )
        return False

    def cleanup(self) -> None:
        self.gc.profiler.exitState("classification")
        if self._two_piece is not None:
            self._two_piece.cleanup()
            return
        # Tearing down mid-cycle (machine stop / standby): if a piece was
        # photographed but never classified or distributed, mark it aborted so
        # the UI drops it instead of leaving it stuck in "capturing" forever.
        if self._mode == ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01:
            current = self.states_map[self.current_state]
            abandon = getattr(current, "abandonInFlightObject", None)
            if callable(abandon):
                abandon("classification channel teardown")
        self.states_map[self.current_state].cleanup()
        if self._dynamic_mode and hasattr(self.transport, "resetDynamicState"):
            self.transport.resetDynamicState()
        # Reset to IDLE so the next resume / start re-runs the chamber
        # purge check instead of resuming mid-cycle.
        self.current_state = ClassificationChannelState.IDLE
