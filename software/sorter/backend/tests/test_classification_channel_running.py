from __future__ import annotations

from types import SimpleNamespace

from defs.known_object import ClassificationStatus, KnownObject
from subsystems.classification_channel.running import Running
from subsystems.classification_channel.zone_manager import TrackAngularExtent


class _Logger:
    def debug(self, *args, **kwargs) -> None:
        pass

    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class _RuntimeStats:
    def __init__(self) -> None:
        self.leader_wins_events: list[dict[str, object]] = []
        self.recognizer_counts: dict[str, int] = {}

    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, *args, **kwargs) -> None:
        pass

    def observeMultiDropLeaderWins(self, **meta) -> None:
        self.leader_wins_events.append(dict(meta))

    def observeRecognizerCounter(self, name: str) -> None:
        self.recognizer_counts[name] = self.recognizer_counts.get(name, 0) + 1


class _Stepper:
    def __init__(self) -> None:
        self.stopped = True
        self.moves: list[float] = []
        self.speed_limits: list[tuple[int, int]] = []
        self.accelerations: list[int] = []

    def degrees_for_microsteps(self, steps: int) -> float:
        return float(steps) / 10.0

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(float(degrees))
        self.stopped = True
        return True

    def set_speed_limits(self, microsteps: int, speed: int) -> None:
        self.speed_limits.append((int(microsteps), int(speed)))

    def set_acceleration(self, acceleration: int) -> None:
        self.accelerations.append(int(acceleration))


class _Transport:
    def __init__(self) -> None:
        self.zone_manager = object()
        self._pieces_by_track: dict[int, SimpleNamespace] = {}
        self._ignored_recovery_tracks: set[int] = set()
        self.register_calls: list[int | None] = []
        self._pending = False

    def pieceForTrack(self, track_global_id: int):
        return self._pieces_by_track.get(int(track_global_id))

    def activePieces(self):
        return list(self._pieces_by_track.values())

    def registerIncomingPiece(self, *, tracked_global_id: int | None = None):
        piece = KnownObject(
            uuid=f"piece-{tracked_global_id}",
            tracked_global_id=tracked_global_id,
            classification_status=ClassificationStatus.pending,
        )
        if tracked_global_id is not None:
            self._pieces_by_track[int(tracked_global_id)] = piece
        self.register_calls.append(tracked_global_id)
        return piece

    def updateTrackedPieces(self, track_extents, *, carousel_angle_deg=None):
        return [], []

    def shouldIgnoreRecoveredTrack(
        self,
        track_global_id: int,
        *,
        first_seen_ts: float | None,
        first_seen_grace_s: float = 1.0,
    ) -> bool:
        return int(track_global_id) in self._ignored_recovery_tracks

    def isPendingClassification(self, uuid: str) -> bool:
        return False

    def hasPendingClassifications(self) -> bool:
        return self._pending


class _Shared:
    def __init__(self) -> None:
        self.classification_gate_calls: list[tuple[bool, str | None]] = []
        self.distribution_ready = True

    def set_classification_gate(self, open: bool, reason: str | None = None) -> None:
        self.classification_gate_calls.append((bool(open), reason))

    def set_distribution_gate(self, open: bool, reason: str | None = None) -> None:
        pass

    def publish_piece_delivered(self, *args, **kwargs) -> None:
        pass


class _EventQueue:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put(self, item) -> None:
        self.items.append(item)


def _make_running() -> tuple[Running, _Transport, _Shared, _EventQueue]:
    transport = _Transport()
    shared = _Shared()
    event_queue = _EventQueue()
    stepper = _Stepper()
    running = Running(
        irl=SimpleNamespace(carousel_stepper=stepper),
        irl_config=SimpleNamespace(
            classification_channel_config=SimpleNamespace(
                intake_angle_deg=0.0,
                intake_body_half_width_deg=10.0,
                intake_guard_deg=28.0,
                drop_angle_deg=30.0,
                drop_tolerance_deg=14.0,
                point_of_no_return_deg=18.0,
                recognition_window_deg=60.0,
                max_zones=4,
                hood_dwell_ms=1200,
                min_carousel_crops_for_recognize=0,
                min_carousel_dwell_ms=0,
                min_carousel_traversal_deg=0.0,
                exit_release_overlap_ratio=0.5,
                exit_release_shimmy_amplitude_deg=1.5,
                exit_release_shimmy_cycles=2,
                exit_release_shimmy_microsteps_per_second=4200,
                exit_release_shimmy_acceleration_microsteps_per_second_sq=9000,
            )
            ,
            feeder_config=SimpleNamespace(
                classification_channel_eject=SimpleNamespace(
                    steps_per_pulse=90,
                    microsteps_per_second=3400,
                    acceleration_microsteps_per_second_sq=2500,
                )
            ),
        ),
        gc=SimpleNamespace(
            logger=_Logger(),
            runtime_stats=_RuntimeStats(),
        ),
        shared=shared,
        transport=transport,
        vision=None,
        event_queue=event_queue,
    )
    return running, transport, shared, event_queue


def test_running_registers_new_intake_piece_only_while_awaiting_handoff() -> None:
    running, transport, shared, _events = _make_running()
    track = TrackAngularExtent(
        global_id=41,
        center_deg=2.0,
        half_width_deg=6.0,
        last_seen_ts=1.0,
        hit_count=3,
    )

    running._registerNewIntakePiece([track], now_wall=10.0, now_mono=20.0)

    assert transport.register_calls == []
    assert shared.classification_gate_calls == []


def test_running_requires_minimum_track_hits_before_registering_new_piece() -> None:
    running, transport, shared, _events = _make_running()
    running._awaiting_intake_piece = True
    running._intake_requested_at_mono = 19.0
    running._intake_requested_at_wall = 9.8
    weak_track = TrackAngularExtent(
        global_id=41,
        center_deg=1.5,
        half_width_deg=6.0,
        last_seen_ts=1.0,
        hit_count=1,
    )

    running._registerNewIntakePiece([weak_track], now_wall=10.0, now_mono=20.0)

    assert transport.register_calls == []
    assert running._awaiting_intake_piece is True
    assert shared.classification_gate_calls == []


def test_running_registers_piece_from_confirmed_track_when_awaiting_handoff() -> None:
    running, transport, shared, events = _make_running()
    running._awaiting_intake_piece = True
    running._intake_requested_at_mono = 19.0
    running._intake_requested_at_wall = 9.8
    strong_track = TrackAngularExtent(
        global_id=41,
        center_deg=1.5,
        half_width_deg=6.0,
        last_seen_ts=10.0,
        hit_count=3,
        first_seen_ts=9.9,
    )

    running._registerNewIntakePiece([strong_track], now_wall=10.0, now_mono=20.0)

    assert transport.register_calls == [41]
    assert running._awaiting_intake_piece is False
    assert running._intake_requested_at_mono is None
    assert running._intake_requested_at_wall is None
    assert shared.classification_gate_calls[-1] == (False, "piece_in_hood")
    assert len(events.items) == 1


def test_running_seeds_recent_preview_from_live_track_thumb() -> None:
    transport = _Transport()
    shared = _Shared()
    event_queue = _EventQueue()
    stepper = _Stepper()

    class _Vision:
        def __init__(self) -> None:
            self.preview_calls: list[int] = []

        def getFeederTrackPreview(self, global_id: int) -> str | None:
            self.preview_calls.append(global_id)
            return "seeded-thumb-b64"

    vision = _Vision()
    running = Running(
        irl=SimpleNamespace(carousel_stepper=stepper),
        irl_config=SimpleNamespace(
            classification_channel_config=SimpleNamespace(
                intake_angle_deg=0.0,
                intake_body_half_width_deg=10.0,
                intake_guard_deg=28.0,
                drop_angle_deg=30.0,
                drop_tolerance_deg=14.0,
                point_of_no_return_deg=18.0,
                recognition_window_deg=60.0,
                max_zones=4,
                hood_dwell_ms=1200,
                min_carousel_crops_for_recognize=0,
                min_carousel_dwell_ms=0,
                min_carousel_traversal_deg=0.0,
                exit_release_overlap_ratio=0.5,
                exit_release_shimmy_amplitude_deg=1.5,
                exit_release_shimmy_cycles=2,
                exit_release_shimmy_microsteps_per_second=4200,
                exit_release_shimmy_acceleration_microsteps_per_second_sq=9000,
            ),
            feeder_config=SimpleNamespace(
                classification_channel_eject=SimpleNamespace(
                    steps_per_pulse=90,
                    microsteps_per_second=3400,
                    acceleration_microsteps_per_second_sq=2500,
                )
            ),
        ),
        gc=SimpleNamespace(
            logger=_Logger(),
            runtime_stats=_RuntimeStats(),
        ),
        shared=shared,
        transport=transport,
        vision=vision,
        event_queue=event_queue,
    )
    running._awaiting_intake_piece = True
    running._intake_requested_at_mono = 19.0
    running._intake_requested_at_wall = 9.8
    strong_track = TrackAngularExtent(
        global_id=41,
        center_deg=1.5,
        half_width_deg=6.0,
        last_seen_ts=10.0,
        hit_count=3,
        first_seen_ts=9.9,
    )

    running._registerNewIntakePiece([strong_track], now_wall=10.0, now_mono=20.0)

    assert vision.preview_calls == [41]
    assert len(event_queue.items) == 1
    assert event_queue.items[0].data.thumbnail == "seeded-thumb-b64"


def test_running_ignores_stale_track_that_predates_handoff_request() -> None:
    running, transport, shared, _events = _make_running()
    running._awaiting_intake_piece = True
    running._intake_requested_at_mono = 19.0
    running._intake_requested_at_wall = 10.0
    stale_track = TrackAngularExtent(
        global_id=41,
        center_deg=1.5,
        half_width_deg=6.0,
        last_seen_ts=10.5,
        hit_count=8,
        first_seen_ts=7.5,
    )

    running._registerNewIntakePiece([stale_track], now_wall=11.0, now_mono=20.0)

    assert transport.register_calls == []
    assert running._awaiting_intake_piece is True
    assert shared.classification_gate_calls == []


def test_running_recovers_existing_tracks_without_waiting_for_new_handoff() -> None:
    running, transport, shared, events = _make_running()
    old_track = TrackAngularExtent(
        global_id=52,
        center_deg=146.0,
        half_width_deg=8.0,
        last_seen_ts=20.0,
        hit_count=6,
        first_seen_ts=10.0,
    )

    running._recoverExistingTrackedPieces([old_track], now_wall=20.0)

    assert transport.register_calls == [52]
    assert len(transport.activePieces()) == 1
    assert shared.classification_gate_calls[-1] == (False, "recover_existing_piece")
    assert len(events.items) == 1


def test_running_does_not_recover_track_that_was_just_dropped() -> None:
    running, transport, shared, events = _make_running()
    transport._ignored_recovery_tracks.add(52)
    lingering_track = TrackAngularExtent(
        global_id=52,
        center_deg=146.0,
        half_width_deg=8.0,
        last_seen_ts=20.0,
        hit_count=6,
        first_seen_ts=10.0,
    )

    running._recoverExistingTrackedPieces([lingering_track], now_wall=20.0)

    assert transport.register_calls == []
    assert transport.activePieces() == []
    assert shared.classification_gate_calls == []
    assert events.items == []


def test_running_fires_recognition_for_oldest_pending_piece() -> None:
    running, transport, _shared, _events = _make_running()
    younger_piece = KnownObject(
        uuid="piece-younger",
        tracked_global_id=41,
        classification_status=ClassificationStatus.pending,
        created_at=0.0,
        carousel_detected_confirmed_at=5.0,
    )
    younger_piece.classification_channel_zone_center_deg = 180.0
    older_piece = KnownObject(
        uuid="piece-older",
        tracked_global_id=42,
        classification_status=ClassificationStatus.pending,
        created_at=0.0,
        carousel_detected_confirmed_at=1.0,
    )
    older_piece.classification_channel_zone_center_deg = 42.0
    transport._pieces_by_track = {41: younger_piece, 42: older_piece}
    fired: list[str] = []
    running._recognizer = SimpleNamespace(
        fire=lambda piece: fired.append(piece.uuid) or True
    )

    running._fireRecognition(now_wall=10.0)

    assert fired == ["piece-older"]
    assert older_piece.carousel_snapping_started_at == 10.0
    assert older_piece.carousel_snapping_completed_at == 10.0
    assert younger_piece.carousel_snapping_started_at is None


def _make_running_with_carousel_gate(
    *,
    min_carousel_crops_for_recognize: int,
    min_carousel_dwell_ms: int,
    min_carousel_traversal_deg: float = 0.0,
    vision=None,
) -> tuple[Running, _Transport, _Shared, _EventQueue]:
    transport = _Transport()
    shared = _Shared()
    event_queue = _EventQueue()
    stepper = _Stepper()
    running = Running(
        irl=SimpleNamespace(carousel_stepper=stepper),
        irl_config=SimpleNamespace(
            classification_channel_config=SimpleNamespace(
                intake_angle_deg=0.0,
                intake_body_half_width_deg=10.0,
                intake_guard_deg=28.0,
                drop_angle_deg=30.0,
                drop_tolerance_deg=14.0,
                point_of_no_return_deg=18.0,
                recognition_window_deg=60.0,
                max_zones=4,
                hood_dwell_ms=1200,
                min_carousel_crops_for_recognize=min_carousel_crops_for_recognize,
                min_carousel_dwell_ms=min_carousel_dwell_ms,
                min_carousel_traversal_deg=min_carousel_traversal_deg,
                exit_release_overlap_ratio=0.5,
                exit_release_shimmy_amplitude_deg=1.5,
                exit_release_shimmy_cycles=2,
                exit_release_shimmy_microsteps_per_second=4200,
                exit_release_shimmy_acceleration_microsteps_per_second_sq=9000,
            ),
            feeder_config=SimpleNamespace(
                classification_channel_eject=SimpleNamespace(
                    steps_per_pulse=90,
                    microsteps_per_second=3400,
                    acceleration_microsteps_per_second_sq=2500,
                )
            ),
        ),
        gc=SimpleNamespace(logger=_Logger(), runtime_stats=_RuntimeStats()),
        shared=shared,
        transport=transport,
        vision=vision,
        event_queue=event_queue,
    )
    return running, transport, shared, event_queue


def _make_pending_piece(
    *,
    uuid: str = "piece-carousel",
    tracked_global_id: int = 77,
    carousel_confirmed_at: float = 1.0,
    first_carousel_seen_ts: float | None = None,
    first_carousel_seen_angle_deg: float | None = None,
    current_zone_center_deg: float | None = None,
) -> KnownObject:
    piece = KnownObject(
        uuid=uuid,
        tracked_global_id=tracked_global_id,
        classification_status=ClassificationStatus.pending,
        created_at=0.0,
        carousel_detected_confirmed_at=carousel_confirmed_at,
    )
    piece.first_carousel_seen_ts = first_carousel_seen_ts
    piece.first_carousel_seen_angle_deg = first_carousel_seen_angle_deg
    piece.classification_channel_zone_center_deg = current_zone_center_deg
    return piece


class _StubRecognizer:
    def __init__(self, carousel_crop_count: int, fire_result: bool = True) -> None:
        self._carousel_crop_count = int(carousel_crop_count)
        self._fire_result = bool(fire_result)
        self.fire_calls: list[str] = []

    def countCarouselCrops(self, piece) -> int:
        return self._carousel_crop_count

    def fire(self, piece) -> bool:
        self.fire_calls.append(piece.uuid)
        return self._fire_result


def test_running_skips_recognition_when_carousel_crop_quota_unmet() -> None:
    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=2,
        min_carousel_dwell_ms=0,
    )
    piece = _make_pending_piece(first_carousel_seen_ts=1.0)
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=1)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == []
    counts = running.gc.runtime_stats.recognizer_counts
    assert counts.get("recognize_skipped_carousel_quota") == 1


def test_running_skips_recognition_when_carousel_dwell_not_elapsed() -> None:
    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=0,
        min_carousel_dwell_ms=500,
    )
    piece = _make_pending_piece(first_carousel_seen_ts=9.9)  # 100ms ago
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=4)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == []
    counts = running.gc.runtime_stats.recognizer_counts
    assert counts.get("recognize_skipped_carousel_dwell") == 1


def test_running_skips_recognition_when_piece_still_alive_on_c3() -> None:
    class _Vision:
        def __init__(self) -> None:
            self._live = {
                "c_channel_3": {77},
                "carousel": set(),
            }

        def getFeederTrackerLiveGlobalIds(self, role: str) -> set[int]:
            return set(self._live.get(role, set()))

    vision = _Vision()
    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=0,
        min_carousel_dwell_ms=0,
        vision=vision,
    )
    piece = _make_pending_piece(first_carousel_seen_ts=1.0)
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=3)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == []
    counts = running.gc.runtime_stats.recognizer_counts
    assert counts.get("recognize_skipped_not_on_carousel") == 1


def test_running_skips_recognition_when_carousel_traversal_unmet() -> None:
    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=0,
        min_carousel_dwell_ms=0,
        min_carousel_traversal_deg=60.0,
    )
    piece = _make_pending_piece(
        first_carousel_seen_ts=1.0,
        first_carousel_seen_angle_deg=100.0,
        current_zone_center_deg=120.0,  # only 20 deg of traversal
    )
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=4)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == []
    counts = running.gc.runtime_stats.recognizer_counts
    assert counts.get("recognize_skipped_carousel_traversal") == 1


def test_running_fires_recognition_when_carousel_traversal_sufficient() -> None:
    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=0,
        min_carousel_dwell_ms=0,
        min_carousel_traversal_deg=60.0,
    )
    piece = _make_pending_piece(
        first_carousel_seen_ts=1.0,
        first_carousel_seen_angle_deg=100.0,
        current_zone_center_deg=175.0,  # 75 deg of traversal
    )
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=4)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == [piece.uuid]
    counts = running.gc.runtime_stats.recognizer_counts
    assert counts.get("recognize_skipped_carousel_traversal") is None


def test_running_skips_traversal_gate_when_angle_unavailable() -> None:
    # Graceful-degradation case: no first-seen angle -> gate does not
    # block, bumping no traversal counter. Other gates still apply.
    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=0,
        min_carousel_dwell_ms=0,
        min_carousel_traversal_deg=60.0,
    )
    piece = _make_pending_piece(
        first_carousel_seen_ts=1.0,
        first_carousel_seen_angle_deg=None,
        current_zone_center_deg=175.0,
    )
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=4)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == [piece.uuid]
    counts = running.gc.runtime_stats.recognizer_counts
    assert counts.get("recognize_skipped_carousel_traversal") is None


def test_running_fires_recognition_when_carousel_gate_clears() -> None:
    class _Vision:
        def getFeederTrackerLiveGlobalIds(self, role: str) -> set[int]:
            # c_channel_3 track has died; carousel is live -> handoff done.
            return {77} if role == "carousel" else set()

    running, transport, _shared, _events = _make_running_with_carousel_gate(
        min_carousel_crops_for_recognize=2,
        min_carousel_dwell_ms=300,
        vision=_Vision(),
    )
    piece = _make_pending_piece(first_carousel_seen_ts=9.0)  # 1s of dwell
    transport._pieces_by_track = {piece.tracked_global_id: piece}
    recognizer = _StubRecognizer(carousel_crop_count=2)
    running._recognizer = recognizer

    running._fireRecognition(now_wall=10.0)

    assert recognizer.fire_calls == [piece.uuid]
    assert piece.carousel_snapping_completed_at == 10.0


def test_drop_body_overlap_ratio_is_high_when_piece_is_mostly_in_drop_window() -> None:
    running, _transport, _shared, _events = _make_running()
    piece = KnownObject()
    piece.classification_channel_zone_center_deg = 34.0
    piece.classification_channel_zone_half_width_deg = 12.0

    ratio = running._dropBodyOverlapRatio(piece)

    assert ratio > 0.5


def test_start_exit_release_shimmy_builds_small_returning_motion_plan() -> None:
    running, transport, _shared, _events = _make_running()
    piece = KnownObject(
        uuid="piece-drop",
        tracked_global_id=99,
        classification_status=ClassificationStatus.classified,
    )
    piece.classification_channel_zone_center_deg = 30.0
    piece.classification_channel_zone_half_width_deg = 12.0
    transport._pieces_by_track = {99: piece}

    started = running._startExitReleaseShimmyIfNeeded(piece.uuid)

    assert started is True
    assert running.irl.carousel_stepper.moves[:1] == [-1.5]
    assert running._exit_release_drop_uuid == piece.uuid
    assert running._exit_release_plan_deg == [3.0, -1.5, -1.5, 3.0, -1.5]
