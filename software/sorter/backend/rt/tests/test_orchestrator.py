from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from rt.contracts.runtime import Runtime, RuntimeHealth, RuntimeInbox
from rt.contracts.tracking import TrackBatch
from rt.coupling.orchestrator import Orchestrator
from rt.coupling.slots import CapacitySlot


@dataclass(slots=True)
class _TickEvent:
    runtime_id: str
    capacity_downstream: int
    tracks: Any


class _FakeRuntime(Runtime):
    def __init__(
        self,
        runtime_id: str,
        *,
        feed_id: str | None = None,
        raises: bool = False,
    ) -> None:
        self.runtime_id = runtime_id
        self.feed_id = feed_id
        self.ticks: list[_TickEvent] = []
        self.started = False
        self.stopped = False
        self._raises = raises
        self._available_slots = 1
        self._debug_snapshot: dict[str, Any] = {}
        self._capacity_debug_snapshot: dict[str, Any] = {}
        self._health = RuntimeHealth(state="idle", blocked_reason=None, last_tick_ms=0.5)

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        if self._raises:
            raise RuntimeError("boom")
        self.ticks.append(
            _TickEvent(
                runtime_id=self.runtime_id,
                capacity_downstream=inbox.capacity_downstream,
                tracks=inbox.tracks,
            )
        )

    def available_slots(self) -> int:
        return self._available_slots

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        return None

    def health(self) -> RuntimeHealth:
        return self._health

    def debug_snapshot(self) -> dict[str, Any]:
        return dict(self._debug_snapshot)

    def capacity_debug_snapshot(self) -> dict[str, Any]:
        return dict(self._capacity_debug_snapshot)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeTrackSource:
    def __init__(self, batch: TrackBatch | None) -> None:
        self._batch = batch

    def latest_tracks(self) -> TrackBatch | None:
        return self._batch


def _make_orchestrator(runtimes: list[Runtime], slots: dict, sources=None) -> Orchestrator:
    return Orchestrator(
        runtimes=runtimes,
        slots=slots,
        perception_sources=sources or {},
        tick_period_s=0.010,
    )


def test_tick_order_is_downstream_first() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2", feed_id="c2_feed")
    c3 = _FakeRuntime("c3", feed_id="c3_feed")
    slots = {
        ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
        ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
    }
    orch = _make_orchestrator([c1, c2, c3], slots)
    orch.tick_once(now_mono=0.0)
    # Reversed order: c3 first, then c2, then c1.
    ordered_ticks = c3.ticks + c2.ticks + c1.ticks
    assert [t.runtime_id for t in ordered_ticks] == ["c3", "c2", "c1"]


def test_sector_carousel_mode_enables_handler_and_bypasses_c4_scheduler() -> None:
    c4 = _FakeRuntime("c4", feed_id="c4_feed")
    active_flags: list[bool] = []
    c4.set_carousel_mode_active = active_flags.append  # type: ignore[attr-defined]
    slots = {("c4", "distributor"): CapacitySlot("c4_to_dist", 1)}
    orch = _make_orchestrator([c4], slots)

    class _Handler:
        def __init__(self) -> None:
            self.enabled = False
            self.ticks: list[float] = []

        def enable(self) -> None:
            self.enabled = True

        def disable(self) -> None:
            self.enabled = False

        def tick(self, now_mono: float) -> None:
            self.ticks.append(now_mono)

        def snapshot(self) -> dict[str, Any]:
            return {"enabled": self.enabled}

    handler = _Handler()
    orch.attach_sector_carousel_handler(handler)

    assert orch.set_c4_mode("sector_carousel") == "sector_carousel"
    orch.tick_once(now_mono=12.0)

    assert active_flags == [True]
    assert handler.enabled is True
    assert handler.ticks == [12.0]

    assert orch.set_c4_mode("runtime") == "runtime"
    assert active_flags == [True, False]
    assert handler.enabled is False


def test_capacity_downstream_pulled_from_downstream_runtime() -> None:
    """Capacity is sourced from the downstream runtime's own headroom.

    The historical behaviour also gated on ``CapacitySlot.available()``,
    which created the bug a transient claim would block all upstream
    movement for its 3 s expiry even when the downstream channel was
    empty. The orchestrator now trusts ``available_slots()`` alone.
    """
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2", feed_id="c2_feed")
    c2._available_slots = 3
    slot = CapacitySlot("c1_to_c2", 99)
    slots = {("c1", "c2"): slot}
    orch = _make_orchestrator([c1, c2], slots)

    orch.tick_once(now_mono=0.0)
    assert c1.ticks[-1].capacity_downstream == 3
    # A slot claim no longer reduces upstream-visible capacity — the
    # downstream runtime's own count is the only source of truth.
    slot.try_claim()
    c2._available_slots = 2
    orch.tick_once(now_mono=0.1)
    assert c1.ticks[-1].capacity_downstream == 2
    # c2 has no downstream wired -> capacity should be 0.
    assert c2.ticks[-1].capacity_downstream == 0


def test_capacity_downstream_is_limited_by_downstream_runtime_headroom() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c2._available_slots = 0
    slot = CapacitySlot("c1_to_c2", 3)
    orch = _make_orchestrator([c1, c2], {("c1", "c2"): slot})

    orch.tick_once(now_mono=0.0)
    assert c1.ticks[-1].capacity_downstream == 0

    c2._available_slots = 2
    orch.tick_once(now_mono=0.1)
    assert c1.ticks[-1].capacity_downstream == 2


def test_c1_capacity_obeys_c3_transitive_backpressure() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c2._available_slots = 2
    c3._available_slots = 0
    c3._capacity_debug_snapshot = {"reason": "piece_cap", "piece_count": 8}
    orch = _make_orchestrator(
        [c1, c2, c3],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        },
    )

    orch.tick_once(now_mono=0.0)

    assert c2.ticks[-1].capacity_downstream == 0
    assert c1.ticks[-1].capacity_downstream == 0
    c1_capacity = orch.status_snapshot()["capacity_debug"]["c1"]
    assert c1_capacity["downstream"] == "c3"
    assert c1_capacity["immediate_downstream"] == "c2"
    assert c1_capacity["reason"] == "piece_cap"

    c3._available_slots = 1
    orch.tick_once(now_mono=0.1)

    assert c1.ticks[-1].capacity_downstream == 2


def test_c1_capacity_obeys_c4_backlog_backpressure() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    c2._available_slots = 2
    c3._available_slots = 1
    c4._available_slots = 2
    c4._debug_snapshot = {
        "raw_detection_count": 6,
        "dossier_count": 3,
    }
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )

    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 0
    c1_capacity = orch.status_snapshot()["capacity_debug"]["c1"]
    assert c1_capacity["downstream"] == "c4"
    assert c1_capacity["immediate_downstream"] == "c2"
    assert c1_capacity["reason"] == "backlog_dossiers"
    assert c1_capacity["controller"]["name"] == "c1_c4_backpressure"

    # Hysteresis: dropping just below the high water mark must NOT
    # unblock C1. Both counters need to relax to/below the resume
    # thresholds first (default raw_resume=4, dossier_resume=1).
    c4._debug_snapshot = {
        "raw_detection_count": 6,
        "dossier_count": 2,
    }
    orch.tick_once(now_mono=0.1)
    assert c1.ticks[-1].capacity_downstream == 0
    assert (
        orch.status_snapshot()["capacity_debug"]["c1"]["reason"]
        == "backlog_dossiers_holding"
    )

    c4._debug_snapshot = {
        "raw_detection_count": 4,
        "dossier_count": 1,
    }
    orch.tick_once(now_mono=0.2)
    assert c1.ticks[-1].capacity_downstream == 2


def test_c1_c4_backpressure_can_be_tuned_live() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    c2._available_slots = 2
    c3._available_slots = 1
    c4._available_slots = 2
    c4._debug_snapshot = {
        "raw_detection_count": 6,
        "dossier_count": 2,
    }
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )

    orch.update_c1_c4_backpressure(raw_high=6, dossier_high=4)
    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 0
    assert orch.status_snapshot()["capacity_debug"]["c1"]["reason"] == "backlog_raw"
    assert orch.c1_c4_backpressure_snapshot()["raw_high"] == 6


def test_c1_c4_backpressure_hysteresis_holds_in_band() -> None:
    """Once the gate trips at high water it stays blocked through the band.

    Reproduces the documented oscillation failure mode: with a single
    threshold the gate would re-open as soon as dossiers dipped below
    ``dossier_high``, letting C1 fire another bulk pulse before the line
    had actually drained. Hysteresis keeps the block sticky until both
    counters relax to/below the resume thresholds.
    """
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    c2._available_slots = 2
    c3._available_slots = 1
    c4._available_slots = 2
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )
    orch.update_c1_c4_backpressure(
        raw_high=7,
        dossier_high=3,
        raw_resume=3,
        dossier_resume=0,
    )

    # Initially clear — C1 may feed.
    c4._debug_snapshot = {"raw_detection_count": 0, "dossier_count": 0}
    orch.tick_once(now_mono=0.0)
    assert c1.ticks[-1].capacity_downstream == 2

    # Cross high-water on dossiers — block engages.
    c4._debug_snapshot = {"raw_detection_count": 5, "dossier_count": 3}
    orch.tick_once(now_mono=0.1)
    assert c1.ticks[-1].capacity_downstream == 0
    assert orch.status_snapshot()["capacity_debug"]["c1"]["reason"] == "backlog_dossiers"

    # Drop just below high-water — without hysteresis this used to
    # unblock immediately. The sticky block must hold.
    c4._debug_snapshot = {"raw_detection_count": 5, "dossier_count": 2}
    orch.tick_once(now_mono=0.2)
    assert c1.ticks[-1].capacity_downstream == 0
    assert (
        orch.status_snapshot()["capacity_debug"]["c1"]["reason"]
        == "backlog_dossiers_holding"
    )

    # Dossier reaches resume but raw still above raw_resume — still blocked.
    c4._debug_snapshot = {"raw_detection_count": 5, "dossier_count": 0}
    orch.tick_once(now_mono=0.3)
    assert c1.ticks[-1].capacity_downstream == 0
    assert (
        orch.status_snapshot()["capacity_debug"]["c1"]["reason"]
        == "backlog_raw_holding"
    )

    # Both counters at/below resume — gate releases.
    c4._debug_snapshot = {"raw_detection_count": 3, "dossier_count": 0}
    orch.tick_once(now_mono=0.4)
    assert c1.ticks[-1].capacity_downstream == 2
    assert orch.c1_c4_backpressure_snapshot()["blocked"] is False


def test_orchestrator_feeder_mode_defaults_to_lease() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    assert orch.feeder_mode() == "lease"


def test_orchestrator_rejects_section_mode_without_handler() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    with pytest.raises(RuntimeError, match="section feeder handler"):
        orch.set_feeder_mode("section")


def test_orchestrator_section_mode_skips_c1_c2_c3_runtimes() -> None:
    """In section mode the orchestrator must not tick c1/c2/c3 — the
    section handler owns those decisions. C4 still ticks normally so
    classification + distribution keep running."""

    class _StubHandler:
        def __init__(self) -> None:
            self.tick_calls = 0
            self._enabled = False

        def enable(self) -> None:
            self._enabled = True

        def disable(self) -> None:
            self._enabled = False

        def tick(self, **kwargs) -> None:
            self.tick_calls += 1

        def snapshot(self) -> dict[str, Any]:
            return {"enabled": self._enabled, "tick_calls": self.tick_calls}

    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )
    handler = _StubHandler()
    orch.attach_section_feeder_handler(handler)

    # Lease mode: all runtimes tick, handler does not.
    orch.tick_once(now_mono=0.0)
    assert len(c1.ticks) == 1
    assert len(c4.ticks) == 1
    assert handler.tick_calls == 0

    # Switch to section mode.
    orch.set_feeder_mode("section")
    assert handler._enabled is True

    orch.tick_once(now_mono=0.020)
    # c1/c2/c3 must NOT have ticked again; c4 must have.
    assert len(c1.ticks) == 1
    assert len(c2.ticks) == 1
    assert len(c3.ticks) == 1
    assert len(c4.ticks) == 2
    assert handler.tick_calls == 1

    # Switch back to lease.
    orch.set_feeder_mode("lease")
    assert handler._enabled is False
    orch.tick_once(now_mono=0.040)
    assert len(c1.ticks) == 2
    assert handler.tick_calls == 1  # not ticked again


def test_orchestrator_c4_mode_defaults_to_runtime() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    assert orch.c4_mode() == "runtime"


def test_orchestrator_rejects_legacy_carousel_mode() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    with pytest.raises(ValueError, match="c4_mode"):
        orch.set_c4_mode("carousel")


def test_orchestrator_c4_mode_switch_toggles_runtime_sector_flag() -> None:
    """Switching to sector carousel flips RuntimeC4 into external-scheduler mode."""

    class _StubC4(_FakeRuntime):
        def __init__(self) -> None:
            super().__init__("c4")
            self.carousel_active = False

        def set_carousel_mode_active(self, active: bool) -> None:
            self.carousel_active = bool(active)

    class _StubSectorCarousel:
        def __init__(self) -> None:
            self.enabled = False

        def enable(self) -> None:
            self.enabled = True

        def disable(self) -> None:
            self.enabled = False

        def snapshot(self) -> dict[str, Any]:
            return {}

        def tick(self, now_mono: float | None = None) -> None:
            return None

        def bind_front_classification(self, **kwargs: Any) -> bool:
            return False

    c1 = _FakeRuntime("c1")
    c4 = _StubC4()
    orch = _make_orchestrator(
        [c1, c4], {("c1", "c4"): CapacitySlot("c1_to_c4", 1)}
    )
    handler = _StubSectorCarousel()
    orch.attach_sector_carousel_handler(handler)

    orch.set_c4_mode("sector_carousel")
    assert handler.enabled is True
    assert c4.carousel_active is True

    orch.set_c4_mode("runtime")
    assert handler.enabled is False
    assert c4.carousel_active is False


def test_orchestrator_sector_handler_binds_front_classification_when_active() -> None:
    """Sector mode mirrors RuntimeC4's front classification into the slot scheduler."""

    class _StubC4(_FakeRuntime):
        def __init__(self) -> None:
            super().__init__("c4")
            self.carousel_active = False

        def set_carousel_mode_active(self, active: bool) -> None:
            self.carousel_active = bool(active)

        def carousel_front_snapshot(self) -> dict[str, Any] | None:
            return {
                "piece_uuid": "p1",
                "global_id": 7,
                "angle_deg": 12.0,
                "exit_distance_deg": 18.0,
                "classification_present": True,
                "classification": "brick",
                "dossier": {"piece_uuid": "p1"},
            }

    class _StubSectorCarousel:
        def __init__(self) -> None:
            self.tick_calls: list[float | None] = []
            self.bound: list[dict[str, Any]] = []
            self.enabled = False

        def enable(self) -> None:
            self.enabled = True

        def disable(self) -> None:
            self.enabled = False

        def snapshot(self) -> dict[str, Any]:
            return {"enabled": self.enabled}

        def tick(self, now_mono: float | None = None) -> None:
            self.tick_calls.append(now_mono)

        def bind_front_classification(self, **kwargs: Any) -> bool:
            self.bound.append(kwargs)
            return True

    c1 = _FakeRuntime("c1")
    c4 = _StubC4()
    orch = _make_orchestrator(
        [c1, c4],
        {
            ("c1", "c4"): CapacitySlot("c1_to_c4", 1),
        },
    )
    handler = _StubSectorCarousel()
    orch.attach_sector_carousel_handler(handler)

    # Runtime mode: handler not ticked.
    orch.tick_once(now_mono=0.0)
    assert handler.tick_calls == []

    orch.set_c4_mode("sector_carousel")
    orch.tick_once(now_mono=0.020)
    assert handler.tick_calls == [0.020]
    assert handler.bound == [
        {
            "c4_piece_uuid": "p1",
            "classification": "brick",
            "dossier": {"piece_uuid": "p1"},
            "now_mono": 0.020,
        }
    ]


def test_orchestrator_c4_mode_switch_toggles_sector_handler() -> None:
    class _StubSectorCarousel:
        def __init__(self) -> None:
            self.enabled = False

        def enable(self) -> None:
            self.enabled = True

        def disable(self) -> None:
            self.enabled = False

        def snapshot(self) -> dict[str, Any]:
            return {"enabled": self.enabled}

        def tick(self, now_mono: float | None = None) -> None:
            return None

    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    handler = _StubSectorCarousel()
    orch.attach_sector_carousel_handler(handler)

    orch.set_c4_mode("sector_carousel")
    assert handler.enabled is True
    snap = orch.status_snapshot()
    assert snap["c4_mode"] == "sector_carousel"
    assert snap["sector_carousel_handler"] == {"enabled": True}

    orch.set_c4_mode("runtime")
    assert handler.enabled is False
    assert orch.c4_mode() == "runtime"


def test_orchestrator_status_snapshot_exposes_feeder_mode() -> None:
    class _StubHandler:
        def enable(self) -> None: ...
        def disable(self) -> None: ...
        def tick(self, **kwargs) -> None: ...
        def snapshot(self) -> dict[str, Any]:
            return {"enabled": False}

    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    orch.attach_section_feeder_handler(_StubHandler())
    snap = orch.status_snapshot()
    assert snap["feeder_mode"] == "lease"
    assert snap["section_feeder_handler"] == {"enabled": False}


def test_orchestrator_advances_attached_pulse_observer_each_tick() -> None:
    """The orchestrator must call ``observer.tick`` so deadlines advance."""

    class _StubObserver:
        def __init__(self) -> None:
            self.tick_count = 0

        def tick(self, now_mono: float) -> None:
            self.tick_count += 1

        def summary(self) -> dict[str, Any]:
            return {"completed_count": 0}

        def in_flight(self) -> list[dict[str, Any]]:
            return []

        def recent(self, limit: int = 20) -> list[dict[str, Any]]:
            return []

    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2],
        {("c1", "c2"): CapacitySlot("c1_to_c2", 1)},
    )
    obs = _StubObserver()
    orch.attach_c1_pulse_observer(obs)

    orch.tick_once(now_mono=0.0)
    orch.tick_once(now_mono=0.020)
    orch.tick_once(now_mono=0.040)

    assert obs.tick_count == 3
    snapshot = orch.status_snapshot()
    assert snapshot["c1_pulse_observer"] == {"completed_count": 0}


def test_orchestrator_cross_runtime_snapshot_pulls_c2_density_and_c4_counts() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    c2._capacity_debug_snapshot = {
        "density": {
            "piece_count_estimate": 4,
            "occupancy_area_px": 1234,
            "clump_score": 0.42,
            "free_arc_fraction": 0.61,
            "exit_queue_length": 1,
        },
        "visible_track_count": 5,
    }
    c4._debug_snapshot = {
        "raw_detection_count": 6,
        "raw_track_count": 7,
        "dossier_count": 2,
    }
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )

    snap = orch.cross_runtime_snapshot()
    assert snap["c2_piece_count_estimate"] == 4.0
    assert snap["c2_occupancy_area_px"] == 1234.0
    assert snap["c2_clump_score"] == pytest.approx(0.42)
    assert snap["c2_free_arc_fraction"] == pytest.approx(0.61)
    assert snap["c2_exit_queue_length"] == 1.0
    assert snap["c2_visible_track_count"] == 5.0
    assert snap["c4_raw_detection_count"] == 6.0
    assert snap["c4_raw_track_count"] == 7.0
    assert snap["c4_dossier_count"] == 2.0


def test_c1_recovery_admission_blocks_high_levels_without_headroom() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    # C2 currently holds 11 equivalent pieces; default safe capacity is 14
    # so headroom is 3. Default level estimates are (3, 6, 12, 25, 40),
    # so only level 0 (3) should be admitted.
    c2._capacity_debug_snapshot = {
        "density": {
            "piece_count_estimate": 11,
            "occupancy_area_px": 0,
            "clump_score": 0.0,
            "free_arc_fraction": 0.0,
            "exit_queue_length": 0,
        },
    }
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )

    allowed_l0, info_l0 = orch.c1_recovery_admission_decision(0)
    assert allowed_l0 is True
    assert info_l0["headroom_eq"] == 3
    assert info_l0["level_estimate_eq"] == 3
    assert info_l0["reason"] == "ok"

    allowed_l1, info_l1 = orch.c1_recovery_admission_decision(1)
    assert allowed_l1 is False
    assert info_l1["level_estimate_eq"] == 6
    assert info_l1["reason"] == "insufficient_c2_headroom"


def test_c1_recovery_admission_clamps_level_to_estimates_length() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c2._capacity_debug_snapshot = {
        "density": {"piece_count_estimate": 0},
    }
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    orch.update_c1_recovery_admission(level_estimates_eq=[2, 4])
    # Level 7 clamps to last entry (4). Headroom is 14 (default capacity).
    allowed, info = orch.c1_recovery_admission_decision(7)
    assert allowed is True
    assert info["level_estimate_eq"] == 4


def test_c1_recovery_admission_disable_short_circuits_to_allowed() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c2._capacity_debug_snapshot = {
        "density": {"piece_count_estimate": 100},  # well over capacity
    }
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    orch.update_c1_recovery_admission(enabled=False)
    allowed, info = orch.c1_recovery_admission_decision(4)
    assert allowed is True
    assert info["enabled"] is False
    assert info["reason"] == "admission_disabled"


def test_c1_recovery_admission_rejects_decreasing_estimates() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    orch = _make_orchestrator(
        [c1, c2], {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    )
    with pytest.raises(ValueError, match="non-decreasing"):
        orch.update_c1_recovery_admission(level_estimates_eq=[10, 5, 3])


def test_c1_c4_backpressure_rejects_resume_at_or_above_high() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c4 = _FakeRuntime("c4")
    orch = _make_orchestrator(
        [c1, c2, c3, c4],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
            ("c3", "c4"): CapacitySlot("c3_to_c4", 1),
        },
    )
    with pytest.raises(ValueError, match="raw_resume"):
        orch.update_c1_c4_backpressure(raw_high=5, raw_resume=5)
    with pytest.raises(ValueError, match="dossier_resume"):
        orch.update_c1_c4_backpressure(dossier_high=2, dossier_resume=3)


def test_c1_capacity_obeys_c2_vision_density_controller() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c2._available_slots = 2
    c3._available_slots = 1
    c2._capacity_debug_snapshot = {
        "reason": "ok",
            "density": {
                "piece_count_estimate": 2,
                "clump_score": 0.8,
                "exit_queue_length": 0,
            },
    }
    orch = _make_orchestrator(
        [c1, c2, c3],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        },
    )

    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 0
    c1_capacity = orch.status_snapshot()["capacity_debug"]["c1"]
    assert c1_capacity["downstream"] == "c2"
    assert c1_capacity["reason"] == "vision_density_clump"
    assert c1_capacity["controller"]["name"] == "c1_c2_vision_burst"


def test_c1_capacity_allows_low_clean_c2_buffer() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c2._available_slots = 2
    c3._available_slots = 1
    c2._capacity_debug_snapshot = {
        "reason": "ok",
            "density": {
                "piece_count_estimate": 0,
                "clump_score": 0.0,
                "exit_queue_length": 0,
            },
    }
    orch = _make_orchestrator(
        [c1, c2, c3],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        },
    )

    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 2


def test_c1_capacity_holds_single_visible_c2_piece_by_default() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c2._available_slots = 2
    c3._available_slots = 1
    c2._capacity_debug_snapshot = {
        "reason": "ok",
        "density": {
            "piece_count_estimate": 1,
            "clump_score": 0.0,
            "exit_queue_length": 0,
        },
    }
    orch = _make_orchestrator(
        [c1, c2, c3],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        },
    )

    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 0
    assert (
        orch.status_snapshot()["capacity_debug"]["c1"]["reason"]
        == "vision_target_band"
    )


def test_c1_capacity_holds_middle_c2_target_band() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c2._available_slots = 2
    c3._available_slots = 1
    c2._capacity_debug_snapshot = {
        "reason": "ok",
        "density": {
            "piece_count_estimate": 2,
            "clump_score": 0.0,
            "exit_queue_length": 0,
        },
    }
    orch = _make_orchestrator(
        [c1, c2, c3],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        },
    )

    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 0
    assert (
        orch.status_snapshot()["capacity_debug"]["c1"]["reason"]
        == "vision_target_band"
    )


def test_c1_vision_controller_can_be_tuned_live() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c3 = _FakeRuntime("c3")
    c2._available_slots = 2
    c3._available_slots = 1
    c2._capacity_debug_snapshot = {
        "reason": "ok",
        "density": {
            "piece_count_estimate": 1,
            "clump_score": 0.0,
            "exit_queue_length": 0,
        },
    }
    orch = _make_orchestrator(
        [c1, c2, c3],
        {
            ("c1", "c2"): CapacitySlot("c1_to_c2", 1),
            ("c2", "c3"): CapacitySlot("c2_to_c3", 1),
        },
    )
    orch.update_c1_c2_vision_controller(target_low=2, target_high=4)

    orch.tick_once(now_mono=0.0)

    assert c1.ticks[-1].capacity_downstream == 2
    assert orch.c1_c2_vision_controller_snapshot()["target_low"] == 2


def test_perception_source_forwarded_to_feed_runtime() -> None:
    c2 = _FakeRuntime("c2", feed_id="c2_feed")
    slots: dict = {}
    batch = TrackBatch("c2_feed", 1, 0.0, tuple(), tuple())
    orch = _make_orchestrator([c2], slots, sources={"c2_feed": _FakeTrackSource(batch)})
    orch.tick_once(now_mono=0.0)
    assert c2.ticks[-1].tracks is batch


def test_tick_swallows_runtime_exceptions() -> None:
    bad = _FakeRuntime("bad", raises=True)
    good = _FakeRuntime("good")
    slots = {("bad", "good"): CapacitySlot("bad_to_good", 1)}
    orch = _make_orchestrator([bad, good], slots)
    # Must not raise — exception is logged, other runtimes still tick.
    orch.tick_once(now_mono=0.0)
    assert good.ticks  # good still ticked despite bad raising


def test_health_aggregates_per_runtime() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    slots = {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    orch = _make_orchestrator([c1, c2], slots)
    snap = orch.health()
    assert set(snap.keys()) == {"c1", "c2"}
    for entry in snap.values():
        assert entry["state"] == "idle"
        assert entry["last_tick_ms"] == 0.5


def test_status_snapshot_surfaces_runtime_and_slot_debug() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c1._debug_snapshot = {"piece_count": 2, "downstream_taken": 1}
    slot = CapacitySlot("c1_to_c2", 2)
    slot.try_claim()
    orch = _make_orchestrator([c1, c2], {("c1", "c2"): slot})

    snapshot = orch.status_snapshot()

    assert snapshot["runtime_health"]["c1"]["state"] == "idle"
    assert snapshot["runtime_debug"]["c1"] == {"piece_count": 2, "downstream_taken": 1}
    assert snapshot["slot_debug"]["c1_to_c2"] == {
        "capacity": 2,
        "taken": 1,
        "available": 1,
    }


def test_flow_gate_accounting_refines_downstream_capacity_reason() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    c1._health = RuntimeHealth(
        state="idle",
        blocked_reason="downstream_full",
        last_tick_ms=0.5,
    )
    c2._available_slots = 0
    c2._capacity_debug_snapshot = {"reason": "piece_cap"}
    orch = _make_orchestrator(
        [c1, c2],
        {("c1", "c2"): CapacitySlot("c1_to_c2", 1)},
    )

    orch.tick_once(now_mono=10.0)
    orch.tick_once(now_mono=10.5)
    flow = orch.status_snapshot()["flow_gate_accounting"]

    assert flow["current"]["c1"] == "BLOCKED_C2_DENSITY_CAP"
    assert flow["totals_s"]["c1:BLOCKED_C2_DENSITY_CAP"] == pytest.approx(0.5)


def test_start_stop_lifecycle_propagates_to_runtimes() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    slots = {("c1", "c2"): CapacitySlot("c1_to_c2", 1)}
    orch = _make_orchestrator([c1, c2], slots)
    orch.start()
    try:
        # Give the tick thread a moment to run at least once.
        time.sleep(0.05)
    finally:
        orch.stop()
    assert c1.started and c2.started
    assert c1.stopped and c2.stopped
    assert orch.tick_count() >= 1


def test_start_paused_blocks_ticks_until_resume() -> None:
    c1 = _FakeRuntime("c1")
    slots: dict = {}
    orch = _make_orchestrator([c1], slots)
    orch.start(paused=True)
    try:
        time.sleep(0.03)
        assert orch.tick_count() == 0
        orch.resume()
        time.sleep(0.03)
        assert orch.tick_count() >= 1
        paused_at = orch.tick_count()
        orch.pause()
        time.sleep(0.03)
        assert orch.tick_count() == paused_at
    finally:
        orch.stop()


def test_tick_count_increments() -> None:
    c1 = _FakeRuntime("c1")
    slots: dict = {}
    orch = _make_orchestrator([c1], slots)
    assert orch.tick_count() == 0
    orch.tick_once(now_mono=0.0)
    orch.tick_once(now_mono=0.01)
    assert orch.tick_count() == 2


def test_orchestrator_rejects_invalid_tick_period() -> None:
    import pytest

    with pytest.raises(ValueError):
        Orchestrator(runtimes=[], slots={}, tick_period_s=0.0)


def test_step_advances_tick_count_only_when_paused() -> None:
    c1 = _FakeRuntime("c1")
    orch = _make_orchestrator([c1], {})
    orch.start(paused=True)
    try:
        assert orch.is_paused()
        result = orch.step(3)
        assert result["ticks_executed"] == 3
        assert result["tick_count"] == 3
        assert orch.tick_count() == 3
        assert len(c1.ticks) == 3
    finally:
        orch.stop()


def test_step_rejected_while_running() -> None:
    import pytest

    c1 = _FakeRuntime("c1")
    orch = _make_orchestrator([c1], {})
    orch.start(paused=False)
    try:
        with pytest.raises(RuntimeError):
            orch.step(1)
    finally:
        orch.stop()


def test_step_validates_count() -> None:
    import pytest

    c1 = _FakeRuntime("c1")
    orch = _make_orchestrator([c1], {})
    orch.start(paused=True)
    try:
        with pytest.raises(ValueError):
            orch.step(0)
        with pytest.raises(ValueError):
            orch.step(101)
    finally:
        orch.stop()


def test_inspect_snapshot_includes_per_runtime_and_slots() -> None:
    c1 = _FakeRuntime("c1")
    c2 = _FakeRuntime("c2")
    slots = {("c1", "c2"): CapacitySlot("c1_to_c2", 2)}
    orch = _make_orchestrator([c1, c2], slots)
    snap = orch.inspect_snapshot()
    assert snap["paused"] is False
    assert snap["tick_count"] == 0
    assert "slot_inspect" in snap
    assert "c1_to_c2" in snap["slot_inspect"]
    assert snap["slot_inspect"]["c1_to_c2"]["capacity"] == 2
    assert snap["slot_inspect"]["c1_to_c2"]["claims"] == []
    # Fake runtimes don't implement inspect_snapshot, so runtime_inspect
    # is allowed to be empty — the orchestrator must not crash on missing
    # methods.
    assert isinstance(snap.get("runtime_inspect"), dict)
