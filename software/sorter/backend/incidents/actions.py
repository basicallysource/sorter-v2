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


def _passThrough(gc: Any, incident: dict[str, Any]) -> None:
    from server import shared_state

    approve = getattr(shared_state, "approveDistributionNoBinPassthrough", None)
    if callable(approve):
        piece = incident.get("piece_uuid")
        approve(piece if isinstance(piece, str) else None)
    _done(gc, incident)


ACTIONS: dict[str, Action] = {
    "done": Action("Done", _done),
    "clear_c4": Action("Turn to clear", _clearC4),
    "clear_stall": Action("Done", _clearStall),
    "rehome_chute": Action("Home chute", _rehomeChute),
    "pass_through": Action("Send to bucket", _passThrough),
}
