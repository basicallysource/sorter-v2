"""Unit tests for the polar feeder tracker + cross-camera handoff."""

from __future__ import annotations

import numpy as np

from vision.tracking import (
    PieceHandoffManager,
    PolarFeederTracker,
    build_feeder_tracker_system,
)
from vision.tracking.history import SectorSnapshot


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
    persist_static_ghost_regions: bool = False,
) -> tuple[PolarFeederTracker, PieceHandoffManager]:
    manager = PieceHandoffManager(handoff_chain={})
    tracker = PolarFeederTracker(
        role=role,
        handoff_manager=manager,
        pixel_fallback_distance_px=pixel_fallback_distance_px,
        detection_score_threshold=score_threshold,
        coast_limit_ticks=coast_limit_ticks,
        stagnant_false_track_max_age_s=stagnant_false_track_max_age_s,
        persist_static_ghost_regions=persist_static_ghost_regions,
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


def test_persistent_stagnant_ghost_regions_survive_restart_and_clear_on_revival(
    tmp_path,
    monkeypatch,
):
    machine_params = tmp_path / "machine_params.toml"
    machine_params.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(machine_params))

    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
        persist_static_ghost_regions=True,
    )
    tracker.set_channel_geometry((200.0, 200.0), 40.0, 120.0)

    last_tracks = []
    for i in range(8):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(280.0, 200.0, size=40)], [0.9], ts)
    assert last_tracks == []

    reloaded, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
        persist_static_ghost_regions=True,
    )
    reloaded.set_channel_geometry((200.0, 200.0), 40.0, 120.0)

    suppressed = reloaded.update([_bbox_around(280.0, 200.0, size=40)], [0.9], 0.0)
    assert suppressed == []

    revived = reloaded.update([_bbox_around(279.0, 214.0, size=40)], [0.9], 0.2)
    assert len(revived) == 1


def test_carousel_jitter_ghost_is_suppressed_even_after_accumulating_path_length():
    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
    )
    tracker.set_channel_geometry((200.0, 200.0), 40.0, 120.0)

    # Fixed structure with a jumpy detector center: enough historical travel
    # to look "motion confirmed" if we only trust path length, but its recent
    # polar position stays essentially fixed.
    centers = [
        (280.0, 200.0),
        (292.0, 206.0),
        (272.0, 197.0),
        (288.0, 204.0),
        (281.0, 201.0),
        (280.0, 200.0),
        (281.0, 200.0),
        (279.0, 199.0),
        (280.0, 200.0),
    ]
    last_tracks = []
    for i, (cx, cy) in enumerate(centers):
        ts = i * 0.2
        last_tracks = tracker.update([_bbox_around(cx, cy, size=40)], [0.9], ts)

    assert last_tracks == [], (
        "recently-stationary carousel ghost should age out even if jitter "
        "previously accumulated enough path length to look mobile"
    )


def test_large_carousel_ghost_region_expands_suppression_radius():
    tracker, _ = _make_single_tracker(
        role="carousel",
        stagnant_false_track_max_age_s=1.0,
    )
    tracker.set_channel_geometry((200.0, 200.0), 40.0, 140.0)

    # A large static guide-like box should create a suppression region larger
    # than the fixed default radius so later center jumps along the same
    # structure still merge into one persistent ghost.
    for i in range(8):
        ts = i * 0.2
        tracker.update([_bbox_around(280.0, 220.0, size=120)], [0.9], ts)

    regions = tracker.get_ignored_static_regions(timestamp=1.6)
    assert len(regions) == 1
    assert regions[0]["radius_px"] > 56.0


def test_live_piece_crop_prefers_latest_real_crop_over_composite_thumb():
    tracker, _ = _make_single_tracker(role="carousel")
    first = tracker.update([_bbox_around(280.0, 200.0, size=40)], [0.9], 0.0)
    assert len(first) == 1
    gid = first[0].global_id
    track = next(iter(tracker._tracks.values()))
    track.thumb_jpeg_b64 = "composite-thumb"
    track.sector_snapshots = [
        SectorSnapshot(
            sector_index=1,
            start_angle_deg=10.0,
            end_angle_deg=20.0,
            captured_ts=1.0,
            bbox_x=0,
            bbox_y=0,
            width=10,
            height=10,
            jpeg_b64="sector-1",
            piece_jpeg_b64="crop-older",
        ),
        SectorSnapshot(
            sector_index=2,
            start_angle_deg=20.0,
            end_angle_deg=30.0,
            captured_ts=2.0,
            bbox_x=0,
            bbox_y=0,
            width=10,
            height=10,
            jpeg_b64="sector-2",
            piece_jpeg_b64="crop-latest",
        ),
    ]

    assert tracker.get_live_piece_crop(gid) == "crop-latest"
    assert tracker.get_live_thumb(gid) == "composite-thumb"


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


# ---------------------------------------------------------------------------
# Appearance-gate safety (id-switch regression guard)
# ---------------------------------------------------------------------------


def _unit_vec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(32).astype(np.float32)
    return v / float(np.linalg.norm(v))


def _seed_track_with_embedding(
    tracker: PolarFeederTracker,
    *,
    start: tuple[float, float],
    embedding: np.ndarray,
) -> int:
    """Place a track at ``start`` and manually stamp its embedding."""
    tracks = tracker.update([_bbox_around(*start, size=40)], [0.9], 0.0)
    assert tracks, "seed frame should produce a track"
    gid = tracks[0].global_id
    live = next(t for t in tracker._tracks.values() if t.global_id == gid)
    live.embedding = embedding.copy()
    return gid


class _FixedEmbedder:
    """Stub BoxMOT embedder that returns a caller-supplied matrix.

    Used in tracker tests so we can precisely control what the tracker
    sees on each tick without touching the real BoxMOT model.
    """

    def __init__(self, vec: np.ndarray | None) -> None:
        self._vec = vec

    def extract(self, _frame, bboxes):
        if self._vec is None or not bboxes:
            return None
        return np.stack([self._vec for _ in bboxes]).astype(np.float32)


def test_missing_detection_embedding_allows_tight_geometric_match():
    """Track has an embedding, detection yields no embedding this tick, and
    the two are geometrically very close — should still match."""
    tracker, _ = _make_single_tracker()
    # Embedder is running, but returns "no row" (as if bbox was degenerate).
    tracker._embedder = _FixedEmbedder(None)  # type: ignore[attr-defined]
    emb = _unit_vec(1)
    gid = _seed_track_with_embedding(tracker, start=(200.0, 200.0), embedding=emb)
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Detection 6 px away -> geom_cost = 0.03, well under 0.25.
    tracks = tracker.update(
        [_bbox_around(206.0, 200.0, size=40)], [0.9], 0.2, frame_bgr=fake_frame,
    )
    assert len(tracks) == 1
    assert tracks[0].global_id == gid


def test_missing_detection_embedding_rejects_loose_geometric_match():
    """Track has an embedding, detection yields no embedding this tick, and
    the two are far apart — must NOT inherit the id."""
    tracker, _ = _make_single_tracker(pixel_fallback_distance_px=200.0)
    tracker._embedder = _FixedEmbedder(None)  # type: ignore[attr-defined]
    emb = _unit_vec(2)
    gid = _seed_track_with_embedding(tracker, start=(200.0, 200.0), embedding=emb)
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Detection 120 px away -> geom_cost = 0.6 > 0.25 strict threshold.
    tracks = tracker.update(
        [_bbox_around(320.0, 200.0, size=40)], [0.9], 0.2, frame_bgr=fake_frame,
    )
    assert len(tracks) == 2, "expect old track coasting + new track"
    new_track = next(t for t in tracks if not t.coasting)
    assert new_track.global_id != gid


def test_low_cosine_similarity_rejects_even_with_close_geometry():
    tracker, _ = _make_single_tracker()
    emb_a = _unit_vec(10)
    emb_b = -emb_a  # cosine similarity = -1, well below the 0.55 gate.
    gid = _seed_track_with_embedding(tracker, start=(200.0, 200.0), embedding=emb_a)
    tracker._embedder = _FixedEmbedder(emb_b)  # type: ignore[attr-defined]
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    tracks = tracker.update(
        [_bbox_around(206.0, 200.0, size=40)], [0.9], 0.2, frame_bgr=fake_frame,
    )
    assert len(tracks) == 2, "gate must reject; both tracks alive this tick"
    new_track = next(t for t in tracks if not t.coasting)
    assert new_track.global_id != gid


def test_high_cosine_similarity_matches_without_bumping_suspect_counter():
    events: list[dict] = []
    manager = PieceHandoffManager(handoff_chain={})
    tracker = PolarFeederTracker(
        role="c_channel_2",
        handoff_manager=manager,
        pixel_fallback_distance_px=200.0,
        detection_score_threshold=0.1,
        coast_limit_ticks=5,
        id_switch_suspect_observer=lambda **kw: events.append(kw),
    )
    emb = _unit_vec(20)
    gid = _seed_track_with_embedding(tracker, start=(200.0, 200.0), embedding=emb)
    tracker._embedder = _FixedEmbedder(emb)  # type: ignore[attr-defined]
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    tracks = tracker.update(
        [_bbox_around(206.0, 200.0, size=40)], [0.9], 0.2, frame_bgr=fake_frame,
    )
    assert len(tracks) == 1
    assert tracks[0].global_id == gid
    assert events == [], "high-similarity match must not flag id switch"


def test_hungarian_suspect_pair_increments_counter():
    events: list[dict] = []
    manager = PieceHandoffManager(handoff_chain={})
    tracker = PolarFeederTracker(
        role="c_channel_2",
        handoff_manager=manager,
        pixel_fallback_distance_px=200.0,
        detection_score_threshold=0.1,
        coast_limit_ticks=5,
        # Drop the hard appearance gate so Hungarian actually gets to
        # accept the suspect pair we construct. Keep a non-1.0 value so
        # float-precision wobble doesn't re-enable it accidentally.
        min_appearance_similarity=-10.0,
        id_switch_suspect_observer=lambda **kw: events.append(kw),
    )
    emb_a = _unit_vec(30)
    emb_b = -emb_a  # sim ≈ -1, far below ID_SWITCH_SIM_SUSPECT (0.3)

    gid = _seed_track_with_embedding(tracker, start=(200.0, 200.0), embedding=emb_a)
    tracker._embedder = _FixedEmbedder(emb_b)  # type: ignore[attr-defined]
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Geometry cost ~120/200 = 0.6 which exceeds the 0.5 suspect threshold.
    tracks = tracker.update(
        [_bbox_around(320.0, 200.0, size=40)], [0.9], 0.2, frame_bgr=fake_frame
    )
    # Match should happen (gate is disabled) and the suspect observer fires.
    assert len(tracks) == 1
    assert tracks[0].global_id == gid
    assert len(events) == 1, f"expected one suspect event, got {events}"
    assert events[0]["similarity"] < 0.3
    assert events[0]["geom_cost"] > 0.5
