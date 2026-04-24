from __future__ import annotations

import math
import unittest
from unittest import mock

import numpy as np

from rt.contracts.feed import FeedFrame
from rt.contracts.tracking import Track, TrackBatch
from rt.perception import segment_recorder


def _frame(ts: float, seq: int) -> FeedFrame:
    raw = np.zeros((120, 120, 3), dtype=np.uint8)
    raw[40:60, 70:90] = (255, 255, 255)
    return FeedFrame(
        feed_id="c4_feed",
        camera_id="cam-test",
        raw=raw,
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def _tracks(ts: float, seq: int, angle_deg: float) -> TrackBatch:
    track = Track(
        track_id=1,
        global_id=42,
        piece_uuid=None,
        bbox_xyxy=(70, 40, 90, 60),
        score=0.9,
        confirmed_real=True,
        angle_rad=math.radians(angle_deg),
        radius_px=30.0,
        hit_count=seq + 1,
        first_seen_ts=1.0,
        last_seen_ts=ts,
    )
    return TrackBatch(
        feed_id="c4_feed",
        frame_seq=seq,
        timestamp=ts,
        tracks=(track,),
        lost_track_ids=(),
    )


class SegmentRecorderTests(unittest.TestCase):
    def test_captures_immediate_and_dense_piece_crops(self) -> None:
        payloads: list[dict] = []

        recorder = segment_recorder.SegmentRecorder()
        recorder.set_channel_geometry(
            polar_center=(60.0, 60.0),
            polar_radius_range=(10.0, 55.0),
        )
        recorder.begin_recording(
            piece_uuid="piece-fast-crops",
            tracked_global_id=42,
            now_mono=1.0,
        )

        with (
            mock.patch.object(segment_recorder, "write_piece_crop", return_value=None),
            mock.patch.object(
                segment_recorder,
                "remember_piece_segment",
                side_effect=lambda _uuid, _role, _seq, payload: payloads.append(payload),
            ),
            mock.patch.object(segment_recorder, "refresh_piece_preview_and_push"),
        ):
            recorder.on_frame(_frame(1.00, 0), _tracks(1.00, 0, 0.0))
            recorder.on_frame(_frame(1.03, 1), _tracks(1.03, 1, 0.5))
            recorder.on_frame(_frame(1.04, 2), _tracks(1.04, 2, 2.0))
            recorder.on_frame(_frame(1.13, 3), _tracks(1.13, 3, 2.1))
            recorder.flush_snapshot("piece-fast-crops")

        self.assertEqual(1, len(payloads))
        sectors = payloads[0]["sector_snapshots"]
        self.assertEqual(3, len(sectors))
        self.assertEqual(
            "piece_crops/piece-fast-crops/seg0/wedge_000.jpg",
            sectors[0]["jpeg_path"],
        )
        self.assertEqual(sectors[0]["jpeg_path"], sectors[0]["piece_jpeg_path"])
        self.assertEqual([0, 1, 2], [sector["sector_index"] for sector in sectors])
        self.assertEqual([1.00, 1.04, 1.13], [sector["captured_ts"] for sector in sectors])


if __name__ == "__main__":
    unittest.main()
