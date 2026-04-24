from __future__ import annotations

import math

from rt.contracts.tracking import Track
from rt.services.track_transit import TrackTransitRegistry


def _track(global_id: int = 2, angle_deg: float = 0.0) -> Track:
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


def test_claim_skips_same_global_id_candidate() -> None:
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
