from __future__ import annotations

from dataclasses import dataclass

from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame, RectZone
from rt.contracts.tracking import Track, TrackBatch
from rt.perception.free_fall_capture import FreeFallCaptureWorker


@dataclass
class _FrameSource:
    frames: list[FeedFrame]

    def frames_until(self, *, feed_id, deadline_mono, stop):
        yield from self.frames


class _Detector:
    key = "fake"

    def detect(self, frame, zone):
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=(
                Detection(bbox_xyxy=(10, 10, 20, 20), score=0.9),
            ),
            algorithm="fake",
            latency_ms=0.0,
        )


class _Tracker:
    key = "fake"

    def __init__(self, boxes):
        self._boxes = list(boxes)
        self._i = 0

    def update(self, detections, frame):
        box = self._boxes[min(self._i, len(self._boxes) - 1)]
        self._i += 1
        return TrackBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            tracks=(
                Track(
                    track_id=1,
                    global_id=1,
                    piece_uuid=None,
                    bbox_xyxy=box,
                    score=0.9,
                    confirmed_real=True,
                    angle_rad=None,
                    radius_px=None,
                    hit_count=self._i,
                    first_seen_ts=frame.timestamp,
                    last_seen_ts=frame.timestamp,
                ),
            ),
            lost_track_ids=(),
        )


def _frame(seq: int, ts: float) -> FeedFrame:
    return FeedFrame(
        feed_id="c4_feed",
        camera_id="cam",
        raw=None,
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def test_capture_annotates_detections_and_stops_when_settled() -> None:
    frames = [_frame(1, 0.0), _frame(2, 0.1), _frame(3, 0.2), _frame(4, 0.3)]
    tracker = _Tracker(
        [
            (0, 0, 10, 10),
            (2, 0, 12, 10),
            (3, 0, 13, 10),
            (4, 0, 14, 10),
        ]
    )
    worker = FreeFallCaptureWorker(
        detector=_Detector(),
        tracker=tracker,
        zone=RectZone(0, 0, 100, 100),
        frame_source=_FrameSource(frames),
        settle_velocity_px_s=30.0,
        settle_frames=2,
    )

    result = worker.capture("piece-1", now_mono=0.0)

    assert result.reason == "settled"
    assert result.frames
    assert result.frames[0].detections.detections[0].meta["piece_uuid"] == "piece-1"
