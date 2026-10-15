"""A piece that does not fall off the exit (a tire gripping the platter) rides
around and is classified again in the drop zone. The second record is not
counted, and the machine holds for the operator to take the piece off."""

from __future__ import annotations

import logging
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

from defs.known_object import ClassificationStatus, KnownObject
from subsystems.classification_channel.two_piece import flow as two_piece
from subsystems.classification_channel.two_piece.flow import (
    TwoPieceClassificationChannel,
    _TrackedPiece,
)


class _Worker:
    def __init__(self, obj: KnownObject) -> None:
        self.ctx = SimpleNamespace(known_object=obj)

    def emitKnownObject(self) -> None:
        pass


def _channel() -> TwoPieceClassificationChannel:
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.logger = logging.getLogger("test_c4_piece_circling")
    ch.gc = SimpleNamespace()
    ch._recent_ejects = deque(maxlen=16)
    ch._lost, ch._last_step_at, ch._turned_at = [], None, 0.0
    ch._rotation_started_at = 0.0
    ch._pair_until, ch._pair_group = 0.0, None
    return ch


def _piece(track_id: int, part_id: str, name: str, color_id: str = "11") -> _TrackedPiece:
    obj = KnownObject(part_id=part_id, part_name=name, color_id=color_id)
    obj.classification_status = ClassificationStatus.classified
    return _TrackedPiece(track_id, _Worker(obj), time.monotonic())


def _eject(ch: TwoPieceClassificationChannel, tp: _TrackedPiece, *, timed_out: bool = False) -> None:
    ch._rememberEject(tp, timed_out=timed_out)


WHEEL = "Wheel Center Small with Stub Axles (Pulley Wheel) with Black Tire 15mm D."


def test_a_tire_that_comes_back_is_counted_once_and_holds_the_machine() -> None:
    ch = _channel()
    _eject(ch, _piece(192, "3464c02", WHEEL))
    again = _piece(195, "3464c02", WHEEL)
    with patch.object(two_piece.incidents, "report", return_value=True) as report:
        ch._checkCircling(again)
    assert again.known_object.dead
    report.assert_called_once()
    assert report.call_args.args[1] == "piece_circling"


def test_two_bricks_in_a_row_are_two_bricks() -> None:
    ch = _channel()
    _eject(ch, _piece(1, "3001", "Brick 2 x 4"))
    next_brick = _piece(2, "3001", "Brick 2 x 4")
    with patch.object(two_piece.incidents, "report", return_value=True) as report:
        ch._checkCircling(next_brick)
    assert not next_brick.known_object.dead
    report.assert_not_called()


def test_any_part_comes_back_after_an_eject_that_timed_out() -> None:
    ch = _channel()
    _eject(ch, _piece(1, "3001", "Brick 2 x 4"), timed_out=True)
    again = _piece(2, "3001", "Brick 2 x 4")
    with patch.object(two_piece.incidents, "report", return_value=True):
        ch._checkCircling(again)
    assert again.known_object.dead


def test_a_tire_long_after_the_last_one_is_a_new_tire() -> None:
    ch = _channel()
    _eject(ch, _piece(1, "3464c02", WHEEL))
    at, *rest = ch._recent_ejects[-1]
    ch._recent_ejects[-1] = (at - two_piece._CIRCLING_WINDOW_S - 1.0, *rest)
    later = _piece(2, "3464c02", WHEEL)
    with patch.object(two_piece.incidents, "report", return_value=True) as report:
        ch._checkCircling(later)
    assert not later.known_object.dead
    report.assert_not_called()
