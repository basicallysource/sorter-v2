import time

from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from subsystems.classification_channel.incidents import (
    C4_EXIT_STUCK_INCIDENT_KIND,
    c4_stall_incident_active,
    clear_c4_exit_stuck_incident,
    publish_c4_exit_stuck_incident,
    record_c4_exit_stuck_auto_resolved,
)

# General no-progress watchdog: if a piece is physically on the classification
# channel (perception n_pieces > 0) but the flow makes NO progress for this
# long, the process is wedged — no matter WHICH state it's stuck in or which
# zone perception thinks the piece is in. "Progress" covers phase changes,
# track ids appearing/leaving, zone changes, substantial piece movement, and
# capture/classify milestones.
# With automatic handling the watchdog first tries to clear the channel itself
# (rotate forward up to _STALL_AUTO_CLEAR_MAX_TURNS full output turns, checking
# occupancy as it goes); only if that fails does it raise the operator
# exit-stuck incident. While the incident is active the flow is frozen and only
# the watchdog keeps running, so the incident auto-clears the moment perception
# sees the channel empty. The threshold is well above any normal single-state
# dwell (rotate/classify/discharge all transition within a few seconds).
_STALL_INCIDENT_MS = 30000.0
_STALL_AUTO_CLEAR_MAX_TURNS = 2
from subsystems.shared_variables import SharedVariables


class ClassificationChannelStateMachine:
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
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.shared = shared
        self.vision = vision
        self.event_queue = event_queue
        self.transport = transport
        self.irl_config = irl_config
        from subsystems.classification_channel.two_piece import (
            TwoPieceClassificationChannel,
        )
        from subsystems.classification_channel.two_piece.context import (
            SimpleStateMachineRev01Context,
        )

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
        # The flow's phase (waiting_for_piece, waiting, ejecting, staging) is
        # what the runtime stats show as the classification channel's state.
        self._phase = self._two_piece.phaseName()
        if hasattr(self.gc, "runtime_stats"):
            self.gc.runtime_stats.observeStateTransition("classification", None, self._phase)
        # No-progress watchdog state: last time the SM made a transition (its
        # "progress" signal) and whether we've raised the stall incident.
        self._last_progress_at = time.monotonic()
        self._stall_incident_raised = False
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
        if not stall_hold:
            self._two_piece.step()
            phase = self._two_piece.phaseName()
            if phase != self._phase and hasattr(self.gc, "runtime_stats"):
                self.gc.runtime_stats.observeStateTransition("classification", self._phase, phase)
            self._phase = phase
        self._checkStall(time.monotonic())

    def _watchdogStateLabel(self) -> str:
        return self._two_piece.phaseName()

    def _progressAt(self) -> float:
        return float(self._two_piece.last_progress_at)

    def _rearmProgress(self, now: float) -> None:
        self._last_progress_at = now
        self._two_piece.noteProgress()

    def _checkStall(self, now: float) -> None:
        # If we raised the incident and it's since been resolved (operator
        # cleared it), re-arm from now so we don't instantly re-fire on the next
        # step — give the resumed flow a fresh window to make progress.
        if self._stall_incident_raised and not c4_stall_incident_active(self.gc):
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
            record_c4_exit_stuck_auto_resolved(
                self.gc,
                stalled_ms=stalled_ms,
                stalled_state=self._watchdogStateLabel(),
                moved_deg=auto_result.output_deg_moved,
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
        result = self._two_piece.attemptStallAutoClear(max_output_deg=max_output_deg)
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
        # Fresh watchdog window on the next start — a pause/standby stretch must
        # not count toward "stalled".
        self._last_progress_at = time.monotonic()
        self._two_piece.cleanup()
