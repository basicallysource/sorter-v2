"""When Hive last heard from a machine."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.machine import Machine

# How stale machines.last_seen_at may get before an upload refreshes it.
LAST_SEEN_MIN_INTERVAL_S = 30.0


def mark_machine_seen(machine: Machine, now: datetime) -> None:
    """Record that ``machine`` was just heard from, unless that was already
    recorded in the last ``LAST_SEEN_MIN_INTERVAL_S`` seconds.

    A machine can send many files a minute; writing its machines row on every
    one would make each upload wait on every other write to that row, for a
    timestamp nobody reads more finely than a minute.
    """
    last = machine.last_seen_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < LAST_SEEN_MIN_INTERVAL_S:
            return
    machine.last_seen_at = now
