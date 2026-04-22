from __future__ import annotations

import numpy as np

import rt.perception  # noqa: F401 - trigger detector registration
from rt.contracts.feed import FeedFrame, RectZone
from rt.contracts.registry import DETECTORS
from rt.perception.detectors.mog2 import Mog2Detector


def _frame(raw: np.ndarray, seq: int, ts: float = 1.0) -> FeedFrame:
    return FeedFrame(
        feed_id="test_feed",
        camera_id="cam0",
        raw=raw,
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def test_mog2_registered_in_registry() -> None:
    assert "mog2" in DETECTORS.keys()


def test_mog2_detects_moving_rect_after_bootstrap() -> None:
    det = Mog2Detector(min_area_px=50, blur_kernel=3, morph_kernel=3)
    zone = RectZone(x=0, y=0, w=200, h=200)

    # Warm up with a static background.
    bg = np.full((200, 200, 3), 40, dtype=np.uint8)
    for i in range(30):
        det.detect(_frame(bg, seq=i, ts=float(i) * 0.1), zone)

    # Introduce a bright moving rectangle.
    saw_detection = False
    for i in range(30, 45):
        frame = bg.copy()
        x = 20 + (i - 30) * 4
        frame[60:110, x : x + 30] = 220
        batch = det.detect(_frame(frame, seq=i, ts=float(i) * 0.1), zone)
        if batch.detections:
            saw_detection = True
            for d in batch.detections:
                x1, y1, x2, y2 = d.bbox_xyxy
                assert x2 > x1 and y2 > y1
                assert 0 <= x1 < 200 and 0 <= y1 < 200
            break

    assert saw_detection, "MOG2 should have detected the moving rectangle"


def test_mog2_respects_zone_mask() -> None:
    det = Mog2Detector(min_area_px=50, blur_kernel=3, morph_kernel=3)
    # Zone covers only the top-left quadrant.
    zone = RectZone(x=0, y=0, w=100, h=100)

    bg = np.full((200, 200, 3), 40, dtype=np.uint8)
    for i in range(30):
        det.detect(_frame(bg, seq=i, ts=float(i) * 0.1), zone)

    # Motion in the BOTTOM-RIGHT (outside the zone).
    frame = bg.copy()
    frame[140:180, 140:180] = 220
    batch = det.detect(_frame(frame, seq=50, ts=5.0), zone)
    for d in batch.detections:
        x1, y1, x2, y2 = d.bbox_xyxy
        # Any detection must lie inside the zone.
        assert x1 < 100 and y1 < 100


def test_mog2_reset_clears_background_model() -> None:
    det = Mog2Detector(min_area_px=50)
    zone = RectZone(x=0, y=0, w=100, h=100)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    for i in range(10):
        det.detect(_frame(frame, seq=i), zone)
    det.reset()
    # After reset we must be back in bootstrap (no detections even on change).
    bright = np.full((100, 100, 3), 220, dtype=np.uint8)
    batch = det.detect(_frame(bright, seq=100), zone)
    assert batch.detections == ()
