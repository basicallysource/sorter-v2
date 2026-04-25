from __future__ import annotations

import math
from typing import Callable

from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.runtimes.c2 import RuntimeC2


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


def _track(
    track_id: int = 1,
    global_id: int | None = 1,
    angle_rad: float | None = 0.0,
    confirmed: bool = True,
    last_seen_ts: float = 0.0,
    hit_count: int = 5,
) -> Track:
    return Track(
        track_id=track_id,
        global_id=global_id,
        piece_uuid=None,
        bbox_xyxy=(0, 0, 10, 10),
        score=0.9,
        confirmed_real=confirmed,
        angle_rad=angle_rad,
        radius_px=100.0,
        hit_count=hit_count,
        first_seen_ts=0.0,
        last_seen_ts=last_seen_ts,
    )


def _batch(*tracks: Track, timestamp: float = 0.0) -> TrackBatch:
    return TrackBatch(
        feed_id="c2_feed",
        frame_seq=1,
        timestamp=timestamp,
        tracks=tuple(tracks),
        lost_track_ids=tuple(),
    )


def _make(
    *,
    upstream_cap: int = 1,
    downstream_cap: int = 1,
    pulse_success: bool = True,
    wiggle_success: bool = True,
    exit_handoff_min_interval_s: float = 0.85,
) -> tuple[RuntimeC2, CapacitySlot, CapacitySlot, list[str]]:
    upstream = CapacitySlot("c1_to_c2", capacity=upstream_cap)
    downstream = CapacitySlot("c2_to_c3", capacity=downstream_cap)
    log: list[str] = []

    def pulse(
        mode: RuntimeC2.PulseMode,
        pulse_ms: float,
        profile_name: str | None = None,
    ) -> bool:
        log.append(f"{mode.value}:{pulse_ms:.0f}")
        return pulse_success

    def wiggle() -> bool:
        log.append("wiggle")
        return wiggle_success

    def sample_transport(
        deg: float,
        max_speed: int | None = None,
        acceleration: int | None = None,
    ) -> bool:
        log.append(f"sample:{deg:.1f}")
        return pulse_success

    rt = RuntimeC2(
        upstream_slot=upstream,
        downstream_slot=downstream,
        pulse_command=pulse,
        wiggle_command=wiggle,
        sample_transport_command=sample_transport,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        pulse_cooldown_s=0.0,
        wiggle_stall_ms=200,
        wiggle_cooldown_ms=500,
        exit_handoff_min_interval_s=exit_handoff_min_interval_s,
    )
    return rt, upstream, downstream, log


def test_c2_pulses_when_exit_track_present_and_downstream_free() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    # Track at the exit fires a precise pulse and claims the downstream slot.
    assert log == ["precise:40"]
    assert down.available() == 0


def test_c2_pulses_for_stable_unconfirmed_exit_track() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=0.0, confirmed=False, hit_count=2)),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log == ["precise:40"]
    assert down.available() == 0


def test_c2_approach_pulse_is_precise_without_committing() -> None:
    rt, _up, down, log = _make()
    # Track at 30° — outside the 30° commit arc but inside the 45°
    # approach arc → small precise pulse, no downstream slot claim.
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=math.radians(35.0))),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log == ["precise:40"]
    assert down.available() == 1
    assert rt.health().state == "approaching"


def test_c2_advances_at_normal_speed_when_ring_has_no_track_near_exit() -> None:
    rt, _up, down, log = _make()
    # Track is far from exit (angle 90°) — outside both commit and
    # approach arcs. C2 advances the ring at normal transport speed
    # without claiming a downstream slot.
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=math.pi / 2.0)),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log == ["normal:40"]
    assert down.available() == 1
    assert rt.health().state == "advancing"


def test_c2_advances_loaded_ring_with_precise_pulse() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(
        tracks=_batch(
            _track(track_id=1, global_id=1, angle_rad=math.pi / 2.0),
            _track(track_id=2, global_id=2, angle_rad=math.pi),
        ),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log == ["precise:40"]
    assert down.available() == 1
    assert rt.health().state == "advancing"


def test_c2_idles_with_empty_ring() -> None:
    rt, _up, _down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert log == []
    assert rt.health().state == "idle"


def test_c2_sample_transport_scales_to_small_continuous_steps() -> None:
    rt, _up, _down, log = _make()
    port = rt.sample_transport_port()

    port.configure_sample_transport(target_rpm=3.2)

    assert port.nominal_degrees_per_step() == 15.0
    assert port.step(1.0) is True
    assert log == ["sample:15.0"]


def test_c2_does_not_pulse_when_downstream_full() -> None:
    rt, _up, _down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=0)
    rt.tick(inbox, now_mono=0.0)
    assert log == []
    assert rt.health().blocked_reason == "downstream_full"


def test_c2_does_not_wiggle_when_downstream_is_closed() -> None:
    rt, _up, _down, log = _make()
    stuck = _batch(_track(angle_rad=0.0))
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.1)
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.5)
    assert log == []
    assert rt.health().blocked_reason == "downstream_full"


def test_c2_new_visible_piece_releases_upstream_slot() -> None:
    rt, up, _down, _log = _make(upstream_cap=2)
    # Upstream slot was claimed twice — we expect one release per new piece.
    assert up.try_claim() is True
    assert up.try_claim() is True
    assert up.available() == 0
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=42, angle_rad=math.pi)),  # far from exit
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert up.available() == 1  # one piece credited
    # Second tick with same piece must not release again.
    rt.tick(inbox, now_mono=0.1)
    assert up.available() == 1


def test_c2_new_pending_tracks_do_not_fill_ring_capacity() -> None:
    rt, up, _down, _log = _make(upstream_cap=1)
    assert up.try_claim() is True
    tracks = _batch(
        _track(
            track_id=1,
            global_id=1,
            confirmed=False,
            angle_rad=math.pi / 2,
            hit_count=1,
        ),
        _track(
            track_id=2,
            global_id=2,
            confirmed=False,
            angle_rad=math.pi,
            hit_count=1,
        ),
        _track(
            track_id=3,
            global_id=3,
            confirmed=False,
            angle_rad=-math.pi / 2,
            hit_count=1,
        ),
        _track(
            track_id=4,
            global_id=4,
            confirmed=False,
            angle_rad=math.pi / 3,
            hit_count=1,
        ),
        _track(
            track_id=5,
            global_id=5,
            confirmed=False,
            angle_rad=-math.pi / 3,
            hit_count=1,
        ),
    )
    rt.tick(RuntimeInbox(tracks=tracks, capacity_downstream=1), now_mono=0.0)
    snap = rt.debug_snapshot()
    assert rt.available_slots() == 1
    assert up.available() == 0
    assert snap["piece_count"] == 0
    assert snap["admission_piece_count"] == 0
    assert snap["visible_track_count"] == 5
    assert snap["pending_track_count"] == 5


def test_c2_stable_pending_tracks_reserve_ring_capacity() -> None:
    rt, _up, _down, _log = _make()
    tracks = _batch(
        _track(
            track_id=1,
            global_id=1,
            confirmed=False,
            angle_rad=math.pi / 2,
            hit_count=3,
        ),
        _track(
            track_id=2,
            global_id=2,
            confirmed=False,
            angle_rad=math.pi,
            hit_count=3,
        ),
        _track(
            track_id=3,
            global_id=3,
            confirmed=False,
            angle_rad=-math.pi / 2,
            hit_count=3,
        ),
        _track(
            track_id=4,
            global_id=4,
            confirmed=False,
            angle_rad=math.pi / 3,
            hit_count=3,
        ),
        _track(
            track_id=5,
            global_id=5,
            confirmed=False,
            angle_rad=-math.pi / 3,
            hit_count=3,
        ),
    )
    rt.tick(RuntimeInbox(tracks=tracks, capacity_downstream=1), now_mono=0.0)
    snap = rt.debug_snapshot()
    # available_slots no longer gates on max_piece_count — see RuntimeC2.
    # The piece count bookkeeping is still surfaced for operator tuning.
    assert rt.available_slots() == 1
    assert snap["piece_count"] == 5
    assert snap["admission_piece_count"] == 5
    assert snap["pending_track_count"] == 0


def test_c2_ignores_stale_coasted_track_at_exit() -> None:
    rt, _up, _down, log = _make()
    stale = _track(angle_rad=0.0, last_seen_ts=0.1)
    rt.tick(
        RuntimeInbox(tracks=_batch(stale, timestamp=1.0), capacity_downstream=1),
        now_mono=1.0,
    )
    assert log == []
    assert rt.available_slots() == 1


def test_c2_on_piece_delivered_releases_upstream() -> None:
    rt, up, _down, _log = _make(upstream_cap=1)
    assert up.try_claim() is True
    rt.on_piece_delivered("uuid", now_mono=0.0)
    assert up.available() == 1


def test_c2_pulse_failure_releases_downstream_claim() -> None:
    rt, _up, down, log = _make(pulse_success=False)
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert log == ["precise:40"]
    assert down.available() == 1  # rolled back on failure


def test_c2_pending_handoff_waits_without_repeat_exit_pulse() -> None:
    rt, _up, down, log = _make(downstream_cap=1)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=42, angle_rad=0.0)),
        capacity_downstream=1,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=42, angle_rad=0.0)),
            capacity_downstream=0,
        ),
        now_mono=0.4,
    )

    assert down.taken(now_mono=0.4) == 1
    assert log == ["precise:40"]
    assert rt.debug_snapshot()["pending_downstream_claims"] == 1
    assert rt.health().state == "handoff_wait"
    assert rt.health().blocked_reason == "awaiting_downstream_arrival"


def test_c2_pending_handoff_retries_same_track_after_spacing_without_new_claim() -> None:
    rt, _up, down, log = _make(downstream_cap=1)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=42, angle_rad=0.0)),
        capacity_downstream=1,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=42, angle_rad=0.0)),
            capacity_downstream=0,
        ),
        now_mono=1.0,
    )

    assert down.taken(now_mono=1.0) == 1
    assert log == ["precise:40", "precise:40"]
    assert rt.debug_snapshot()["pending_downstream_claims"] == 1
    assert rt.health().state == "handoff_retry"


def test_c2_pending_handoff_escalates_to_double_nudge_without_new_claim() -> None:
    rt, _up, down, log = _make(downstream_cap=1)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=42, angle_rad=0.0)),
        capacity_downstream=1,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=42, angle_rad=0.0)),
            capacity_downstream=0,
        ),
        now_mono=1.0,
    )
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=42, angle_rad=0.0)),
            capacity_downstream=0,
        ),
        now_mono=2.0,
    )

    assert down.taken(now_mono=2.0) == 1
    assert log == ["precise:40", "precise:40", "precise:40", "precise:40"]
    snap = rt.debug_snapshot()
    assert snap["pending_downstream_claims"] == 1
    assert snap["pending_downstream_retry_max"] == 2
    assert rt.health().state == "handoff_retry"


def test_c2_exit_spacing_blocks_nearby_next_piece() -> None:
    rt, _up, down, log = _make(
        downstream_cap=4,
        exit_handoff_min_interval_s=0.85,
    )

    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=1, angle_rad=0.0)),
            capacity_downstream=4,
        ),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=2, angle_rad=math.radians(20.0))),
            capacity_downstream=down.available(now_mono=0.2),
        ),
        now_mono=0.2,
    )

    assert log == ["precise:40"]
    assert down.taken(now_mono=0.2) == 1
    assert rt.health().state == "handoff_spacing"
    assert rt.health().blocked_reason == "exit_spacing"


def test_c2_retries_exit_after_claim_hold_expires() -> None:
    rt, _up, down, log = _make(downstream_cap=1)
    inbox = RuntimeInbox(
        tracks=_batch(_track(global_id=42, angle_rad=0.0)),
        capacity_downstream=1,
    )

    rt.tick(inbox, now_mono=0.0)
    rt.tick(inbox, now_mono=4.0)

    assert down.taken(now_mono=4.0) == 1
    assert log == ["precise:40", "precise:40"]


def test_c2_available_slots_no_longer_caps_at_piece_count() -> None:
    """C2 used to drop available_slots to 0 once piece_count reached
    max_piece_count, but the carousel keeps feeding pieces past that
    soft cap regardless. The runtime now keeps reporting capacity 1
    so C1 keeps feeding and the next physical singulation gate
    (further downstream) is the real bottleneck."""
    rt, _up, _down, _log = _make()
    tracks = _batch(
        _track(track_id=1, global_id=1, angle_rad=math.pi / 2),
        _track(track_id=2, global_id=2, angle_rad=math.pi),
        _track(track_id=3, global_id=3, angle_rad=-math.pi / 2),
        _track(track_id=4, global_id=4, angle_rad=math.pi / 3),
        _track(track_id=5, global_id=5, angle_rad=-math.pi / 3),
    )
    rt.tick(RuntimeInbox(tracks=tracks, capacity_downstream=1), now_mono=0.0)
    assert rt.available_slots() == 1


# ----------------------------------------------------------------------
# PurgePort binding


def test_c2_purge_port_arm_pulses_despite_full_downstream() -> None:
    rt, _up, _down, log = _make()
    port = rt.purge_port()
    assert port.key == "c2"

    port.arm()
    # Downstream full + no exit track — normally blocked, purge must still pulse.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_rad=math.pi)), capacity_downstream=0),
        now_mono=0.0,
    )

    assert log == ["normal:40"]
    assert rt.available_slots() == 0


def test_c2_purge_port_counts_mirror_ring() -> None:
    rt, _up, _down, _log = _make()
    port = rt.purge_port()
    port.arm()

    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(global_id=1, angle_rad=0.5),
                _track(global_id=2, angle_rad=1.0),
            ),
            capacity_downstream=0,
        ),
        now_mono=0.0,
    )
    counts = port.counts()

    assert counts.piece_count == 2
    assert counts.owned_count == 0
    assert counts.pending_detections == 0


def test_c2_purge_port_disarm_clears_flag_and_bookkeeping() -> None:
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
    assert len(rt._bookkeeping.seen_global_ids) == 0
