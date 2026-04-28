from __future__ import annotations

import math

from rt.contracts.tracking import Track, TrackBatch
from rt.perception.track_policy import action_track


def wrap_rad(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def is_fresh_track(track: Track, batch_ts: float, *, track_stale_s: float) -> bool:
    last_seen_ts = float(track.last_seen_ts)
    if batch_ts <= 0.0 or last_seen_ts <= 0.0:
        return True
    return (batch_ts - last_seen_ts) <= track_stale_s


def fresh_ring_tracks(batch: TrackBatch | None, *, track_stale_s: float) -> list[Track]:
    if batch is None:
        return []
    batch_ts = float(batch.timestamp)
    return [
        track
        for track in batch.tracks
        if is_fresh_track(track, batch_ts, track_stale_s=track_stale_s)
    ]


def closest_actionable_within(
    tracks: list[Track],
    arc: float,
    *,
    min_hits: int,
) -> Track | None:
    candidates = [
        track
        for track in tracks
        if track.angle_rad is not None and action_track(track, min_hits=min_hits)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda track: abs(wrap_rad(track.angle_rad or 0.0)))
    head = candidates[0]
    if abs(wrap_rad(head.angle_rad or 0.0)) > arc:
        return None
    return head


def track_angle_deg(track: Track) -> float | None:
    if track.angle_rad is None:
        return None
    return math.degrees(float(track.angle_rad))


def track_diagnostics(track: Track) -> dict[str, object]:
    return {
        "track_id": track.track_id,
        "global_id": track.global_id,
        "piece_uuid": track.piece_uuid,
        "angle_deg": track_angle_deg(track),
        "score": float(track.score),
        "hit_count": int(track.hit_count),
        "confirmed_real": bool(track.confirmed_real),
    }
