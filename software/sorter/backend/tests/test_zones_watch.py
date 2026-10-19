"""The piece watch: a piece the feeder saw fall off one channel, and the one
that appears on the next moments later, are one hand-off, timed."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from zones import watch as watch_mod
from zones.watch import PieceWatch, Sighting

CENTER = (200.0, 200.0)


def _at(angle: float, radius: float = 155.0, ts: float = 0.0, size: float = 20.0) -> Sighting:
    return Sighting(
        ts,
        (CENTER[0] + radius * math.cos(math.radians(angle))) / 400.0,
        (CENTER[1] + radius * math.sin(math.radians(angle))) / 400.0,
        size / 400.0,
    )


class _FakePerception:
    def __init__(self) -> None:
        self.frames: dict[int, tuple] = {}

    def read_pieces_and_frame(self, channel: int):
        return self.frames.get(channel)

    def show(self, channel: int, ts: float, pieces: list[tuple[int, float]]) -> None:
        observations = []
        for track_id, angle in pieces:
            x, y = _at(angle).at((400, 400))
            observations.append(
                SimpleNamespace(
                    sv_bt_track_id=track_id,
                    bbox=(int(x - 10), int(y - 10), int(x + 10), int(y + 10)),
                )
            )
        self.frames[channel] = (observations, SimpleNamespace(timestamp=ts, bgr=np.zeros((400, 400, 3), np.uint8)))


def test_a_piece_seen_to_fall_and_then_landing_on_the_next_channel_is_a_handoff(monkeypatch) -> None:
    perception = _FakePerception()
    watch = PieceWatch(perception)
    clock = {"now": 100.0}
    monkeypatch.setattr(watch_mod.time, "time", lambda: clock["now"])

    def tick(at: float) -> None:
        clock["now"] = at
        watch._tick(at, at)

    perception.show(2, 100.0, [(7, 170.0)])
    tick(100.0)
    perception.show(2, 100.5, [(7, 182.0)])
    tick(100.5)
    perception.show(2, 101.0, [])
    watch.fell(2, 7)
    perception.show(3, 101.4, [(31, 300.0)])
    tick(101.4)
    perception.show(3, 101.8, [(31, 302.0)])
    tick(101.8)
    tick(103.5)

    [handoff] = watch.handoffs(2)
    assert handoff.delay_s == pytest.approx(0.9)
    left = handoff.left.at((400, 400))
    landed = handoff.landed.at((400, 400))
    assert math.degrees(math.atan2(left[1] - CENTER[1], left[0] - CENTER[0])) % 360 == pytest.approx(182.0, abs=0.5)
    assert math.degrees(math.atan2(landed[1] - CENTER[1], landed[0] - CENTER[0])) % 360 == pytest.approx(300.0, abs=0.5)


def test_a_landing_pairs_with_the_piece_that_left_last_not_one_out_of_sight(monkeypatch) -> None:
    perception = _FakePerception()
    watch = PieceWatch(perception)
    clock = {"now": 0.0}
    monkeypatch.setattr(watch_mod.time, "time", lambda: clock["now"])

    def tick(at: float) -> None:
        clock["now"] = at
        watch._tick(at, at)

    # Track 1 rides into the part of the ring the camera cannot see at 50
    # degrees; track 2 falls off the exit at 185 a second later; one piece lands.
    perception.show(3, 10.0, [(1, 50.0), (2, 180.0)])
    tick(10.0)
    perception.show(3, 11.0, [(2, 185.0)])
    tick(11.0)
    perception.show(3, 11.5, [])
    watch.fell(3, 2)
    perception.show(4, 11.8, [(40, 300.0)])
    tick(11.8)
    tick(14.0)

    [handoff] = watch.handoffs(3)
    left = handoff.left.at((400, 400))
    assert math.degrees(math.atan2(left[1] - CENTER[1], left[0] - CENTER[0])) % 360 == pytest.approx(185.0, abs=0.5)
    assert handoff.delay_s == pytest.approx(0.8)


def test_a_landing_with_no_fall_reported_is_no_hand_off(monkeypatch) -> None:
    perception = _FakePerception()
    watch = PieceWatch(perception)
    clock = {"now": 0.0}
    monkeypatch.setattr(watch_mod.time, "time", lambda: clock["now"])
    for at, pieces3, pieces4 in ((10.0, [(5, 180.0)], []), (11.0, [], [(9, 300.0)]), (13.0, [], [(9, 302.0)])):
        clock["now"] = at
        perception.show(3, at, pieces3)
        perception.show(4, at, pieces4)
        watch._tick(at, at)
    assert watch.handoffs(3) == []
