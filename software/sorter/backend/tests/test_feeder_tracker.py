"""Unit tests for the polar feeder tracker + cross-camera handoff."""

from __future__ import annotations

from vision.tracking import (
    PieceHandoffManager,
    PolarFeederTracker,
    build_feeder_tracker_system,
)


def _bbox_around(cx: float, cy: float, size: int = 40) -> tuple[int, int, int, int]:
    half = size // 2
    return (int(cx - half), int(cy - half), int(cx + half), int(cy + half))


def _make_single_tracker(
    role: str = "c_channel_2",
    *,
    score_threshold: float = 0.1,
    pixel_fallback_distance_px: float = 200.0,
    coast_limit_ticks: int = 5,
    stagnant_false_track_max_age_s: float = 3.0,
) -> tuple[PolarFeederTracker, PieceHandoffManager]:
    manager = PieceHandoffManager(handoff_chain={})
    tracker = PolarFeederTracker(
        role=role,
        handoff_manager=manager,
        pixel_fallback_distance_px=pixel_fallback_distance_px,
        detection_score_threshold=score_threshold,
        coast_limit_ticks=coast_limit_ticks,
        stagnant_false_track_max_age_s=stagnant_false_track_max_age_s,
    )
    return tracker, manager


# ---------------------------------------------------------------------------
# Core per-camera behavior
# ---------------------------------------------------------------------------


def test_stable_id_linear_motion():
    tracker, _ = _make_single_tracker()
    ids_seen: set[int] = set()
    velocities: list[tuple[float, float]] = []
    for i in range(10):
        cx = 100.0 + i * 30.0
        cy = 200.0
        ts = i * 0.2
        tracks = tracker.update([_bbox_around(cx, cy, size=60)], [0.9], ts)
        if not tracks:
            continue
        ids_seen.add(tracks[0].global_id)
        velocities.append(tracks[0].velocity_px_per_s)
    assert len(ids_seen) == 1, f"expected one stable id, saw {ids_seen}"
    # Final velocity should roughly match 30 px / 0.2 s = 150 px/s on x, ~0 on y.
    vx_final, vy_final = velocities[-1]
    assert 100.0 <= vx_final <= 200.0, f"vx expected ~150, got {vx_final}"
    assert abs(vy_final) < 20.0, f"vy expected ~0, got {vy_final}"


def test_paths_crossing_preserves_ids():
    tracker, _ = _make_single_tracker()
    ticks = []
    for i in range(8):
        ts = i * 0.2
        a = _bbox_around(100.0 + i * 15.0, 200.0, size=60)
        b = _bbox_around(100.0 + i * 15.0, 400.0, size=60)
        tracks = tracker.update([a, b], [0.9, 0.9], ts)
        if len(tracks) != 2:
            continue
        ticks.append(sorted(t.global_id for t in tracks))
    # Once both tracks have stabilised, the id pair should stay consistent.
    assert len(ticks) >= 4, f"expected tracker to lock on — got {ticks}"
    assert all(pair == ticks[-1] for pair in ticks[-4:]), ticks


def test_detection_dropout_coasts_and_reassociates():
    tracker, _ = _make_single_tracker()

    # Warm-up frames so track is established.
    for i in range(3):
        tracker.update([_bbox_around(100.0 + i * 30.0, 200.0, size=60)], [0.9], i * 0.2)

    # Dropout tick — no detections. Track should coast in the lost buffer.
    dropout = tracker.update([], [], 0.6)
    assert len(dropout) == 1, "track should coast, not disappear"
    assert dropout[0].coasting is True
    dropout_id = dropout[0].global_id

    # Recover — piece reappears on the predicted trajectory.
    recover = tracker.update([_bbox_around(220.0, 200.0, size=60)], [0.9], 0.8)
    assert len(recover) == 1
    assert recover[0].global_id == dropout_id, "id should persist across dropout"
    assert recover[0].coasting is False


def test_reset_clears_ids():
    tracker, _ = _make_single_tracker()
    tracker.update([_bbox_around(100.0, 200.0, size=60)], [0.9], 0.0)
    tracker.reset()
    new = tracker.update([_bbox_around(300.0, 400.0, size=60)], [0.9], 0.2)
    assert len(new) == 1
    assert new[0].global_id >= 1


def test_score_threshold_filters_low():
    tracker, _ = _make_single_tracker(score_threshold=0.5)
    tracks = tracker.update([_bbox_around(100.0, 200.0, size=60)], [0.2], 0.0)
    assert tracks == []


def test_stagnant_false_track_is_ignored_after_grace_period():
    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
    )

    last_tracks = []
    for i in range(8):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], ts)

    assert last_tracks == [], "static false detection should be ignored after aging out"

    suppressed = tracker.update([_bbox_around(202.0, 242.0, size=60)], [0.9], 1.8)
    assert suppressed == [], "ignored static region should suppress immediate re-spawn"


def test_real_track_survives_later_pause_once_motion_was_confirmed():
    tracker, _ = _make_single_tracker(stagnant_false_track_max_age_s=1.0)

    moving_points = [100.0, 116.0, 134.0, 156.0]
    last_tracks = []
    for i, cx in enumerate(moving_points):
        last_tracks = tracker.update([_bbox_around(cx, 200.0, size=60)], [0.9], i * 0.2)
    assert len(last_tracks) == 1

    paused_tracks = []
    for j in range(4, 11):
        paused_tracks = tracker.update([_bbox_around(156.0, 200.0, size=60)], [0.9], j * 0.2)

    assert len(paused_tracks) == 1, "legit track should remain after later pause"


def test_stagnant_filter_is_not_applied_to_c_channel_3():
    tracker, _ = _make_single_tracker(
        role="c_channel_3",
        stagnant_false_track_max_age_s=1.0,
    )

    last_tracks = []
    for i in range(8):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], ts)

    assert len(last_tracks) == 1, "stagnant suppression should stay scoped off c_channel_3"


def test_stagnant_filter_skips_handoff_tracks_on_classification_channel():
    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
    )

    tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], 0.0)
    internal_track = next(iter(tracker._tracks.values()))
    internal_track.handoff_from = "c_channel_3"

    last_tracks = []
    for i in range(1, 8):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], ts)

    assert len(last_tracks) == 1, "handoff-backed classification track should not be suppressed"


# ---------------------------------------------------------------------------
# Handoff semantics
# ---------------------------------------------------------------------------


def _make_two_camera_system():
    manager, trackers, _history = build_feeder_tracker_system(
        roles=("c_channel_2", "c_channel_3"),
        handoff_window_s=2.0,
        frame_rate=5,
    )
    # Zones: c_channel_2 exit = right half (x > 600), c_channel_3 entry = left half (x < 200).
    manager.set_zones(
        "c_channel_2",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    manager.set_zones(
        "c_channel_3",
        entry_polygon=[(0, 0), (200, 0), (200, 720), (0, 720)],
    )
    return manager, trackers


def _feed_until_dead(tracker, role: str, start_ts: float, max_ticks: int = 60) -> float:
    """Tick the tracker with empty detections until it stops reporting tracks."""
    ts = start_ts
    for _ in range(max_ticks):
        ts += 0.2
        tracks = tracker.update([], [], ts)
        if not tracks:
            return ts
    return ts


def test_handoff_c2_to_c3_inherits_global_id():
    manager, trackers = _make_two_camera_system()
    c2 = trackers["c_channel_2"]
    c3 = trackers["c_channel_3"]

    # Tick 1: piece near the exit zone on c_channel_2.
    t1 = c2.update([_bbox_around(700.0, 360.0, size=60)], [0.9], 0.0)
    assert len(t1) == 1
    original_id = t1[0].global_id

    # Let the track die by feeding c2 empty frames.
    death_ts = _feed_until_dead(c2, "c_channel_2", start_ts=0.0)
    # Piece should now be pending in the handoff manager.
    pending = manager.pending_snapshot()
    assert len(pending) == 1, pending
    assert pending[0]["global_id"] == original_id

    # Tick shortly after: the piece appears on c_channel_3's entry zone.
    new_tracks = c3.update(
        [_bbox_around(100.0, 360.0, size=60)],
        [0.9],
        death_ts + 0.2,
    )
    assert len(new_tracks) == 1
    assert new_tracks[0].global_id == original_id
    assert new_tracks[0].handoff_from == "c_channel_2"


def test_handoff_expires_after_window():
    manager, trackers = _make_two_camera_system()
    c2 = trackers["c_channel_2"]
    c3 = trackers["c_channel_3"]

    c2.update([_bbox_around(700.0, 360.0, size=60)], [0.9], 0.0)
    death_ts = _feed_until_dead(c2, "c_channel_2", start_ts=0.0)
    original_id = manager.pending_snapshot()[0]["global_id"]

    # New detection on c_channel_3 AFTER the handoff window.
    too_late_ts = death_ts + 2.0 + 0.5
    fresh = c3.update([_bbox_around(100.0, 360.0, size=60)], [0.9], too_late_ts)
    assert len(fresh) == 1
    assert fresh[0].global_id != original_id
    assert fresh[0].handoff_from is None


def test_handoff_fifo_matches_multiple_pending():
    manager, trackers = _make_two_camera_system()
    c2 = trackers["c_channel_2"]
    c3 = trackers["c_channel_3"]

    # Two pieces on c_channel_2, then let both die.
    c2.update(
        [_bbox_around(700.0, 300.0, size=60), _bbox_around(800.0, 400.0, size=60)],
        [0.9, 0.9],
        0.0,
    )
    _feed_until_dead(c2, "c_channel_2", start_ts=0.0)
    pending = manager.pending_snapshot()
    assert len(pending) == 2
    first_pending_id = pending[0]["global_id"]
    second_pending_id = pending[1]["global_id"]

    # First new arrival on c_channel_3.
    first = c3.update([_bbox_around(100.0, 360.0, size=60)], [0.9], 2.6)
    assert first[0].global_id == first_pending_id

    # Second new arrival on c_channel_3 — spaced far enough that ByteTrack
    # won't merge the new bbox with the already-tracked first one. ByteTrack
    # needs one extra tick to activate a newly-seen detection, so we feed
    # it two frames before asserting.
    second_bboxes = [
        _bbox_around(100.0, 300.0, size=60),
        _bbox_around(160.0, 500.0, size=60),
    ]
    c3.update(second_bboxes, [0.9, 0.9], 2.8)
    second = c3.update(second_bboxes, [0.9, 0.9], 3.0)
    second_ids = {t.global_id for t in second}
    assert first_pending_id in second_ids
    assert second_pending_id in second_ids
