"""C4 admission strategy — collapses the legacy C3->C4 gate into a plugin.

Ports ``subsystems/feeder/admission.classification_channel_admission_blocked``
into a single `AdmissionStrategy`. Marc's explicit goal: the hard-coded
``MAX_CLASSIFICATION_CHANNEL_DETECTION_CAP=3`` dissolves into this strategy so
the hard cap is just one check among several, tunable per config.
"""

from __future__ import annotations

from typing import Any

from rt.contracts.admission import AdmissionDecision
from rt.contracts.registry import register_admission


_UNSET = object()


@register_admission("c4")
class C4Admission:
    """Admission gate for the classification channel.

    Five sequential checks against ``runtime_state``:
      1. ``dropzone_clear`` (the upstream laydown window on C4 is free).
      2. ``arc_clear`` (intake arc free of existing zones).
      3. ``zone_count`` vs ``max_zones`` (how many pieces physically owned).
      4. ``transport_count`` vs ``max_zones`` (dossier bookkeeping backup).
      5. Optional ``raw_detection_count`` cap (disabled by default).
    """

    key = "c4"

    def __init__(
        self,
        *,
        max_zones: int = 1,
        max_raw_detections: int | None = None,
        intake_angle_deg: float = 0.0,
        guard_angle_deg: float = 30.0,
        require_dropzone_clear: bool = True,
    ) -> None:
        if max_zones < 1:
            raise ValueError(f"max_zones must be >= 1, got {max_zones}")
        self._max_zones = int(max_zones)
        if max_raw_detections is None or int(max_raw_detections) <= 0:
            self._max_raw_detections = None
        else:
            self._max_raw_detections = int(max_raw_detections)
        self._intake_angle_deg = float(intake_angle_deg)
        self._guard_angle_deg = float(guard_angle_deg)
        self._require_dropzone_clear = bool(require_dropzone_clear)

    @property
    def max_zones(self) -> int:
        return self._max_zones

    @property
    def max_raw_detections(self) -> int | None:
        return self._max_raw_detections

    @property
    def intake_angle_deg(self) -> float:
        return self._intake_angle_deg

    @property
    def guard_angle_deg(self) -> float:
        return self._guard_angle_deg

    @property
    def require_dropzone_clear(self) -> bool:
        return self._require_dropzone_clear

    def configure(
        self,
        *,
        max_zones: int | None = None,
        max_raw_detections: int | None | object = _UNSET,
        guard_angle_deg: float | None = None,
        require_dropzone_clear: bool | None = None,
    ) -> None:
        if max_zones is not None:
            if int(max_zones) < 1:
                raise ValueError(f"max_zones must be >= 1, got {max_zones}")
            self._max_zones = int(max_zones)
        if max_raw_detections is not _UNSET:
            if max_raw_detections is None or int(max_raw_detections) <= 0:
                self._max_raw_detections = None
            else:
                self._max_raw_detections = int(max_raw_detections)
        if guard_angle_deg is not None:
            self._guard_angle_deg = float(guard_angle_deg)
        if require_dropzone_clear is not None:
            self._require_dropzone_clear = bool(require_dropzone_clear)

    def can_admit(
        self,
        inbound_piece_hint: dict[str, Any],  # noqa: ARG002 — interface conformance
        runtime_state: dict[str, Any],
    ) -> AdmissionDecision:
        dropzone_clear = runtime_state.get("dropzone_clear", True)
        if self._require_dropzone_clear and dropzone_clear is False:
            return AdmissionDecision(allowed=False, reason="dropzone_clear")

        arc_clear = runtime_state.get("arc_clear", True)
        if arc_clear is False:
            return AdmissionDecision(allowed=False, reason="arc_clear")

        zone_count = int(runtime_state.get("zone_count", 0) or 0)
        if zone_count >= self._max_zones:
            return AdmissionDecision(allowed=False, reason="zone_cap")

        transport_count = int(runtime_state.get("transport_count", 0) or 0)
        if transport_count >= self._max_zones:
            return AdmissionDecision(allowed=False, reason="transport_cap")

        if self._max_raw_detections is not None:
            raw_count = int(runtime_state.get("raw_detection_count", 0) or 0)
            if raw_count >= self._max_raw_detections:
                return AdmissionDecision(allowed=False, reason="raw_cap")

        return AdmissionDecision(allowed=True, reason="ok")


__all__ = ["C4Admission"]
