"""How long an exit holds after a piece falls, from how long pieces take to land.

A channel pushes nothing off its exit for a while after a piece falls, so the
next channel sees it land first. How long a piece takes to land is measured
from the pieces seen to fall and then land (zones/watch.py), so a machine with
a long drop or a ramp holds longer, and a quick one no longer than it needs.
What it set and why is in ``report()``, on the feeder's tuning page.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

# The hold: the time nine in ten pieces took to land, plus HOLD_MARGIN_S,
# within HOLD_MIN_S and HOLD_MAX_S, once HOLD_LANDINGS_NEEDED falls have been
# seen to land. A landing slower than SLOW_LANDING_S is left out: that is
# another piece turning up, not the one that fell. Worked out again at most
# every HOLD_EVERY_S.
HOLD_MARGIN_S = 0.3
HOLD_MIN_S = 0.5
HOLD_MAX_S = 2.5
HOLD_LANDINGS_NEEDED = 20
SLOW_LANDING_S = 3.0
HOLD_EVERY_S = 5.0


def _quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(share * (len(ordered) - 1))))]


def _landingDelays(channel: int) -> list[float]:
    from zones import watch

    current = watch.current()
    if current is None:
        return []
    return [h.delay_s for h in current.handoffs(channel)]


class LandingHold:
    def __init__(self, landing_delays: Callable[[int], list[float]] = _landingDelays) -> None:
        self._landing_delays = landing_delays
        self._lock = threading.Lock()
        self._holds: dict[int, dict[str, Any]] = {}
        self._held_at: dict[int, float] = {}

    def holdS(self, channel: int, configured_s: float, follows_landings: bool, mono: float) -> float:
        """How long the exit of ``channel`` holds after a piece falls: from how
        long pieces have taken to land, or the configured hold until enough
        have been seen (or when it should not follow them)."""
        if not follows_landings:
            with self._lock:
                self._holds[channel] = {"hold_s": configured_s, "measured": False, "follows": False, "landings": 0}
                self._held_at.pop(channel, None)
            return configured_s
        if mono - self._held_at.get(channel, -1e9) >= HOLD_EVERY_S:
            try:
                delays = [d for d in self._landing_delays(channel) if 0.0 <= d <= SLOW_LANDING_S]
            except Exception:
                delays = []
            entry: dict[str, Any] = {"hold_s": None, "measured": False, "follows": True, "landings": len(delays)}
            if len(delays) >= HOLD_LANDINGS_NEEDED:
                p90 = _quantile(delays, 0.9)
                entry.update(hold_s=min(HOLD_MAX_S, max(HOLD_MIN_S, p90 + HOLD_MARGIN_S)), measured=True, p90_s=p90)
            with self._lock:
                self._holds[channel] = entry
                self._held_at[channel] = mono
        entry = self._holds[channel]
        return entry["hold_s"] if entry["measured"] else configured_s

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {"hold": {str(ch): dict(entry) for ch, entry in self._holds.items()}}


_hold: Optional[LandingHold] = None
_hold_lock = threading.Lock()


def get() -> LandingHold:
    global _hold
    with _hold_lock:
        if _hold is None:
            _hold = LandingHold()
        return _hold
