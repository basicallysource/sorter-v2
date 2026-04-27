from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol

from rt.contracts.detection import DetectionBatch, Detector
from rt.contracts.feed import Feed, FeedFrame, Zone
from rt.contracts.tracking import TrackBatch, Tracker


@dataclass(frozen=True, slots=True)
class FrameWithDetections:
    frame: FeedFrame
    detections: DetectionBatch
    tracks: TrackBatch
    piece_uuid: str


@dataclass(slots=True)
class FreeFallCaptureResult:
    piece_uuid: str
    frames: list[FrameWithDetections] = field(default_factory=list)
    reason: str = "unknown"
    started_at_mono: float = 0.0
    ended_at_mono: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(0.0, float(self.ended_at_mono) - float(self.started_at_mono))


class _FrameSource(Protocol):
    def frames_until(
        self,
        *,
        feed_id: str,
        deadline_mono: float,
        stop: Callable[[], bool],
    ) -> Iterable[FeedFrame]: ...


class FreeFallCaptureWorker:
    """Capture the short C3->C4 free-fall window through Detector + Tracker."""

    def __init__(
        self,
        *,
        feed: Feed | None = None,
        detector: Detector,
        tracker: Tracker,
        zone: Zone,
        frame_source: _FrameSource | None = None,
        feed_id: str = "c4_feed",
        max_window_s: float = 0.8,
        no_detection_timeout_s: float = 0.2,
        settle_velocity_px_s: float = 25.0,
        settle_frames: int = 3,
        poll_s: float = 0.01,
        logger: logging.Logger | None = None,
    ) -> None:
        if feed is None and frame_source is None:
            raise ValueError("feed or frame_source is required")
        self._feed = feed
        self._detector = detector
        self._tracker = tracker
        self._zone = zone
        self._frame_source = frame_source
        self._feed_id = feed_id
        self._max_window_s = max(0.01, float(max_window_s))
        self._no_detection_timeout_s = max(0.0, float(no_detection_timeout_s))
        self._settle_velocity_px_s = max(0.0, float(settle_velocity_px_s))
        self._settle_frames = max(1, int(settle_frames))
        self._poll_s = max(0.0, float(poll_s))
        self._logger = logger or logging.getLogger("rt.free_fall_capture")

    def capture(
        self,
        piece_uuid: str,
        *,
        now_mono: float | None = None,
    ) -> FreeFallCaptureResult:
        started = time.monotonic() if now_mono is None else float(now_mono)
        deadline = started + self._max_window_s
        result = FreeFallCaptureResult(
            piece_uuid=str(piece_uuid),
            started_at_mono=started,
            ended_at_mono=started,
        )
        first_detection_at: float | None = None
        stable_count = 0
        previous_center: tuple[float, float, float] | None = None
        last_seq: int | None = None

        def stop() -> bool:
            return time.monotonic() >= deadline

        for frame in self._iter_frames(deadline, stop):
            frame_mono = getattr(frame, "monotonic_ts", None)
            now = (
                float(frame_mono)
                if isinstance(frame_mono, (int, float))
                else time.monotonic()
            )
            if frame.frame_seq == last_seq:
                continue
            last_seq = frame.frame_seq
            try:
                detections = self._detector.detect(frame, self._zone)
                tracks = self._tracker.update(detections, frame)
            except Exception:
                self._logger.exception("FreeFallCaptureWorker: processing raised")
                result.reason = "processing_raised"
                break
            result.frames.append(
                FrameWithDetections(
                    frame=frame,
                    detections=self._annotate_detections(detections, piece_uuid),
                    tracks=tracks,
                    piece_uuid=str(piece_uuid),
                )
            )
            if detections.detections and first_detection_at is None:
                first_detection_at = now
            center = self._best_center(tracks)
            if center is not None and previous_center is not None:
                dt = max(1e-6, center[2] - previous_center[2])
                velocity = math.hypot(
                    center[0] - previous_center[0],
                    center[1] - previous_center[1],
                ) / dt
                if velocity <= self._settle_velocity_px_s:
                    stable_count += 1
                else:
                    stable_count = 0
                if stable_count >= self._settle_frames:
                    result.reason = "settled"
                    break
            if center is not None:
                previous_center = center
            if (
                first_detection_at is None
                and now - started >= self._no_detection_timeout_s
            ):
                result.reason = "no_detection_timeout"
                break
            if now >= deadline:
                result.reason = "max_window"
                break
        else:
            result.reason = "max_window" if time.monotonic() >= deadline else "exhausted"
        if not result.reason or result.reason == "unknown":
            result.reason = "max_window"
        result.ended_at_mono = max(result.started_at_mono, time.monotonic())
        return result

    def _iter_frames(
        self,
        deadline_mono: float,
        stop: Callable[[], bool],
    ) -> Iterable[FeedFrame]:
        if self._frame_source is not None:
            yield from self._frame_source.frames_until(
                feed_id=self._feed_id,
                deadline_mono=deadline_mono,
                stop=stop,
            )
            return
        assert self._feed is not None
        while not stop():
            frame = self._feed.latest()
            if frame is not None:
                yield frame
            if self._poll_s:
                time.sleep(self._poll_s)

    def _annotate_detections(
        self, detections: DetectionBatch, piece_uuid: str
    ) -> DetectionBatch:
        annotated = []
        for det in detections.detections:
            meta = dict(det.meta)
            meta["piece_uuid"] = str(piece_uuid)
            annotated.append(
                type(det)(
                    bbox_xyxy=det.bbox_xyxy,
                    score=det.score,
                    class_id=det.class_id,
                    mask=det.mask,
                    meta=meta,
                )
            )
        return DetectionBatch(
            feed_id=detections.feed_id,
            frame_seq=detections.frame_seq,
            timestamp=detections.timestamp,
            detections=tuple(annotated),
            algorithm=detections.algorithm,
            latency_ms=detections.latency_ms,
        )

    def _best_center(self, tracks: TrackBatch) -> tuple[float, float, float] | None:
        if not tracks.tracks:
            return None
        track = max(tracks.tracks, key=lambda t: (t.score, t.hit_count))
        x1, y1, x2, y2 = track.bbox_xyxy
        return (
            (float(x1) + float(x2)) / 2.0,
            (float(y1) + float(y2)) / 2.0,
            float(tracks.timestamp),
        )


__all__ = [
    "FrameWithDetections",
    "FreeFallCaptureResult",
    "FreeFallCaptureWorker",
]
