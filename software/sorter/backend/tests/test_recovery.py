"""A recovery procedure frees a stuck piece move by move while its incident
holds the machine, shows how far it has got on the incident's card, and stops
when the operator says so."""

from __future__ import annotations

import functools
import logging
from types import SimpleNamespace

import pytest

import incidents
import recovery
from recovery.judges import exitEmpty, pieceGoneFrom, turnIntoExit
from recovery.procedures import C4_SHAKE_OFF, LANDING_HELD
from recovery.runner import FREED, GAVE_UP, RUNNING, STOPPED, Recovery


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class _Motor:
    def __init__(self, label: str, log: list) -> None:
        self.label = label
        self.log = log
        self.refuse = 0

    def turn(self, deg: float):
        if self.refuse:
            self.refuse -= 1
            return None
        self.log.append((self.label, "turn", deg))
        return 0.3

    def shake(self, profile):
        self.log.append((self.label, "shake", profile.key))
        return 0.5

    def idle(self) -> bool:
        return True


def _until_done(rec: Recovery, clock: _Clock, ticks: int = 2000) -> None:
    for _ in range(ticks):
        if rec.done:
            return
        rec.step()
        clock.t += 0.05
    raise AssertionError("the recovery did not finish")


def _landing(judge, log, clock):
    motors = {"this": _Motor("C3", log), "above": _Motor("C2", log)}
    return Recovery(LANDING_HELD, motors, judge, clock=clock, wall=clock)


def test_it_tries_each_move_in_order_and_stops_once_the_piece_is_free() -> None:
    clock, log = _Clock(), []
    verdicts = iter([False, False, True])
    rec = _landing(lambda since: next(verdicts), log, clock)
    _until_done(rec, clock)
    assert rec.state == FREED
    assert log == [
        ("C2", "turn", 3.0), ("C3", "turn", -6.0),
        ("C2", "turn", 6.0), ("C3", "turn", -6.0),
        ("C2", "turn", -6.0), ("C3", "turn", -6.0),
    ]


def test_it_judges_only_a_picture_taken_after_the_move_settled() -> None:
    clock, log = _Clock(), []
    asked = []

    def judge(since):
        asked.append((since, clock.t))
        return None if len(asked) < 3 else True

    rec = _landing(judge, log, clock)
    _until_done(rec, clock)
    since, now = asked[0]
    # The moves took 0.6 s (two turns) and the move settles 1 s after that.
    assert since == pytest.approx(100.0 + 0.6 + 1.0, abs=0.11)
    assert now >= since
    assert rec.state == FREED and len(log) == 2


def test_it_gives_up_after_the_last_move() -> None:
    clock, log = _Clock(), []
    rec = _landing(lambda since: False, log, clock)
    _until_done(rec, clock)
    assert rec.state == GAVE_UP
    assert ("C3", "shake", "hard") in log
    assert rec.progress()["step"] == len(LANDING_HELD.moves)


def test_stop_ends_it_where_it_is() -> None:
    clock, log = _Clock(), []
    rec = _landing(lambda since: False, log, clock)
    rec.step()
    rec.stop()
    _until_done(rec, clock)
    assert rec.state == STOPPED and log == [("C2", "turn", 3.0)]


def test_a_motor_that_refuses_is_asked_again() -> None:
    clock, log = _Clock(), []
    rec = _landing(lambda since: True, log, clock)
    rec.motors["above"].refuse = 2
    _until_done(rec, clock)
    assert log[0] == ("C2", "turn", 3.0) and rec.state == FREED


def test_the_classification_channel_turns_the_piece_into_its_exit_and_back_after() -> None:
    clock, log = _Clock(), []
    verdicts = iter([False, False, True])
    rec = Recovery(
        C4_SHAKE_OFF, {"this": _Motor("C4", log)}, lambda since: next(verdicts),
        exit_turn=lambda: -70.0, clock=clock, wall=clock,
    )
    _until_done(rec, clock)
    assert rec.state == FREED
    assert log == [("C4", "turn", -70.0), ("C4", "shake", "heavy"), ("C4", "shake", "hard"), ("C4", "turn", 70.0)]


def test_progress_says_which_step_and_what_it_does() -> None:
    clock, log = _Clock(), []
    rec = _landing(lambda since: False, log, clock)
    progress = rec.progress()
    assert (progress["step"], progress["steps"], progress["state"]) == (1, 7, RUNNING)
    assert progress["doing"] == "Turn C2 forward 3°, then turn C3 back 6° to see if it rides"


class _Stats:
    def __init__(self) -> None:
        self.active = None
        self.resolved_by = None

    def activeIncident(self):
        return dict(self.active) if self.active else None

    def setActiveIncident(self, incident):
        self.active = dict(incident)

    def clearActiveIncident(self, kind=None, resolved_by="system", **_):
        if self.active and (kind is None or self.active.get("kind") == kind):
            self.active = None
            self.resolved_by = resolved_by


@pytest.fixture
def held_incident(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(recovery, "Recovery", functools.partial(Recovery, clock=clock, wall=clock))
    monkeypatch.setattr(recovery, "_run", None)
    gc = SimpleNamespace(runtime_stats=_Stats(), logger=logging.getLogger("test_recovery"))
    gc.runtime_stats.setActiveIncident({"kind": "piece_held", "subject": "C3", "channel": "c3", "track_id": 5})
    return gc, clock


def test_its_card_shows_the_step_and_closes_the_incident_once_free(held_incident) -> None:
    gc, clock = held_incident
    log, verdicts = [], iter([False, True])
    motors = {"this": _Motor("C3", log), "above": _Motor("C2", log)}
    assert recovery.start(gc, "landing_held", kind="piece_held", motors=motors, judge=lambda since: next(verdicts))
    card = incidents.describe(gc.runtime_stats.active)
    assert card["recovery"]["step"] == 1 and card["actions"] == [{"key": "stop_recovery", "label": "Stop"}]
    for _ in range(400):
        recovery.step(gc)
        clock.t += 0.05
        if gc.runtime_stats.active is None:
            break
    assert gc.runtime_stats.active is None and gc.runtime_stats.resolved_by == "recovery"
    assert not recovery.running()


def test_when_it_gives_up_the_card_asks_the_operator(held_incident) -> None:
    gc, clock = held_incident
    motors = {"this": _Motor("C3", []), "above": _Motor("C2", [])}
    recovery.start(gc, "landing_held", kind="piece_held", motors=motors, judge=lambda since: False)
    for _ in range(4000):
        recovery.step(gc)
        clock.t += 0.05
        if not recovery.running():
            break
    card = incidents.describe(gc.runtime_stats.active)
    assert card["recovery"]["state"] == GAVE_UP
    assert card["actions"] == [{"key": "done", "label": "Done"}]
    assert "where pieces land on C3" in card["todo"]


def test_done_stops_it(held_incident) -> None:
    gc, clock = held_incident
    log = []
    motors = {"this": _Motor("C3", log), "above": _Motor("C2", log)}
    recovery.start(gc, "landing_held", kind="piece_held", motors=motors, judge=lambda since: False)
    recovery.step(gc)
    gc.runtime_stats.clearActiveIncident(kind="piece_held", resolved_by="operator")
    recovery.step(gc)
    assert not recovery.running()
    moved = len(log)
    for _ in range(50):
        recovery.step(gc)
        clock.t += 0.05
    assert len(log) == moved


def _perception(ts, pieces, channel=3, channel_def=None):
    state = SimpleNamespace(ts=ts, pieces=pieces)
    return SimpleNamespace(read_states=lambda: {channel: state}, channels=lambda: {channel: channel_def})


def _piece(box, fwd=200.0, track=None):
    return SimpleNamespace(bbox=box, com_forward_to_exit_deg=fwd, sv_bt_track_id=track)


def test_a_held_piece_is_free_once_nothing_sits_where_it_sat() -> None:
    box = (500, 300, 560, 360)
    assert pieceGoneFrom(_perception(10.0, [_piece(box)]), 3, box)(11.0) is None  # an older picture
    assert pieceGoneFrom(_perception(12.0, [_piece((503, 302, 562, 361))]), 3, box)(11.0) is False
    assert pieceGoneFrom(_perception(12.0, [_piece((560, 300, 620, 360))]), 3, box)(11.0) is True


_C4 = SimpleNamespace(exit_sections=frozenset(range(100, 227)), precise_sections=frozenset(range(100, 185)))
_WIDTH = 227 - 185


def _c4(*pieces):
    return _perception(1.0, [_piece((0, 0, 1, 1), fwd=f, track=t) for t, f in pieces], channel=4, channel_def=_C4)


def test_turning_into_the_exit_takes_the_shorter_way() -> None:
    assert turnIntoExit(_c4((1, 10.0)), 4) == pytest.approx(10.0 + _WIDTH / 2)
    assert turnIntoExit(_c4((1, 290.0)), 4) == pytest.approx(290.0 + _WIDTH / 2 - 360.0)


def test_turning_into_the_exit_never_carries_another_piece_through_it() -> None:
    # The stuck piece (track 7) came back around; another waits 70 degrees
    # short of the exit. Backwards (49) is shorter and keeps it clear.
    assert turnIntoExit(_c4((3, 70.0), (7, 290.0)), 4, target_track=7) == pytest.approx(-49.0)
    # Backwards would carry the other piece into the exit too, so forward, the
    # long way, which keeps it clear.
    assert turnIntoExit(_c4((3, 310.0), (7, 200.0)), 4, target_track=7) == pytest.approx(221.0)
    assert turnIntoExit(_c4((3, 250.0), (7, 10.0)), 4, target_track=7) == pytest.approx(31.0)
    # Just behind it, the other piece reaches the exit either way: by hand.
    assert turnIntoExit(_c4((3, 300.0), (7, 290.0)), 4, target_track=7) is None
    # A piece already in the exit, or a target that is not there: by hand.
    assert turnIntoExit(_c4((3, -5.0), (7, 290.0)), 4, target_track=7) is None
    assert turnIntoExit(_c4((3, 100.0)), 4, target_track=7) is None


def test_freed_once_nothing_is_in_the_exit() -> None:
    assert exitEmpty(_c4((3, 70.0)), 4)(0.5) is True
    assert exitEmpty(_c4((3, 70.0), (7, -20.0)), 4)(0.5) is False
    assert exitEmpty(_c4((3, 70.0)), 4)(2.0) is None
