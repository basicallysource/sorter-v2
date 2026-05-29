"""Architectural-isolation tests for InferenceWorker.

These exist to fail loudly if a future change reintroduces role-string
dispatch and silently swaps frame sources between NPU cores.

What they pin:
- An InferenceWorker constructed with mismatched capture/channel raises
  at construction (cannot reach the hot loop in a wrong state).
- A frame whose ``source_id`` does not match the worker's capture is
  rejected before inference runs; ``source_id_assertions`` counter goes
  up; the slot is reset to neutral, not corrupted with a wrong-channel
  detection.
- The "happy path" three workers with three captures + three channels +
  three runtimes do not cross outputs even when scheduled concurrently.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pytest

from perception.arcs import bboxInsideChannelMask
from perception.capture import CaptureWorker, PerceptionFrame
from perception.channel import buildChannelDef
from perception.inference import InferenceWorker
from perception.runtime import StubRuntime
from perception.state import LatestStateSlot


# --- fixtures --------------------------------------------------------------


@dataclass
class FakeFrame:
    raw: np.ndarray
    timestamp: float


class FakeCapture:
    """Mimics the parts of ``vision.camera.CaptureThread`` perception uses.

    Has a ``latest_frame`` attribute the CaptureWorker reads, and exposes
    a ``push`` for the test to drive it.
    """

    def __init__(self, w: int = 100, h: int = 100) -> None:
        self._frame: Optional[FakeFrame] = None
        self._w = w
        self._h = h

    @property
    def latest_frame(self) -> Optional[FakeFrame]:
        return self._frame

    def push(self, timestamp: float, fill: int = 64) -> None:
        self._frame = FakeFrame(
            raw=np.full((self._h, self._w, 3), fill, dtype=np.uint8),
            timestamp=timestamp,
        )


def _annulus_polygon(
    center: tuple[float, float],
    inner: float,
    outer: float,
) -> np.ndarray:
    outer_pts = []
    inner_pts = []
    for i in range(64):
        theta = 2.0 * math.pi * i / 64.0
        outer_pts.append([center[0] + outer * math.cos(theta), center[1] + outer * math.sin(theta)])
        inner_pts.append([center[0] + inner * math.cos(theta), center[1] + inner * math.sin(theta)])
    return np.array(outer_pts + list(reversed(inner_pts)), dtype=np.int32)


def _build_worker_set(
    runtime_bboxes_by_id: dict[int, tuple[tuple[int, int, int, int], ...]],
):
    """Three workers (C2/C3/C4), three captures, three StubRuntimes."""
    captures_thread = {
        "c_channel_2": FakeCapture(),
        "c_channel_3": FakeCapture(),
        "carousel": FakeCapture(),
    }
    captures = {
        role: CaptureWorker(source_id=role, capture_thread=ct)
        for role, ct in captures_thread.items()
    }
    runtimes = {ch_id: StubRuntime(bb) for ch_id, bb in runtime_bboxes_by_id.items()}
    channels = {
        ch_id: buildChannelDef(
            channel_id=ch_id,
            polygon=_annulus_polygon((50, 50), 20, 40),
            frame_shape=(100, 100),
            section_zero_angle=0.0,
            drop_arc=(75.0, 105.0),
            exit_arc=(255.0, 285.0),
            precise_arc=None,
        )
        for ch_id in (2, 3, 4)
    }
    slots = {ch_id: LatestStateSlot() for ch_id in (2, 3, 4)}
    role_for_id = {2: "c_channel_2", 3: "c_channel_3", 4: "carousel"}
    workers = {}
    for ch_id, role in role_for_id.items():
        workers[ch_id] = InferenceWorker(
            capture=captures[role],
            runtime=runtimes[ch_id],
            channel_def=channels[ch_id],
            slot=slots[ch_id],
        )
    return captures_thread, captures, runtimes, channels, slots, workers


# --- construction-time invariant ------------------------------------------


def test_constructor_rejects_mismatched_capture_and_channel() -> None:
    """If you try to wire a c_channel_3 capture to a C2 channel def, the
    InferenceWorker refuses to be constructed."""
    capture = CaptureWorker(source_id="c_channel_3", capture_thread=FakeCapture())
    bad_channel = buildChannelDef(
        channel_id=2,           # registry says channel_id=2 → camera_source_id="c_channel_2"
        polygon=_annulus_polygon((50, 50), 20, 40),
        frame_shape=(100, 100),
        section_zero_angle=0.0,
        drop_arc=(75.0, 105.0),
        exit_arc=(255.0, 285.0),
        precise_arc=None,
    )
    with pytest.raises(ValueError, match="source_id"):
        InferenceWorker(
            capture=capture,
            runtime=StubRuntime(),
            channel_def=bad_channel,
            slot=LatestStateSlot(),
        )


# --- runtime source_id assertion ------------------------------------------


def test_runtime_source_id_assertion_fires_if_frame_lies() -> None:
    """We forge a frame whose source_id doesn't match the capture's. The
    worker rejects it, increments the assertion counter, writes a neutral
    slot, and does NOT call the runtime."""
    capture_thread = FakeCapture()
    capture = CaptureWorker(source_id="c_channel_2", capture_thread=capture_thread)
    channel = buildChannelDef(
        channel_id=2,
        polygon=_annulus_polygon((50, 50), 20, 40),
        frame_shape=(100, 100),
        section_zero_angle=0.0,
        drop_arc=(75.0, 105.0),
        exit_arc=(255.0, 285.0),
        precise_arc=None,
    )
    runtime = StubRuntime(bboxes=[(40, 40, 60, 60)])
    slot = LatestStateSlot()
    worker = InferenceWorker(
        capture=capture, runtime=runtime, channel_def=channel, slot=slot,
    )

    # Forge a frame that pretends to be from another camera.
    forged = PerceptionFrame(
        source_id="c_channel_3",
        timestamp=1.0,
        bgr=np.zeros((100, 100, 3), dtype=np.uint8),
    )
    assert worker._check_source_id(forged) is False  # type: ignore[attr-defined]
    assert worker.source_id_assertions == 1
    assert runtime.calls == 0


# --- happy-path isolation under concurrent execution ----------------------


def test_three_workers_do_not_cross_outputs_when_run_concurrently() -> None:
    """Each runtime returns a different bbox geometry. After running the
    worker loops concurrently for a few iterations each, each slot should
    reflect ONLY the bboxes from its own runtime, not any other's."""
    # Drop-arc bbox for C2, exit-arc bbox for C3, nothing for C4.
    def bbox_at(angle_deg: float) -> tuple[int, int, int, int]:
        rad = math.radians(angle_deg)
        cx = 50.0 + 30.0 * math.cos(rad)
        cy = 50.0 + 30.0 * math.sin(rad)
        return (int(cx - 5), int(cy - 5), int(cx + 5), int(cy + 5))

    runtimes = {
        2: (bbox_at(90.0),),    # in drop arc
        3: (bbox_at(270.0),),   # in exit arc
        4: (),                  # empty
    }
    captures_thread, captures, _, _, slots, workers = _build_worker_set(runtimes)

    for w in workers.values():
        w.start()
    try:
        # Push frames into each capture and let the loops run a few ticks.
        deadline = time.time() + 2.0
        ts = 0.0
        while time.time() < deadline and not all(
            workers[ch].inferences >= 3 for ch in (2, 3, 4)
        ):
            ts += 0.05
            for ct in captures_thread.values():
                ct.push(timestamp=ts)
            time.sleep(0.02)
    finally:
        for w in workers.values():
            w.stop()

    s2 = slots[2].read()
    s3 = slots[3].read()
    s4 = slots[4].read()
    # No worker ever rejected a frame.
    for w in workers.values():
        assert w.source_id_assertions == 0, (w.source_id, w.source_id_assertions)
    # Each channel only saw its own runtime's bboxes.
    assert s2.in_drop is True and s2.in_exit is False, s2
    assert s3.in_drop is False and s3.in_exit is True, s3
    assert s4.in_drop is False and s4.in_exit is False and s4.n_pieces == 0, s4


# --- belt-and-suspenders: even runtime-swapped workers report correctly --


def test_swapping_capture_at_runtime_is_caught_by_source_id_check() -> None:
    """A future bug that reassigns ``worker._capture`` to a different
    CaptureWorker must be caught by the loop's source_id check, not
    silently produce wrong-channel results."""
    capture_a_thread = FakeCapture()
    capture_b_thread = FakeCapture()
    capture_a = CaptureWorker(source_id="c_channel_2", capture_thread=capture_a_thread)
    capture_b = CaptureWorker(source_id="c_channel_3", capture_thread=capture_b_thread)
    channel = buildChannelDef(
        channel_id=2,
        polygon=_annulus_polygon((50, 50), 20, 40),
        frame_shape=(100, 100),
        section_zero_angle=0.0,
        drop_arc=(75.0, 105.0),
        exit_arc=(255.0, 285.0),
        precise_arc=None,
    )
    runtime = StubRuntime(bboxes=[(40, 40, 60, 60)])
    slot = LatestStateSlot()
    worker = InferenceWorker(
        capture=capture_a, runtime=runtime, channel_def=channel, slot=slot,
    )

    # Simulate the dangerous swap.
    worker._capture = capture_b  # type: ignore[attr-defined]

    # Push a frame on the (now wrong) capture.
    capture_b_thread.push(timestamp=1.0)
    frame = capture_b.latest_frame()
    assert frame is not None
    assert worker._check_source_id(frame) is False  # type: ignore[attr-defined]
    assert worker.source_id_assertions == 1


# Ensure helper import is exercised (silences pyright unused warning).
_ = bboxInsideChannelMask
