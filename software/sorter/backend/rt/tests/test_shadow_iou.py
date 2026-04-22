from __future__ import annotations

import time
from dataclasses import dataclass

from rt.events.bus import InProcessEventBus
from rt.events.topics import RT_SHADOW_IOU
from rt.shadow.iou import (
    RollingIouTracker,
    bbox_iou,
    compute_frame_iou,
)


@dataclass(frozen=True)
class _FakeTrack:
    bbox_xyxy: tuple[int, int, int, int]


@dataclass(frozen=True)
class _LegacyTrack:
    bbox: tuple[int, int, int, int]


def test_bbox_iou_identical_boxes() -> None:
    box = (0, 0, 10, 10)
    assert bbox_iou(box, box) == 1.0


def test_bbox_iou_disjoint_boxes() -> None:
    assert bbox_iou((0, 0, 5, 5), (100, 100, 110, 110)) == 0.0


def test_bbox_iou_half_overlap() -> None:
    # Two 10x10 boxes overlapping on a 5x10 strip → inter=50, union=150.
    iou = bbox_iou((0, 0, 10, 10), (5, 0, 15, 10))
    assert abs(iou - (50.0 / 150.0)) < 1e-9


def test_bbox_iou_degenerate_inputs_zero() -> None:
    assert bbox_iou((5, 5, 5, 5), (0, 0, 10, 10)) == 0.0
    assert bbox_iou((0, 0, 10, 10), (5, 5, 5, 5)) == 0.0


def test_compute_frame_iou_both_empty_is_one() -> None:
    assert compute_frame_iou([], []) == 1.0


def test_compute_frame_iou_one_empty_is_zero() -> None:
    assert compute_frame_iou([_FakeTrack((0, 0, 10, 10))], []) == 0.0
    assert compute_frame_iou([], [_LegacyTrack((0, 0, 10, 10))]) == 0.0


def test_compute_frame_iou_identical_sets() -> None:
    new = [_FakeTrack((0, 0, 10, 10)), _FakeTrack((20, 20, 30, 30))]
    legacy = [_LegacyTrack((0, 0, 10, 10)), _LegacyTrack((20, 20, 30, 30))]
    assert compute_frame_iou(new, legacy) == 1.0


def test_compute_frame_iou_accepts_new_and_legacy_shapes() -> None:
    new = [_FakeTrack((0, 0, 10, 10))]
    legacy = [_LegacyTrack((0, 0, 10, 10))]
    assert compute_frame_iou(new, legacy) == 1.0


def test_compute_frame_iou_partial_match_penalizes_extras() -> None:
    # one perfect match + one extra on new side = 0.5 (perfect/2)
    new = [_FakeTrack((0, 0, 10, 10)), _FakeTrack((100, 100, 110, 110))]
    legacy = [_LegacyTrack((0, 0, 10, 10))]
    iou = compute_frame_iou(new, legacy)
    assert abs(iou - 0.5) < 1e-9


def test_rolling_mean_initial_state() -> None:
    t = RollingIouTracker(window_sec=10.0)
    assert t.mean_iou() == 0.0
    assert t.sample_count() == 0


def test_rolling_mean_after_records() -> None:
    t = RollingIouTracker(window_sec=10.0)
    box_a = _FakeTrack((0, 0, 10, 10))
    box_b = _LegacyTrack((0, 0, 10, 10))
    # Two perfect matches in quick succession.
    now = time.monotonic()
    t.record([box_a], [box_b], timestamp=now)
    t.record([box_a], [box_b], timestamp=now + 0.1)
    assert t.mean_iou(now=now + 0.2) == 1.0
    assert t.sample_count(now=now + 0.2) == 2


def test_rolling_window_expiry_drops_old_samples() -> None:
    t = RollingIouTracker(window_sec=1.0)
    now = 1000.0
    box = _FakeTrack((0, 0, 10, 10))
    legacy = _LegacyTrack((0, 0, 10, 10))
    # One perfect match far in the past
    t.record([box], [legacy], timestamp=now - 5.0)
    # One mismatch just now
    t.record([box], [], timestamp=now)
    # Only the mismatch (IoU=0) is inside the 1s window.
    assert t.sample_count(now=now) == 1
    assert t.mean_iou(now=now) == 0.0


def test_snapshot_shape() -> None:
    t = RollingIouTracker(window_sec=2.0)
    snap = t.snapshot()
    assert set(snap.keys()) == {"mean_iou", "sample_count", "window_sec"}
    assert snap["mean_iou"] == 0.0
    assert snap["sample_count"] == 0
    assert snap["window_sec"] == 2.0


def test_publish_event_emits_on_bus() -> None:
    bus = InProcessEventBus()
    received: list = []
    bus.subscribe(RT_SHADOW_IOU, received.append)
    t = RollingIouTracker(window_sec=5.0)
    box = _FakeTrack((0, 0, 10, 10))
    legacy = _LegacyTrack((0, 0, 10, 10))
    t.record([box], [legacy])
    t.publish_event(bus, topic=RT_SHADOW_IOU, role="c2", source="test")
    # drain synchronously (bus not started)
    bus.drain()
    assert len(received) == 1
    ev = received[0]
    assert ev.topic == RT_SHADOW_IOU
    assert ev.payload["role"] == "c2"
    assert ev.payload["mean_iou"] == 1.0
    assert ev.payload["sample_count"] == 1
    assert ev.payload["window_sec"] == 5.0
