"""Stable physical-piece identities above short-lived tracker tracklets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from rt.contracts.tracking import Track, TrackBatch
from rt.pieces.identity import new_piece_uuid


DEFAULT_HOLDOVER_S = 1.0
DEFAULT_MATCH_DISTANCE_PX = 180.0
DEFAULT_APPEARANCE_MATCH_THRESHOLD = 0.50
_RETENTION_S = 8.0


@dataclass(slots=True)
class _StablePiece:
    piece_uuid: str
    first_seen_ts: float
    last_seen_ts: float
    last_track: Track
    track_keys: set[int]
    appearance_embedding: tuple[float, ...] | None = None


class TrackletStabilizer:
    """Merge tracker-local tracklets into stable physical piece UUIDs.

    The stabilizer intentionally does not replace the tracker. It only adds a
    piece layer above it: raw ``global_id`` values remain tracklet/debug data,
    while ``piece_uuid`` becomes the UI/database identity that survives brief
    tracker dropouts.
    """

    def __init__(
        self,
        *,
        holdover_s: float = DEFAULT_HOLDOVER_S,
        match_distance_px: float = DEFAULT_MATCH_DISTANCE_PX,
        appearance_threshold: float = DEFAULT_APPEARANCE_MATCH_THRESHOLD,
    ) -> None:
        self._holdover_s = max(0.1, float(holdover_s))
        self._match_distance_px = max(20.0, float(match_distance_px))
        self._appearance_threshold = float(appearance_threshold)
        self._pieces: dict[str, _StablePiece] = {}
        self._track_to_piece: dict[int, str] = {}

    def update(self, batch: TrackBatch) -> TrackBatch:
        now_ts = float(batch.timestamp)
        self._sweep(now_ts)

        assigned_pieces: set[str] = set()
        tracks: list[Track] = []
        for track in batch.tracks:
            piece = self._piece_for_track(track, now_ts, assigned_pieces)
            assigned_pieces.add(piece.piece_uuid)
            stable_track = self._merge_track(track, piece, now_ts=now_ts)
            tracks.append(stable_track)

        tracks.extend(self._holdover_tracks(now_ts, assigned_pieces))
        return TrackBatch(
            feed_id=batch.feed_id,
            frame_seq=batch.frame_seq,
            timestamp=batch.timestamp,
            tracks=tuple(tracks),
            lost_track_ids=tuple(batch.lost_track_ids),
        )

    def project(self, batch: TrackBatch) -> TrackBatch:
        tracks: list[Track] = []
        for track in batch.tracks:
            piece_uuid = self._lookup_piece_uuid(track)
            if piece_uuid is None:
                tracks.append(track)
                continue
            tracks.append(replace(track, piece_uuid=piece_uuid))
        return TrackBatch(
            feed_id=batch.feed_id,
            frame_seq=batch.frame_seq,
            timestamp=batch.timestamp,
            tracks=tuple(tracks),
            lost_track_ids=tuple(batch.lost_track_ids),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "piece_count": len(self._pieces),
            "tracklet_count": len(self._track_to_piece),
            "holdover_s": self._holdover_s,
            "match_distance_px": self._match_distance_px,
        }

    def _piece_for_track(
        self,
        track: Track,
        now_ts: float,
        assigned_pieces: set[str],
    ) -> _StablePiece:
        existing_uuid = self._lookup_piece_uuid(track)
        if existing_uuid is not None and existing_uuid not in assigned_pieces:
            piece = self._pieces.get(existing_uuid)
            if piece is not None:
                return piece

        matched = self._match_recent_piece(track, now_ts, assigned_pieces)
        if matched is not None:
            return matched

        piece_uuid = (
            track.piece_uuid
            if isinstance(track.piece_uuid, str) and track.piece_uuid.strip()
            else new_piece_uuid()
        )
        piece = _StablePiece(
            piece_uuid=piece_uuid,
            first_seen_ts=float(track.first_seen_ts),
            last_seen_ts=float(track.last_seen_ts),
            last_track=track,
            track_keys=set(),
            appearance_embedding=_normalize_embedding(track.appearance_embedding),
        )
        self._pieces[piece_uuid] = piece
        return piece

    def _merge_track(self, track: Track, piece: _StablePiece, *, now_ts: float) -> Track:
        key = _track_key(track)
        if key is not None:
            self._track_to_piece[key] = piece.piece_uuid
            piece.track_keys.add(key)
        embedding = _normalize_embedding(track.appearance_embedding)
        if embedding is None:
            embedding = piece.appearance_embedding
        else:
            piece.appearance_embedding = embedding
        stable_track = replace(
            track,
            piece_uuid=piece.piece_uuid,
            appearance_embedding=embedding,
        )
        piece.last_seen_ts = float(track.last_seen_ts or now_ts)
        piece.last_track = stable_track
        return stable_track

    def _match_recent_piece(
        self,
        track: Track,
        now_ts: float,
        assigned_pieces: set[str],
    ) -> _StablePiece | None:
        best: tuple[float, _StablePiece] | None = None
        for piece in self._pieces.values():
            if piece.piece_uuid in assigned_pieces:
                continue
            gap_s = max(0.0, now_ts - float(piece.last_seen_ts))
            if gap_s > self._holdover_s:
                continue
            distance = _track_distance_px(track, piece.last_track)
            if distance is None or distance > self._match_distance_px:
                continue
            sim = _cosine_similarity(
                _normalize_embedding(track.appearance_embedding),
                piece.appearance_embedding,
            )
            if sim is not None and sim < self._appearance_threshold:
                continue
            score = distance + (gap_s * 25.0)
            if sim is not None:
                score -= sim * 20.0
            if best is None or score < best[0]:
                best = (score, piece)
        return best[1] if best is not None else None

    def _holdover_tracks(
        self,
        now_ts: float,
        assigned_pieces: set[str],
    ) -> list[Track]:
        out: list[Track] = []
        for piece in self._pieces.values():
            if piece.piece_uuid in assigned_pieces:
                continue
            gap_s = max(0.0, now_ts - float(piece.last_seen_ts))
            if gap_s > self._holdover_s:
                continue
            # Keep the stable identity visible to overlays/debug consumers, but
            # mark it as a ghost so runtimes never act on a stale position.
            out.append(
                replace(
                    piece.last_track,
                    confirmed_real=False,
                    ghost=True,
                    appearance_embedding=piece.appearance_embedding,
                )
            )
        return out

    def _lookup_piece_uuid(self, track: Track) -> str | None:
        if isinstance(track.piece_uuid, str) and track.piece_uuid in self._pieces:
            return track.piece_uuid
        key = _track_key(track)
        if key is None:
            return None
        piece_uuid = self._track_to_piece.get(key)
        if piece_uuid in self._pieces:
            return piece_uuid
        return None

    def _sweep(self, now_ts: float) -> None:
        expired = {
            uuid
            for uuid, piece in self._pieces.items()
            if now_ts - float(piece.last_seen_ts) > _RETENTION_S
        }
        if not expired:
            return
        for uuid in expired:
            piece = self._pieces.pop(uuid, None)
            if piece is None:
                continue
            for key in piece.track_keys:
                self._track_to_piece.pop(key, None)


def _track_key(track: Track) -> int | None:
    value = track.global_id if track.global_id is not None else track.track_id
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _center(track: Track) -> tuple[float, float] | None:
    bbox = getattr(track, "bbox_xyxy", None)
    if not isinstance(bbox, tuple) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _track_distance_px(a: Track, b: Track) -> float | None:
    if (
        a.angle_rad is not None
        and b.angle_rad is not None
        and a.radius_px is not None
        and b.radius_px is not None
    ):
        radius = max(1.0, (float(a.radius_px) + float(b.radius_px)) / 2.0)
        arc = abs(_circular_diff(float(a.angle_rad), float(b.angle_rad))) * radius
        radial = abs(float(a.radius_px) - float(b.radius_px))
        return math.hypot(arc, radial)
    ca = _center(a)
    cb = _center(b)
    if ca is None or cb is None:
        return None
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def _circular_diff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def _normalize_embedding(
    value: tuple[float, ...] | list[float] | None,
) -> tuple[float, ...] | None:
    if value is None:
        return None
    try:
        vals = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not vals or any(not math.isfinite(v) for v in vals):
        return None
    return vals


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


__all__ = [
    "DEFAULT_HOLDOVER_S",
    "DEFAULT_MATCH_DISTANCE_PX",
    "TrackletStabilizer",
]
