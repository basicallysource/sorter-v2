from __future__ import annotations

import math
from typing import Any

from rt.contracts.purge import PurgeCounts


class C4LandingLeasePort:
    """C4's implementation of the downstream landing-lease gate."""

    key = "c4"

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def request_lease(
        self,
        *,
        predicted_arrival_in_s: float,
        min_spacing_deg: float,
        now_mono: float,
        track_global_id: int | None = None,
        handoff_quality: str | None = None,
        handoff_multi_risk: bool | None = None,
        handoff_context: dict | None = None,
    ) -> str | None:
        del handoff_quality, handoff_multi_risk, handoff_context
        bank = self._runtime._bank
        encoder = self._runtime._carousel_angle_rad
        intake_world = math.radians(self._runtime._zone_manager.intake_angle_deg)
        intake_tray = self._runtime._tray_frame_rad(intake_world, encoder)
        return bank.request_landing_lease(
            predicted_arrival_t=float(now_mono)
            + max(0.0, float(predicted_arrival_in_s)),
            predicted_landing_a=intake_tray,
            min_spacing_rad=math.radians(max(0.0, float(min_spacing_deg))),
            now_t=float(now_mono),
            requested_by=track_global_id,
        )

    def consume_lease(self, lease_id: str) -> None:
        self._runtime._bank.consume_landing_lease(lease_id)


class C4PurgePort:
    """PurgePort binding for RuntimeC4."""

    key = "c4"

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def arm(self) -> None:
        self._runtime.arm_startup_purge()

    def disarm(self) -> None:
        self._runtime._startup_purge_state.armed = False
        self._runtime._startup_purge_controller.exit()

    def counts(self) -> PurgeCounts:
        return PurgeCounts(
            piece_count=int(self._runtime._raw_detection_count),
            owned_count=len(self._runtime._pieces),
            pending_detections=0,
        )

    def drain_step(self, now_mono: float) -> bool:
        del now_mono
        return bool(self._runtime._startup_purge_state.armed)


class C4SampleTransportPort:
    key = "c4"

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def step(self, now_mono: float) -> bool:
        return self._runtime._dispatch_sample_transport_step(now_mono)

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
        return float(self._runtime._sample_transport_step_deg)


class C4SectorCarouselPort:
    key = "c4"

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def transport_move(self, degrees: float) -> bool:
        return self._runtime._transport_move(degrees)

    def hardware_busy(self) -> bool:
        return bool(self._runtime._hw.busy())


__all__ = [
    "C4LandingLeasePort",
    "C4PurgePort",
    "C4SampleTransportPort",
    "C4SectorCarouselPort",
]
