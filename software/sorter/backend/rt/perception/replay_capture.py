"""Capture detector-input frames for offline tracker replay benchmarks."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np

from blob_manager import BLOB_DIR
from rt.contracts.feed import FeedFrame, PolygonZone, PolarZone, RectZone, Zone


_LOG = logging.getLogger(__name__)
REPLAY_CAPTURE_ROOT = BLOB_DIR / "replay_captures"


def _zone_kind(zone: Zone | None) -> str | None:
    if zone is None:
        return None
    return type(zone).__name__.replace("Zone", "").lower()


def _zone_payload(zone: Zone | None) -> dict[str, Any] | None:
    if isinstance(zone, RectZone):
        return {"kind": "rect", "x": zone.x, "y": zone.y, "w": zone.w, "h": zone.h}
    if isinstance(zone, PolygonZone):
        return {"kind": "polygon", "vertices": [list(v) for v in zone.vertices]}
    if isinstance(zone, PolarZone):
        return {
            "kind": "polar",
            "center_xy": list(zone.center_xy),
            "r_inner": zone.r_inner,
            "r_outer": zone.r_outer,
            "theta_start_rad": zone.theta_start_rad,
            "theta_end_rad": zone.theta_end_rad,
        }
    return None


def _tracker_geometry_payload(
    tracker: Any,
    *,
    offset_xy: tuple[int, int] = (0, 0),
) -> dict[str, Any]:
    ox, oy = int(offset_xy[0]), int(offset_xy[1])
    center = getattr(tracker, "_polar_center", None)
    radius_range = getattr(tracker, "_polar_radius_range", None)
    payload: dict[str, Any] = {}
    if isinstance(center, (tuple, list)) and len(center) == 2:
        try:
            payload["polar_center"] = [float(center[0]) - ox, float(center[1]) - oy]
        except Exception:
            pass
    if isinstance(radius_range, (tuple, list)) and len(radius_range) == 2:
        try:
            payload["polar_radius_range"] = [
                float(radius_range[0]),
                float(radius_range[1]),
            ]
        except Exception:
            pass
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


class DetectorInputRecorder:
    """Losslessly records the exact clean crop a detector sees per frame."""

    def __init__(
        self,
        *,
        feed_id: str,
        detector_key: str,
        tracker_key: str,
        zone: Zone | None,
        tracker: Any,
        max_frames: int = 300,
        sample_every_n: int = 1,
        label: str | None = None,
        root_dir: Path | None = None,
    ) -> None:
        self.capture_id = (
            time.strftime("%Y%m%d-%H%M%S")
            + f"_{feed_id}_{uuid4().hex[:8]}"
        )
        safe_label = "".join(ch for ch in str(label or "").strip() if ch.isalnum() or ch in "-_")
        if safe_label:
            self.capture_id += f"_{safe_label[:40]}"
        self.feed_id = feed_id
        self.detector_key = detector_key
        self.tracker_key = tracker_key
        self.zone = zone
        self.tracker = tracker
        self.max_frames = max(1, int(max_frames))
        self.sample_every_n = max(1, int(sample_every_n))
        self.root_dir = (root_dir or REPLAY_CAPTURE_ROOT) / self.capture_id
        self.frames_dir = self.root_dir / "frames"
        self.preview_dir = self.root_dir / "preview"
        self.manifest_path = self.root_dir / "manifest.json"
        self.frames_jsonl_path = self.root_dir / "frames.jsonl"
        self.started_at = time.time()
        self.stopped_at: float | None = None
        self.frame_count = 0
        self.seen_count = 0
        self.last_error: str | None = None
        self.active = True
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self._persist_manifest()

    def status(self) -> dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "feed_id": self.feed_id,
            "detector_key": self.detector_key,
            "tracker_key": self.tracker_key,
            "active": self.active,
            "frame_count": self.frame_count,
            "seen_count": self.seen_count,
            "max_frames": self.max_frames,
            "sample_every_n": self.sample_every_n,
            "root_dir": str(self.root_dir),
            "manifest_path": str(self.manifest_path),
            "frames_jsonl_path": str(self.frames_jsonl_path),
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_error": self.last_error,
        }

    def stop(self) -> dict[str, Any]:
        if self.active:
            self.active = False
            self.stopped_at = time.time()
            self._persist_manifest()
        return self.status()

    def capture(
        self,
        *,
        frame: FeedFrame,
        detector: Any,
        zone: Zone,
        tracker: Any,
    ) -> None:
        if not self.active:
            return
        self.seen_count += 1
        if (self.seen_count - 1) % self.sample_every_n != 0:
            return
        if self.frame_count >= self.max_frames:
            self.stop()
            return
        raw = getattr(frame, "raw", None)
        if not isinstance(raw, np.ndarray) or raw.size == 0:
            return
        apply_zone = getattr(detector, "_apply_zone", None)
        if not callable(apply_zone):
            self.last_error = "detector has no _apply_zone helper"
            return
        try:
            crop, offset = apply_zone(raw, zone)
        except NotImplementedError:
            self.last_error = "detector zone crop is not implemented"
            return
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            _LOG.exception("detector-input replay capture failed")
            return
        if not isinstance(crop, np.ndarray) or crop.size == 0:
            return
        crop = np.ascontiguousarray(crop)
        ox, oy = int(offset[0]), int(offset[1])
        idx = self.frame_count
        stem = f"{idx:06d}_seq{int(frame.frame_seq):08d}"
        npy_rel = f"frames/{stem}.npy"
        png_rel = f"preview/{stem}.png"
        np.save(self.root_dir / npy_rel, crop)
        try:
            cv2.imwrite(str(self.root_dir / png_rel), crop)
        except Exception:
            png_rel = ""
        record = {
            "index": idx,
            "feed_id": frame.feed_id,
            "camera_id": frame.camera_id,
            "frame_seq": int(frame.frame_seq),
            "timestamp": float(frame.timestamp),
            "monotonic_ts": float(frame.monotonic_ts),
            "source_shape": list(raw.shape),
            "crop_shape": list(crop.shape),
            "crop_dtype": str(crop.dtype),
            "crop_bounds_xyxy": [ox, oy, ox + int(crop.shape[1]), oy + int(crop.shape[0])],
            "crop_npy": npy_rel,
            "preview_png": png_rel or None,
            "zone_kind": _zone_kind(zone),
            "detector_key": getattr(detector, "key", self.detector_key),
            "tracker_key": getattr(tracker, "key", self.tracker_key),
            "tracker_params": _tracker_geometry_payload(tracker, offset_xy=(ox, oy)),
        }
        with self.frames_jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.frame_count += 1
        if self.frame_count >= self.max_frames:
            self.stop()
        elif self.frame_count % 10 == 0:
            self._persist_manifest()

    def _persist_manifest(self) -> None:
        payload = {
            **self.status(),
            "zone": _zone_payload(self.zone),
            "format": {
                "frame_record": "frames.jsonl",
                "image_array": "NumPy .npy, BGR uint8 as passed to detector",
                "preview": "PNG convenience preview, not used for benchmark",
            },
        }
        _write_json(self.manifest_path, payload)


__all__ = ["DetectorInputRecorder", "REPLAY_CAPTURE_ROOT"]
