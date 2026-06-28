"""Angular + color tracker for circular channel motion.

Pieces on the (classification) channel travel on an arc around a known center,
so association is done in ANGLE space, not by box overlap. Each track holds an
angular position + angular velocity; between frames the angle is predicted
forward (``angle + ω·dt``). A piece that briefly leaves the frame or rounds the
curve is re-acquired where the angular prediction lands — which is exactly where
IoU-based ByteTrack fails (the linearly-extrapolated box no longer overlaps the
reappearance). A cheap average-color gate keeps a gray piece from inheriting a
yellow piece's id.

Built for low object counts (0–4 on the channel), so association is a simple
greedy nearest-angle match — no Hungarian needed. Shares the
``perception.tracking`` interface: fed bboxes + scores + the frame + the channel
each cycle, returns ``{bbox: track_id}``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from .arcs import Bbox
from .tracker_config import AngularTrackerConfig


def _bbox_center(b: Bbox) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _angle_deg(cx: float, cy: float, x: float, y: float) -> float:
    return math.degrees(math.atan2(y - cy, x - cx)) % 360.0


def _ang_dist(a: float, b: float) -> float:
    """Smallest absolute angle between two bearings, 0..180."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _signed_ang_delta(frm: float, to: float) -> float:
    """Signed shortest rotation from ``frm`` to ``to``, in (-180, 180]."""
    return ((to - frm + 180.0) % 360.0) - 180.0


def _mean_color(frame_bgr: "np.ndarray | None", b: Bbox) -> Optional[tuple[float, float, float]]:
    if frame_bgr is None:
        return None
    h, w = frame_bgr.shape[:2]
    x1 = max(0, min(int(b[0]), w - 1))
    y1 = max(0, min(int(b[1]), h - 1))
    x2 = max(x1 + 1, min(int(b[2]), w))
    y2 = max(y1 + 1, min(int(b[3]), h))
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    m = crop.reshape(-1, crop.shape[-1]).mean(axis=0) / 255.0
    return (float(m[0]), float(m[1]), float(m[2]))


def _color_dist(a: Optional[tuple], b: Optional[tuple]) -> float:
    # Normalized so the max possible distance (black vs white) is 1.0.
    if a is None or b is None:
        return 0.0
    d = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))
    return d / math.sqrt(3.0)


@dataclass
class _Track:
    track_id: int
    angle: float
    radius: float
    omega: float  # deg/s
    color: Optional[tuple[float, float, float]]
    last_t: float
    hit_count: int = 1
    bbox: Bbox = (0, 0, 0, 0)


class AngularColorTracker:
    """Greedy angular-position tracker with a color gate. One per channel."""

    def __init__(self, cfg: AngularTrackerConfig) -> None:
        self._cfg = cfg
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self._tracks = {}
        self._next_id = 1

    def update(self, upd: Any) -> dict[Bbox, int]:
        cfg = self._cfg
        channel = upd.channel
        now = float(upd.timestamp)
        center = getattr(channel, "center", None) if channel is not None else None
        # Without a center we can't do angular association — degrade to "no ids"
        # rather than guess (ByteTrack remains the fallback the operator can pick).
        if center is None:
            return {}
        cx, cy = float(center[0]), float(center[1])

        # 1) Featurize this frame's detections.
        dets = []
        for b, s in zip(upd.bboxes, upd.scores):
            mx, my = _bbox_center(b)
            dets.append(
                {
                    "bbox": (int(b[0]), int(b[1]), int(b[2]), int(b[3])),
                    "score": float(s),
                    "angle": _angle_deg(cx, cy, mx, my),
                    "radius": math.hypot(mx - cx, my - cy),
                    "color": _mean_color(upd.frame_bgr, b),
                }
            )

        # 2) Candidate (track, det) pairs that pass all gates, scored by angular
        #    distance to the track's PREDICTED angle (constant angular velocity).
        candidates = []
        for tid, tr in self._tracks.items():
            dt = max(1e-3, now - tr.last_t)
            pred_angle = (tr.angle + tr.omega * dt) % 360.0
            r_tol = max(1.0, cfg.radius_gate_frac * max(tr.radius, 1.0))
            for di, det in enumerate(dets):
                ad = _ang_dist(pred_angle, det["angle"])
                if ad > cfg.angular_gate_deg:
                    continue
                if abs(det["radius"] - tr.radius) > r_tol:
                    continue
                if cfg.use_color and _color_dist(tr.color, det["color"]) > cfg.color_gate:
                    continue
                candidates.append((ad, tid, di))

        # 3) Greedy assignment (fine for 0–4 pieces): smallest angular gap first.
        candidates.sort(key=lambda c: c[0])
        matched_tracks: set[int] = set()
        matched_dets: dict[int, int] = {}  # det index -> track id
        for _ad, tid, di in candidates:
            if tid in matched_tracks or di in matched_dets:
                continue
            matched_tracks.add(tid)
            matched_dets[di] = tid

        a = cfg.velocity_smoothing
        # 4) Update matched tracks.
        for di, tid in matched_dets.items():
            det = dets[di]
            tr = self._tracks[tid]
            dt = max(1e-3, now - tr.last_t)
            new_omega = _signed_ang_delta(tr.angle, det["angle"]) / dt
            tr.omega = a * new_omega + (1.0 - a) * tr.omega
            tr.angle = det["angle"]
            tr.radius = det["radius"]
            if det["color"] is not None:
                tr.color = (
                    det["color"]
                    if tr.color is None
                    else tuple(a * det["color"][i] + (1.0 - a) * tr.color[i] for i in range(3))
                )
            tr.bbox = det["bbox"]
            tr.last_t = now
            tr.hit_count += 1

        # 5) New tracks for unmatched, confident detections.
        for di, det in enumerate(dets):
            if di in matched_dets:
                continue
            if det["score"] < cfg.activation_score:
                continue
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = _Track(
                track_id=tid,
                angle=det["angle"],
                radius=det["radius"],
                omega=0.0,
                color=det["color"],
                last_t=now,
                bbox=det["bbox"],
            )
            matched_dets[di] = tid

        # 6) Drop tracks that have coasted longer than the allowed window.
        dead = [tid for tid, tr in self._tracks.items() if now - tr.last_t > cfg.max_coast_s]
        for tid in dead:
            del self._tracks[tid]

        # 7) Emit {bbox: id} for detections whose track has enough hits.
        out: dict[Bbox, int] = {}
        for di, tid in matched_dets.items():
            tr = self._tracks.get(tid)
            if tr is not None and tr.hit_count >= cfg.min_hits:
                out[dets[di]["bbox"]] = tid
        return out
