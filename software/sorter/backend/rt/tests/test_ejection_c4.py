from __future__ import annotations

import pytest

from rt.contracts.ejection import EjectionTiming

from rt.runtimes._strategies.ejection_c4 import C4EjectionTiming


def test_c4_ejection_accepts_custom_values() -> None:
    strat = C4EjectionTiming(
        pulse_ms=120.0,
        settle_ms=400.0,
        fall_time_ms=1200.0,
    )
    timing = strat.timing_for({})
    assert isinstance(timing, EjectionTiming)
    assert timing.pulse_ms == 120.0
    assert timing.settle_ms == 400.0
    assert timing.fall_time_ms == 1200.0


def test_c4_ejection_constant_across_contexts() -> None:
    strat = C4EjectionTiming(pulse_ms=100.0, settle_ms=200.0, fall_time_ms=800.0)
    a = strat.timing_for({"size_class": "S"})
    b = strat.timing_for({"size_class": "L"})
    assert a == b


def test_c4_ejection_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        C4EjectionTiming(pulse_ms=0.0)
    with pytest.raises(ValueError):
        C4EjectionTiming(settle_ms=-1.0)
    with pytest.raises(ValueError):
        C4EjectionTiming(fall_time_ms=-1.0)
