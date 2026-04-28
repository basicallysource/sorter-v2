from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EjectionTiming:
    """Pulse + settle + fall-time window for a single ejection event."""

    pulse_ms: float
    settle_ms: float
    fall_time_ms: float


class EjectionTimingStrategy(Protocol):
    """How a Runtime (esp. C3, C4) decides timing of its ejection pulse and
    settle/fall-time windows. Swappable per hardware variant, per seed profile,
    or per experimental tuning run."""

    key: str

    def timing_for(self, piece_context: dict[str, Any]) -> EjectionTiming: ...
