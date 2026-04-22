"""C4 ejection timing — constant pulse + settle + fall window.

Phase-4 C4 uses fixed values (pulse_ms, settle_ms, fall_time_ms). The
``fall_time_ms`` is the minimum wait after a commit before C4 may accept
the next piece — ports the legacy ``CHUTE_SETTLE_MS``-class constants. Per-
piece adaptive timing (size-class dependent fall) is a future strategy.
"""

from __future__ import annotations

from typing import Any

from rt.contracts.ejection import EjectionTiming
from rt.contracts.registry import register_ejection_timing


@register_ejection_timing("c4")
class C4EjectionTiming:
    """Constant classifier-chamber ejection window."""

    key = "c4"

    def __init__(
        self,
        *,
        pulse_ms: float = 150.0,
        settle_ms: float = 500.0,
        fall_time_ms: float = 1500.0,
    ) -> None:
        if pulse_ms <= 0.0:
            raise ValueError(f"pulse_ms must be > 0, got {pulse_ms}")
        if settle_ms < 0.0:
            raise ValueError(f"settle_ms must be >= 0, got {settle_ms}")
        if fall_time_ms < 0.0:
            raise ValueError(f"fall_time_ms must be >= 0, got {fall_time_ms}")
        self._timing = EjectionTiming(
            pulse_ms=float(pulse_ms),
            settle_ms=float(settle_ms),
            fall_time_ms=float(fall_time_ms),
        )

    def timing_for(self, piece_context: dict[str, Any]) -> EjectionTiming:  # noqa: ARG002
        return self._timing


__all__ = ["C4EjectionTiming"]
