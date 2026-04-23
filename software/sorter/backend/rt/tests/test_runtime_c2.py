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
        hit_count=5,
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
) -> tuple[RuntimeC2, CapacitySlot, CapacitySlot, list[str]]:
    upstream = CapacitySlot("c1_to_c2", capacity=upstream_cap)
    downstream = CapacitySlot("c2_to_c3", capacity=downstream_cap)
    log: list[str] = []

    def pulse(pulse_ms: float) -> bool:
        log.append(f"pulse:{pulse_ms:.0f}")
        return pulse_success

    def wiggle() -> bool:
        log.append("wiggle")
        return wiggle_success

    rt = RuntimeC2(
        upstream_slot=upstream,
        downstream_slot=downstream,
        pulse_command=pulse,
        wiggle_command=wiggle,
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        pulse_cooldown_s=0.0,
        wiggle_stall_ms=200,
        wiggle_cooldown_ms=500,
    )
    return rt, upstream, downstream, log


def test_c2_pulses_when_exit_track_present_and_downstream_free() -> None:
    rt, _up, down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=1)
    rt.tick(inbox, now_mono=0.0)
    assert log == ["pulse:40"]
    assert down.available() == 0


def test_c2_skips_when_no_exit_track() -> None:
    rt, _up, _down, log = _make()
    # Track is far from exit (angle 90°).
    inbox = RuntimeInbox(
        tracks=_batch(_track(angle_rad=math.pi / 2.0)),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    assert log == []
    assert rt.health().state == "idle"


def test_c2_does_not_pulse_when_downstream_full() -> None:
    rt, _up, _down, log = _make()
    inbox = RuntimeInbox(tracks=_batch(_track(angle_rad=0.0)), capacity_downstream=0)
    rt.tick(inbox, now_mono=0.0)
    assert log == []
    assert rt.health().blocked_reason == "downstream_full"


def test_c2_exit_wiggle_fires_after_stall() -> None:
    rt, _up, _down, log = _make()
    stuck = _batch(_track(angle_rad=0.0))
    # Downstream is closed so the normal pulse path is blocked.
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.0)
    assert log == []  # starts stall timer
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.1)
    rt.tick(RuntimeInbox(tracks=stuck, capacity_downstream=0), now_mono=0.5)
    assert "wiggle" in log
    assert rt.health().state == "exit_wiggle"


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


def test_c2_visible_tracks_count_toward_ring_capacity() -> None:
    rt, _up, _down, _log = _make()
    tracks = _batch(
        _track(track_id=1, global_id=1, confirmed=False, angle_rad=math.pi / 2),
        _track(track_id=2, global_id=2, confirmed=False, angle_rad=math.pi),
        _track(track_id=3, global_id=3, confirmed=False, angle_rad=-math.pi / 2),
        _track(track_id=4, global_id=4, confirmed=False, angle_rad=math.pi / 3),
        _track(track_id=5, global_id=5, confirmed=False, angle_rad=-math.pi / 3),
    )
    rt.tick(RuntimeInbox(tracks=tracks, capacity_downstream=1), now_mono=0.0)
    assert rt.available_slots() == 0


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
    assert log == ["pulse:40"]
    assert down.available() == 1  # rolled back on failure


def test_c2_available_slots_caps_at_ring_count() -> None:
    rt, _up, _down, _log = _make()
    tracks = _batch(
        _track(track_id=1, global_id=1, angle_rad=math.pi / 2),
        _track(track_id=2, global_id=2, angle_rad=math.pi),
        _track(track_id=3, global_id=3, angle_rad=-math.pi / 2),
        _track(track_id=4, global_id=4, angle_rad=math.pi / 3),
        _track(track_id=5, global_id=5, angle_rad=-math.pi / 3),
    )
    rt.tick(RuntimeInbox(tracks=tracks, capacity_downstream=1), now_mono=0.0)
    # Default max_ring_count = 5 so we should now report 0.
    assert rt.available_slots() == 0


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

    assert log == ["pulse:40"]
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

    assert counts.ring_count == 2
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
    assert rt._ring_count == 0
    assert len(rt._bookkeeping.seen_global_ids) == 0
