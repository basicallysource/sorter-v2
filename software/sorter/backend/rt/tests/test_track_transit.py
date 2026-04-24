from __future__ import annotations

import math

from rt.contracts.tracking import Track
from rt.services.track_transit import TrackTransitRegistry


def _track(
    global_id: int = 2,
    angle_deg: float = 0.0,
    appearance_embedding: tuple[float, ...] | None = None,
) -> Track:
    return Track(
        track_id=global_id,
        global_id=global_id,
        piece_uuid=None,
        bbox_xyxy=(0, 0, 10, 10),
        score=0.9,
        confirmed_real=True,
        angle_rad=math.radians(angle_deg),
        radius_px=50.0,
        hit_count=3,
        first_seen_ts=0.0,
        last_seen_ts=0.0,
        appearance_embedding=appearance_embedding,
    )


def test_claim_returns_matching_target_candidate() -> None:
    registry = TrackTransitRegistry()
    candidate = registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=1,
        target_runtime="c4",
        now_mono=10.0,
        source_angle_deg=12.0,
        relation="cross_channel",
    )

    claimed = registry.claim(
        target_runtime="c4",
        track=_track(global_id=2, angle_deg=14.0),
        now_mono=10.2,
    )

    assert claimed == candidate
    assert registry.snapshot(10.2) == []


def test_claim_allows_same_global_id_candidate_by_default() -> None:
    registry = TrackTransitRegistry(default_ttl_s=1.0)
    candidate = registry.begin(
        source_runtime="c4",
        source_feed="c4_feed",
        source_global_id=9,
        target_runtime="c4",
        now_mono=1.0,
    )

    assert (
        registry.claim(target_runtime="c4", track=_track(global_id=9), now_mono=1.2)
        == candidate
    )


def test_claim_can_exclude_same_global_id_candidate() -> None:
    registry = TrackTransitRegistry(default_ttl_s=1.0)
    registry.begin(
        source_runtime="c4",
        source_feed="c4_feed",
        source_global_id=9,
        target_runtime="c4",
        now_mono=1.0,
    )

    assert (
        registry.claim(
            target_runtime="c4",
            track=_track(global_id=9),
            now_mono=1.2,
            exclude_same_global_id=True,
        )
        is None
    )


def test_claim_sweeps_expired_candidates() -> None:
    registry = TrackTransitRegistry(default_ttl_s=1.0)
    registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=3,
        target_runtime="c4",
        now_mono=1.0,
        ttl_s=0.5,
    )

    assert (
        registry.claim(
            target_runtime="c4",
            track=_track(global_id=4),
            now_mono=2.0,
        )
        is None
    )
    assert registry.snapshot(2.0) == []


def test_claim_rejects_candidate_with_dissimilar_appearance() -> None:
    """Cosine similarity gate is the Police-vs-Slope safety net on C3→C4."""

    registry = TrackTransitRegistry(appearance_threshold=0.55)
    red_slope = (1.0, 0.0, 0.0, 0.0)
    white_police = (0.0, 1.0, 0.0, 0.0)

    registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=1,
        target_runtime="c4",
        now_mono=1.0,
        source_angle_deg=10.0,
        relation="cross_channel",
        source_embedding=red_slope,
    )

    # The newly arriving track looks nothing like the parked candidate.
    claimed = registry.claim(
        target_runtime="c4",
        track=_track(global_id=2, appearance_embedding=white_police),
        now_mono=1.2,
    )
    assert claimed is None
    # Candidate must stay parked — a future same-looking track should still
    # be able to claim it.
    assert registry.snapshot(1.2)


def test_claim_prefers_candidate_with_closer_appearance_match() -> None:
    registry = TrackTransitRegistry(appearance_threshold=0.1)
    a = registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=1,
        target_runtime="c4",
        now_mono=1.0,
        source_angle_deg=10.0,
        source_embedding=(1.0, 0.0, 0.0, 0.0),
    )
    b = registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=2,
        target_runtime="c4",
        now_mono=1.0,
        source_angle_deg=10.0,
        source_embedding=(0.9, 0.1, 0.0, 0.0),
    )

    claimed = registry.claim(
        target_runtime="c4",
        track=_track(global_id=99, appearance_embedding=(1.0, 0.0, 0.0, 0.0)),
        now_mono=1.1,
    )
    # b has a slightly lower similarity than a, so a should win.
    assert claimed == a
    # b stays parked
    assert any(c["transit_id"] == b.transit_id for c in registry.snapshot(1.1))


def test_claim_falls_back_to_geometric_score_without_embeddings() -> None:
    """Pre-existing behaviour: motion-only tracker in use, no embeddings."""

    registry = TrackTransitRegistry()
    candidate = registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=1,
        target_runtime="c4",
        now_mono=1.0,
        source_angle_deg=10.0,
    )

    assert (
        registry.claim(
            target_runtime="c4",
            track=_track(global_id=2),  # no embedding
            now_mono=1.1,
        )
        == candidate
    )


def test_claim_accepts_candidate_when_track_embedding_is_missing() -> None:
    """One side missing embedding → permissive: do not block the match."""

    registry = TrackTransitRegistry(appearance_threshold=0.99)
    candidate = registry.begin(
        source_runtime="c3",
        source_feed="c3_feed",
        source_global_id=1,
        target_runtime="c4",
        now_mono=1.0,
        source_embedding=(1.0, 0.0, 0.0, 0.0),
    )

    # The new track has no embedding — gate must not reject (otherwise we'd
    # break fleets running a mix of trackers during a rollout).
    assert (
        registry.claim(
            target_runtime="c4",
            track=_track(global_id=2),
            now_mono=1.1,
        )
        == candidate
    )
