"""Generic purge strategy shared by C2/C3/C4 channels.

One instance per channel, bound via :class:`PurgePort`. Owns timing,
arming, clear-verification, and status. Does NOT own hardware calls or
piece-ownership — those live behind the port.
"""

from __future__ import annotations

from dataclasses import dataclass

from rt.contracts.purge import PurgeCounts, PurgePort


@dataclass(frozen=True, slots=True)
class PurgeTickResult:
    channel: str
    done: bool
    counts: PurgeCounts


class GenericPurgeStrategy:
    key = "purge_generic"

    def __init__(
        self,
        port: PurgePort,
        *,
        clear_hold_ms: float = 600.0,
    ) -> None:
        if clear_hold_ms < 0.0:
            raise ValueError(f"clear_hold_ms must be >= 0, got {clear_hold_ms}")
        self._port = port
        self._clear_hold_s = float(clear_hold_ms) / 1000.0
        self._clear_since: float | None = None
        self._armed = False

    @property
    def channel(self) -> str:
        return self._port.key

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def clear_hold_s(self) -> float:
        return self._clear_hold_s

    def arm(self) -> None:
        self._port.arm()
        self._clear_since = None
        self._armed = True

    def disarm(self) -> None:
        try:
            self._port.disarm()
        finally:
            self._armed = False
            self._clear_since = None

    def tick(self, now_mono: float) -> PurgeTickResult:
        """Advance one coordinator tick.

        Non-blocking. Always returns a fresh counts snapshot. Never
        auto-disarms — the coordinator owns disarm ordering (top-down
        topology gate), this method only drives drain + clear-hold
        bookkeeping.
        """
        counts = self._port.counts()
        if not self._armed:
            return PurgeTickResult(channel=self._port.key, done=True, counts=counts)

        if counts.is_empty:
            if self._clear_since is None:
                self._clear_since = float(now_mono)
        else:
            self._clear_since = None
            self._port.drain_step(float(now_mono))

        done = self._is_clear(counts, float(now_mono))
        return PurgeTickResult(channel=self._port.key, done=done, counts=counts)

    def is_channel_clear(self, now_mono: float) -> bool:
        """Channel-local clear check (counts empty + clear_hold elapsed).

        Knows nothing about upstream neighbours — topology gating is the
        coordinator's job.
        """
        if not self._armed:
            return True
        counts = self._port.counts()
        return self._is_clear(counts, float(now_mono))

    def _is_clear(self, counts: PurgeCounts, now_mono: float) -> bool:
        if not counts.is_empty:
            return False
        if self._clear_since is None:
            return False
        return (now_mono - self._clear_since) >= self._clear_hold_s


__all__ = ["GenericPurgeStrategy", "PurgeTickResult"]
