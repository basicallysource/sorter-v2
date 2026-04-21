from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from defs.known_object import ClassificationStatus

if TYPE_CHECKING:
    from irl.config import (
        ClassificationChannelConfig,
        ClassificationChannelSizeClassConfig,
    )


def _normalize_deg(value: float) -> float:
    normalized = float(value) % 360.0
    if normalized < 0.0:
        normalized += 360.0
    return normalized


def _circular_diff_deg(a: float, b: float) -> float:
    diff = (_normalize_deg(a) - _normalize_deg(b) + 540.0) % 360.0 - 180.0
    return diff


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


@dataclass(frozen=True)
class TrackAngularExtent:
    global_id: int
    center_deg: float
    half_width_deg: float
    last_seen_ts: float
    hit_count: int
    first_seen_ts: float = 0.0


@dataclass
class ExclusionZone:
    piece_uuid: str
    track_global_id: int | None
    center_deg: float
    measured_half_width_deg: float
    size_class: str
    body_half_width_deg: float
    soft_guard_deg: float
    hard_guard_deg: float
    last_seen_mono: float
    stale: bool = False
    hard_collision: bool = False
    collision_piece_uuids: tuple[str, ...] = ()
    classification_status: ClassificationStatus = ClassificationStatus.pending

    @property
    def body_start_deg(self) -> float:
        return self.center_deg - self.body_half_width_deg

    @property
    def body_end_deg(self) -> float:
        return self.center_deg + self.body_half_width_deg

    @property
    def soft_start_deg(self) -> float:
        return self.center_deg - (self.body_half_width_deg + self.soft_guard_deg)

    @property
    def soft_end_deg(self) -> float:
        return self.center_deg + (self.body_half_width_deg + self.soft_guard_deg)

    @property
    def hard_start_deg(self) -> float:
        return self.center_deg - (self.body_half_width_deg + self.hard_guard_deg)

    @property
    def hard_end_deg(self) -> float:
        return self.center_deg + (self.body_half_width_deg + self.hard_guard_deg)

    def to_overlay_payload(self) -> dict[str, object]:
        return {
            "piece_uuid": self.piece_uuid,
            "track_global_id": self.track_global_id,
            "center_deg": _normalize_deg(self.center_deg),
            "size_class": self.size_class,
            "measured_half_width_deg": self.measured_half_width_deg,
            "body_half_width_deg": self.body_half_width_deg,
            "soft_guard_deg": self.soft_guard_deg,
            "hard_guard_deg": self.hard_guard_deg,
            "stale": self.stale,
            "hard_collision": self.hard_collision,
            "collision_piece_uuids": list(self.collision_piece_uuids),
            "classification_status": self.classification_status.value,
        }


@dataclass
class _SizeState:
    class_index: int
    pending_smaller_index: int | None = None
    pending_count: int = 0


class ZoneManager:
    def __init__(self, config: "ClassificationChannelConfig") -> None:
        self._config = config
        self._zones_by_piece_uuid: dict[str, ExclusionZone] = {}
        self._size_state_by_piece_uuid: dict[str, _SizeState] = {}

    def zone_count(self) -> int:
        return len(self._zones_by_piece_uuid)

    def zones(self) -> list[ExclusionZone]:
        return list(self._zones_by_piece_uuid.values())

    def zone_for_piece(self, piece_uuid: str) -> ExclusionZone | None:
        return self._zones_by_piece_uuid.get(piece_uuid)

    def remove_piece(self, piece_uuid: str) -> None:
        self._zones_by_piece_uuid.pop(piece_uuid, None)
        self._size_state_by_piece_uuid.pop(piece_uuid, None)

    def register_provisional_piece(
        self,
        *,
        piece_uuid: str,
        track_global_id: int | None,
        classification_status: ClassificationStatus,
        now_mono: float,
    ) -> ExclusionZone:
        size_cfg = self._size_class_config_for_name("M")
        zone = ExclusionZone(
            piece_uuid=piece_uuid,
            track_global_id=track_global_id,
            center_deg=self._config.intake_angle_deg,
            measured_half_width_deg=self._config.intake_body_half_width_deg,
            size_class=size_cfg.name,
            body_half_width_deg=size_cfg.body_half_width_deg,
            soft_guard_deg=size_cfg.soft_guard_deg,
            hard_guard_deg=size_cfg.hard_guard_deg,
            last_seen_mono=now_mono,
            stale=False,
            classification_status=classification_status,
        )
        self._zones_by_piece_uuid[piece_uuid] = zone
        self._size_state_by_piece_uuid[piece_uuid] = _SizeState(
            class_index=self._size_class_index(size_cfg.name)
        )
        self._recompute_collisions()
        return zone

    def update_from_tracks(
        self,
        *,
        track_extents: list[TrackAngularExtent],
        pieces_by_track_id: dict[int, tuple[str, ClassificationStatus]],
        now_mono: float,
    ) -> list[ExclusionZone]:
        seen_piece_uuids: set[str] = set()
        for extent in track_extents:
            piece_meta = pieces_by_track_id.get(int(extent.global_id))
            if piece_meta is None:
                continue
            piece_uuid, classification_status = piece_meta
            seen_piece_uuids.add(piece_uuid)
            size_cfg = self._pick_size_class(piece_uuid, extent.half_width_deg)
            self._zones_by_piece_uuid[piece_uuid] = ExclusionZone(
                piece_uuid=piece_uuid,
                track_global_id=int(extent.global_id),
                center_deg=extent.center_deg,
                measured_half_width_deg=extent.half_width_deg,
                size_class=size_cfg.name,
                body_half_width_deg=size_cfg.body_half_width_deg,
                soft_guard_deg=size_cfg.soft_guard_deg,
                hard_guard_deg=size_cfg.hard_guard_deg,
                last_seen_mono=now_mono,
                stale=False,
                classification_status=classification_status,
            )

        stale_timeout_s = max(0.1, float(self._config.stale_zone_timeout_s))
        expired_piece_uuids: list[str] = []
        for piece_uuid, zone in list(self._zones_by_piece_uuid.items()):
            if piece_uuid in seen_piece_uuids:
                continue
            age_s = max(0.0, now_mono - zone.last_seen_mono)
            if age_s > stale_timeout_s:
                expired_piece_uuids.append(piece_uuid)
                continue
            zone.stale = True
            self._zones_by_piece_uuid[piece_uuid] = zone

        for piece_uuid in expired_piece_uuids:
            self.remove_piece(piece_uuid)

        self._recompute_collisions()
        return self.zones()

    def is_arc_clear(
        self,
        *,
        center_deg: float,
        body_half_width_deg: float,
        hard_guard_deg: float,
        ignore_piece_uuid: str | None = None,
    ) -> bool:
        start = center_deg - (body_half_width_deg + hard_guard_deg)
        end = center_deg + (body_half_width_deg + hard_guard_deg)
        for zone in self._zones_by_piece_uuid.values():
            if zone.piece_uuid == ignore_piece_uuid:
                continue
            if _arcs_overlap(start, end, zone.hard_start_deg, zone.hard_end_deg):
                return False
        return True

    def pieces_in_window(self, *, center_deg: float, tolerance_deg: float) -> list[str]:
        window_start = center_deg - tolerance_deg
        window_end = center_deg + tolerance_deg
        piece_uuids: list[str] = []
        for zone in self._zones_by_piece_uuid.values():
            if _arcs_overlap(zone.body_start_deg, zone.body_end_deg, window_start, window_end):
                piece_uuids.append(zone.piece_uuid)
        return piece_uuids

    def pieces_centered_in_window(
        self,
        *,
        center_deg: float,
        tolerance_deg: float,
    ) -> list[str]:
        piece_uuids: list[str] = []
        for zone in self._zones_by_piece_uuid.values():
            if abs(_circular_diff_deg(zone.center_deg, center_deg)) <= tolerance_deg:
                piece_uuids.append(zone.piece_uuid)
        return piece_uuids

    def pieces_in_body_window(
        self,
        *,
        center_deg: float,
        tolerance_deg: float,
        ignore_piece_uuid: str | None = None,
    ) -> list[str]:
        window_start = center_deg - tolerance_deg
        window_end = center_deg + tolerance_deg
        piece_uuids: list[str] = []
        for zone in self._zones_by_piece_uuid.values():
            if zone.piece_uuid == ignore_piece_uuid:
                continue
            if _arcs_overlap(zone.body_start_deg, zone.body_end_deg, window_start, window_end):
                piece_uuids.append(zone.piece_uuid)
        return piece_uuids

    def pieces_in_body_window_with_offsets(
        self,
        *,
        center_deg: float,
        tolerance_deg: float,
        ignore_piece_uuid: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return interfering piece UUIDs alongside the signed angular offset
        of each zone's center from ``center_deg``.

        The offset is computed with :func:`_circular_diff_deg`; the sign is the
        same convention used everywhere else in this module, so callers can
        distinguish "behind" (negative offset, still approaching drop in
        carousel rotation direction) from "ahead" (positive offset, already
        past drop).
        """
        window_start = center_deg - tolerance_deg
        window_end = center_deg + tolerance_deg
        results: list[tuple[str, float]] = []
        for zone in self._zones_by_piece_uuid.values():
            if zone.piece_uuid == ignore_piece_uuid:
                continue
            if _arcs_overlap(zone.body_start_deg, zone.body_end_deg, window_start, window_end):
                results.append(
                    (zone.piece_uuid, _circular_diff_deg(zone.center_deg, center_deg))
                )
        return results

    def closest_piece_to_angle(
        self,
        *,
        center_deg: float,
        max_distance_deg: float,
    ) -> str | None:
        best_piece_uuid: str | None = None
        best_distance = float("inf")
        for zone in self._zones_by_piece_uuid.values():
            distance = abs(_circular_diff_deg(zone.center_deg, center_deg))
            if distance > max_distance_deg or distance >= best_distance:
                continue
            best_piece_uuid = zone.piece_uuid
            best_distance = distance
        return best_piece_uuid

    def hard_collisions(self) -> list[tuple[str, str]]:
        collisions: list[tuple[str, str]] = []
        for zone in self._zones_by_piece_uuid.values():
            for other_piece_uuid in zone.collision_piece_uuids:
                pair = tuple(sorted((zone.piece_uuid, other_piece_uuid)))
                if pair not in collisions:
                    collisions.append(pair)
        return collisions

    def overlay_payload(self) -> list[dict[str, object]]:
        return [zone.to_overlay_payload() for zone in self._zones_by_piece_uuid.values()]

    def _pick_size_class(
        self,
        piece_uuid: str,
        measured_half_width_deg: float,
    ) -> "ClassificationChannelSizeClassConfig":
        measured_index = self._size_class_index_for_measurement(measured_half_width_deg)
        current_state = self._size_state_by_piece_uuid.get(piece_uuid)
        if current_state is None:
            self._size_state_by_piece_uuid[piece_uuid] = _SizeState(
                class_index=measured_index
            )
            return self._config.size_classes[measured_index]

        if measured_index >= current_state.class_index:
            current_state.class_index = measured_index
            current_state.pending_smaller_index = None
            current_state.pending_count = 0
            return self._config.size_classes[current_state.class_index]

        if current_state.pending_smaller_index != measured_index:
            current_state.pending_smaller_index = measured_index
            current_state.pending_count = 1
            return self._config.size_classes[current_state.class_index]

        current_state.pending_count += 1
        if current_state.pending_count >= max(
            1, int(self._config.size_downgrade_confirmations)
        ):
            current_state.class_index = measured_index
            current_state.pending_smaller_index = None
            current_state.pending_count = 0

        return self._config.size_classes[current_state.class_index]

    def _size_class_index_for_measurement(self, measured_half_width_deg: float) -> int:
        for index, size_cfg in enumerate(self._config.size_classes):
            if measured_half_width_deg <= size_cfg.max_measured_half_width_deg:
                return index
        return len(self._config.size_classes) - 1

    def _size_class_index(self, name: str) -> int:
        for index, size_cfg in enumerate(self._config.size_classes):
            if size_cfg.name == name:
                return index
        return 0

    def _size_class_config_for_name(
        self,
        name: str,
    ) -> "ClassificationChannelSizeClassConfig":
        return self._config.size_classes[self._size_class_index(name)]

    def _recompute_collisions(self) -> None:
        piece_uuids = list(self._zones_by_piece_uuid.keys())
        collision_map: dict[str, list[str]] = {piece_uuid: [] for piece_uuid in piece_uuids}
        for index, piece_uuid in enumerate(piece_uuids):
            zone = self._zones_by_piece_uuid[piece_uuid]
            for other_piece_uuid in piece_uuids[index + 1 :]:
                other_zone = self._zones_by_piece_uuid[other_piece_uuid]
                if _arcs_overlap(
                    zone.hard_start_deg,
                    zone.hard_end_deg,
                    other_zone.hard_start_deg,
                    other_zone.hard_end_deg,
                ):
                    collision_map[piece_uuid].append(other_piece_uuid)
                    collision_map[other_piece_uuid].append(piece_uuid)

        for piece_uuid in piece_uuids:
            zone = self._zones_by_piece_uuid[piece_uuid]
            collision_piece_uuids = tuple(sorted(collision_map[piece_uuid]))
            zone.hard_collision = bool(collision_piece_uuids)
            zone.collision_piece_uuids = collision_piece_uuids
            self._zones_by_piece_uuid[piece_uuid] = zone


__all__ = [
    "ExclusionZone",
    "TrackAngularExtent",
    "ZoneManager",
]
