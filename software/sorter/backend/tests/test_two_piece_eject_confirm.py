"""An eject is confirmed by id-gone AND an empty exit arc, not by an id blink.

Regression (2026-09-05 00:41): track 29 blinked for 0.35 s at the fall-off
lip, the eject was committed, and the piece came back as track 30 — an
unclassified stray to misc, while distribution had already advanced.
"""
import logging
from types import SimpleNamespace

from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _EJECT_GONE_CONFIRM_S,
    _Phase,
    _TrackedPiece,
    _ZONE_EXIT_ONLY,
)


def _handler():
    h = object.__new__(TwoPieceClassificationChannel)
    h._phase = _Phase.EJECTING
    h._phase_started_at = 100.0
    h.logger = logging.getLogger("test")
    h.advanced = 0
    h.transport = SimpleNamespace(advanceTransport=lambda: setattr(h, "advanced", h.advanced + 1))
    h.phases = []
    h._enterPhase = lambda phase: (setattr(h, "_phase", phase), h.phases.append(phase))
    h.ctx = SimpleNamespace(config=SimpleNamespace(discharge_center_tolerance_deg=3.0, discharge_max_move_output_deg=20.0, discharge_speed_usteps_per_s=1000))
    h.startOutputMove = lambda *a, **k: None
    tp = object.__new__(_TrackedPiece)
    tp.track_id = 29
    tp.last_seen = 100.0
    tp.ejected = False
    h._eject_target = tp
    return h, tp


def _state(exit_only: bool):
    pieces = [SimpleNamespace(zone_code=_ZONE_EXIT_ONLY, sv_bt_track_id=30)] if exit_only else []
    return SimpleNamespace(pieces=pieces, exit_com_forward_to_center_deg=None)


def test_id_blink_with_piece_still_in_exit_arc_does_not_commit() -> None:
    h, tp = _handler()
    h._ejecting(_state(exit_only=True), stopped=True, now=100.0 + _EJECT_GONE_CONFIRM_S + 0.1)
    assert h.advanced == 0 and tp.ejected is False and h.phases == []


def test_id_gone_and_exit_arc_empty_commits() -> None:
    h, tp = _handler()
    h._ejecting(_state(exit_only=False), stopped=True, now=100.0 + _EJECT_GONE_CONFIRM_S + 0.1)
    assert h.advanced == 1 and tp.ejected is True and h.phases == [_Phase.STAGING]


def test_staging_without_a_target_returns_to_waiting_without_rotating() -> None:
    h, _tp = _handler()
    h._phase = _Phase.STAGING
    h._stage_target = None
    h._pieces = {}
    moves = []
    h.startOutputMove = lambda *a, **k: moves.append(a)
    state = SimpleNamespace(pieces=[], in_drop=True, exit_com_forward_to_precise_deg=90.0, exit_com_forward_deg=200.0)
    h._staging(state, stopped=True, now=101.0)
    assert h.phases == [_Phase.WAITING]
    assert moves == []
