#!/usr/bin/env python3
"""Benchmark tracker/ReID combinations on captured detector-input replays.

Input is a directory produced by ``/api/rt/replay-capture/start``. Frames are
loaded from lossless ``.npy`` crops, detections are recomputed on each crop,
and each tracker spec receives the exact same detection stream.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import rt.perception  # noqa: E402,F401 - register detectors/trackers
from rt.contracts.feed import FeedFrame, RectZone  # noqa: E402
from rt.contracts.registry import DETECTORS, TRACKERS  # noqa: E402
from rt.contracts.tracking import Track, TrackBatch  # noqa: E402


DEFAULT_TRACKERS = (
    "boxmot_bytetrack",
    "boxmot_bytetrack:track_buffer=45",
    "boxmot_bytetrack:track_thresh=0.50",
    "botsort_reid",
    "botsort_reid:with_reid=false",
    "boxmot_raw_bytetrack",
    "boxmot_raw_botsort",
)


@dataclass
class ObjectTrail:
    trail_id: int
    last_center: tuple[float, float]
    last_frame_index: int
    last_polar: tuple[float, float] | None = None
    detections: int = 0
    tracker_ids: list[int | None] = field(default_factory=list)


class _ReplayBoxmotTracker:
    """Small benchmark-only adapter for direct BoxMOT tracker classes.

    The production runtime intentionally uses sorter-native tracker adapters.
    This wrapper exists only so replay benchmarks can compare upstream BoxMOT
    algorithms on the exact same detector stream without making them runtime
    strategies yet.
    """

    key = "boxmot"

    def __init__(self, tracker_type: str, params: dict[str, Any]) -> None:
        self.key = f"boxmot_{tracker_type}"
        self._tracker_type = tracker_type
        self._core = _create_boxmot_core(tracker_type, params)
        self._previous_live_ids: set[int] = set()
        self._first_seen: dict[int, float] = {}
        self._hits: dict[int, int] = {}

    def update(self, detections: Any, frame: FeedFrame) -> TrackBatch:
        dets_np = _detections_to_boxmot_numpy(detections)
        image = _frame_image(frame)
        try:
            rows = self._core.update(dets_np, image)
        except TypeError:
            rows = self._core.update(dets_np)
        rows_np = np.atleast_2d(np.asarray(rows, dtype=np.float32))
        if rows_np.size == 0 or rows_np.shape[-1] < 5:
            rows_np = np.empty((0, 8), dtype=np.float32)

        timestamp = frame.timestamp if frame.timestamp > 0 else time.time()
        tracks: list[Track] = []
        live_ids: set[int] = set()
        for row in rows_np:
            track_id = int(row[4])
            if track_id < 0:
                continue
            live_ids.add(track_id)
            self._first_seen.setdefault(track_id, float(timestamp))
            self._hits[track_id] = self._hits.get(track_id, 0) + 1
            bbox = _clip_bbox(row[:4])
            score = float(row[5]) if row.shape[0] > 5 else 0.0
            tracks.append(
                Track(
                    track_id=track_id,
                    global_id=track_id,
                    piece_uuid=None,
                    bbox_xyxy=bbox,
                    score=score,
                    confirmed_real=True,
                    angle_rad=None,
                    radius_px=None,
                    hit_count=self._hits[track_id],
                    first_seen_ts=self._first_seen[track_id],
                    last_seen_ts=float(timestamp),
                    ghost=False,
                )
            )

        lost = tuple(sorted(self._previous_live_ids - live_ids))
        self._previous_live_ids = live_ids
        return TrackBatch(
            feed_id=detections.feed_id,
            frame_seq=detections.frame_seq,
            timestamp=float(timestamp),
            tracks=tuple(tracks),
            lost_track_ids=lost,
        )

    def stop(self) -> None:
        model = getattr(self._core, "model", None)
        stop = getattr(model, "stop", None)
        if callable(stop):
            stop()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_frames(capture_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_json(capture_dir / "manifest.json")
    frames_path = capture_dir / "frames.jsonl"
    frames: list[dict[str, Any]] = []
    with frames_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                frames.append(json.loads(line))
    frames.sort(key=lambda item: int(item.get("index", 0)))
    return manifest, frames


def _parse_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    try:
        if "." in lowered:
            return float(lowered)
        return int(lowered)
    except ValueError:
        return value


def _parse_tracker_spec(spec: str) -> tuple[str, str, dict[str, Any]]:
    label = spec
    if ":" not in spec:
        return label, spec, {}
    key, raw_params = spec.split(":", 1)
    params: dict[str, Any] = {}
    for part in raw_params.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"Invalid tracker parameter in {spec!r}: {part!r}")
        name, value = part.split("=", 1)
        params[name.strip()] = _parse_value(value)
    return label, key.strip(), params


def _bbox_center(bbox: tuple[int, int, int, int] | list[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(v) for v in bbox)
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5


def _clip_bbox(row: Any) -> tuple[int, int, int, int]:
    values = [float(v) for v in list(row)[:4]]
    if len(values) < 4:
        return (0, 0, 0, 0)
    x1, y1, x2, y2 = values
    return (
        int(round(x1)),
        int(round(y1)),
        int(round(x2)),
        int(round(y2)),
    )


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _polar_position(
    center: tuple[float, float],
    polar_center: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if polar_center is None:
        return None
    dx = float(center[0]) - float(polar_center[0])
    dy = float(center[1]) - float(polar_center[1])
    return math.atan2(dy, dx), math.hypot(dx, dy)


def _circular_abs_delta(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


def _trail_distance(
    *,
    center: tuple[float, float],
    polar: tuple[float, float] | None,
    trail: ObjectTrail,
) -> float:
    if polar is not None and trail.last_polar is not None:
        angle, radius = polar
        prev_angle, prev_radius = trail.last_polar
        arc = _circular_abs_delta(angle, prev_angle) * max(1.0, (radius + prev_radius) * 0.5)
        radial = abs(radius - prev_radius)
        return math.hypot(arc, radial)
    return _distance(center, trail.last_center)


def _assign_detections_to_trails(
    trails: list[ObjectTrail],
    detections: tuple[Any, ...],
    *,
    frame_index: int,
    max_distance_px: float,
    max_gap_frames: int,
    polar_center: tuple[float, float] | None = None,
) -> list[ObjectTrail]:
    assignments: list[ObjectTrail] = []
    used_trails: set[int] = set()
    next_id = max((trail.trail_id for trail in trails), default=0) + 1
    for det in detections:
        center = _bbox_center(det.bbox_xyxy)
        polar = _polar_position(center, polar_center)
        candidates = [
            (
                _trail_distance(center=center, polar=polar, trail=trail),
                trail,
            )
            for trail in trails
            if trail.trail_id not in used_trails
            and frame_index - trail.last_frame_index <= max_gap_frames
        ]
        candidates = [
            item
            for item in candidates
            if item[0]
            <= max_distance_px
            * max(1, frame_index - item[1].last_frame_index)
        ]
        if candidates:
            _, trail = min(candidates, key=lambda item: item[0])
            trail.last_center = center
            trail.last_polar = polar
            trail.last_frame_index = frame_index
            trail.detections += 1
            used_trails.add(trail.trail_id)
        else:
            trail = ObjectTrail(
                trail_id=next_id,
                last_center=center,
                last_frame_index=frame_index,
                last_polar=polar,
                detections=1,
            )
            next_id += 1
            trails.append(trail)
            used_trails.add(trail.trail_id)
        assignments.append(trail)
    return assignments


def _nearest_track_id(
    det_bbox: tuple[int, int, int, int],
    tracks: tuple[Any, ...],
    *,
    max_distance_px: float,
) -> int | None:
    center = _bbox_center(det_bbox)
    best: tuple[float, int] | None = None
    for track in tracks:
        gid = getattr(track, "global_id", None)
        bbox = getattr(track, "bbox_xyxy", None)
        if not isinstance(gid, int) or not isinstance(bbox, tuple):
            continue
        dist = _distance(center, _bbox_center(bbox))
        if dist > max_distance_px:
            continue
        if best is None or dist < best[0]:
            best = (dist, gid)
    return best[1] if best is not None else None


def _id_switch_count(ids: list[int | None]) -> int:
    switches = 0
    previous: int | None = None
    for value in ids:
        if value is None:
            continue
        if previous is not None and value != previous:
            switches += 1
        previous = value
    return switches


def _gap_count(ids: list[int | None]) -> int:
    gaps = 0
    seen_before = False
    in_gap = False
    for value in ids:
        if value is None:
            if seen_before and not in_gap:
                gaps += 1
                in_gap = True
            continue
        seen_before = True
        in_gap = False
    return gaps


def _detect_all(
    *,
    capture_dir: Path,
    manifest: dict[str, Any],
    frames: list[dict[str, Any]],
    detector_key: str,
) -> list[tuple[dict[str, Any], np.ndarray, Any]]:
    detector = DETECTORS.create(detector_key)
    out: list[tuple[dict[str, Any], np.ndarray, Any]] = []
    try:
        for record in frames:
            crop = np.load(capture_dir / str(record["crop_npy"]))
            h, w = int(crop.shape[0]), int(crop.shape[1])
            frame = FeedFrame(
                feed_id=str(record.get("feed_id") or manifest.get("feed_id") or "replay"),
                camera_id=str(record.get("camera_id") or "replay"),
                raw=crop,
                gray=None,
                timestamp=float(record.get("timestamp") or record.get("index") or 0.0),
                monotonic_ts=float(record.get("monotonic_ts") or record.get("timestamp") or 0.0),
                frame_seq=int(record.get("frame_seq") or record.get("index") or 0),
            )
            detections = detector.detect(frame, RectZone(x=0, y=0, w=w, h=h))
            out.append((record, crop, detections))
    finally:
        stop = getattr(detector, "stop", None)
        if callable(stop):
            stop()
    return out


def _detections_to_boxmot_numpy(detections: Any) -> np.ndarray:
    rows: list[tuple[float, float, float, float, float, float]] = []
    for det in detections.detections:
        x1, y1, x2, y2 = (float(v) for v in det.bbox_xyxy)
        rows.append((x1, y1, x2, y2, float(det.score), 0.0))
    if not rows:
        return np.empty((0, 6), dtype=np.float32)
    return np.asarray(rows, dtype=np.float32)


def _frame_image(frame: FeedFrame) -> np.ndarray:
    image = getattr(frame, "raw", None)
    if image is None:
        return np.zeros((64, 64, 3), dtype=np.uint8)
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8, copy=False)
    return arr


def _boxmot_defaults(tracker_type: str) -> dict[str, Any]:
    import yaml
    from boxmot.trackers.tracker_zoo import get_tracker_config

    config_path = get_tracker_config(tracker_type)
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    return {
        str(name): details.get("default")
        for name, details in raw.items()
        if isinstance(details, dict) and "default" in details
    }


def _create_boxmot_core(tracker_type: str, params: dict[str, Any]) -> Any:
    import torch
    from boxmot.trackers.tracker_zoo import create_tracker
    from rt.perception.trackers.boxmot_reid import (
        DEFAULT_REID_MODEL,
        REID_CACHE_DIR,
        _select_torch_device,
    )

    boxmot_params = _boxmot_defaults(tracker_type)
    for key, value in params.items():
        if key in boxmot_params or key in {
            "frame_rate",
            "with_reid",
            "embedding_off",
            "cmc_off",
            "aw_off",
        }:
            boxmot_params[key] = value

    if tracker_type in {"botsort", "bytetrack"}:
        boxmot_params["frame_rate"] = int(params.get("frame_rate", 10))

    device_name = str(params.get("device") or _select_torch_device())
    device = torch.device(device_name)
    reid_model = str(params.get("reid_model") or DEFAULT_REID_MODEL)
    reid_weights = REID_CACHE_DIR / reid_model
    return create_tracker(
        tracker_type,
        reid_weights=reid_weights,
        device=device,
        half=bool(params.get("half", False)),
        per_class=False,
        evolve_param_dict=boxmot_params,
    )


def _create_tracker(tracker_key: str, params: dict[str, Any]) -> Any:
    if tracker_key.startswith("boxmot_raw_"):
        tracker_type = tracker_key.removeprefix("boxmot_raw_")
        return _ReplayBoxmotTracker(tracker_type, params)
    if tracker_key.startswith("boxmot_") and tracker_key not in TRACKERS.keys():
        tracker_type = tracker_key.removeprefix("boxmot_")
        return _ReplayBoxmotTracker(tracker_type, params)
    _import_legacy_tracker_if_requested(tracker_key)
    return TRACKERS.create(tracker_key, **params)


def _import_legacy_tracker_if_requested(tracker_key: str) -> None:
    """Register legacy trackers only when a benchmark explicitly asks for one."""

    if tracker_key.startswith("rf_"):
        import rt.perception.trackers.roboflow  # noqa: F401
    elif tracker_key == "polar":
        import rt.perception.trackers.polar  # noqa: F401


def _benchmark_tracker(
    *,
    spec: str,
    detection_stream: list[tuple[dict[str, Any], np.ndarray, Any]],
    match_distance_px: float,
    max_gap_frames: int,
) -> dict[str, Any]:
    label, tracker_key, params = _parse_tracker_spec(spec)
    base_params = dict(detection_stream[0][0].get("tracker_params") or {}) if detection_stream else {}
    base_params.update(params)
    tracker = _create_tracker(tracker_key, base_params)
    polar_center = _coerce_polar_center(base_params.get("polar_center"))
    trails: list[ObjectTrail] = []
    track_births = 0
    lost_total = 0
    previous_live_ids: set[int] = set()
    frames_with_tracks = 0
    total_tracks = 0
    total_detections = 0
    started = time.perf_counter()
    try:
        for frame_index, (record, crop, detections) in enumerate(detection_stream):
            frame = FeedFrame(
                feed_id=str(record.get("feed_id") or "replay"),
                camera_id=str(record.get("camera_id") or "replay"),
                raw=crop,
                gray=None,
                timestamp=float(record.get("timestamp") or frame_index),
                monotonic_ts=float(record.get("monotonic_ts") or record.get("timestamp") or frame_index),
                frame_seq=int(record.get("frame_seq") or frame_index),
            )
            batch = tracker.update(detections, frame)
            tracks = tuple(batch.tracks)
            live_ids = {int(t.global_id) for t in tracks if isinstance(t.global_id, int)}
            track_births += len(live_ids - previous_live_ids)
            previous_live_ids = live_ids
            lost_total += len(batch.lost_track_ids)
            if tracks:
                frames_with_tracks += 1
            total_tracks += len(tracks)
            total_detections += len(detections.detections)
            assigned = _assign_detections_to_trails(
                trails,
                detections.detections,
                frame_index=frame_index,
                max_distance_px=match_distance_px,
                max_gap_frames=max_gap_frames,
                polar_center=polar_center,
            )
            for det, trail in zip(detections.detections, assigned):
                trail.tracker_ids.append(
                    _nearest_track_id(
                        det.bbox_xyxy,
                        tracks,
                        max_distance_px=match_distance_px,
                    )
                )
    finally:
        stop = getattr(tracker, "stop", None)
        if callable(stop):
            stop()
    switch_total = sum(_id_switch_count(trail.tracker_ids) for trail in trails)
    gap_total = sum(_gap_count(trail.tracker_ids) for trail in trails)
    fragmented = sum(
        1
        for trail in trails
        if len({tid for tid in trail.tracker_ids if tid is not None}) > 1
    )
    elapsed_s = time.perf_counter() - started
    return {
        "label": label,
        "tracker_key": tracker_key,
        "params": base_params,
        "frames": len(detection_stream),
        "detections": total_detections,
        "object_trails": len(trails),
        "frames_with_tracks": frames_with_tracks,
        "avg_tracks_per_frame": round(total_tracks / max(1, len(detection_stream)), 3),
        "track_births": track_births,
        "lost_track_ids": lost_total,
        "id_switches": switch_total,
        "tracking_gaps": gap_total,
        "fragmented_object_trails": fragmented,
        "elapsed_s": round(elapsed_s, 3),
    }


def _coerce_polar_center(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--detector-key", default=None)
    parser.add_argument("--tracker", action="append", dest="trackers")
    parser.add_argument("--match-distance-px", type=float, default=55.0)
    parser.add_argument("--max-gap-frames", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    capture_dir = args.capture_dir.resolve()
    manifest, frames = _load_frames(capture_dir)
    if not frames:
        raise SystemExit("capture has no frames")
    detector_key = args.detector_key or str(frames[0].get("detector_key") or manifest.get("detector_key"))
    detection_stream = _detect_all(
        capture_dir=capture_dir,
        manifest=manifest,
        frames=frames,
        detector_key=detector_key,
    )
    specs = tuple(args.trackers or DEFAULT_TRACKERS)
    results = []
    for spec in specs:
        try:
            results.append(
                _benchmark_tracker(
                    spec=spec,
                    detection_stream=detection_stream,
                    match_distance_px=float(args.match_distance_px),
                    max_gap_frames=int(args.max_gap_frames),
                )
            )
        except Exception as exc:
            label, tracker_key, params = _parse_tracker_spec(spec)
            results.append(
                {
                    "label": label,
                    "tracker_key": tracker_key,
                    "params": params,
                    "frames": len(detection_stream),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    report = {
        "capture_dir": str(capture_dir),
        "detector_key": detector_key,
        "frame_count": len(frames),
        "results": results,
    }
    output = args.output or (capture_dir / "tracker_benchmark.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Replay: {capture_dir}")
    print(f"Detector: {detector_key}")
    print(f"Output: {output}")
    print(
        "tracker\tbirths\tlost\tid_switches\tgaps\tfragmented\tavg_tracks\tobject_trails\telapsed_s"
    )
    for item in results:
        if item.get("error"):
            print(f"{item['label']}\tERROR\t{item['error']}")
            continue
        print(
            f"{item['label']}\t{item['track_births']}\t{item['lost_track_ids']}\t"
            f"{item['id_switches']}\t{item['tracking_gaps']}\t"
            f"{item['fragmented_object_trails']}\t{item['avg_tracks_per_frame']}\t"
            f"{item['object_trails']}\t{item.get('elapsed_s', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
