from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from zones import learner as learner_mod
from zones.learner import Handoff, Sighting, ZoneLearner, _stepped, learnedDrop, learnedExit
from zones.model import ChannelZones, Ring, Span

CENTER = (200.0, 200.0)


def _zones(channel: int, **kw) -> ChannelZones:
    base = dict(
        channel=channel,
        frame=(400, 400),
        ring=Ring(CENTER, 120.0, 190.0, 160.0),
        drop=Span(280.0, 340.0),
        exit=Span(160.0, 200.0),
        precise_width=6.0,
    )
    base.update(kw)
    return ChannelZones(**base)


def _at(angle: float, radius: float = 155.0, ts: float = 0.0, size: float = 20.0) -> Sighting:
    return Sighting(
        ts,
        CENTER[0] + radius * math.cos(math.radians(angle)),
        CENTER[1] + radius * math.sin(math.radians(angle)),
        size,
    )


def _handoffs(left: list[float], landed: list[float]) -> list[Handoff]:
    return [Handoff(2, _at(a, ts=i), _at(b, ts=i + 0.8), 0.8) for i, (a, b) in enumerate(zip(left, landed))]


def test_the_exit_is_where_pieces_were_last_seen_before_landing() -> None:
    hand = _handoffs([175 + (i % 9) for i in range(40)], [300.0] * 40)
    span = learnedExit(_zones(2), hand)
    assert span is not None
    assert span.contains(175.0) and span.contains(183.0)
    assert span.width >= learner_mod.MIN_EXIT_DEG


def test_the_drop_zone_covers_every_landing_with_a_piece_to_spare() -> None:
    hand = _handoffs([180.0] * 40, [290 + (i % 21) for i in range(40)])
    span = learnedDrop(_zones(3), hand)
    assert span is not None
    assert span.contains(286.0) and span.contains(314.0)


def test_a_zone_moves_a_few_degrees_at_a_time_and_never_when_locked() -> None:
    zones = _zones(3)
    target = Span(300.0, 0.0)
    stepped = _stepped(zones, "drop", target)
    assert stepped is not None
    assert stepped.drop.start == pytest.approx(280.0 + learner_mod.MAX_STEP_DEG)
    assert stepped.source["drop"] == "learned"
    assert _stepped(_zones(3, locked=frozenset({"drop"})), "drop", target) is None
    assert _stepped(zones, "drop", Span(280.5, 340.5)) is None


class _FakePerception:
    def __init__(self) -> None:
        self.frames: dict[int, tuple] = {}

    def read_pieces_and_frame(self, channel: int):
        return self.frames.get(channel)

    def show(self, channel: int, ts: float, pieces: list[tuple[int, float]]) -> None:
        observations = []
        for track_id, angle in pieces:
            s = _at(angle)
            observations.append(
                SimpleNamespace(
                    sv_bt_track_id=track_id,
                    bbox=(int(s.x - 10), int(s.y - 10), int(s.x + 10), int(s.y + 10)),
                )
            )
        self.frames[channel] = (observations, SimpleNamespace(timestamp=ts, bgr=None))


def test_a_piece_leaving_one_channel_and_landing_on_the_next_is_a_handoff(monkeypatch) -> None:
    perception = _FakePerception()
    learner = ZoneLearner(perception, apply_changes=False)
    clock = {"now": 100.0}
    monkeypatch.setattr(learner_mod.time, "time", lambda: clock["now"])

    def tick(at: float) -> None:
        clock["now"] = at
        learner._tick(at, at)

    perception.show(2, 100.0, [(7, 170.0)])
    tick(100.0)
    perception.show(2, 100.5, [(7, 182.0)])
    tick(100.5)
    perception.show(2, 101.0, [])
    perception.show(3, 101.4, [(31, 300.0)])
    tick(101.4)
    perception.show(3, 101.8, [(31, 302.0)])
    tick(101.8)
    tick(103.0)

    [handoff] = learner.handoffs(2)
    assert handoff.delay_s == pytest.approx(0.9)
    assert math.degrees(math.atan2(handoff.left.y - CENTER[1], handoff.left.x - CENTER[0])) % 360 == pytest.approx(182.0, abs=0.5)
    assert math.degrees(math.atan2(handoff.landed.y - CENTER[1], handoff.landed.x - CENTER[0])) % 360 == pytest.approx(300.0, abs=0.5)
