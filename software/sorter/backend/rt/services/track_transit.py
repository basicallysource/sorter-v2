"""Tracklet transit registry.

Trackers are allowed to split a physical object into multiple short-lived
track IDs. This registry sits above tracker strategies and below the runtimes:
when a track leaves a useful region, the runtime can park a small transit
candidate; when a new stable detection appears, the downstream runtime can
claim the best candidate and keep the physical identity continuous.

Appearance gating
-----------------
When the primary tracker is appearance-aware (BoTSORT + ReID), re-acquisition
*within* a channel is handled inside the tracker and this registry is not
needed for that case. What still needs to happen across the C3→C4 boundary is
explicit hand-off between runtimes: the registry keeps candidates alive there
and uses the ReID embedding attached to each Track as an optional cosine-
similarity gate on ``claim()`` so visually distinct pieces cannot be wrongly
married to a parked candidate.

The gate is permissive by design: when either side lacks an embedding (e.g.
because the motion-only shadow tracker is in use) the registry falls back to
the pre-existing geometric score so we never regress.
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
    source_embedding: tuple[float, ...] | None = None


DEFAULT_APPEARANCE_SIMILARITY_THRESHOLD = 0.55
"""Cosine-similarity gate on ``claim`` — candidates below this are refused.

0.55 is a permissive starting point sized for cross-channel C3→C4 hand-off
where we want to catch gross mismatches (red slope claimed by a white police
piece) without rejecting same-piece transitions that might have drifted under
different lighting or pose. Tighten via env/config once we have calibration
data.
"""


class TrackTransitRegistry:
    """Small in-memory, best-effort transit cache."""

    def __init__(
        self,
        *,
        default_ttl_s: float = 4.0,
        appearance_threshold: float = DEFAULT_APPEARANCE_SIMILARITY_THRESHOLD,
    ) -> None:
        self._default_ttl_s = max(0.1, float(default_ttl_s))
        self._appearance_threshold = float(appearance_threshold)
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
        source_embedding: tuple[float, ...] | None = None,
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
            source_embedding=_normalize_embedding(source_embedding),
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
        exclude_same_global_id: bool = False,
        appearance_threshold: float | None = None,
        relation_angle_limits_deg: dict[str, float] | None = None,
    ) -> TransitCandidate | None:
        now = float(now_mono)
        target = str(target_runtime)
        relations = {str(r) for r in allowed_relations} if allowed_relations else None
        track_emb = _normalize_embedding(getattr(track, "appearance_embedding", None))
        threshold = (
            float(appearance_threshold)
            if appearance_threshold is not None
            else self._appearance_threshold
        )
        with self._lock:
            self._sweep_locked(now)
            candidates = [
                c
                for c in self._candidates.values()
                if c.target_runtime == target
                and c.expires_at_mono >= now
                and (
                    not exclude_same_global_id
                    or c.source_global_id != track.global_id
                )
                and (relations is None or c.relation in relations)
                and (
                    max_age_s is None
                    or (now - c.created_at_mono) <= max(0.0, float(max_age_s))
                )
                and _appearance_allows(c.source_embedding, track_emb, threshold)
                and _angle_allows(c, track, relation_angle_limits_deg)
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
        # Reward high appearance similarity so that if two candidates would
        # both pass the hard threshold, the closer match wins.
        track_emb = _normalize_embedding(getattr(track, "appearance_embedding", None))
        sim = _cosine_similarity(candidate.source_embedding, track_emb)
        if sim is not None:
            score -= float(sim)
        return score


def _normalize_embedding(
    value: tuple[float, ...] | list[float] | None,
) -> tuple[float, ...] | None:
    if value is None:
        return None
    try:
        vals = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if not vals or any(not math.isfinite(v) for v in vals):
        return None
    return tuple(vals)


def _cosine_similarity(
    a: tuple[float, ...] | None,
    b: tuple[float, ...] | None,
) -> float | None:
    if a is None or b is None or len(a) != len(b) or not a:
        return None
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return None
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _appearance_allows(
    candidate_embedding: tuple[float, ...] | None,
    track_embedding: tuple[float, ...] | None,
    threshold: float,
) -> bool:
    """Return True unless both sides have embeddings AND the similarity fails.

    Missing embeddings (e.g. motion-only tracker in use) never block a match —
    the registry preserves its prior behaviour when no appearance info flows.
    """

    sim = _cosine_similarity(candidate_embedding, track_embedding)
    if sim is None:
        return True
    return sim >= threshold


def _angle_allows(
    candidate: TransitCandidate,
    track: Track,
    relation_angle_limits_deg: dict[str, float] | None,
) -> bool:
    """Optional hard gate for fragile same-channel track-split stitching."""

    if not relation_angle_limits_deg:
        return True
    limit = relation_angle_limits_deg.get(candidate.relation)
    if limit is None:
        return True
    if candidate.source_angle_deg is None or track.angle_rad is None:
        return False
    angle_deg = math.degrees(float(track.angle_rad))
    delta = abs(
        ((angle_deg - float(candidate.source_angle_deg) + 180.0) % 360.0) - 180.0
    )
    return delta <= max(0.0, float(limit))


__all__ = [
    "DEFAULT_APPEARANCE_SIMILARITY_THRESHOLD",
    "TrackTransitRegistry",
    "TransitCandidate",
]
