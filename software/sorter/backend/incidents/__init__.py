"""Incidents: the machine noticed something it cannot sort past on its own.

Subsystems say what they see (``report``) and when it is gone (``clear``).
This package owns the rest: what each kind is called and what the operator
does about it (``kinds.py``), what the card's buttons do (``actions.py``), how
a kind is handled (off, manual, automatic, set on the Incidents settings page),
and the card the dashboard shows (``describe``).

One incident is open at a time, and the machine holds while it is. The slot
still lives in ``runtime_stats`` until every kind reports through here.
"""

from __future__ import annotations

import time
from typing import Any

from .actions import ACTIONS
from .kinds import ALIASES, AUTOMATIC, KINDS, MANUAL, OFF, IncidentKind

__all__ = [
    "ACTIONS", "ALIASES", "AUTOMATIC", "KINDS", "MANUAL", "OFF", "IncidentKind",
    "act", "clear", "describe", "handling", "openIncident", "report",
]

# How a stepper is named on a card.
_MOTORS = {
    "c_channel_1_rotor": "C1",
    "c_channel_2_rotor": "C2",
    "c_channel_3_rotor": "C3",
    "carousel": "The classification channel",
    "chute_stepper": "The chute",
}


def handling(kind: str) -> str:
    """off, manual or automatic, as set for this kind (manual when it has no setting)."""
    from toml_config import incidentHandlingMode

    return incidentHandlingMode(kind)


def openIncident(gc: Any, kind: str | None = None, subject: str | None = None) -> dict[str, Any] | None:
    """The open incident, if there is one and it matches."""
    runtime_stats = getattr(gc, "runtime_stats", None)
    active = runtime_stats.activeIncident() if runtime_stats is not None else None
    if not isinstance(active, dict):
        return None
    if kind is not None and active.get("kind") != kind:
        return None
    if subject is not None and active.get("subject") != subject:
        return None
    return active


def report(gc: Any, kind: str, *, subject: str, **fields: Any) -> bool:
    """Open this kind's incident for ``subject`` (a channel, a motor), or keep
    the one already open for it. Returns whether it is open: False when the
    kind is switched off, or another incident already holds the machine."""
    if handling(kind) == OFF:
        return False
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None:
        return False
    active = runtime_stats.activeIncident()
    if isinstance(active, dict):
        return active.get("kind") == kind and active.get("subject") == subject
    runtime_stats.setActiveIncident(
        {"kind": kind, "subject": subject, "triggered_at": time.time(), **fields}
    )
    return True


def clear(gc: Any, kind: str, *, subject: str | None = None, resolved_by: str = "system") -> None:
    """The problem is gone: close this kind's incident (for ``subject``, if given)."""
    if openIncident(gc, kind, subject) is not None:
        gc.runtime_stats.clearActiveIncident(kind=kind, resolved_by=resolved_by)


def describe(incident: dict[str, Any] | None) -> dict[str, Any] | None:
    """The dashboard's card: a title, one line of what to do, and its buttons."""
    if not isinstance(incident, dict):
        return None
    kind = KINDS.get(ALIASES.get(str(incident.get("kind")), str(incident.get("kind"))))
    subject = _subject(incident)
    if kind is None:
        title, todo, actions = str(incident.get("kind") or "Incident"), str(
            incident.get("operator_message") or ""
        ), ("done",)
    else:
        title, todo, actions = kind.title, kind.todo, kind.actionsFor(incident)
    fields = _Fields(incident, subject)
    return {
        "kind": incident.get("kind"),
        "title": title,
        "subject": subject,
        "todo": todo.format_map(fields),
        "actions": [{"key": key, "label": ACTIONS[key].label} for key in actions],
        "since": incident.get("triggered_at"),
    }


def act(gc: Any, action: str) -> dict[str, Any]:
    """Run one of the open incident's buttons."""
    incident = openIncident(gc)
    if incident is None:
        return {"ok": True, "acted": False}
    card = describe(incident) or {}
    if action not in {a["key"] for a in card.get("actions", [])}:
        raise ValueError(f"{card.get('title', 'This incident')} has no action {action!r}.")
    ACTIONS[action].run(gc, incident)
    return {"ok": True, "acted": True, "kind": incident.get("kind")}


def _subject(incident: dict[str, Any]) -> str:
    for key in ("subject", "channel_label"):
        value = incident.get(key)
        if isinstance(value, str) and value:
            return value
    steppers = incident.get("steppers")
    if isinstance(steppers, list) and steppers:
        return ", ".join(_MOTORS.get(str(s), str(s)) for s in steppers)
    channel = incident.get("channel")
    return _MOTORS.get(str(channel), str(channel).upper()) if channel else ""


class _Fields(dict):
    """The incident's fields for a todo line; a missing one reads as a plain word."""

    def __init__(self, incident: dict[str, Any], subject: str) -> None:
        super().__init__(incident)
        self.setdefault("channel", subject or "the channel")
        self.setdefault("motor", subject or "A motor")
        self.setdefault("upstream", incident.get("upstream_label") or "the channel above")

    def __missing__(self, key: str) -> str:
        return key
