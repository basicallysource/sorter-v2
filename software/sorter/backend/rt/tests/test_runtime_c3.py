from __future__ import annotations

import math
from typing import Callable

from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.runtimes.c3 import RuntimeC3


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
        radius_px=50.0,
        hit_count=hit_count,
        first_seen_ts=0.0,
        last_seen_ts=last_seen_ts,
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
        pulse_cooldown_s=0.0,
        wiggle_stall_ms=200,
        wiggle_cooldown_ms=500,
        holdover_ms=kwargs.get("holdover_ms", 2000),
        max_piece_count=kwargs.get("max_piece_count", 3),
    )
    return rt, upstream, downstream, log


def test_c3_precise_pulse_when_track_at_exit() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("precise:")
    assert down.available() == 0


def test_c3_precise_pulse_for_stable_unconfirmed_exit_track() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=0.0, confirmed=False, hit_count=2)),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log and log[0].startswith("precise:")
    assert down.available() == 0


def test_c3_precise_only_pulse_off_exit_never_commits() -> None:
    rt, _up, down, log = _make()
    # Track far from exit — C3 now runs at a single (precise) speed, but
    # still must not claim a downstream slot until the piece is inside
    # the commit arc.
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=math.pi)),
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
    # C3 now runs at a single speed — every pulse is precise regardless
    # of holdover state. The holdover flag is still exposed for
    # debugging but no longer switches the hardware gear.
    assert log and log[0].startswith("precise:")


def test_c3_sample_transport_scales_to_small_continuous_steps() -> None:
    rt, _up, _down, log = _make()
    port = rt.sample_transport_port()

    port.configure_sample_transport(target_rpm=3.2)

    assert port.nominal_degrees_per_step() == 15.0
    assert port.step(1.0) is True
    assert log == ["sample:15.0"]


def test_c3_exit_wiggle_when_downstream_closed_and_piece_stuck() -> None:
    rt, _up, _down, log = _make()
    stuck = _batch(_track(angle_rad=0.0))
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.5)
    assert "wiggle" in log


def test_c3_precise_pulse_rolled_back_on_hw_failure() -> None:
    rt, _up, down, log = _make(pulse_success=False)
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert down.available() == 1


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
    rt, _up, _down, _log = _make(max_piece_count=1)
    # With max_piece_count=1, one confirmed piece fills the ring and
    # available_slots drops to 0 until the piece drains downstream.
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
