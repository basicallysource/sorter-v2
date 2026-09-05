from types import SimpleNamespace

from subsystems.feeder.pulse_perception.flow import exitPulseOutputDeg


def _cfg(approach=8.0, tip=2.0):
    return SimpleNamespace(exit_pulse_output_deg=tip, exit_approach_output_deg=approach)


def test_large_pulse_before_the_precise_arc_small_pulse_inside_it() -> None:
    assert exitPulseOutputDeg(_cfg(), SimpleNamespace(in_precise=False)) == 8.0
    assert exitPulseOutputDeg(_cfg(), SimpleNamespace(in_precise=True)) == 2.0


def test_disabled_approach_keeps_the_tip_over_pulse() -> None:
    assert exitPulseOutputDeg(_cfg(approach=0.0), SimpleNamespace(in_precise=False)) == 2.0
    assert exitPulseOutputDeg(_cfg(), SimpleNamespace()) == 2.0  # unknown state: cautious
