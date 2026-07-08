"""StallGuard stall detection -> per-stepper state -> operator incident.

The TMC2209 raises its DIAG line when a configured motor stalls; the firmware
latches that per channel. Detection is turned ON for any stepper that has an
enabled `[stepper_stallguard.*]` entry — switched on once at hardware init (see
`applyStepperStallguard`) and left on. There is NO per-move or per-state arming:
if a motor has a threshold, every move is protected, full stop.

This monitor is the single source of truth for "is motor X stalled". Each poll it
reads every board's latch bitmask and mirrors it onto `stepper.stalled` per
stepper. Everything else is *derived* from that:

- The blocking `stepper_stall` incident is a pure projection of "any stepper
  latched" — raised while at least one is stalled, auto-resolved once none are.
- The per-stepper UI reads `stepper.stalled` and clears a specific motor's latch.

Clearing therefore happens by clearing the firmware latch (globally or per
stepper); the incident then resolves itself on the next poll. There is still NO
auto-recovery: the latch only clears when something explicitly clears it (an
operator action), because a real stall needs hands. A fresh stall also
invalidates the affected subsystem's home reference (lost steps => unknown
position), forcing a re-home.

Because a chute stall loses the home reference, clearing the stall latch alone is
NOT enough to resume sorting: the chute position is untrustworthy. So once the
stall latch is gone but the chute is still unhomed, this monitor raises a
follow-on blocking `chute_needs_homing` incident (a pure projection of
`chute.homed`). It keeps the machine halted until the chute is re-homed, and
auto-resolves the instant `chute.homed` becomes true again.
"""

import time

from global_config import GlobalConfig

STEPPER_STALL_INCIDENT_KIND = "stepper_stall"
CHUTE_NEEDS_HOMING_INCIDENT_KIND = "chute_needs_homing"

# Poll cadence. Runs on its own daemon thread (not the main loop) so the UART
# round-trips never hitch 30 Hz operation. Each cycle issues one GET_STALL_STATUS
# per board, so cost scales with board count, not motor count.
STALL_POLL_INTERVAL_S = 0.25


class StepperStallMonitor:
    def __init__(self, gc: GlobalConfig):
        self._gc = gc
        # Names stalled as of the previous poll, so we can act on rising edges
        # (a *newly* stalled motor) — e.g. invalidate its home reference once.
        self._prev_stalled: set[str] = set()

    def run(self) -> None:
        import server.shared_state as shared_state

        while True:
            try:
                self.poll(shared_state.getActiveIRL())
            except Exception as e:
                self._gc.logger.warning(f"Stall monitor poll error: {e}")
            time.sleep(STALL_POLL_INTERVAL_S)

    def _enabled_groups(self, irl) -> dict:
        # board interface -> [StepperMotor] for every configured+enabled stepper.
        groups: dict = {}
        interfaces = getattr(irl, "interfaces", None) or {}
        for iface in interfaces.values():
            for stepper in getattr(iface, "steppers", ()):  # raw per-board steppers
                if getattr(stepper, "stallguard_enabled", False) and stepper.stallguard_sgthrs is not None:
                    groups.setdefault(iface, []).append(stepper)
        return groups

    def poll(self, irl) -> None:
        if irl is None:
            return
        groups = self._enabled_groups(irl)
        if not groups:
            return

        # 1) Mirror the firmware latch onto each stepper. On a board read failure we
        #    keep that board's steppers at their last known state (don't falsely
        #    clear a real stall just because one UART read glitched).
        now_stalled: set[str] = set()
        for iface, steppers in groups.items():
            try:
                mask = iface.get_stall_status()
            except Exception as e:
                self._gc.logger.warning(
                    f"StallGuard poll failed on board '{getattr(iface, 'name', '?')}': {e}"
                )
                for stepper in steppers:
                    if getattr(stepper, "stalled", False):
                        now_stalled.add(stepper.name)
                continue
            for stepper in steppers:
                stepper.stalled = bool(mask & (1 << stepper.channel))
                if stepper.stalled:
                    now_stalled.add(stepper.name)

        # 2) Rising edges: a newly stalled motor lost steps -> drop its home ref.
        newly = now_stalled - self._prev_stalled
        if newly:
            self._gc.logger.error(f"Stepper stall detected on {sorted(newly)}.")
            self._invalidate_home(irl, newly)
        self._prev_stalled = now_stalled

        # A stall is a machine fault, not a soft hold: park the machine. Requesting
        # the pause every poll while both stalled AND running is deliberate — it is
        # the detection-side half of the invariant "a stalled machine never runs"
        # (the other half is resume being refused while the incident is active). It
        # self-limits: the pause lands within a main-loop tick and then the state is
        # no longer RUNNING, so no further requests go out.
        if now_stalled:
            self._request_pause_if_running()

        # 3) The incident is a pure projection of the latch state, plus the
        #    derived "chute lost its home reference" hold. `homed` defaults to
        #    True so a chute without the attribute never raises a spurious hold.
        chute = getattr(irl, "chute", None)
        chute_unhomed = chute is not None and not bool(getattr(chute, "homed", True))
        self._sync_incident(now_stalled, chute_unhomed, self._controller_live())

    def _request_pause_if_running(self) -> None:
        try:
            import server.shared_state as shared_state

            controller = shared_state.controller_ref
            if controller is None:
                return
            if getattr(getattr(controller, "state", None), "value", None) != "running":
                return
            q = shared_state.command_queue
            if q is None:
                return
            from defs.events import PauseCommandEvent, PauseCommandData

            q.put(PauseCommandEvent(tag="pause", data=PauseCommandData()))
            self._gc.logger.warning("Stall while running -> requesting machine pause.")
        except Exception:
            pass

    def _controller_live(self) -> bool:
        # The chute is unhomed during the normal pre-home startup window too
        # (a fresh IRL exists before its chute is homed). Only treat "unhomed"
        # as an operator-blocking condition once a controller is published, i.e.
        # the machine finished bringing up and is running/paused.
        try:
            import server.shared_state as shared_state

            return shared_state.controller_ref is not None
        except Exception:
            return False

    def _invalidate_home(self, irl, names: set[str]) -> None:
        chute = getattr(irl, "chute", None)
        if chute is None:
            return
        cs = getattr(chute, "stepper", None)
        if cs is not None and getattr(cs, "name", None) in names and hasattr(chute, "markUnhomed"):
            try:
                chute.markUnhomed("stall")
            except Exception:
                pass

    def _sync_incident(
        self, stalled: set[str], chute_unhomed: bool, controller_live: bool
    ) -> None:
        rs = self._gc.runtime_stats
        active = rs.activeIncident()
        active_kind = active.get("kind") if isinstance(active, dict) else None
        # Our two derived incidents. We freely transition between them (stall ->
        # needs-homing once the latch clears, needs-homing -> stall on a fresh
        # stall) but never stomp a third party's incident in the single slot.
        ours = {STEPPER_STALL_INCIDENT_KIND, CHUTE_NEEDS_HOMING_INCIDENT_KIND}
        if stalled:
            if active is None or active_kind in ours:
                names = sorted(stalled)
                # A chute stall drops the home reference -> the resolution is a
                # re-home, not a plain resume. Flag it so the UI offers re-home.
                if chute_unhomed:
                    message = (
                        f"Motor stall detected on {', '.join(names)}. Clear the jam, "
                        "then re-home the chute to resume sorting."
                    )
                else:
                    message = (
                        f"Motor stall detected on {', '.join(names)}. Clear the jam, "
                        "then clear the stall to resume."
                    )
                rs.setActiveIncident(
                    {
                        "kind": STEPPER_STALL_INCIDENT_KIND,
                        "channel": names[0],
                        "steppers": names,
                        "status": "needs_manual_fix",
                        "requires_rehome": bool(chute_unhomed),
                        "operator_message": message,
                    }
                )
            return
        if chute_unhomed and controller_live:
            # Latch is gone but the chute never got re-homed -> keep the machine
            # halted with a dedicated needs-homing hold.
            if active is None or active_kind in ours:
                rs.setActiveIncident(
                    {
                        "kind": CHUTE_NEEDS_HOMING_INCIDENT_KIND,
                        "channel": "chute_stepper",
                        "status": "needs_manual_fix",
                        "operator_message": (
                            "The chute lost its home reference after a stall. "
                            "Re-home the chute to resume sorting."
                        ),
                    }
                )
            return
        if active_kind in ours:
            # Nothing latched and the chute is homed -> our incident is stale.
            rs.clearActiveIncident(kind=active_kind)
