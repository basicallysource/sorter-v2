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
