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
"""

import time

from global_config import GlobalConfig

STEPPER_STALL_INCIDENT_KIND = "stepper_stall"

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

        # 3) The incident is a pure projection of the latch state.
        self._sync_incident(now_stalled)

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

    def _sync_incident(self, stalled: set[str]) -> None:
        rs = self._gc.runtime_stats
        active = rs.activeIncident()
        active_kind = active.get("kind") if isinstance(active, dict) else None
        if stalled:
            # Raise/refresh our incident — but never stomp a different incident.
            if active is None or active_kind == STEPPER_STALL_INCIDENT_KIND:
                names = sorted(stalled)
                rs.setActiveIncident(
                    {
                        "kind": STEPPER_STALL_INCIDENT_KIND,
                        "channel": names[0],
                        "steppers": names,
                        "status": "needs_manual_fix",
                        "operator_message": (
                            f"Motor stall detected on {', '.join(names)}. Clear the jam, "
                            "then clear the stall to resume."
                        ),
                    }
                )
        elif active_kind == STEPPER_STALL_INCIDENT_KIND:
            # Nothing latched anymore -> our incident is stale; resolve it.
            rs.clearActiveIncident(kind=STEPPER_STALL_INCIDENT_KIND)
