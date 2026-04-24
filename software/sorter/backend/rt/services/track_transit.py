"""Tracklet transit registry.

Trackers are allowed to split a physical object into multiple short-lived
track IDs. This registry sits above tracker strategies and below the runtimes:
when a track leaves a useful region, the runtime can park a small transit
candidate; when a new stable detection appears, the downstream runtime can
claim the best candidate and keep the physical identity continuous.
"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from rt.contracts.tracking import Track


@dataclass(frozen=True, slots=True)
class TransitCandidate:
    transit_id: str
    source_runtime: str
    source_feed: str
    source_global_id: int | None
    target_runtime: str
    created_at_mono: float
    expires_at_mono: float
    piece_uuid: str | None = None
    source_angle_deg: float | None = None
    source_radius_px: float | None = None
    relation: str = "track_split"
    payload: dict[str, Any] = field(default_factory=dict)


class TrackTransitRegistry:
    """Small in-memory, best-effort transit cache."""

    def __init__(self, *, default_ttl_s: float = 4.0) -> None:
        self._default_ttl_s = max(0.1, float(default_ttl_s))
        self._lock = threading.Lock()
        self._candidates: dict[str, TransitCandidate] = {}

    def begin(
        self,
        *,
        source_runtime: str,
        source_feed: str,
        source_global_id: int | None,
        target_runtime: str,
        now_mono: float,
        ttl_s: float | None = None,
        piece_uuid: str | None = None,
        source_angle_deg: float | None = None,
        source_radius_px: float | None = None,
        relation: str = "track_split",
        payload: dict[str, Any] | None = None,
    ) -> TransitCandidate:
        ttl = self._default_ttl_s if ttl_s is None else max(0.1, float(ttl_s))
        candidate = TransitCandidate(
            transit_id=uuid.uuid4().hex[:12],
            source_runtime=str(source_runtime),
            source_feed=str(source_feed),
            source_global_id=(
                int(source_global_id) if isinstance(source_global_id, int) else None
            ),
            target_runtime=str(target_runtime),
            created_at_mono=float(now_mono),
            expires_at_mono=float(now_mono) + ttl,
            piece_uuid=piece_uuid if isinstance(piece_uuid, str) and piece_uuid else None,
            source_angle_deg=(
                float(source_angle_deg)
                if isinstance(source_angle_deg, (int, float)) and math.isfinite(source_angle_deg)
                else None
            ),
            source_radius_px=(
                float(source_radius_px)
                if isinstance(source_radius_px, (int, float)) and math.isfinite(source_radius_px)
                else None
            ),
            relation=str(relation or "track_split"),
            payload=dict(payload or {}),
        )
        with self._lock:
            self._sweep_locked(float(now_mono))
            self._candidates[candidate.transit_id] = candidate
        return candidate

    def claim(
        self,
        *,
        target_runtime: str,
        track: Track,
        now_mono: float,
        max_age_s: float | None = None,
        allowed_relations: tuple[str, ...] | set[str] | None = None,
    ) -> TransitCandidate | None:
        now = float(now_mono)
        target = str(target_runtime)
        relations = {str(r) for r in allowed_relations} if allowed_relations else None
        with self._lock:
            self._sweep_locked(now)
            candidates = [
                c
                for c in self._candidates.values()
                if c.target_runtime == target
                and c.expires_at_mono >= now
                and c.source_global_id != track.global_id
                and (relations is None or c.relation in relations)
                and (
                    max_age_s is None
                    or (now - c.created_at_mono) <= max(0.0, float(max_age_s))
                )
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda c: self._score(c, track, now))
            chosen = candidates[0]
            self._candidates.pop(chosen.transit_id, None)
            return chosen

    def snapshot(self, now_mono: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if now_mono is not None:
                self._sweep_locked(float(now_mono))
            return [
                {
                    "transit_id": c.transit_id,
                    "source_runtime": c.source_runtime,
                    "source_feed": c.source_feed,
                    "source_global_id": c.source_global_id,
                    "target_runtime": c.target_runtime,
                    "piece_uuid": c.piece_uuid,
                    "relation": c.relation,
                    "created_at_mono": c.created_at_mono,
                    "expires_at_mono": c.expires_at_mono,
                }
                for c in sorted(self._candidates.values(), key=lambda c: c.created_at_mono)
            ]

    def _sweep_locked(self, now_mono: float) -> None:
        self._candidates = {
            key: value
            for key, value in self._candidates.items()
            if value.expires_at_mono >= now_mono
        }

    def _score(self, candidate: TransitCandidate, track: Track, now_mono: float) -> float:
        age = max(0.0, float(now_mono) - candidate.created_at_mono)
        score = age
        if candidate.piece_uuid:
            score -= 1.0
        if candidate.source_angle_deg is not None and track.angle_rad is not None:
            angle_deg = math.degrees(float(track.angle_rad))
            delta = abs(((angle_deg - candidate.source_angle_deg + 180.0) % 360.0) - 180.0)
            score += delta / 180.0
        return score


__all__ = ["TrackTransitRegistry", "TransitCandidate"]
