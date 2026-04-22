from __future__ import annotations

from subsystems.feeder.analysis import ChannelAction


CH3_PRECISE_HOLDOVER_MS = 2000


class C3HoldoverStrategy:
    def __init__(self, holdover_ms: int = CH3_PRECISE_HOLDOVER_MS) -> None:
        self._holdover_ms = int(holdover_ms)
        self._last_precise_at: float = 0.0

    @property
    def active(self) -> bool:
        return self._last_precise_at > 0.0

    @property
    def state_name(self) -> str:
        return "holding" if self.active else "idle"

    def reset(self) -> None:
        self._last_precise_at = 0.0

    def apply(self, action: ChannelAction, now_mono: float) -> ChannelAction:
        if action == ChannelAction.PULSE_PRECISE:
            self._last_precise_at = now_mono
            return action
        if (
            action == ChannelAction.PULSE_NORMAL
            and self._last_precise_at > 0.0
            and (now_mono - self._last_precise_at) * 1000 < self._holdover_ms
        ):
            return ChannelAction.PULSE_PRECISE
        return action


__all__ = ["CH3_PRECISE_HOLDOVER_MS", "C3HoldoverStrategy"]
