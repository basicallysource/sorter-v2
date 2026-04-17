"""ByteTrack-backed multi-object tracker for feeder cameras.

Wraps ``supervision.ByteTrack`` so we keep the nice parts (mature motion
model + low-score second-stage matching that recovers brief detector
dropouts) while adding the pieces the rest of the app needs: cross-camera
global IDs via ``PieceHandoffManager``, per-track snapshots for the
sidebar, angular sector capture for the pie-chart modal, and a live
thumbnail cache.

The public API mirrors the previous pure-Kalman SORT tracker so the rest
of the codebase (``VisionManager``, tests) doesn't need to change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import supervision as sv

from .base import TrackedPiece, Tracker
from .handoff import PieceHandoffManager
from .history import (
    PieceHistoryBuffer,
    SectorSnapshot,
    TrackSegment,
    encode_snapshot,
    render_sector_composite,
    render_snapshot_thumb,
)


DEFAULT_SECTOR_COUNT = 12


@dataclass
class _ChannelGeometry:
    center_x: float
    center_y: float
    r_inner: float
    r_outer: float
    sector_count: int


def _wedge_bbox(
    cx: float,
    cy: float,
    r_in: float,
    r_out: float,
    a0: float,
    a1: float,
    frame_shape: tuple[int, ...],
    samples: int = 12,
) -> tuple[int, int, int, int] | None:
    xs: list[float] = []
    ys: list[float] = []
    for i in range(samples + 1):
        t = i / samples
        a = a0 + (a1 - a0) * t
        ca, sa = math.cos(a), math.sin(a)
        xs.append(cx + r_in * ca)
        xs.append(cx + r_out * ca)
        ys.append(cy + r_in * sa)
        ys.append(cy + r_out * sa)
    h = int(frame_shape[0])
    w = int(frame_shape[1])
    x1 = max(0, int(math.floor(min(xs))))
    y1 = max(0, int(math.floor(min(ys))))
    x2 = min(w, int(math.ceil(max(xs))))
    y2 = min(h, int(math.ceil(max(ys))))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return (x1, y1, x2, y2)


@dataclass
class _LiveTrack:
    internal_id: int          # ByteTrack's tracker_id
    global_id: int            # Handoff-manager-assigned, stable across cameras
    bbox: tuple[int, int, int, int]
    center: tuple[float, float]
    velocity: tuple[float, float]
    score: float | None
    first_seen_ts: float
    origin_seen_ts: float
    last_seen_ts: float
    hit_count: int = 1
    coast_count: int = 0
    handoff_from: str | None = None
    snapshot_jpeg_b64: str = ""
    snapshot_width: int = 0
    snapshot_height: int = 0
    path: list[tuple[float, float, float]] = field(default_factory=list)
    last_capture_angle_rad: float | None = None
    last_capture_span_rad: float = 0.0
    sector_snapshots: list[SectorSnapshot] = field(default_factory=list)
    thumb_jpeg_b64: str = ""
    thumb_sector_count_at_build: int = -1


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


class ByteTrackFeederTracker(Tracker):
    """Per-camera ByteTrack wrapper with handoff + history + sector capture.

    ByteTrack owns its own Kalman filter and does the matching; we keep
    per-``tracker_id`` bookkeeping on top so the rest of the app can treat
    this like a normal ``Tracker``. Tracks are archived when they've been
    unseen for more than ``coast_limit_ticks`` consecutive update calls —
    that's looser than raw SORT to give ByteTrack's low-score second stage
    a chance to recover.
    """

    def __init__(
        self,
        role: str,
        handoff_manager: PieceHandoffManager,
        *,
        frame_rate: int = 5,
        # Activation threshold must be below our typical YOLO confidence —
        # otherwise low-score detections never create tracks and pieces keep
        # getting fresh IDs every few frames.
        track_activation_threshold: float = 0.1,
        # Matching cost threshold (1 - IoU). 0.9 accepts pairs with IoU ≥ 0.1,
        # which we need because pieces can move 30–60 px/frame on the annulus
        # and bbox-to-bbox IoU drops fast at our 5 Hz detection rate.
        minimum_matching_threshold: float = 0.9,
        # 10 s of tolerance for ByteTrack's Kalman to keep predicting a lost
        # track — pieces occasionally get hidden behind arm/shadow.
        lost_track_buffer: int = 50,
        minimum_consecutive_frames: int = 1,
        # Our archive trigger. Larger than the 5-tick default so we give
        # ByteTrack a real chance to recover tracks before we write them off.
        coast_limit_ticks: int = 20,
        detection_score_threshold: float = 0.1,
        min_hits_for_history: int = 3,
        history: PieceHistoryBuffer | None = None,
    ) -> None:
        self.role = role
        self._handoff = handoff_manager
        self._history = history
        self._score_threshold = float(detection_score_threshold)
        self._coast_limit = int(coast_limit_ticks)
        # Single-tick blips are usually detector noise — skip them so the
        # history buffer fills with real pieces instead of flicker.
        self._min_hits_for_history = max(1, int(min_hits_for_history))
        self._bytetrack = sv.ByteTrack(
            track_activation_threshold=track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=minimum_matching_threshold,
            frame_rate=frame_rate,
            minimum_consecutive_frames=minimum_consecutive_frames,
        )
        self._tracks: dict[int, _LiveTrack] = {}
        self._last_ts: float | None = None
        self._last_active: list[TrackedPiece] = []
        self._channel_geom: _ChannelGeometry | None = None

    # ---- Channel geometry (for sector-snapshot capture) ----------------

    def set_channel_geometry(
        self,
        center: tuple[float, float],
        r_inner: float,
        r_outer: float,
        sector_count: int = DEFAULT_SECTOR_COUNT,
    ) -> None:
        cx, cy = center
        if r_outer <= r_inner or sector_count <= 0:
            self._channel_geom = None
            return
        self._channel_geom = _ChannelGeometry(
            center_x=float(cx),
            center_y=float(cy),
            r_inner=float(r_inner),
            r_outer=float(r_outer),
            sector_count=int(sector_count),
        )

    # ---- Public tracker API -------------------------------------------

    def update(
        self,
        bboxes: list[tuple[int, int, int, int]],
        scores: list[float],
        timestamp: float,
        frame_bgr: "np.ndarray | None" = None,
    ) -> list[TrackedPiece]:
        # Score-filter low-confidence detections outright. ByteTrack itself
        # benefits from seeing low-score detections in the second stage, but
        # we've seen YOLO spit out sub-0.1 junk on empty frames.
        xyxy: list[list[float]] = []
        conf: list[float] = []
        for bbox, score in zip(bboxes, scores):
            s = float(score) if score is not None else 0.0
            if s < self._score_threshold:
                continue
            xyxy.append([float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])])
            conf.append(s)

        if xyxy:
            det = sv.Detections(
                xyxy=np.asarray(xyxy, dtype=np.float32),
                confidence=np.asarray(conf, dtype=np.float32),
                class_id=np.zeros(len(xyxy), dtype=int),
            )
        else:
            det = sv.Detections.empty()

        result = self._bytetrack.update_with_detections(det)
        self._last_ts = timestamp

        seen_ids: set[int] = set()
        for i in range(len(result)):
            # Tracks that ByteTrack couldn't match still appear in the
            # result with ``tracker_id = -1`` or ``None``. Skip those.
            raw_tid = result.tracker_id[i] if result.tracker_id is not None else None
            if raw_tid is None or int(raw_tid) <= 0:
                continue
            tid = int(raw_tid)
            bbox = tuple(int(v) for v in result.xyxy[i])
            score = float(result.confidence[i]) if result.confidence is not None else None
            cx, cy = _bbox_center(bbox)
            seen_ids.add(tid)

            track = self._tracks.get(tid)
            if track is None:
                global_id, handoff_from = self._handoff.register_track(
                    self.role, (cx, cy), timestamp
                )
                snap_b64, snap_w, snap_h = "", 0, 0
                if frame_bgr is not None and self._history is not None:
                    snap_b64, snap_w, snap_h = encode_snapshot(frame_bgr)
                track = _LiveTrack(
                    internal_id=tid,
                    global_id=global_id,
                    bbox=bbox,
                    center=(cx, cy),
                    velocity=(0.0, 0.0),
                    score=score,
                    first_seen_ts=timestamp,
                    origin_seen_ts=timestamp,
                    last_seen_ts=timestamp,
                    handoff_from=handoff_from,
                    snapshot_jpeg_b64=snap_b64,
                    snapshot_width=snap_w,
                    snapshot_height=snap_h,
                    path=[(float(timestamp), float(cx), float(cy))],
                )
                self._tracks[tid] = track
            else:
                prev_t, prev_x, prev_y = (
                    track.path[-1] if track.path else (timestamp, cx, cy)
                )
                dt = max(1e-3, float(timestamp) - float(prev_t))
                new_vx = (cx - prev_x) / dt
                new_vy = (cy - prev_y) / dt
                # EMA-smooth the velocity — raw frame-to-frame is noisy.
                a = 0.5
                track.velocity = (
                    a * new_vx + (1 - a) * track.velocity[0],
                    a * new_vy + (1 - a) * track.velocity[1],
                )
                track.bbox = bbox
                track.center = (cx, cy)
                track.score = score if score is not None else track.score
                track.hit_count += 1
                track.coast_count = 0
                track.last_seen_ts = timestamp
                track.path.append((float(timestamp), float(cx), float(cy)))

            self._maybe_capture_sector(track, frame_bgr, timestamp)

        # Coast unseen tracks and archive if the buffer runs out.
        dead_ids: list[int] = []
        for tid, track in self._tracks.items():
            if tid in seen_ids:
                continue
            track.coast_count += 1
            if track.coast_count > self._coast_limit:
                dead_ids.append(tid)

        for tid in dead_ids:
            track = self._tracks.pop(tid)
            self._handoff.notify_track_death(
                self.role,
                track.global_id,
                track.center,
                track.last_seen_ts,
                death_ts=timestamp,
            )
            if (
                self._history is not None
                and track.snapshot_jpeg_b64
                and track.hit_count >= self._min_hits_for_history
            ):
                self._history.record_segment(
                    self._build_segment(track),
                    global_id=track.global_id,
                )

        # Emit TrackedPiece snapshot list for overlays/API.
        active: list[TrackedPiece] = []
        for track in self._tracks.values():
            active.append(
                TrackedPiece(
                    global_id=track.global_id,
                    source_role=self.role,
                    bbox=track.bbox,
                    center=track.center,
                    velocity_px_per_s=track.velocity,
                    first_seen_ts=track.first_seen_ts,
                    origin_seen_ts=track.origin_seen_ts,
                    last_seen_ts=track.last_seen_ts,
                    hit_count=track.hit_count,
                    coasting=track.coast_count > 0,
                    score=track.score,
                    handoff_from=track.handoff_from,
                )
            )
        self._last_active = active
        return list(active)

    def active_tracks(self) -> list[TrackedPiece]:
        return list(self._last_active)

    def reset(self) -> None:
        if self._history is not None:
            for track in self._tracks.values():
                if (
                    not track.snapshot_jpeg_b64
                    or track.hit_count < self._min_hits_for_history
                ):
                    continue
                self._history.record_segment(
                    self._build_segment(track),
                    global_id=track.global_id,
                )
        self._tracks.clear()
        self._last_ts = None
        self._last_active = []
        self._bytetrack.reset()

    def get_live_thumb(self, global_id: int) -> str:
        track = next(
            (t for t in self._tracks.values() if t.global_id == global_id),
            None,
        )
        if track is None:
            return ""
        geom = self._channel_geom
        sector_n = len(track.sector_snapshots)
        if (
            geom is not None
            and sector_n > 0
            and sector_n != track.thumb_sector_count_at_build
            and track.snapshot_width > 0
            and track.snapshot_height > 0
        ):
            b64, _w, _h = render_sector_composite(
                track.sector_snapshots,
                geom.center_x,
                geom.center_y,
                geom.r_inner,
                geom.r_outer,
                track.snapshot_width,
                track.snapshot_height,
            )
            if b64:
                track.thumb_jpeg_b64 = b64
                track.thumb_sector_count_at_build = sector_n
                return b64
        if track.thumb_jpeg_b64:
            return track.thumb_jpeg_b64
        if track.snapshot_jpeg_b64:
            b64, _w, _h = render_snapshot_thumb(track.snapshot_jpeg_b64)
            if b64:
                track.thumb_jpeg_b64 = b64
                track.thumb_sector_count_at_build = sector_n
                return b64
        return ""

    # ---- Internal helpers ---------------------------------------------

    def _maybe_capture_sector(
        self,
        track: _LiveTrack,
        frame_bgr: "np.ndarray | None",
        timestamp: float,
    ) -> None:
        """Capture a dynamically-sized wedge snapshot around the piece.

        Wedge bounds are derived from the piece bbox: the four corners map
        to angles + radii via polar conversion, and we add a small margin
        so the wedge frames the piece without clipping. Triggered whenever
        the piece has traveled more than ``MIN_CAPTURE_ANGULAR_STEP_DEG``
        of arc since the last snapshot — keeps roughly sector-count-many
        captures per revolution without hard binning.
        """
        geom = self._channel_geom
        if geom is None or frame_bgr is None:
            return
        cx_t, cy_t = track.center
        dx = cx_t - geom.center_x
        dy = cy_t - geom.center_y
        dist_center = math.hypot(dx, dy)
        if dist_center < geom.r_inner * 0.4 or dist_center > geom.r_outer * 1.6:
            return

        center_angle_rad = math.atan2(dy, dx)

        # Angular + radial extent from bbox corners.
        x1, y1, x2, y2 = track.bbox
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        corner_angles = [math.atan2(cy - geom.center_y, cx - geom.center_x) for cx, cy in corners]
        corner_radii = [math.hypot(cx - geom.center_x, cy - geom.center_y) for cx, cy in corners]

        # Unwrap angles so we can pick min/max without wrap-around glitches.
        anchor = center_angle_rad
        unwrapped = []
        for a in corner_angles:
            d = a - anchor
            while d > math.pi:
                d -= 2 * math.pi
            while d < -math.pi:
                d += 2 * math.pi
            unwrapped.append(anchor + d)
        a_min = min(unwrapped)
        a_max = max(unwrapped)
        # Angular margin: at least 4° each side, or 25% of the extent.
        angular_margin = max(math.radians(4.0), (a_max - a_min) * 0.25)
        a0 = a_min - angular_margin
        a1 = a_max + angular_margin

        # Radial margin: small absolute pad; clamp to channel bounds with slack.
        r_margin = max(4.0, (max(corner_radii) - min(corner_radii)) * 0.25)
        r_in = max(geom.r_inner * 0.5, min(corner_radii) - r_margin)
        r_out = min(geom.r_outer * 1.15, max(corner_radii) + r_margin)
        if r_out <= r_in:
            return

        # No-overlap trigger: new wedge's center must be far enough from the
        # last wedge's center that the two wedges don't touch. Required gap =
        # half of last span + half of new span + small safety margin.
        new_span_rad = a1 - a0
        min_gap_rad = math.radians(3.0)
        if track.last_capture_angle_rad is not None:
            raw_diff = center_angle_rad - track.last_capture_angle_rad
            # Normalize to [-π, π] so wrap-around works.
            while raw_diff > math.pi:
                raw_diff -= 2 * math.pi
            while raw_diff < -math.pi:
                raw_diff += 2 * math.pi
            required = (track.last_capture_span_rad + new_span_rad) / 2.0 + min_gap_rad
            if abs(raw_diff) < required:
                return

        bbox = _wedge_bbox(
            geom.center_x,
            geom.center_y,
            r_in,
            r_out,
            a0,
            a1,
            frame_bgr.shape,
        )
        if bbox is None:
            return
        bx1, by1, bx2, by2 = bbox
        crop = frame_bgr[by1:by2, bx1:bx2]
        if crop.size == 0:
            return
        b64, w, h = encode_snapshot(crop)
        if not b64:
            return

        # Keep the legacy sector_index field useful for debugging — use the
        # center angle to compute which 30° slice the piece is roughly in.
        sector_span = (2 * math.pi) / geom.sector_count
        norm_angle = center_angle_rad % (2 * math.pi)
        idx = int(norm_angle / sector_span) % geom.sector_count

        track.sector_snapshots.append(
            SectorSnapshot(
                sector_index=idx,
                start_angle_deg=math.degrees(a0) % 360.0,
                end_angle_deg=math.degrees(a1) % 360.0,
                captured_ts=float(timestamp),
                bbox_x=int(bx1),
                bbox_y=int(by1),
                width=int(w),
                height=int(h),
                jpeg_b64=b64,
                r_inner=float(r_in),
                r_outer=float(r_out),
            )
        )
        track.last_capture_angle_rad = center_angle_rad
        track.last_capture_span_rad = new_span_rad

    def _build_segment(self, track: _LiveTrack) -> TrackSegment:
        geom = self._channel_geom
        composite_b64 = ""
        composite_w = composite_h = 0
        if (
            geom is not None
            and track.sector_snapshots
            and track.snapshot_width > 0
            and track.snapshot_height > 0
        ):
            composite_b64, composite_w, composite_h = render_sector_composite(
                track.sector_snapshots,
                geom.center_x,
                geom.center_y,
                geom.r_inner,
                geom.r_outer,
                track.snapshot_width,
                track.snapshot_height,
            )
        if not composite_b64 and track.snapshot_jpeg_b64:
            composite_b64, composite_w, composite_h = render_snapshot_thumb(
                track.snapshot_jpeg_b64
            )
        return TrackSegment(
            source_role=self.role,
            handoff_from=track.handoff_from,
            first_seen_ts=track.first_seen_ts,
            last_seen_ts=track.last_seen_ts,
            snapshot_jpeg_b64=track.snapshot_jpeg_b64,
            snapshot_width=track.snapshot_width,
            snapshot_height=track.snapshot_height,
            path=list(track.path),
            hit_count=track.hit_count,
            channel_center_x=geom.center_x if geom is not None else None,
            channel_center_y=geom.center_y if geom is not None else None,
            channel_radius_inner=geom.r_inner if geom is not None else None,
            channel_radius_outer=geom.r_outer if geom is not None else None,
            sector_count=geom.sector_count if geom is not None else 0,
            sector_snapshots=list(track.sector_snapshots),
            composite_jpeg_b64=composite_b64,
            composite_width=composite_w,
            composite_height=composite_h,
        )
