from __future__ import annotations

import pytest

from rt.contracts.admission import AdmissionDecision

from rt.runtimes._strategies.admission_c4 import C4Admission


def _state(**overrides):
    base = {
        "raw_detection_count": 0,
        "zone_count": 0,
        "dropzone_clear": True,
        "arc_clear": True,
        "transport_count": 0,
    }
    base.update(overrides)
    return base


def test_c4_allows_when_state_empty() -> None:
    strategy = C4Admission(max_zones=1)
    decision = strategy.can_admit({}, _state())
    assert isinstance(decision, AdmissionDecision)
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_c4_blocks_on_raw_cap() -> None:
    strategy = C4Admission(max_zones=2, max_raw_detections=3)
    decision = strategy.can_admit({}, _state(raw_detection_count=3))
    assert decision.allowed is False
    assert decision.reason == "raw_cap"


def test_c4_raw_cap_is_disabled_by_default() -> None:
    strategy = C4Admission(max_zones=2)
    decision = strategy.can_admit({}, _state(raw_detection_count=99))
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_c4_raw_cap_zero_disables_guard() -> None:
    strategy = C4Admission(max_zones=2, max_raw_detections=0)
    decision = strategy.can_admit({}, _state(raw_detection_count=99))
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_c4_blocks_when_dropzone_not_clear() -> None:
    strategy = C4Admission(max_zones=2, max_raw_detections=3)
    decision = strategy.can_admit({}, _state(dropzone_clear=False))
    assert decision.allowed is False
    assert decision.reason == "dropzone_clear"


def test_c4_blocks_on_zone_cap() -> None:
    strategy = C4Admission(max_zones=2)
    decision = strategy.can_admit({}, _state(zone_count=2))
    assert decision.allowed is False
    assert decision.reason == "zone_cap"


def test_c4_blocks_on_arc_not_clear() -> None:
    strategy = C4Admission(max_zones=2)
    decision = strategy.can_admit({}, _state(arc_clear=False))
    assert decision.allowed is False
    assert decision.reason == "arc_clear"


def test_c4_blocks_on_transport_cap() -> None:
    strategy = C4Admission(max_zones=1)
    decision = strategy.can_admit({}, _state(transport_count=1))
    assert decision.allowed is False
    assert decision.reason == "transport_cap"


def test_c4_dropzone_short_circuits_other_checks() -> None:
    # Physical laydown clearance wins over heuristic/raw-count guards.
    strategy = C4Admission(max_zones=2, max_raw_detections=3)
    decision = strategy.can_admit(
        {},
        _state(
            dropzone_clear=False,
            raw_detection_count=5,
            zone_count=99,
            arc_clear=False,
            transport_count=99,
        ),
    )
    assert decision.allowed is False
    assert decision.reason == "dropzone_clear"


def test_c4_validates_constructor_inputs() -> None:
    with pytest.raises(ValueError):
        C4Admission(max_zones=0)


def test_c4_accepts_missing_state_fields() -> None:
    strategy = C4Admission(max_zones=1)
    # Empty state behaves like all zeros + arc_clear=True.
    decision = strategy.can_admit({}, {})
    assert decision.allowed is True
