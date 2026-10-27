"""Recovery: when a piece is stuck, the machine works through a procedure to
free it (procedures.py) while the piece's incident holds everything else, shows
on the incident's card which step it is on, and stops if the operator says so.

A subsystem that finds a stuck piece opens its incident and, when that kind is
handled automatically, ``start``s a procedure. The coordinator ``step``s it on
every tick while the incident is open. Freed, the incident closes itself; given
up, the card asks the operator.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .motors import ChannelMotor
from .procedures import PROCEDURES, Procedure
from .profiles import SHAKES, ShakeProfile, shakeProfile
from .runner import FREED, GAVE_UP, RUNNING, STOPPED, Judge, Recovery

__all__ = [
    "ChannelMotor", "FREED", "GAVE_UP", "PROCEDURES", "Procedure", "RUNNING", "SHAKES",
    "STOPPED", "ShakeProfile", "current", "running", "shakeProfile", "start", "step", "stop",
]


@dataclass
class _Run:
    recovery: Recovery
    kind: str
    published: Optional[dict[str, Any]] = None


_run: Optional[_Run] = None


def running() -> bool:
    return _run is not None


def current() -> Optional[dict[str, Any]]:
    return _run.recovery.progress() if _run is not None else None


def start(
    gc: Any,
    procedure: str,
    *,
    kind: str,
    motors: dict[str, ChannelMotor],
    judge: Judge,
    exit_turn: Callable[[], Optional[float]] | None = None,
) -> bool:
    """Start ``procedure`` for the open ``kind`` incident. False when another
    recovery is running or the incident is not open."""
    global _run
    import incidents

    if _run is not None or incidents.openIncident(gc, kind) is None:
        return False
    _run = _Run(Recovery(PROCEDURES[procedure], motors, judge, exit_turn), kind)
    _publish(gc, _run)
    return True


def step(gc: Any) -> None:
    """One tick, while an incident holds the machine."""
    global _run
    run = _run
    if run is None:
        return
    import incidents

    if incidents.openIncident(gc, run.kind) is None:
        # Done was pressed, or something else closed it: stop moving.
        run.recovery.stop()
        _run = None
        return
    run.recovery.step()
    _publish(gc, run)
    if run.recovery.done:
        _run = None
        if run.recovery.state == FREED:
            gc.runtime_stats.clearActiveIncident(kind=run.kind, resolved_by="recovery")


def stop(gc: Any) -> bool:
    run = _run
    if run is None:
        return False
    run.recovery.stop()
    _publish(gc, run)
    return True


def _publish(gc: Any, run: _Run) -> None:
    """Put the recovery's progress on its incident, so the card shows it, and
    log each change to the control data."""
    progress = run.recovery.progress()
    if progress == run.published:
        return
    run.published = progress
    runtime_stats = getattr(gc, "runtime_stats", None)
    active = runtime_stats.activeIncident() if runtime_stats is not None else None
    if isinstance(active, dict) and active.get("kind") == run.kind:
        runtime_stats.setActiveIncident({**active, "recovery": progress})
    try:
        gc.logger.info(f"Recovery {progress['procedure']}: step {progress['step']} of {progress['steps']}, {progress['state']}: {progress['doing']}")
    except Exception:
        pass
    try:
        import control_data_store

        control_data_store.record({"type": "event", "kind": "recovery", **progress, "t": time.time()})
    except Exception:
        pass
