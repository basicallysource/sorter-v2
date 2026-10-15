"""A piece committed as ejected that is still seen at the exit did not fall. It
used to stay the head of the queue until the stall watchdog swept the whole
channel into the bucket; now the channel turns a little to push it off while
the chute is still aimed for it."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from subsystems.classification_channel.two_piece import flow as two_piece
from subsystems.classification_channel.two_piece.constants import C4_TRAVEL_SIGN
from subsystems.classification_channel.two_piece.flow import (
    TwoPieceClassificationChannel,
    _TrackedPiece,
)


class _Worker:
    def __init__(self) -> None:
        self.ctx = SimpleNamespace(known_object=None)


def _channel() -> tuple[TwoPieceClassificationChannel, list[float]]:
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.logger = logging.getLogger("test_c4_push_off")
    ch.ctx = SimpleNamespace(config=SimpleNamespace(discharge_speed_usteps_per_s=1000))
    ch._pieces = {}
    ch._lost, ch._last_step_at, ch._turned_at = [], None, 0.0
    ch._rotation_started_at = 0.0
    ch._pair_until, ch._pair_group = 0.0, None
    moves: list[float] = []
    ch.startOutputMove = lambda deg, speed: moves.append(deg) or True
    return ch, moves


def _piece(ch, track_id: int, now: float, *, zone: int, gap: float, ejected_ago: float | None = None) -> _TrackedPiece:
    tp = _TrackedPiece(track_id, _Worker(), now - 10.0)
    tp.zone, tp.gap_to_exit, tp.last_seen = zone, gap, now
    if ejected_ago is not None:
        tp.placed = tp.ejected = True
        tp.ejected_at = now - ejected_ago
    ch._pieces[track_id] = tp
    return tp


def test_an_ejected_piece_still_at_the_exit_is_pushed_off() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    _piece(ch, 54, now, zone=two_piece._ZONE_EXIT, gap=-1.0, ejected_ago=2.0)
    _piece(ch, 55, now, zone=0, gap=93.0)
    assert ch._pushOffLingeringEject(now)
    assert moves == [C4_TRAVEL_SIGN * two_piece._PUSH_OFF_DEG]


def test_a_piece_ridden_past_the_exit_centre_but_still_in_the_exit_zone_is_pushed() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    _piece(ch, 137, now, zone=two_piece._ZONE_EXIT, gap=-36.0, ejected_ago=2.0)
    assert ch._pushOffLingeringEject(now)
    assert len(moves) == 1


def test_an_ejected_piece_outside_the_exit_zone_is_not_pushed() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    _piece(ch, 137, now, zone=0, gap=90.0, ejected_ago=2.0)
    assert not ch._pushOffLingeringEject(now)
    assert moves == []


def test_a_piece_still_falling_is_left_alone() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    _piece(ch, 54, now, zone=two_piece._ZONE_EXIT, gap=-1.0, ejected_ago=0.3)
    assert not ch._pushOffLingeringEject(now)
    assert moves == []


def test_no_push_while_the_chute_is_aimed_for_another_piece() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    _piece(ch, 54, now, zone=two_piece._ZONE_EXIT, gap=-1.0, ejected_ago=2.0)
    head = _piece(ch, 55, now, zone=0, gap=93.0)
    head.placed = True
    assert not ch._pushOffLingeringEject(now)
    assert moves == []


def test_it_gives_up_after_a_few_pushes() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    stuck = _piece(ch, 54, now, zone=two_piece._ZONE_EXIT, gap=-1.0, ejected_ago=2.0)
    for _ in range(two_piece._PUSH_OFF_TRIES + 2):
        stuck.ejected_at = now - 2.0
        ch._pushOffLingeringEject(now)
    assert len(moves) == two_piece._PUSH_OFF_TRIES
