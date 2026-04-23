"""Polar-space Hungarian tracker — port of PolarFeederTracker.

Simplified from the original:
- no OSNet / appearance embeddings (runtime-rebuild phase carries only geometry)
- no PieceHandoffManager (that lives in a separate runtime-level concern)
- no history buffer / sector capture / dossier mint

Kept:
- polar (angle, radius) + polar Kalman prediction when geometry is set
- cartesian L2 fallback when no polar_center is given
- Hungarian assignment with per-pair gating
- whitelist confirmation (monotonic angular progress >= 5 deg OR centroid
  drift >= 40 px) - sticky once flipped True
- coast-limit expiration of unmatched tracks

global_id == track_id here. Cross-camera inheritance is a handoff-manager
concern that is not in scope for this perception-layer tracker.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from rt.contracts.detection import DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import register_tracker
from rt.contracts.tracking import Track, TrackBatch


_CONFIRMED_MIN_ANGULAR_PROGRESS_DEG = 5.0
# Reversal tolerance absorbs detector jitter: per-frame bbox noise of a
# couple of degrees is normal, especially near the ring centre where a
# few pixels of wobble translate into several degrees. 1° was strict
# enough to reject real pieces that only wobbled during smooth rotation;
# 4° keeps the check honest without over-rejecting.
_CONFIRMED_REVERSAL_TOLERANCE_DEG = 4.0
_CONFIRMED_MIN_CENTROID_DRIFT_PX = 40.0
_CONFIRMED_WINDOW_MIN_SAMPLES = 6
# Asymmetric verdicts — easy to confirm real, hard to declare ghost:
#   * Motion evidence (6 samples) flips pending/ghost back to real.
#   * Ghost demands substantially more rotation-windowed evidence of
#     non-motion (18 samples). A fresh piece briefly stopping between
#     carousel moves must not be labelled a ghost before the operator
#     even sees it move.
_GHOST_WINDOW_MIN_SAMPLES = 18
_VERDICT_WINDOW_SAMPLES = 18
# Cap rotation_samples so long-lived tracks don't accumulate unbounded
# memory. Must be >= _VERDICT_WINDOW_SAMPLES.
_ROTATION_SAMPLES_MAX = 64
_ROTATION_WINDOW_BUFFER = 128  # rolling history kept in memory
_ROTATION_WINDOW_MAX_AGE_S = 60.0


def _wrap_angle(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _circular_diff(a: float, b: float) -> float:
    return _wrap_angle(a - b)


def _bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


class _PolarKalman:
    """Kalman filter over [angle, radius, ang_vel, rad_vel]."""

    def __init__(self, angle: float, radius: float) -> None:
        self.state = np.array(
            [_wrap_angle(angle), float(radius), 0.0, 0.0], dtype=np.float64
        )
        self.P = np.diag([0.02, 200.0, 1.0, 50.0]).astype(np.float64)
        self.Q = np.diag([0.001, 2.0, 0.05, 20.0]).astype(np.float64)
        self.R = np.diag([0.005, 12.0]).astype(np.float64)
        self.H = np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64
        )

    def predict(self, dt: float) -> None:
        if dt <= 0:
            return
        F = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self.state = F @ self.state
        self.state[0] = _wrap_angle(self.state[0])
        self.P = F @ self.P @ F.T + self.Q

    def update(self, meas_angle: float, meas_radius: float) -> None:
        y = np.array(
            [
                _circular_diff(meas_angle, self.state[0]),
                meas_radius - self.state[1],
            ],
            dtype=np.float64,
        )
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y
        self.state[0] = _wrap_angle(self.state[0])
        self.P = (np.eye(4) - K @ self.H) @ self.P

    @property
    def angle(self) -> float:
        return float(self.state[0])

    @property
    def radius(self) -> float:
        return float(self.state[1])


@dataclass
class _LiveTrack:
    track_id: int
    bbox: tuple[int, int, int, int]
    center_px: tuple[float, float]
    score: float
    first_seen_ts: float
    last_seen_ts: float
    hit_count: int = 1
    coast_count: int = 0
    confirmed_real: bool = False
    ghost: bool = False
    kalman: _PolarKalman | None = None
    path: list[tuple[float, float, float]] = field(default_factory=list)
    # Samples whose timestamp fell inside a known rotation window; used as
    # the authoritative input for confirmed_real and ghost verdicts.
    rotation_samples: list[tuple[float, float, float]] = field(default_factory=list)
    angle_rad: float | None = None
    radius_px: float | None = None


@register_tracker("polar")
class PolarTracker:
    """Hungarian-assignment tracker in polar or cartesian space."""

    key = "polar"

    def __init__(
        self,
        polar_center: tuple[float, float] | None = None,
        polar_radius_range: tuple[float, float] | None = None,
        max_angular_step_deg: float = 45.0,
        max_radial_step_px: float = 60.0,
        pixel_fallback_distance_px: float = 100.0,
        coast_limit_ticks: int = 20,
        detection_score_threshold: float = 0.0,
    ) -> None:
        if polar_center is not None:
            self._polar_center: tuple[float, float] | None = (
                float(polar_center[0]),
                float(polar_center[1]),
            )
        else:
            self._polar_center = None
        self._polar_radius_range = polar_radius_range
        self._max_angular_step = math.radians(float(max_angular_step_deg))
        self._max_radial_step = float(max_radial_step_px)
        self._pixel_fallback = float(pixel_fallback_distance_px)
        self._coast_limit = int(coast_limit_ticks)
        self._score_threshold = float(detection_score_threshold)
        self._tracks: dict[int, _LiveTrack] = {}
        self._next_track_id = 1
        self._last_ts: float | None = None
        self._lock = threading.RLock()
        # Rolling buffer of rotation windows, published by the runtime that
        # drives this feed's motor. A sample whose timestamp falls inside
        # any window counts as "during rotation" for ghost/confirmed-real
        # evaluation. Thread-safe via the shared RLock.
        self._rotation_windows: deque[tuple[float, float]] = deque(
            maxlen=_ROTATION_WINDOW_BUFFER
        )

    # ---- Geometry helpers ---------------------------------------------

    def _to_polar(self, center_px: tuple[float, float]) -> tuple[float, float]:
        assert self._polar_center is not None
        cx, cy = center_px
        dx = cx - self._polar_center[0]
        dy = cy - self._polar_center[1]
        return math.atan2(dy, dx), math.hypot(dx, dy)

    # ---- Public API ----------------------------------------------------

    def register_rotation_window(self, start_ts: float, end_ts: float) -> None:
        """Record that the ring/carousel was rotating in ``[start_ts, end_ts]``.

        ``ts`` values are frame timestamps (same clock as ``FeedFrame.timestamp``).
        Called by the runtime whenever it commands a pulse or a carousel move.
        Samples whose timestamp falls in any stored window count as
        "during-rotation" for ghost / confirmed-real verdicts.
        """
        if not (end_ts > start_ts):
            return
        with self._lock:
            self._rotation_windows.append((float(start_ts), float(end_ts)))
            # Trim windows older than _ROTATION_WINDOW_MAX_AGE_S so memory
            # does not grow unbounded on long-lived runs.
            if self._last_ts is not None:
                cutoff = float(self._last_ts) - _ROTATION_WINDOW_MAX_AGE_S
                while self._rotation_windows and self._rotation_windows[0][1] < cutoff:
                    self._rotation_windows.popleft()

    def _in_rotation_window(self, ts: float) -> bool:
        for start, end in self._rotation_windows:
            if start <= ts <= end:
                return True
        return False

    def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch:
        with self._lock:
            return self._update_locked(detections, frame)

    def _update_locked(
        self, detections: DetectionBatch, frame: FeedFrame
    ) -> TrackBatch:
        timestamp = frame.timestamp if frame.timestamp > 0 else time.time()
        # Score filter
        filtered: list[tuple[tuple[int, int, int, int], float]] = []
        for det in detections.detections:
            score = float(det.score)
            if score < self._score_threshold:
                continue
            bbox = tuple(int(v) for v in det.bbox_xyxy)
            filtered.append((bbox, score))

        dt = 0.2 if self._last_ts is None else max(0.0, timestamp - self._last_ts)
        self._last_ts = timestamp

        for track in self._tracks.values():
            if track.kalman is not None:
                track.kalman.predict(dt)

        track_ids = list(self._tracks.keys())
        matched_tids: set[int] = set()
        matched_det_indices: set[int] = set()

        if track_ids and filtered:
            self._assign(track_ids, filtered, matched_tids, matched_det_indices, timestamp)

        # Coast unmatched tracks
        lost_ids: list[int] = []
        for tid, track in list(self._tracks.items()):
            if tid in matched_tids:
                continue
            track.coast_count += 1
            if track.coast_count > self._coast_limit:
                self._tracks.pop(tid)
                lost_ids.append(tid)

        # Spawn tracks from unmatched detections
        for idx, (bbox, score) in enumerate(filtered):
            if idx in matched_det_indices:
                continue
            cx, cy = _bbox_center(bbox)
            kalman: _PolarKalman | None = None
            ang: float | None = None
            rad: float | None = None
            if self._polar_center is not None:
                ang, rad = self._to_polar((cx, cy))
                kalman = _PolarKalman(ang, rad)
            tid = self._next_track_id
            self._next_track_id += 1
            self._tracks[tid] = _LiveTrack(
                track_id=tid,
                bbox=bbox,
                center_px=(cx, cy),
                score=score,
                first_seen_ts=timestamp,
                last_seen_ts=timestamp,
                kalman=kalman,
                angle_rad=ang,
                radius_px=rad,
                path=[(float(timestamp), float(cx), float(cy))],
            )

        # Emit snapshot
        track_list: list[Track] = []
        for track in self._tracks.values():
            track_list.append(
                Track(
                    track_id=track.track_id,
                    global_id=track.track_id,
                    piece_uuid=None,
                    bbox_xyxy=track.bbox,
                    score=float(track.score),
                    confirmed_real=bool(track.confirmed_real),
                    angle_rad=track.angle_rad,
                    radius_px=track.radius_px,
                    hit_count=int(track.hit_count),
                    first_seen_ts=float(track.first_seen_ts),
                    last_seen_ts=float(track.last_seen_ts),
                    ghost=bool(track.ghost),
                )
            )

        return TrackBatch(
            feed_id=detections.feed_id,
            frame_seq=detections.frame_seq,
            timestamp=timestamp,
            tracks=tuple(track_list),
            lost_track_ids=tuple(lost_ids),
        )

    def _assign(
        self,
        track_ids: list[int],
        filtered: list[tuple[tuple[int, int, int, int], float]],
        matched_tids: set[int],
        matched_det_indices: set[int],
        timestamp: float,
    ) -> None:
        from scipy.optimize import linear_sum_assignment

        rows = len(track_ids)
        cols = len(filtered)
        large = 1e6
        cost = np.full((rows, cols), large, dtype=np.float64)

        det_centers = [_bbox_center(bb) for bb, _ in filtered]

        if self._polar_center is not None:
            det_polar = [self._to_polar(c) for c in det_centers]
            for ri, tid in enumerate(track_ids):
                track = self._tracks[tid]
                if track.kalman is None:
                    ang, rad = self._to_polar(track.center_px)
                    track.kalman = _PolarKalman(ang, rad)
                pa = track.kalman.angle
                pr = track.kalman.radius
                for ci, (da, dr) in enumerate(det_polar):
                    ang_cost = abs(_circular_diff(da, pa)) / self._max_angular_step
                    rad_cost = abs(dr - pr) / self._max_radial_step
                    if ang_cost >= 1.0 or rad_cost >= 1.0:
                        continue
                    cost[ri, ci] = ang_cost + 0.5 * rad_cost
        else:
            for ri, tid in enumerate(track_ids):
                track = self._tracks[tid]
                tx, ty = track.center_px
                for ci, (dx, dy) in enumerate(det_centers):
                    d = math.hypot(dx - tx, dy - ty)
                    if d >= self._pixel_fallback:
                        continue
                    cost[ri, ci] = d / self._pixel_fallback

        row_ind, col_ind = linear_sum_assignment(cost)
        for r, c in zip(row_ind, col_ind):
            if cost[r, c] >= large:
                continue
            tid = track_ids[r]
            matched_tids.add(tid)
            matched_det_indices.add(int(c))
            bbox, score = filtered[c]
            cx, cy = _bbox_center(bbox)
            track = self._tracks[tid]
            if track.kalman is not None and self._polar_center is not None:
                da, dr = self._to_polar((cx, cy))
                track.kalman.update(da, dr)
                track.angle_rad = da
                track.radius_px = dr
            track.bbox = bbox
            track.center_px = (cx, cy)
            track.score = float(score)
            track.hit_count += 1
            track.coast_count = 0
            track.last_seen_ts = timestamp
            sample = (float(timestamp), float(cx), float(cy))
            track.path.append(sample)
            # Only samples observed during a known rotation window contribute
            # to ghost/confirmed-real verdicts — so a stationary track during
            # standstill is never prematurely judged a ghost.
            if self._in_rotation_window(float(timestamp)):
                track.rotation_samples.append(sample)
                if len(track.rotation_samples) > _ROTATION_SAMPLES_MAX:
                    del track.rotation_samples[: -_ROTATION_SAMPLES_MAX]
                # Evaluate confirmed/ghost on a rolling window of the most
                # recent rotation samples. A track that moved earlier but
                # stops while the ring keeps turning must be able to flip
                # back to ghost, and a track declared ghost can flip back
                # to confirmed if it finally moves — both directions are
                # honest reads of the latest evidence.
                window = track.rotation_samples[-_VERDICT_WINDOW_SAMPLES:]
                if self._evaluate_confirmed_real_samples(window):
                    track.confirmed_real = True
                    track.ghost = False
                else:
                    track.confirmed_real = False
                    track.ghost = len(window) >= _GHOST_WINDOW_MIN_SAMPLES

    def _evaluate_confirmed_real(self, track: _LiveTrack) -> bool:
        return self._evaluate_confirmed_real_samples(track.rotation_samples)

    def _evaluate_confirmed_real_samples(
        self,
        samples: list[tuple[float, float, float]],
    ) -> bool:
        if len(samples) < _CONFIRMED_WINDOW_MIN_SAMPLES:
            return False

        # (B) centroid drift - works without polar geometry. Use the
        # first and last third of the window so the head/tail medians
        # stay non-overlapping even at the minimum-sample boundary.
        half = max(2, len(samples) // 3)
        head = samples[:half]
        tail = samples[-half:]
        head_x = sorted(float(s[1]) for s in head)[len(head) // 2]
        head_y = sorted(float(s[2]) for s in head)[len(head) // 2]
        tail_x = sorted(float(s[1]) for s in tail)[len(tail) // 2]
        tail_y = sorted(float(s[2]) for s in tail)[len(tail) // 2]
        if math.hypot(tail_x - head_x, tail_y - head_y) >= _CONFIRMED_MIN_CENTROID_DRIFT_PX:
            return True

        if self._polar_center is None:
            return False

        reversal_tol = math.radians(_CONFIRMED_REVERSAL_TOLERANCE_DEG)
        min_progress = math.radians(_CONFIRMED_MIN_ANGULAR_PROGRESS_DEG)
        start_angle, _ = self._to_polar((float(samples[0][1]), float(samples[0][2])))
        unwrapped: list[float] = [0.0]
        anchor = start_angle
        accum = 0.0
        for _ts, x, y in samples[1:]:
            angle, _ = self._to_polar((float(x), float(y)))
            step = _circular_diff(angle, anchor)
            accum += step
            unwrapped.append(accum)
            anchor = angle
        net_progress = abs(unwrapped[-1])
        if net_progress < min_progress:
            return False
        direction = 1.0 if unwrapped[-1] >= 0.0 else -1.0
        for i in range(1, len(unwrapped)):
            step = (unwrapped[i] - unwrapped[i - 1]) * direction
            if step < -reversal_tol:
                return False
        return True

    def _evaluate_ghost(self, track: _LiveTrack) -> bool:
        # A track is declared a ghost only after it has accumulated enough
        # rotation-windowed evidence without being confirmed-real — i.e. the
        # ring was rotating around it, but it stayed put.
        return len(track.rotation_samples) >= _GHOST_WINDOW_MIN_SAMPLES

    def ring_geometry(self) -> dict[str, float] | None:
        """Return polar geometry (center + radii) when configured.

        Used by overlay/snapshot callers that need the ring's image-space
        geometry without re-reading the saved polygon blob.
        """
        if self._polar_center is None:
            return None
        cx, cy = self._polar_center
        inner: float | None
        outer: float | None
        if self._polar_radius_range is not None:
            inner = float(self._polar_radius_range[0])
            outer = float(self._polar_radius_range[1])
        else:
            inner = None
            outer = None
        return {
            "center_x": float(cx),
            "center_y": float(cy),
            "inner_radius": float(inner) if inner is not None else 0.0,
            "outer_radius": float(outer) if outer is not None else 0.0,
        }

    def live_global_ids(self) -> set[int]:
        with self._lock:
            return {t.track_id for t in self._tracks.values()}

    def reset(self) -> None:
        with self._lock:
            self._tracks.clear()
            self._rotation_windows.clear()
            self._last_ts = None
            self._next_track_id = 1


__all__ = ["PolarTracker"]
