"""What an incident card's buttons do. Each runs against the open incident."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Action:
    label: str
    run: Callable[[Any, dict[str, Any]], None]


def _done(gc: Any, incident: dict[str, Any]) -> None:
    gc.runtime_stats.clearActiveIncident(kind=incident.get("kind"), resolved_by="operator")


def _closeWarning(gc: Any, incident: dict[str, Any]) -> None:
    gc.runtime_stats.clearWarning(
        str(incident.get("kind")), subject=incident.get("subject"), resolved_by="operator"
    )


def _restartSeen(gc: Any, incident: dict[str, Any]) -> None:
    # The operator has read why the machine restarted: the card stays away
    # for that restart, also after the next start.
    import boot_record

    try:
        boot_record.markSeen(str(incident.get("kind")), incident.get("record_id"))
    except OSError as exc:
        gc.logger.warning(f"boot record: seeing the restart was not saved: {exc}")
    _closeWarning(gc, incident)


def _stopRecovery(gc: Any, incident: dict[str, Any]) -> None:
    import recovery

    if not recovery.stop(gc):
        raise RuntimeError("Nothing is being tried for it.")


def _clearC4(gc: Any, incident: dict[str, Any]) -> None:
    from server import shared_state

    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None)
    classification = getattr(coordinator, "classification", None)
    request = getattr(classification, "requestStallAutoResolve", None)
    if not callable(request) or not request():
        raise RuntimeError("The classification channel is not running.")


def _clearStall(gc: Any, incident: dict[str, Any]) -> None:
    from server.routers import stallguard

    stallguard.clear_stall_incident()


def _rehomeChute(gc: Any, incident: dict[str, Any]) -> None:
    from server.routers import stallguard

    stallguard.rehome_after_stall()


def _retryDriver(gc: Any, incident: dict[str, Any]) -> None:
    import driver_watch

    if not driver_watch.retry(str(incident.get("channel") or "")):
        raise RuntimeError("That motor's driver is not being watched.")


def _passThrough(gc: Any, incident: dict[str, Any]) -> None:
    from server import shared_state

    approve = getattr(shared_state, "approveDistributionNoBinPassthrough", None)
    if callable(approve):
        piece = incident.get("piece_uuid")
        approve(piece if isinstance(piece, str) else None)
    _done(gc, incident)


ACTIONS: dict[str, Action] = {
    "done": Action("Done", _done),
    "close_warning": Action("Done", _closeWarning),
    "restart_seen": Action("Done", _restartSeen),
    "stop_recovery": Action("Stop", _stopRecovery),
    "clear_c4": Action("Turn to clear", _clearC4),
    "clear_stall": Action("Done", _clearStall),
    "rehome_chute": Action("Home chute", _rehomeChute),
    "retry_driver": Action("Try again", _retryDriver),
    "pass_through": Action("Send to bucket", _passThrough),
}
