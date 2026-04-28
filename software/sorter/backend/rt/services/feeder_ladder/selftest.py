"""Software-only ladder selftest for the C1->C2->C3 feeder chain.

The test uses inline hardware fakes and synthetic tracks. It deliberately
does not touch cameras, steppers, USB, or the live orchestrator; the goal is
to prove the feeder state machines and lease handoffs before live ladder
tests start.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from rt.contracts.events import Event
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.bus import InProcessEventBus
from rt.events.topics import C3_HANDOFF_TRIGGER
from rt.runtimes.c1 import RuntimeC1
from rt.runtimes.c2 import RuntimeC2
from rt.runtimes.c3 import RuntimeC3


@dataclass(slots=True)
class _Check:
    name: str
    ok: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _ScenarioResult:
    name: str
    checks: list[_Check] = field(default_factory=list)

    def check(self, name: str, condition: bool, **details: Any) -> None:
        self.checks.append(_Check(name=name, ok=bool(condition), details=details))

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "checks": [asdict(check) for check in self.checks],
        }


class _InlineHw:
    def __init__(self) -> None:
        self._busy = False
        self.commands: list[str] = []

    def start(self) -> None:  # pragma: no cover - interface parity
        return None

    def stop(self, timeout_s: float = 2.0) -> None:  # pragma: no cover
        return None

    def enqueue(
        self,
        command: Callable[[], None],
        *,
        priority: int = 0,
        label: str = "hw_cmd",
    ) -> bool:
        self.commands.append(label)
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


class _C4LeasePort:
    def __init__(self, *, grant: bool = True, lease_id: str = "c4-lease") -> None:
        self.grant = bool(grant)
        self.lease_id = str(lease_id)
        self.requests: list[dict[str, Any]] = []
        self.consumed: list[str] = []

    def request_lease(self, **kwargs: Any) -> str | None:
        self.requests.append(dict(kwargs))
        return self.lease_id if self.grant else None

    def consume_lease(self, lease_id: str) -> None:
        self.consumed.append(str(lease_id))


class _DenyLeasePort:
    def request_lease(self, **_kwargs: Any) -> str | None:
        return None

    def consume_lease(self, _lease_id: str) -> None:
        return None


def run_feeder_ladder_selftest() -> dict[str, Any]:
    scenarios = [
        _scenario_happy_path(),
        _scenario_c2_landing_lease_denied(),
        _scenario_c3_c4_landing_lease_denied(),
        _scenario_c3_suspect_multi_payload(),
        _scenario_stale_tracks_do_not_eject(),
        _scenario_c1_recovery_admission_denied(),
    ]
    ok = all(scenario.ok for scenario in scenarios)
    return {
        "ok": bool(ok),
        "source": "feeder-ladder-selftest",
        "scenario_count": len(scenarios),
        "scenarios": [scenario.as_dict() for scenario in scenarios],
    }


def _scenario_happy_path() -> _ScenarioResult:
    result = _ScenarioResult("happy_path_c1_to_c3_to_c4_event")
    c1, c2, c3, slots, logs, bus, events = _make_chain()

    c1.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    c2.tick(
        RuntimeInbox(
            tracks=_batch("c2_feed", _track(1, 101, 0.0)),
            capacity_downstream=c3.available_slots(),
        ),
        now_mono=0.1,
    )
    c3.tick(
        RuntimeInbox(
            tracks=_batch("c3_feed", _track(2, 201, 0.0, piece_uuid="piece-201")),
            capacity_downstream=1,
        ),
        now_mono=0.2,
    )
    bus.drain()

    result.check("c1_pulsed", logs["c1"] == ["pulse"], log=list(logs["c1"]))
    result.check(
        "c2_exit_pulsed",
        bool(logs["c2"]) and logs["c2"][0].startswith("precise:"),
        log=list(logs["c2"]),
    )
    result.check(
        "c3_exit_pulsed",
        bool(logs["c3"]) and logs["c3"][0].startswith("precise:"),
        log=list(logs["c3"]),
    )
    result.check("c1_claim_released_by_c2", slots["c1_to_c2"].taken(0.2) == 0)
    result.check("c2_claim_released_by_c3", slots["c2_to_c3"].taken(0.2) == 0)
    result.check("c3_claim_created_for_c4", slots["c3_to_c4"].taken(0.2) == 1)
    result.check("c3_handoff_event", len(events) == 1)
    if events:
        payload = events[0].payload
        result.check("event_has_lease", bool(payload.get("landing_lease_id")))
        result.check(
            "event_single_confident",
            payload.get("handoff_quality") == "single_confident",
            payload=dict(payload),
        )
    return result


def _scenario_c2_landing_lease_denied() -> _ScenarioResult:
    result = _ScenarioResult("c2_landing_lease_denied_blocks_motion")
    c1_to_c2 = CapacitySlot("c1_to_c2", 1)
    c2_to_c3 = CapacitySlot("c2_to_c3", 1)
    c2_log: list[str] = []
    c2 = _make_c2(c1_to_c2, c2_to_c3, c2_log)
    c2.set_landing_lease_port(_DenyLeasePort())

    c2.tick(
        RuntimeInbox(
            tracks=_batch("c2_feed", _track(1, 101, 0.0)),
            capacity_downstream=1,
        ),
        now_mono=1.0,
    )

    result.check("no_motion", c2_log == [], log=list(c2_log))
    result.check("blocked_reason", c2.health().blocked_reason == "lease_denied")
    result.check("no_downstream_claim", c2_to_c3.taken(1.0) == 0)
    return result


def _scenario_c3_c4_landing_lease_denied() -> _ScenarioResult:
    result = _ScenarioResult("c3_c4_landing_lease_denied_blocks_event")
    bus = InProcessEventBus()
    events: list[Event] = []
    bus.subscribe(C3_HANDOFF_TRIGGER, events.append)
    c2_to_c3 = CapacitySlot("c2_to_c3", 1)
    c3_to_c4 = CapacitySlot("c3_to_c4", 1)
    c3_log: list[str] = []
    c3 = _make_c3(c2_to_c3, c3_to_c4, c3_log, event_bus=bus)
    c3.set_landing_lease_port(_C4LeasePort(grant=False))
    c3.set_downstream_landing_lease_required(True)

    c3.tick(
        RuntimeInbox(
            tracks=_batch("c3_feed", _track(1, 301, 0.0)),
            capacity_downstream=1,
        ),
        now_mono=2.0,
    )
    bus.drain()

    result.check("no_motion", c3_log == [], log=list(c3_log))
    result.check("blocked_reason", c3.health().blocked_reason == "lease_denied")
    result.check("no_event", events == [])
    result.check("no_downstream_claim", c3_to_c4.taken(2.0) == 0)
    return result


def _scenario_c3_suspect_multi_payload() -> _ScenarioResult:
    result = _ScenarioResult("c3_suspect_multi_payload")
    bus = InProcessEventBus()
    events: list[Event] = []
    bus.subscribe(C3_HANDOFF_TRIGGER, events.append)
    c2_to_c3 = CapacitySlot("c2_to_c3", 1)
    c3_to_c4 = CapacitySlot("c3_to_c4", 1)
    c3_log: list[str] = []
    c4_port = _C4LeasePort(grant=True, lease_id="lease-multi")
    c3 = _make_c3(c2_to_c3, c3_to_c4, c3_log, event_bus=bus, max_piece_count=5)
    c3.set_landing_lease_port(c4_port)
    c3.set_downstream_landing_lease_required(True)

    c3.tick(
        RuntimeInbox(
            tracks=_batch(
                "c3_feed",
                _track(1, 301, 0.0),
                _track(2, 302, math.radians(10.0)),
            ),
            capacity_downstream=1,
        ),
        now_mono=3.0,
    )
    bus.drain()

    result.check("motion_happened", bool(c3_log), log=list(c3_log))
    result.check("event_emitted", len(events) == 1)
    if events:
        payload = events[0].payload
        result.check(
            "suspect_multi",
            payload.get("handoff_quality") == "suspect_multi",
            payload=dict(payload),
        )
        result.check("multi_risk_true", payload.get("handoff_multi_risk") is True)
        result.check("candidate_ids", payload.get("candidate_global_ids") == [301, 302])
    result.check(
        "lease_request_carries_quality",
        bool(c4_port.requests)
        and c4_port.requests[0].get("handoff_quality") == "suspect_multi",
        requests=list(c4_port.requests),
    )
    return result


def _scenario_stale_tracks_do_not_eject() -> _ScenarioResult:
    result = _ScenarioResult("stale_tracks_do_not_eject")
    c1_to_c2 = CapacitySlot("c1_to_c2", 1)
    c2_to_c3 = CapacitySlot("c2_to_c3", 1)
    c2_log: list[str] = []
    c2 = _make_c2(c1_to_c2, c2_to_c3, c2_log)

    c2.tick(
        RuntimeInbox(
            tracks=_batch(
                "c2_feed",
                _track(1, 101, 0.0, last_seen_ts=9.0),
                timestamp=10.0,
            ),
            capacity_downstream=1,
        ),
        now_mono=10.0,
    )

    result.check("no_motion", c2_log == [], log=list(c2_log))
    result.check("no_downstream_claim", c2_to_c3.taken(10.0) == 0)
    result.check("idle", c2.health().blocked_reason is None)
    return result


def _scenario_c1_recovery_admission_denied() -> _ScenarioResult:
    result = _ScenarioResult("c1_recovery_admission_denied")
    c1_to_c2 = CapacitySlot("c1_to_c2", 1)
    c1_log: list[str] = []

    def pulse() -> bool:
        c1_log.append("pulse")
        return True

    def recovery(level: int) -> bool:
        c1_log.append(f"recover_l{level}")
        return True

    c1 = RuntimeC1(
        downstream_slot=c1_to_c2,
        pulse_command=pulse,
        recovery_command=recovery,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        jam_timeout_s=1.0,
        jam_min_pulses=1,
        jam_cooldown_s=0.0,
        pulse_cooldown_s=0.0,
        startup_hold_s=0.0,
        observation_hold_s=0.0,
        recovery_admission_check=lambda _level: (
            False,
            {"reason": "simulated_downstream_headroom_block"},
        ),
    )

    c1.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    c1.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=1.1)

    result.check("initial_pulse_only", c1_log == ["pulse"], log=list(c1_log))
    result.check(
        "blocked_reason",
        c1.health().blocked_reason == "recovery_headroom_insufficient",
        health=asdict(c1.health()),
    )
    result.check(
        "attempt_not_burned",
        c1.debug_snapshot()["jam"]["attempts"] == 0,
        debug=c1.debug_snapshot()["jam"],
    )
    return result


def _make_chain() -> tuple[
    RuntimeC1,
    RuntimeC2,
    RuntimeC3,
    dict[str, CapacitySlot],
    dict[str, list[str]],
    InProcessEventBus,
    list[Event],
]:
    c1_to_c2 = CapacitySlot("c1_to_c2", 1)
    c2_to_c3 = CapacitySlot("c2_to_c3", 1)
    c3_to_c4 = CapacitySlot("c3_to_c4", 1)
    logs: dict[str, list[str]] = {"c1": [], "c2": [], "c3": []}
    bus = InProcessEventBus()
    events: list[Event] = []
    bus.subscribe(C3_HANDOFF_TRIGGER, events.append)
    c1 = _make_c1(c1_to_c2, logs["c1"])
    c2 = _make_c2(
        c1_to_c2,
        c2_to_c3,
        logs["c2"],
        upstream_progress_callback=lambda now: c1.notify_downstream_progress(now),
    )
    c3 = _make_c3(c2_to_c3, c3_to_c4, logs["c3"], event_bus=bus)
    c2.set_landing_lease_port(c3.landing_lease_port())
    c3.set_landing_lease_port(_C4LeasePort(grant=True, lease_id="c4-lease-ok"))
    c3.set_downstream_landing_lease_required(True)
    return (
        c1,
        c2,
        c3,
        {"c1_to_c2": c1_to_c2, "c2_to_c3": c2_to_c3, "c3_to_c4": c3_to_c4},
        logs,
        bus,
        events,
    )


def _make_c1(slot: CapacitySlot, log: list[str]) -> RuntimeC1:
    def pulse() -> bool:
        log.append("pulse")
        return True

    def recovery(level: int) -> bool:
        log.append(f"recover_l{level}")
        return True

    return RuntimeC1(
        downstream_slot=slot,
        pulse_command=pulse,
        recovery_command=recovery,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        pulse_cooldown_s=0.0,
        startup_hold_s=0.0,
        observation_hold_s=0.0,
        unconfirmed_pulse_limit=100,
    )


def _make_c2(
    upstream_slot: CapacitySlot,
    downstream_slot: CapacitySlot,
    log: list[str],
    *,
    upstream_progress_callback: Callable[[float], None] | None = None,
) -> RuntimeC2:
    def pulse(
        mode: RuntimeC2.PulseMode,
        pulse_ms: float,
        profile_name: str | None = None,
    ) -> bool:
        log.append(f"{mode.value}:{pulse_ms:.0f}")
        return True

    def wiggle() -> bool:
        log.append("wiggle")
        return True

    return RuntimeC2(
        upstream_slot=upstream_slot,
        downstream_slot=downstream_slot,
        pulse_command=pulse,
        wiggle_command=wiggle,
        upstream_progress_callback=upstream_progress_callback,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        pulse_cooldown_s=0.0,
        exit_handoff_min_interval_s=0.0,
        max_piece_count=5,
    )


def _make_c3(
    upstream_slot: CapacitySlot,
    downstream_slot: CapacitySlot,
    log: list[str],
    *,
    event_bus: InProcessEventBus | None = None,
    max_piece_count: int = 5,
) -> RuntimeC3:
    def pulse(
        mode: RuntimeC3.PulseMode,
        pulse_ms: float,
        profile_name: str | None = None,
    ) -> bool:
        log.append(f"{mode.value}:{pulse_ms:.0f}")
        return True

    def wiggle() -> bool:
        log.append("wiggle")
        return True

    return RuntimeC3(
        upstream_slot=upstream_slot,
        downstream_slot=downstream_slot,
        pulse_command=pulse,
        wiggle_command=wiggle,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        event_bus=event_bus,
        pulse_cooldown_s=0.0,
        exit_handoff_min_interval_s=0.0,
        max_piece_count=max_piece_count,
    )


def _track(
    track_id: int,
    global_id: int,
    angle_rad: float,
    *,
    last_seen_ts: float = 0.0,
    hit_count: int = 5,
    piece_uuid: str | None = None,
) -> Track:
    return Track(
        track_id=track_id,
        global_id=global_id,
        piece_uuid=piece_uuid,
        bbox_xyxy=(0, 0, 10, 10),
        score=0.9,
        confirmed_real=True,
        angle_rad=angle_rad,
        radius_px=80.0,
        hit_count=hit_count,
        first_seen_ts=0.0,
        last_seen_ts=last_seen_ts,
    )


def _batch(
    feed_id: str,
    *tracks: Track,
    timestamp: float = 0.0,
) -> TrackBatch:
    return TrackBatch(
        feed_id=feed_id,
        frame_seq=1,
        timestamp=timestamp,
        tracks=tuple(tracks),
        lost_track_ids=tuple(),
    )


__all__ = ["run_feeder_ladder_selftest"]
