"""BoTSORT + OSNet Re-Identification adapter.

This is the production ReID shadow tracker for the sorter. BoxMot ByteTrack
owns the primary motion tracklets; BoTSORT pairs a Kalman motion model with an
OSNet appearance model so the perception runner can enrich primary tracks with
embeddings for C3→C4 handoff and short tracklet stitching.

The adapter keeps the existing sorter contract intact:

- Emits ``Track`` objects with our polar geometry (angle_rad / radius_px),
  local IDs, and the rotation-window ghost/real verdict used by every other
  tracker adapter. Everything downstream keeps working unchanged.
- Publishes each track's appearance embedding on ``Track.appearance_embedding``
  so the track_transit registry can use cosine similarity as a cross-channel
  re-identification gate (C3 → C4 handoff).

ReID weights are auto-downloaded by boxmot on first use and cached under
``blob/reid_models/``. If boxmot/torch or network access is unavailable the
adapter raises on construction — callers are expected to pick a different
tracker key rather than silently degrade.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from blob_manager import BLOB_DIR
from rt.contracts.detection import DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import register_tracker
from rt.contracts.tracking import Track, TrackBatch
from rt.perception.trackers._geometry import (
    bbox_center as _bbox_center,
    circular_diff as _circular_diff,
    clip_bbox as _clip_bbox,
)


_LOG = logging.getLogger(__name__)

# Rotation-window / ghost verdict constants — mirrored from the other adapter
# families so the verdict stays comparable in shadow mode.
_ROTATION_WINDOW_BUFFER = 128
_ROTATION_WINDOW_MAX_AGE_S = 60.0
_CONFIRMED_MIN_ANGULAR_PROGRESS_DEG = 5.0
_CONFIRMED_REVERSAL_TOLERANCE_DEG = 4.0
_CONFIRMED_MIN_CENTROID_DRIFT_PX = 40.0
_CONFIRMED_WINDOW_MIN_SAMPLES = 6
_GHOST_WINDOW_MIN_SAMPLES = 18
_VERDICT_WINDOW_SAMPLES = 18
_ROTATION_SAMPLES_MAX = 64

DEFAULT_REID_MODEL = "osnet_x0_25_msmt17.pt"
REID_CACHE_DIR = BLOB_DIR / "reid_models"


@dataclass
class _BoxmotTrackState:
    """Per-track state owned by the adapter (not boxmot)."""

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
    appearance_embedding: tuple[float, ...] | None = None


class _CoreProtocol:
    """Minimal protocol our adapter expects from the BoTSORT-ish core.

    Kept as a duck-typed docstring rather than a formal ``typing.Protocol`` so
    the real boxmot BoTSORT class satisfies it without runtime checks, and
    tests can inject a plain Python fake.
    """

    # update(dets: np.ndarray(N,6), img: np.ndarray(H,W,3)) -> np.ndarray(M,8)
    #   columns: x1, y1, x2, y2, track_id, conf, cls, det_idx
    # tracked_stracks: iterable of objects with:
    #   .track_id (int), .smooth_feat (np.ndarray | None), .curr_feat (np.ndarray | None)


@register_tracker("botsort_reid")
class BotSortReIDTracker:
    """BoTSORT with OSNet ReID, wrapped to emit sorter-native tracks."""

    key = "botsort_reid"

    def __init__(
        self,
        *,
        polar_center: tuple[float, float] | None = None,
        polar_radius_range: tuple[float, float] | None = None,
        detection_score_threshold: float = 0.0,
        track_high_thresh: float = 0.5,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.6,
        track_buffer: int = 45,
        match_thresh: float = 0.8,
        proximity_thresh: float = 0.5,
        appearance_thresh: float = 0.25,
        frame_rate: int = 10,
        with_reid: bool = True,
        reid_model: str = DEFAULT_REID_MODEL,
        reid_cache_dir: str | Path | None = None,
        device: str | None = None,
        half: bool = False,
        core_factory: Callable[[], Any] | None = None,
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

        self._track_high_thresh = float(track_high_thresh)
        self._track_low_thresh = float(track_low_thresh)
        self._new_track_thresh = float(new_track_thresh)
        self._track_buffer = int(track_buffer)
        self._match_thresh = float(match_thresh)
        self._proximity_thresh = float(proximity_thresh)
        self._appearance_thresh = float(appearance_thresh)
        self._frame_rate = int(frame_rate)
        self._with_reid = bool(with_reid)
        self._half = bool(half)
        self._reid_model = str(reid_model)
        self._reid_cache_dir = Path(reid_cache_dir) if reid_cache_dir else REID_CACHE_DIR
        self._device_str = device

        self._core_factory = core_factory or self._default_core_factory
        self._core: Any | None = None

        self._external_to_local: dict[int, int] = {}
        self._states: dict[int, _BoxmotTrackState] = {}
        self._next_local_id = 1
        self._last_ts: float | None = None
        self._rotation_windows: deque[tuple[float, float]] = deque(
            maxlen=_ROTATION_WINDOW_BUFFER
        )
        self._lock = threading.RLock()

    # ---- Boxmot core factory (lazy, separated for tests) -----------------

    def _default_core_factory(self) -> Any:
        """Build the real boxmot BoTSORT tracker. Deferred until first update."""

        try:
            import torch
            from boxmot.trackers.botsort.botsort import BotSort
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "botsort_reid requires boxmot + torch; install them or pick "
                "another tracker key"
            ) from exc

        weights_path = self._resolve_reid_weights()
        device = torch.device(self._device_str or _select_torch_device())
        return BotSort(
            reid_weights=weights_path,
            device=device,
            half=self._half,
            track_high_thresh=self._track_high_thresh,
            track_low_thresh=self._track_low_thresh,
            new_track_thresh=self._new_track_thresh,
            track_buffer=self._track_buffer,
            match_thresh=self._match_thresh,
            proximity_thresh=self._proximity_thresh,
            appearance_thresh=self._appearance_thresh,
            frame_rate=self._frame_rate,
            with_reid=self._with_reid,
        )

    def _resolve_reid_weights(self) -> Path:
        self._reid_cache_dir.mkdir(parents=True, exist_ok=True)
        weights = self._reid_cache_dir / self._reid_model
        if weights.exists():
            return weights
        # boxmot's BotSort will fetch the weight on construction using its
        # own downloader (see boxmot.utils.checks). We only need to hand it a
        # path under our cache directory — boxmot writes there if missing.
        return weights

    # ---- Public API ------------------------------------------------------

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

    def live_global_ids(self) -> set[int]:
        with self._lock:
            return set(self._states)

    def reset(self) -> None:
        with self._lock:
            self._core = None
            self._external_to_local.clear()
            self._states.clear()
            self._next_local_id = 1
            self._rotation_windows.clear()
            self._last_ts = None

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

    # ---- Internals -------------------------------------------------------

    def _ensure_core(self) -> Any:
        if self._core is None:
            self._core = self._core_factory()
        return self._core

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

    def _update_locked(
        self,
        detections: DetectionBatch,
        frame: FeedFrame,
    ) -> TrackBatch:
        timestamp = frame.timestamp if frame.timestamp > 0 else time.time()
        self._last_ts = timestamp
        previous_active_locals = set(self._states)

        dets_np = self._detections_to_numpy(detections)
        image = self._frame_image(frame)
        core = self._ensure_core()
        try:
            tracked = core.update(dets_np, image)
        except Exception:
            _LOG.exception("botsort_reid update raised — returning empty batch")
            tracked = np.empty((0, 8), dtype=np.float32)

        # Map external id → smooth feature vector from boxmot's internal STracks
        id_to_feat = _collect_track_features(core)

        current_external_ids: set[int] = set()
        output: list[Track] = []
        rows = np.atleast_2d(np.asarray(tracked, dtype=np.float32))
        if rows.size == 0 or rows.shape[-1] < 7:
            rows = np.empty((0, 8), dtype=np.float32)

        for row in rows:
            external_id = int(row[4])
            if external_id < 0:
                continue
            current_external_ids.add(external_id)
            bbox = _clip_bbox(row[:4])
            score = float(row[5])
            local_id = self._local_id_for_external(external_id)
            state = self._states.get(local_id)
            if state is None:
                state = _BoxmotTrackState(
                    local_id=local_id,
                    first_seen_ts=float(timestamp),
                    last_seen_ts=float(timestamp),
                )
                self._states[local_id] = state
            embedding = id_to_feat.get(external_id)
            self._apply_observation(
                state,
                bbox=bbox,
                score=score,
                timestamp=float(timestamp),
                embedding=embedding,
            )
            output.append(self._to_track(state))

        active_locals = {
            self._external_to_local[eid]
            for eid in current_external_ids
            if eid in self._external_to_local
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

    def _detections_to_numpy(self, detections: DetectionBatch) -> np.ndarray:
        rows: list[tuple[float, float, float, float, float, float]] = []
        for det in detections.detections:
            score = float(det.score)
            if score < self._score_threshold:
                continue
            x1, y1, x2, y2 = (float(v) for v in det.bbox_xyxy)
            rows.append((x1, y1, x2, y2, score, 0.0))
        if not rows:
            return np.empty((0, 6), dtype=np.float32)
        return np.asarray(rows, dtype=np.float32)

    def _frame_image(self, frame: FeedFrame) -> np.ndarray:
        image = getattr(frame, "raw", None)
        if image is None:
            # BoTSORT's GMC + ReID both need a frame. Fall back to a small black
            # image so at least motion-only association still works.
            return np.zeros((64, 64, 3), dtype=np.uint8)
        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        return arr

    def _local_id_for_external(self, external_id: int) -> int:
        local_id = self._external_to_local.get(external_id)
        if local_id is not None:
            return local_id
        local_id = self._next_local_id
        self._next_local_id += 1
        self._external_to_local[external_id] = local_id
        return local_id

    def _apply_observation(
        self,
        state: _BoxmotTrackState,
        *,
        bbox: tuple[int, int, int, int],
        score: float,
        timestamp: float,
        embedding: tuple[float, ...] | None,
    ) -> None:
        state.bbox = bbox
        state.score = score
        cx, cy = _bbox_center(bbox)
        angle, radius = self._polar_or_none((cx, cy))
        state.angle_rad = angle
        state.radius_px = radius
        state.hit_count += 1
        state.last_seen_ts = float(timestamp)
        if embedding is not None:
            state.appearance_embedding = embedding

        if self._in_rotation_window(float(timestamp)):
            sample = (float(timestamp), float(cx), float(cy))
            state.rotation_samples.append(sample)
            if len(state.rotation_samples) > _ROTATION_SAMPLES_MAX:
                del state.rotation_samples[:-_ROTATION_SAMPLES_MAX]
            window = state.rotation_samples[-_VERDICT_WINDOW_SAMPLES:]
            if self._evaluate_confirmed_real(window):
                state.confirmed_real = True
                state.ghost = False
            elif not state.confirmed_real:
                state.confirmed_real = False
                state.ghost = len(window) >= _GHOST_WINDOW_MIN_SAMPLES

    def _evaluate_confirmed_real(
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

    def _to_track(self, state: _BoxmotTrackState) -> Track:
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
            appearance_embedding=state.appearance_embedding,
        )


def _collect_track_features(core: Any) -> dict[int, tuple[float, ...]]:
    """Pull smooth appearance embeddings out of boxmot's active STracks.

    BoTSORT's ``STrack.id`` is the same integer that shows up in row[4] of
    ``tracker.update()``'s output — ``track_id`` on a ``BaseTrack`` is just the
    class-level default ``0`` and is NOT the externally visible ID. Test doubles
    use ``track_id`` explicitly, so we accept either attribute.
    """

    out: dict[int, tuple[float, ...]] = {}
    sources: list[Any] = []
    for attr in ("active_tracks", "tracked_stracks"):
        value = getattr(core, attr, None)
        if value:
            sources.extend(value)
    for strack in sources:
        raw_id = getattr(strack, "id", None)
        if not isinstance(raw_id, (int, np.integer)):
            raw_id = getattr(strack, "track_id", None)
        if not isinstance(raw_id, (int, np.integer)):
            continue
        feat = getattr(strack, "smooth_feat", None)
        if feat is None:
            feat = getattr(strack, "curr_feat", None)
        if feat is None:
            continue
        try:
            arr = np.asarray(feat, dtype=np.float32).reshape(-1)
        except Exception:
            continue
        if arr.size == 0 or not np.all(np.isfinite(arr)):
            continue
        out[int(raw_id)] = tuple(float(v) for v in arr)
    return out


def _select_torch_device() -> str:
    raw = os.environ.get("RT_TORCH_DEVICE", "").strip().lower()
    if raw:
        return raw
    try:
        import torch
    except ImportError:  # pragma: no cover
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


__all__ = [
    "BotSortReIDTracker",
    "DEFAULT_REID_MODEL",
    "REID_CACHE_DIR",
]
