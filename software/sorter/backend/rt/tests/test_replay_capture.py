from __future__ import annotations

import json

import numpy as np

from rt.contracts.feed import FeedFrame, RectZone
from rt.perception.replay_capture import DetectorInputRecorder


class _Detector:
    key = "fake_detector"

    def _apply_zone(self, raw, zone):
        return np.ascontiguousarray(raw[2:7, 3:9]), (3, 2)


class _Tracker:
    key = "fake_tracker"
    _polar_center = (10.0, 8.0)
    _polar_radius_range = (3.0, 12.0)


def test_detector_input_recorder_writes_lossless_crop_and_manifest(tmp_path) -> None:
    raw = np.zeros((12, 14, 3), dtype=np.uint8)
    raw[2:7, 3:9] = (10, 20, 30)
    frame = FeedFrame(
        feed_id="c4_feed",
        camera_id="cam-test",
        raw=raw,
        gray=None,
        timestamp=1.25,
        monotonic_ts=9.5,
        frame_seq=42,
    )
    recorder = DetectorInputRecorder(
        feed_id="c4_feed",
        detector_key="fake_detector",
        tracker_key="fake_tracker",
        zone=RectZone(x=0, y=0, w=14, h=12),
        tracker=_Tracker(),
        max_frames=1,
        root_dir=tmp_path,
    )

    recorder.capture(
        frame=frame,
        detector=_Detector(),
        zone=RectZone(x=0, y=0, w=14, h=12),
        tracker=_Tracker(),
    )

    status = recorder.status()
    assert status["active"] is False
    assert status["frame_count"] == 1
    root = tmp_path / status["capture_id"]
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["feed_id"] == "c4_feed"
    records = [
        json.loads(line)
        for line in (root / "frames.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["crop_bounds_xyxy"] == [3, 2, 9, 7]
    assert record["tracker_params"]["polar_center"] == [7.0, 6.0]
    crop = np.load(root / record["crop_npy"])
    assert crop.shape == (5, 6, 3)
    assert crop.dtype == np.uint8
    assert crop[0, 0].tolist() == [10, 20, 30]
