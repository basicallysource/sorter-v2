from __future__ import annotations

import math
from concurrent.futures import Future
from typing import Any, Callable

from rt.contracts.classification import ClassifierResult
from rt.contracts.feed import FeedFrame
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.runtimes._strategies import C4Admission, C4EjectionTiming
from rt.runtimes._zones import ZoneManager
from rt.runtimes.c4 import RuntimeC4


# ----------------------------------------------------------------------


class _InlineHw:
    def __init__(self) -> None:
        self._busy = False
        self.commands: list[str] = []

    def start(self) -> None:  # pragma: no cover
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


class _StubClassifier:
    """Immediate-synchronous classifier — ``classify_async`` returns a done future."""

    key = "stub"

    def __init__(self, result: ClassifierResult | None = None) -> None:
        self._result = result or ClassifierResult(
            part_id="3001",
            color_id="red",
            category="part",
            confidence=0.9,
            algorithm="stub",
            latency_ms=5.0,
            meta={},
        )
        self.calls: int = 0
        self.submit_delay_pending: Future[ClassifierResult] | None = None

    def classify(self, track, frame, crop):  # pragma: no cover — unused here
        self.calls += 1
        return self._result

    def classify_async(self, track, frame, crop):
        self.calls += 1
        if self.submit_delay_pending is not None:
            fut = self.submit_delay_pending
            self.submit_delay_pending = None
            return fut
        fut: Future[ClassifierResult] = Future()
        fut.set_result(self._result)
        return fut

    def reset(self) -> None:  # pragma: no cover
        return None

    def stop(self) -> None:  # pragma: no cover
        return None


def _track(
    track_id: int = 1,
    global_id: int = 1,
    angle_deg: float = 0.0,
    confirmed: bool = True,
) -> Track:
    return Track(
        track_id=track_id,
        global_id=global_id,
        piece_uuid=None,
        bbox_xyxy=(0, 0, 10, 10),
        score=0.9,
        confirmed_real=confirmed,
        angle_rad=math.radians(angle_deg),
        radius_px=50.0,
        hit_count=5,
        first_seen_ts=0.0,
        last_seen_ts=0.0,
    )


def _batch(*tracks: Track) -> TrackBatch:
    return TrackBatch(
        feed_id="c4_feed",
        frame_seq=1,
        timestamp=0.0,
        tracks=tuple(tracks),
        lost_track_ids=tuple(),
    )


def _frame() -> FeedFrame:
    return FeedFrame(
        feed_id="c4_feed",
        camera_id="c4",
        raw=None,
        gray=None,
        timestamp=0.0,
        monotonic_ts=0.0,
        frame_seq=42,
    )


def _make(
    *,
    max_zones: int = 1,
    classifier: _StubClassifier | None = None,
    crop_provider: Callable[[FeedFrame, Track], Any] | None = None,
    ejection: C4EjectionTiming | None = None,
) -> tuple[RuntimeC4, CapacitySlot, CapacitySlot, _StubClassifier, list[str]]:
    upstream = CapacitySlot("c3_to_c4", capacity=max_zones)
    downstream = CapacitySlot("c4_to_dist", capacity=max_zones)
    clf = classifier or _StubClassifier()
    log: list[str] = []

    def move(deg: float) -> bool:
        log.append(f"move:{deg:.1f}")
        return True

    def eject() -> bool:
        log.append("eject")
        return True

    zm = ZoneManager(
        max_zones=max_zones,
        intake_angle_deg=0.0,
        guard_angle_deg=10.0,
        default_half_width_deg=10.0,
    )
    rt = RuntimeC4(
        upstream_slot=upstream,
        downstream_slot=downstream,
        zone_manager=zm,
        classifier=clf,
        admission=C4Admission(max_zones=max_zones, max_raw_detections=3),
        ejection=ejection or C4EjectionTiming(
            pulse_ms=150.0, settle_ms=100.0, fall_time_ms=0.0
        ),
        carousel_move_command=move,
        eject_command=eject,
        crop_provider=crop_provider or (lambda _f, _t: b"crop"),
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        angle_tolerance_deg=15.0,
        classify_angle_deg=90.0,
        exit_angle_deg=180.0,
        intake_half_width_deg=8.0,
        shimmy_stall_ms=100,
        shimmy_cooldown_ms=200,
    )
    rt.set_latest_frame(_frame())
    return rt, upstream, downstream, clf, log


# ----------------------------------------------------------------------


def test_c4_available_slots_open_when_empty() -> None:
    rt, _up, _down, _clf, _log = _make()
    assert rt.available_slots() == 1


def test_c4_available_slots_blocks_on_zone_cap() -> None:
    rt, up, _down, _clf, _log = _make(max_zones=1)
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 1
    assert rt.available_slots() == 0


def test_c4_available_slots_blocks_on_raw_cap() -> None:
    rt, _up, _down, _clf, _log = _make(max_zones=2)
    # Construct a batch with 3 tracks, none of which we own yet.
    inbox = RuntimeInbox(
        tracks=_batch(
            _track(track_id=10, global_id=10, angle_deg=200.0),
            _track(track_id=11, global_id=11, angle_deg=210.0),
            _track(track_id=12, global_id=12, angle_deg=220.0),
        ),
        capacity_downstream=1,
    )
    rt.tick(inbox, now_mono=0.0)
    # raw cap = 3 → next admission attempt must be blocked.
    assert rt.available_slots() == 0


def test_c4_intake_mints_dossier_and_releases_upstream() -> None:
    rt, up, _down, _clf, _log = _make(max_zones=1)
    assert up.try_claim() is True
    assert up.available() == 0
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 1
    # Upstream slot was released.
    assert up.available() == 1


def test_c4_submits_classifier_at_classify_angle() -> None:
    clf = _StubClassifier()
    rt, _up, _down, clf_out, _log = _make(classifier=clf)
    # Piece at intake angle.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert clf.calls == 0
    # Piece moves to classify angle — classifier should fire.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    assert clf.calls == 1
    # Dossier has result attached.
    uuid = next(iter(rt._pieces))  # noqa: SLF001 — test-only inspection
    dossier = rt.dossier_for(uuid)
    assert dossier is not None
    assert dossier.result is not None
    assert dossier.result.part_id == "3001"


def test_c4_drop_commit_fires_eject_on_exit() -> None:
    rt, _up, down, _clf, log = _make(max_zones=1)
    inbox_intake = RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1)
    rt.tick(inbox_intake, now_mono=0.0)
    # Bring piece to classify angle (triggers classification).
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    # Bring piece to exit angle with downstream capacity open — should eject.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=1),
        now_mono=0.2,
    )
    assert "eject" in log
    assert down.available() == 0
    assert rt.fsm_state() == "drop_commit"


def test_c4_does_not_eject_when_not_classified() -> None:
    # Classifier future stays pending — drop should be held off.
    clf = _StubClassifier()
    pending: Future[ClassifierResult] = Future()
    clf.submit_delay_pending = pending
    rt, _up, down, _clf_out, log = _make(max_zones=1, classifier=clf)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    # Pass classify angle — future is still pending.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    # Arrive at exit — should NOT eject because result is None.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=1),
        now_mono=0.2,
    )
    assert "eject" not in log
    assert down.available() == 1
    # Resolve the pending future + tick again.
    pending.set_result(
        ClassifierResult(
            part_id="9999",
            color_id="blue",
            category="part",
            confidence=0.75,
            algorithm="stub",
            latency_ms=5.0,
            meta={},
        )
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=1),
        now_mono=0.3,
    )
    assert "eject" in log


def test_c4_on_piece_delivered_pops_dossier_and_releases_downstream() -> None:
    rt, _up, down, _clf, _log = _make(max_zones=1)
    # Bring a piece all the way through and eject.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=1),
        now_mono=0.2,
    )
    piece_uuid = next(iter(rt._pieces))  # noqa: SLF001
    assert down.available() == 0
    rt.on_piece_delivered(piece_uuid, now_mono=0.3)
    assert rt.dossier_count() == 0
    assert down.available() == 1
    assert rt.fsm_state() == "running"


def test_c4_on_piece_rejected_stub_pops_dossier() -> None:
    rt, _up, down, _clf, _log = _make(max_zones=1)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    piece_uuid = next(iter(rt._pieces))  # noqa: SLF001
    # Before reject, downstream has not been claimed — calling reject still
    # releases defensively; capacity must stay <= initial.
    initial = down.available()
    rt.on_piece_rejected(piece_uuid, reason="distributor_full")
    assert rt.dossier_count() == 0
    assert rt.fsm_state() in ("running", "classify_pending")
    # No lingering zone.
    assert rt._zone_manager.zone_count() == 0  # noqa: SLF001
    assert down.available() >= initial


def test_c4_shimmy_when_downstream_closed_and_piece_at_exit() -> None:
    rt, _up, _down, _clf, log = _make(max_zones=1)
    # Establish piece at intake, classify, then reach exit.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    stuck = RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=0)
    rt.tick(stuck, now_mono=0.2)
    rt.tick(stuck, now_mono=0.5)
    assert any(c == "c4_exit_shimmy" for c in _hw_commands(rt))


def test_c4_tick_catches_exception_gracefully() -> None:
    class _BadClassifier(_StubClassifier):
        def classify_async(self, track, frame, crop):
            raise RuntimeError("classifier exploded")

    bad = _BadClassifier()
    rt, _up, _down, _clf, _log = _make(classifier=bad)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    # tick should NOT raise even if classify_async blows up.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    # Dossier exists without result.
    uuid = next(iter(rt._pieces))  # noqa: SLF001
    assert rt.dossier_for(uuid).result is None


def test_c4_ignores_unconfirmed_tracks() -> None:
    rt, up, _down, clf, _log = _make()
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(angle_deg=0.0, confirmed=False)),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 0
    assert up.available() == 0  # upstream still claimed — no intake fired
    assert clf.calls == 0


def test_c4_state_transitions_through_commit_cycle() -> None:
    rt, _up, _down, _clf, _log = _make(max_zones=1)
    assert rt.fsm_state() == "running"
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.fsm_state() == "running"
    # At classify angle a synchronous stub finishes in-tick; FSM stays running.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    assert rt.fsm_state() == "running"
    # Drop commit fires at exit angle.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=1),
        now_mono=0.2,
    )
    assert rt.fsm_state() == "drop_commit"


def test_c4_post_commit_cooldown_blocks_new_intake() -> None:
    # fall_time_ms=500 → 0.5 s cooldown window after delivery.
    eject = C4EjectionTiming(pulse_ms=100.0, settle_ms=50.0, fall_time_ms=500.0)
    rt, _up, down, _clf, _log = _make(max_zones=1, ejection=eject)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=1),
        now_mono=0.2,
    )
    piece_uuid = next(iter(rt._pieces))  # noqa: SLF001
    rt.on_piece_delivered(piece_uuid, now_mono=0.3)
    # New inbound track at intake — cooldown should suppress admission.
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(track_id=2, global_id=2, angle_deg=0.0)),
            capacity_downstream=1,
        ),
        now_mono=0.35,
    )
    assert rt.dossier_count() == 0
    # After cooldown, admission resumes.
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(track_id=2, global_id=2, angle_deg=0.0)),
            capacity_downstream=1,
        ),
        now_mono=1.0,
    )
    assert rt.dossier_count() == 1


def test_c4_deadlock_recovery_after_tracker_drop() -> None:
    # Admit a piece, then have the tracker drop it permanently. After the
    # ZoneManager stale_timeout_s elapses, both the zone and the dossier
    # must be pruned so new admits can proceed.
    rt, up, _down, _clf, _log = _make(max_zones=1)
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=1, angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 1
    assert rt._zone_manager.zone_count() == 1  # noqa: SLF001
    assert rt.available_slots() == 0

    # Tracker glitch: track vanishes for a long span. ZoneManager default
    # stale_timeout_s is 1.5 s — advance clock beyond that with empty tracks.
    for t in (0.2, 0.6, 1.0, 1.4, 2.0):
        rt.tick(
            RuntimeInbox(tracks=_batch(), capacity_downstream=1),
            now_mono=t,
        )

    assert rt._zone_manager.zone_count() == 0  # noqa: SLF001
    assert rt.dossier_count() == 0
    assert rt.available_slots() == 1

    # New admission goes through on a fresh track id.
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=2, angle_deg=0.0)), capacity_downstream=1),
        now_mono=2.1,
    )
    assert rt.dossier_count() == 1


# ----------------------------------------------------------------------
# Introspection helper


def _hw_commands(rt: RuntimeC4) -> list[str]:
    hw = rt._hw  # noqa: SLF001
    return getattr(hw, "commands", [])
