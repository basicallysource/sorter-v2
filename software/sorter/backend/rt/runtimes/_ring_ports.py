from __future__ import annotations

from typing import Any

from rt.contracts.purge import PurgeCounts
from rt.hardware.motion_profiles import PROFILE_CONTINUOUS

from ._move_events import publish_move_completed


RING_SAMPLE_TRANSPORT_TARGET_INTERVAL_S = 0.75
RING_SAMPLE_TRANSPORT_MIN_STEP_DEG = 15.0
RING_SAMPLE_TRANSPORT_MAX_STEP_DEG = 90.0


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
        mode: Any,
        pulse_method: str,
        include_mode_in_event: bool = False,
        mark_transport_attempt: bool = False,
    ) -> None:
        self._runtime = runtime
        self.key = key
        self._mode = mode
        self._pulse_method = pulse_method
        self._include_mode_in_event = bool(include_mode_in_event)
        self._mark_transport_attempt = bool(mark_transport_attempt)

    def step(self, now_mono: float) -> bool:
        runtime = self._runtime
        if runtime._hw.busy() or runtime._hw.pending() > 0:
            runtime._set_state("sample_transport", blocked_reason="hw_busy")
            return False

        mode = self._mode
        timing = runtime._ejection.timing_for(
            {"sample_transport": True, "mode": mode.value}
        )

        def _run_pulse() -> None:
            ok = False
            try:
                if (
                    runtime._sample_transport_command is not None
                    and runtime._sample_transport_step_deg
                ):
                    ok = bool(
                        runtime._sample_transport_command(
                            runtime._sample_transport_step_deg,
                            runtime._sample_transport_max_speed,
                            runtime._sample_transport_acceleration,
                        )
                    )
                else:
                    ok = bool(
                        getattr(runtime, self._pulse_method)(
                            mode,
                            timing.pulse_ms,
                            PROFILE_CONTINUOUS,
                        )
                    )
            except Exception:
                runtime._logger.exception(
                    "Runtime%s: sample transport pulse raised",
                    self.key.upper(),
                )
            finally:
                extra: dict[str, Any] = {"sample_transport": True}
                if self._include_mode_in_event:
                    extra["mode"] = mode.value
                publish_move_completed(
                    runtime._bus,
                    runtime._logger,
                    runtime_id=runtime.runtime_id,
                    feed_id=runtime.feed_id,
                    source=f"{self.key}_sample_transport",
                    ok=bool(ok),
                    duration_ms=timing.pulse_ms,
                    extra=extra,
                )

        runtime._next_pulse_at = now_mono + runtime._pulse_cooldown_s
        enqueued = runtime._hw.enqueue(_run_pulse, label=f"{self.key}_sample_transport")
        if not enqueued:
            runtime._set_state("sample_transport", blocked_reason="hw_queue_full")
            return False

        duration_s = timing.pulse_ms / 1000.0
        if self._mark_transport_attempt:
            runtime._mark_transport_attempt(now_mono, duration_s=duration_s)
        runtime._publish_rotation_window(duration_s, now_mono)
        runtime._set_state("sample_transport")
        return True

    def configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self._runtime._sample_transport_max_speed = direct_max_speed_usteps_per_s
        self._runtime._sample_transport_acceleration = (
            direct_acceleration_usteps_per_s2
        )
        if target_rpm is None:
            self._runtime._sample_transport_step_deg = None
            return

        target_degrees_per_second = max(0.0, float(target_rpm)) * 6.0
        step = target_degrees_per_second * RING_SAMPLE_TRANSPORT_TARGET_INTERVAL_S
        self._runtime._sample_transport_step_deg = max(
            RING_SAMPLE_TRANSPORT_MIN_STEP_DEG,
            min(RING_SAMPLE_TRANSPORT_MAX_STEP_DEG, step),
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
