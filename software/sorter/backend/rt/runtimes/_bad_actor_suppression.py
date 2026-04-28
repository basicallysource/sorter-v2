"""Small local suppressor for physically stuck round parts.

This is intentionally not a general ghost tracker. It only quarantines stable
tracks that sit in a watched arc for several seconds with no meaningful angular
motion, so a rolling part stuck in a drop-zone corner does not freeze upstream
flow forever. If it moves again, it is immediately treated as normal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from rt.contracts.tracking import Track


@dataclass(slots=True)
class _WatchedTrack:
    first_ts: float
    first_angle_rad: float
    last_ts: float
    last_angle_rad: float
    ignored: bool = False
    ignored_since: float | None = None
    ignored_angle_rad: float | None = None


class StationaryBadActorSuppressor:
    """Quarantine near-stationary tracks inside a specific angular arc."""

    def __init__(
        self,
        *,
        name: str,
        stationary_after_s: float = 4.0,
        stationary_span_deg: float = 6.0,
        release_move_deg: float = 18.0,
        stale_after_s: float = 2.0,
    ) -> None:
        self.name = str(name)
        self.stationary_after_s = max(0.1, float(stationary_after_s))
        self.stationary_span_rad = math.radians(max(0.1, float(stationary_span_deg)))
        self.release_move_rad = math.radians(max(0.1, float(release_move_deg)))
        self.stale_after_s = max(0.1, float(stale_after_s))
        self._tracks: dict[int, _WatchedTrack] = {}

    def update(
        self,
        tracks: Iterable[Track],
        *,
        now_mono: float,
        arc_center_rad: float,
        arc_half_width_rad: float,
    ) -> set[int]:
        live_keys: set[int] = set()
        ignored: set[int] = set()
        center = float(arc_center_rad)
        half_width = max(0.0, float(arc_half_width_rad))
        now = float(now_mono)

        for track in tracks:
            key = track_key(track)
            if key is None or track.angle_rad is None:
                continue
            angle = float(track.angle_rad)
            live_keys.add(key)
            in_arc = abs(_wrap_rad(angle - center)) <= half_width
            state = self._tracks.get(key)
            if state is None:
                state = _WatchedTrack(
                    first_ts=now,
                    first_angle_rad=angle,
                    last_ts=now,
                    last_angle_rad=angle,
                )
                self._tracks[key] = state

            if state.ignored:
                ignored_angle = state.ignored_angle_rad
                moved = (
                    ignored_angle is not None
                    and abs(_wrap_rad(angle - ignored_angle)) >= self.release_move_rad
                )
                if moved or not in_arc:
                    state.ignored = False
                    state.ignored_since = None
                    state.ignored_angle_rad = None
                    state.first_ts = now
                    state.first_angle_rad = angle
                else:
                    ignored.add(key)
                    state.last_ts = now
                    state.last_angle_rad = angle
                    continue

            if not in_arc:
                state.first_ts = now
                state.first_angle_rad = angle
                state.last_ts = now
                state.last_angle_rad = angle
                continue

            span = abs(_wrap_rad(angle - state.first_angle_rad))
            if span > self.stationary_span_rad:
                state.first_ts = now
                state.first_angle_rad = angle
            elif (now - state.first_ts) >= self.stationary_after_s:
                state.ignored = True
                state.ignored_since = now
                state.ignored_angle_rad = angle
                ignored.add(key)

            state.last_ts = now
            state.last_angle_rad = angle

        stale_before = now - self.stale_after_s
        for key, state in list(self._tracks.items()):
            if key not in live_keys and state.last_ts < stale_before:
                self._tracks.pop(key, None)

        return ignored

    def ignored_keys(self) -> set[int]:
        return {key for key, state in self._tracks.items() if state.ignored}

    def reset(self) -> None:
        self._tracks.clear()

    def snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        now = float(now_mono) if now_mono is not None else None
        ignored = []
        for key, state in self._tracks.items():
            if not state.ignored:
                continue
            ignored.append(
                {
                    "key": int(key),
                    "ignored_for_s": (
                        max(0.0, now - float(state.ignored_since))
                        if now is not None and state.ignored_since is not None
                        else None
                    ),
                    "angle_deg": math.degrees(float(state.last_angle_rad)),
                }
            )
        ignored.sort(key=lambda item: item["key"])
        return {
            "name": self.name,
            "ignored_count": len(ignored),
            "ignored": ignored[:8],
            "stationary_after_s": self.stationary_after_s,
            "stationary_span_deg": math.degrees(self.stationary_span_rad),
            "release_move_deg": math.degrees(self.release_move_rad),
        }


def track_key(track: Track) -> int | None:
    raw = track.global_id if track.global_id is not None else track.track_id
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _wrap_rad(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


__all__ = ["StationaryBadActorSuppressor", "track_key"]
