"""Standalone `ZoneManager` for RuntimeC4.

Self-contained port of ``subsystems/classification_channel/zone_manager.py``
with no bridge imports. Models the classification carousel as a set of
angular exclusion zones — each piece occupies an arc around its center.
Used by C4 for intake admission (arc-clear check) and transport bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _normalize_deg(value: float) -> float:
    normalized = float(value) % 360.0
    if normalized < 0.0:
        normalized += 360.0
    return normalized


def _circular_diff_deg(a: float, b: float) -> float:
    return (_normalize_deg(a) - _normalize_deg(b) + 540.0) % 360.0 - 180.0


def _segments_for_arc(start_deg: float, end_deg: float) -> list[tuple[float, float]]:
    start = _normalize_deg(start_deg)
    end = _normalize_deg(end_deg)
    if start <= end:
        return [(start, end)]
    return [(0.0, end), (start, 360.0)]


def _arcs_overlap(
    start_a: float,
    end_a: float,
    start_b: float,
    end_b: float,
) -> bool:
    for seg_a in _segments_for_arc(start_a, end_a):
        for seg_b in _segments_for_arc(start_b, end_b):
            if seg_a[0] <= seg_b[1] and seg_b[0] <= seg_a[1]:
                return True
    return False


@dataclass(frozen=True, slots=True)
class TrackAngularExtent:
    """Observed angular extent of a single track on the carousel."""

    piece_uuid: str
    global_id: int | None
    center_deg: float
    half_width_deg: float
    last_seen_mono: float


@dataclass(slots=True)
class ExclusionZone:
    """Occupied angular zone around a piece on the carousel ring."""

    piece_uuid: str
    global_id: int | None
    center_deg: float
    half_width_deg: float
    guard_deg: float
    last_seen_mono: float
    stale: bool = False

    @property
    def start_deg(self) -> float:
        return self.center_deg - (self.half_width_deg + self.guard_deg)

    @property
    def end_deg(self) -> float:
        return self.center_deg + (self.half_width_deg + self.guard_deg)


class ZoneManager:
    """Tracks angular occupancy of the classification carousel ring."""

    def __init__(
        self,
        *,
        max_zones: int,
        intake_angle_deg: float = 0.0,
        guard_angle_deg: float = 30.0,
        default_half_width_deg: float = 20.0,
        stale_timeout_s: float = 1.5,
    ) -> None:
        if max_zones < 1:
            raise ValueError(f"max_zones must be >= 1, got {max_zones}")
        self._max_zones = int(max_zones)
        self._intake_angle_deg = float(intake_angle_deg)
        self._guard_deg = float(guard_angle_deg)
        self._default_half_width = float(default_half_width_deg)
        self._stale_timeout_s = float(stale_timeout_s)
        self._zones: dict[str, ExclusionZone] = {}

    # -- Queries -----------------------------------------------------

    @property
    def max_zones(self) -> int:
        return self._max_zones

    @property
    def intake_angle_deg(self) -> float:
        return self._intake_angle_deg

    @property
    def guard_angle_deg(self) -> float:
        return self._guard_deg

    def zone_count(self) -> int:
        return len(self._zones)

    def zones(self) -> tuple[ExclusionZone, ...]:
        return tuple(self._zones.values())

    def has_piece(self, piece_uuid: str) -> bool:
        return piece_uuid in self._zones

    def zone_for(self, piece_uuid: str) -> ExclusionZone | None:
        return self._zones.get(piece_uuid)

    # -- Intake ------------------------------------------------------

    def is_arc_clear(
        self,
        angle_deg: float | None = None,
        *,
        half_width_deg: float | None = None,
        ignore_piece_uuid: str | None = None,
    ) -> bool:
        """True iff the probe arc does not overlap any existing zone."""
        center = float(angle_deg) if angle_deg is not None else self._intake_angle_deg
        half = float(half_width_deg) if half_width_deg is not None else self._default_half_width
        start = center - (half + self._guard_deg)
        end = center + (half + self._guard_deg)
        for zone in self._zones.values():
            if zone.piece_uuid == ignore_piece_uuid:
                continue
            if _arcs_overlap(start, end, zone.start_deg, zone.end_deg):
                return False
        return True

    def add_zone(
        self,
        *,
        piece_uuid: str,
        angle_deg: float | None = None,
        half_width_deg: float | None = None,
        global_id: int | None = None,
        now_mono: float = 0.0,
    ) -> bool:
        """Register a new piece occupying a zone. False if no capacity."""
        if piece_uuid in self._zones:
            # Idempotent: refresh timestamp.
            self._zones[piece_uuid].last_seen_mono = float(now_mono)
            self._zones[piece_uuid].stale = False
            return True
        if len(self._zones) >= self._max_zones:
            return False
        center = float(angle_deg) if angle_deg is not None else self._intake_angle_deg
        half = float(half_width_deg) if half_width_deg is not None else self._default_half_width
        self._zones[piece_uuid] = ExclusionZone(
            piece_uuid=piece_uuid,
            global_id=global_id,
            center_deg=center,
            half_width_deg=half,
            guard_deg=self._guard_deg,
            last_seen_mono=float(now_mono),
        )
        return True

    def remove_zone(self, piece_uuid: str) -> None:
        self._zones.pop(piece_uuid, None)

    # -- Tracking updates --------------------------------------------

    def update_from_tracks(
        self,
        extents: list[TrackAngularExtent],
        *,
        now_mono: float,
    ) -> tuple[str, ...]:
        """Refresh existing zones from live track observations. Drops stale zones
        whose tracks disappeared more than ``stale_timeout_s`` ago. Returns the
        tuple of piece_uuids that were evicted on this call."""
        seen_uuids: set[str] = set()
        for extent in extents:
            if extent.piece_uuid not in self._zones:
                continue
            seen_uuids.add(extent.piece_uuid)
            zone = self._zones[extent.piece_uuid]
            zone.center_deg = extent.center_deg
            zone.half_width_deg = extent.half_width_deg
            zone.last_seen_mono = float(now_mono)
            zone.stale = False

        expired: list[str] = []
        for piece_uuid, zone in self._zones.items():
            if piece_uuid in seen_uuids:
                continue
            age = max(0.0, float(now_mono) - zone.last_seen_mono)
            if age > self._stale_timeout_s:
                expired.append(piece_uuid)
            else:
                zone.stale = True
        for piece_uuid in expired:
            self._zones.pop(piece_uuid, None)
        return tuple(expired)


__all__ = [
    "ExclusionZone",
    "TrackAngularExtent",
    "ZoneManager",
]
