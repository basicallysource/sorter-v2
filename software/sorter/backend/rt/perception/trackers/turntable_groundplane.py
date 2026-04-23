"""Shadow tracker prototype using ground-plane/cartesian association.

This tracker is intentionally independent from the production polar tracker.
It is built for shadow-mode comparison: fast births, conservative merging of
near-duplicate tracks, and a cartesian motion model that can later consume
turntable telemetry as a deterministic rotation prior.
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


_ROTATION_WINDOW_BUFFER = 128
_ROTATION_WINDOW_MAX_AGE_S = 60.0
_CONFIRMED_MIN_ANGULAR_PROGRESS_DEG = 5.0
_CONFIRMED_REVERSAL_TOLERANCE_DEG = 4.0
_CONFIRMED_MIN_CENTROID_DRIFT_PX = 40.0
_CONFIRMED_WINDOW_MIN_SAMPLES = 6
_GHOST_WINDOW_MIN_SAMPLES = 18
_VERDICT_WINDOW_SAMPLES = 18
_ROTATION_SAMPLES_MAX = 64


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _circular_diff(a: float, b: float) -> float:
    return _wrap_angle(float(a) - float(b))


def _bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0


def _bbox_iou(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = float(iw * ih)
    if inter <= 0.0:
        return 0.0
    area_a = float(max(0, ax2 - ax1) * max(0, ay2 - ay1))
    area_b = float(max(0, bx2 - bx1) * max(0, by2 - by1))
    denom = area_a + area_b - inter
    return inter / denom if denom > 0.0 else 0.0


class _CartesianKalman:
    """Small constant-velocity KF over image/world-plane coordinates."""

    def __init__(self, x: float, y: float) -> None:
        self.state = np.array([float(x), float(y), 0.0, 0.0], dtype=np.float64)
        self.P = np.diag([80.0, 80.0, 400.0, 400.0]).astype(np.float64)
        self.Q_base = np.diag([4.0, 4.0, 120.0, 120.0]).astype(np.float64)
        self.R = np.diag([36.0, 36.0]).astype(np.float64)
        self.H = np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64
        )

    def predict(
        self,
        dt: float,
        *,
        omega_rad_s: float | None = None,
        pivot: tuple[float, float] | None = None,
    ) -> None:
        if dt <= 0.0:
            return
        if pivot is not None and omega_rad_s is not None and abs(omega_rad_s) > 1e-4:
            px, py = pivot
            theta = float(omega_rad_s) * float(dt)
            c = math.cos(theta)
            s = math.sin(theta)
            rx = self.state[0] - px
            ry = self.state[1] - py
            vx = self.state[2]
            vy = self.state[3]
            self.state[0] = px + c * rx - s * ry
            self.state[1] = py + s * rx + c * ry
            self.state[2] = c * vx - s * vy
            self.state[3] = s * vx + c * vy
            # Velocity here represents slip/residual motion after the table
            # rotation prior. Keep a small residual constant-velocity step.
            self.state[0] += self.state[2] * dt
            self.state[1] += self.state[3] * dt
        else:
            self.state[0] += self.state[2] * dt
            self.state[1] += self.state[3] * dt

        F = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        q_scale = max(1.0, dt / 0.1)
        self.P = F @ self.P @ F.T + (self.Q_base * q_scale)

    def update(self, x: float, y: float) -> None:
        z = np.array([float(x), float(y)], dtype=np.float64)
        y_vec = z - (self.H @ self.state)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y_vec
        self.P = (np.eye(4, dtype=np.float64) - K @ self.H) @ self.P

    @property
    def center(self) -> tuple[float, float]:
        return float(self.state[0]), float(self.state[1])


@dataclass
class _LiveGroundTrack:
    track_id: int
    bbox: tuple[int, int, int, int]
    center_px: tuple[float, float]
    score: float
    first_seen_ts: float
    last_seen_ts: float
    kalman: _CartesianKalman
    hit_count: int = 1
    coast_count: int = 0
    matched_this_tick: bool = True
    confirmed_real: bool = False
    ghost: bool = False
    angle_rad: float | None = None
    radius_px: float | None = None
    path: list[tuple[float, float, float]] = field(default_factory=list)
    rotation_samples: list[tuple[float, float, float]] = field(default_factory=list)


@register_tracker("turntable_groundplane")
class TurntableGroundplaneTracker:
    """Rotation-aware cartesian tracker for shadow-mode comparison."""

    key = "turntable_groundplane"

    def __init__(
        self,
        polar_center: tuple[float, float] | None = None,
        polar_radius_range: tuple[float, float] | None = None,
        max_step_px: float = 120.0,
        max_angular_step_deg: float = 55.0,
        max_radial_step_px: float = 70.0,
        duplicate_merge_distance_px: float = 28.0,
        duplicate_merge_iou: float = 0.55,
        min_hits: int = 3,
        coast_limit_ticks: int = 8,
        detection_score_threshold: float = 0.0,
        omega_ema_alpha: float = 0.85,
    ) -> None:
        if polar_center is not None:
            self._polar_center: tuple[float, float] | None = (
                float(polar_center[0]),
                float(polar_center[1]),
            )
        else:
            self._polar_center = None
        self._polar_radius_range = polar_radius_range
        self._max_step_px = float(max_step_px)
        self._max_angular_step = math.radians(float(max_angular_step_deg))
        self._max_radial_step = float(max_radial_step_px)
        self._duplicate_merge_distance_px = float(duplicate_merge_distance_px)
        self._duplicate_merge_iou = float(duplicate_merge_iou)
        self._min_hits = max(1, int(min_hits))
        self._coast_limit = max(0, int(coast_limit_ticks))
        self._score_threshold = float(detection_score_threshold)
        self._omega_ema_alpha = min(0.99, max(0.0, float(omega_ema_alpha)))
        self._omega_rad_s: float | None = None
        self._tracks: dict[int, _LiveGroundTrack] = {}
        self._next_track_id = 1
        self._last_ts: float | None = None
        self._rotation_windows: deque[tuple[float, float]] = deque(
            maxlen=_ROTATION_WINDOW_BUFFER
        )
        self._lock = threading.RLock()

    # ---- Geometry -----------------------------------------------------

    def _to_polar(self, center_px: tuple[float, float]) -> tuple[float, float]:
        assert self._polar_center is not None
        dx = float(center_px[0]) - self._polar_center[0]
        dy = float(center_px[1]) - self._polar_center[1]
        return math.atan2(dy, dx), math.hypot(dx, dy)

    def _polar_or_none(
        self,
        center_px: tuple[float, float],
    ) -> tuple[float | None, float | None]:
        if self._polar_center is None:
            return None, None
        return self._to_polar(center_px)

    def _in_rotation_window(self, ts: float) -> bool:
        return any(start <= ts <= end for start, end in self._rotation_windows)

    def _rotation_prior_for_ts(self, ts: float) -> float | None:
        if self._polar_center is None or self._omega_rad_s is None:
            return None
        if not self._in_rotation_window(ts):
            return None
        return self._omega_rad_s

    # ---- Public API ---------------------------------------------------

    def register_rotation_window(self, start_ts: float, end_ts: float) -> None:
        if not (end_ts > start_ts):
            return
        with self._lock:
            self._rotation_windows.append((float(start_ts), float(end_ts)))
            if self._last_ts is not None:
                cutoff = float(self._last_ts) - _ROTATION_WINDOW_MAX_AGE_S
                while self._rotation_windows and self._rotation_windows[0][1] < cutoff:
                    self._rotation_windows.popleft()

    def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch:
        with self._lock:
            return self._update_locked(detections, frame)

    def _update_locked(
        self,
        detections: DetectionBatch,
        frame: FeedFrame,
    ) -> TrackBatch:
        timestamp = frame.timestamp if frame.timestamp > 0 else time.time()
        dt = 0.2 if self._last_ts is None else max(0.0, timestamp - self._last_ts)
        self._last_ts = timestamp

        prior = self._rotation_prior_for_ts(timestamp)
        for track in self._tracks.values():
            track.matched_this_tick = False
            track.kalman.predict(dt, omega_rad_s=prior, pivot=self._polar_center)

        filtered: list[tuple[tuple[int, int, int, int], float]] = []
        for det in detections.detections:
            score = float(det.score)
            if score < self._score_threshold:
                continue
            bbox = tuple(int(v) for v in det.bbox_xyxy)
            filtered.append((bbox, score))

        track_ids = list(self._tracks.keys())
        matched_tids: set[int] = set()
        matched_det_indices: set[int] = set()
        if track_ids and filtered:
            self._assign(track_ids, filtered, matched_tids, matched_det_indices, timestamp)

        lost_ids: list[int] = []
        for tid, track in list(self._tracks.items()):
            if tid in matched_tids:
                continue
            track.coast_count += 1
            if track.coast_count > self._coast_limit:
                self._tracks.pop(tid)
                lost_ids.append(tid)

        for idx, (bbox, score) in enumerate(filtered):
            if idx in matched_det_indices:
                continue
            self._spawn_track(bbox, score, timestamp)

        self._merge_duplicates(lost_ids)

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

    def _spawn_track(
        self,
        bbox: tuple[int, int, int, int],
        score: float,
        timestamp: float,
    ) -> None:
        cx, cy = _bbox_center(bbox)
        angle, radius = self._polar_or_none((cx, cy))
        tid = self._next_track_id
        self._next_track_id += 1
        self._tracks[tid] = _LiveGroundTrack(
            track_id=tid,
            bbox=bbox,
            center_px=(cx, cy),
            score=float(score),
            first_seen_ts=float(timestamp),
            last_seen_ts=float(timestamp),
            kalman=_CartesianKalman(cx, cy),
            angle_rad=angle,
            radius_px=radius,
            path=[(float(timestamp), float(cx), float(cy))],
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
        det_centers = [_bbox_center(bbox) for bbox, _score in filtered]
        det_polar: list[tuple[float, float]] = []
        if self._polar_center is not None:
            det_polar = [self._to_polar(center) for center in det_centers]

        for ri, tid in enumerate(track_ids):
            track = self._tracks[tid]
            pred_center = track.kalman.center
            pred_angle: float | None = None
            pred_radius: float | None = None
            if self._polar_center is not None:
                pred_angle, pred_radius = self._to_polar(pred_center)
            for ci, det_center in enumerate(det_centers):
                pixel_dist = math.hypot(
                    float(det_center[0]) - pred_center[0],
                    float(det_center[1]) - pred_center[1],
                )
                pixel_cost = pixel_dist / self._max_step_px
                if pixel_cost >= 1.0:
                    continue
                if self._polar_center is None or pred_angle is None or pred_radius is None:
                    cost[ri, ci] = pixel_cost
                    continue
                det_angle, det_radius = det_polar[ci]
                angular_delta = _circular_diff(det_angle, pred_angle)
                angular_cost = abs(angular_delta) / self._max_angular_step
                radial_cost = abs(det_radius - pred_radius) / self._max_radial_step
                if angular_cost >= 1.0 or radial_cost >= 1.0:
                    continue
                value = 0.55 * pixel_cost + 0.30 * angular_cost + 0.15 * radial_cost
                if self._omega_rad_s is not None and abs(self._omega_rad_s) > 1e-4:
                    if math.copysign(1.0, angular_delta) != math.copysign(1.0, self._omega_rad_s):
                        value *= 1.2
                cost[ri, ci] = value

        row_ind, col_ind = linear_sum_assignment(cost)
        for row, col in zip(row_ind, col_ind):
            if cost[row, col] >= large:
                continue
            tid = track_ids[int(row)]
            matched_tids.add(tid)
            matched_det_indices.add(int(col))
            bbox, score = filtered[int(col)]
            self._update_track(self._tracks[tid], bbox, score, timestamp)

    def _update_track(
        self,
        track: _LiveGroundTrack,
        bbox: tuple[int, int, int, int],
        score: float,
        timestamp: float,
    ) -> None:
        previous_ts = float(track.last_seen_ts)
        previous_center = track.center_px
        previous_angle = track.angle_rad
        cx, cy = _bbox_center(bbox)
        track.kalman.update(cx, cy)
        angle, radius = self._polar_or_none((cx, cy))
        if (
            self._polar_center is not None
            and previous_angle is not None
            and angle is not None
            and timestamp > previous_ts
            and self._in_rotation_window(float(timestamp))
        ):
            omega = _circular_diff(angle, previous_angle) / (float(timestamp) - previous_ts)
            if abs(omega) > 1e-4 and math.isfinite(omega):
                if self._omega_rad_s is None:
                    self._omega_rad_s = float(omega)
                else:
                    alpha = self._omega_ema_alpha
                    self._omega_rad_s = alpha * self._omega_rad_s + (1.0 - alpha) * float(omega)

        dt = max(1e-3, float(timestamp) - previous_ts)
        track.kalman.state[2] = (float(cx) - float(previous_center[0])) / dt
        track.kalman.state[3] = (float(cy) - float(previous_center[1])) / dt
        track.bbox = bbox
        track.center_px = (cx, cy)
        track.score = float(score)
        track.hit_count += 1
        track.coast_count = 0
        track.matched_this_tick = True
        track.last_seen_ts = float(timestamp)
        track.angle_rad = angle
        track.radius_px = radius
        track.path.append((float(timestamp), float(cx), float(cy)))
        if len(track.path) > 32:
            del track.path[: -32]
        if self._in_rotation_window(float(timestamp)):
            sample = (float(timestamp), float(cx), float(cy))
            track.rotation_samples.append(sample)
            if len(track.rotation_samples) > _ROTATION_SAMPLES_MAX:
                del track.rotation_samples[: -_ROTATION_SAMPLES_MAX]
            window = track.rotation_samples[-_VERDICT_WINDOW_SAMPLES:]
            if self._evaluate_confirmed_real_samples(window):
                track.confirmed_real = True
                track.ghost = False
            else:
                track.confirmed_real = False
                track.ghost = len(window) >= _GHOST_WINDOW_MIN_SAMPLES

    def _merge_duplicates(self, lost_ids: list[int]) -> None:
        ids = sorted(self._tracks)
        dropped: set[int] = set()
        for i, left_id in enumerate(ids):
            if left_id in dropped or left_id not in self._tracks:
                continue
            left = self._tracks[left_id]
            for right_id in ids[i + 1:]:
                if right_id in dropped or right_id not in self._tracks:
                    continue
                right = self._tracks[right_id]
                dist = math.hypot(
                    float(left.center_px[0]) - float(right.center_px[0]),
                    float(left.center_px[1]) - float(right.center_px[1]),
                )
                too_far = dist > self._duplicate_merge_distance_px
                low_overlap = _bbox_iou(left.bbox, right.bbox) < self._duplicate_merge_iou
                if too_far and low_overlap:
                    continue
                keep, drop = self._choose_duplicate_survivor(left, right)
                if drop.track_id == keep.track_id:
                    continue
                self._fold_duplicate_evidence(keep, drop)
                self._tracks.pop(drop.track_id, None)
                dropped.add(drop.track_id)
                lost_ids.append(drop.track_id)

    def _fold_duplicate_evidence(
        self,
        keep: _LiveGroundTrack,
        drop: _LiveGroundTrack,
    ) -> None:
        keep.hit_count = max(int(keep.hit_count), int(drop.hit_count))
        keep.path = sorted(
            keep.path + drop.path,
            key=lambda sample: sample[0],
        )[-32:]
        merged_rotation_samples = sorted(
            keep.rotation_samples + drop.rotation_samples,
            key=lambda sample: sample[0],
        )[-_ROTATION_SAMPLES_MAX:]
        keep.rotation_samples = merged_rotation_samples
        if drop.confirmed_real:
            keep.confirmed_real = True
            keep.ghost = False
        elif drop.ghost and not keep.confirmed_real:
            keep.ghost = True

    def _choose_duplicate_survivor(
        self,
        left: _LiveGroundTrack,
        right: _LiveGroundTrack,
    ) -> tuple[_LiveGroundTrack, _LiveGroundTrack]:
        left_key = (
            int(left.matched_this_tick),
            int(left.hit_count),
            -int(left.coast_count),
            float(left.score),
            -int(left.track_id),
        )
        right_key = (
            int(right.matched_this_tick),
            int(right.hit_count),
            -int(right.coast_count),
            float(right.score),
            -int(right.track_id),
        )
        if right_key > left_key:
            return right, left
        return left, right

    def _evaluate_confirmed_real_samples(
        self,
        samples: list[tuple[float, float, float]],
    ) -> bool:
        if len(samples) < _CONFIRMED_WINDOW_MIN_SAMPLES:
            return False

        third = max(2, len(samples) // 3)
        head = samples[:third]
        tail = samples[-third:]
        head_x = sorted(float(s[1]) for s in head)[len(head) // 2]
        head_y = sorted(float(s[2]) for s in head)[len(head) // 2]
        tail_x = sorted(float(s[1]) for s in tail)[len(tail) // 2]
        tail_y = sorted(float(s[2]) for s in tail)[len(tail) // 2]
        if math.hypot(tail_x - head_x, tail_y - head_y) >= (
            _CONFIRMED_MIN_CENTROID_DRIFT_PX
        ):
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
        for idx in range(1, len(unwrapped)):
            step = (unwrapped[idx] - unwrapped[idx - 1]) * direction
            if step < -reversal_tol:
                return False
        return True

    def observed_rpm(self) -> float | None:
        with self._lock:
            if self._omega_rad_s is None:
                return None
            return abs(float(self._omega_rad_s)) / (2.0 * math.pi) * 60.0

    def ring_geometry(self) -> dict[str, float] | None:
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
            return {track.track_id for track in self._tracks.values()}

    def reset(self) -> None:
        with self._lock:
            self._tracks.clear()
            self._rotation_windows.clear()
            self._last_ts = None
            self._next_track_id = 1
            self._omega_rad_s = None


__all__ = ["TurntableGroundplaneTracker"]
