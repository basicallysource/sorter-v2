from __future__ import annotations

from rt.contracts.tracking import Track, TrackBatch
from rt.perception.track_stabilizer import TrackletStabilizer


def _track(
    gid: int,
    *,
    ts: float,
    bbox: tuple[int, int, int, int],
    embedding: tuple[float, ...] | None = None,
) -> Track:
    return Track(
        track_id=gid,
        global_id=gid,
        piece_uuid=None,
        bbox_xyxy=bbox,
        score=0.9,
        confirmed_real=True,
        angle_rad=None,
        radius_px=None,
        hit_count=3,
        first_seen_ts=ts,
        last_seen_ts=ts,
        appearance_embedding=embedding,
    )


def _batch(ts: float, *tracks: Track) -> TrackBatch:
    return TrackBatch(
        feed_id="c4_feed",
        frame_seq=int(ts * 10),
        timestamp=ts,
        tracks=tuple(tracks),
        lost_track_ids=(),
    )


def test_assigns_piece_uuid_and_holds_over_short_dropout() -> None:
    stabilizer = TrackletStabilizer(holdover_s=1.0, match_distance_px=120.0)
    first = stabilizer.update(_batch(1.0, _track(10, ts=1.0, bbox=(0, 0, 10, 10))))
    piece_uuid = first.tracks[0].piece_uuid

    held = stabilizer.update(_batch(1.4))

    assert held.tracks[0].piece_uuid == piece_uuid
    assert held.tracks[0].ghost is True


def test_merges_new_tracklet_after_short_dropout_by_geometry() -> None:
    stabilizer = TrackletStabilizer(holdover_s=1.0, match_distance_px=120.0)
    first = stabilizer.update(_batch(1.0, _track(10, ts=1.0, bbox=(0, 0, 10, 10))))
    piece_uuid = first.tracks[0].piece_uuid

    second = stabilizer.update(_batch(1.6, _track(99, ts=1.6, bbox=(12, 0, 22, 10))))

    assert second.tracks[0].piece_uuid == piece_uuid
    assert second.tracks[0].global_id == 99


def test_appearance_mismatch_blocks_geometry_merge() -> None:
    stabilizer = TrackletStabilizer(
        holdover_s=1.0,
        match_distance_px=120.0,
        appearance_threshold=0.8,
    )
    first = stabilizer.update(
        _batch(1.0, _track(10, ts=1.0, bbox=(0, 0, 10, 10), embedding=(1.0, 0.0)))
    )
    piece_uuid = first.tracks[0].piece_uuid

    second = stabilizer.update(
        _batch(1.4, _track(11, ts=1.4, bbox=(2, 0, 12, 10), embedding=(0.0, 1.0)))
    )

    assert second.tracks[0].piece_uuid != piece_uuid
