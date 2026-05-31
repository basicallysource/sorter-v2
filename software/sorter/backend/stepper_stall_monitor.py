"""StallGuard stall detection -> operator incident.

The TMC2209 raises its DIAG line when a configured motor stalls; the firmware
latches that per channel. Detection is turned ON for any stepper that has an
enabled `[stepper_stallguard.*]` entry — switched on once at hardware init (see
`applyStepperStallguard`) and left on. There is NO per-move or per-state arming:
if a motor has a threshold, every move is protected, full stop.

This monitor only watches. It polls the per-board latch over USB and, on a stall,
publishes a blocking `stepper_stall` incident. The coordinator then halts all flow
until the operator clears the jam and acknowledges — there is deliberately NO
auto-recovery, because a real stall needs hands.
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
        # True once we've raised an incident; reset (and the firmware latch
        # cleared) after the operator acknowledges, so the next stall is caught.
        self._raised = False

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
        groups = self._enabled_groups(irl) if irl is not None else {}
        if not groups:
            return

        runtime_stats = self._gc.runtime_stats
        active = runtime_stats.activeIncident()
        if isinstance(active, dict) and active.get("kind") == STEPPER_STALL_INCIDENT_KIND:
            return  # our incident is up; the machine is held, waiting for ack
        if self._raised:
            # Operator acknowledged (our incident is gone). Reset the firmware
            # latches so the next stall is caught.
            for steppers in groups.values():
                for stepper in steppers:
                    try:
                        stepper.clear_stall()
                        stepper.enable_stall_detection(True)
                    except Exception:
                        pass
            self._raised = False
            return
        if isinstance(active, dict):
            return  # a different incident holds the machine; don't poll over it

        stalled: list[str] = []
        for iface, steppers in groups.items():
            try:
                mask = iface.get_stall_status()
            except Exception as e:
                self._gc.logger.warning(
                    f"StallGuard poll failed on board '{getattr(iface, 'name', '?')}': {e}"
                )
                continue
            for stepper in steppers:
                if mask & (1 << stepper.channel):
                    stalled.append(stepper.name)
        if stalled:
            self._raise_incident(stalled)

    def _raise_incident(self, names: list[str]) -> None:
        self._gc.logger.error(f"Stepper stall detected on {names}; halting machine.")
        self._gc.runtime_stats.setActiveIncident(
            {
                "kind": STEPPER_STALL_INCIDENT_KIND,
                "channel": names[0],
                "steppers": names,
                "status": "needs_manual_fix",
                "operator_message": (
                    f"Motor stall detected on {', '.join(names)}. Clear the jam, "
                    "then acknowledge to resume."
                ),
            }
        )
        self._raised = True
