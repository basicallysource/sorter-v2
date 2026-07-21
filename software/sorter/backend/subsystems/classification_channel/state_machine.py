import time

from global_config import GlobalConfig
from irl.config import ClassificationChannelMode, IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from subsystems.base_subsystem import BaseSubsystem
from subsystems.classification_channel.detecting import Detecting
from subsystems.classification_channel.ejecting import Ejecting
from subsystems.classification_channel.idle import Idle
from subsystems.classification_channel.incidents import (
    C4_EXIT_STUCK_INCIDENT_KIND,
    c4_stall_incident_active,
    clear_c4_exit_stuck_incident,
    publish_c4_exit_stuck_incident,
)

# General no-progress watchdog: if a piece is physically on the classification
# channel (perception n_pieces > 0) but the flow makes NO progress for this
# long, the process is wedged — no matter WHICH state it's stuck in or which
# zone perception thinks the piece is in. "Progress" is a state transition in
# simple mode; in two-piece mode it also covers track ids appearing/leaving,
# zone changes, substantial piece movement, and capture/classify milestones.
# With automatic handling the watchdog first tries to clear the channel itself
# (rotate forward up to _STALL_AUTO_CLEAR_MAX_TURNS full output turns, checking
# occupancy as it goes); only if that fails does it raise the operator
# exit-stuck incident. While the incident is active the flow is frozen and only
# the watchdog keeps running, so the incident auto-clears the moment perception
# sees the channel empty. The threshold is well above any normal single-state
# dwell (rotate/classify/discharge all transition within a few seconds).
_STALL_INCIDENT_MS = 30000.0
_STALL_AUTO_CLEAR_MAX_TURNS = 2
# Phantom drop-zone recovery. When rotating the platter can't clear a stall, the
# piece is almost always hung at the feeder->classification hand-off (the C4
# camera sees it in the drop zone but it isn't on the platter). Before raising
# the operator incident, nudge the upstream feeder rotor a couple degrees and
# return to normal flow to see if that frees it (or seats it as a real,
# classifiable piece). Retry across this many stall windows, then escalate.
_PHANTOM_NUDGE_MAX_ATTEMPTS = 3
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
        # How many upstream-feeder phantom nudges we've spent on the current
        # stall. Reset whenever the channel clears or the operator resolves it.
        self._phantom_nudge_attempts = 0
        # Operator pressed "Auto Resolve" on an active stall incident: the next
        # step() runs the same rotate-to-clear routine the automatic policy
        # uses, on the coordinator thread (never from the HTTP handler).
        self._stall_resolve_requested = False

    def step(self) -> None:
        # While OUR stall incident is active the flow is frozen: only the
        # watchdog runs, so the incident auto-clears the moment the operator
        # removes the piece (or it finally falls off) — and nothing moves while
        # the operator's hands are in the machine.
        stall_hold = self._stall_incident_raised and c4_stall_incident_active(self.gc)
        if stall_hold and self._stall_resolve_requested:
            self._runRequestedStallResolve()
            stall_hold = self._stall_incident_raised and c4_stall_incident_active(self.gc)
        if self._two_piece is not None:
            if not stall_hold:
                self._two_piece.step()
            self._checkStall(time.monotonic())
            return
        if stall_hold:
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

    def _watchdogStateLabel(self) -> str:
        if self._two_piece is not None:
            return self._two_piece.phaseName()
        return self.current_state.value

    def _progressAt(self) -> float:
        if self._two_piece is not None:
            return float(self._two_piece.last_progress_at)
        return self._last_progress_at

    def _rearmProgress(self, now: float) -> None:
        self._last_progress_at = now
        if self._two_piece is not None:
            self._two_piece.noteProgress()

    def _checkStall(self, now: float) -> None:
        # Only the supported rev01 paths (simple + two-piece). Legacy/dynamic
        # paths have their own flow.
        if self._mode not in (
            ClassificationChannelMode.SIMPLE_STATE_MACHINE_REV01,
            ClassificationChannelMode.TWO_PIECE_STATE_MACHINE_REV01,
        ):
            return

        # If we raised the incident and it's since been resolved (operator
        # cleared it), re-arm from now so we don't instantly re-fire on the next
        # step — give the resumed flow a fresh window to make progress.
        if self._stall_incident_raised and not c4_stall_incident_active(self.gc):
            self._stall_incident_raised = False
            self._phantom_nudge_attempts = 0
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
            self._phantom_nudge_attempts = 0
            if self._stall_incident_raised:
                clear_c4_exit_stuck_incident(self.gc)
                self._stall_incident_raised = False
            return

        stalled_ms = (now - self._progressAt()) * 1000.0
        if self._stall_incident_raised or stalled_ms < _STALL_INCIDENT_MS:
            return

        try:
            from toml_config import incidentHandlingOff

            if incidentHandlingOff(C4_EXIT_STUCK_INCIDENT_KIND):
                return
        except Exception:
            pass

        # Auto-resolve: when this incident is set to automatic handling, try to
        # clear the channel ourselves (advance forward until the piece is gone,
        # the same routine spoke-home uses) instead of stopping for an operator.
        # Only fall through to the manual incident if that didn't clear it.
        auto_result = self._tryAutoResolveStall(stalled_ms)
        if auto_result is not None and auto_result.cleared:
            self._phantom_nudge_attempts = 0
            return

        # Rotating the platter couldn't clear it, and automatic handling is on
        # (auto_result is not None). The "piece" is almost certainly a phantom
        # hung at the feeder->classification hand-off, not on the platter. Nudge
        # the upstream feeder a couple degrees and return to normal flow to see
        # if that frees it (or seats it as a real, classifiable piece). Only
        # after a few failed nudges do we escalate to the operator.
        if auto_result is not None and self._phantom_nudge_attempts < _PHANTOM_NUDGE_MAX_ATTEMPTS:
            from subsystems.classification_channel.simple_state_machine_rev01.channel_clear import (
                nudgeUpstreamFeederOnce,
            )

            moved_deg = nudgeUpstreamFeederOnce(self.gc, self.irl)
            if moved_deg is not None:
                self._phantom_nudge_attempts += 1
                self._rearmProgress(now)
                self.logger.info(
                    f"ClassificationChannel: dropzone still occupied after channel "
                    f"advance — nudged upstream feeder {moved_deg:.1f}° (attempt "
                    f"{self._phantom_nudge_attempts}/{_PHANTOM_NUDGE_MAX_ATTEMPTS}), "
                    f"resuming to re-check"
                )
                return

        published = publish_c4_exit_stuck_incident(
            self.gc,
            stalled_ms=stalled_ms,
            stalled_state=self._watchdogStateLabel(),
            auto_clear_failed=auto_result is not None,
            auto_clear_moved_deg=(
                auto_result.output_deg_moved if auto_result is not None else 0.0
            ),
        )
        self._stall_incident_raised = bool(published)
        # Handed off to the operator (or a rival incident owns the slot): a fresh
        # stall later gets its own full budget of automatic nudges.
        self._phantom_nudge_attempts = 0
        if not published:
            # Another incident owns the slot (or stats are unavailable). Re-arm
            # so we retry after a full window instead of every tick.
            self._rearmProgress(now)
        self.logger.info(
            f"ClassificationChannel: STALLED in {self._watchdogStateLabel()} for "
            f"{stalled_ms:.0f}ms with a piece on the channel — raised exit-stuck "
            f"incident (published={self._stall_incident_raised})"
        )

    def _tryAutoResolveStall(self, stalled_ms: float):
        """Returns None when auto handling is off, otherwise the
        ChannelClearResult of the attempt (check .cleared)."""
        try:
            from toml_config import incidentHandlingAutomatic

            if not incidentHandlingAutomatic(C4_EXIT_STUCK_INCIDENT_KIND):
                return None
        except Exception:
            return None

        self.logger.info(
            f"ClassificationChannel: STALLED in {self._watchdogStateLabel()} for "
            f"{stalled_ms:.0f}ms — auto-resolve enabled, advancing channel to clear the piece"
        )
        return self._runStallClear()

    def _runStallClear(self):
        """The one stall-recovery action, shared by the automatic policy and the
        operator's Auto Resolve button: rotate the channel forward
        (occupancy-checked) until it clears or the budget runs out. Blocking;
        must only run on the coordinator thread. Returns a ChannelClearResult."""
        max_output_deg = _STALL_AUTO_CLEAR_MAX_TURNS * 360.0
        if self._two_piece is not None:
            result = self._two_piece.attemptStallAutoClear(max_output_deg=max_output_deg)
        else:
            from subsystems.classification_channel.simple_state_machine_rev01.channel_clear import (
                clearChannelByAdvancing,
            )

            result = clearChannelByAdvancing(
                self.gc,
                self.irl,
                self.irl_config,
                vision=self.vision,
                max_output_deg=max_output_deg,
            )
        if result.cleared:
            # Re-arm fresh: the blocking clear consumed real time, so the window
            # restarts from now, not from the pre-clear timestamp.
            self._rearmProgress(time.monotonic())
            self.logger.info(
                f"ClassificationChannel: stall clear advanced "
                f"{result.output_deg_moved:.0f}° and the channel is empty — resuming"
            )
        else:
            self.logger.warning(
                f"ClassificationChannel: stall clear advanced {result.output_deg_moved:.0f}° but the "
                f"channel is still occupied ({result.reason})"
            )
        return result

    def requestStallAutoResolve(self) -> bool:
        """Called from the HTTP router when the operator presses Auto Resolve on
        an active stall incident. Only sets a flag — the coordinator thread
        performs the actual motion on its next step()."""
        if not c4_stall_incident_active(self.gc):
            return False
        self._stall_resolve_requested = True
        return True

    def _runRequestedStallResolve(self) -> None:
        self._stall_resolve_requested = False
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return
        active = runtime_stats.activeIncident()
        if not isinstance(active, dict) or active.get("kind") != C4_EXIT_STUCK_INCIDENT_KIND:
            return
        # Show the run in the popup (and lock its buttons) before the blocking
        # clear starts.
        running = dict(active)
        running["status"] = "auto_release_running"
        running["awaiting_operator"] = False
        runtime_stats.setActiveIncident(running)
        self.logger.info(
            "ClassificationChannel: operator requested stall auto-resolve — "
            "advancing channel to clear the piece"
        )
        result = self._runStallClear()
        if result.cleared:
            clear_c4_exit_stuck_incident(self.gc)
            self._stall_incident_raised = False
            return
        failed = dict(running)
        failed["status"] = "waiting_for_operator"
        failed["awaiting_operator"] = True
        failed["auto_clear_failed"] = True
        failed["auto_clear_moved_deg"] = float(result.output_deg_moved)
        failed["operator_message"] = (
            "Auto resolve rotated the channel "
            f"{result.output_deg_moved:.0f}° and it is still occupied. Remove the "
            "piece (or clear the jam) to continue."
        )
        runtime_stats.setActiveIncident(failed)

    def cleanup(self) -> None:
        self.gc.profiler.exitState("classification")
        # Fresh watchdog window on the next start — a pause/standby stretch must
        # not count toward "stalled".
        self._last_progress_at = time.monotonic()
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
