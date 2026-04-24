from __future__ import annotations

import math
from concurrent.futures import Future
from typing import Any, Callable

from rt.contracts.classification import ClassifierResult
from rt.contracts.feed import FeedFrame
from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.slots import CapacitySlot
from rt.runtimes._strategies import (
    C4Admission,
    C4EjectionTiming,
    C4StartupPurgeStrategy,
)
from rt.runtimes._zones import ZoneManager
from rt.runtimes.c4 import RuntimeC4
from rt.services.track_transit import TrackTransitRegistry


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
    hit_count: int = 5,
    score: float = 0.9,
    first_seen_ts: float = 0.0,
    last_seen_ts: float = 0.0,
    bbox_xyxy: tuple[int, int, int, int] = (0, 0, 10, 10),
    radius_px: float = 50.0,
) -> Track:
    return Track(
        track_id=track_id,
        global_id=global_id,
        piece_uuid=None,
        bbox_xyxy=bbox_xyxy,
        score=score,
        confirmed_real=confirmed,
        angle_rad=math.radians(angle_deg),
        radius_px=radius_px,
        hit_count=hit_count,
        first_seen_ts=first_seen_ts,
        last_seen_ts=last_seen_ts,
    )


def _batch(*tracks: Track, timestamp: float = 0.0) -> TrackBatch:
    return TrackBatch(
        feed_id="c4_feed",
        frame_seq=1,
        timestamp=timestamp,
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
    admission: C4Admission | None = None,
    startup_purge: C4StartupPurgeStrategy | None = None,
    startup_purge_detection_count_provider: Callable[[], int] | None = None,
    **runtime_kwargs: Any,
) -> tuple[RuntimeC4, CapacitySlot, CapacitySlot, _StubClassifier, list[str]]:
    upstream = CapacitySlot("c3_to_c4", capacity=max_zones)
    downstream = CapacitySlot("c4_to_dist", capacity=max_zones)
    clf = classifier or _StubClassifier()
    log: list[str] = []

    def move(deg: float) -> bool:
        log.append(f"move:{deg:.1f}")
        return True

    def transport_move(deg: float) -> bool:
        log.append(f"transport:{deg:.1f}")
        return True

    def sample_transport_move(deg: float) -> bool:
        log.append(f"sample:{deg:.1f}")
        return True

    def purge_move(deg: float) -> bool:
        log.append(f"purge:{deg:.1f}")
        return True

    def eject() -> bool:
        log.append("eject")
        return True

    zm = ZoneManager(
        max_zones=max_zones,
        intake_angle_deg=0.0,
        guard_angle_deg=10.0,
        default_half_width_deg=10.0,
        drop_angle_deg=30.0,
        drop_tolerance_deg=14.0,
    )
    rt = RuntimeC4(
        upstream_slot=upstream,
        downstream_slot=downstream,
        zone_manager=zm,
        classifier=clf,
        admission=admission or C4Admission(max_zones=max_zones),
        ejection=ejection or C4EjectionTiming(
            pulse_ms=150.0, settle_ms=100.0, fall_time_ms=0.0
        ),
        startup_purge=startup_purge,
        startup_purge_detection_count_provider=startup_purge_detection_count_provider,
        carousel_move_command=move,
        transport_move_command=transport_move,
        sample_transport_move_command=sample_transport_move,
        startup_purge_move_command=purge_move,
        eject_command=eject,
        crop_provider=crop_provider or (lambda _f, _t: b"crop"),
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        angle_tolerance_deg=15.0,
        classify_angle_deg=90.0,
        exit_angle_deg=180.0,
        intake_half_width_deg=8.0,
        shimmy_stall_ms=100,
        shimmy_cooldown_ms=200,
        **runtime_kwargs,
    )
    rt.set_latest_frame(_frame())
    return rt, upstream, downstream, clf, log


# ----------------------------------------------------------------------


def test_c4_available_slots_open_when_empty() -> None:
    rt, _up, _down, _clf, _log = _make()
    assert rt.available_slots() == 1


def test_c4_sample_transport_uses_sample_move_command() -> None:
    rt, _up, _down, _clf, log = _make()

    assert rt.sample_transport_port().step(1.0) is True

    assert "sample:6.0" in log
    assert "transport:6.0" not in log


def test_c4_sample_transport_scales_step_for_high_target_rpm() -> None:
    rt, _up, _down, _clf, log = _make()
    port = rt.sample_transport_port()

    port.configure_sample_transport(target_rpm=30.0)

    assert port.nominal_degrees_per_step() == 45.0
    assert port.step(1.0) is True
    assert "sample:45.0" in log


def test_c4_available_slots_blocks_on_zone_cap() -> None:
    rt, up, _down, _clf, _log = _make(max_zones=1)
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 1
    assert rt.available_slots() == 0


def test_c4_available_slots_blocks_when_dropzone_occupied() -> None:
    rt, _up, _down, _clf, _log = _make(max_zones=4)
    rt._zone_manager.add_zone(piece_uuid="drop", angle_deg=30.0, global_id=9, now_mono=0.0)
    assert rt.available_slots() == 0


def test_c4_available_slots_blocks_on_raw_cap() -> None:
    rt, _up, _down, _clf, _log = _make(
        max_zones=2,
        admission=C4Admission(max_zones=2, max_raw_detections=3),
    )
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


def test_c4_idle_jog_when_it_believes_tray_is_empty() -> None:
    rt, _up, _down, _clf, log = _make()

    rt.tick(RuntimeInbox(tracks=_batch(), capacity_downstream=1), now_mono=1.0)

    assert "move:2.0" in log
    assert "c4_idle_jog" in _hw_commands(rt)
    assert rt.health().state == "idle_jog"
    assert rt.debug_snapshot()["idle_jog"]["count"] == 1

    rt.tick(RuntimeInbox(tracks=_batch(), capacity_downstream=1), now_mono=1.2)
    assert rt.debug_snapshot()["idle_jog"]["count"] == 1

    rt.tick(RuntimeInbox(tracks=_batch(), capacity_downstream=1), now_mono=1.6)
    assert rt.debug_snapshot()["idle_jog"]["count"] == 2


def test_c4_idle_jog_does_not_compete_with_owned_transport() -> None:
    rt, _up, _down, _clf, _log = _make()

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )

    assert rt.dossier_count() == 1
    assert "c4_idle_jog" not in _hw_commands(rt)


def test_c4_transport_unjam_when_owned_track_does_not_progress() -> None:
    rt, _up, _down, _clf, log = _make(
        unjam_stall_ms=500,
        unjam_cooldown_ms=1000,
        unjam_min_progress_deg=2.0,
    )
    stuck = _track(angle_deg=0.0)

    rt.tick(RuntimeInbox(tracks=_batch(stuck), capacity_downstream=1), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=_batch(stuck), capacity_downstream=1), now_mono=0.2)
    rt.tick(RuntimeInbox(tracks=_batch(stuck), capacity_downstream=1), now_mono=0.6)

    assert "move:-3.0" in log
    assert "move:9.0" in log
    assert "c4_transport_unjam" in _hw_commands(rt)
    assert rt.health().state == "transport_unjam"
    assert rt.debug_snapshot()["transport_unjam"]["count"] == 1


def test_c4_transport_unjam_watch_resets_on_progress() -> None:
    rt, _up, _down, _clf, _log = _make(
        unjam_stall_ms=500,
        unjam_cooldown_ms=1000,
        unjam_min_progress_deg=2.0,
    )

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=4.0)), capacity_downstream=1),
        now_mono=0.6,
    )

    assert "c4_transport_unjam" not in _hw_commands(rt)
    assert rt.debug_snapshot()["transport_unjam"]["count"] == 0


def test_c4_transport_waits_for_hw_backlog_to_clear() -> None:
    rt, _up, _down, _clf, log = _make()

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    log.clear()
    rt._hw.pending = lambda: 1  # type: ignore[method-assign,attr-defined]

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=10.0)), capacity_downstream=1),
        now_mono=1.0,
    )

    assert log == []


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


def test_c4_reuses_lost_piece_uuid_when_track_reappears_via_transit() -> None:
    registry = TrackTransitRegistry()
    rt, _up, _down, _clf, _log = _make(max_zones=1, track_transit=registry)

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=1, angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    piece_uuid = next(iter(rt._pieces))  # noqa: SLF001 - test-only inspection

    rt.tick(RuntimeInbox(tracks=_batch(), capacity_downstream=1), now_mono=2.0)
    assert rt.dossier_count() == 0
    assert registry.snapshot(2.0)

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=2, angle_deg=0.0)), capacity_downstream=1),
        now_mono=2.1,
    )

    dossier = rt.dossier_for(piece_uuid)
    assert dossier is not None
    assert dossier.global_id == 2
    assert dossier.extras["track_stitched"] is True
    assert dossier.extras["transit_relation"] == "track_split"
    assert dossier.extras["previous_tracked_global_id"] == 1
    assert rt.debug_snapshot()["transit_link_count"] == 1


def test_c4_reuses_lost_piece_uuid_when_same_track_id_reappears() -> None:
    registry = TrackTransitRegistry()
    rt, _up, _down, _clf, _log = _make(max_zones=1, track_transit=registry)

    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=17, angle_deg=0.0)),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    piece_uuid = next(iter(rt._pieces))  # noqa: SLF001 - test-only inspection

    rt.tick(RuntimeInbox(tracks=_batch(), capacity_downstream=1), now_mono=2.0)
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(global_id=17, angle_deg=0.0)),
            capacity_downstream=1,
        ),
        now_mono=7.5,
    )

    dossier = rt.dossier_for(piece_uuid)
    assert dossier is not None
    assert dossier.global_id == 17
    assert dossier.extras["track_stitched"] is True
    assert dossier.extras["previous_tracked_global_id"] == 17


def test_c4_consumes_c3_to_c4_transit_metadata() -> None:
    registry = TrackTransitRegistry()
    registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=77,
        target_runtime="c4",
        now_mono=10.0,
        relation="cross_channel",
    )
    rt, _up, _down, _clf, _log = _make(max_zones=1, track_transit=registry)

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=88, angle_deg=0.0)), capacity_downstream=1),
        now_mono=10.2,
    )

    piece_uuid = next(iter(rt._pieces))  # noqa: SLF001 - test-only inspection
    dossier = rt.dossier_for(piece_uuid)
    assert dossier is not None
    assert dossier.extras["track_stitched"] is True
    assert dossier.extras["transit_relation"] == "cross_channel"
    assert dossier.extras["transit_source_runtime"] == "c3"
    assert dossier.extras["transit_source_global_id"] == 77


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


def test_c4_waits_for_distributor_ready_before_ejecting() -> None:
    rt, _up, down, _clf, log = _make(max_zones=1)
    handoffs: list[dict[str, Any]] = []
    commits: list[str] = []

    class _Port:
        def handoff_request(self, **kwargs: Any) -> bool:
            handoffs.append(dict(kwargs))
            return True

        def handoff_commit(self, piece_uuid: str, **_kwargs: Any) -> bool:
            commits.append(piece_uuid)
            return True

        def handoff_abort(self, piece_uuid: str, **_kwargs: Any) -> bool:
            return True

    rt.set_handoff_port(_Port())

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    assert len(handoffs) == 1
    piece_uuid = handoffs[0]["piece_uuid"]
    assert handoffs[0]["classification"].part_id == "3001"
    assert down.available() == 0

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=0),
        now_mono=0.2,
    )
    assert "eject" not in log
    assert commits == []

    rt.on_distributor_ready(piece_uuid)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=180.0)), capacity_downstream=0),
        now_mono=0.3,
    )
    assert "eject" in log
    assert commits == [piece_uuid]


def test_c4_aborts_distributor_handoff_when_track_is_lost() -> None:
    rt, _up, down, _clf, _log = _make(max_zones=1)
    handoffs: list[dict[str, Any]] = []
    aborts: list[tuple[str, str]] = []

    class _Port:
        def handoff_request(self, **kwargs: Any) -> bool:
            handoffs.append(dict(kwargs))
            return True

        def handoff_commit(self, piece_uuid: str, **_kwargs: Any) -> bool:
            return True

        def handoff_abort(self, piece_uuid: str, *, reason: str = "handoff_aborted", **_kwargs: Any) -> bool:
            aborts.append((piece_uuid, reason))
            return True

    rt.set_handoff_port(_Port())

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )
    assert len(handoffs) == 1
    piece_uuid = handoffs[0]["piece_uuid"]
    assert down.available() == 0

    for t in (0.2, 0.8, 1.4, 2.0):
        rt.tick(RuntimeInbox(tracks=_batch(), capacity_downstream=1), now_mono=t)

    assert aborts == [(piece_uuid, "track_lost")]
    assert rt.dossier_count() == 0
    assert down.available() == 1


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


def test_c4_waits_for_stable_unconfirmed_tracks() -> None:
    rt, up, _down, clf, _log = _make()
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(
            tracks=_batch(_track(angle_deg=0.0, confirmed=False, hit_count=1)),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 0
    assert up.available() == 0  # upstream still claimed — no intake fired
    assert clf.calls == 0


def test_c4_admits_stable_unconfirmed_tracks() -> None:
    rt, up, _down, _clf, _log = _make()
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(angle_deg=0.0, confirmed=False, hit_count=2, score=0.8)
            ),
            capacity_downstream=1,
        ),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 1
    dossier = next(iter(rt._pieces.values()))  # noqa: SLF001
    assert dossier.extras.get("admission_basis") == "stable_detection"
    assert up.available() == 1


def test_c4_recovers_stable_visible_tracks_after_restart_and_starts_transport() -> None:
    rt, up, _down, _clf, log = _make(max_zones=2)
    stable = _track(
        global_id=7,
        angle_deg=45.0,
        confirmed=False,
        hit_count=6,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(stable, timestamp=1.0), capacity_downstream=1),
        now_mono=1.0,
    )
    assert rt.dossier_count() == 1
    dossier = next(iter(rt._pieces.values()))  # noqa: SLF001
    assert dossier.extras.get("recovered") is True
    assert up.available() == 2
    assert "transport:6.0" in log
    assert rt.health().state == "rotate_pipeline"


def test_c4_recovery_dedupes_overlapping_noisy_tracks() -> None:
    rt, _up, _down, _clf, _log = _make(max_zones=4)
    noisy_a = _track(
        global_id=7,
        angle_deg=45.0,
        confirmed=False,
        hit_count=8,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )
    noisy_b = _track(
        global_id=8,
        angle_deg=47.0,
        confirmed=False,
        hit_count=8,
        score=0.93,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )

    rt.tick(
        RuntimeInbox(tracks=_batch(noisy_a, noisy_b, timestamp=1.0), capacity_downstream=1),
        now_mono=1.0,
    )

    assert rt.dossier_count() == 1
    assert rt.debug_snapshot()["zone_count"] == 1


def test_c4_recovery_fills_free_slots_when_piece_already_owned() -> None:
    rt, up, _down, _clf, _log = _make(max_zones=3)
    assert up.try_claim() is True
    owned = _track(global_id=1, angle_deg=0.0, confirmed=True)
    stable_a = _track(
        global_id=7,
        angle_deg=55.0,
        confirmed=False,
        hit_count=8,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )
    stable_b = _track(
        global_id=8,
        angle_deg=105.0,
        confirmed=False,
        hit_count=8,
        score=0.93,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )

    rt.tick(
        RuntimeInbox(tracks=_batch(owned, timestamp=0.0), capacity_downstream=1),
        now_mono=0.0,
    )
    assert rt.dossier_count() == 1

    rt.tick(
        RuntimeInbox(
            tracks=_batch(owned, stable_a, stable_b, timestamp=1.0),
            capacity_downstream=1,
        ),
        now_mono=1.0,
    )

    assert rt.dossier_count() == 3
    recovered = [
        dossier
        for dossier in rt._pieces.values()  # noqa: SLF001
        if dossier.extras.get("recovered") is True
    ]
    assert len(recovered) == 2


def test_c4_slows_pipeline_motion_near_exit() -> None:
    rt, _up, _down, _clf, log = _make(max_zones=1)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )

    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=150.0)), capacity_downstream=1),
        now_mono=0.3,
    )

    assert "transport:6.0" in log
    assert "move:3.0" in log


def test_c4_exit_requires_majority_bbox_overlap_when_geometry_available() -> None:
    rt, _up, down, _clf, log = _make(max_zones=1)
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )

    # Center is at the exit angle, but the angular bbox is too wide for
    # more than half of it to be inside the exit window.
    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(
                    angle_deg=180.0,
                    bbox_xyxy=(-200, -20, 200, 20),
                    radius_px=80.0,
                )
            ),
            capacity_downstream=1,
        ),
        now_mono=0.3,
    )
    assert "eject" not in log
    assert down.available() == 1

    rt.tick(
        RuntimeInbox(
            tracks=_batch(
                _track(
                    angle_deg=180.0,
                    bbox_xyxy=(-5, -5, 5, 5),
                    radius_px=80.0,
                )
            ),
            capacity_downstream=1,
        ),
        now_mono=0.5,
    )
    assert "eject" in log


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


def test_c4_startup_purge_blocks_slots_until_clear() -> None:
    purge = C4StartupPurgeStrategy(
        enabled=True,
        prime_step_deg=6.0,
        prime_cooldown_ms=0.0,
        max_prime_moves=0,
        clear_hold_ms=100.0,
    )
    rt, _up, _down, _clf, _log = _make(startup_purge=purge)
    rt.arm_startup_purge()
    assert rt.available_slots() == 0
    rt.tick(RuntimeInbox(tracks=_batch(timestamp=0.0), capacity_downstream=1), now_mono=0.0)
    assert rt.available_slots() == 0
    rt.tick(RuntimeInbox(tracks=_batch(timestamp=0.2), capacity_downstream=1), now_mono=0.2)
    assert rt.available_slots() == 1
    assert rt.fsm_state() == "running"


def test_c4_startup_purge_primes_visible_tracks_before_recovery() -> None:
    purge = C4StartupPurgeStrategy(
        enabled=True,
        prime_step_deg=7.0,
        prime_cooldown_ms=0.0,
        max_prime_moves=2,
        clear_hold_ms=0.0,
    )
    rt, _up, _down, _clf, log = _make(startup_purge=purge)
    rt.arm_startup_purge()
    visible = _track(
        global_id=21,
        angle_deg=45.0,
        confirmed=False,
        hit_count=1,
        score=0.9,
        first_seen_ts=0.0,
        last_seen_ts=0.1,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(visible, timestamp=0.1), capacity_downstream=1),
        now_mono=0.1,
    )
    assert "purge:7.0" in log
    assert rt.fsm_state() == "startup_purge"
    assert rt.available_slots() == 0


def test_c4_startup_purge_primes_from_detection_count_before_tracks_exist() -> None:
    purge = C4StartupPurgeStrategy(
        enabled=True,
        prime_step_deg=9.0,
        prime_cooldown_ms=0.0,
        max_prime_moves=2,
        clear_hold_ms=0.0,
    )
    rt, _up, _down, _clf, log = _make(
        startup_purge=purge,
        startup_purge_detection_count_provider=lambda: 3,
    )
    rt.arm_startup_purge()
    rt.tick(
        RuntimeInbox(tracks=_batch(timestamp=0.1), capacity_downstream=1),
        now_mono=0.1,
    )
    assert "purge:9.0" in log
    assert rt.fsm_state() == "startup_purge"
    assert rt.available_slots() == 0


def test_c4_startup_purge_keeps_sweeping_visible_unowned_parts() -> None:
    purge = C4StartupPurgeStrategy(
        enabled=True,
        prime_step_deg=5.0,
        prime_cooldown_ms=0.0,
        max_prime_moves=1,
        clear_hold_ms=0.0,
    )
    rt, _up, _down, _clf, log = _make(
        startup_purge=purge,
        startup_purge_detection_count_provider=lambda: 2,
    )
    rt.arm_startup_purge()

    rt.tick(
        RuntimeInbox(tracks=_batch(timestamp=0.1), capacity_downstream=1),
        now_mono=0.1,
    )
    assert log.count("purge:5.0") == 1
    assert rt.fsm_state() == "startup_purge"
    assert rt.available_slots() == 0

    rt.tick(
        RuntimeInbox(tracks=_batch(timestamp=0.2), capacity_downstream=1),
        now_mono=0.2,
    )
    assert log.count("purge:5.0") == 2
    assert rt.fsm_state() == "startup_purge"
    assert rt.available_slots() == 0


def test_c4_startup_purge_recovers_rotates_and_ejects_without_classifier() -> None:
    purge = C4StartupPurgeStrategy(
        enabled=True,
        prime_step_deg=6.0,
        prime_cooldown_ms=0.0,
        max_prime_moves=1,
        clear_hold_ms=0.0,
    )
    rt, up, _down, clf, log = _make(
        max_zones=2,
        startup_purge=purge,
        ejection=C4EjectionTiming(pulse_ms=100.0, settle_ms=0.0, fall_time_ms=0.0),
    )
    rt.arm_startup_purge()
    stable = _track(
        global_id=7,
        angle_deg=45.0,
        confirmed=False,
        hit_count=6,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(stable, timestamp=1.0), capacity_downstream=1),
        now_mono=1.0,
    )
    assert rt.dossier_count() == 1
    assert clf.calls == 0
    assert up.available() == 2
    assert "purge:6.0" in log
    exit_track = _track(
        global_id=7,
        angle_deg=180.0,
        confirmed=False,
        hit_count=7,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.1,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(exit_track, timestamp=1.1), capacity_downstream=1),
        now_mono=1.1,
    )
    assert "eject" in log
    assert rt.fsm_state() == "startup_purge"
    rt.tick(
        RuntimeInbox(tracks=_batch(timestamp=1.2), capacity_downstream=1),
        now_mono=1.2,
    )
    assert rt.dossier_count() == 0
    assert rt.available_slots() == 1
    assert rt.fsm_state() == "running"

    # New admission goes through on a fresh track id.
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=2, angle_deg=0.0)), capacity_downstream=1),
        now_mono=2.1,
    )
    assert rt.dossier_count() == 1


def test_c4_startup_purge_owned_sweeps_when_no_exit_track() -> None:
    # Regression: when owned tracks exist, none is at the exit angle, and
    # _maybe_advance_transport declines to move (e.g. transport cooldown),
    # the FSM previously stalled in awaiting_exit because the prime branch
    # only runs while owned_count == 0. The owned-sweep fallback must now
    # rotate the tray itself.
    purge = C4StartupPurgeStrategy(
        enabled=True,
        prime_step_deg=4.0,
        prime_cooldown_ms=0.0,
        max_prime_moves=1,
        clear_hold_ms=0.0,
    )
    rt, _up, _down, _clf, log = _make(startup_purge=purge)
    rt.arm_startup_purge()

    stable = _track(
        global_id=9,
        angle_deg=45.0,
        confirmed=False,
        hit_count=6,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(stable, timestamp=1.0), capacity_downstream=1),
        now_mono=1.0,
    )
    # First tick: _maybe_advance_transport enqueues a transport-step move
    # (default transport_step_deg=6.0) and sets _next_transport_at.
    assert rt.dossier_count() == 1
    assert "purge:6.0" in log

    # Second tick inside the transport cooldown window — _maybe_advance_transport
    # returns False (transport blocked). Without the fallback the FSM would land
    # in awaiting_exit with no motion. With the fallback it must enqueue a
    # prime_step_deg=4.0 sweep instead.
    lingering = _track(
        global_id=9,
        angle_deg=45.0,
        confirmed=False,
        hit_count=8,
        score=0.95,
        first_seen_ts=0.0,
        last_seen_ts=1.05,
    )
    rt.tick(
        RuntimeInbox(tracks=_batch(lingering, timestamp=1.05), capacity_downstream=1),
        now_mono=1.05,
    )

    assert "purge:4.0" in log, (
        "owned-sweep fallback must rotate the tray when owned track is "
        "not at exit and transport is cooldown-blocked"
    )
    assert rt.fsm_state() == "startup_purge"


# ----------------------------------------------------------------------
# PurgePort binding


def _purge_port_runtime() -> RuntimeC4:
    rt, *_ = _make(startup_purge=C4StartupPurgeStrategy(enabled=True))
    return rt


def test_c4_purge_port_arm_flips_startup_flag() -> None:
    rt = _purge_port_runtime()
    port = rt.purge_port()
    assert port.key == "c4"
    assert rt.startup_purge_armed is False

    port.arm()

    assert rt.startup_purge_armed is True


def test_c4_purge_port_counts_reflect_runtime_state() -> None:
    rt = _purge_port_runtime()
    rt._raw_detection_count = 3
    rt._pieces["uuid-a"] = object()  # type: ignore[assignment]
    rt._pieces["uuid-b"] = object()  # type: ignore[assignment]

    counts = rt.purge_port().counts()

    assert counts.piece_count == 3
    assert counts.owned_count == 2
    assert counts.pending_detections == 0
    assert counts.is_empty is False


def test_c4_purge_port_counts_empty_when_idle() -> None:
    rt = _purge_port_runtime()
    counts = rt.purge_port().counts()
    assert counts.is_empty is True


def test_c4_purge_port_drain_step_reports_armed_state() -> None:
    rt = _purge_port_runtime()
    port = rt.purge_port()
    assert port.drain_step(now_mono=1.0) is False

    port.arm()

    assert port.drain_step(now_mono=1.0) is True


def test_c4_purge_port_disarm_clears_flag_and_exits_mode() -> None:
    rt = _purge_port_runtime()
    port = rt.purge_port()
    port.arm()
    assert rt.startup_purge_armed is True

    port.disarm()

    assert rt.startup_purge_armed is False


# ----------------------------------------------------------------------
# Introspection helper


def _hw_commands(rt: RuntimeC4) -> list[str]:
    hw = rt._hw  # noqa: SLF001
    return getattr(hw, "commands", [])


# ----------------------------------------------------------------------
# Event-bus publishing (H1 fix — rt_flow piece-dossier bridge)


def _make_with_bus() -> tuple[RuntimeC4, CapacitySlot, _StubClassifier, list]:
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

    upstream = CapacitySlot("c3_to_c4", capacity=1)
    downstream = CapacitySlot("c4_to_dist", capacity=1)
    clf = _StubClassifier()
    zm = ZoneManager(
        max_zones=1,
        intake_angle_deg=0.0,
        guard_angle_deg=10.0,
        default_half_width_deg=10.0,
    )
    rt = RuntimeC4(
        upstream_slot=upstream,
        downstream_slot=downstream,
        zone_manager=zm,
        classifier=clf,
        admission=C4Admission(max_zones=1, max_raw_detections=3),
        ejection=C4EjectionTiming(pulse_ms=150.0, settle_ms=100.0, fall_time_ms=0.0),
        carousel_move_command=lambda _d: True,
        eject_command=lambda: True,
        crop_provider=lambda _f, _t: b"crop",
        hw_worker=_InlineHw(),  # type: ignore[arg-type]
        event_bus=_Bus(),
        angle_tolerance_deg=15.0,
        classify_angle_deg=90.0,
        exit_angle_deg=180.0,
        intake_half_width_deg=8.0,
    )
    rt.set_latest_frame(_frame())
    return rt, upstream, clf, published


def test_c4_publishes_piece_registered_on_intake() -> None:
    rt, up, _clf, published = _make_with_bus()
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=55, angle_deg=0.0)), capacity_downstream=1),
        now_mono=1.0,
    )

    registered = [e for e in published if e.topic == "piece.registered"]
    assert len(registered) == 1
    evt = registered[0]
    assert evt.source == "c4"
    assert isinstance(evt.payload.get("piece_uuid"), str)
    assert evt.payload["tracked_global_id"] == 55
    assert evt.payload["confirmed_real"] is True
    assert evt.payload["stage"] == "registered"
    assert evt.payload["classification_status"] == "pending"
    assert evt.payload["classification_channel_zone_state"] == "active"
    nested = evt.payload.get("dossier")
    assert isinstance(nested, dict)
    assert nested.get("tracked_global_id") == 55
    assert nested.get("classification_channel_zone_state") == "active"


def test_c4_publishes_piece_classified_on_classifier_return() -> None:
    rt, up, _clf, published = _make_with_bus()
    assert up.try_claim() is True
    # Intake at 0°.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=77, angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )
    # Bring the track to the classify angle (90°) so async is submitted.
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=77, angle_deg=90.0)), capacity_downstream=1),
        now_mono=0.1,
    )

    classified = [e for e in published if e.topic == "piece.classified"]
    assert len(classified) == 1
    evt = classified[0]
    assert isinstance(evt.payload.get("piece_uuid"), str)
    assert evt.payload["tracked_global_id"] == 77
    assert evt.payload["stage"] == "classified"
    assert evt.payload["classification_status"] == "classified"
    assert evt.payload["classification_channel_zone_state"] == "active"
    nested = evt.payload.get("dossier")
    assert isinstance(nested, dict)
    assert nested.get("classification_channel_zone_state") == "active"
    assert nested.get("part_id") == "3001"
    assert nested.get("color_id") == "red"


def test_c4_publishes_piece_lost_when_owned_track_evicted() -> None:
    rt, up, _clf, published = _make_with_bus()
    assert up.try_claim() is True
    rt.tick(
        RuntimeInbox(tracks=_batch(_track(global_id=88, angle_deg=0.0)), capacity_downstream=1),
        now_mono=0.0,
    )

    for t in (0.2, 0.8, 1.4, 2.0):
        rt.tick(RuntimeInbox(tracks=_batch(timestamp=t), capacity_downstream=1), now_mono=t)

    lost = [
        e
        for e in published
        if e.payload.get("classification_channel_zone_state") == "lost"
    ]
    assert len(lost) == 1
    evt = lost[0]
    assert evt.topic == "piece.registered"
    assert evt.payload["tracked_global_id"] == 88
    assert evt.payload["stage"] == "registered"
    assert evt.payload["classification_status"] == "pending"
    nested = evt.payload.get("dossier")
    assert isinstance(nested, dict)
    assert nested.get("classification_channel_zone_state") == "lost"
