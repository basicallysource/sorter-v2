from types import SimpleNamespace

from subsystems.feeder.pulse_perception.flow import exitPulseOutputDeg


def _cfg(approach=8.0, tip=2.0):
    return SimpleNamespace(exit_pulse_output_deg=tip, exit_approach_output_deg=approach)


def _state(*codes):
    return SimpleNamespace(pieces=[SimpleNamespace(zone_code=c) for c in codes])


def test_large_pulse_in_the_approach_band_small_pulse_once_a_piece_is_at_the_lip() -> None:
    assert exitPulseOutputDeg(_cfg(), _state(3)) == 8.0        # precise = approach band
    assert exitPulseOutputDeg(_cfg(), _state(3, 1)) == 8.0     # plus one in drop
    assert exitPulseOutputDeg(_cfg(), _state(2)) == 2.0        # at the lip
    assert exitPulseOutputDeg(_cfg(), _state(3, 2)) == 2.0     # one at the lip, one behind


def test_disabled_approach_or_unknown_state_keeps_the_tip_over_pulse() -> None:
    assert exitPulseOutputDeg(_cfg(approach=0.0), _state(3)) == 2.0
    assert exitPulseOutputDeg(_cfg(), SimpleNamespace()) == 2.0


def test_tip_over_hold_constant_covers_the_admission_window_gap() -> None:
    from subsystems.feeder.pulse_perception.flow import TIP_OVER_HOLD_S
    assert 1.0 <= TIP_OVER_HOLD_S <= 2.0


def test_tip_over_pulses_pace_slower_than_approach_pulses() -> None:
    from subsystems.feeder.pulse_perception.flow import exitPulsePauseMs
    cfg = SimpleNamespace(exit_pulse_output_deg=2.0, exit_pulse_pause_ms=600, tip_over_pause_ms=1200)
    assert exitPulsePauseMs(cfg, 2.0) == 1200
    assert exitPulsePauseMs(cfg, 8.0) == 600
    cfg.tip_over_pause_ms = 100  # never below the base pause
    assert exitPulsePauseMs(cfg, 2.0) == 600


def test_approach_pulse_is_bounded_by_the_gap_to_the_exit_only_band() -> None:
    cfg = _cfg(approach=8.0, tip=2.0)
    far = SimpleNamespace(pieces=[SimpleNamespace(zone_code=3, com_forward_to_exit_deg=30.0)])
    mid = SimpleNamespace(pieces=[SimpleNamespace(zone_code=3, com_forward_to_exit_deg=20.0)])
    near = SimpleNamespace(pieces=[SimpleNamespace(zone_code=3, com_forward_to_exit_deg=15.0)])
    assert exitPulseOutputDeg(cfg, far) == 8.0
    assert exitPulseOutputDeg(cfg, mid) == 6.0       # 20 - 14 margin
    assert exitPulseOutputDeg(cfg, near) == 2.0      # within margin + tip: tip-over only
