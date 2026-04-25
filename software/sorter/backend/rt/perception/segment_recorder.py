"""Collect track path + wedge crops per piece and flush them to SQLite.

One recorder instance serves all perception runners. C4 assigns a piece_uuid
to a tracker global_id at intake; from that point on, every frame this piece
appears in contributes (a) a point to the path and (b) a piece crop once the
piece moved far enough, or enough time passed. A background thread handles JPEG
encoding + disk writes so the perception hot path stays snappy.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Tuple

import cv2
import numpy as np

from blob_manager import write_piece_crop
from local_state import remember_piece_segment

from rt.contracts.events import Event, EventBus, Subscription
from rt.contracts.feed import FeedFrame
from rt.contracts.tracking import TrackBatch
from rt.events.topics import (
    PIECE_CLASSIFIED,
    PIECE_DISTRIBUTED,
    PIECE_REGISTERED,
)
from rt.projections.piece_dossier import refresh_piece_preview_and_push

if False:  # TYPE_CHECKING guard without importing TYPE_CHECKING
    from rt.perception.pipeline_runner import PerceptionRunner

_LOG = logging.getLogger(__name__)

_SEGMENT_ROLE = "carousel"
_SEGMENT_SEQUENCE = 0
_WRITER_QUEUE_MAX = 500
_HEARTBEAT_INTERVAL_S = 0.5
_CROP_CAPTURE_MIN_INTERVAL_S = 0.08
_CROP_CAPTURE_MIN_ANGLE_DEG = 1.5
_CROP_CAPTURE_MAX_PER_PIECE = 80
# Padding around the bbox extent so the wedge clipPath doesn't shave the piece
# at the edges. Angular: n° on each side. Radial: n pixels on each side.
_WEDGE_ANGLE_PADDING_DEG = 1.5
_WEDGE_RADIUS_PADDING_PX = 12.0


def _bbox_polar_extent(
    cx: float,
    cy: float,
    bbox: Tuple[int, int, int, int],
    anchor_deg: float,
) -> Tuple[float, float, float, float]:
    """Return (start_deg, end_deg, r_inner, r_outer) enclosing the bbox.

    Computes the polar coordinates of all 4 bbox corners relative to the
    channel center. Angular extent is min/max of the corner angles (unwrapped
    around ``anchor_deg`` so pieces across the 0°/360° seam stay narrow).
    Radial extent is min/max corner radius — needed so long pieces that poke
    past the channel annulus aren't clipped by the default r_inner/r_outer.
    Both extents are padded so the clipPath doesn't shave the piece.
    """
    x1, y1, x2, y2 = bbox
    corners = ((x1, y1), (x2, y1), (x1, y2), (x2, y2))
    deltas: list[float] = []
    radii: list[float] = []
    for px, py in corners:
        dx = float(px) - cx
        dy = float(py) - cy
        a = math.degrees(math.atan2(dy, dx))
        # Unwrap relative to anchor so the arc stays short across the seam.
        d = ((a - anchor_deg + 180.0) % 360.0) - 180.0
        deltas.append(d)
        radii.append(math.hypot(dx, dy))
    start_deg = anchor_deg + min(deltas) - _WEDGE_ANGLE_PADDING_DEG
    end_deg = anchor_deg + max(deltas) + _WEDGE_ANGLE_PADDING_DEG
    r_inner = max(0.0, min(radii) - _WEDGE_RADIUS_PADDING_PX)
    r_outer = max(radii) + _WEDGE_RADIUS_PADDING_PX
    return start_deg, end_deg, r_inner, r_outer


@dataclass
class _SectorSnapshot:
    sector_index: int
    start_angle_deg: float
    end_angle_deg: float
    r_inner: float
    r_outer: float
    captured_ts: float
    bbox_x: int
    bbox_y: int
    width: int
    height: int
    jpeg_path: str | None = None
    piece_jpeg_path: str | None = None


@dataclass
class _Recording:
    piece_uuid: str
    tracked_global_id: int
    first_seen_ts: float
    last_seen_ts: float
    tracklet_id: str | None = None
    feed_id: str | None = None
    tracker_key: str | None = None
    tracker_epoch: str | None = None
    raw_track_id: int | None = None
    hit_count: int = 0
    path: list[list[float]] = field(default_factory=list)
    sectors: dict[int, _SectorSnapshot] = field(default_factory=dict)
    channel_center_x: float | None = None
    channel_center_y: float | None = None
    channel_radius_inner: float | None = None
    channel_radius_outer: float | None = None
    snapshot_width: int | None = None
    snapshot_height: int | None = None
    snapshot_written: bool = False
    wedge_counter: int = 0
    # Last captured center angle/time. Ghost filtering now runs upstream, so
    # the recorder can be more eager than the old non-overlap sector gate.
    last_wedge_angle_deg: float | None = None
    last_wedge_ts: float | None = None


@dataclass
class _WriteJob:
    piece_uuid: str
    kind: str  # "wedge" | "snapshot"
    idx: int
    jpeg_bytes: bytes


class SegmentRecorder:
    """Per-process sidecar that records track paths and wedge crops.

    Wiring: ``begin_recording`` is called when C4 mints a piece_uuid for a
    tracker global_id (via the PIECE_REGISTERED subscriber). ``on_frame`` is
    called from every perception pipeline tick. ``finalize`` flushes the
    record to SQLite when a terminal piece event arrives.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, _Recording] = {}
        self._track_to_piece: dict[int, str] = {}
        self._polar_center: Tuple[float, float] | None = None
        self._polar_radius_range: Tuple[float, float] | None = None
        self._queue: queue.Queue[_WriteJob | None] = queue.Queue(maxsize=_WRITER_QUEUE_MAX)
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="SegmentRecorderWriter", daemon=True
        )
        self._writer_thread.start()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="SegmentRecorderHeartbeat", daemon=True
        )
        self._heartbeat_thread.start()
        self._subscriptions: list[Subscription] = []

    # ---- Public API ----------------------------------------------------

    def set_channel_geometry(
        self,
        *,
        polar_center: Tuple[float, float] | None,
        polar_radius_range: Tuple[float, float] | None,
    ) -> None:
        with self._lock:
            self._polar_center = polar_center
            self._polar_radius_range = polar_radius_range

    def begin_recording(
        self,
        *,
        piece_uuid: str,
        tracked_global_id: int,
        now_mono: float,
        tracklet_id: str | None = None,
        feed_id: str | None = None,
        tracker_key: str | None = None,
        tracker_epoch: str | None = None,
        raw_track_id: int | None = None,
    ) -> None:
        with self._lock:
            rec = self._records.get(piece_uuid)
            if rec is None:
                rec = _Recording(
                    piece_uuid=piece_uuid,
                    tracked_global_id=int(tracked_global_id),
                    first_seen_ts=float(now_mono),
                    last_seen_ts=float(now_mono),
                    tracklet_id=tracklet_id,
                    feed_id=feed_id,
                    tracker_key=tracker_key,
                    tracker_epoch=tracker_epoch,
                    raw_track_id=(
                        int(raw_track_id)
                        if isinstance(raw_track_id, int)
                        else int(tracked_global_id)
                    ),
                )
                self._records[piece_uuid] = rec
            else:
                if tracklet_id:
                    rec.tracklet_id = tracklet_id
                if feed_id:
                    rec.feed_id = feed_id
                if tracker_key:
                    rec.tracker_key = tracker_key
                if tracker_epoch:
                    rec.tracker_epoch = tracker_epoch
                if isinstance(raw_track_id, int):
                    rec.raw_track_id = raw_track_id
            self._track_to_piece[int(tracked_global_id)] = piece_uuid
            if self._polar_center is not None:
                rec.channel_center_x = float(self._polar_center[0])
                rec.channel_center_y = float(self._polar_center[1])
            if self._polar_radius_range is not None:
                rec.channel_radius_inner = float(self._polar_radius_range[0])
                rec.channel_radius_outer = float(self._polar_radius_range[1])

    def on_frame(self, frame: FeedFrame, raw_tracks: TrackBatch) -> None:
        if frame is None or raw_tracks is None:
            return
        raw = getattr(frame, "raw", None)
        if not isinstance(raw, np.ndarray) or raw.size == 0:
            return
        ts = float(getattr(frame, "monotonic_ts", None) or time.monotonic())
        # Snapshot mapping under the lock, then do image work lock-free.
        per_track: list[tuple[_Recording, Any]] = []
        with self._lock:
            if not self._track_to_piece:
                return
            for track in raw_tracks.tracks:
                gid = getattr(track, "global_id", None)
                if gid is None:
                    continue
                piece_uuid = self._track_to_piece.get(int(gid))
                if piece_uuid is None:
                    continue
                rec = self._records.get(piece_uuid)
                if rec is None:
                    continue
                per_track.append((rec, track))

        if not per_track:
            return

        frame_h, frame_w = int(raw.shape[0]), int(raw.shape[1])

        with self._lock:
            for rec, track in per_track:
                rec.hit_count += 1
                rec.last_seen_ts = ts
                if rec.snapshot_width is None:
                    rec.snapshot_width = frame_w
                    rec.snapshot_height = frame_h
                if not rec.snapshot_written:
                    rec.snapshot_written = True
                    self._enqueue_crop(
                        piece_uuid=rec.piece_uuid,
                        kind="snapshot",
                        idx=0,
                        crop_bytes=raw,
                    )

                bbox = getattr(track, "bbox_xyxy", None)
                cx, cy = self._bbox_center(bbox)
                if cx is not None and cy is not None:
                    rec.path.append([ts, float(cx), float(cy)])

                angle_rad = getattr(track, "angle_rad", None)
                if not isinstance(angle_rad, (int, float)):
                    continue
                angle_deg = math.degrees(float(angle_rad))
                if rec.channel_center_x is None or rec.channel_center_y is None:
                    continue  # no geometry yet → can't compute polar extent
                bbox_crop = self._bbox_to_crop(bbox, frame_w, frame_h)
                if bbox_crop is None:
                    continue
                x0, y0, x1, y1 = bbox_crop
                start_deg, end_deg, r_in, r_out = _bbox_polar_extent(
                    rec.channel_center_x,
                    rec.channel_center_y,
                    (x0, y0, x1, y1),
                    angle_deg,
                )
                if rec.wedge_counter >= _CROP_CAPTURE_MAX_PER_PIECE:
                    continue
                if rec.last_wedge_angle_deg is not None and rec.last_wedge_ts is not None:
                    angle_delta = abs(
                        ((angle_deg - rec.last_wedge_angle_deg + 180.0) % 360.0)
                        - 180.0
                    )
                    elapsed_s = max(0.0, ts - rec.last_wedge_ts)
                    if (
                        angle_delta < _CROP_CAPTURE_MIN_ANGLE_DEG
                        and elapsed_s < _CROP_CAPTURE_MIN_INTERVAL_S
                    ):
                        continue
                idx = rec.wedge_counter
                rec.wedge_counter += 1
                rec.last_wedge_angle_deg = angle_deg
                rec.last_wedge_ts = ts
                crop_path = f"piece_crops/{rec.piece_uuid}/seg{_SEGMENT_SEQUENCE}/wedge_{idx:03d}.jpg"
                rec.sectors[idx] = _SectorSnapshot(
                    sector_index=idx,
                    start_angle_deg=start_deg,
                    end_angle_deg=end_deg,
                    r_inner=r_in,
                    r_outer=r_out,
                    captured_ts=ts,
                    bbox_x=x0,
                    bbox_y=y0,
                    width=x1 - x0,
                    height=y1 - y0,
                    jpeg_path=crop_path,
                    piece_jpeg_path=crop_path,
                )
                self._enqueue_crop(
                    piece_uuid=rec.piece_uuid,
                    kind="wedge",
                    idx=idx,
                    crop_bytes=raw[y0:y1, x0:x1],
                )

    def finalize(self, piece_uuid: str) -> None:
        with self._lock:
            rec = self._records.pop(piece_uuid, None)
            if rec is not None:
                self._track_to_piece.pop(rec.tracked_global_id, None)
        if rec is None:
            return
        self._persist(rec)

    def flush_snapshot(self, piece_uuid: str) -> None:
        """Write an intermediate DB row without tearing down the recording."""
        with self._lock:
            rec = self._records.get(piece_uuid)
            if rec is None:
                return
            snapshot = _Recording(
                piece_uuid=rec.piece_uuid,
                tracked_global_id=rec.tracked_global_id,
                first_seen_ts=rec.first_seen_ts,
                last_seen_ts=rec.last_seen_ts,
                tracklet_id=rec.tracklet_id,
                feed_id=rec.feed_id,
                tracker_key=rec.tracker_key,
                tracker_epoch=rec.tracker_epoch,
                raw_track_id=rec.raw_track_id,
                hit_count=rec.hit_count,
                path=list(rec.path),
                sectors=dict(rec.sectors),
                channel_center_x=rec.channel_center_x,
                channel_center_y=rec.channel_center_y,
                channel_radius_inner=rec.channel_radius_inner,
                channel_radius_outer=rec.channel_radius_outer,
                snapshot_width=rec.snapshot_width,
                snapshot_height=rec.snapshot_height,
                snapshot_written=rec.snapshot_written,
                wedge_counter=rec.wedge_counter,
                last_wedge_angle_deg=rec.last_wedge_angle_deg,
                last_wedge_ts=rec.last_wedge_ts,
            )
        self._persist(snapshot)

    def set_subscriptions(self, subscriptions: list[Subscription]) -> None:
        self._subscriptions = list(subscriptions)

    def close(self) -> None:
        """Detach event hooks and stop background workers."""

        for subscription in list(self._subscriptions):
            try:
                subscription.unsubscribe()
            except Exception:
                _LOG.debug("segment_recorder: unsubscribe raised", exc_info=True)
        self._subscriptions = []
        self._heartbeat_stop.set()
        if self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)
        try:
            self._queue.put(None, timeout=1.0)
        except queue.Full:
            _LOG.warning("segment_recorder: writer queue stayed full during close")
        if self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.0)

    # ---- Internals -----------------------------------------------------

    @staticmethod
    def _bbox_center(bbox: Any) -> Tuple[float | None, float | None]:
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
            return None, None
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            return None, None
        return (x1 + x2) * 0.5, (y1 + y2) * 0.5

    @staticmethod
    def _bbox_to_crop(
        bbox: Any, frame_w: int, frame_h: int
    ) -> Tuple[int, int, int, int] | None:
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
            return None
        try:
            x1, y1, x2, y2 = (int(round(float(v))) for v in bbox)
        except (TypeError, ValueError):
            return None
        x0 = max(0, min(frame_w - 1, x1))
        y0 = max(0, min(frame_h - 1, y1))
        x1c = max(0, min(frame_w, x2))
        y1c = max(0, min(frame_h, y2))
        if x1c - x0 <= 1 or y1c - y0 <= 1:
            return None
        return x0, y0, x1c, y1c

    def _enqueue_crop(
        self,
        *,
        piece_uuid: str,
        kind: str,
        idx: int,
        crop_bytes: np.ndarray,
    ) -> None:
        if crop_bytes is None or crop_bytes.size == 0:
            return
        # Copy the view so the frame buffer can be freed without racing.
        buf = np.ascontiguousarray(crop_bytes)
        ok, encoded = cv2.imencode(".jpg", buf, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return
        job = _WriteJob(
            piece_uuid=piece_uuid,
            kind=kind,
            idx=idx,
            jpeg_bytes=encoded.tobytes(),
        )
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            _LOG.warning(
                "segment_recorder: writer queue full, dropping %s crop for %s",
                kind, piece_uuid,
            )

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(_HEARTBEAT_INTERVAL_S):
            with self._lock:
                uuids = list(self._records.keys())
            for piece_uuid in uuids:
                try:
                    self.flush_snapshot(piece_uuid)
                except Exception:
                    _LOG.exception(
                        "segment_recorder: heartbeat flush failed (%s)", piece_uuid
                    )

    def _writer_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                write_piece_crop(
                    piece_uuid=job.piece_uuid,
                    sequence=_SEGMENT_SEQUENCE,
                    kind=job.kind,
                    idx=job.idx,
                    jpeg_bytes=job.jpeg_bytes,
                )
            except Exception:
                _LOG.exception(
                    "segment_recorder: write_piece_crop failed (%s/%d)",
                    job.kind, job.idx,
                )

    def _persist(self, rec: _Recording) -> None:
        sector_payloads = [
            {
                "sector_index": s.sector_index,
                "start_angle_deg": s.start_angle_deg,
                "end_angle_deg": s.end_angle_deg,
                "r_inner": s.r_inner,
                "r_outer": s.r_outer,
                "captured_ts": s.captured_ts,
                "bbox_x": s.bbox_x,
                "bbox_y": s.bbox_y,
                "width": s.width,
                "height": s.height,
                "jpeg_path": s.jpeg_path,
                "piece_jpeg_path": s.piece_jpeg_path,
            }
            for s in sorted(rec.sectors.values(), key=lambda s: s.sector_index)
        ]
        snapshot_path = (
            f"piece_crops/{rec.piece_uuid}/seg{_SEGMENT_SEQUENCE}/snapshot_000.jpg"
            if rec.snapshot_written
            else None
        )
        duration_s = max(0.0, float(rec.last_seen_ts) - float(rec.first_seen_ts))
        payload: dict[str, Any] = {
            "first_seen_ts": rec.first_seen_ts,
            "last_seen_ts": rec.last_seen_ts,
            "duration_s": duration_s,
            "hit_count": rec.hit_count,
            "tracked_global_id": rec.tracked_global_id,
            "tracklet_id": rec.tracklet_id,
            "feed_id": rec.feed_id,
            "tracker_key": rec.tracker_key,
            "tracker_epoch": rec.tracker_epoch,
            "raw_track_id": rec.raw_track_id,
            "path": rec.path,
            "sector_snapshots": sector_payloads,
            "sector_count": len(sector_payloads),
            "channel_center_x": rec.channel_center_x,
            "channel_center_y": rec.channel_center_y,
            "channel_radius_inner": rec.channel_radius_inner,
            "channel_radius_outer": rec.channel_radius_outer,
            "snapshot_width": rec.snapshot_width,
            "snapshot_height": rec.snapshot_height,
            "snapshot_path": snapshot_path,
        }
        try:
            remember_piece_segment(
                rec.piece_uuid, _SEGMENT_ROLE, _SEGMENT_SEQUENCE, payload
            )
            refresh_piece_preview_and_push(rec.piece_uuid, broadcast=True)
        except Exception:
            _LOG.exception(
                "segment_recorder: remember_piece_segment failed (%s)",
                rec.piece_uuid,
            )


def install(
    bus: EventBus,
    c4_runner: "PerceptionRunner",
) -> SegmentRecorder:
    """Instantiate the recorder and wire it into the rt runtime.

    - Pulls channel geometry from the C4 tracker (arc channels use
      PolygonZone, so the zone itself does not carry polar geometry).
    - Attaches the recorder to the C4 pipeline so ``on_frame`` fires
      every perception tick.
    - Subscribes begin/flush/finalize to the three piece-lifecycle topics.

    Returns the recorder so callers can inspect it in tests.
    """
    recorder = SegmentRecorder()
    tracker = c4_runner._pipeline.tracker
    recorder.set_channel_geometry(
        polar_center=getattr(tracker, "_polar_center", None),
        polar_radius_range=getattr(tracker, "_polar_radius_range", None),
    )
    c4_runner._pipeline.segment_recorder = recorder

    def _on_piece_event(event: Event) -> None:
        payload = event.payload or {}
        piece_uuid = payload.get("piece_uuid") or payload.get("uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            return
        try:
            if event.topic == PIECE_REGISTERED:
                tracked_gid = payload.get("tracked_global_id")
                if isinstance(tracked_gid, int):
                    tracklet_id = payload.get("tracklet_id")
                    if not isinstance(tracklet_id, str) or not tracklet_id.strip():
                        tracklet_id = payload.get("current_tracklet_id")
                    recorder.begin_recording(
                        piece_uuid=piece_uuid,
                        tracked_global_id=tracked_gid,
                        now_mono=float(event.ts_mono),
                        tracklet_id=tracklet_id
                        if isinstance(tracklet_id, str) and tracklet_id.strip()
                        else None,
                        feed_id=payload.get("feed_id")
                        if isinstance(payload.get("feed_id"), str)
                        else None,
                        tracker_key=payload.get("tracker_key")
                        if isinstance(payload.get("tracker_key"), str)
                        else None,
                        tracker_epoch=payload.get("tracker_epoch")
                        if isinstance(payload.get("tracker_epoch"), str)
                        else None,
                        raw_track_id=payload.get("raw_track_id")
                        if isinstance(payload.get("raw_track_id"), int)
                        else tracked_gid,
                    )
            elif event.topic == PIECE_CLASSIFIED:
                recorder.flush_snapshot(piece_uuid)
            elif event.topic == PIECE_DISTRIBUTED:
                recorder.finalize(piece_uuid)
        except Exception:
            _LOG.exception(
                "segment_recorder: hook raised for topic=%s", event.topic
            )

    subscriptions = [
        bus.subscribe(topic, _on_piece_event)
        for topic in (PIECE_REGISTERED, PIECE_CLASSIFIED, PIECE_DISTRIBUTED)
    ]
    recorder.set_subscriptions(subscriptions)
    return recorder


__all__ = ["SegmentRecorder", "install"]
