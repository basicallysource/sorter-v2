from __future__ import annotations

import math
from typing import Callable

from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.events.bus import InProcessEventBus
from rt.events.topics import C3_HANDOFF_TRIGGER
from rt.runtimes.c3 import RuntimeC3
from rt.services.track_transit import TrackTransitRegistry


class _InlineHw:
    def __init__(self) -> None:
        self._busy = False
        self.commands: list[str] = []

    def start(self) -> None:  # pragma: no cover
        return None

    def stop(self, timeout_s: float = 2.0) -> None:  # pragma: no cover
        return None

    def enqueue(self, command: Callable[[], None], *, priority: int = 0, label: str = "hw_cmd") -> bool:
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


class _DenyLandingLease:
    def request_lease(self, **_kwargs) -> str | None:
        return None

    def consume_lease(self, _lease_id: str) -> None:
        return None


class _GrantLandingLease:
    def __init__(self, lease_id: str = "lease-ok") -> None:
        self.lease_id = lease_id
        self.requests: list[dict[str, object]] = []
        self.consumed: list[str] = []

    def request_lease(self, **kwargs) -> str | None:
        self.requests.append(dict(kwargs))
        return self.lease_id

    def consume_lease(self, lease_id: str) -> None:
        self.consumed.append(str(lease_id))


def _track(
    track_id: int = 1,
    global_id: int | None = 1,
    angle_rad: float | None = 0.0,
    confirmed: bool = True,
    last_seen_ts: float = 0.0,
    hit_count: int = 5,
    appearance_embedding: tuple[float, ...] | None = None,
    piece_uuid: str | None = None,
) -> Track:
    return Track(
        track_id=track_id,
        global_id=global_id,
        piece_uuid=piece_uuid,
        bbox_xyxy=(0, 0, 10, 10),
        score=0.9,
        confirmed_real=confirmed,
        angle_rad=angle_rad,
        radius_px=50.0,
        hit_count=hit_count,
        first_seen_ts=0.0,
        last_seen_ts=last_seen_ts,
        appearance_embedding=appearance_embedding,
    )


def _batch(*tracks: Track, timestamp: float = 0.0) -> TrackBatch:
    return TrackBatch(
        feed_id="c3_feed",
        frame_seq=1,
        timestamp=timestamp,
        tracks=tuple(tracks),
        lost_track_ids=tuple(),
    )


def _make(**kwargs) -> tuple[RuntimeC3, CapacitySlot, CapacitySlot, list[str]]:
    upstream = CapacitySlot("c2_to_c3", capacity=kwargs.get("upstream_cap", 1))
    downstream = CapacitySlot("c3_to_c4", capacity=kwargs.get("downstream_cap", 1))
    log: list[str] = []

    pulse_success = kwargs.get("pulse_success", True)

    def pulse(mode: RuntimeC3.PulseMode, pulse_ms: float) -> bool:
        log.append(f"{mode.value}:{pulse_ms:.0f}")
        return pulse_success

    def wiggle() -> bool:
        log.append("wiggle")
        return True

    def sample_transport(
        deg: float,
        max_speed: int | None = None,
        acceleration: int | None = None,
    ) -> bool:
        log.append(f"sample:{deg:.1f}")
        return pulse_success

    rt = RuntimeC3(
        upstream_slot=upstream,
        downstream_slot=downstream,
        pulse_command=pulse,
        wiggle_command=wiggle,
        sample_transport_command=sample_transport,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        event_bus=kwargs.get("event_bus"),
        pulse_cooldown_s=0.0,
        wiggle_stall_ms=200,
        wiggle_cooldown_ms=500,
        holdover_ms=kwargs.get("holdover_ms", 2000),
        max_piece_count=kwargs.get("max_piece_count", 3),
        track_transit=kwargs.get("track_transit"),
        exit_handoff_min_interval_s=kwargs.get("exit_handoff_min_interval_s", 0.85),
    )
    return rt, upstream, downstream, log


def test_c3_precise_pulse_when_track_at_exit() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("precise:")
    assert down.available() == 0


def test_c3_reports_lease_denial_separately_from_capacity() -> None:
    rt, _up, down, log = _make()
    rt.set_landing_lease_port(_DenyLandingLease())
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)

    rt.tick(inbox, now_mono=0.0)

    assert log == []
    assert down.available() == 1
    assert rt.health().blocked_reason == "lease_denied"


def test_c3_sector_mode_requires_landing_lease_port() -> None:
    rt, _up, down, log = _make()
    rt.set_downstream_landing_lease_required(True)
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)

    rt.tick(inbox, now_mono=0.0)

    assert log == []
    assert down.available() == 1
    assert rt.health().blocked_reason == "landing_lease_port_missing"
    snap = rt.debug_snapshot()
    assert snap["downstream_landing_lease_required"] is True
    assert snap["downstream_landing_lease_port_wired"] is False


def test_c3_sector_mode_requires_track_id_for_landing_lease() -> None:
    rt, _up, down, log = _make()
    rt.set_landing_lease_port(_GrantLandingLease())
    rt.set_downstream_landing_lease_required(True)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=None, angle_rad=0.0)),
        capacity_downstream=1,
    )

    rt.tick(inbox, now_mono=0.0)

    assert log == []
    assert down.available() == 1
    assert rt.health().blocked_reason == "landing_lease_track_id_missing"


def test_c3_handoff_trigger_carries_landing_lease_id() -> None:
    bus = InProcessEventBus()
    events = []
    bus.subscribe(C3_HANDOFF_TRIGGER, events.append)
    rt, _up, down, log = _make(event_bus=bus)
    port = _GrantLandingLease("lease-123")
    rt.set_landing_lease_port(port)
    rt.set_downstream_landing_lease_required(True)

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=17, angle_rad=0.0)), capacity_downstream=1),
        now_mono=10.0,
    )
    bus.drain()

    assert log and log[0].startswith("precise:")
    assert down.available() == 0
    assert port.requests and port.consumed == []
    assert len(events) == 1
    assert events[0].payload["landing_lease_id"] == "lease-123"
    assert events[0].payload["track_global_id"] == 17
    assert events[0].payload["handoff_quality"] == "single_confident"
    assert events[0].payload["handoff_multi_risk"] is False


def test_c3_handoff_trigger_marks_suspect_multi_when_second_track_near_exit() -> None:
    bus = InProcessEventBus()
    events = []
    bus.subscribe(C3_HANDOFF_TRIGGER, events.append)
    rt, _up, _down, log = _make(event_bus=bus, max_piece_count=5)
    port = _GrantLandingLease("lease-456")
    rt.set_landing_lease_port(port)
    rt.set_downstream_landing_lease_required(True)

    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(track_id=1, global_id=17, angle_rad=0.0),
                _track(track_id=2, global_id=18, angle_rad=math.radians(12.0)),
            ),
            capacity_downstream=1,
        ),
        now_mono=10.0,
    )
    bus.drain()

    assert log and log[0].startswith("precise:")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["landing_lease_id"] == "lease-456"
    assert payload["handoff_quality"] == "suspect_multi"
    assert payload["handoff_multi_risk"] is True
    assert payload["c3_exit_actionable_count"] == 2
    assert payload["c3_nearby_track_count"] == 1
    assert payload["candidate_global_ids"] == [17, 18]
    assert port.requests[0]["handoff_quality"] == "suspect_multi"
    assert port.requests[0]["handoff_multi_risk"] is True


def test_c3_ignores_stationary_round_part_in_upstream_landing_arc() -> None:
    rt, _up, _down, _log = _make()
    landing_track = _track(global_id=44, angle_rad=math.pi, hit_count=12)

    for ts in (0.0, 1.0, 2.0, 3.0, 4.1):
        rt.tick(
            RuntimeInbox(tracks=_batch(landing_track), capacity_downstream=1),
            now_mono=ts,
        )

    debug = rt.debug_snapshot()
    assert debug["visible_track_count"] == 1
    assert debug["active_visible_track_count"] == 0
    assert debug["upstream_bad_actor_suppression"]["ignored_count"] == 1
    assert rt.purge_port().counts().piece_count == 0

    lease = rt.landing_lease_port().request_lease(
        predicted_arrival_in_s=0.5,
        min_spacing_deg=60.0,
        now_mono=4.2,
        track_global_id=101,
    )
    assert lease is not None


def test_c3_reactivates_ignored_landing_part_after_clear_motion() -> None:
    rt, _up, _down, _log = _make()
    landing_track = _track(global_id=44, angle_rad=math.pi, hit_count=12)

    for ts in (0.0, 1.0, 2.0, 3.0, 4.1):
        rt.tick(
            RuntimeInbox(tracks=_batch(landing_track), capacity_downstream=1),
            now_mono=ts,
        )
    assert rt.debug_snapshot()["upstream_bad_actor_suppression"]["ignored_count"] == 1

    moved_track = _track(
        global_id=44,
        angle_rad=math.pi - math.radians(25.0),
        hit_count=14,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(moved_track), capacity_downstream=1),
        now_mono=5.0,
    )

    debug = rt.debug_snapshot()
    assert debug["upstream_bad_actor_suppression"]["ignored_count"] == 0
    assert debug["active_visible_track_count"] == 1
    assert rt.landing_lease_port().request_lease(
        predicted_arrival_in_s=0.5,
        min_spacing_deg=60.0,
        now_mono=5.1,
        track_global_id=101,
    ) is None


def test_c3_ignores_stationary_transport_bad_actor_after_motion_attempts() -> None:
    rt, _up, _down, log = _make()
    stuck = _track(global_id=55, angle_rad=math.radians(-25.0), hit_count=12)

    for ts in (0.0, 1.0, 2.0, 4.0, 7.2):
        rt.tick(
            RuntimeInbox(tracks=_batch(stuck), capacity_downstream=1),
            now_mono=ts,
        )

    debug = rt.debug_snapshot()
    assert log
    assert debug["visible_track_count"] == 1
    assert debug["active_visible_track_count"] == 0
    assert debug["transport_bad_actor_suppression"]["ignored_count"] == 1
    assert rt.purge_port().counts().piece_count == 0
    assert rt.available_slots() == 1


def test_c3_transport_bad_actor_cluster_blocks_upstream_capacity() -> None:
    rt, _up, _down, _log = _make()
    rt._ignored_transport_bad_actor_keys.update({11, 12, 13, 14, 15, 16, 17})

    capacity = rt.capacity_debug_snapshot()

    assert rt.available_slots() == 1
    assert capacity["available"] == 1
    assert capacity["reason"] == "ok"
    assert capacity["transport_bad_actor_ignored_count"] == 7
    assert capacity["transport_bad_actor_capacity_block_count"] == 8

    rt._ignored_transport_bad_actor_keys.add(18)

    capacity = rt.capacity_debug_snapshot()

    assert rt.available_slots() == 0
    assert capacity["available"] == 0
    assert capacity["reason"] == "transport_bad_actor_cluster"
    assert capacity["transport_bad_actor_ignored_count"] == 8
    assert capacity["transport_bad_actor_capacity_block_count"] == 8


def test_c3_transport_bad_actor_reactivates_after_clear_motion() -> None:
    rt, _up, _down, _log = _make()
    stuck = _track(global_id=55, angle_rad=math.radians(-25.0), hit_count=12)

    for ts in (0.0, 1.0, 2.0, 4.0, 7.2):
        rt.tick(
            RuntimeInbox(tracks=_batch(stuck), capacity_downstream=1),
            now_mono=ts,
        )
    assert rt.debug_snapshot()["transport_bad_actor_suppression"]["ignored_count"] == 1

    moved = _track(global_id=55, angle_rad=math.radians(-55.0), hit_count=13)
    rt.tick(
        RuntimeInbox(tracks=_batch(moved), capacity_downstream=1),
        now_mono=8.0,
    )

    debug = rt.debug_snapshot()
    assert debug["transport_bad_actor_suppression"]["ignored_count"] == 0
    assert debug["active_visible_track_count"] == 1


def test_c3_does_not_transport_ignore_piece_waiting_for_downstream_capacity() -> None:
    rt, _up, _down, log = _make()
    waiting = _track(global_id=56, angle_rad=0.0, hit_count=12)

    for ts in (0.0, 1.0, 2.0, 4.0, 7.2):
        rt.tick(
            RuntimeInbox(tracks=_batch(waiting), capacity_downstream=0),
            now_mono=ts,
        )

    debug = rt.debug_snapshot()
    assert log == []
    assert debug["active_visible_track_count"] == 1
    assert debug["transport_bad_actor_suppression"]["ignored_count"] == 0


def test_c3_exit_pulse_publishes_c4_transit_candidate() -> None:
    registry = TrackTransitRegistry()
    rt, _up, _down, _log = _make(track_transit=registry)

    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=17, angle_rad=0.0)),
            capacity_downstream=1,
        ),
        now_mono=10.0,
    )

    candidates = registry.snapshot(10.0)
    assert len(candidates) == 1
    assert candidates[0]["source_runtime"] == "c3"
    assert candidates[0]["source_global_id"] == 17
    assert candidates[0]["target_runtime"] == "c4"
    assert candidates[0]["relation"] == "cross_channel"


def test_c3_exit_transit_carries_stable_piece_uuid() -> None:
    registry = TrackTransitRegistry()
    rt, _up, _down, _log = _make(track_transit=registry)

    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=17, angle_rad=0.0, piece_uuid="piece-c3")),
            capacity_downstream=1,
        ),
        now_mono=10.0,
    )

    candidates = registry.snapshot(10.0)
    assert candidates[0]["piece_uuid"] == "piece-c3"


def test_c3_exit_transit_carries_track_appearance_embedding() -> None:
    """ReID embedding must propagate C3 → transit registry so C4 can gate it."""

    registry = TrackTransitRegistry()
    rt, _up, _down, _log = _make(track_transit=registry)

    embedding = (1.0, 0.0, 0.0, 0.0)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(global_id=18, angle_rad=0.0, appearance_embedding=embedding)
            ),
            capacity_downstream=1,
        ),
        now_mono=11.0,
    )
    # Registry stashes the embedding on the candidate — poke past the public
    # snapshot() to assert it directly.
    stored = next(iter(registry._candidates.values()))  # type: ignore[attr-defined]
    assert stored.source_embedding == embedding


def test_c3_precise_pulse_for_stable_unconfirmed_exit_track() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=0.0, confirmed=False, hit_count=2)),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("precise:")
    assert down.available() == 0


def test_c3_normal_pulse_off_exit_never_commits() -> None:
    rt, _up, down, log = _make()
    # Track far from exit — outside both commit and approach arcs.
    # C3 advances the ring at NORMAL speed and must not claim the
    # downstream slot until the piece is inside the commit arc.
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=math.pi)),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("normal:")
    assert down.available() == 1


def test_c3_loaded_ring_uses_precise_pulse_off_exit() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(
        tracks=_batch(
            _track(track_id=1, global_id=1, angle_rad=math.pi),
            _track(track_id=2, global_id=2, angle_rad=math.radians(120.0)),
        ),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("precise:")
    assert down.available() == 1


def test_c3_records_dropzone_arrival_burst_diagnostics() -> None:
    rt, _up, _down, _log = _make(max_piece_count=5)

    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(track_id=99, global_id=99, angle_rad=math.radians(120.0)),
            ),
            capacity_downstream=0,
        ),
        now_mono=9.0,
    )

    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(track_id=1, global_id=1, angle_rad=math.radians(120.0)),
                _track(track_id=2, global_id=2, angle_rad=math.radians(180.0)),
                _track(track_id=3, global_id=3, angle_rad=math.radians(-120.0)),
            ),
            capacity_downstream=0,
        ),
        now_mono=10.0,
    )

    diag = rt.debug_snapshot()["handoff_burst_diagnostics"]
    assert diag["anomalies"]
    anomaly = diag["anomalies"][-1]
    assert anomaly["kind"] == "dropzone_arrival_burst"
    assert anomaly["runtime_id"] == "c3"
    assert anomaly["arrival_count_window"] == 3
    assert anomaly["context"]["piece_count"] == 3


def test_c3_approach_pulse_is_precise_without_committing() -> None:
    rt, _up, down, log = _make()
    # Track inside the approach arc (45°) but outside the commit arc
    # (20°) — small precise pulse, no downstream claim.
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=math.radians(35.0))),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("precise:")
    assert down.available() == 1


def test_c3_holdover_promotes_normal_to_precise() -> None:
    rt, _up, down, log = _make(holdover_ms=2000, downstream_cap=2)
    # Precise pulse first — arms holdover.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=2),
        now_mono=0.0,
    )
    assert rt.in_holdover(0.0)
    # Next tick with track off-exit should still fire precise due to holdover.
    log.clear()
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(angle_rad=math.pi)),
            capacity_downstream=down.available(),
        ),
        now_mono=0.5,
    )
    assert log and log[0].startswith("precise:")


def test_c3_holdover_expires_after_window() -> None:
    rt, _up, _down, log = _make(holdover_ms=200)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.in_holdover(0.1)
    assert not rt.in_holdover(1.0)
    log.clear()
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=math.pi)), capacity_downstream=1),
        now_mono=1.0,
    )
    # Holdover has expired and the track is outside both the commit and
    # approach arcs — C3 reverts to NORMAL transport pulses.
    assert log and log[0].startswith("normal:")


def test_c3_sample_transport_scales_to_small_continuous_steps() -> None:
    rt, _up, _down, log = _make()
    port = rt.sample_transport_port()

    port.configure_sample_transport(target_rpm=3.2)

    assert port.nominal_degrees_per_step() == 15.0
    assert port.step(1.0) is True
    assert log == ["sample:15.0"]


def test_c3_does_not_wiggle_when_downstream_is_closed() -> None:
    rt, _up, _down, log = _make()
    stuck = _batch(_track(angle_rad=0.0))
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.5)
    assert log == []
    assert rt.health().blocked_reason == "downstream_full"


def test_c3_precise_pulse_rolled_back_on_hw_failure() -> None:
    rt, _up, down, log = _make(pulse_success=False)
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert down.available() == 1


def test_c3_pending_handoff_waits_without_repeat_exit_pulse() -> None:
    rt, _up, down, log = _make(downstream_cap=4)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=23, angle_rad=0.0)),
        capacity_downstream=4,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(inbox, now_mono=0.4)

    assert down.taken(now_mono=0.4) == 1
    assert len([entry for entry in log if entry.startswith("precise:")]) == 1
    assert rt.debug_snapshot()["pending_downstream_claims"] == 1
    assert rt.health().state == "handoff_wait"
    assert rt.health().blocked_reason == "awaiting_downstream_arrival"


def test_c3_pending_handoff_retries_same_track_after_spacing_without_new_claim() -> None:
    rt, _up, down, log = _make(downstream_cap=4)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=23, angle_rad=0.0)),
        capacity_downstream=4,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(inbox, now_mono=1.0)

    assert down.taken(now_mono=1.0) == 1
    assert len([entry for entry in log if entry.startswith("precise:")]) == 2
    assert rt.debug_snapshot()["pending_downstream_claims"] == 1
    assert rt.health().state == "pulsing_precise"


def test_c3_pending_handoff_escalates_to_double_nudge_without_new_claim() -> None:
    rt, _up, down, log = _make(downstream_cap=4)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=23, angle_rad=0.0)),
        capacity_downstream=4,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(inbox, now_mono=1.0)
    rt.tick(inbox, now_mono=2.0)

    assert down.taken(now_mono=2.0) == 1
    assert len([entry for entry in log if entry.startswith("precise:")]) == 4
    snap = rt.debug_snapshot()
    assert snap["pending_downstream_claims"] == 1
    assert snap["pending_downstream_retry_max"] == 2
    assert rt.health().state == "pulsing_precise"


def test_c3_exit_spacing_blocks_nearby_next_piece() -> None:
    rt, _up, down, log = _make(
        downstream_cap=4,
        exit_handoff_min_interval_s=0.85,
    )

    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=23, angle_rad=0.0)),
            capacity_downstream=4,
        ),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=24, angle_rad=math.radians(15.0))),
            capacity_downstream=down.available(now_mono=0.2),
        ),
        now_mono=0.2,
    )

    assert len([entry for entry in log if entry.startswith("precise:")]) == 1
    assert down.taken(now_mono=0.2) == 1
    assert rt.health().state == "handoff_spacing"
    assert rt.health().blocked_reason == "exit_spacing"


def test_c3_allows_exit_retry_after_claim_hold_expires() -> None:
    rt, _up, down, log = _make(downstream_cap=4)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=23, angle_rad=0.0)),
        capacity_downstream=4,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(inbox, now_mono=4.0)

    assert down.taken(now_mono=4.0) == 1
    assert len([entry for entry in log if entry.startswith("precise:")]) == 2


def test_c3_on_piece_delivered_releases_upstream() -> None:
    rt, up, _down, _log = _make()
    assert up.try_claim() is True
    rt.on_piece_delivered("uuid", now_mono=0.0)
    assert up.available() == 1


def test_c3_new_confirmed_piece_releases_upstream_on_arrival() -> None:
    rt, up, _down, _log = _make(upstream_cap=1)
    assert up.try_claim() is True
    # Piece arrives off-exit; the upstream release fires once it is
    # confirmed real by the tracker.
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=7, angle_rad=math.pi, confirmed=True)),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    assert up.available() == 1


def test_c3_pending_piece_does_not_release_or_fill_capacity() -> None:
    rt, up, _down, _log = _make(upstream_cap=1)
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(
                    global_id=7,
                    angle_rad=math.pi,
                    confirmed=False,
                    hit_count=1,
                )
            ),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    snap = rt.debug_snapshot()
    assert up.available() == 0
    assert rt.available_slots() == 1
    assert snap["piece_count"] == 0
    assert snap["admission_piece_count"] == 0
    assert snap["visible_track_count"] == 1
    assert snap["pending_track_count"] == 1


def test_c3_stable_pending_tracks_reserve_ring_capacity() -> None:
    rt, _up, _down, _log = _make(max_piece_count=1)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(
                    global_id=7,
                    angle_rad=math.pi,
                    confirmed=False,
                    hit_count=3,
                )
            ),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    snap = rt.debug_snapshot()
    assert rt.available_slots() == 0
    assert snap["piece_count"] == 1
    assert snap["admission_piece_count"] == 1
    assert snap["pending_track_count"] == 0


def test_c3_available_slots_blocks_when_ring_full() -> None:
    """The C3 cap is the upstream brake — without it C2 keeps pushing
    pieces into a C3 ring the tracker can no longer separate. Live
    overflow on 2026-04-25 confirmed why this gate must stay in place."""
    rt, _up, _down, _log = _make(max_piece_count=1)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(angle_rad=math.pi / 3, confirmed=True)),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    assert rt.available_slots() == 0


def test_c3_downstream_full_blocks_precise_pulse() -> None:
    rt, _up, _down, log = _make()
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=0),
        now_mono=0.0,
    )
    # No pulse dispatched because capacity_downstream == 0.
    assert not any(entry.startswith("precise:") for entry in log)


def test_c3_downstream_full_still_allows_non_commit_approach_pulse() -> None:
    rt, _up, down, log = _make()

    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(angle_rad=math.radians(35.0))),
            capacity_downstream=0,
        ),
        now_mono=0.0,
    )

    assert log and log[0].startswith("precise:")
    assert down.available() == 1


def test_c3_downstream_full_still_allows_non_commit_normal_pulse() -> None:
    rt, _up, down, log = _make()

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=math.pi)), capacity_downstream=0),
        now_mono=0.0,
    )

    assert log and log[0].startswith("normal:")
    assert down.available() == 1


def test_c3_ignores_stale_coasted_track() -> None:
    rt, _up, _down, log = _make()
    stale = _track(angle_rad=math.pi, last_seen_ts=0.1)
    rt.tick(
        RuntimeInbox(tracks=_batch(stale, timestamp=1.0), capacity_downstream=1),
        now_mono=1.0,
    )
    assert log == []
    assert rt.available_slots() == 1


# ----------------------------------------------------------------------
# PurgePort binding


def test_c3_purge_port_arm_pulses_despite_full_downstream() -> None:
    rt, _up, _down, log = _make()
    port = rt.purge_port()
    assert port.key == "c3"

    port.arm()
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=math.pi)), capacity_downstream=0),
        now_mono=0.0,
    )

    assert log and log[0].startswith("precise:")
    assert rt.available_slots() == 0


def test_c3_purge_port_counts_mirror_ring() -> None:
    rt, _up, _down, _log = _make()
    port = rt.purge_port()
    port.arm()

    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(global_id=1, angle_rad=0.5),
                _track(global_id=2, angle_rad=1.0),
                _track(global_id=3, angle_rad=2.0),
            ),
            capacity_downstream=0,
        ),
        now_mono=0.0,
    )
    counts = port.counts()

    assert counts.piece_count == 3
    assert counts.owned_count == 0
    assert counts.pending_detections == 0


def test_c3_purge_port_disarm_clears_flag_and_bookkeeping() -> None:
    rt, _up, _down, _log = _make()
    port = rt.purge_port()
    port.arm()
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=1, angle_rad=0.0)), capacity_downstream=0),
        now_mono=0.0,
    )
    assert rt._purge_mode is True

    port.disarm()

    assert rt._purge_mode is False
    assert rt._piece_count == 0
    assert len(rt._book.seen_global_ids) == 0
