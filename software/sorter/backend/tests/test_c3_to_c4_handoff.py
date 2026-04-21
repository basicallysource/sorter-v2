"""Tests that pin down the current C3 -> C4 (carousel) handoff behaviour.

The physical rig pours c_channel_3 pieces into the classification-channel
(role="carousel"). The same ``PieceHandoffManager`` bridges every pair in
``handoff_chain``; for a full machine that chain is
``c_channel_2 -> c_channel_3 -> carousel``.

These tests exercise the handoff at the C3->carousel boundary using the
real PolarFeederTracker + PieceHandoffManager with synthetic bboxes.
"""

from __future__ import annotations

import numpy as np
import pytest

from vision.tracking import (
    PolarFeederTracker,
    PieceHandoffManager,
    build_feeder_tracker_system,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _bbox_around(cx: float, cy: float, size: int = 40) -> tuple[int, int, int, int]:
    half = size // 2
    return (int(cx - half), int(cy - half), int(cx + half), int(cy + half))


def _make_three_camera_system() -> tuple[
    PieceHandoffManager, dict[str, PolarFeederTracker]
]:
    """Build the full c_channel_2 -> c_channel_3 -> carousel chain.

    Zones mirror what ``vision_manager._refreshHandoffZones`` installs
    on the live rig (roughly):
      - c_channel_3 exit  : right half of its frame
      - carousel  entry   : full frame (carousel entry position varies a
                            lot depending on how the piece lands after
                            the physical fall out of C3).
    """
    manager, trackers, _history = build_feeder_tracker_system(
        roles=("c_channel_2", "c_channel_3", "carousel"),
        handoff_window_s=2.0,
        frame_rate=5,
    )
    # c_channel_3 exit = right half (x > 600).
    manager.set_zones(
        "c_channel_3",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    # carousel entry = full frame (matches the live configuration at
    # vision_manager.py:2609-2612).
    manager.set_zones(
        "carousel",
        entry_polygon=[(0, 0), (1280, 0), (1280, 720), (0, 720)],
    )
    return manager, trackers


def _feed_until_dead(
    tracker: PolarFeederTracker, start_ts: float, max_ticks: int = 60
) -> float:
    ts = start_ts
    for _ in range(max_ticks):
        ts += 0.2
        tracks = tracker.update([], [], ts)
        if not tracks:
            return ts
    return ts


# ---------------------------------------------------------------------------
# Test A: happy path - single piece falls C3 -> C4 and inherits global_id.
# ---------------------------------------------------------------------------


def test_c3_to_c4_single_piece_inherits_global_id():
    manager, trackers = _make_three_camera_system()
    c3 = trackers["c_channel_3"]
    carousel = trackers["carousel"]

    # Warm up a track on C3 sitting inside the exit zone (right half).
    t1 = c3.update([_bbox_around(700.0, 360.0, size=60)], [0.9], 0.0)
    assert len(t1) == 1
    c3_id = t1[0].global_id

    # Let the C3 track expire (piece falls off the C3 camera view).
    death_ts = _feed_until_dead(c3, start_ts=0.0)

    pending = manager.pending_snapshot()
    assert len(pending) == 1, pending
    assert pending[0]["from_role"] == "c_channel_3"
    assert pending[0]["global_id"] == c3_id

    # Within the handoff window, carousel sees a new detection — at an
    # arbitrary plausible position on the platter, NOT at the same pixel
    # where it died on C3 (different camera, different frame).
    carousel_tracks = carousel.update(
        [_bbox_around(400.0, 300.0, size=60)],
        [0.9],
        death_ts + 0.2,
    )
    assert len(carousel_tracks) == 1
    assert carousel_tracks[0].global_id == c3_id, (
        "carousel should inherit the C3 global_id via the handoff manager"
    )
    assert carousel_tracks[0].handoff_from == "c_channel_3"

    # Pending queue is drained after the successful claim.
    assert manager.pending_snapshot() == []


# ---------------------------------------------------------------------------
# Test B: two pieces, physical order swaps mid-air -> FIFO binds them wrong.
# ---------------------------------------------------------------------------


def _make_manager_with_entry_zone() -> PieceHandoffManager:
    """Minimal manager with a C3→carousel chain and full-frame carousel
    entry zone, used by the unit-level tests that drive
    notify_track_death / register_track directly."""
    manager = PieceHandoffManager(
        handoff_chain={"c_channel_3": "carousel"},
        handoff_window_s=5.0,
    )
    manager.set_zones(
        "c_channel_3",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    manager.set_zones(
        "carousel",
        entry_polygon=[(0, 0), (1280, 0), (1280, 720), (0, 720)],
    )
    return manager


def _unit_vector(seed: int, dim: int = 8) -> np.ndarray:
    """Return a deterministic unit vector. Uses a one-hot axis so tests
    can rely on pairs of vectors with cosine similarity exactly 0 or 1.
    """
    vec = np.zeros(dim, dtype=np.float32)
    vec[int(seed) % dim] = 1.0
    return vec


def test_c3_to_c4_order_swap_rebinds_by_embedding_similarity():
    """Two pieces die on C3 in order A then B (FIFO pending = [A, B]).
    On C4 the *first* detection that lands carries B's embedding — the
    physical order swapped mid-air.

    With embedding-based rebind the first claim must pop the pending
    whose embedding matches (B), not the FIFO head (A). Otherwise
    downstream classification writes B's result under A's global_id.
    """
    manager = _make_manager_with_entry_zone()
    emb_A = _unit_vector(1)
    emb_B = _unit_vector(2)
    # Embeddings are well-separated.
    assert float(np.dot(emb_A, emb_B)) < 0.5

    manager.notify_track_death(
        "c_channel_3", 101, (700.0, 200.0), 1.0, death_ts=1.0,
        last_displacement_px=200.0, embedding=emb_A,
    )
    manager.notify_track_death(
        "c_channel_3", 202, (700.0, 500.0), 1.1, death_ts=1.1,
        last_displacement_px=200.0, embedding=emb_B,
    )
    assert [p["global_id"] for p in manager.pending_snapshot()] == [101, 202]

    # First claim: carries B's embedding. Should pop B (id=202), NOT
    # the FIFO head A.
    gid1, src1, _ = manager.register_track("carousel", (400.0, 300.0), 2.0, embedding=emb_B)
    assert gid1 == 202
    assert src1 == "c_channel_3"
    assert manager.embedding_rebind_total == 1

    # Second claim: carries A's embedding — only one pending left, FIFO
    # fall-through, no further rebind.
    gid2, src2, _ = manager.register_track("carousel", (500.0, 400.0), 2.1, embedding=emb_A)
    assert gid2 == 101
    assert src2 == "c_channel_3"
    assert manager.embedding_rebind_total == 1


def test_handoff_falls_back_to_fifo_when_no_embedding():
    """When the claim carries no embedding (e.g. BoxMOT weights missing,
    or no frame passed into the tracker) the manager must preserve the
    original FIFO behaviour — head wins."""
    manager = _make_manager_with_entry_zone()
    manager.notify_track_death(
        "c_channel_3", 11, (700.0, 200.0), 1.0, death_ts=1.0,
        last_displacement_px=200.0, embedding=_unit_vector(1),
    )
    manager.notify_track_death(
        "c_channel_3", 22, (700.0, 500.0), 1.1, death_ts=1.1,
        last_displacement_px=200.0, embedding=_unit_vector(2),
    )

    gid, src, _ = manager.register_track("carousel", (400.0, 300.0), 2.0)
    assert gid == 11
    assert src == "c_channel_3"
    assert manager.embedding_rebind_total == 0


def test_handoff_falls_back_to_fifo_when_below_similarity_threshold():
    """If every pending has a very low similarity to the claim (below
    ``similarity_threshold``) we trust FIFO rather than pick the
    'least-worst' candidate — same as the no-embedding path."""
    # Claim embedding is nearly orthogonal to both pendings.
    manager = PieceHandoffManager(
        handoff_chain={"c_channel_3": "carousel"},
        handoff_window_s=5.0,
        similarity_threshold=0.95,  # artificially high floor
    )
    manager.set_zones(
        "c_channel_3",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    manager.set_zones(
        "carousel",
        entry_polygon=[(0, 0), (1280, 0), (1280, 720), (0, 720)],
    )

    emb_pending_A = _unit_vector(1)
    emb_pending_B = _unit_vector(2)
    emb_claim = _unit_vector(3)

    manager.notify_track_death(
        "c_channel_3", 33, (700.0, 200.0), 1.0, death_ts=1.0,
        last_displacement_px=200.0, embedding=emb_pending_A,
    )
    manager.notify_track_death(
        "c_channel_3", 44, (700.0, 500.0), 1.1, death_ts=1.1,
        last_displacement_px=200.0, embedding=emb_pending_B,
    )

    gid, _src, _ = manager.register_track(
        "carousel", (400.0, 300.0), 2.0, embedding=emb_claim,
    )
    # Similarity below threshold → FIFO head wins.
    assert gid == 33
    assert manager.embedding_rebind_total == 0


# ---------------------------------------------------------------------------
# Meta: register_track now accepts an appearance input.
# ---------------------------------------------------------------------------


def test_handoff_manager_register_track_signature_accepts_embedding():
    """register_track takes an optional ``embedding`` kwarg. Any future
    refactor that moves it into a separate rebind call needs to update
    this test."""
    import inspect

    sig = inspect.signature(PieceHandoffManager.register_track)
    params = list(sig.parameters.keys())
    assert params == ["self", "role", "center", "timestamp", "embedding"], params
    assert sig.parameters["embedding"].default is None


# ---------------------------------------------------------------------------
# Upstream-liveness probe: reject claims whose pending is still alive upstream.
# ---------------------------------------------------------------------------


def _make_manager_with_probe(
    live_map: dict[str, set[int]],
    *,
    stale_counter: list[int] | None = None,
) -> PieceHandoffManager:
    """Build a C3->carousel manager whose upstream-liveness probe is
    driven by a mutable dict, so tests can flip upstream-alive state
    without needing a real tracker."""

    def _probe(role: str) -> set[int]:
        return set(live_map.get(role, set()))

    def _obs(**_kw) -> None:
        if stale_counter is not None:
            stale_counter[0] += 1

    manager = PieceHandoffManager(
        handoff_chain={"c_channel_3": "carousel"},
        handoff_window_s=5.0,
        upstream_live_ids_probe=_probe,
        stale_pending_observer=_obs,
    )
    manager.set_zones(
        "c_channel_3",
        exit_polygon=[(600, 0), (1280, 0), (1280, 720), (600, 720)],
    )
    manager.set_zones(
        "carousel",
        entry_polygon=[(0, 0), (1280, 0), (1280, 720), (0, 720)],
    )
    return manager


def test_handoff_rejects_claim_when_upstream_still_alive():
    """Pending exists for global_id=42. Probe says 42 is still alive on
    c_channel_3 — claim on carousel must NOT receive id=42, and the
    stale-pending counter must bump."""
    live_map: dict[str, set[int]] = {"c_channel_3": {42}}
    stale_counter = [0]
    manager = _make_manager_with_probe(live_map, stale_counter=stale_counter)

    manager.notify_track_death(
        "c_channel_3", 42, (700.0, 300.0), 1.0, death_ts=1.0,
        last_displacement_px=200.0, embedding=_unit_vector(1),
    )
    assert [p["global_id"] for p in manager.pending_snapshot()] == [42]

    gid, src, _ = manager.register_track(
        "carousel", (400.0, 300.0), 2.0, embedding=_unit_vector(1),
    )
    # Fresh id — NOT the stale 42.
    assert gid != 42
    assert src is None
    assert manager.stale_pending_dropped_total == 1
    assert stale_counter[0] == 1
    # Pending was popped.
    assert manager.pending_snapshot() == []


def test_handoff_happy_path_when_upstream_not_alive():
    """Pending exists for global_id=42. Probe says 42 is NOT alive — the
    carousel claim should succeed and inherit 42."""
    live_map: dict[str, set[int]] = {"c_channel_3": set()}
    stale_counter = [0]
    manager = _make_manager_with_probe(live_map, stale_counter=stale_counter)

    manager.notify_track_death(
        "c_channel_3", 42, (700.0, 300.0), 1.0, death_ts=1.0,
        last_displacement_px=200.0, embedding=_unit_vector(1),
    )
    gid, src, _ = manager.register_track(
        "carousel", (400.0, 300.0), 2.0, embedding=_unit_vector(1),
    )
    assert gid == 42
    assert src == "c_channel_3"
    assert manager.stale_pending_dropped_total == 0
    assert stale_counter[0] == 0


def test_handoff_picks_non_stale_among_multiple_pendings():
    """Two pendings (42, 43). Probe says 42 is alive, 43 isn't. Claim
    should skip 42 and inherit 43 with no fresh id allocated."""
    live_map: dict[str, set[int]] = {"c_channel_3": {42}}
    stale_counter = [0]
    manager = _make_manager_with_probe(live_map, stale_counter=stale_counter)

    manager.notify_track_death(
        "c_channel_3", 42, (700.0, 200.0), 1.0, death_ts=1.0,
        last_displacement_px=200.0, embedding=_unit_vector(1),
    )
    manager.notify_track_death(
        "c_channel_3", 43, (700.0, 500.0), 1.1, death_ts=1.1,
        last_displacement_px=200.0, embedding=_unit_vector(2),
    )
    assert [p["global_id"] for p in manager.pending_snapshot()] == [42, 43]

    gid, src, _ = manager.register_track(
        "carousel", (400.0, 300.0), 2.0, embedding=_unit_vector(2),
    )
    assert gid == 43
    assert src == "c_channel_3"
    assert manager.stale_pending_dropped_total == 1
    assert stale_counter[0] == 1
    # The stale 42 was dropped; the claimed 43 was removed. Queue empty.
    assert manager.pending_snapshot() == []
