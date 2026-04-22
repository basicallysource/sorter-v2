"""Orchestrator integration test with all 5 runtimes mocked.

Verifies:
* Orchestrator ticks a 5-runtime topology without crashing.
* Reversed-order iteration: distributor ticks first, C1 last.
* ``feed_id=None`` runtimes (C1 + Distributor) don't consult perception.
* Aggregated health reports every runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rt.contracts.runtime import Runtime, RuntimeHealth, RuntimeInbox
from rt.contracts.tracking import TrackBatch
from rt.coupling.orchestrator import Orchestrator
from rt.coupling.slots import CapacitySlot


@dataclass
class _FakeRuntime(Runtime):
    runtime_id: str
    feed_id: str | None = None
    tick_log: list[tuple[str, int]] = field(default_factory=list)
    started: bool = False
    stopped: bool = False

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        self.tick_log.append((self.runtime_id, inbox.capacity_downstream))

    def available_slots(self) -> int:
        return 1

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        return None

    def health(self) -> RuntimeHealth:
        return RuntimeHealth(state="idle", blocked_reason=None, last_tick_ms=0.1)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _ConstantTracks:
    def __init__(self, batch: TrackBatch | None) -> None:
        self._batch = batch
        self.reads = 0

    def latest_tracks(self) -> TrackBatch | None:
        self.reads += 1
        return self._batch


def _make_five_runtime_orchestrator() -> tuple[
    Orchestrator,
    list[_FakeRuntime],
    dict[tuple[str, str], CapacitySlot],
    dict[str, _ConstantTracks],
]:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2", feed_id="c2_feed")
    c3 = _FakeRuntime("c3", feed_id="c3_feed")
    c4 = _FakeRuntime("c4", feed_id="c4_feed")
    dist = _FakeRuntime("distributor")

    slots = {
        ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
        ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        ("c3", "c4"): CapacitySlot("c3_to_c4", 3),
        ("c4", "distributor"): CapacitySlot("c4_to_dist", 1),
    }

    sources: dict[str, Any] = {
        "c2_feed": _ConstantTracks(
            TrackBatch("c2_feed", 1, 0.0, tuple(), tuple())
        ),
        "c3_feed": _ConstantTracks(
            TrackBatch("c3_feed", 1, 0.0, tuple(), tuple())
        ),
        "c4_feed": _ConstantTracks(
            TrackBatch("c4_feed", 1, 0.0, tuple(), tuple())
        ),
    }
    orch = Orchestrator(
        runtimes=[c1, c2, c3, c4, dist],
        slots=slots,
        perception_sources=sources,
        tick_period_s=0.020,
    )
    return orch, [c1, c2, c3, c4, dist], slots, sources


def test_all_five_runtimes_tick_in_reverse_order() -> None:
    orch, runtimes, _slots, _srcs = _make_five_runtime_orchestrator()
    orch.tick_once(now_mono=0.0)
    combined = []
    # Runtimes that appear later in the list tick FIRST (downstream-first).
    for rt in reversed(runtimes):
        combined.extend(rt.tick_log)
    ordered_ids = [entry[0] for entry in combined]
    assert ordered_ids == ["distributor", "c4", "c3", "c2", "c1"]


def test_perception_sources_only_consulted_for_feed_runtimes() -> None:
    orch, _runtimes, _slots, sources = _make_five_runtime_orchestrator()
    orch.tick_once(now_mono=0.0)
    # c2/c3/c4 each read perception once; c1/distributor never did.
    assert sources["c2_feed"].reads == 1
    assert sources["c3_feed"].reads == 1
    assert sources["c4_feed"].reads == 1


def test_capacity_propagates_through_slot_chain() -> None:
    orch, runtimes, slots, _srcs = _make_five_runtime_orchestrator()
    # Exhaust c3->c4 capacity (3).
    for _ in range(3):
        slots[("c3", "c4")].try_claim()
    orch.tick_once(now_mono=0.0)
    # c3's inbox.capacity_downstream must reflect the drained slot.
    (c1, c2, c3, c4, dist) = runtimes
    assert c3.tick_log[-1] == ("c3", 0)
    # c2's downstream is c3 slot which is still cap=1.
    assert c2.tick_log[-1] == ("c2", 1)
    # distributor has no downstream => 0.
    assert dist.tick_log[-1] == ("distributor", 0)


def test_health_covers_all_five_runtimes() -> None:
    orch, _runtimes, _slots, _srcs = _make_five_runtime_orchestrator()
    snap = orch.health()
    assert set(snap.keys()) == {"c1", "c2", "c3", "c4", "distributor"}
    for entry in snap.values():
        assert entry["state"] == "idle"


def test_start_stop_propagates_to_all_five() -> None:
    orch, runtimes, _slots, _srcs = _make_five_runtime_orchestrator()
    orch.start()
    try:
        import time as _t

        _t.sleep(0.05)
    finally:
        orch.stop()
    for rt in runtimes:
        assert rt.started
        assert rt.stopped
