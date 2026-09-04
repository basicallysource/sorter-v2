"""A ready head with no successor is ejected on its own after a short grace.

Regression (2026-09-05, sparse feed): the handler only rotated when a captured
drop piece existed, so the last piece of a batch sat classified + aimed until
the 30 s stall watchdog committed it.
"""
import logging
from types import SimpleNamespace

from defs.known_object import PieceStage
from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _LONE_HEAD_EJECT_S,
    _Phase,
    _TrackedPiece,
    _ZONE_NONE,
)


def _handler() -> TwoPieceClassificationChannel:
    h = object.__new__(TwoPieceClassificationChannel)
    h._pieces = {}
    h._phase = _Phase.WAITING
    h._phase_started_at = 0.0
    h._eject_target = None
    h._stage_target = None
    h.shared = SimpleNamespace(distribution_ready=True)
    h.logger = logging.getLogger("test")
    h.phases = []
    h._enterPhase = lambda phase: (setattr(h, "_phase", phase), h.phases.append(phase))
    return h


def _ready_head(placed_at: float) -> _TrackedPiece:
    tp = object.__new__(_TrackedPiece)
    tp.track_id = 7
    tp.zone = _ZONE_NONE
    tp.gap_to_exit = 40.0
    tp.placed = True
    tp.placed_at = placed_at
    tp.ejected = False
    tp.worker = SimpleNamespace(ctx=SimpleNamespace(known_object=SimpleNamespace(stage=PieceStage.distributing)))
    return tp


def test_lone_ready_head_is_ejected_after_grace() -> None:
    h = _handler()
    h._pieces = {7: _ready_head(placed_at=100.0)}
    h._maybeStartRotation(now=100.0 + _LONE_HEAD_EJECT_S - 0.5)
    assert h.phases == []
    h._maybeStartRotation(now=100.0 + _LONE_HEAD_EJECT_S)
    assert h.phases == [_Phase.EJECTING]
    assert h._eject_target.track_id == 7
    assert h._stage_target is None


def test_head_not_yet_aimed_keeps_waiting() -> None:
    h = _handler()
    head = _ready_head(placed_at=0.0)
    h.shared.distribution_ready = False
    h._pieces = {7: head}
    h._maybeStartRotation(now=1000.0)
    assert h.phases == []


def test_ejected_head_is_not_ejected_again_while_its_id_lingers() -> None:
    # After the commit the track id can survive up to the retire window; the
    # lone-head path fired every tick on it (7 "ejects" of one piece, each
    # shifting the transport slots) until the id was gone.
    h = _handler()
    head = _ready_head(placed_at=0.0)
    head.ejected = True
    h._pieces = {7: head}
    h._maybeStartRotation(now=1000.0)
    assert h.phases == []
    assert h._headPiece() is None
