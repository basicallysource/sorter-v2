"""Polar-space multi-object tracker for the circular feeder channel.

Pieces on ``c_channel_2`` / ``c_channel_3`` move along an annulus — their
natural state is ``(angle, radius)``, not ``(x, y)``. Tracking in polar
space makes the motion model nearly linear (constant angular velocity,
near-constant radius) so Kalman prediction stays tight even when pieces
move several tens of pixels per detection tick.

Why not ByteTrack here: ByteTrack matches on IoU, which drops to zero the
moment a piece's bbox no longer overlaps its previous bbox. On the annulus
that happens after 30–60 px of arc movement at 5 Hz detection — tracks
reset constantly. Polar Kalman + Hungarian on angular+radial distance
handles that geometry natively.

Wrap-around at ±π is handled via circular residuals in the Kalman update
and ``_circular_diff`` in the cost matrix. Falls back to plain Cartesian
L2 matching when no channel geometry has been pushed in — so the tracker
still works before the polygons are loaded.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np

from .appearance import cosine_similarity, get_embedder
from .base import TrackedPiece, Tracker
from .handoff import PieceHandoffManager
from .history import (
    PieceHistoryBuffer,
    SectorSnapshot,
    TrackSegment,
    encode_snapshot,
    pick_sharpest_piece_jpeg,
    render_sector_composite,
    render_snapshot_thumb,
)


DEFAULT_SECTOR_COUNT = 18

# When either the track or detection has no embedding, the cosine term is
# undefined and the match cost degenerates to position-only. Require a much
# tighter geometric fit than the normal 1.0 step thresholds in that case so
# an OSNet hiccup on a busy tick cannot cross-bind nearby pieces.
GEOM_STRICT_THRESHOLD = 0.25

# If the Hungarian solver accepts a pair whose cosine similarity is below
# this and whose geometric cost is above this, flag it as a likely
# intra-tracker id switch. Both thresholds are permissive — the signal fires
# only on clearly-suspect matches so operators notice real trouble.
ID_SWITCH_SIM_SUSPECT = 0.3
ID_SWITCH_GEOM_SUSPECT = 0.5

DEFAULT_STAGNANT_FALSE_TRACK_MAX_AGE_S = 3.0
DEFAULT_STAGNANT_FALSE_TRACK_MIN_DISPLACEMENT_PX = 18.0
DEFAULT_STAGNANT_FALSE_TRACK_MIN_PATH_LENGTH_PX = 28.0
DEFAULT_STAGNANT_FALSE_TRACK_MIN_ANGULAR_DISPLACEMENT_DEG = 4.0
DEFAULT_STAGNANT_FALSE_TRACK_MIN_RADIAL_DISPLACEMENT_PX = 10.0
DEFAULT_STAGNANT_FALSE_TRACK_STEP_JITTER_PX = 2.5
DEFAULT_STAGNANT_FALSE_TRACK_SUPPRESSION_RADIUS_PX = 48.0
DEFAULT_STAGNANT_FALSE_TRACK_SUPPRESSION_TTL_S = 4.0


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


@dataclass
class _ChannelGeometry:
    center_x: float
    center_y: float
    r_inner: float
    r_outer: float
    sector_count: int


def _wrap_angle(a: float) -> float:
    """Normalize ``a`` to ``[-π, π]``."""
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _circular_diff(a: float, b: float) -> float:
    """Signed ``a - b`` wrapped to ``[-π, π]``."""
    return _wrap_angle(a - b)


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


# ---------------------------------------------------------------------------
# Polar Kalman filter
# ---------------------------------------------------------------------------


class _PolarKalman:
    """Kalman filter over ``[angle, radius, ang_vel, rad_vel]`` with
    circular residuals on the angle component.
    """

    def __init__(self, angle: float, radius: float) -> None:
        self.state = np.array([_wrap_angle(angle), float(radius), 0.0, 0.0], dtype=np.float64)
        # Loose prior: angle tight, radius much looser, velocities unknown.
        self.P = np.diag([0.02, 200.0, 1.0, 50.0]).astype(np.float64)
        # Process noise — tuned for 5 Hz ticks on our ~1 rad/s channel.
        self.Q = np.diag([0.001, 2.0, 0.05, 20.0]).astype(np.float64)
        # Measurement noise — detections are reasonably precise.
        self.R = np.diag([0.005, 12.0]).astype(np.float64)
        self.H = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64)

    def predict(self, dt: float) -> None:
        if dt <= 0:
            return
        F = np.array(
            [[1.0, 0.0, dt, 0.0], [0.0, 1.0, 0.0, dt], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        self.state = F @ self.state
        self.state[0] = _wrap_angle(self.state[0])
        self.P = F @ self.P @ F.T + self.Q

    def update(self, meas_angle: float, meas_radius: float) -> None:
        y = np.array(
            [_circular_diff(meas_angle, self.state[0]), meas_radius - self.state[1]],
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

    @property
    def angular_vel(self) -> float:
        return float(self.state[2])

    @property
    def radial_vel(self) -> float:
        return float(self.state[3])


# ---------------------------------------------------------------------------
# Per-track state
# ---------------------------------------------------------------------------


@dataclass
class _LiveTrack:
    internal_id: int
    global_id: int
    bbox: tuple[int, int, int, int]
    center_px: tuple[float, float]
    velocity_px: tuple[float, float]
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
    kalman: _PolarKalman | None = None
    embedding: "np.ndarray | None" = None
    # Filled asynchronously once the exit-trigger fires on this track.
    # Shared-by-reference with the eventual TrackSegment so browser reloads
    # after the background thread completes still see the classifier result.
    auto_recognition: "dict | None" = None
    birth_center_px: tuple[float, float] = (0.0, 0.0)
    birth_angle_rad: float | None = None
    birth_radius_px: float | None = None
    path_length_px: float = 0.0
    max_displacement_px: float = 0.0
    max_angular_displacement_rad: float = 0.0
    max_radial_displacement_px: float = 0.0
    motion_confirmed: bool = False


@dataclass
class _IgnoredStaticRegion:
    center_px: tuple[float, float]
    expires_at: float
    radius_px: float
    center_angle_rad: float | None = None
    center_radius_px: float | None = None
    angle_tolerance_rad: float | None = None
    radius_tolerance_px: float | None = None


def _bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


# Appearance matching lives in ``.appearance`` — a thin wrapper around
# BoxMOT's OSNet_x0_25 ReID model. The embedder loads lazily on first use
# and is a no-op fallback if BoxMOT / its weights aren't available.


# ---------------------------------------------------------------------------
# Main tracker
# ---------------------------------------------------------------------------


class PolarFeederTracker(Tracker):
    """Hungarian-assignment tracker in polar space.

    When channel geometry is set, detections are projected to
    ``(angle, radius)``; matching cost is angular distance (wrap-aware) +
    weighted radial distance, gated by ``max_angular_step_rad`` and
    ``max_radial_step_px``. Without geometry, falls back to pixel L2
    distance so tracking still works pre-polygon.
    """

    def __init__(
        self,
        role: str,
        handoff_manager: PieceHandoffManager,
        *,
        max_angular_step_deg: float = 45.0,
        max_radial_step_px: float = 60.0,
        pixel_fallback_distance_px: float = 100.0,
        coast_limit_ticks: int = 20,
        detection_score_threshold: float = 0.1,
        min_hits_for_history: int = 3,
        # OSNet embedding similarity gate — reject matches where the
        # candidate piece doesn't look like the tracked piece. 0.55 is
        # lenient enough for lighting/angle drift on the same LEGO part
        # but tight enough to reject different parts.
        min_appearance_similarity: float = 0.55,
        # Appearance term weight in the match cost. Set to 0.0 to disable.
        appearance_cost_weight: float = 0.8,
        # Toggle to hard-disable ReID (falls back to position-only matching).
        enable_appearance: bool = True,
        history: PieceHistoryBuffer | None = None,
        enable_stagnant_false_track_filter: bool | None = None,
        stagnant_false_track_max_age_s: float = DEFAULT_STAGNANT_FALSE_TRACK_MAX_AGE_S,
        stagnant_false_track_min_displacement_px: float = DEFAULT_STAGNANT_FALSE_TRACK_MIN_DISPLACEMENT_PX,
        stagnant_false_track_min_path_length_px: float = DEFAULT_STAGNANT_FALSE_TRACK_MIN_PATH_LENGTH_PX,
        stagnant_false_track_min_angular_displacement_deg: float = DEFAULT_STAGNANT_FALSE_TRACK_MIN_ANGULAR_DISPLACEMENT_DEG,
        stagnant_false_track_min_radial_displacement_px: float = DEFAULT_STAGNANT_FALSE_TRACK_MIN_RADIAL_DISPLACEMENT_PX,
        stagnant_false_track_step_jitter_px: float = DEFAULT_STAGNANT_FALSE_TRACK_STEP_JITTER_PX,
        stagnant_false_track_suppression_radius_px: float = DEFAULT_STAGNANT_FALSE_TRACK_SUPPRESSION_RADIUS_PX,
        stagnant_false_track_suppression_ttl_s: float = DEFAULT_STAGNANT_FALSE_TRACK_SUPPRESSION_TTL_S,
        id_switch_suspect_observer: "callable | None" = None,
    ) -> None:
        self.role = role
        self._handoff = handoff_manager
        self._history = history
        self._max_angular_step = math.radians(max_angular_step_deg)
        self._max_radial_step = float(max_radial_step_px)
        self._pixel_fallback_distance = float(pixel_fallback_distance_px)
        self._coast_limit = int(coast_limit_ticks)
        self._score_threshold = float(detection_score_threshold)
        self._min_hits_for_history = max(1, int(min_hits_for_history))
        self._min_appearance_sim = float(min_appearance_similarity)
        self._appearance_cost_weight = float(appearance_cost_weight)
        self._embedder = get_embedder() if enable_appearance else None
        self._enable_stagnant_false_track_filter = (
            bool(enable_stagnant_false_track_filter)
            if enable_stagnant_false_track_filter is not None
            else role == "carousel"
        )
        self._stagnant_false_track_max_age_s = max(0.0, float(stagnant_false_track_max_age_s))
        self._stagnant_false_track_min_displacement_px = max(
            0.0, float(stagnant_false_track_min_displacement_px)
        )
        self._stagnant_false_track_min_path_length_px = max(
            0.0, float(stagnant_false_track_min_path_length_px)
        )
        self._stagnant_false_track_min_angular_displacement_rad = math.radians(
            max(0.0, float(stagnant_false_track_min_angular_displacement_deg))
        )
        self._stagnant_false_track_min_radial_displacement_px = max(
            0.0, float(stagnant_false_track_min_radial_displacement_px)
        )
        self._stagnant_false_track_step_jitter_px = max(
            0.0, float(stagnant_false_track_step_jitter_px)
        )
        self._stagnant_false_track_suppression_radius_px = max(
            0.0, float(stagnant_false_track_suppression_radius_px)
        )
        self._stagnant_false_track_suppression_ttl_s = max(
            0.0, float(stagnant_false_track_suppression_ttl_s)
        )
        self._id_switch_suspect_observer = id_switch_suspect_observer
        self._tracks: dict[int, _LiveTrack] = {}
        self._next_internal_id = 0
        self._last_ts: float | None = None
        self._last_active: list[TrackedPiece] = []
        self._channel_geom: _ChannelGeometry | None = None
        self._ignored_static_regions: list[_IgnoredStaticRegion] = []
        # update() and reset() can be invoked concurrently — overlays on
        # HTTP-streaming threads, camera-service encode threads, and the
        # coordinator's main-loop detection path all end up here. The
        # matching code in update() captures a ``list(self._tracks.keys())``
        # snapshot and then dereferences each id later, which races hard
        # when another thread's concurrent update() prunes dead tracks in
        # between. A single reentrant lock serializes all external mutators.
        self._lock = threading.RLock()

    # ---- Channel geometry ---------------------------------------------

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

    # ---- Coord projection ---------------------------------------------

    def _to_polar(self, center_px: tuple[float, float]) -> tuple[float, float]:
        geom = self._channel_geom
        cx, cy = center_px
        dx = cx - geom.center_x
        dy = cy - geom.center_y
        return math.atan2(dy, dx), math.hypot(dx, dy)

    # ---- Public API ----------------------------------------------------

    def update(
        self,
        bboxes: list[tuple[int, int, int, int]],
        scores: list[float],
        timestamp: float,
        frame_bgr: "np.ndarray | None" = None,
    ) -> list[TrackedPiece]:
        with self._lock:
            return self._update_locked(bboxes, scores, timestamp, frame_bgr)

    def _update_locked(
        self,
        bboxes: list[tuple[int, int, int, int]],
        scores: list[float],
        timestamp: float,
        frame_bgr: "np.ndarray | None" = None,
    ) -> list[TrackedPiece]:
        # Score filter
        filtered: list[tuple[tuple[int, int, int, int], float]] = []
        for bbox, score in zip(bboxes, scores):
            s = float(score) if score is not None else 0.0
            if s < self._score_threshold:
                continue
            filtered.append((tuple(int(v) for v in bbox), s))

        dt = 0.2 if self._last_ts is None else max(0.0, timestamp - self._last_ts)
        self._last_ts = timestamp
        self._prune_ignored_static_regions(timestamp)

        # Predict all tracks forward
        for track in self._tracks.values():
            if track.kalman is not None:
                track.kalman.predict(dt)

        # Build cost matrix
        track_ids = list(self._tracks.keys())
        geom = self._channel_geom
        matched_track_ids: set[int] = set()
        matched_det_indices: set[int] = set()

        # Pre-compute OSNet embeddings for each detection in one batched
        # pass (if the embedder + frame are available). ``None`` for rows
        # with degenerate bboxes.
        det_embeddings: list["np.ndarray | None"] = [None] * len(filtered)
        if self._embedder is not None and frame_bgr is not None and filtered:
            det_bboxes_only = [bb for bb, _ in filtered]
            matrix = self._embedder.extract(frame_bgr, det_bboxes_only)
            if matrix is not None:
                for i in range(len(filtered)):
                    vec = matrix[i]
                    if float(np.linalg.norm(vec)) > 0.0:
                        det_embeddings[i] = vec

        if track_ids and filtered:
            from scipy.optimize import linear_sum_assignment

            rows = len(track_ids)
            cols = len(filtered)
            large = 1e6
            cost = np.full((rows, cols), large, dtype=np.float64)

            det_centers = [_bbox_center(bb) for bb, _ in filtered]

            # Record per-pair appearance evidence so we can split the final
            # cost back into geometric/appearance parts when flagging id
            # switches after the Hungarian assignment runs.
            sim_grid: list[list["float | None"]] = [
                [None] * cols for _ in range(rows)
            ]

            # If the embedder isn't running this tick (disabled by config,
            # BoxMOT unavailable, or caller didn't pass a frame), fall back
            # to the pre-fix contract — we have no reid evidence on any
            # tick and tightening geometry would just break position-only
            # tracking. The strict threshold is only useful for the
            # transient-null case: embedder running + frame present, but a
            # specific detection row came back empty (e.g. degenerate bbox
            # or zero-norm OSNet output).
            appearance_active = (
                self._embedder is not None and frame_bgr is not None
            )

            if geom is not None:
                det_polar = [self._to_polar(c) for c in det_centers]
                for ri, tid in enumerate(track_ids):
                    track = self._tracks[tid]
                    if track.kalman is None:
                        # Promote fallback-track to polar now that geom exists.
                        ang, rad = self._to_polar(track.center_px)
                        track.kalman = _PolarKalman(ang, rad)
                    pa = track.kalman.angle
                    pr = track.kalman.radius
                    for ci, (da, dr) in enumerate(det_polar):
                        ang_cost = abs(_circular_diff(da, pa)) / self._max_angular_step
                        rad_cost = abs(dr - pr) / self._max_radial_step
                        if ang_cost >= 1.0 or rad_cost >= 1.0:
                            continue
                        sim = cosine_similarity(track.embedding, det_embeddings[ci])
                        if sim is not None:
                            if sim < self._min_appearance_sim:
                                continue
                            app_cost = self._appearance_cost_weight * (1.0 - sim)
                        elif appearance_active:
                            # No appearance evidence on at least one side
                            # even though the embedder is running — require
                            # a tight geometric fit instead of the normal
                            # 1.0 step tolerance, otherwise a nearby piece
                            # can silently steal this track's id when OSNet
                            # hiccups.
                            if (
                                ang_cost > GEOM_STRICT_THRESHOLD
                                or rad_cost > GEOM_STRICT_THRESHOLD
                            ):
                                continue
                            app_cost = 0.0
                        else:
                            app_cost = 0.0
                        sim_grid[ri][ci] = sim
                        cost[ri, ci] = ang_cost + 0.5 * rad_cost + app_cost
            else:
                # Cartesian fallback
                for ri, tid in enumerate(track_ids):
                    track = self._tracks[tid]
                    tx, ty = track.center_px
                    for ci, (dx, dy) in enumerate(det_centers):
                        d = math.hypot(dx - tx, dy - ty)
                        if d >= self._pixel_fallback_distance:
                            continue
                        geom_cost = d / self._pixel_fallback_distance
                        sim = cosine_similarity(track.embedding, det_embeddings[ci])
                        if sim is not None:
                            if sim < self._min_appearance_sim:
                                continue
                            app_cost = self._appearance_cost_weight * (1.0 - sim)
                        elif appearance_active:
                            if geom_cost > GEOM_STRICT_THRESHOLD:
                                continue
                            app_cost = 0.0
                        else:
                            app_cost = 0.0
                        sim_grid[ri][ci] = sim
                        cost[ri, ci] = geom_cost + app_cost

            row_ind, col_ind = linear_sum_assignment(cost)
            for r, c in zip(row_ind, col_ind):
                if cost[r, c] >= large:
                    continue
                tid = track_ids[r]
                matched_track_ids.add(tid)
                matched_det_indices.add(int(c))
                bbox, score = filtered[c]
                track = self._tracks[tid]
                # Flag matches that Hungarian accepted only because there
                # was no better pairing available — low appearance support
                # combined with loose geometry is the classic intra-tracker
                # id-switch signature.
                pair_sim = sim_grid[r][c]
                if pair_sim is not None and pair_sim < ID_SWITCH_SIM_SUSPECT:
                    geom_cost = float(
                        cost[r, c] - self._appearance_cost_weight * (1.0 - pair_sim)
                    )
                    if geom_cost > ID_SWITCH_GEOM_SUSPECT:
                        observer = self._id_switch_suspect_observer
                        if observer is not None:
                            try:
                                observer(
                                    role=self.role,
                                    global_id=int(track.global_id),
                                    similarity=float(pair_sim),
                                    geom_cost=float(geom_cost),
                                )
                            except Exception:
                                pass
                cx, cy = _bbox_center(bbox)
                prev_cx, prev_cy = track.center_px
                vdt = max(1e-3, float(timestamp) - float(track.last_seen_ts))
                new_vx = (cx - prev_cx) / vdt
                new_vy = (cy - prev_cy) / vdt
                step_distance_px = math.hypot(cx - prev_cx, cy - prev_cy)
                a = 0.5
                track.velocity_px = (
                    a * new_vx + (1 - a) * track.velocity_px[0],
                    a * new_vy + (1 - a) * track.velocity_px[1],
                )
                if track.kalman is not None and geom is not None:
                    da, dr = self._to_polar((cx, cy))
                    track.kalman.update(da, dr)
                track.bbox = bbox
                track.center_px = (cx, cy)
                track.score = float(score)
                track.hit_count += 1
                track.coast_count = 0
                track.last_seen_ts = timestamp
                track.path.append((float(timestamp), float(cx), float(cy)))
                if step_distance_px >= self._stagnant_false_track_step_jitter_px:
                    track.path_length_px += step_distance_px
                birth_cx, birth_cy = track.birth_center_px
                track.max_displacement_px = max(
                    track.max_displacement_px,
                    math.hypot(cx - birth_cx, cy - birth_cy),
                )
                if geom is not None:
                    if track.birth_angle_rad is None or track.birth_radius_px is None:
                        track.birth_angle_rad = da
                        track.birth_radius_px = dr
                    track.max_angular_displacement_rad = max(
                        track.max_angular_displacement_rad,
                        abs(_circular_diff(da, track.birth_angle_rad)),
                    )
                    track.max_radial_displacement_px = max(
                        track.max_radial_displacement_px,
                        abs(dr - track.birth_radius_px),
                    )
                if (
                    track.max_displacement_px >= self._stagnant_false_track_min_displacement_px
                    or track.path_length_px >= self._stagnant_false_track_min_path_length_px
                    or track.max_angular_displacement_rad >= self._stagnant_false_track_min_angular_displacement_rad
                    or track.max_radial_displacement_px >= self._stagnant_false_track_min_radial_displacement_px
                ):
                    track.motion_confirmed = True
                # EMA-update the reference embedding so tracks adapt to
                # slow lighting/angle drift without being dominated by one
                # noisy frame. Renormalize so cosine similarity stays well-
                # defined.
                det_vec = det_embeddings[c]
                if det_vec is not None:
                    if track.embedding is None:
                        track.embedding = det_vec
                    else:
                        blended = 0.8 * track.embedding + 0.2 * det_vec
                        norm = float(np.linalg.norm(blended))
                        if norm > 0.0:
                            track.embedding = (blended / norm).astype(np.float32)
                self._maybe_capture_sector(track, frame_bgr, timestamp)

        stagnant_ids: list[int] = []
        for tid, track in self._tracks.items():
            if tid in matched_track_ids and self._should_ignore_stagnant_false_track(track, timestamp):
                stagnant_ids.append(tid)
        for tid in stagnant_ids:
            track = self._tracks.pop(tid, None)
            if track is not None:
                self._suppress_stagnant_false_track(track, timestamp)

        # Coast unmatched tracks
        dead_ids: list[int] = []
        for tid, track in self._tracks.items():
            if tid in matched_track_ids:
                continue
            track.coast_count += 1
            if track.coast_count > self._coast_limit:
                dead_ids.append(tid)
        for tid in dead_ids:
            track = self._tracks.pop(tid)
            self._handoff.notify_track_death(
                self.role,
                track.global_id,
                track.center_px,
                track.last_seen_ts,
                death_ts=timestamp,
                last_displacement_px=float(track.max_displacement_px),
                embedding=track.embedding,
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

        # Unmatched detections → new tracks
        for idx, (bbox, score) in enumerate(filtered):
            if idx in matched_det_indices:
                continue
            cx, cy = _bbox_center(bbox)
            if self._is_inside_ignored_static_region((cx, cy), timestamp):
                continue
            global_id, handoff_from = self._handoff.register_track(
                self.role, (cx, cy), timestamp, embedding=det_embeddings[idx]
            )
            self._next_internal_id += 1
            internal = self._next_internal_id
            snap_b64, snap_w, snap_h = "", 0, 0
            if frame_bgr is not None and self._history is not None:
                snap_b64, snap_w, snap_h = encode_snapshot(frame_bgr)
            kalman: _PolarKalman | None = None
            birth_angle_rad: float | None = None
            birth_radius_px: float | None = None
            if geom is not None:
                ang, rad = self._to_polar((cx, cy))
                kalman = _PolarKalman(ang, rad)
                birth_angle_rad = ang
                birth_radius_px = rad
            new_track = _LiveTrack(
                internal_id=internal,
                global_id=global_id,
                bbox=bbox,
                center_px=(cx, cy),
                velocity_px=(0.0, 0.0),
                score=float(score),
                first_seen_ts=timestamp,
                origin_seen_ts=timestamp,
                last_seen_ts=timestamp,
                handoff_from=handoff_from,
                snapshot_jpeg_b64=snap_b64,
                snapshot_width=snap_w,
                snapshot_height=snap_h,
                path=[(float(timestamp), float(cx), float(cy))],
                kalman=kalman,
                embedding=det_embeddings[idx],
                birth_center_px=(float(cx), float(cy)),
                birth_angle_rad=birth_angle_rad,
                birth_radius_px=birth_radius_px,
            )
            self._tracks[internal] = new_track
            self._maybe_capture_sector(new_track, frame_bgr, timestamp)

        # Emit active list
        active: list[TrackedPiece] = []
        for track in self._tracks.values():
            active.append(
                TrackedPiece(
                    global_id=track.global_id,
                    source_role=self.role,
                    bbox=track.bbox,
                    center=track.center_px,
                    velocity_px_per_s=track.velocity_px,
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

    def live_global_ids(self) -> set[int]:
        """Snapshot of ``global_id``s for currently-alive tracks.

        Used by :class:`PieceHandoffManager` to skip pending handoffs whose
        upstream piece is still physically on camera — that piece hasn't
        actually left, so a downstream claim for its id would be a misbind.
        """
        with self._lock:
            return {int(t.global_id) for t in self._tracks.values()}

    def get_live_track_angular_extents(self) -> list[dict[str, float | int]]:
        with self._lock:
            geom = self._channel_geom
            if geom is None:
                return []
            extents: list[dict[str, float | int]] = []
            for track in self._tracks.values():
                extent = self._track_angular_extent(track, geom)
                if extent is None:
                    continue
                center_angle_rad, half_width_rad = extent
                extents.append(
                    {
                        "global_id": int(track.global_id),
                        "center_deg": math.degrees(center_angle_rad) % 360.0,
                        "half_width_deg": math.degrees(half_width_rad),
                        "first_seen_ts": float(track.first_seen_ts),
                        "last_seen_ts": float(track.last_seen_ts),
                        "hit_count": int(track.hit_count),
                    }
                )
            return extents

    def reset(self) -> None:
        with self._lock:
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
            self._next_internal_id = 0
            self._ignored_static_regions.clear()

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
                path=track.path,
                handoff=track.handoff_from is not None,
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

    def _track_angular_extent(
        self,
        track: _LiveTrack,
        geom: _ChannelGeometry,
    ) -> tuple[float, float] | None:
        cx_t, cy_t = track.center_px
        dx = cx_t - geom.center_x
        dy = cy_t - geom.center_y
        dist_center = math.hypot(dx, dy)
        if dist_center < geom.r_inner * 0.4 or dist_center > geom.r_outer * 1.6:
            return None

        center_angle_rad = math.atan2(dy, dx)
        x1, y1, x2, y2 = track.bbox
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        corner_angles = [
            math.atan2(cy - geom.center_y, cx - geom.center_x) for cx, cy in corners
        ]

        anchor = center_angle_rad
        unwrapped: list[float] = []
        for angle in corner_angles:
            diff = angle - anchor
            while diff > math.pi:
                diff -= 2 * math.pi
            while diff < -math.pi:
                diff += 2 * math.pi
            unwrapped.append(anchor + diff)
        a_min = min(unwrapped)
        a_max = max(unwrapped)
        raw_half_width_rad = max(0.0, (a_max - a_min) / 2.0)
        half_width_rad = raw_half_width_rad + max(
            math.radians(2.0),
            raw_half_width_rad * 0.15,
        )
        return center_angle_rad, half_width_rad

    # ---- Internal helpers ---------------------------------------------

    def _maybe_capture_sector(
        self,
        track: _LiveTrack,
        frame_bgr: "np.ndarray | None",
        timestamp: float,
    ) -> None:
        geom = self._channel_geom
        if geom is None or frame_bgr is None:
            return
        cx_t, cy_t = track.center_px
        dx = cx_t - geom.center_x
        dy = cy_t - geom.center_y
        dist_center = math.hypot(dx, dy)
        if dist_center < geom.r_inner * 0.4 or dist_center > geom.r_outer * 1.6:
            return

        center_angle_rad = math.atan2(dy, dx)

        # Angular extent from bbox corners — we size the wedge's angular
        # span to the actual piece width (plus a small margin). Radial
        # extent, on the other hand, always spans the full channel ring
        # from inner to outer rim so the user sees the piece in context
        # rather than a narrow strip that might crop the piece.
        x1, y1, x2, y2 = track.bbox
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        corner_angles = [math.atan2(cy - geom.center_y, cx - geom.center_x) for cx, cy in corners]

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
        # Generous angular margin (~8° min or 40 % of extent) so the wedge
        # doesn't clip the piece on edges when YOLO's bbox is a bit tight.
        angular_margin = max(math.radians(8.0), (a_max - a_min) * 0.4)
        a0 = a_min - angular_margin
        a1 = a_max + angular_margin

        # Full ring depth with a small padding so the inner/outer rim is
        # visible around the piece.
        r_in = max(1.0, geom.r_inner - 6.0)
        r_out = geom.r_outer + 6.0
        if r_out <= r_in:
            return

        new_span_rad = a1 - a0
        min_gap_rad = math.radians(3.0)
        if track.last_capture_angle_rad is not None:
            raw_diff = _circular_diff(center_angle_rad, track.last_capture_angle_rad)
            required = (track.last_capture_span_rad + new_span_rad) / 2.0 + min_gap_rad
            if abs(raw_diff) < required:
                return

        # Wide wedge-bbox crop — used by the pie composite + SVG clipPath
        # so the big modal view shows the piece in ring context.
        wedge = _wedge_bbox(
            geom.center_x, geom.center_y, r_in, r_out, a0, a1, frame_bgr.shape,
        )
        if wedge is None:
            return
        bx1, by1, bx2, by2 = wedge
        crop = frame_bgr[by1:by2, bx1:bx2]
        if crop.size == 0:
            return
        b64, w, h = encode_snapshot(crop)
        if not b64:
            return

        # Tight crop around the piece itself — for Recognize / classification
        # thumbnails. Piece bbox + small margin, like the classification
        # chamber does.
        piece_margin = 8
        fh, fw = frame_bgr.shape[:2]
        pbx1 = max(0, int(x1) - piece_margin)
        pby1 = max(0, int(y1) - piece_margin)
        pbx2 = min(fw, int(x2) + piece_margin)
        pby2 = min(fh, int(y2) + piece_margin)
        piece_b64 = ""
        piece_w = piece_h = 0
        if pbx2 - pbx1 >= 4 and pby2 - pby1 >= 4:
            piece_crop = frame_bgr[pby1:pby2, pbx1:pbx2]
            if piece_crop.size > 0:
                piece_b64, piece_w, piece_h = encode_snapshot(piece_crop)

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
                piece_jpeg_b64=piece_b64,
                piece_bbox_x=int(pbx1),
                piece_bbox_y=int(pby1),
                piece_width=int(piece_w),
                piece_height=int(piece_h),
            )
        )
        track.last_capture_angle_rad = center_angle_rad
        track.last_capture_span_rad = new_span_rad

        # Exit trigger: once the piece has covered enough of the annulus to
        # confidently say "this track represents one complete journey across
        # c_channel_3", kick off the auto-recognition so the operator sees
        # a result before the track even dies. Runs once per track.
        self._maybe_fire_auto_recognize(track)

    def _maybe_fire_auto_recognize(self, track: _LiveTrack) -> None:
        """Trigger the Brickognize auto-recognition once this track has
        traveled far enough across c_channel_3 to have covered a useful
        range of viewing angles. Fires once per track (the run_async
        helper is idempotent).
        """
        if self.role != "c_channel_3":
            return
        if track.auto_recognition is not None:
            return
        if len(track.sector_snapshots) < 5:
            return
        geom = self._channel_geom
        if geom is None or not track.path:
            return
        # Circular angular span of the path — fire when we've covered
        # roughly half the ring, i.e. the piece is well past the entry and
        # close to the exit on a normal run.
        import math as _m
        anchor = _m.atan2(
            track.path[0][2] - geom.center_y,
            track.path[0][1] - geom.center_x,
        )
        unwrapped: list[float] = []
        for _ts, x, y in track.path:
            a = _m.atan2(y - geom.center_y, x - geom.center_x)
            d = a - anchor
            while d > _m.pi:
                d -= 2 * _m.pi
            while d < -_m.pi:
                d += 2 * _m.pi
            unwrapped.append(anchor + d)
        span = max(unwrapped) - min(unwrapped)
        if abs(span) < _m.radians(150.0):
            return
        piece_crops = [
            s.piece_jpeg_b64 for s in track.sector_snapshots if s.piece_jpeg_b64
        ]
        if len(piece_crops) < 8:
            return
        try:
            from classification.auto_recognize import run_async as _auto_run
            _gid = track.global_id
            _flush = (
                (lambda: self._history.flush(_gid))
                if self._history is not None and hasattr(self._history, "flush")
                else None
            )
            _auto_run(track, piece_crops, min_crops=5, on_complete=_flush)
        except Exception:
            # Never break the tracker over a recognize hookup.
            pass

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
                path=track.path,
                handoff=track.handoff_from is not None,
            )
        if not composite_b64 and track.snapshot_jpeg_b64:
            composite_b64, composite_w, composite_h = render_snapshot_thumb(
                track.snapshot_jpeg_b64
            )
        segment = TrackSegment(
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
            best_piece_jpeg_b64=pick_sharpest_piece_jpeg(track.sector_snapshots),
            # Share the live track's auto_recognition dict by reference so
            # the background thread's final mutation propagates here too.
            auto_recognition=track.auto_recognition,
        )

        # Fallback: the piece died before hitting our angular-span exit
        # trigger, but we still have enough crops to classify. Fire on the
        # segment (idempotent — no-op if the exit trigger already ran).
        if self.role == "c_channel_3" and segment.auto_recognition is None:
            piece_crops = [
                s.piece_jpeg_b64
                for s in track.sector_snapshots
                if s.piece_jpeg_b64
            ]
            if len(piece_crops) >= 5:
                try:
                    from classification.auto_recognize import run_async as _auto_run
                    _gid = track.global_id
                    _flush = (
                        (lambda: self._history.flush(_gid))
                        if self._history is not None and hasattr(self._history, "flush")
                        else None
                    )
                    _auto_run(segment, piece_crops, min_crops=5, on_complete=_flush)
                except Exception:
                    pass

        return segment

    def _prune_ignored_static_regions(self, timestamp: float) -> None:
        self._ignored_static_regions = [
            region for region in self._ignored_static_regions if region.expires_at > float(timestamp)
        ]

    def _is_inside_ignored_static_region(
        self,
        center_px: tuple[float, float],
        timestamp: float,
    ) -> bool:
        self._prune_ignored_static_regions(timestamp)
        cx, cy = center_px
        geom = self._channel_geom
        polar_center: tuple[float, float] | None = None
        if geom is not None:
            polar_center = self._to_polar(center_px)
        for region in self._ignored_static_regions:
            rx, ry = region.center_px
            if math.hypot(cx - rx, cy - ry) > region.radius_px:
                continue
            if (
                polar_center is not None
                and region.center_angle_rad is not None
                and region.center_radius_px is not None
                and region.angle_tolerance_rad is not None
                and region.radius_tolerance_px is not None
            ):
                angle, radius = polar_center
                if (
                    abs(_circular_diff(angle, region.center_angle_rad))
                    > region.angle_tolerance_rad
                    or abs(radius - region.center_radius_px) > region.radius_tolerance_px
                ):
                    continue
            return True
        return False

    def _should_ignore_stagnant_false_track(
        self,
        track: _LiveTrack,
        timestamp: float,
    ) -> bool:
        if not self._enable_stagnant_false_track_filter:
            return False
        if track.handoff_from is not None:
            return False
        if track.motion_confirmed:
            return False
        age_s = float(timestamp) - float(track.first_seen_ts)
        if age_s < self._stagnant_false_track_max_age_s:
            return False
        if track.max_displacement_px >= self._stagnant_false_track_min_displacement_px:
            return False
        if track.path_length_px >= self._stagnant_false_track_min_path_length_px:
            return False
        if (
            track.max_angular_displacement_rad
            >= self._stagnant_false_track_min_angular_displacement_rad
        ):
            return False
        if (
            track.max_radial_displacement_px
            >= self._stagnant_false_track_min_radial_displacement_px
        ):
            return False
        return True

    def _suppress_stagnant_false_track(
        self,
        track: _LiveTrack,
        timestamp: float,
    ) -> None:
        if self._stagnant_false_track_suppression_ttl_s <= 0.0:
            return
        geom = self._channel_geom
        center_angle_rad: float | None = None
        center_radius_px: float | None = None
        angle_tolerance_rad: float | None = None
        radius_tolerance_px: float | None = None
        if geom is not None:
            center_angle_rad, center_radius_px = self._to_polar(track.center_px)
            angle_tolerance_rad = max(
                self._stagnant_false_track_min_angular_displacement_rad,
                math.radians(2.0),
            )
            radius_tolerance_px = max(
                self._stagnant_false_track_min_radial_displacement_px,
                8.0,
            )
        self._ignored_static_regions.append(
            _IgnoredStaticRegion(
                center_px=track.center_px,
                expires_at=float(timestamp) + self._stagnant_false_track_suppression_ttl_s,
                radius_px=self._stagnant_false_track_suppression_radius_px,
                center_angle_rad=center_angle_rad,
                center_radius_px=center_radius_px,
                angle_tolerance_rad=angle_tolerance_rad,
                radius_tolerance_px=radius_tolerance_px,
            )
        )
