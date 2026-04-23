"""Adapters for the Apache-2.0 Roboflow `trackers` package.

These trackers are intentionally thin benchmark candidates: the Roboflow
implementations own association, while this adapter keeps the sorter runtime
contract stable by adding polar geometry, local IDs, and the same
rotation-window ghost/real verdict used by the native trackers.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
import supervision as sv
from trackers import ByteTrackTracker, OCSORTTracker, SORTTracker

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


def _clip_bbox(values: Iterable[float]) -> tuple[int, int, int, int]:
    raw = [float(v) for v in values]
    if len(raw) != 4:
        return (0, 0, 0, 0)
    x1, y1, x2, y2 = raw
    if not all(math.isfinite(v) for v in raw):
        return (0, 0, 0, 0)
    x1_i = int(round(min(x1, x2)))
    y1_i = int(round(min(y1, y2)))
    x2_i = int(round(max(x1, x2)))
    y2_i = int(round(max(y1, y2)))
    return (x1_i, y1_i, x2_i, y2_i)


@dataclass
class _AdapterTrackState:
    local_id: int
    first_seen_ts: float
    last_seen_ts: float
    hit_count: int = 0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    score: float = 0.0
    confirmed_real: bool = False
    ghost: bool = False
    angle_rad: float | None = None
    radius_px: float | None = None
    rotation_samples: list[tuple[float, float, float]] = field(default_factory=list)


class _RoboflowTrackerAdapter:
    key = "rf_base"

    def __init__(
        self,
        *,
        polar_center: tuple[float, float] | None = None,
        polar_radius_range: tuple[float, float] | None = None,
        detection_score_threshold: float = 0.0,
        emit_coasting_tracks: bool = True,
    ) -> None:
        if polar_center is not None:
            self._polar_center: tuple[float, float] | None = (
                float(polar_center[0]),
                float(polar_center[1]),
            )
        else:
            self._polar_center = None
        self._polar_radius_range = polar_radius_range
        self._score_threshold = float(detection_score_threshold)
        self._emit_coasting_tracks = bool(emit_coasting_tracks)
        self._core = self._make_core()
        self._external_to_local: dict[int, int] = {}
        self._states: dict[int, _AdapterTrackState] = {}
        self._next_local_id = 1
        self._last_ts: float | None = None
        self._rotation_windows: deque[tuple[float, float]] = deque(
            maxlen=_ROTATION_WINDOW_BUFFER
        )
        self._lock = threading.RLock()

    def _make_core(self) -> Any:
        raise NotImplementedError

    def _core_tracks(self) -> list[Any]:
        if hasattr(self._core, "tracks"):
            value = getattr(self._core, "tracks")
        elif hasattr(self._core, "trackers"):
            value = getattr(self._core, "trackers")
        else:
            value = []
        return list(value or [])

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

    def register_rotation_window(self, start_ts: float, end_ts: float) -> None:
        if not (end_ts > start_ts):
            return
        with self._lock:
            self._rotation_windows.append((float(start_ts), float(end_ts)))
            if self._last_ts is not None:
                cutoff = float(self._last_ts) - _ROTATION_WINDOW_MAX_AGE_S
                while self._rotation_windows and self._rotation_windows[0][1] < cutoff:
                    self._rotation_windows.popleft()

    def _in_rotation_window(self, ts: float) -> bool:
        return any(start <= ts <= end for start, end in self._rotation_windows)

    def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch:
        with self._lock:
            return self._update_locked(detections, frame)

    def _update_locked(
        self,
        detections: DetectionBatch,
        frame: FeedFrame,
    ) -> TrackBatch:
        timestamp = frame.timestamp if frame.timestamp > 0 else time.time()
        self._last_ts = timestamp
        previous_active_locals = set(self._states)

        sv_detections = self._to_supervision(detections)
        tracked = self._core.update(sv_detections)
        matched = self._matched_tracker_payloads(tracked)

        current_external_ids: set[int] = set()
        output: list[Track] = []
        for core_track in self._core_tracks():
            external_id = self._external_id(core_track)
            if external_id is None:
                continue
            if not self._emit_coasting_tracks and external_id not in matched:
                continue
            current_external_ids.add(external_id)
            local_id = self._local_id_for_external(external_id)
            state = self._states.get(local_id)
            if state is None:
                state = _AdapterTrackState(
                    local_id=local_id,
                    first_seen_ts=float(timestamp),
                    last_seen_ts=float(timestamp),
                )
                self._states[local_id] = state
            bbox = self._core_bbox(core_track)
            score = matched.get(external_id, (state.score, bbox))[0]
            observed_bbox = matched.get(external_id, (score, bbox))[1]
            observed = external_id in matched
            self._update_state(
                state,
                bbox=bbox,
                observed_bbox=observed_bbox,
                score=float(score),
                timestamp=float(timestamp),
                observed=observed,
            )
            output.append(self._to_track(state))

        active_locals = {
            self._external_to_local[external_id]
            for external_id in current_external_ids
            if external_id in self._external_to_local
        }
        lost_ids = tuple(sorted(previous_active_locals - active_locals))
        for local_id in lost_ids:
            self._states.pop(local_id, None)

        return TrackBatch(
            feed_id=detections.feed_id,
            frame_seq=detections.frame_seq,
            timestamp=float(timestamp),
            tracks=tuple(output),
            lost_track_ids=lost_ids,
        )

    def _to_supervision(self, detections: DetectionBatch) -> sv.Detections:
        boxes: list[tuple[int, int, int, int]] = []
        scores: list[float] = []
        for det in detections.detections:
            score = float(det.score)
            if score < self._score_threshold:
                continue
            boxes.append(tuple(int(v) for v in det.bbox_xyxy))
            scores.append(score)
        if not boxes:
            return sv.Detections.empty()
        return sv.Detections(
            xyxy=np.asarray(boxes, dtype=np.float32),
            confidence=np.asarray(scores, dtype=np.float32),
        )

    def _matched_tracker_payloads(
        self,
        tracked: sv.Detections,
    ) -> dict[int, tuple[float, tuple[int, int, int, int]]]:
        tracker_ids = getattr(tracked, "tracker_id", None)
        if tracker_ids is None:
            return {}
        confidences = tracked.confidence
        if confidences is None:
            confidences = np.zeros(len(tracked), dtype=np.float32)
        out: dict[int, tuple[float, tuple[int, int, int, int]]] = {}
        for idx, raw_id in enumerate(tracker_ids):
            external_id = int(raw_id)
            if external_id < 0:
                continue
            bbox = _clip_bbox(tracked.xyxy[idx])
            score = float(confidences[idx]) if idx < len(confidences) else 0.0
            out[external_id] = (score, bbox)
        return out

    def _external_id(self, core_track: Any) -> int | None:
        raw = getattr(core_track, "tracker_id", -1)
        try:
            external_id = int(raw)
        except Exception:
            return None
        return external_id if external_id >= 0 else None

    def _core_bbox(self, core_track: Any) -> tuple[int, int, int, int]:
        getter = getattr(core_track, "get_state_bbox", None)
        if callable(getter):
            try:
                return _clip_bbox(getter())
            except Exception:
                pass
        last = getattr(core_track, "last_observation", None)
        if last is not None:
            try:
                return _clip_bbox(last)
            except Exception:
                pass
        state = getattr(core_track, "state", None)
        if state is not None:
            try:
                arr = np.asarray(state).reshape(-1)
                return _clip_bbox(arr[:4])
            except Exception:
                pass
        return (0, 0, 0, 0)

    def _local_id_for_external(self, external_id: int) -> int:
        local_id = self._external_to_local.get(external_id)
        if local_id is not None:
            return local_id
        local_id = self._next_local_id
        self._next_local_id += 1
        self._external_to_local[external_id] = local_id
        return local_id

    def _update_state(
        self,
        state: _AdapterTrackState,
        *,
        bbox: tuple[int, int, int, int],
        observed_bbox: tuple[int, int, int, int],
        score: float,
        timestamp: float,
        observed: bool,
    ) -> None:
        state.bbox = bbox
        state.score = score
        cx, cy = _bbox_center(observed_bbox if observed else bbox)
        angle, radius = self._polar_or_none((cx, cy))
        state.angle_rad = angle
        state.radius_px = radius
        if observed:
            state.hit_count += 1
            state.last_seen_ts = float(timestamp)
            if self._in_rotation_window(float(timestamp)):
                sample = (float(timestamp), float(cx), float(cy))
                state.rotation_samples.append(sample)
                if len(state.rotation_samples) > _ROTATION_SAMPLES_MAX:
                    del state.rotation_samples[: -_ROTATION_SAMPLES_MAX]
                window = state.rotation_samples[-_VERDICT_WINDOW_SAMPLES:]
                if self._evaluate_confirmed_real_samples(window):
                    state.confirmed_real = True
                    state.ghost = False
                else:
                    state.confirmed_real = False
                    state.ghost = len(window) >= _GHOST_WINDOW_MIN_SAMPLES

    def _to_track(self, state: _AdapterTrackState) -> Track:
        return Track(
            track_id=state.local_id,
            global_id=state.local_id,
            piece_uuid=None,
            bbox_xyxy=state.bbox,
            score=float(state.score),
            confirmed_real=bool(state.confirmed_real),
            angle_rad=state.angle_rad,
            radius_px=state.radius_px,
            hit_count=int(state.hit_count),
            first_seen_ts=float(state.first_seen_ts),
            last_seen_ts=float(state.last_seen_ts),
            ghost=bool(state.ghost),
        )

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
        if (
            math.hypot(tail_x - head_x, tail_y - head_y)
            >= _CONFIRMED_MIN_CENTROID_DRIFT_PX
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
        if self._polar_center is None:
            return None
        with self._lock:
            best_rpm: float | None = None
            for state in self._states.values():
                if not state.confirmed_real:
                    continue
                samples = state.rotation_samples
                if len(samples) < 4:
                    continue
                recent = samples[-8:]
                ts_start = float(recent[0][0])
                ts_end = float(recent[-1][0])
                dt_s = ts_end - ts_start
                if dt_s <= 0.0:
                    continue
                anchor, _ = self._to_polar((float(recent[0][1]), float(recent[0][2])))
                accum = 0.0
                for _ts, x, y in recent[1:]:
                    angle, _ = self._to_polar((float(x), float(y)))
                    accum += _circular_diff(angle, anchor)
                    anchor = angle
                rpm = abs(accum) / (2.0 * math.pi) / dt_s * 60.0
                if best_rpm is None or rpm > best_rpm:
                    best_rpm = rpm
            return best_rpm

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
            return set(self._states)

    def reset(self) -> None:
        with self._lock:
            self._core = self._make_core()
            self._external_to_local.clear()
            self._states.clear()
            self._next_local_id = 1
            self._rotation_windows.clear()
            self._last_ts = None


@register_tracker("rf_sort")
class RoboflowSORTTracker(_RoboflowTrackerAdapter):
    """SORT via roboflow/trackers."""

    key = "rf_sort"

    def __init__(
        self,
        *,
        lost_track_buffer: int = 8,
        frame_rate: float = 30.0,
        track_activation_threshold: float = 0.55,
        minimum_consecutive_frames: int = 1,
        minimum_iou_threshold: float = 0.1,
        **kwargs: Any,
    ) -> None:
        self._factory: Callable[[], Any] = lambda: SORTTracker(
            lost_track_buffer=int(lost_track_buffer),
            frame_rate=float(frame_rate),
            track_activation_threshold=float(track_activation_threshold),
            minimum_consecutive_frames=int(minimum_consecutive_frames),
            minimum_iou_threshold=float(minimum_iou_threshold),
        )
        super().__init__(**kwargs)

    def _make_core(self) -> Any:
        return self._factory()


@register_tracker("rf_bytetrack")
class RoboflowByteTrackTracker(_RoboflowTrackerAdapter):
    """ByteTrack via roboflow/trackers."""

    key = "rf_bytetrack"

    def __init__(
        self,
        *,
        lost_track_buffer: int = 8,
        frame_rate: float = 30.0,
        track_activation_threshold: float = 0.55,
        minimum_consecutive_frames: int = 1,
        minimum_iou_threshold: float = 0.1,
        high_conf_det_threshold: float = 0.5,
        **kwargs: Any,
    ) -> None:
        self._factory: Callable[[], Any] = lambda: ByteTrackTracker(
            lost_track_buffer=int(lost_track_buffer),
            frame_rate=float(frame_rate),
            track_activation_threshold=float(track_activation_threshold),
            minimum_consecutive_frames=int(minimum_consecutive_frames),
            minimum_iou_threshold=float(minimum_iou_threshold),
            high_conf_det_threshold=float(high_conf_det_threshold),
        )
        super().__init__(**kwargs)

    def _make_core(self) -> Any:
        return self._factory()


@register_tracker("rf_ocsort")
class RoboflowOCSORTTracker(_RoboflowTrackerAdapter):
    """OC-SORT via roboflow/trackers."""

    key = "rf_ocsort"

    def __init__(
        self,
        *,
        lost_track_buffer: int = 8,
        frame_rate: float = 30.0,
        minimum_consecutive_frames: int = 1,
        minimum_iou_threshold: float = 0.1,
        direction_consistency_weight: float = 0.2,
        high_conf_det_threshold: float = 0.5,
        delta_t: int = 3,
        **kwargs: Any,
    ) -> None:
        self._factory: Callable[[], Any] = lambda: OCSORTTracker(
            lost_track_buffer=int(lost_track_buffer),
            frame_rate=float(frame_rate),
            minimum_consecutive_frames=int(minimum_consecutive_frames),
            minimum_iou_threshold=float(minimum_iou_threshold),
            direction_consistency_weight=float(direction_consistency_weight),
            high_conf_det_threshold=float(high_conf_det_threshold),
            delta_t=int(delta_t),
        )
        super().__init__(**kwargs)

    def _make_core(self) -> Any:
        return self._factory()


__all__ = [
    "RoboflowSORTTracker",
    "RoboflowByteTrackTracker",
    "RoboflowOCSORTTracker",
]
