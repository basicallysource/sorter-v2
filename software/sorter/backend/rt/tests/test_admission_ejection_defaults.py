from __future__ import annotations

from rt.contracts.admission import AdmissionDecision, AdmissionStrategy
from rt.contracts.ejection import EjectionTiming, EjectionTimingStrategy
from rt.contracts.registry import ADMISSION_STRATEGIES, EJECTION_TIMING_STRATEGIES

# Import side-effect registers strategies.
import rt.runtimes._strategies  # noqa: F401


def test_always_admit_registered() -> None:
    assert "always" in ADMISSION_STRATEGIES.keys()
    strategy: AdmissionStrategy = ADMISSION_STRATEGIES.create("always")
    assert strategy.key == "always"
    decision = strategy.can_admit({"piece_uuid": "x"}, {"ring_count": 99})
    assert isinstance(decision, AdmissionDecision)
    assert decision.allowed is True


def test_constant_ejection_registered() -> None:
    assert "constant" in EJECTION_TIMING_STRATEGIES.keys()
    strat: EjectionTimingStrategy = EJECTION_TIMING_STRATEGIES.create("constant")
    assert strat.key == "constant"
    timing = strat.timing_for({"track_id": 42})
    assert isinstance(timing, EjectionTiming)
    assert timing.pulse_ms > 0.0
    assert timing.settle_ms > 0.0
    assert timing.fall_time_ms > 0.0


def test_constant_ejection_accepts_custom_values() -> None:
    strat = EJECTION_TIMING_STRATEGIES.create(
        "constant",
        pulse_ms=25.0,
        settle_ms=60.0,
        fall_time_ms=200.0,
    )
    timing = strat.timing_for({})
    assert timing.pulse_ms == 25.0
    assert timing.settle_ms == 60.0
    assert timing.fall_time_ms == 200.0
