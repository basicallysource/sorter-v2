"""Pieces on the classification channel keep what they were classified as.

The tracker sometimes gives a piece a new id, a second piece can slide in while
the last one is being turned off the drop zone, a turn sized for one piece can
carry another off the exit, and a pause used to forget every piece. Each sent
classified pieces to misc and left a "timed out" record behind. These tests
pin the fixes, and the notes a piece carries about what happened to it.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from types import SimpleNamespace

from defs.known_object import ClassificationStatus, KnownObject, PieceStage, notePieceProblem
from piece_cycles import CycleRecorder
from piece_transport import ClassificationChannelTransport
from runtime_stats import RuntimeStatsCollector
from subsystems.classification_channel.two_piece import flow as two_piece
from subsystems.classification_channel.two_piece.constants import C4_TRAVEL_SIGN
from subsystems.classification_channel.two_piece.flow import (
    TwoPieceClassificationChannel,
    _Phase,
    _TrackedPiece,
)
from subsystems.shared_variables import SharedVariables

_LOGGER = logging.getLogger("test_c4_keeps_pieces")


class _Worker:
    def __init__(self, obj: KnownObject | None) -> None:
        self.ctx = SimpleNamespace(known_object=obj, classify_started_at=0.0)
        self.emits = 0

    def emitKnownObject(self) -> None:
        self.emits += 1

    def abandonInFlightObject(self, reason: str) -> None:
        pass


def _channel() -> tuple[TwoPieceClassificationChannel, list[float]]:
    transport = ClassificationChannelTransport()
    shared = SharedVariables()
    shared.transport = transport
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.transport = transport
    ch.shared = shared
    ch.logger = _LOGGER
    ch.gc = SimpleNamespace(logger=_LOGGER, runtime_stats=RuntimeStatsCollector())
    ch.ctx = SimpleNamespace(
        config=SimpleNamespace(
            discharge_center_tolerance_deg=2.0,
            discharge_max_move_output_deg=150.0,
            discharge_speed_usteps_per_s=1000,
            precise_center_tolerance_deg=2.0,
            precise_converge_speed_usteps_per_s=1000,
            multi_feed_confirm_reads=3,
        ),
        reset=lambda: None,
        known_object=None,
    )
    ch._pieces = {}
    ch._lost, ch._last_step_at, ch._turned_at = [], None, 0.0
    ch._rotation_started_at = 0.0
    ch._pair_until, ch._pair_group = 0.0, None
    ch._phase = _Phase.WAITING
    ch._eject_target = None
    ch._stage_target = None
    ch._phase_started_at = time.monotonic()
    ch.last_progress_at = time.monotonic()
    ch._multi_drop_streak = 0
    ch._multi_drop_last_ts = -1.0
    ch._multi_drop_seq = 0
    ch._recent_ejects = deque(maxlen=16)
    ch._bucket_hold_cycles = 0
    ch._cycles = CycleRecorder()
    ch._was_ready = False
    ch._ready_since = None
    moves: list[float] = []
    ch.startOutputMove = lambda deg, speed: moves.append(deg) or True
    return ch, moves


def _classified(part: str = "3001") -> KnownObject:
    obj = KnownObject(part_id=part, color_id="1")
    obj.classification_status = ClassificationStatus.classified
    return obj


def _piece(
    ch,
    track_id: int,
    now: float,
    *,
    gap: float,
    zone: int = two_piece._ZONE_PRECISE,
    obj: KnownObject | None = None,
    seen_ago: float = 0.0,
    age: float = 5.0,
) -> _TrackedPiece:
    tp = _TrackedPiece(track_id, _Worker(obj), now - age)
    tp.zone, tp.gap_to_exit, tp.last_seen = zone, gap, now - seen_ago
    tp.history.append((now - seen_ago, gap))
    tp.first_gap = gap
    if obj is not None:
        tp.capture_done = tp.result_applied = True
    ch._pieces[track_id] = tp
    return tp


# ------------------------------------------------------------ a new tracker id


def test_a_tracker_double_takes_over_the_waiting_piece() -> None:
    """The classified piece waiting for the chute got a second id
    at the same place, the first id dropped out, and the piece went to misc as
    one nobody photographed."""
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified()
    head = _piece(ch, 293, now, gap=83.0, obj=obj, seen_ago=1.0)
    ch.transport.placePieceForDistribution(obj)
    head.placed = True
    double = _piece(ch, 294, now, gap=83.5)
    double.history.appendleft((now - 1.0, 83.4))  # there all along, on top of it

    ch._retireGonePieces(now)

    assert ch._pieces[294] is head
    assert head.track_id == 294 and head.placed
    assert ch.transport.getPieceForDistributionPositioning() is obj
    assert ch._lost == []


def test_a_takeover_ties_the_new_id_to_the_piece_in_the_control_log(monkeypatch) -> None:
    """The control-data log names C4 pieces by track id; the id that takes a
    piece over is tied to it there too, naming the id it replaced."""
    import control_data_store

    events: list[dict] = []
    monkeypatch.setattr(control_data_store, "record", events.append)
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified()
    _piece(ch, 293, now, gap=83.0, obj=obj, seen_ago=1.0)
    double = _piece(ch, 294, now, gap=83.5)
    double.history.appendleft((now - 1.0, 83.4))

    ch._retireGonePieces(now)

    assert [(e["kind"], e["track"], e["piece"], e["took_over"]) for e in events] == [("c4_piece", 294, obj.uuid, 293)]


def test_a_new_id_after_a_turn_takes_over_the_piece_it_replaced() -> None:
    """The piece being staged got a new id while the channel
    turned it; its classification was left behind on a timed-out record."""
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified("4081b")
    staged = _piece(ch, 185, now, gap=235.0, zone=two_piece._ZONE_DROP, obj=obj, seen_ago=1.0)
    ch._turned_at = now - 0.8
    ch._retireGonePieces(now)
    assert ch._lost and ch._lost[0][0] is staged

    newcomer = _piece(ch, 186, now + 0.4, gap=165.0, zone=two_piece._ZONE_DROP, age=0.0)
    ch._adoptLost(newcomer, now + 0.4)

    assert ch._pieces[186] is staged
    assert staged.known_object is obj
    assert ch._lost == []


def test_a_piece_seen_elsewhere_does_not_take_over() -> None:
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified()
    _piece(ch, 50, now, gap=83.0, obj=obj, seen_ago=1.0)
    other = _piece(ch, 51, now, gap=150.0)
    other.history.appendleft((now - 1.0, 151.0))
    ch._retireGonePieces(now)
    assert 50 not in ch._pieces and ch._pieces[51] is other
    assert ch._lost and ch._lost[0][0].track_id == 50


def test_a_lost_piece_nobody_picks_up_says_so() -> None:
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified()
    _piece(ch, 60, now, gap=83.0, obj=obj, seen_ago=1.0)
    ch._retireGonePieces(now)
    ch._expireLost(now + two_piece._RELINK_WINDOW_S + 0.1)
    assert ch._lost == []
    assert [p["kind"] for p in obj.problems] == ["track_lost"]
    assert "lost track" in obj.problems[0]["message"]


# ------------------------------------------------------ a second piece, late


def test_a_piece_landing_while_the_last_one_is_staged_is_a_double_feed() -> None:
    """A second piece slid in 2 s after the first, while
    the channel turned the first off the drop zone; neither was flagged."""
    ch, _ = _channel()
    now = time.monotonic()
    first_obj = _classified("3579")
    first = _piece(ch, 333, now, gap=111.0, zone=0, obj=first_obj, age=2.4)
    first.first_gap = 241.0  # where it landed
    ch._stage_target = first
    ch._phase = _Phase.STAGING
    late = _piece(ch, 334, now, gap=177.0, zone=two_piece._ZONE_DROP, age=0.2)

    ch._flagLateArrivals(now)

    assert first.double_feed and late.double_feed
    assert first.multi_drop_group == late.multi_drop_group is not None
    assert first_obj.classification_status == ClassificationStatus.multi_drop_fail
    assert [p["kind"] for p in first_obj.problems] == ["late_double_feed"]
    assert late.known_object is not None
    assert late.known_object.problems[0]["kind"] == "late_double_feed"


def test_a_piece_coming_around_from_past_the_exit_is_not_a_late_feed() -> None:
    """A piece that did not fall rode on past the exit, out of the camera's
    sight, and came back into the drop zone from behind while the next piece
    was being staged. It was never fed, so it is no double feed, and the piece
    being staged keeps its classification."""
    ch, _ = _channel()
    now = time.monotonic()
    first_obj = _classified()
    first = _piece(ch, 40, now, gap=165.0, zone=two_piece._ZONE_DROP, obj=first_obj, age=1.8)
    first.first_gap = 203.0
    ch._stage_target = first
    ch._phase = _Phase.EJECTING
    back = _piece(ch, 41, now, gap=288.0, zone=two_piece._ZONE_DROP, age=0.2)
    back.first_gap = 307.0
    ch._flagLateArrivals(now)
    assert not first.double_feed and not back.double_feed
    assert first_obj.classification_status == ClassificationStatus.classified


def test_a_tracker_double_of_the_staged_piece_is_not_a_second_piece() -> None:
    ch, _ = _channel()
    now = time.monotonic()
    first = _piece(ch, 333, now, gap=200.0, zone=two_piece._ZONE_DROP, obj=_classified(), age=1.0)
    ch._stage_target = first
    ch._phase = _Phase.STAGING
    double = _piece(ch, 334, now, gap=203.0, zone=two_piece._ZONE_DROP, age=0.3)
    ch._flagLateArrivals(now)
    assert not first.double_feed and not double.double_feed


def test_a_piece_already_there_when_the_turn_began_is_not_late() -> None:
    """A piece that landed while the machine was paused is new to the channel
    after the resume, but it was there before the turn began: not a feed that
    came in late behind the staged piece."""
    ch, _ = _channel()
    now = time.monotonic()
    first = _piece(ch, 86, now, gap=150.0, zone=two_piece._ZONE_DROP, obj=_classified(), age=30.0)
    first.first_gap = 220.0
    ch._stage_target = first
    ch._phase = _Phase.EJECTING
    ch._rotation_started_at = now - 0.2
    landed = _piece(ch, 115, now, gap=210.0, zone=two_piece._ZONE_DROP, age=0.5)
    ch._flagLateArrivals(now)
    assert not first.double_feed and not landed.double_feed


def test_resuming_gives_an_unphotographed_id_a_fresh_stray_grace() -> None:
    """An id that showed up during the stop may be a kept piece's new id: it
    must not be sent to misc as a stray before the hand-over can claim it."""
    ch, _ = _channel()
    now = time.monotonic()
    newcomer = _piece(ch, 88, now - 600.0, gap=70.0)
    ch._resumeAfterPause(now)
    assert newcomer.created_at == now


def test_nothing_is_late_while_the_channel_waits_for_a_piece() -> None:
    ch, _ = _channel()
    now = time.monotonic()
    first = _piece(ch, 333, now, gap=111.0, zone=0, obj=_classified(), age=2.0)
    ch._stage_target = first
    newcomer = _piece(ch, 334, now, gap=210.0, zone=two_piece._ZONE_DROP, age=0.3)
    ch._flagLateArrivals(now)
    assert not newcomer.double_feed


# ---------------------------------------------- turns keep waiting pieces on


def test_the_eject_turn_stops_short_of_dropping_the_piece_behind() -> None:
    """Ejecting a piece at the exit with a turn sized to stage the
    next one carried the classified piece waiting in between off as well."""
    ch, moves = _channel()
    now = time.monotonic()
    target = _piece(ch, 336, now, gap=10.0, zone=two_piece._ZONE_EXIT, obj=_classified())
    waiting = _piece(ch, 335, now, gap=83.0, obj=_classified("3001"))
    staged = _piece(ch, 337, now, gap=194.0, zone=two_piece._ZONE_DROP, obj=_classified())
    ch._eject_target, ch._stage_target = target, staged
    ch._phase, ch._phase_started_at = _Phase.EJECTING, now
    state = SimpleNamespace(
        exit_com_forward_to_center_deg=12.0,
        pieces=(SimpleNamespace(com_forward_to_exit_deg=10.0),),
    )
    ch.gc.perception_service = SimpleNamespace(
        channels=lambda: {4: SimpleNamespace(precise_sections=range(45))}
    )

    ch._ejecting(state, True, now)

    assert len(moves) == 1
    room = waiting.gap_to_exit - two_piece._KEEP_ON_MIN_GAP_DEG
    assert moves[0] == C4_TRAVEL_SIGN * room


def test_the_eject_turn_is_sized_for_the_target_not_the_leading_box() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    target = _piece(ch, 40, now, gap=60.0, obj=_classified())
    ch._eject_target, ch._phase, ch._phase_started_at = target, _Phase.EJECTING, now
    # The leading box this frame is a different, nearer one (gap 5 to the edge).
    state = SimpleNamespace(
        exit_com_forward_to_center_deg=9.0,
        pieces=(SimpleNamespace(com_forward_to_exit_deg=5.0),),
    )
    ch._ejecting(state, True, now)
    assert moves == [C4_TRAVEL_SIGN * 64.0]


def test_staging_stops_before_pushing_the_waiting_piece_off() -> None:
    ch, moves = _channel()
    now = time.monotonic()
    _piece(ch, 70, now, gap=two_piece._KEEP_ON_MIN_GAP_DEG + 1.0, obj=_classified())
    _piece(ch, 71, now, gap=230.0, zone=two_piece._ZONE_DROP, obj=_classified())
    ch._phase, ch._phase_started_at = _Phase.STAGING, now
    state = SimpleNamespace(
        in_drop=True, exit_com_forward_to_precise_deg=-20.0, exit_com_forward_deg=26.0
    )
    ch._staging(state, True, now)
    assert moves == []
    assert ch._phase == _Phase.WAITING


# ------------------------------------------------------------- pause / resume


def test_the_head_goes_alone_when_a_straddling_piece_keeps_the_gate_shut() -> None:
    """A piece left across the drop zone's edge makes the zone read occupied,
    so the feeder's gate never opens and no next piece comes; the waiting head
    goes out on its own instead of sitting until the stall watchdog sweeps."""
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified()
    head = _piece(ch, 54, now, gap=110.0, zone=0, obj=obj)
    ch.transport.placePieceForDistribution(obj)
    head.placed = True
    obj.stage = PieceStage.distributing
    ch.shared.distribution_ready = True
    ch._ready_since = None
    ch._phase_started_at = now - two_piece._HEAD_ALONE_AFTER_S - 1.0
    ch._maybeStartRotation()
    assert ch._phase == _Phase.EJECTING and ch._eject_target is head


def test_a_pause_keeps_the_pieces_and_places_the_head_again() -> None:
    ch, _ = _channel()
    now = time.monotonic()
    obj = _classified()
    head = _piece(ch, 337, now, gap=74.0, obj=obj)
    ch.transport.placePieceForDistribution(obj)
    head.placed = True
    ch._phase = _Phase.EJECTING
    ch._eject_target = head

    ch.pause()

    assert ch._pieces[337] is head and head.known_object is obj
    assert not head.placed
    assert ch.transport.getPieceForDistributionPositioning() is None
    assert ch._phase == _Phase.WAITING and ch._eject_target is None


def test_the_first_step_of_a_run_restarts_the_watchdog_clock() -> None:
    """Built, then homed and only resumed half a minute later: the stall
    watchdog must not count that wait and sweep the channel."""
    ch, _ = _channel()
    now = time.monotonic()
    ch.last_progress_at = now - 45.0
    ch.gc.perception_service = SimpleNamespace(
        read_state=lambda ch_id: SimpleNamespace(n_pieces=0, in_drop=False, pieces=())
    )
    ch.irl = SimpleNamespace(carousel_stepper=SimpleNamespace(stopped=True))
    ch.setClassificationReady = lambda ready, reason: None
    ch._recordCycle = lambda *a: None
    ch._captureDropPieces = lambda perception_service, now: None
    ch.step()
    assert ch.last_progress_at >= now


def test_resuming_refreshes_the_pieces_and_the_watchdog() -> None:
    ch, _ = _channel()
    now = time.monotonic()
    tp = _piece(ch, 337, now - 600.0, gap=74.0, obj=_classified())
    ch.last_progress_at = now - 600.0
    ch._resumeAfterPause(now)
    assert tp.last_seen == now
    assert ch.last_progress_at == now
    assert tp.worker.emits == 1


# ----------------------------------------------------------- the reaper's note


def test_a_timed_out_piece_says_how_long_and_in_what_state() -> None:
    stats = RuntimeStatsCollector()
    stats.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)
    obj = _classified()
    notePieceProblem(obj, "track_lost", "The camera lost track of it.")
    stats.observeKnownObject(
        {
            "uuid": obj.uuid,
            "created_at": 10.0,
            "updated_at": 20.0,
            "stage": "created",
            "classification_status": "classified",
            "problems": list(obj.problems),
        }
    )
    reaped = stats.reapStuckPieces(now=60.0, timeout_s=30.0)
    assert len(reaped) == 1
    kinds = [p["kind"] for p in reaped[0]["problems"]]
    assert kinds == ["track_lost", "timed_out"]
    note = reaped[0]["problems"][-1]
    assert note["after_s"] == 40.0
    assert "40 s" in note["message"] and "waiting to go to its bin" in note["message"]


def test_a_pause_does_not_count_toward_timing_out() -> None:
    stats = RuntimeStatsCollector()
    stats.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)
    stats.observeKnownObject(
        {"uuid": "p", "created_at": 10.0, "updated_at": 20.0, "stage": "created",
         "classification_status": "classified"}
    )
    stats.setLifecycleState("paused", now_wall=21.0, now_monotonic=21.0)
    stats.setLifecycleState("running", now_wall=500.0, now_monotonic=500.0)
    assert stats.reapStuckPieces(now=510.0, timeout_s=30.0) == []
    assert len(stats.reapStuckPieces(now=531.0, timeout_s=30.0)) == 1


# ------------------------------------------------- notes travel with the piece


def test_notes_go_out_with_the_piece_and_into_its_record() -> None:
    from run_recorder import _serializePiece
    from utils.event import knownObjectToEvent

    obj = _classified()
    notePieceProblem(obj, "pushed_off", "Still at the exit.", after_s=1.234)
    notePieceProblem(obj, "pushed_off", "Still at the exit.", after_s=2.0)  # same note: kept once
    event = knownObjectToEvent(obj)
    assert [p.kind for p in event.data.problems] == ["pushed_off"]
    assert event.data.problems[0].after_s == 1.2
    assert _serializePiece(obj)["problems"][0]["message"] == "Still at the exit."
