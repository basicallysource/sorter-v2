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


DEFAULT_TRACKERS = (
    "botsort_reid",
    "botsort_reid:with_reid=false",
    "turntable_groundplane",
    "rf_bytetrack",
    "rf_ocsort",
)


@dataclass
class ObjectTrail:
    trail_id: int
    last_center: tuple[float, float]
    last_frame_index: int
    detections: int = 0
    tracker_ids: list[int | None] = field(default_factory=list)


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


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _assign_detections_to_trails(
    trails: list[ObjectTrail],
    detections: tuple[Any, ...],
    *,
    frame_index: int,
    max_distance_px: float,
    max_gap_frames: int,
) -> list[ObjectTrail]:
    assignments: list[ObjectTrail] = []
    used_trails: set[int] = set()
    next_id = max((trail.trail_id for trail in trails), default=0) + 1
    for det in detections:
        center = _bbox_center(det.bbox_xyxy)
        candidates = [
            (
                _distance(center, trail.last_center),
                trail,
            )
            for trail in trails
            if trail.trail_id not in used_trails
            and frame_index - trail.last_frame_index <= max_gap_frames
        ]
        candidates = [item for item in candidates if item[0] <= max_distance_px]
        if candidates:
            _, trail = min(candidates, key=lambda item: item[0])
            trail.last_center = center
            trail.last_frame_index = frame_index
            trail.detections += 1
            used_trails.add(trail.trail_id)
        else:
            trail = ObjectTrail(
                trail_id=next_id,
                last_center=center,
                last_frame_index=frame_index,
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
    tracker = TRACKERS.create(tracker_key, **base_params)
    trails: list[ObjectTrail] = []
    track_births = 0
    lost_total = 0
    previous_live_ids: set[int] = set()
    frames_with_tracks = 0
    total_tracks = 0
    total_detections = 0
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
    }


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
    results = [
        _benchmark_tracker(
            spec=spec,
            detection_stream=detection_stream,
            match_distance_px=float(args.match_distance_px),
            max_gap_frames=int(args.max_gap_frames),
        )
        for spec in specs
    ]
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
        "tracker\tbirths\tlost\tid_switches\tgaps\tfragmented\tavg_tracks\tobject_trails"
    )
    for item in results:
        print(
            f"{item['label']}\t{item['track_births']}\t{item['lost_track_ids']}\t"
            f"{item['id_switches']}\t{item['tracking_gaps']}\t"
            f"{item['fragmented_object_trails']}\t{item['avg_tracks_per_frame']}\t"
            f"{item['object_trails']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
