"""In-memory ring buffer of completed track histories.

Each entry records the trajectory of a piece across however many cameras it
traversed. When a track dies on c_channel_2 + gets re-acquired on c_channel_3
via the handoff manager, the two per-camera recordings show up as separate
``TrackSegment`` entries under the same ``global_id``.

Storage is lossy by design — only the last ``MAX_ENTRIES`` completed tracks
are kept. Snapshots are base64-JPEG in memory to keep the API stateless
(no file serving, no cleanup on restart).
"""

from __future__ import annotations

import base64
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable

import cv2
import numpy as np


DEFAULT_MAX_ENTRIES = 300
DEFAULT_MAX_PATH_POINTS = 400
SNAPSHOT_JPEG_QUALITY = 88
COMPOSITE_THUMB_SIZE = 640


@dataclass
class SectorSnapshot:
    """A pie-slice snapshot of one wedge as the piece passed through it.

    Angular + radial bounds are derived dynamically from the piece's bbox
    (plus a small margin) so the wedge snugly wraps the actual detected
    object instead of consuming a fixed 30° slice. ``jpeg_b64`` is the
    frame cropped to the wedge's axis-aligned bounding box (not the wedge
    itself — the frontend applies an SVG clipPath). ``bbox_x/y`` give the
    crop's top-left in frame-pixel coordinates.

    ``r_inner`` / ``r_outer`` override the channel's default radii for
    this specific wedge — useful when the piece doesn't span the full
    annulus.
    """

    sector_index: int
    start_angle_deg: float
    end_angle_deg: float
    captured_ts: float
    bbox_x: int
    bbox_y: int
    width: int
    height: int
    jpeg_b64: str
    r_inner: float = 0.0
    r_outer: float = 0.0


@dataclass
class TrackSegment:
    """One camera's view of a piece's life."""

    source_role: str
    handoff_from: str | None
    first_seen_ts: float
    last_seen_ts: float
    snapshot_jpeg_b64: str
    snapshot_width: int
    snapshot_height: int
    path: list[tuple[float, float, float]] = field(default_factory=list)  # (ts, x, y)
    hit_count: int = 0
    # Channel geometry snapshot — needed by the frontend to render sector
    # wedges over the right polar region. In frame-pixel coordinates.
    channel_center_x: float | None = None
    channel_center_y: float | None = None
    channel_radius_inner: float | None = None
    channel_radius_outer: float | None = None
    sector_count: int = 0
    sector_snapshots: list[SectorSnapshot] = field(default_factory=list)
    # Backend-rendered mini composite of all sector wedges, cropped + resized
    # for sidebar thumbnails. Empty if no sector snapshots were captured.
    composite_jpeg_b64: str = ""
    composite_width: int = 0
    composite_height: int = 0

    def to_summary(self) -> dict:
        return {
            "source_role": self.source_role,
            "handoff_from": self.handoff_from,
            "first_seen_ts": self.first_seen_ts,
            "last_seen_ts": self.last_seen_ts,
            "duration_s": max(0.0, self.last_seen_ts - self.first_seen_ts),
            "hit_count": self.hit_count,
            "path_points": len(self.path),
            "snapshot_width": self.snapshot_width,
            "snapshot_height": self.snapshot_height,
            "sector_count": self.sector_count,
            "sector_snapshot_count": len(self.sector_snapshots),
            "composite_jpeg_b64": self.composite_jpeg_b64,
            "composite_width": self.composite_width,
            "composite_height": self.composite_height,
        }

    def to_detail(self) -> dict:
        return {
            **self.to_summary(),
            "snapshot_jpeg_b64": self.snapshot_jpeg_b64,
            "path": [list(point) for point in self.path],
            "channel_center_x": self.channel_center_x,
            "channel_center_y": self.channel_center_y,
            "channel_radius_inner": self.channel_radius_inner,
            "channel_radius_outer": self.channel_radius_outer,
            "sector_snapshots": [
                {
                    "sector_index": s.sector_index,
                    "start_angle_deg": s.start_angle_deg,
                    "end_angle_deg": s.end_angle_deg,
                    "captured_ts": s.captured_ts,
                    "bbox_x": s.bbox_x,
                    "bbox_y": s.bbox_y,
                    "width": s.width,
                    "height": s.height,
                    "jpeg_b64": s.jpeg_b64,
                    "r_inner": s.r_inner,
                    "r_outer": s.r_outer,
                }
                for s in self.sector_snapshots
            ],
        }


@dataclass
class TrackHistoryEntry:
    """Aggregates all segments belonging to a single global_id."""

    global_id: int
    created_at: float
    finished_at: float
    segments: list[TrackSegment] = field(default_factory=list)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(seg.source_role for seg in self.segments)

    @property
    def handoff_count(self) -> int:
        return sum(1 for seg in self.segments if seg.handoff_from is not None)

    @property
    def max_sector_snapshots(self) -> int:
        if not self.segments:
            return 0
        return max(len(seg.sector_snapshots) for seg in self.segments)

    def to_summary(self) -> dict:
        # Pick the segment with the most sector snapshots as the thumb source
        # — it's the richest view of the piece's trajectory.
        thumb = ""
        if self.segments:
            richest = max(self.segments, key=lambda s: len(s.sector_snapshots))
            thumb = richest.composite_jpeg_b64
        return {
            "global_id": self.global_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "duration_s": max(0.0, self.finished_at - self.created_at),
            "roles": list(self.roles),
            "handoff_count": self.handoff_count,
            "segment_count": len(self.segments),
            "total_hit_count": sum(seg.hit_count for seg in self.segments),
            "max_sector_snapshots": self.max_sector_snapshots,
            "composite_jpeg_b64": thumb,
        }

    def to_detail(self) -> dict:
        return {
            **self.to_summary(),
            "segments": [seg.to_detail() for seg in self.segments],
        }


def render_sector_composite(
    sector_snapshots: list[SectorSnapshot],
    channel_center_x: float,
    channel_center_y: float,
    channel_radius_inner: float,
    channel_radius_outer: float,
    frame_width: int,
    frame_height: int,
    *,
    target_size: int = COMPOSITE_THUMB_SIZE,
) -> tuple[str, int, int]:
    """Composite all sector wedges into one small JPEG for sidebar thumbs.

    Builds a full-frame canvas, stamps each decoded sector-JPEG at its
    ``(bbox_x, bbox_y)`` clipped to the wedge polygon via ``cv2.fillPoly``,
    then crops to the channel bounding square and resizes to ``target_size``.
    Returns ``("", 0, 0)`` if nothing usable was produced.
    """
    if not sector_snapshots or frame_width <= 0 or frame_height <= 0:
        return "", 0, 0
    if channel_radius_outer <= channel_radius_inner or channel_radius_outer <= 0:
        return "", 0, 0

    canvas = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)

    for snap in sector_snapshots:
        try:
            raw = base64.b64decode(snap.jpeg_b64)
        except (ValueError, TypeError):
            continue
        arr = np.frombuffer(raw, dtype=np.uint8)
        sector_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if sector_img is None:
            continue
        sh, sw = sector_img.shape[:2]
        x1 = int(snap.bbox_x)
        y1 = int(snap.bbox_y)
        x2 = min(frame_width, x1 + sw)
        y2 = min(frame_height, y1 + sh)
        if x2 <= x1 or y2 <= y1:
            continue
        sector_img = sector_img[: (y2 - y1), : (x2 - x1)]

        a0 = math.radians(snap.start_angle_deg)
        a1 = math.radians(snap.end_angle_deg)
        # Use the per-snapshot radii when the wedge is dynamically sized to
        # the piece — fall back to the channel radii for older entries.
        r_in = snap.r_inner if snap.r_inner > 0 else channel_radius_inner
        r_out = snap.r_outer if snap.r_outer > r_in else channel_radius_outer
        n = 16
        pts: list[list[int]] = []
        for i in range(n + 1):
            t = i / n
            a = a0 + (a1 - a0) * t
            pts.append([
                int(round(channel_center_x + r_out * math.cos(a))),
                int(round(channel_center_y + r_out * math.sin(a))),
            ])
        for i in range(n, -1, -1):
            t = i / n
            a = a0 + (a1 - a0) * t
            pts.append([
                int(round(channel_center_x + r_in * math.cos(a))),
                int(round(channel_center_y + r_in * math.sin(a))),
            ])
        mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
        cv2.fillPoly(mask, [np.array(pts, dtype=np.int32)], 255)
        sub_mask = mask[y1:y2, x1:x2]
        if sub_mask.size == 0:
            continue
        sub_canvas = canvas[y1:y2, x1:x2]
        # In-place blit where the mask is set.
        np.copyto(sub_canvas, sector_img, where=sub_mask[..., None] > 0)

    # Crop to a square around the channel outer radius (with small padding).
    pad = 6
    r = int(math.ceil(channel_radius_outer)) + pad
    cx_i = int(round(channel_center_x))
    cy_i = int(round(channel_center_y))
    x1 = max(0, cx_i - r)
    y1 = max(0, cy_i - r)
    x2 = min(frame_width, cx_i + r)
    y2 = min(frame_height, cy_i + r)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return "", 0, 0
    crop = canvas[y1:y2, x1:x2]

    # Downsize OR upsize — use INTER_LANCZOS4 to preserve edge detail on
    # small sector snapshots that need to span a ~640 px thumb.
    interp = cv2.INTER_AREA if crop.shape[0] > target_size else cv2.INTER_LANCZOS4
    thumb = cv2.resize(crop, (target_size, target_size), interpolation=interp)
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return "", 0, 0
    return base64.b64encode(buf.tobytes()).decode("ascii"), target_size, target_size


def render_snapshot_thumb(
    jpeg_b64: str,
    *,
    target_size: int = COMPOSITE_THUMB_SIZE,
) -> tuple[str, int, int]:
    """Downscale a base64 JPEG (usually the first-frame snapshot) into a
    square thumbnail. Used as a fallback when no sector composite exists.
    """
    if not jpeg_b64:
        return "", 0, 0
    try:
        raw = base64.b64decode(jpeg_b64)
    except (ValueError, TypeError):
        return "", 0, 0
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return "", 0, 0
    h, w = img.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    crop = img[y0 : y0 + side, x0 : x0 + side]
    interp = cv2.INTER_AREA if side > target_size else cv2.INTER_LANCZOS4
    thumb = cv2.resize(crop, (target_size, target_size), interpolation=interp)
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return "", 0, 0
    return base64.b64encode(buf.tobytes()).decode("ascii"), target_size, target_size


def encode_snapshot(frame_bgr: np.ndarray) -> tuple[str, int, int]:
    """Encode ``frame_bgr`` → base64 JPEG. Returns ``(b64_str, width, height)``."""
    h, w = frame_bgr.shape[:2]
    ok, buf = cv2.imencode(
        ".jpg",
        frame_bgr,
        [cv2.IMWRITE_JPEG_QUALITY, SNAPSHOT_JPEG_QUALITY],
    )
    if not ok:
        return "", int(w), int(h)
    return base64.b64encode(buf.tobytes()).decode("ascii"), int(w), int(h)


class PieceHistoryBuffer:
    """Thread-safe in-memory ring buffer keyed by ``global_id``.

    Live tracks can push additional segments into an existing entry (useful
    when a c_channel_2 → c_channel_3 handoff carries the same global_id
    across cameras). When the buffer overflows the oldest entry is dropped.
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_path_points: int = DEFAULT_MAX_PATH_POINTS,
    ) -> None:
        self._max_entries = int(max_entries)
        self._max_path_points = int(max_path_points)
        self._lock = threading.Lock()
        # OrderedDict → O(1) LRU-style trimming by insertion order.
        self._entries: "OrderedDict[int, TrackHistoryEntry]" = OrderedDict()

    def record_segment(self, segment: TrackSegment, global_id: int) -> None:
        with self._lock:
            # Trim path once so the stored segment respects the cap.
            if len(segment.path) > self._max_path_points:
                stride = max(1, len(segment.path) // self._max_path_points)
                segment.path = segment.path[::stride][: self._max_path_points]

            existing = self._entries.pop(global_id, None)
            if existing is None:
                existing = TrackHistoryEntry(
                    global_id=global_id,
                    created_at=segment.first_seen_ts,
                    finished_at=segment.last_seen_ts,
                    segments=[segment],
                )
            else:
                existing.segments.append(segment)
                existing.created_at = min(existing.created_at, segment.first_seen_ts)
                existing.finished_at = max(existing.finished_at, segment.last_seen_ts)
            # Re-insert at the end — keeps the most-recently-updated entry newest.
            self._entries[global_id] = existing
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def list_summaries(
        self,
        limit: int | None = None,
        *,
        min_sectors: int = 0,
    ) -> list[dict]:
        with self._lock:
            entries = list(self._entries.values())
        if min_sectors > 0:
            entries = [e for e in entries if e.max_sector_snapshots >= min_sectors]
        entries.sort(key=lambda e: e.finished_at, reverse=True)
        if limit is not None:
            entries = entries[:limit]
        return [entry.to_summary() for entry in entries]

    def get_detail(self, global_id: int) -> dict | None:
        with self._lock:
            entry = self._entries.get(global_id)
        if entry is None:
            return None
        return entry.to_detail()

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()
