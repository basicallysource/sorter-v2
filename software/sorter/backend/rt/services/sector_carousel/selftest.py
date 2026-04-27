from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .handler import SectorCarouselHandler
from .slot import SlotPhase


@dataclass(slots=True)
class _ScenarioResult:
    name: str
    passed: bool
    checks: list[str]
    failures: list[str]
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "checks": list(self.checks),
            "failures": list(self.failures),
            "metrics": dict(self.metrics),
        }


def run_sector_carousel_ladder_selftest() -> dict[str, Any]:
    """Run a deterministic software-only preflight for the sector carousel.

    The selftest deliberately avoids cameras, steppers, event buses, and API
    state. It validates the state machine invariants that must hold before
    any live machine ladder begins.
    """

    started = time.perf_counter()
    scenarios = [
        _scenario_phase_gate(),
        _scenario_single_piece_lifecycle(),
        _scenario_five_token_ring(),
        _scenario_fault_injection(),
        _scenario_slow_classifier_stale_result(),
    ]
    failures = [
        failure
        for scenario in scenarios
        for failure in scenario.failures
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "ok": not failures,
        "scenario_count": len(scenarios),
        "passed_count": sum(1 for scenario in scenarios if scenario.passed),
        "failed_count": sum(1 for scenario in scenarios if not scenario.passed),
        "elapsed_ms": elapsed_ms,
        "scenarios": [scenario.as_dict() for scenario in scenarios],
    }


def _scenario_phase_gate() -> _ScenarioResult:
    result = _result("phase_gate")
    moves: list[float] = []
    handler = SectorCarouselHandler(
        c4_transport=lambda deg: moves.append(float(deg)) or True,
        require_phase_verification=True,
        sector_step_deg=2.0,
        rotation_chunk_deg=2.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-phase", now_mono=1.0)
    _ready_all_slots(handler)

    _expect(
        result,
        "rotation blocked before phase verification",
        handler.rotate_one_sector(now_mono=2.0) is False and not moves,
    )
    _expect(
        result,
        "phase gate visible",
        handler.gate_status(now_mono=2.0)["reasons"][0]["reason"]
        == "phase_verification_required",
    )

    handler.verify_phase(source="selftest", measured_offset_deg=0.0, now_mono=2.1)

    _expect(
        result,
        "rotation allowed after phase verification",
        handler.rotate_one_sector(now_mono=2.2) is True and moves == [2.0],
    )
    _expect_invariants_ok(result, handler, now_mono=2.2)
    result.metrics["move_count"] = len(moves)
    return _finish(result)


def _scenario_single_piece_lifecycle() -> _ScenarioResult:
    result = _result("single_piece_lifecycle")
    dropped: list[str] = []
    handler = SectorCarouselHandler(
        c4_eject=lambda: dropped.append("piece-1") or True,
        settle_s=0.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)

    _advance_ready(handler, 2.0)
    _advance_ready(handler, 3.0)
    handler.slots[2].classification = "class-red"
    _advance_ready(handler, 4.0)
    handler.slots[3].distributor_ready = True
    _advance_ready(handler, 5.0)
    handler.tick(5.1)

    _expect(
        result,
        "piece reaches dropped-pending-clear",
        handler.slots[4].phase is SlotPhase.DROPPED_PENDING_CLEAR
        and handler.slots[4].ejected,
    )
    _advance_ready(handler, 6.0)
    _expect(
        result,
        "piece clears after next rotation",
        all(not slot.occupied for slot in handler.slots),
    )
    _expect(result, "eject called exactly once", dropped == ["piece-1"])
    _expect_invariants_ok(result, handler, now_mono=6.0)
    result.metrics["rotations"] = handler.snapshot(now_mono=6.0)["counters"]["rotations"]
    return _finish(result)


def _scenario_five_token_ring() -> _ScenarioResult:
    result = _result("five_token_ring")
    classes = {
        "A": "class_red",
        "B": "class_blue",
        "C": "class_green",
        "D": "class_yellow",
        "E": "class_reject",
    }
    dropped: list[tuple[str, str]] = []
    handler = SectorCarouselHandler(
        c4_eject=lambda: True,
        settle_s=0.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()

    pieces = list(classes)
    next_piece = 0
    now = 1.0
    guard = 0
    while next_piece < len(pieces) or any(slot.occupied for slot in handler.slots):
        guard += 1
        if guard > 50:
            result.failures.append("five-token ring exceeded iteration guard")
            break
        if next_piece < len(pieces) and not handler.slots[0].occupied:
            handler.inject_at_slot1(pieces[next_piece], now_mono=now)
            next_piece += 1
        for slot in handler.slots:
            if slot.phase is SlotPhase.CLASSIFYING:
                slot.classification = classes[str(slot.piece_uuid)]
            elif slot.phase is SlotPhase.DROPPING and not slot.ejected:
                dropped.append((str(slot.piece_uuid), str(slot.classification)))
                handler.tick(now + 0.05)
        _ready_all_slots(handler)
        _expect_invariants_ok(result, handler, now_mono=now)
        if any(slot.occupied for slot in handler.slots):
            handler.rotate_one_sector(now_mono=now + 0.1)
        now += 1.0

    expected = list(classes.items())
    _expect(result, "all five tokens dropped in class order", dropped == expected)
    _expect_invariants_ok(result, handler, now_mono=now)
    result.metrics["dropped"] = dropped
    result.metrics["event_count"] = len(handler.recent_events(limit=200))
    return _finish(result)


def _scenario_fault_injection() -> _ScenarioResult:
    result = _result("fault_injection")
    handler = SectorCarouselHandler(settle_s=0.0, rotation_chunk_settle_s=0.0)
    handler.enable()

    handler.on_c3_handoff_trigger(
        _event(
            piece_uuid="piece-no-lease",
            landing_lease_id=None,
            ts_mono=1.0,
        )
    )
    _expect(
        result,
        "handoff without lease rejected",
        handler.snapshot(now_mono=1.0)["blocked"] == "handoff_missing_landing_lease",
    )

    lease = handler.request_lease(
        predicted_arrival_in_s=0.6,
        min_spacing_deg=30.0,
        now_mono=2.0,
        track_global_id=7,
    )
    _expect(result, "first landing lease granted", isinstance(lease, str))
    second = handler.request_lease(
        predicted_arrival_in_s=0.6,
        min_spacing_deg=30.0,
        now_mono=2.1,
        track_global_id=8,
    )
    _expect(result, "second landing lease rejected while pending", second is None)

    handler.on_c3_handoff_trigger(
        _event(
            piece_uuid="piece-ok",
            landing_lease_id=lease,
            ts_mono=2.2,
        )
    )
    _expect(
        result,
        "valid leased handoff injects slot 1",
        handler.slots[0].piece_uuid == "piece-ok",
    )
    blocked_lease = handler.request_lease(
        predicted_arrival_in_s=0.6,
        min_spacing_deg=30.0,
        now_mono=2.3,
        track_global_id=9,
    )
    _expect(result, "slot1 occupied rejects new lease", blocked_lease is None)
    _expect_invariants_ok(result, handler, now_mono=2.3)
    result.metrics["errors"] = handler.snapshot(now_mono=2.3)["counters"]["errors"]
    return _finish(result)


def _scenario_slow_classifier_stale_result() -> _ScenarioResult:
    result = _result("slow_classifier_stale_result")
    handler = SectorCarouselHandler(settle_s=0.0, rotation_chunk_settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-slow", now_mono=1.0)
    _advance_ready(handler, 2.0)
    _advance_ready(handler, 3.0)

    slot = handler.slots[2]
    slot.classifier_request_id = "request-current"
    applied = handler.bind_classification(
        "piece-slow",
        "wrong",
        request_id="request-old",
        now_mono=3.5,
    )
    _expect(result, "stale classifier result rejected", applied is False)
    _expect(
        result,
        "classification remains unset after stale result",
        slot.classification is None,
    )
    ok = handler.bind_classification(
        "piece-slow",
        "class-good",
        request_id="request-current",
        now_mono=3.6,
    )
    _expect(result, "current classifier result applied", ok is True)
    _expect(result, "classification is correct", slot.classification == "class-good")
    _expect_invariants_ok(result, handler, now_mono=3.6)
    result.metrics["stale_classifier_results"] = handler.snapshot(now_mono=3.6)[
        "counters"
    ]["stale_classifier_results"]
    return _finish(result)


def _advance_ready(handler: SectorCarouselHandler, now_mono: float) -> None:
    _ready_all_slots(handler)
    rotated = handler.rotate_one_sector(now_mono=now_mono)
    if not rotated:
        gates = handler.gate_status(now_mono=now_mono, include_cooldown=False)
        raise AssertionError(f"selftest rotate failed: {gates}")


def _ready_all_slots(handler: SectorCarouselHandler) -> None:
    for slot in handler.slots:
        if slot.phase is SlotPhase.CAPTURING:
            slot.capture_done = True
        elif slot.phase is SlotPhase.CLASSIFYING and slot.classification is None:
            slot.classification = f"class-{slot.piece_uuid}"
        elif slot.phase is SlotPhase.AWAITING_DIST:
            slot.distributor_ready = True
        elif slot.phase is SlotPhase.DROPPING:
            handler.tick(float(slot.entered_phase_at) + 0.01)


def _event(
    *,
    piece_uuid: str,
    landing_lease_id: str | None,
    ts_mono: float,
) -> Any:
    from rt.contracts.events import Event
    from rt.events.topics import C3_HANDOFF_TRIGGER

    payload: dict[str, Any] = {"piece_uuid": piece_uuid}
    if landing_lease_id is not None:
        payload["landing_lease_id"] = landing_lease_id
    return Event(
        topic=C3_HANDOFF_TRIGGER,
        payload=payload,
        source="sector-carousel-selftest",
        ts_mono=float(ts_mono),
    )


def _result(name: str) -> _ScenarioResult:
    return _ScenarioResult(name=name, passed=False, checks=[], failures=[], metrics={})


def _finish(result: _ScenarioResult) -> _ScenarioResult:
    result.passed = not result.failures
    return result


def _expect(
    result: _ScenarioResult,
    label: str,
    condition: bool,
) -> None:
    result.checks.append(label)
    if not condition:
        result.failures.append(label)


def _expect_invariants_ok(
    result: _ScenarioResult,
    handler: SectorCarouselHandler,
    *,
    now_mono: float,
) -> None:
    status = handler.invariant_status(now_mono=now_mono)
    _expect(
        result,
        f"invariants ok at {now_mono:.2f}",
        bool(status.get("ok")),
    )
    if not status.get("ok"):
        result.metrics.setdefault("invariant_violations", []).append(
            status.get("violations")
        )


__all__ = ["run_sector_carousel_ladder_selftest"]
