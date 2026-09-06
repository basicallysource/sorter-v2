"""Arm the lip (Codex review 2026-09-06): while C4 is busy C3 walks the lead
to the approach margin and holds; when C4 opens a bounded fast move takes it
to +8°, then the normal tips."""
from types import SimpleNamespace

from perception.cascade import Action, feederChannelAction
from subsystems.feeder.pulse_perception.flow import (
    APPROACH_MARGIN_DEG,
    ARM_TOLERANCE_DEG,
    RELEASE_FLOOR_GAP_DEG,
    RELEASE_MAX_OUTPUT_DEG,
    armGapDeg,
    c3ExitMotionPlan,
)


def _cfg(**over):
    base = dict(exit_pulse_output_deg=2.0, exit_pulse_pause_ms=600, tip_over_pause_ms=1200,
                exit_approach_output_deg=8.0, crowded_tip_output_deg=1.0, crowded_tip_speed_usteps_per_s=1500,
                ch3_move_speed_usteps_per_s=3000, ch2_move_speed_usteps_per_s=3000, ch1_move_speed_usteps_per_s=3000,
                exit_arm_enabled=True)
    base.update(over)
    return SimpleNamespace(**base)


def _state(*pieces, in_exit=True, in_drop=False, ts=1.0):
    gaps = [g for _, g in pieces]
    return SimpleNamespace(
        ts=ts, in_exit=in_exit, in_drop=in_drop, n_pieces=len(pieces),
        exit_com_forward_deg=min(gaps) if gaps else None,
        pieces=[SimpleNamespace(zone_code=z, com_forward_to_exit_deg=g) for z, g in pieces],
    )


def test_arm_gap_is_the_existing_approach_margin() -> None:
    assert armGapDeg(_cfg()) == APPROACH_MARGIN_DEG == 14.0
    assert armGapDeg(_cfg(exit_arm_enabled=False)) is None


def test_busy_far_lead_arms_with_bounded_pulses_and_the_band_holds() -> None:
    cfg = _cfg()
    p = c3ExitMotionPlan(cfg, _state((3, 30.0)), downstream_ready=False)
    assert (p.kind, p.output_deg, p.pause_ms, p.dispense_capable, p.wants_advance) == ("arm", 8.0, 600, False, True)
    p = c3ExitMotionPlan(cfg, _state((3, 20.0)), downstream_ready=False)
    assert p.kind == "arm" and p.output_deg == 6.0             # lands exactly on the 14° margin
    for gap in (16.0, 15.0, 14.0, 5.0, -3.0):
        p = c3ExitMotionPlan(cfg, _state((3 if gap > 0 else 2, gap)), downstream_ready=False)
        assert p.kind == "hold" and p.output_deg == 0.0 and not p.wants_advance, gap
    assert c3ExitMotionPlan(_cfg(exit_arm_enabled=False), _state((3, 30.0)), downstream_ready=False).kind == "hold"


def test_cascade_freezes_in_the_arm_band_so_the_watchdog_sees_no_advance() -> None:
    arm = armGapDeg(_cfg()) + ARM_TOLERANCE_DEG
    assert feederChannelAction(_state((3, 30.0)), downstream_clear=False, arm_gap_deg=arm) is Action.PRECISE
    assert feederChannelAction(_state((3, 16.0)), downstream_clear=False, arm_gap_deg=arm) is Action.FREEZE
    assert feederChannelAction(_state((3, 30.0)), downstream_clear=False, arm_gap_deg=None) is Action.FREEZE


def test_unknown_gap_fails_safe() -> None:
    state = SimpleNamespace(ts=1.0, in_exit=True, in_drop=False, n_pieces=1, exit_com_forward_deg=None,
                            pieces=[SimpleNamespace(zone_code=3, com_forward_to_exit_deg=None)])
    assert c3ExitMotionPlan(_cfg(), state, downstream_ready=True).kind == "hold"
    assert c3ExitMotionPlan(_cfg(), state, downstream_ready=False).kind == "hold"


def test_open_gate_release_is_bounded_to_the_floor_and_carries_tip_timing() -> None:
    cfg = _cfg()
    p = c3ExitMotionPlan(cfg, _state((3, 16.0)), downstream_ready=True)
    assert (p.kind, p.output_deg, p.pause_ms, p.dispense_capable) == ("release", 8.0, 1200, True)  # 16 -> 8
    p = c3ExitMotionPlan(cfg, _state((3, 12.0)), downstream_ready=True)
    assert (p.kind, p.output_deg) == ("release", 4.0)                                          # 12 -> 8
    assert RELEASE_MAX_OUTPUT_DEG == 8.0 and RELEASE_FLOOR_GAP_DEG == 8.0
    for gap in (10.0, 9.0, 4.0):                                                                 # at/below floor + tip: normal tips
        p = c3ExitMotionPlan(cfg, _state((3, gap)), downstream_ready=True)
        assert (p.kind, p.output_deg, p.pause_ms) == ("tip", 2.0, 1200), gap
    p = c3ExitMotionPlan(cfg, _state((2, -3.0)), downstream_ready=True)
    assert (p.kind, p.output_deg, p.pause_ms) == ("tip", 2.0, 1200)


def test_far_lead_with_open_gate_still_approaches_as_before() -> None:
    p = c3ExitMotionPlan(_cfg(), _state((3, 30.0)), downstream_ready=True)
    assert (p.kind, p.output_deg, p.pause_ms, p.dispense_capable) == ("approach", 8.0, 600, False)


def test_prospective_crowding_before_the_lip_forces_the_gentle_ladder() -> None:
    cfg = _cfg()
    p = c3ExitMotionPlan(cfg, _state((3, 15.0), (3, 30.0)), downstream_ready=True)   # follower 15° behind
    assert (p.kind, p.output_deg, p.speed, p.pause_ms) == ("crowded_tip", 1.0, 1500, 1200)
    p = c3ExitMotionPlan(cfg, _state((3, 15.0), (0, 45.0)), downstream_ready=True)   # 30° behind: fast release allowed
    assert p.kind == "release"
    p = c3ExitMotionPlan(cfg, _state((2, -3.0), (3, 12.0)), downstream_ready=True)   # a lip piece with a close follower
    assert (p.kind, p.output_deg, p.speed) == ("crowded_tip", 1.0, 1500)


def test_greedy_follower_in_the_drop_zone_does_not_change_the_plan() -> None:
    p = c3ExitMotionPlan(_cfg(), _state((3, 15.0), (1, 200.0), in_drop=True), downstream_ready=True)
    assert p.kind == "release" and p.output_deg == 7.0
