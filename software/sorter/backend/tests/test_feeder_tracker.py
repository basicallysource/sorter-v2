"""Unit tests for the polar feeder tracker + cross-camera handoff."""

from __future__ import annotations

import numpy as np

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


def test_force_kill_track_releases_global_id():
    """force_kill_track must remove the track immediately so a subsequent
    detection at the same position gets a fresh global_id — modelling the
    'piece dropped through the chute → next piece in this sector must NOT
    inherit the dropped piece's identity' guarantee.
    """
    tracker, _ = _make_single_tracker()
    tracks = tracker.update([_bbox_around(100.0, 200.0, size=60)], [0.9], 0.0)
    assert len(tracks) == 1
    dropped_id = tracks[0].global_id

    killed = tracker.force_kill_track(dropped_id)
    assert killed is True

    # Same sector position one tick later — must NOT inherit dropped_id.
    after = tracker.update([_bbox_around(100.0, 200.0, size=60)], [0.9], 0.2)
    assert len(after) == 1
    assert after[0].global_id != dropped_id, (
        "force-killed track must not be re-acquired by a fresh detection"
    )


def test_force_kill_track_returns_false_for_unknown_global_id():
    tracker, _ = _make_single_tracker()
    tracker.update([_bbox_around(100.0, 200.0, size=60)], [0.9], 0.0)
    assert tracker.force_kill_track(global_id=999999) is False


# ---------------------------------------------------------------------------
# Phase 2: sector-anchored identity on the C4 platter
# ---------------------------------------------------------------------------


def _make_carousel_tracker() -> PolarFeederTracker:
    """Carousel tracker with 5-sector geometry and sector-anchoring on,
    mirroring the production wiring."""
    manager = PieceHandoffManager(handoff_chain={})
    tracker = PolarFeederTracker(
        role="carousel",
        handoff_manager=manager,
        detection_score_threshold=0.1,
        coast_limit_ticks=20,
        enable_stagnant_false_track_filter=False,
        enable_sector_anchoring=True,
    )
    # 5 physical sectors of 72° each, centered at (500, 500).
    tracker.set_channel_geometry((500.0, 500.0), 80.0, 300.0, sector_count=5)
    return tracker


def _point_on_circle(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    import math as _math
    a = _math.radians(angle_deg)
    return (cx + r * _math.cos(a), cy + r * _math.sin(a))


def test_sector_anchoring_rejects_jump_more_than_one_sector():
    """A new detection more than one sector away from the only existing
    track must not be picked up as that track's continuation. Without
    sector anchoring the polar tracker could bridge the gap and silently
    swap identities; sector anchoring is the structural defense that
    keeps the identity tied to the physical wall geometry.

    The polar angular gate (default 45°) already catches large jumps in
    this isolated setup, so the sector-jump counter may not fire; what
    matters here is the behavioural guarantee: id is not transferred.
    """
    tracker = _make_carousel_tracker()
    # Born in sector 0 (angle ≈ 0°).
    cx0, cy0 = _point_on_circle(500.0, 500.0, 200.0, 0.0)
    first = tracker.update([_bbox_around(cx0, cy0, size=60)], [0.9], 0.0)
    assert len(first) == 1
    gid = first[0].global_id

    # 144° away → that's 2 sectors at 72° each.
    cx2, cy2 = _point_on_circle(500.0, 500.0, 200.0, 144.0)
    second = tracker.update([_bbox_around(cx2, cy2, size=60)], [0.9], 0.2)
    new_ids = [t.global_id for t in second if not t.coasting]
    assert gid not in new_ids, "two-sector jump must not inherit identity"


def test_sector_anchoring_rejects_new_track_in_occupied_sector():
    """A second detection in the same sector as an existing track must
    not spawn a duplicate ID — the physical walls forbid two pieces in
    one sector."""
    tracker = _make_carousel_tracker()
    cx0, cy0 = _point_on_circle(500.0, 500.0, 200.0, 0.0)
    tracker.update([_bbox_around(cx0, cy0, size=60)], [0.9], 0.0)

    # A second piece 10° away — clearly still in sector 0 (sector width 72°)
    # but far enough that the polar match cost would otherwise allow a
    # separate detection.
    cx1, cy1 = _point_on_circle(500.0, 500.0, 200.0, 10.0)
    second = tracker.update(
        [_bbox_around(cx0, cy0, size=60), _bbox_around(cx1, cy1, size=60)],
        [0.9, 0.9],
        0.2,
    )
    # Only one track survives — the duplicate detection was rejected.
    live = [t for t in second if not t.coasting]
    assert len(live) == 1
    assert tracker._sector_anchoring_rejected_occupied >= 1


def test_sector_anchoring_rejects_multi_sector_bbox():
    """A YOLO bbox whose angular span exceeds one sector is treated as a
    multi-piece merge artifact and dropped before tracking."""
    tracker = _make_carousel_tracker()
    # Bbox spanning roughly 130° angular — that's well over one 72° sector.
    # Construct it as a tangent-spanning rectangle around the rim.
    # Center is (500, 500); rim at r=200. A bbox from (-200, -200)..(200, 50)
    # covers angles from roughly -135° to +135°.
    big_bbox = (300, 300, 700, 550)
    tracks = tracker.update([big_bbox], [0.9], 0.0)
    assert tracks == [], "multi-sector bbox must be rejected"
    assert tracker._sector_anchoring_rejected_multipiece >= 1


def test_sector_anchoring_counter_fires_when_polar_gate_would_allow_jump():
    """Direct test that the sector-jump rejection is what kills the
    cross-sector match, not just the polar gate. Build a tracker with a
    wide polar gate (135°) so the polar cost alone would not reject a
    two-sector hop, and verify the sector rule does the work.
    """
    manager = PieceHandoffManager(handoff_chain={})
    tracker = PolarFeederTracker(
        role="carousel",
        handoff_manager=manager,
        max_angular_step_deg=135.0,
        max_radial_step_px=200.0,
        detection_score_threshold=0.1,
        coast_limit_ticks=20,
        enable_stagnant_false_track_filter=False,
        enable_sector_anchoring=True,
    )
    tracker.set_channel_geometry((500.0, 500.0), 80.0, 300.0, sector_count=5)

    cx0, cy0 = _point_on_circle(500.0, 500.0, 200.0, 0.0)
    first = tracker.update([_bbox_around(cx0, cy0, size=60)], [0.9], 0.0)
    gid = first[0].global_id

    # 130° away → still within the 135° polar gate, but more than one
    # 72° sector away. Sector rule must reject the bind.
    cx2, cy2 = _point_on_circle(500.0, 500.0, 200.0, 130.0)
    second = tracker.update([_bbox_around(cx2, cy2, size=60)], [0.9], 0.2)
    new_ids = [t.global_id for t in second if not t.coasting]
    assert gid not in new_ids
    assert tracker._sector_anchoring_rejected_jump >= 1


def test_sector_anchoring_allows_normal_motion_within_one_sector():
    """Sanity: a piece moving slightly within its sector must still bind
    to the same track. The sector constraint is ±1, not ==0."""
    tracker = _make_carousel_tracker()
    cx0, cy0 = _point_on_circle(500.0, 500.0, 200.0, 0.0)
    first = tracker.update([_bbox_around(cx0, cy0, size=60)], [0.9], 0.0)
    gid = first[0].global_id

    # Move 20° (still in sector 0 — sector boundary at 36°/-36° given
    # 72° width centered on world angle origin).
    cx1, cy1 = _point_on_circle(500.0, 500.0, 200.0, 20.0)
    second = tracker.update([_bbox_around(cx1, cy1, size=60)], [0.9], 0.2)
    live = [t for t in second if not t.coasting]
    assert len(live) == 1
    assert live[0].global_id == gid


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


def test_polar_ghost_suppression_releases_when_object_moves_along_arc():
    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
    )
    tracker.set_channel_geometry((200.0, 200.0), 40.0, 120.0)

    last_tracks = []
    for i in range(8):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(280.0, 200.0, size=40)], [0.9], ts)
    assert last_tracks == []

    # Still essentially the same polar position -> remain suppressed.
    suppressed = tracker.update([_bbox_around(278.0, 205.0, size=40)], [0.9], 1.8)
    assert suppressed == []

    # Move along the arc by ~10 degrees while staying within the broad
    # cartesian suppression radius. That should revive the track because the
    # object is no longer stationary in polar space.
    revived = tracker.update([_bbox_around(279.0, 214.0, size=40)], [0.9], 2.0)
    assert len(revived) == 1


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


def test_split_feeder_system_filters_long_lived_c3_static_ghosts():
    _manager, trackers, _history = build_feeder_tracker_system(
        roles=("c_channel_2", "c_channel_3", "carousel"),
        handoff_window_s=2.0,
        frame_rate=5,
    )
    tracker = trackers["c_channel_3"]

    last_tracks = []
    for i in range(40):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], ts)

    assert last_tracks == [], "split-feeder c_channel_3 ghost should age out"


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


def test_pending_drop_exempts_stagnant_track_from_kill(monkeypatch):
    """A piece physically parked at the drop zone (e.g. waiting for
    distribution_ready) must not be culled by the stagnant filter once the
    state machine has marked it as pending drop — otherwise
    live_global_ids("carousel") drops the id mid-wait and the drop handoff
    breaks."""
    import vision.tracking.polar_tracker as pt_module

    fake_now = [1000.0]
    monkeypatch.setattr(pt_module.time, "time", lambda: fake_now[0])

    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.5,
    )

    # Bring a track into existence at t=0.0.
    first = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], 0.0)
    assert len(first) == 1
    gid = first[0].global_id

    # State machine commits the piece to drop — align fake wall clock with
    # tracker timeline so the 4s protection maps cleanly onto tracker ts.
    fake_now[0] = 0.0
    tracker.mark_pending_drop(gid)

    last_tracks = []
    for i in range(1, 10):
        ts = i * 0.2  # crosses max_age_s=1.5s by tick 8
        last_tracks = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], ts)

    assert len(last_tracks) == 1, (
        "pending-drop-pinned track must survive the stagnant-false-track filter"
    )
    assert last_tracks[0].global_id == gid


def test_pending_drop_protection_expires(monkeypatch):
    """Protection is time-bounded — once ``protect_for_s`` elapses, the track
    goes back to normal stagnant-filter treatment."""
    import vision.tracking.polar_tracker as pt_module

    fake_now = [0.0]
    monkeypatch.setattr(pt_module.time, "time", lambda: fake_now[0])

    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
    )

    first = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], 0.0)
    assert len(first) == 1
    gid = first[0].global_id

    # Short protection window — shorter than the time we'll stay static for.
    tracker.mark_pending_drop(gid, protect_for_s=0.5)

    last_tracks = []
    for i in range(1, 12):
        ts = i * 0.2  # well past both 0.5s protection and 1.0s max_age
        last_tracks = tracker.update([_bbox_around(200.0, 240.0, size=60)], [0.9], ts)

    assert last_tracks == [], (
        "expired pending-drop protection should fall back to normal stagnant culling"
    )


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


def test_c2_handoff_disabled_fresh_id_on_c3():
    """C2 clumps too much — the c_channel_2 → c_channel_3 handoff edge was
    removed (user decision). A piece that dies in C2's exit zone must NOT
    queue a pending handoff, and a downstream C3 birth must get a fresh
    ``global_id`` instead of inheriting from C2.
    """
    manager, trackers = _make_two_camera_system()
    c2 = trackers["c_channel_2"]
    c3 = trackers["c_channel_3"]

    # Tick 1: piece near the exit zone on c_channel_2.
    t1 = c2.update([_bbox_around(700.0, 360.0, size=60)], [0.9], 0.0)
    assert len(t1) == 1
    original_id = t1[0].global_id

    # Let the track die by feeding c2 empty frames.
    death_ts = _feed_until_dead(c2, "c_channel_2", start_ts=0.0)
    # No pending handoff should be queued — C2 is no longer an upstream.
    assert manager.pending_snapshot() == []

    # Tick shortly after: the piece appears on c_channel_3's entry zone.
    # It must get a fresh id, NOT inherit from c_channel_2.
    new_tracks = c3.update(
        [_bbox_around(100.0, 360.0, size=60)],
        [0.9],
        death_ts + 0.2,
    )
    assert len(new_tracks) == 1
    assert new_tracks[0].global_id != original_id
    assert new_tracks[0].handoff_from is None


def test_handoff_notifies_exit_observer_when_track_dies_in_exit_zone():
    seen: list[dict] = []
    manager = PieceHandoffManager(
        handoff_chain={"c_channel_2": "c_channel_3"},
        exit_observer=lambda **payload: seen.append(payload),
    )
    manager.set_zones(
        "c_channel_2",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )

    manager.notify_track_death(
        "c_channel_2",
        42,
        (700.0, 360.0),
        1.0,
        death_ts=1.4,
    )

    assert len(seen) == 1
    assert seen[0]["channel"] == "c_channel_2"
    assert seen[0]["global_id"] == 42
    assert seen[0]["exited_at"] == 1.4


# NOTE: the former c2→c3 window-expiry and FIFO tests were deleted — the
# C2→C3 handoff edge is gone entirely (user decision: C2 clumping made the
# cross-camera identity transfer unreliable). The equivalent behaviours are
# still validated on the C3→carousel edge in test_c3_to_c4_handoff.py.


# ---------------------------------------------------------------------------
# Cross-camera ghost-track rejection
# ---------------------------------------------------------------------------


def test_handoff_rejects_stationary_ghost_claim_at_same_pixel():
    """A stationary C2 detection that dies in the exit zone must not hand its
    global_id to a C3 track born at the same pixel position — that is almost
    certainly the same static detector artefact, not a real piece in motion.
    """
    rejects: list[dict] = []
    manager = PieceHandoffManager(
        handoff_chain={"c_channel_2": "c_channel_3"},
        handoff_window_s=6.0,
        ghost_reject_radius_px=25.0,
        ghost_stationary_threshold_px=8.0,
        ghost_reject_observer=lambda **payload: rejects.append(payload),
    )
    manager.set_zones(
        "c_channel_2",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    # C3's entry zone covers the ghost pixel so the claim actually reaches
    # the pending queue — the reject check is what must short-circuit it.
    manager.set_zones(
        "c_channel_3",
        entry_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )

    ghost_center = (700.0, 360.0)
    # Seed a fresh id for the ghost, then kill it with ~zero displacement.
    ghost_id, _ = manager.register_track("c_channel_2", ghost_center, 0.0)
    manager.notify_track_death(
        "c_channel_2",
        ghost_id,
        ghost_center,
        last_seen_ts=1.0,
        death_ts=1.2,
        last_displacement_px=2.0,  # well under the 8 px stationary threshold
    )
    assert len(manager.pending_snapshot()) == 1

    # Shortly after: a C3 detection pops up at essentially the same pixel.
    new_id, handoff_from = manager.register_track(
        "c_channel_3",
        (702.0, 361.0),  # ~2 px away, inside the 25 px reject radius
        1.4,
    )

    assert handoff_from is None, "stationary ghost must not transfer global_id"
    assert new_id != ghost_id
    # Pending should be drained so it cannot block future real claims.
    assert manager.pending_snapshot() == []
    # Counter + observer both fired exactly once.
    assert manager.ghost_rejected_total == 1
    assert len(rejects) == 1
    assert rejects[0]["ghost_global_id"] == ghost_id


def test_handoff_accepts_moving_track_even_at_similar_pixel():
    """The reject gate must only fire for stationary ghosts — a track that
    actually moved must still hand off, even if the downstream rebirth lands
    close to its last observed center.
    """
    manager = PieceHandoffManager(
        handoff_chain={"c_channel_2": "c_channel_3"},
        handoff_window_s=6.0,
    )
    manager.set_zones(
        "c_channel_2",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    manager.set_zones(
        "c_channel_3",
        entry_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )

    real_id, _ = manager.register_track("c_channel_2", (620.0, 360.0), 0.0)
    manager.notify_track_death(
        "c_channel_2",
        real_id,
        (700.0, 360.0),
        last_seen_ts=1.0,
        death_ts=1.2,
        last_displacement_px=80.0,  # clearly moving
    )

    new_id, handoff_from = manager.register_track(
        "c_channel_3",
        (702.0, 361.0),
        1.4,
    )

    assert handoff_from == "c_channel_2"
    assert new_id == real_id
    assert manager.ghost_rejected_total == 0
