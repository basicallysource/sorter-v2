"""Default `ConstantPulseEjection` ejection-timing strategy.

Emits a fixed `EjectionTiming` regardless of the piece context. Values come
from the old ``subsystems/channels/c3_precise.py`` hard-coded constants; per-
piece tuning is a future strategy.
"""

from __future__ import annotations

from typing import Any

from rt.contracts.ejection import EjectionTiming
from rt.contracts.registry import register_ejection_timing


@register_ejection_timing("constant")
class ConstantPulseEjection:
    """Emits the same pulse/settle/fall-time for every piece."""

    key = "constant"

    def __init__(
        self,
        *,
        pulse_ms: float = 40.0,
        settle_ms: float = 80.0,
        fall_time_ms: float = 350.0,
    ) -> None:
        self._timing = EjectionTiming(
            pulse_ms=float(pulse_ms),
            settle_ms=float(settle_ms),
            fall_time_ms=float(fall_time_ms),
        )

    def timing_for(self, piece_context: dict[str, Any]) -> EjectionTiming:  # noqa: ARG002
        return self._timing


__all__ = ["ConstantPulseEjection"]
