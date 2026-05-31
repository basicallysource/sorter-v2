"""StallGuard stall detection -> operator incident.

The TMC2209 raises its DIAG line when a configured motor stalls; the firmware
latches that per channel. This monitor polls the latch over USB while the machine
is RUNNING and, on a stall, publishes a blocking `stepper_stall` incident. The
coordinator then halts all flow until the operator clears the jam and
acknowledges — there is deliberately NO auto-recovery, because a real stall needs
hands.

Detection is armed ONLY while RUNNING. Homing drives motors into hard endstops,
manual jogs and StallGuard sweeps push motors around at the operator's command —
all of which would otherwise trip a stall. Gating on RUNNING keeps those quiet.
"""

import time

from global_config import GlobalConfig
from defs.sorter_controller import SorterLifecycle

STEPPER_STALL_INCIDENT_KIND = "stepper_stall"

# Poll cadence. Runs on its own daemon thread (not the main loop) so the UART
# round-trips never hitch 30 Hz operation. Each cycle issues one GET_STALL_STATUS
# per board, so cost scales with board count, not motor count.
STALL_POLL_INTERVAL_S = 0.25

_TMC_REG_TCOOLTHRS = 0x14
_TMC_REG_SGTHRS = 0x40


class StepperStallMonitor:
    def __init__(self, gc: GlobalConfig):
        self._gc = gc
        self._armed = False
        # True once we've raised an incident; reset after the operator clears it
        # so we can re-arm the firmware latch and resume polling.
        self._raised = False

    def run(self, get_controller) -> None:
        import server.shared_state as shared_state

        while True:
            try:
                self.poll(get_controller(), shared_state.getActiveIRL())
            except Exception as e:
                self._gc.logger.warning(f"Stall monitor poll error: {e}")
            time.sleep(STALL_POLL_INTERVAL_S)

    def _armed_groups(self, irl) -> dict:
        # board interface -> [StepperMotor] for every configured+enabled stepper.
        groups: dict = {}
        interfaces = getattr(irl, "interfaces", None) or {}
        for iface in interfaces.values():
            for stepper in getattr(iface, "steppers", ()):  # raw per-board steppers
                if getattr(stepper, "stallguard_enabled", False) and stepper.stallguard_sgthrs is not None:
                    groups.setdefault(iface, []).append(stepper)
        return groups

    def _arm(self, groups: dict) -> None:
        # Re-write thresholds here (not just at init) so they survive sweeps and
        # coolstep toggles that clobber SGTHRS/TCOOLTHRS between runs.
        count = 0
        for steppers in groups.values():
            for stepper in steppers:
                try:
                    stepper.write_driver_register(_TMC_REG_SGTHRS, stepper.stallguard_sgthrs)
                    stepper.write_driver_register(_TMC_REG_TCOOLTHRS, stepper.stallguard_tcoolthrs)
                    stepper.clear_stall()
                    stepper.enable_stall_detection(True)
                    count += 1
                except Exception as e:
                    self._gc.logger.warning(f"StallGuard arm failed for '{stepper.name}': {e}")
        self._armed = True
        self._raised = False
        self._gc.logger.info(f"StallGuard armed on {count} stepper(s).")

    def _disarm(self, groups: dict) -> None:
        for steppers in groups.values():
            for stepper in steppers:
                try:
                    stepper.enable_stall_detection(False)
                except Exception:
                    pass
        self._armed = False
        self._raised = False

    def poll(self, controller, irl) -> None:
        running = controller is not None and getattr(controller, "state", None) == SorterLifecycle.RUNNING
        groups = self._armed_groups(irl) if irl is not None else {}

        if not running:
            if self._armed:
                self._disarm(groups)
            return
        if not groups:
            return
        if not self._armed:
            self._arm(groups)
            return

        runtime_stats = self._gc.runtime_stats
        active = runtime_stats.activeIncident()
        if isinstance(active, dict) and active.get("kind") == STEPPER_STALL_INCIDENT_KIND:
            return  # our incident is up; the machine is held, waiting for ack
        if self._raised:
            # Operator acknowledged (our incident is gone). Reset firmware latches
            # and re-arm so the next stall is caught.
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
