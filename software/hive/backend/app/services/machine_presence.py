"""When Hive last heard from a machine."""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone

from app.models.machine import Machine

# How stale machines.last_seen_at may get before an upload refreshes it.
LAST_SEEN_MIN_INTERVAL_S = 60.0

# When a request in this process last took the write for each machine.
_taken: dict[str, float] = {}
_taken_lock = threading.Lock()
_monotonic = time.monotonic


def mark_machine_seen(machine: Machine, now: datetime) -> None:
    """Record that ``machine`` was just heard from, at most once a minute.

    A machine sends several files a second; writing its machines row on every
    one would make each upload wait on every other write to that row, for a
    timestamp nobody reads more finely than a minute. So the row is written
    only when the value loaded with the machine is ``LAST_SEEN_MIN_INTERVAL_S``
    old and no other request in this process has taken the write since: the
    requests that arrive together all load the same old value, and only the
    first of them writes.
    """
    last = machine.last_seen_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < LAST_SEEN_MIN_INTERVAL_S:
            return
    key = str(machine.id)
    taken_at = _monotonic()
    with _taken_lock:
        if taken_at - _taken.get(key, -math.inf) < LAST_SEEN_MIN_INTERVAL_S:
            return
        _taken[key] = taken_at
    machine.last_seen_at = now
