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
import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


# ``0`` disables trimming — we keep every completed track until the
# process exits. Set a positive integer to cap the ring buffer again.
DEFAULT_MAX_ENTRIES = 0
DEFAULT_MAX_PATH_POINTS = 400
SNAPSHOT_JPEG_QUALITY = 88
COMPOSITE_THUMB_SIZE = 640

BURST_JPEG_QUALITY = 80
BURST_MAX_EDGE_PX = 640


@dataclass
class DropZoneBurstFrame:
    """One YOLO-detected crop from the ±2s burst captured around first C4 entry."""

    frame_index: int
    timestamp: float
    phase: str  # "pre" | "post"
    detected: bool
    jpeg_b64: str
    crop_jpeg_b64: str
    bbox: tuple[int, int, int, int] | None
    score: float | None


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
    # Tight crop around just the piece bbox (+small margin) — used for
    # Recognize/classification. Separate from ``jpeg_b64`` so the pie-chart
    # composite keeps the full wedge context.
    piece_jpeg_b64: str = ""
    piece_bbox_x: int = 0
    piece_bbox_y: int = 0
    piece_width: int = 0
    piece_height: int = 0


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
    # Sharpest piece crop across all sector snapshots — used in the list
    # overview as a third thumbnail between the composite and the
    # Brickognize reference. Empty if no piece crops were captured.
    best_piece_jpeg_b64: str = ""
    # Auto-recognize result filled asynchronously once the segment is
    # archived. ``None`` means no attempt was made yet; a dict carries
    # ``status`` (``pending``/``ok``/``insufficient_consistency``/``error``),
    # the chosen best_item + best_color, and image_count actually sent.
    auto_recognition: "dict | None" = None

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
            "best_piece_jpeg_b64": self.best_piece_jpeg_b64,
            "auto_recognition": self.auto_recognition,
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
                    "piece_jpeg_b64": s.piece_jpeg_b64,
                    "piece_bbox_x": s.piece_bbox_x,
                    "piece_bbox_y": s.piece_bbox_y,
                    "piece_width": s.piece_width,
                    "piece_height": s.piece_height,
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
    drop_zone_burst: list[DropZoneBurstFrame] = field(default_factory=list)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(seg.source_role for seg in self.segments)

    @property
    def handoff_count(self) -> int:
        return sum(1 for seg in self.segments if seg.handoff_from is not None)

    @property
    def touches_classification_channel(self) -> bool:
        return any(seg.source_role == "carousel" for seg in self.segments)

    @property
    def max_sector_snapshots(self) -> int:
        if not self.segments:
            return 0
        return max(len(seg.sector_snapshots) for seg in self.segments)

    def to_summary(self) -> dict:
        # Pick the segment with the most sector snapshots as the thumb source
        # — it's the richest view of the piece's trajectory.
        thumb = ""
        best_piece = ""
        top_pieces: list[str] = []
        auto_recognition = None
        if self.segments:
            richest = max(self.segments, key=lambda s: len(s.sector_snapshots))
            thumb = richest.composite_jpeg_b64
            best_piece = richest.best_piece_jpeg_b64
            top_pieces = pick_top_piece_jpegs_across_segments(self.segments, limit=8)
            # Surface any segment's auto-recognition result (there's usually
            # one per track; prefer the segment with the actual classifier
            # response over a "pending" placeholder).
            for seg in self.segments:
                if seg.auto_recognition is not None:
                    auto_recognition = seg.auto_recognition
                    if auto_recognition.get("status") == "ok":
                        break
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
            "best_piece_jpeg_b64": best_piece,
            "top_piece_jpegs": top_pieces,
            "auto_recognition": auto_recognition,
        }

    def to_detail(self) -> dict:
        return {
            **self.to_summary(),
            "segments": [seg.to_detail() for seg in self.segments],
            "drop_zone_burst": [
                {
                    "frame_index": f.frame_index,
                    "timestamp": f.timestamp,
                    "phase": f.phase,
                    "detected": f.detected,
                    "jpeg_b64": f.jpeg_b64,
                    "crop_jpeg_b64": f.crop_jpeg_b64,
                    "bbox": list(f.bbox) if f.bbox is not None else None,
                    "score": f.score,
                }
                for f in self.drop_zone_burst
            ],
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
    path: list[tuple[float, float, float]] | None = None,
    handoff: bool = False,
) -> tuple[str, int, int]:
    """Composite all sector wedges into one small JPEG for sidebar thumbs.

    Builds a full-frame canvas, stamps each decoded sector-JPEG at its
    ``(bbox_x, bbox_y)`` clipped to the wedge polygon via ``cv2.fillPoly``,
    draws the trajectory polyline + capture-point circles on top, then
    crops to the channel bounding square and resizes to ``target_size``.
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

    # Trajectory polyline + capture-point circles — match the SVG modal
    # so the thumbnail tells the same story at a glance.
    if path and len(path) > 1:
        poly_pts = np.array(
            [[int(round(x)), int(round(y))] for _ts, x, y in path],
            dtype=np.int32,
        ).reshape(-1, 1, 2)
        # BGR: magenta for handoff tracks, green otherwise.
        poly_color = (220, 80, 220) if handoff else (0, 220, 0)
        cv2.polylines(canvas, [poly_pts], False, poly_color, thickness=3, lineType=cv2.LINE_AA)

    if sector_snapshots and path:
        for snap in sector_snapshots:
            # Find nearest path sample by capture timestamp.
            nearest = min(path, key=lambda p: abs(p[0] - snap.captured_ts))
            cv2.circle(
                canvas,
                (int(round(nearest[1])), int(round(nearest[2]))),
                radius=26,
                color=(0, 220, 255),  # yellow in BGR
                thickness=3,
                lineType=cv2.LINE_AA,
            )

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


def _score_piece_crop_sharpness(b64: str) -> float:
    """Laplacian-variance sharpness of a base64 piece crop. ``-1.0`` on
    decode failure so callers can filter with a positive threshold.
    """
    if not b64:
        return -1.0
    try:
        raw = base64.b64decode(b64)
    except (ValueError, TypeError):
        return -1.0
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        return -1.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def pick_sharpest_piece_jpeg(sector_snapshots: list) -> str:
    """Scan all sector snapshots, pick the piece-crop JPEG with the
    highest Laplacian variance (sharpness proxy). Used for the list-view
    "best crop" thumbnail. Returns empty string when nothing usable is
    available.
    """
    best_score = -1.0
    best_b64 = ""
    for snap in sector_snapshots:
        b64 = getattr(snap, "piece_jpeg_b64", "") or ""
        score = _score_piece_crop_sharpness(b64)
        if score > best_score:
            best_score = score
            best_b64 = b64
    return best_b64


def pick_top_piece_jpegs(sector_snapshots: list, limit: int = 8) -> list[str]:
    """Top-N sharpest piece crops across all sector snapshots.

    Used for the compact-view 3×3 "recognized + surrounding crops"
    layout — we ship the strongest ``limit`` crops so the UI can render
    them without a separate detail fetch per card.
    """
    scored: list[tuple[float, str]] = []
    for snap in sector_snapshots:
        b64 = getattr(snap, "piece_jpeg_b64", "") or ""
        if not b64:
            continue
        score = _score_piece_crop_sharpness(b64)
        if score < 0:
            continue
        scored.append((score, b64))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [b64 for _s, b64 in scored[: max(0, int(limit))]]


def pick_top_piece_jpegs_across_segments(
    segments: list[TrackSegment],
    *,
    limit: int = 8,
    per_segment_quota: int = 2,
) -> list[str]:
    """Top-N piece crops across the full handoff chain.

    Reserve a small quota per segment first so summary cards expose both the
    upstream c_channel_3 view and the downstream classification-channel view
    after a handoff. Remaining slots are filled globally by sharpness.
    """
    ranked_by_segment: list[list[tuple[float, str]]] = []
    for segment in sorted(segments, key=lambda seg: float(seg.first_seen_ts)):
        ranked: list[tuple[float, str]] = []
        for snap in segment.sector_snapshots:
            b64 = getattr(snap, "piece_jpeg_b64", "") or ""
            if not b64:
                continue
            score = _score_piece_crop_sharpness(b64)
            if score < 0:
                continue
            ranked.append((score, b64))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked:
            ranked_by_segment.append(ranked)

    if not ranked_by_segment:
        return []

    selected: list[str] = []
    seen: set[str] = set()
    quota = max(0, int(per_segment_quota))
    max_items = max(0, int(limit))

    for ranked in ranked_by_segment:
        for _score, b64 in ranked[:quota]:
            if b64 in seen:
                continue
            selected.append(b64)
            seen.add(b64)
            if len(selected) >= max_items:
                return selected[:max_items]

    all_ranked = [item for ranked in ranked_by_segment for item in ranked]
    all_ranked.sort(key=lambda item: item[0], reverse=True)
    for _score, b64 in all_ranked:
        if b64 in seen:
            continue
        selected.append(b64)
        seen.add(b64)
        if len(selected) >= max_items:
            break

    return selected[:max_items]


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


def _entry_from_dict(raw: dict) -> "TrackHistoryEntry | None":
    """Rehydrate a persisted ``to_detail()`` dict back into domain dataclasses."""
    try:
        global_id = int(raw.get("global_id"))
    except (TypeError, ValueError):
        return None
    segments_raw = raw.get("segments") or []
    segments: list[TrackSegment] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            continue
        sector_snaps = []
        for s in seg.get("sector_snapshots") or []:
            if not isinstance(s, dict):
                continue
            try:
                sector_snaps.append(
                    SectorSnapshot(
                        sector_index=int(s.get("sector_index", 0)),
                        start_angle_deg=float(s.get("start_angle_deg", 0.0)),
                        end_angle_deg=float(s.get("end_angle_deg", 0.0)),
                        captured_ts=float(s.get("captured_ts", 0.0)),
                        bbox_x=int(s.get("bbox_x", 0)),
                        bbox_y=int(s.get("bbox_y", 0)),
                        width=int(s.get("width", 0)),
                        height=int(s.get("height", 0)),
                        jpeg_b64=str(s.get("jpeg_b64", "")),
                        r_inner=float(s.get("r_inner", 0.0)),
                        r_outer=float(s.get("r_outer", 0.0)),
                        piece_jpeg_b64=str(s.get("piece_jpeg_b64", "")),
                        piece_bbox_x=int(s.get("piece_bbox_x", 0)),
                        piece_bbox_y=int(s.get("piece_bbox_y", 0)),
                        piece_width=int(s.get("piece_width", 0)),
                        piece_height=int(s.get("piece_height", 0)),
                    )
                )
            except Exception:
                continue
        path_raw = seg.get("path") or []
        path: list[tuple[float, float, float]] = []
        for p in path_raw:
            if not isinstance(p, (list, tuple)) or len(p) < 3:
                continue
            try:
                path.append((float(p[0]), float(p[1]), float(p[2])))
            except Exception:
                continue
        try:
            segments.append(
                TrackSegment(
                    source_role=str(seg.get("source_role", "")),
                    handoff_from=seg.get("handoff_from"),
                    first_seen_ts=float(seg.get("first_seen_ts", 0.0)),
                    last_seen_ts=float(seg.get("last_seen_ts", 0.0)),
                    snapshot_jpeg_b64=str(seg.get("snapshot_jpeg_b64", "")),
                    snapshot_width=int(seg.get("snapshot_width", 0)),
                    snapshot_height=int(seg.get("snapshot_height", 0)),
                    path=path,
                    hit_count=int(seg.get("hit_count", 0)),
                    channel_center_x=seg.get("channel_center_x"),
                    channel_center_y=seg.get("channel_center_y"),
                    channel_radius_inner=seg.get("channel_radius_inner"),
                    channel_radius_outer=seg.get("channel_radius_outer"),
                    sector_count=int(seg.get("sector_count", 0)),
                    sector_snapshots=sector_snaps,
                    composite_jpeg_b64=str(seg.get("composite_jpeg_b64", "")),
                    composite_width=int(seg.get("composite_width", 0)),
                    composite_height=int(seg.get("composite_height", 0)),
                    best_piece_jpeg_b64=str(seg.get("best_piece_jpeg_b64", "")),
                    auto_recognition=seg.get("auto_recognition"),
                )
            )
        except Exception:
            continue
    if not segments:
        return None
    burst_frames: list[DropZoneBurstFrame] = []
    for bf in raw.get("drop_zone_burst") or []:
        if not isinstance(bf, dict):
            continue
        try:
            raw_bbox = bf.get("bbox")
            bbox: tuple[int, int, int, int] | None = None
            if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                bbox = (int(raw_bbox[0]), int(raw_bbox[1]), int(raw_bbox[2]), int(raw_bbox[3]))
            burst_frames.append(
                DropZoneBurstFrame(
                    frame_index=int(bf.get("frame_index", 0)),
                    timestamp=float(bf.get("timestamp", 0.0)),
                    phase=str(bf.get("phase", "post")),
                    detected=bool(bf.get("detected", False)),
                    jpeg_b64=str(bf.get("jpeg_b64", "")),
                    crop_jpeg_b64=str(bf.get("crop_jpeg_b64", "")),
                    bbox=bbox,
                    score=float(bf["score"]) if isinstance(bf.get("score"), (int, float)) else None,
                )
            )
        except Exception:
            continue
    try:
        return TrackHistoryEntry(
            global_id=global_id,
            created_at=float(raw.get("created_at", 0.0)),
            finished_at=float(raw.get("finished_at", 0.0)),
            segments=segments,
            drop_zone_burst=burst_frames,
        )
    except Exception:
        return None


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
        persist_dir: "Path | None" = None,
    ) -> None:
        self._max_entries = int(max_entries)
        self._max_path_points = int(max_path_points)
        self._lock = threading.Lock()
        # OrderedDict → O(1) LRU-style trimming by insertion order.
        self._entries: "OrderedDict[int, TrackHistoryEntry]" = OrderedDict()
        self._persist_dir = Path(persist_dir) if persist_dir is not None else None
        if self._persist_dir is not None:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

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
            # max_entries <= 0 disables trimming entirely — keep the full run.
            if self._max_entries > 0:
                while len(self._entries) > self._max_entries:
                    popped_id, _popped = self._entries.popitem(last=False)
                    self._delete_from_disk(popped_id)
            self._write_to_disk(existing)

    def attach_burst(self, global_id: int, burst_frames: list[DropZoneBurstFrame]) -> None:
        """Attach drop-zone burst frames to an existing or newly-created entry.

        Called from the background burst-collector thread once all frames are
        ready. Creates a stub entry if the track hasn't been archived yet —
        the next ``record_segment`` call will merge into it.
        """
        with self._lock:
            existing = self._entries.get(global_id)
            if existing is None:
                if not burst_frames:
                    return
                now = burst_frames[0].timestamp if burst_frames else 0.0
                existing = TrackHistoryEntry(
                    global_id=global_id,
                    created_at=now,
                    finished_at=now,
                    segments=[],
                    drop_zone_burst=burst_frames,
                )
                self._entries[global_id] = existing
            else:
                existing.drop_zone_burst = burst_frames
            self._write_to_disk(existing)

    def max_global_id(self) -> int:
        """Highest ``global_id`` currently in the buffer (0 if empty).
        Used to seed the handoff manager's id counter after a restart so
        fresh tracks don't collide with persisted history.
        """
        with self._lock:
            if not self._entries:
                return 0
            return max(self._entries.keys())

    def flush(self, global_id: int) -> None:
        """Re-serialize a single entry — used when the async
        auto-recognize thread finishes and mutates the shared dict."""
        with self._lock:
            entry = self._entries.get(global_id)
            if entry is not None:
                self._write_to_disk(entry)

    def _entry_path(self, global_id: int) -> "Path | None":
        if self._persist_dir is None:
            return None
        return self._persist_dir / f"{int(global_id)}.json"

    def _write_to_disk(self, entry: TrackHistoryEntry) -> None:
        path = self._entry_path(entry.global_id)
        if path is None:
            return
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(entry.to_detail(), separators=(",", ":")))
            tmp.replace(path)
        except Exception:
            # Persistence is best-effort — a full disk or permission issue
            # should never take the tracker with it.
            pass

    def _delete_from_disk(self, global_id: int) -> None:
        path = self._entry_path(int(global_id))
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    def _load_from_disk(self) -> None:
        if self._persist_dir is None or not self._persist_dir.exists():
            return
        for path in sorted(self._persist_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except Exception:
                continue
            entry = _entry_from_dict(raw)
            if entry is not None:
                self._entries[entry.global_id] = entry
        # Re-sort by finished_at so most-recent is at the end.
        ordered = sorted(self._entries.items(), key=lambda kv: kv[1].finished_at)
        self._entries = OrderedDict(ordered)

    def list_summaries(
        self,
        limit: int | None = None,
        *,
        min_sectors: int = 0,
    ) -> list[dict]:
        with self._lock:
            entries = list(self._entries.values())
        if min_sectors > 0:
            entries = [
                e
                for e in entries
                if e.touches_classification_channel or e.max_sector_snapshots >= min_sectors
            ]
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
        """Clear in-memory history AND the persisted JSON files on disk."""
        with self._lock:
            self._entries.clear()
            if self._persist_dir is not None and self._persist_dir.exists():
                for path in self._persist_dir.glob("*.json"):
                    try:
                        path.unlink()
                    except Exception:
                        pass
