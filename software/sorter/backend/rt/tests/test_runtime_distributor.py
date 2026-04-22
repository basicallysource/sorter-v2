from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from rt.contracts.classification import ClassifierResult
from rt.contracts.rules import BinDecision, RulesEngine
from rt.contracts.runtime import RuntimeInbox
from rt.coupling.slots import CapacitySlot
from rt.runtimes._strategies import C4EjectionTiming
from rt.runtimes.distributor import RuntimeDistributor


class _InlineHw:
    """HwWorker-compatible double that executes commands synchronously."""

    def __init__(self) -> None:
        self._busy = False
        self.labels: list[str] = []

    def start(self) -> None:
        return None

    def stop(self, timeout_s: float = 2.0) -> None:
        return None

    def enqueue(
        self,
        command: Callable[[], None],
        *,
        priority: int = 0,
        label: str = "hw_cmd",
    ) -> bool:
        self.labels.append(label)
        self._busy = True
        try:
            command()
        finally:
            self._busy = False
        return True

    def busy(self) -> bool:
        return self._busy

    def pending(self) -> int:
        return 0


@dataclass
class _FakeRules(RulesEngine):
    decision: BinDecision = field(
        default_factory=lambda: BinDecision(
            bin_id="L0-S0-B0",
            category="bricks",
            reason="matched_profile:bricks",
        )
    )
    calls: int = 0
    key: str = "fake"

    def decide_bin(
        self,
        classification: ClassifierResult,
        context: dict[str, Any],
    ) -> BinDecision:
        self.calls += 1
        return self.decision

    def reload(self) -> None:  # pragma: no cover
        return None


def _classification(part_id: str = "3001") -> ClassifierResult:
    return ClassifierResult(
        part_id=part_id,
        color_id="red",
        category=None,
        confidence=0.9,
        algorithm="stub",
        latency_ms=5.0,
        meta={},
    )


@dataclass
class _Recorder:
    ready: list[str] = field(default_factory=list)
    delivered: list[str] = field(default_factory=list)
    acks: list[tuple[str, bool, str]] = field(default_factory=list)
    moves: list[str] = field(default_factory=list)


def _make(
    *,
    rules: RulesEngine | None = None,
    fall_time_ms: float = 0.0,
    position_query_seq: list[str | None] | None = None,
    chute_move_succeeds: bool = True,
) -> tuple[RuntimeDistributor, CapacitySlot, _Recorder, _FakeRules, _InlineHw]:
    upstream = CapacitySlot("c4_to_dist", capacity=1)
    upstream.try_claim()  # Simulate C4 reserving the slot on handoff.
    rec = _Recorder()
    fake_rules = rules or _FakeRules()
    position_steps = list(position_query_seq or [])

    def move(bin_id: str) -> bool:
        rec.moves.append(bin_id)
        return bool(chute_move_succeeds)

    def position_query() -> str | None:
        if position_steps:
            return position_steps.pop(0)
        # Default: report "settled at last commanded bin" after the first call.
        return rec.moves[-1] if rec.moves else None

    def on_ready(uuid: str) -> None:
        rec.ready.append(uuid)

    def on_delivered(uuid: str) -> None:
        rec.delivered.append(uuid)

    def on_ack(uuid: str, accepted: bool, reason: str) -> None:
        rec.acks.append((uuid, accepted, reason))

    hw = _InlineHw()
    dist = RuntimeDistributor(
        upstream_slot=upstream,
        rules_engine=fake_rules,
        ejection_timing=C4EjectionTiming(
            pulse_ms=150.0, settle_ms=100.0, fall_time_ms=fall_time_ms
        ),
        chute_move_command=move,
        chute_position_query=position_query,
        on_ready_callback=on_ready,
        on_piece_delivered_callback=on_delivered,
        on_ack_callback=on_ack,
        hw_worker=hw,  # type: ignore[arg-type]
        chute_settle_s=0.0,
    )
    return dist, upstream, rec, (
        fake_rules if isinstance(fake_rules, _FakeRules) else _FakeRules()
    ), hw


def _inbox() -> RuntimeInbox:
    return RuntimeInbox(tracks=None, capacity_downstream=0)


# ----------------------------------------------------------------------


def test_initial_state_is_idle() -> None:
    dist, *_ = _make()
    assert dist.fsm_state() == "idle"
    assert dist.available_slots() == 1
    assert dist.pending_piece_uuid() is None


def test_handoff_request_triggers_positioning() -> None:
    dist, _upstream, rec, rules, _hw = _make()
    accepted = dist.handoff_request(
        piece_uuid="p1",
        classification=_classification(),
        now_mono=1.0,
    )
    assert accepted is True
    assert dist.fsm_state() == "positioning"
    assert dist.pending_piece_uuid() == "p1"
    assert rec.moves == ["L0-S0-B0"]
    assert rules.calls == 1
    assert dist.available_slots() == 0


def test_busy_distributor_rejects_second_handoff() -> None:
    dist, *_ = _make()
    ok1 = dist.handoff_request(piece_uuid="p1", classification=_classification())
    ok2 = dist.handoff_request(piece_uuid="p2", classification=_classification())
    assert ok1 is True
    assert ok2 is False


def test_tick_transitions_to_ready_and_fires_on_ready() -> None:
    dist, _upstream, rec, *_ = _make()
    dist.handoff_request(piece_uuid="p1", classification=_classification(), now_mono=1.0)
    dist.tick(_inbox(), now_mono=1.1)
    assert dist.fsm_state() == "ready"
    assert rec.ready == ["p1"]


def test_handoff_commit_arms_sending_and_completes_delivery() -> None:
    dist, upstream, rec, *_ = _make(fall_time_ms=0.0)
    dist.handoff_request(piece_uuid="p1", classification=_classification(), now_mono=1.0)
    dist.tick(_inbox(), now_mono=1.1)
    assert dist.fsm_state() == "ready"

    ok = dist.handoff_commit("p1", now_mono=1.2)
    assert ok is True
    assert dist.fsm_state() == "sending"

    # Fall time = 0 -> next tick completes the delivery.
    dist.tick(_inbox(), now_mono=1.3)
    assert rec.delivered == ["p1"]
    assert rec.acks == [("p1", True, "matched_profile:bricks")]
    # Upstream slot released; new piece could be admitted next.
    assert upstream.available() == 1
    # FSM walks through commit_wait -> idle on the following tick.
    assert dist.fsm_state() in ("commit_wait", "idle")
    dist.tick(_inbox(), now_mono=1.4)
    assert dist.fsm_state() == "idle"


def test_handoff_commit_rejected_in_wrong_state() -> None:
    dist, *_ = _make()
    # Not ready yet.
    dist.handoff_request(piece_uuid="p1", classification=_classification(), now_mono=1.0)
    ok = dist.handoff_commit("p1", now_mono=1.05)
    assert ok is False


def test_unknown_part_triggers_reject_dispatch() -> None:
    rules = _FakeRules(
        decision=BinDecision(bin_id=None, category=None, reason="unknown_part")
    )
    dist, upstream, rec, _, _hw = _make(rules=rules)
    dist.handoff_request(
        piece_uuid="p_unknown",
        classification=ClassifierResult(
            part_id=None,
            color_id=None,
            category=None,
            confidence=0.0,
            algorithm="stub",
            latency_ms=0.0,
            meta={},
        ),
        now_mono=2.0,
    )
    assert dist.fsm_state() == "reject_dispatch"
    assert rec.moves == ["reject"]

    # Tick -> settled -> sending (no C4 handshake on reject path)
    dist.tick(_inbox(), now_mono=2.1)
    assert dist.fsm_state() == "sending"
    # Complete fall-time window.
    dist.tick(_inbox(), now_mono=2.2)
    assert rec.acks == [("p_unknown", False, "unknown_part")]
    # on_delivered is NOT called for rejects.
    assert rec.delivered == []
    assert upstream.available() == 1


def test_position_timeout_raises_reject() -> None:
    # Position query never matches target.
    def never_match() -> str | None:
        return "some_other_bin"

    upstream = CapacitySlot("c4_to_dist", 1)
    upstream.try_claim()
    rec = _Recorder()

    def move(bin_id: str) -> bool:
        rec.moves.append(bin_id)
        return True

    def on_ready(uuid: str) -> None:
        rec.ready.append(uuid)

    def on_delivered(uuid: str) -> None:
        rec.delivered.append(uuid)

    def on_ack(uuid: str, accepted: bool, reason: str) -> None:
        rec.acks.append((uuid, accepted, reason))

    hw = _InlineHw()
    dist = RuntimeDistributor(
        upstream_slot=upstream,
        rules_engine=_FakeRules(),
        ejection_timing=C4EjectionTiming(
            pulse_ms=150.0, settle_ms=100.0, fall_time_ms=0.0
        ),
        chute_move_command=move,
        chute_position_query=never_match,
        on_ready_callback=on_ready,
        on_piece_delivered_callback=on_delivered,
        on_ack_callback=on_ack,
        hw_worker=hw,  # type: ignore[arg-type]
        position_timeout_s=0.5,
        chute_settle_s=0.0,
    )
    dist.handoff_request(piece_uuid="p1", classification=_classification(), now_mono=10.0)
    dist.tick(_inbox(), now_mono=10.1)
    assert dist.fsm_state() == "positioning"
    dist.tick(_inbox(), now_mono=11.0)  # Past timeout.
    assert rec.acks == [("p1", False, "position_timeout")]
    assert rec.delivered == []


def test_rules_engine_exception_triggers_reject() -> None:
    class _Boom(_FakeRules):
        def decide_bin(self, classification, context):
            raise RuntimeError("bad profile")

    dist, _upstream, rec, _rules, _hw = _make(rules=_Boom())
    accepted = dist.handoff_request(
        piece_uuid="p1", classification=_classification(), now_mono=1.0
    )
    # Still returns True because we start positioning on reject_bin anyway,
    # BUT the decision is a None bin => reject_dispatch path + reject bin.
    assert accepted is True
    assert dist.pending_target_bin() == "reject"


def test_on_piece_delivered_noop() -> None:
    dist, *_ = _make()
    # Terminal runtime; confirms the callback is a no-op.
    dist.on_piece_delivered("p_anything", now_mono=0.0)


def test_available_slots_reflects_pending_state() -> None:
    dist, *_ = _make(fall_time_ms=0.0)
    assert dist.available_slots() == 1
    dist.handoff_request(piece_uuid="p1", classification=_classification(), now_mono=0.0)
    assert dist.available_slots() == 0
    dist.tick(_inbox(), now_mono=0.1)  # -> ready
    dist.handoff_commit("p1", now_mono=0.2)
    dist.tick(_inbox(), now_mono=0.3)  # -> commit_wait
    dist.tick(_inbox(), now_mono=0.4)  # -> idle
    assert dist.available_slots() == 1


def test_event_bus_publishes_piece_distributed() -> None:
    from rt.contracts.events import Event, EventBus

    published: list[Event] = []

    class _Bus(EventBus):  # type: ignore[misc]
        def publish(self, event: Event) -> None:
            published.append(event)

        def subscribe(self, topic_glob, handler):  # pragma: no cover
            raise NotImplementedError

        def drain(self) -> None:  # pragma: no cover
            return None

        def start(self) -> None:  # pragma: no cover
            return None

        def stop(self) -> None:  # pragma: no cover
            return None

    upstream = CapacitySlot("c4_to_dist", 1)
    upstream.try_claim()
    rec = _Recorder()
    hw = _InlineHw()
    dist = RuntimeDistributor(
        upstream_slot=upstream,
        rules_engine=_FakeRules(),
        ejection_timing=C4EjectionTiming(
            pulse_ms=150.0, settle_ms=100.0, fall_time_ms=0.0
        ),
        chute_move_command=lambda b: (rec.moves.append(b) or True),
        chute_position_query=lambda: rec.moves[-1] if rec.moves else None,
        on_ready_callback=rec.ready.append,
        on_piece_delivered_callback=rec.delivered.append,
        on_ack_callback=lambda u, a, r: rec.acks.append((u, a, r)),
        hw_worker=hw,  # type: ignore[arg-type]
        event_bus=_Bus(),
        chute_settle_s=0.0,
    )
    dist.handoff_request(piece_uuid="p1", classification=_classification(), now_mono=0.0)
    dist.tick(_inbox(), now_mono=0.1)
    dist.handoff_commit("p1", now_mono=0.2)
    dist.tick(_inbox(), now_mono=0.3)

    assert len(published) == 1
    evt = published[0]
    assert evt.topic == "piece.distributed"
    assert evt.payload["piece_uuid"] == "p1"
    assert evt.payload["bin_id"] == "L0-S0-B0"
    assert evt.payload["accepted"] is True
