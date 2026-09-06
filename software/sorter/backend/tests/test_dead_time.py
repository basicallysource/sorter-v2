"""Station timeline recording and the dead-time overlap analysis."""
import logging
from types import SimpleNamespace

from dead_time import PATTERNS, Segment, StationTimeline, analyze
from runtime_stats import RuntimeStatsCollector


def _segments(**per_station):
    return {station: [Segment(*s) for s in segs] for station, segs in per_station.items()}


def test_timeline_cuts_segments_only_on_activity_change() -> None:
    tl = StationTimeline()
    tl.observe("c3", "advance", "3 on channel", now_wall=100.0, now_monotonic=10.0)
    tl.observe("c3", "advance", "2 on channel", now_wall=101.0, now_monotonic=11.0)
    tl.observe("c3", "arm", "1 on channel", now_wall=104.0, now_monotonic=14.0)
    snap = tl.snapshot(counting=True, now_monotonic=16.0)
    assert [e["activity"] for e in snap["timeline_recent"]] == ["advance", "arm"]
    assert snap["time_s"]["c3"] == {"advance": 4.0, "arm": 2.0}
    assert snap["current"]["c3"]["activity"] == "arm"
    segs = tl.segments(window_s=3.0, now_wall=106.0)
    assert segs["c3"] == [Segment(103.0, 104.0, "advance", "3 on channel"), Segment(104.0, 106.0, "arm", "1 on channel")]


def test_paused_time_does_not_count_as_station_time() -> None:
    stats = RuntimeStatsCollector()
    stats.setLifecycleState("running", now_wall=100.0, now_monotonic=10.0)
    stats.stations.observe("belt", "running", counting=True, now_wall=100.0, now_monotonic=10.0)
    stats.setLifecycleState("paused", now_wall=105.0, now_monotonic=15.0)
    stats.setLifecycleState("running", now_wall=205.0, now_monotonic=115.0)
    snap = stats.stations.snapshot(counting=True, now_monotonic=117.0)
    assert snap["time_s"]["belt"] == {"running": 7.0}
    assert "stations" in stats.snapshot()


def test_analysis_finds_the_serial_coupling_and_starvation_gaps() -> None:
    # 0-4 C4 classifies while C3 holds an armed piece; 4-6 C4 ejects, C3 still
    # holding; 6-8 C4 empty, C3 releasing; 8-10 C4 empty and C3 empty, belt held.
    segs = _segments(
        c4=[(0, 4, "classifying"), (4, 6, "ejecting"), (6, 10, "waiting_drop")],
        c3=[(0, 6, "armed_hold"), (6, 8, "release"), (8, 10, "empty")],
        belt=[(0, 8, "running"), (8, 10, "stopped_c3_full")],
    )
    result = analyze(segs, window_s=10.0, now_wall=10.0)
    by_key = {o["key"]: o for o in result["opportunities"]}
    assert by_key["c3_waits_for_c4"]["seconds"] == 6.0
    assert by_key["c3_waits_for_c4"]["breakdown"] == {"classifying": 4.0, "ejecting": 2.0}
    assert by_key["c3_waits_for_c4"]["episodes"] == 1 and by_key["c3_waits_for_c4"]["longest_s"] == 6.0
    assert by_key["c4_starved_c3_holding"]["seconds"] == 2.0
    assert by_key["c4_starved_c3_empty"]["breakdown"] == {"stopped_c3_full": 2.0}
    assert by_key["c4_classifying"]["share_pct"] == 40.0
    assert "c4_waits_for_chute" not in by_key
    assert result["stations"]["c4"]["time_s"] == {"waiting_drop": 4.0, "classifying": 4.0, "ejecting": 2.0}
    assert result["opportunities"][0]["key"] == "c3_waits_for_c4"


def test_episodes_split_on_interruptions_and_keep_the_longest() -> None:
    segs = _segments(
        c4=[(0, 10, "aiming")],
        distribution=[(0, 3, "positioning"), (3, 4, "idle"), (4, 10, "positioning")],
    )
    result = analyze(segs, window_s=10.0, now_wall=10.0, patterns=[p for p in PATTERNS if p.key == "c4_waits_for_chute"])
    (opp,) = result["opportunities"]
    assert opp["seconds"] == 10.0 and opp["episodes"] == 1  # the pattern only looks at c4
    assert opp["breakdown"] == {"positioning": 9.0, "idle": 1.0}


def test_pattern_needs_every_station_it_names() -> None:
    result = analyze(_segments(c4=[(0, 10, "waiting_drop")]), window_s=10.0, now_wall=10.0)
    assert {o["key"] for o in result["opportunities"]} == set()  # no c3 data: no verdict


class _Stats:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def observeStation(self, station, activity, detail="") -> None:
        self.seen.append((station, activity))


def test_c3_station_activity_from_action_and_plan(monkeypatch) -> None:
    from perception.cascade import Action
    from subsystems.feeder.pulse_perception import flow
    from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig

    handler = object.__new__(flow.PulsePerceptionFeeding)
    handler.gc = SimpleNamespace(runtime_stats=_Stats(), logger=logging.getLogger("test"))
    cfg = PulsePerceptionConfig()
    piece = SimpleNamespace(zone_code=2, com_forward_to_exit_deg=3.0, gap_to_next_deg=None)
    at_lip = SimpleNamespace(pieces=[piece], in_exit=True, in_drop=False, ts=1.0)
    empty = SimpleNamespace(pieces=[], in_exit=False, in_drop=False, ts=1.0)
    monkeypatch.setattr(flow, "c3ExitMotionPlan", lambda cfg, state, ready, channel=3: flow.C3ExitPlan("hold", 0.0, 0, 1, False, False))
    handler._reportC3Station(Action.PRECISE, at_lip, cfg, downstream_ready=False, held=False)
    handler._reportC3Station(Action.FREEZE, at_lip, cfg, downstream_ready=False, held=False)
    handler._reportC3Station(Action.IDLE, empty, cfg, downstream_ready=True, held=False)
    handler._reportC3Station(Action.ADVANCE, at_lip, cfg, downstream_ready=True, held=True)
    assert handler.gc.runtime_stats.seen == [("c3", "armed_hold"), ("c3", "waiting_c4"), ("c3", "empty"), ("c3", "held_incident")]


def test_c4_station_activity_follows_the_head_and_drop_state() -> None:
    from subsystems.classification_channel.two_piece import _ZONE_DROP, PieceStage, TwoPieceClassificationChannel, _Phase, _TrackedPiece

    h = object.__new__(TwoPieceClassificationChannel)
    h._pieces, h._orphans, h._aliases = {}, [], {}
    h._phase = _Phase.WAITING
    h.shared = SimpleNamespace(distribution_ready=False)
    empty = SimpleNamespace(pieces=[])

    def piece(tid, zone, **flags):
        tp = object.__new__(_TrackedPiece)
        tp.track_id, tp.zone, tp.gap_to_exit, tp.off_platter, tp.ejected = tid, zone, 50.0, False, False
        tp.capture_done = tp.result_applied = tp.placed = False
        tp.worker = SimpleNamespace(ctx=SimpleNamespace(known_object=None))
        for k, v in flags.items():
            setattr(tp, k, v)
        h._pieces[tid] = tp
        return tp

    assert h._stationActivity(empty, stopped=True, aligning=False) == ("waiting_drop", "")
    assert h._stationActivity(empty, stopped=True, aligning=True) == ("aligning", "")
    drop = piece(1, _ZONE_DROP)
    assert h._stationActivity(empty, stopped=True, aligning=False)[0] == "capturing"
    drop.capture_done = True
    assert h._stationActivity(empty, stopped=True, aligning=False)[0] == "ready"
    del h._pieces[1]
    head = piece(2, 3, capture_done=True)  # zone 3 = precise arc, forward of the drop zone
    assert h._stationActivity(empty, stopped=True, aligning=False)[0] == "classifying"
    head.result_applied = head.placed = True
    assert h._stationActivity(empty, stopped=True, aligning=False)[0] == "aiming"
    h.shared.distribution_ready = True
    head.worker.ctx.known_object = SimpleNamespace(stage=PieceStage.distributing)
    assert h._stationActivity(empty, stopped=True, aligning=False)[0] == "waiting_successor"
    h._phase = _Phase.EJECTING
    assert h._stationActivity(empty, stopped=False, aligning=False) == ("ejecting", "")
