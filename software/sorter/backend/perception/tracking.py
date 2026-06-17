"""Cross-frame identity for perception-channel detections.

The perception path is otherwise stateless — each frame's bboxes are attributed
by position, with no cross-frame identity (see ``state.PieceObservation``). This
assigns each on-channel bbox a stable ``sv_bt_track_id`` so the same physical
piece keeps one id frame-to-frame, surviving brief detector dropouts.

Two interchangeable trackers (``tracker_config.TrackerType``):
- ``SvByteTrackTracker`` — wraps ``supervision.ByteTrack`` (motion + IoU).
- ``AngularColorTracker`` — angle-around-the-center + color, for circular motion.

``TrackerManager`` is what ``InferenceWorker`` holds: it reads the active tracker
type + that tracker's params from ``machine_params.toml`` on a short TTL and
(re)builds the active tracker when either changes, so the Settings page takes
effect live without a restart. Every tracker is fed a ``TrackUpdate`` (bboxes +
scores + the frame + the channel) each cycle and returns ``{bbox: track_id}``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

try:
    import supervision as sv
except Exception:  # pragma: no cover - supervision is a declared dep; guard dev imports
    sv = None  # type: ignore[assignment]

from .arcs import Bbox
from .angular_tracker import AngularColorTracker
from .ordered_tracker import OrderedChannelTracker
from .tracker_config import (
    ByteTrackConfig,
    TrackerType,
    configFromDict,
)


# Re-read the active tracker + its params from disk at most this often so the
# Settings page takes effect live, without hammering the filesystem.
_CONFIG_TTL_S = 1.0


@dataclass
class TrackUpdate:
    """Everything a tracker may need for one frame. ByteTrack uses bboxes +
    scores; the angular tracker also uses the frame (color) and channel (center)."""

    bboxes: list[Bbox]
    scores: list[float]
    frame_bgr: Any
    channel: Any
    timestamp: float


class SvByteTrackTracker:
    """``supervision.ByteTrack`` wrapper: bboxes + scores in, ids out."""

    def __init__(self, cfg: ByteTrackConfig) -> None:
        self._bt = (
            sv.ByteTrack(
                track_activation_threshold=cfg.track_activation_threshold,
                lost_track_buffer=cfg.lost_track_buffer,
                minimum_matching_threshold=cfg.minimum_matching_threshold,
                frame_rate=cfg.frame_rate,
                minimum_consecutive_frames=cfg.minimum_consecutive_frames,
            )
            if sv is not None
            else None
        )

    @property
    def enabled(self) -> bool:
        return self._bt is not None

    def reset(self) -> None:
        if self._bt is not None:
            self._bt.reset()

    def update(self, upd: TrackUpdate) -> dict[Bbox, int]:
        if self._bt is None:
            return {}
        assert sv is not None  # _bt is non-None only when supervision imported
        bboxes = upd.bboxes
        if not bboxes:
            # Still advance ByteTrack's frame clock so coasting tracks age out.
            self._bt.update_with_detections(sv.Detections.empty())
            return {}
        xyxy = np.asarray(
            [[float(b[0]), float(b[1]), float(b[2]), float(b[3])] for b in bboxes],
            dtype=np.float32,
        )
        conf = np.asarray(
            [float(s) for s in upd.scores] if upd.scores else [1.0] * len(bboxes),
            dtype=np.float32,
        )
        det = sv.Detections(
            xyxy=xyxy, confidence=conf, class_id=np.zeros(len(bboxes), dtype=int)
        )
        out = self._bt.update_with_detections(det)
        result: dict[Bbox, int] = {}
        if out.tracker_id is None:
            return result
        # supervision returns matched detections coordinate-identical to the input
        # boxes, so the int-tuple key round-trips back to the bbox we passed in.
        for i in range(len(out)):
            tid = out.tracker_id[i]
            if tid is None or int(tid) <= 0:
                continue
            row = out.xyxy[i]
            box = (int(row[0]), int(row[1]), int(row[2]), int(row[3]))
            result[box] = int(tid)
        return result


def build_tracker(tracker_type: str, cfg_dict: dict) -> Optional[Any]:
    """Construct the tracker for ``tracker_type`` from its persisted config dict."""
    cfg = configFromDict(tracker_type, cfg_dict)
    if tracker_type == TrackerType.ORDERED.value:
        return OrderedChannelTracker(cfg)
    if tracker_type == TrackerType.ANGULAR.value:
        return AngularColorTracker(cfg)
    tracker = SvByteTrackTracker(cfg)
    return tracker if tracker.enabled else None


def _load_active() -> tuple[str, dict]:
    try:
        from toml_config import getActiveTrackerType, getTrackerConfig

        t = getActiveTrackerType()
        return t, getTrackerConfig(t)
    except Exception:
        return TrackerType.BYTETRACK.value, {}


class TrackerManager:
    """Holds the active tracker, hot-swapping it when the operator changes the
    type or its params on the Settings page (checked at most once per TTL)."""

    def __init__(self) -> None:
        self._key: tuple = ()
        self._type: str = TrackerType.BYTETRACK.value
        self._tracker: Optional[Any] = None
        self._loaded_at: float = 0.0
        self._reload()

    def _reload(self) -> None:
        tracker_type, cfg = _load_active()
        key = (tracker_type, tuple(sorted(cfg.items())))
        if key != self._key:
            self._tracker = build_tracker(tracker_type, cfg)
            self._type = tracker_type
            self._key = key
        self._loaded_at = time.monotonic()

    def _maybe_reload(self) -> None:
        if time.monotonic() - self._loaded_at >= _CONFIG_TTL_S:
            self._reload()

    @property
    def active_type(self) -> str:
        return self._type

    @property
    def enabled(self) -> bool:
        return self._tracker is not None

    def update(
        self,
        bboxes: list[Bbox],
        scores: list[float],
        *,
        frame_bgr: Any = None,
        channel: Any = None,
        timestamp: float = 0.0,
    ) -> dict[Bbox, int]:
        self._maybe_reload()
        if self._tracker is None:
            return {}
        return self._tracker.update(
            TrackUpdate(
                bboxes=bboxes,
                scores=scores,
                frame_bgr=frame_bgr,
                channel=channel,
                timestamp=timestamp,
            )
        )
