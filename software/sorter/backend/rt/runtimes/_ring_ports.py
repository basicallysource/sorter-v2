from __future__ import annotations

from typing import Any

from rt.contracts.purge import PurgeCounts


class RingPurgePort:
    """Shared purge binding for C2/C3 ring runtimes."""

    def __init__(self, runtime: Any, *, key: str, visible_count_attr: str) -> None:
        self._runtime = runtime
        self.key = key
        self._visible_count_attr = visible_count_attr

    def arm(self) -> None:
        self._runtime._purge_mode = True

    def disarm(self) -> None:
        self._runtime._purge_mode = False
        self._runtime._reset_bookkeeping()

    def counts(self) -> PurgeCounts:
        return PurgeCounts(
            piece_count=int(getattr(self._runtime, self._visible_count_attr)),
            owned_count=0,
            pending_detections=0,
        )

    def drain_step(self, now_mono: float) -> bool:
        del now_mono
        return bool(self._runtime._purge_mode)


class RingSampleTransportPort:
    """Shared sample-transport binding for C2/C3 ring runtimes."""

    def __init__(
        self,
        runtime: Any,
        *,
        key: str,
        dispatch_method: str = "_dispatch_sample_transport_pulse",
    ) -> None:
        self._runtime = runtime
        self.key = key
        self._dispatch_method = dispatch_method

    def step(self, now_mono: float) -> bool:
        return bool(getattr(self._runtime, self._dispatch_method)(now_mono))

    def configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self._runtime._configure_sample_transport(
            target_rpm=target_rpm,
            direct_max_speed_usteps_per_s=direct_max_speed_usteps_per_s,
            direct_acceleration_usteps_per_s2=direct_acceleration_usteps_per_s2,
        )

    def nominal_degrees_per_step(self) -> float | None:
        step = self._runtime._sample_transport_step_deg
        if step is not None:
            return float(step)
        fn = getattr(self._runtime._pulse_command, "nominal_degrees_per_step", None)
        if callable(fn):
            value = fn()
            return float(value) if isinstance(value, (int, float)) and value > 0 else None
        return None


__all__ = ["RingPurgePort", "RingSampleTransportPort"]
