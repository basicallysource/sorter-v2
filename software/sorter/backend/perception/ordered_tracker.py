"""Order-preserving tracker for the classification channel.

Built for this machine's exact situation, exploiting an invariant nothing else
uses: on a rigid one-way platter, pieces NEVER pass each other, so their order
around the channel is fixed. Association therefore reduces to aligning two
already-ordered lists (the live tracks and this frame's detections) — which is
robust to arbitrarily large between-frame jumps (a piece that the platter just
flung 90 deg forward is still the Nth piece in line). No motion model, no
prediction, and crucially NO dependence on motor-command timing — it reads only
the bbox stream, so there is nothing to synchronise against the perception loop.

Why this beats the alternatives here:
- ByteTrack matches by box IoU -> the rotation jump breaks overlap -> new id.
- The angular tracker predicts by constant angular velocity -> a stationary
  piece (omega~=0) that suddenly accelerates outruns its own prediction on the
  first frame of a move -> lost id.
- This tracker only requires that order is preserved and that pieces move
  FORWARD (toward the exit); both always hold. Colour/size/radius are used only
  as soft tie-breakers to disambiguate the rare same-frame "one exits at the
  head while one enters at the drop" case.

Designed for 0-4 pieces, so the alignment is a tiny exact DP. Shares the
``perception.tracking`` interface: fed bboxes + scores + the frame + the
channel each cycle, returns ``{bbox: track_id}``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - cv2 is a hard backend dep; guard dev imports
    cv2 = None  # type: ignore[assignment]

from .arcs import Bbox, bboxCenter, orderedPieceObservations
from .tracker_config import OrderedTrackerConfig

_INF = float("inf")
# perception.arcs region code for the drop zone (where new pieces legitimately
# enter). A detection sitting here is a strong new-piece candidate.
_DROP_ZONE = 1


def _color_feat(
    frame_bgr: "np.ndarray | None", bbox: Bbox, center_frac: float
) -> Optional[tuple[float, float, float]]:
    """A lighting-tolerant colour descriptor sampled from the CENTRE of the box
    (a big box is mostly platter background, so the centre is where the piece
    actually is). Returns a saturation-weighted hue vector plus brightness:
    ``(s*cos h, s*sin h, v)``. Two grey pieces collapse to ~(0,0,v) and separate
    by brightness; two distinct hues separate by the chroma vector. ``None`` when
    no frame / empty crop."""
    if frame_bgr is None or cv2 is None:
        return None
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return None
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    hw, hh = bw * center_frac / 2.0, bh * center_frac / 2.0
    cx1, cy1 = max(0, int(mx - hw)), max(0, int(my - hh))
    cx2, cy2 = min(w, int(mx + hw) + 1), min(h, int(my + hh) + 1)
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    crop = frame_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue = hsv[..., 0].astype(np.float32) * (2.0 * math.pi / 180.0)  # OpenCV H is 0..179
    sat = hsv[..., 1].astype(np.float32) / 255.0
    val = hsv[..., 2].astype(np.float32) / 255.0
    return (
        float(np.mean(sat * np.cos(hue))),
        float(np.mean(sat * np.sin(hue))),
        float(np.mean(val)),
    )


def _color_dist(a: Optional[tuple], b: Optional[tuple]) -> float:
    # Brightness (v) is down-weighted because it shifts most with lighting as a
    # piece travels under the hood. 0 when either side is unknown (neutral).
    if a is None or b is None:
        return 0.0
    dx, dy, dv = a[0] - b[0], a[1] - b[1], (a[2] - b[2]) * 0.6
    return min(1.0, math.sqrt(dx * dx + dy * dy + dv * dv))


@dataclass
class _Det:
    bbox: Bbox
    gap: float          # travel coord: forward gap to exit, SMALLER = more forward
    zone: int
    score: float
    radius: float
    color: Optional[tuple[float, float, float]]
    area: float


@dataclass
class _Track:
    track_id: int
    gap: float
    zone: int
    radius: float
    color: Optional[tuple[float, float, float]]
    area: float
    bbox: Bbox
    last_match_t: float
    hits: int = 1


@dataclass
class _Alignment:
    matches: list[tuple[int, int]] = field(default_factory=list)  # (track idx, det idx)
    unmatched_tracks: list[int] = field(default_factory=list)
    unmatched_dets: list[int] = field(default_factory=list)


class OrderedChannelTracker:
    """Order-preserving channel tracker with colour/size tie-breaks."""

    def __init__(self, cfg: OrderedTrackerConfig) -> None:
        self._cfg = cfg
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self._tracks = {}
        self._next_id = 1

    # ------------------------------------------------------------------ update

    def update(self, upd: Any) -> dict[Bbox, int]:
        cfg = self._cfg
        channel = upd.channel
        now = float(upd.timestamp)
        center = getattr(channel, "center", None) if channel is not None else None
        if center is None:
            return {}
        cx, cy = float(center[0]), float(center[1])

        score_by_bbox: dict[Bbox, float] = {}
        for b, s in zip(upd.bboxes, upd.scores or []):
            score_by_bbox[(int(b[0]), int(b[1]), int(b[2]), int(b[3]))] = float(s)

        # orderedPieceObservations returns on-channel pieces leading-first
        # (ascending gap-to-exit) — exactly the order invariant we rely on.
        dets: list[_Det] = []
        for gap, _sec, zone, bbox in orderedPieceObservations(upd.bboxes, channel):
            mx, my = bboxCenter(bbox)
            x1, y1, x2, y2 = bbox
            dets.append(
                _Det(
                    bbox=bbox,
                    gap=float(gap),
                    zone=int(zone),
                    score=score_by_bbox.get(bbox, 1.0),
                    radius=math.hypot(mx - cx, my - cy),
                    color=_color_feat(upd.frame_bgr, bbox, cfg.color_center_frac),
                    area=float(max(1, (x2 - x1)) * max(1, (y2 - y1))),
                )
            )

        tracks = sorted(self._tracks.values(), key=lambda t: t.gap)  # leading-first
        align = self._align(tracks, dets)

        # An id is emitted (and so becomes a real piece downstream) only once a
        # track is CONFIRMED — seen for min_hits frames. A one-frame false box
        # never reaches that, so it's filtered out before it can spawn a phantom
        # piece or a bogus multi-drop.
        out: dict[Bbox, int] = {}
        for ti, di in align.matches:
            tr = tracks[ti]
            det = dets[di]
            self._updateTrack(tr, det, now)
            if tr.hits >= cfg.min_hits:
                out[det.bbox] = tr.track_id
        for di in align.unmatched_dets:
            det = dets[di]
            if det.score >= cfg.new_track_min_score:
                tr = self._newTrack(det, now)
                if tr.hits >= cfg.min_hits:
                    out[det.bbox] = tr.track_id
        # Coast unmatched tracks until they age out. Two-tier leash: a CONFIRMED
        # piece is held max_coast_s so it survives a real detector blink; an
        # unconfirmed (tentative) track gets the much shorter tentative leash so a
        # one-frame ghost is discarded almost immediately instead of lingering in
        # the order alignment.
        for tid, tr in list(self._tracks.items()):
            leash = cfg.max_coast_s if tr.hits >= cfg.min_hits else cfg.tentative_max_coast_s
            if now - tr.last_match_t > leash:
                del self._tracks[tid]
        return out

    # --------------------------------------------------- alignment (tiny exact DP)

    def _align(self, tracks: list[_Track], dets: list[_Det]) -> _Alignment:
        m, n = len(tracks), len(dets)
        if m == 0:
            return _Alignment(unmatched_dets=list(range(n)))
        if n == 0:
            return _Alignment(unmatched_tracks=list(range(m)))

        # cost[i][j] = best cost aligning tracks[0..i) with dets[0..j); both lists
        # are leading-first, so a monotonic alignment IS the no-crossing
        # constraint. back[][] records the chosen step for backtracking.
        cost = [[0.0] * (n + 1) for _ in range(m + 1)]
        back = [[0] * (n + 1) for _ in range(m + 1)]  # 0=match 1=skip-track 2=skip-det
        for i in range(1, m + 1):
            cost[i][0] = cost[i - 1][0] + self._missCost(i - 1)
            back[i][0] = 1
        for j in range(1, n + 1):
            cost[0][j] = cost[0][j - 1] + self._newCost(dets[j - 1])
            back[0][j] = 2
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                mc = cost[i - 1][j - 1] + self._matchCost(tracks[i - 1], dets[j - 1])
                sk_t = cost[i - 1][j] + self._missCost(i - 1)
                sk_d = cost[i][j - 1] + self._newCost(dets[j - 1])
                best, choice = mc, 0
                if sk_t < best:
                    best, choice = sk_t, 1
                if sk_d < best:
                    best, choice = sk_d, 2
                cost[i][j] = best
                back[i][j] = choice

        align = _Alignment()
        i, j = m, n
        while i > 0 or j > 0:
            if i > 0 and j > 0 and back[i][j] == 0:
                align.matches.append((i - 1, j - 1))
                i, j = i - 1, j - 1
            elif i > 0 and (j == 0 or back[i][j] == 1):
                align.unmatched_tracks.append(i - 1)
                i -= 1
            else:
                align.unmatched_dets.append(j - 1)
                j -= 1
        return align

    def _matchCost(self, tr: _Track, det: _Det) -> float:
        cfg = self._cfg
        # Pieces only ever move FORWARD (gap shrinks toward the exit). A detection
        # whose gap grew beyond a small jitter tolerance moved backward -> cannot
        # be this track. A large forward jump is free (that is the whole point).
        if det.gap - tr.gap > cfg.back_tol_deg:
            return _INF
        appearance = (
            cfg.color_weight * _color_dist(tr.color, det.color)
            + cfg.size_weight * (abs(tr.area - det.area) / max(tr.area, det.area))
            + cfg.radius_weight * (abs(tr.radius - det.radius) / max(tr.radius, 1.0))
        )
        if appearance > cfg.match_max_cost:
            return _INF
        return appearance

    def _missCost(self, track_idx: int) -> float:
        # Leaving a track unmatched (coast/exit). The head (leading, idx 0) is the
        # only piece that can fall off the exit, so an unmatched head is cheap
        # (it probably just exited); an unmatched middle track is a blink we would
        # rather hold, so it is dearer.
        cfg = self._cfg
        return cfg.miss_cost * (0.5 if track_idx == 0 else 1.0)

    def _newCost(self, det: _Det) -> float:
        # Spawning a new id for an unmatched detection. A box in the drop zone is a
        # legitimate new arrival, so it is cheap; elsewhere it is more likely a
        # re-detection of a coasting track, so prefer matching by making it dearer.
        cfg = self._cfg
        return cfg.new_cost * (0.5 if det.zone == _DROP_ZONE else 1.0)

    # ------------------------------------------------------------------ helpers

    def _updateTrack(self, tr: _Track, det: _Det, now: float) -> None:
        a = self._cfg.smoothing
        tr.gap = det.gap
        tr.zone = det.zone
        tr.radius = det.radius
        tr.area = det.area
        tr.bbox = det.bbox
        tr.last_match_t = now
        tr.hits += 1
        if det.color is not None:
            if tr.color is None:
                tr.color = det.color
            else:
                tr.color = (
                    a * det.color[0] + (1.0 - a) * tr.color[0],
                    a * det.color[1] + (1.0 - a) * tr.color[1],
                    a * det.color[2] + (1.0 - a) * tr.color[2],
                )

    def _newTrack(self, det: _Det, now: float) -> _Track:
        tid = self._next_id
        self._next_id += 1
        tr = _Track(
            track_id=tid,
            gap=det.gap,
            zone=det.zone,
            radius=det.radius,
            color=det.color,
            area=det.area,
            bbox=det.bbox,
            last_match_t=now,
            hits=1,
        )
        self._tracks[tid] = tr
        return tr
