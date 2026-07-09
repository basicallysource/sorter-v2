from global_config import GlobalConfig
from defs.events import ServerToMainThreadEvent
from sorter_controller import SorterController
from stepper_stall_monitor import (
    STEPPER_STALL_INCIDENT_KIND,
    CHUTE_NEEDS_HOMING_INCIDENT_KIND,
)

_RESUME_BLOCKING_INCIDENTS = {
    STEPPER_STALL_INCIDENT_KIND,
    CHUTE_NEEDS_HOMING_INCIDENT_KIND,
}


def _blockingFaultKind(gc: GlobalConfig) -> str | None:
    incident = gc.runtime_stats.activeIncident()
    kind = incident.get("kind") if isinstance(incident, dict) else None
    return kind if kind in _RESUME_BLOCKING_INCIDENTS else None


def handleServerToMainEvent(
    gc: GlobalConfig,
    controller: SorterController,
    event: ServerToMainThreadEvent,
) -> None:
    if event.tag == "pause":
        gc.logger.info("received pause command")
        controller.pause()
    elif event.tag == "resume":
        # A stall / lost-home is a hard fault: the machine stays parked until the
        # operator clears it (and re-homes the chute). Refuse resume here so no
        # code path — operator, queued command, or otherwise — can run onto a
        # stalled motor or an unhomed chute.
        fault = _blockingFaultKind(gc)
        if fault is not None:
            gc.logger.warning(f"Ignoring resume: blocked by active '{fault}' incident.")
            return
        gc.logger.info("received resume command")
        controller.resume()
    elif event.tag == "heartbeat":
        gc.logger.info(f"received heartbeat from server at {event.data.timestamp}")
    elif event.tag == "set_profiler_enabled":
        gc.logger.info(f"received set_profiler_enabled: {event.data.enabled}")
        gc.profiler.enabled = bool(event.data.enabled)
    else:
        gc.logger.warn(f"unknown event tag: {event.tag}")
