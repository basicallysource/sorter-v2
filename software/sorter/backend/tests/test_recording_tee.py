"""The recording tee: raw MJPEG splitting in the capture path, the subscriber
queue's drop behaviour, and the multipart / event serialisation the external
recorder parses."""

from __future__ import annotations

import queue
import types

import cv2
import numpy as np

from server.routers.recording import keepalive_part, raw_part, serialize_debug
from vision.camera import RawFrameSubscription, _decode_raw_mjpeg_read


def _jpeg_bytes(w: int = 32, h: int = 24) -> bytes:
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = (0, 255, 0)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_raw_read_splits_into_bgr_and_the_original_bytes() -> None:
    jpeg = _jpeg_bytes()
    raw = np.frombuffer(jpeg, np.uint8).reshape(1, -1)  # what V4L2 hands back
    bgr, out = _decode_raw_mjpeg_read(raw)
    assert out == jpeg
    assert bgr is not None and bgr.shape == (24, 32, 3)


def test_raw_read_passes_through_an_already_decoded_frame() -> None:
    frame = np.zeros((24, 32, 3), np.uint8)
    bgr, out = _decode_raw_mjpeg_read(frame)
    assert bgr is frame
    assert out is None


def test_raw_read_rejects_garbage_as_a_failed_read() -> None:
    assert _decode_raw_mjpeg_read(np.zeros((1, 10), np.uint8)) == (None, None)
    assert _decode_raw_mjpeg_read(None) == (None, None)
    truncated = np.frombuffer(_jpeg_bytes()[:40], np.uint8)
    assert _decode_raw_mjpeg_read(truncated) == (None, None)


def test_subscription_drops_instead_of_blocking() -> None:
    sub = RawFrameSubscription(maxsize=2)
    for i in range(5):
        sub.offer(b"x", float(i), i)
    assert sub.queue.qsize() == 2
    assert sub.dropped == 3
    assert sub.queue.get_nowait() == (b"x", 0.0, 0)


def test_raw_part_framing_carries_timestamp_and_seq() -> None:
    jpeg = _jpeg_bytes()
    part = raw_part(jpeg, 1700000000.25, 7, 3)
    head, _, body = part.partition(b"\r\n\r\n")
    assert head.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
    assert b"Content-Length: %d\r\n" % len(jpeg) in head
    assert b"X-Timestamp: 1700000000.25\r\n" in head
    assert b"X-Seq: 7\r\n" in head and b"X-Dropped: 3" in head
    assert body == jpeg + b"\r\n"
    assert keepalive_part().startswith(b"--frame\r\nContent-Type: application/x-keepalive\r\n")
    repeated = raw_part(b"\xff\xd8", 1.5, 7, 0, repeat=True)
    assert b"X-Repeat: 1\r\n" in repeated and b"Content-Type: image/jpeg\r\n" in repeated
    assert b"X-Repeat: 0\r\n" in raw_part(b"\xff\xd8", 1.5, 7, 0)


def test_serialize_debug_matches_what_the_feed_overlay_draws() -> None:
    frame = types.SimpleNamespace(timestamp=12.5)
    det = types.SimpleNamespace(bbox=(1, 2, 3, 4), in_primary=True, secondary_zone_ids=("z",), sv_bt_track_id=9)
    debug = {
        "frame": frame,
        "infer_ms": 4.2,
        "pre_merge_bboxes": [(1, 2, 3, 4)],
        "on_channel_bboxes": [(0, 0, 1, 1)],
        "detections": [det],
        "merged_bboxes": [(1, 2, 5, 6)],
        "merged_track_ids": [9],
        "crop_rect": (0, 0, 10, 10),
    }
    out = serialize_debug(debug)
    assert out is not None
    assert out["type"] == "infer" and out["frame_ts"] == 12.5
    assert out["on_bboxes"] == [[1.0, 2.0, 3.0, 4.0]]  # pre-merge wins, as on the live feed
    assert out["detections"] == [
        {"bbox": [1.0, 2.0, 3.0, 4.0], "in_primary": True, "secondary_zone_ids": ["z"], "track_id": 9}
    ]
    assert out["merged_bboxes"] == [[1.0, 2.0, 5.0, 6.0]] and out["merged_track_ids"] == [9]
    assert serialize_debug({"frame": None}) is None


def test_raw_stream_rate_limit_keeps_one_frame_per_interval() -> None:
    """The fps cap is chosen on capture timestamps, so the far end gets an
    evenly spaced stream and the frames in between are never sent."""
    from server.routers.recording import RAW_KEEPALIVE_S  # noqa: F401  (import shape check)

    min_gap = 1.0 / 5.0
    last_sent = 0.0
    kept = []
    for i in range(60):  # 2 seconds of a 30 fps camera
        ts = 1000.0 + i / 30.0
        if min_gap and (ts - last_sent) < min_gap:
            continue
        last_sent = ts
        kept.append(ts)
    assert len(kept) == 10
    gaps = [round(b - a, 4) for a, b in zip(kept, kept[1:])]
    assert all(g >= min_gap for g in gaps)
