"""Arm the lip: while C4 is busy C3 walks the lead to exit_arm_gap_deg short
of the exit-only entry edge and holds; when C4 opens one sized release pulse
sends it over."""
from types import SimpleNamespace

from perception.cascade import Action, feederChannelAction
from subsystems.feeder.pulse_perception.flow import exitPulseOutputDeg


def _cfg(**over):
    base = dict(exit_pulse_output_deg=2.0, exit_pulse_pause_ms=600, tip_over_pause_ms=1200,
                exit_approach_output_deg=8.0, crowded_tip_output_deg=1.0, crowded_tip_speed_usteps_per_s=1500,
                exit_arm_gap_deg=10.0, exit_release_depth_deg=4.0, exit_release_max_output_deg=12.0)
    base.update(over)
    return SimpleNamespace(**base)


def _state(lead, *pieces, in_exit=True, in_drop=False):
    return SimpleNamespace(
        in_exit=in_exit, in_drop=in_drop, n_pieces=len(pieces) or 1, exit_com_forward_deg=lead,
        pieces=[SimpleNamespace(zone_code=z, com_forward_to_exit_deg=g) for z, g in pieces],
    )


def test_cascade_keeps_walking_until_armed_then_holds() -> None:
    assert feederChannelAction(_state(30.0), downstream_clear=False, arm_gap_deg=10.0) is Action.PRECISE
    assert feederChannelAction(_state(10.0), downstream_clear=False, arm_gap_deg=10.0) is Action.FREEZE
    assert feederChannelAction(_state(4.0), downstream_clear=False, arm_gap_deg=10.0) is Action.FREEZE
    assert feederChannelAction(_state(30.0), downstream_clear=False, arm_gap_deg=None) is Action.FREEZE  # off
    assert feederChannelAction(_state(30.0), downstream_clear=True, arm_gap_deg=10.0) is Action.PRECISE


def test_arming_pulses_stop_at_the_arm_gap_and_never_tip() -> None:
    cfg = _cfg()
    assert exitPulseOutputDeg(cfg, _state(30.0, (3, 30.0)), downstream_ready=False) == 8.0
    assert exitPulseOutputDeg(cfg, _state(14.0, (3, 14.0)), downstream_ready=False) == 4.0   # lands exactly on +10
    assert exitPulseOutputDeg(cfg, _state(10.0, (3, 10.0)), downstream_ready=False) == 0.0   # hold
    assert exitPulseOutputDeg(cfg, _state(-3.0, (2, -3.0)), downstream_ready=False) == 0.0   # never tip while busy
    assert exitPulseOutputDeg(_cfg(exit_arm_gap_deg=0.0), _state(30.0, (3, 30.0)), downstream_ready=False) == 0.0


def test_release_is_one_sized_pulse_for_an_armed_lonely_lead() -> None:
    cfg = _cfg()
    assert exitPulseOutputDeg(cfg, _state(10.0, (3, 10.0)), downstream_ready=True) == 12.0   # 10 + 4, capped at 12
    assert exitPulseOutputDeg(cfg, _state(5.0, (3, 5.0)), downstream_ready=True) == 9.0
    assert exitPulseOutputDeg(cfg, _state(20.0, (3, 20.0)), downstream_ready=True) == 6.0    # not armed: approach, bounded by the margin
    assert exitPulseOutputDeg(cfg, _state(10.0, (3, 10.0), (3, 18.0)), downstream_ready=True) == 12.0  # a follower 8° behind still fine


def test_release_yields_to_the_crowded_ladder_and_to_a_piece_already_at_the_lip() -> None:
    cfg = _cfg()
    assert exitPulseOutputDeg(cfg, _state(-3.0, (2, -3.0), (3, 12.0)), downstream_ready=True) == 1.0  # crowded
    assert exitPulseOutputDeg(cfg, _state(-3.0, (2, -3.0)), downstream_ready=True) == 2.0            # at the lip: tip
