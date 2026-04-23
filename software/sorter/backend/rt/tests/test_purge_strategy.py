from __future__ import annotations

from dataclasses import dataclass, field

from rt.contracts.purge import PurgeCounts
from rt.runtimes._strategies.purge_generic import GenericPurgeStrategy


@dataclass
class FakePort:
    key: str = "cX"
    counts_seq: list[PurgeCounts] = field(default_factory=list)
    arm_calls: int = 0
    disarm_calls: int = 0
    drain_calls: list[float] = field(default_factory=list)
    _idx: int = 0

    def arm(self) -> None:
        self.arm_calls += 1

    def disarm(self) -> None:
        self.disarm_calls += 1

    def counts(self) -> PurgeCounts:
        if not self.counts_seq:
            return PurgeCounts(0, 0, 0)
        idx = min(self._idx, len(self.counts_seq) - 1)
        self._idx += 1
        return self.counts_seq[idx]

    def drain_step(self, now_mono: float) -> bool:
        self.drain_calls.append(float(now_mono))
        return True


def test_arm_calls_port_and_marks_armed() -> None:
    port = FakePort()
    strat = GenericPurgeStrategy(port, clear_hold_ms=500.0)

    assert strat.is_armed is False
    strat.arm()
    assert strat.is_armed is True
    assert port.arm_calls == 1


def test_tick_drives_drain_when_not_empty() -> None:
    port = FakePort(
        counts_seq=[PurgeCounts(ring_count=3, owned_count=0, pending_detections=0)]
    )
    strat = GenericPurgeStrategy(port, clear_hold_ms=500.0)
    strat.arm()

    result = strat.tick(now_mono=1.0)

    assert port.drain_calls == [1.0]
    assert result.done is False
    assert result.counts.ring_count == 3


def test_clear_hold_needs_two_ticks_before_done() -> None:
    port = FakePort(
        counts_seq=[
            PurgeCounts(0, 0, 0),  # tick @ 1.0 — sets clear_since
            PurgeCounts(0, 0, 0),  # tick @ 1.3 — within hold window, not done
            PurgeCounts(0, 0, 0),  # tick @ 1.6 — clear_hold elapsed, done
        ]
    )
    strat = GenericPurgeStrategy(port, clear_hold_ms=500.0)
    strat.arm()

    r1 = strat.tick(1.0)
    r2 = strat.tick(1.3)
    r3 = strat.tick(1.6)

    assert r1.done is False
    assert r2.done is False
    assert r3.done is True
    assert port.drain_calls == []


def test_reappearing_piece_resets_clear_hold() -> None:
    port = FakePort(
        counts_seq=[
            PurgeCounts(0, 0, 0),  # clear
            PurgeCounts(ring_count=2, owned_count=0, pending_detections=0),  # piece arrives
            PurgeCounts(0, 0, 0),  # clear again — clear_since must reset
        ]
    )
    strat = GenericPurgeStrategy(port, clear_hold_ms=500.0)
    strat.arm()

    strat.tick(1.0)
    strat.tick(1.2)
    result = strat.tick(1.6)

    assert result.done is False
    assert port.drain_calls == [1.2]
    assert strat.is_channel_clear(1.6) is False


def test_is_channel_clear_true_only_after_hold() -> None:
    port = FakePort(
        counts_seq=[PurgeCounts(0, 0, 0), PurgeCounts(0, 0, 0), PurgeCounts(0, 0, 0)]
    )
    strat = GenericPurgeStrategy(port, clear_hold_ms=400.0)
    strat.arm()

    strat.tick(1.0)
    assert strat.is_channel_clear(1.1) is False
    assert strat.is_channel_clear(1.45) is True


def test_disarm_calls_port_and_clears_state() -> None:
    port = FakePort(counts_seq=[PurgeCounts(0, 0, 0)])
    strat = GenericPurgeStrategy(port, clear_hold_ms=100.0)
    strat.arm()
    strat.tick(1.0)

    strat.disarm()

    assert strat.is_armed is False
    assert port.disarm_calls == 1
    assert strat.is_channel_clear(5.0) is True


def test_channel_property_matches_port_key() -> None:
    port = FakePort(key="c3")
    strat = GenericPurgeStrategy(port)
    assert strat.channel == "c3"


def test_does_not_auto_disarm_on_clear() -> None:
    port = FakePort(counts_seq=[PurgeCounts(0, 0, 0)] * 5)
    strat = GenericPurgeStrategy(port, clear_hold_ms=50.0)
    strat.arm()
    for t in (1.0, 1.1, 1.2, 1.3, 1.4):
        strat.tick(t)
    assert strat.is_armed is True
    assert port.disarm_calls == 0


def test_negative_clear_hold_rejected() -> None:
    port = FakePort()
    import pytest

    with pytest.raises(ValueError):
        GenericPurgeStrategy(port, clear_hold_ms=-1.0)


def test_tick_when_not_armed_is_done_without_drain() -> None:
    port = FakePort(
        counts_seq=[PurgeCounts(ring_count=5, owned_count=0, pending_detections=0)]
    )
    strat = GenericPurgeStrategy(port, clear_hold_ms=100.0)

    result = strat.tick(1.0)

    assert result.done is True
    assert port.drain_calls == []
