from __future__ import annotations

import math

import pytest

from rt.contracts.tracking import Track
from rt.services.transport_velocity import TransportVelocityObserver


def _track(
    *,
    global_id: int = 1,
    angle_deg: float,
    last_seen_ts: float,
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
        hit_count=5,
        first_seen_ts=0.0,
        last_seen_ts=last_seen_ts,
    )


def test_transport_velocity_wraps_angle_delta_across_zero() -> None:
    observer = TransportVelocityObserver(channel="c4", exit_angle_deg=0.0)

    observer.update([_track(angle_deg=350.0, last_seen_ts=1.0)], now_mono=1.0)
    snap = observer.update(
        [_track(angle_deg=10.0, last_seen_ts=2.0)],
        now_mono=2.0,
        base_step_deg=6.0,
        max_step_deg=18.0,
    )

    assert snap.measured_track_count == 1
    assert snap.front_rpm == pytest.approx(20.0 / 360.0 * 60.0)


def test_transport_velocity_recommends_longer_window_when_piece_is_slow() -> None:
    observer = TransportVelocityObserver(
        channel="c4",
        exit_angle_deg=180.0,
        target_rpm=2.0,
    )

    observer.update([_track(angle_deg=45.0, last_seen_ts=1.0)], now_mono=1.0)
    snap = observer.update(
        [_track(angle_deg=48.0, last_seen_ts=2.0)],
        now_mono=2.0,
        base_step_deg=6.0,
        max_step_deg=18.0,
        exit_slow_zone_deg=36.0,
    )

    assert snap.recommendation == "extend_transport_window"
    assert snap.recommended_step_deg == 18.0


def test_transport_velocity_keeps_small_step_in_exit_slow_zone() -> None:
    observer = TransportVelocityObserver(
        channel="c4",
        exit_angle_deg=180.0,
        target_rpm=2.0,
    )

    observer.update([_track(angle_deg=170.0, last_seen_ts=1.0)], now_mono=1.0)
    snap = observer.update(
        [_track(angle_deg=171.0, last_seen_ts=2.0)],
        now_mono=2.0,
        base_step_deg=6.0,
        max_step_deg=18.0,
        exit_slow_zone_deg=36.0,
    )

    assert snap.recommendation == "exit_approach_hold_small"
    assert snap.recommended_step_deg == 6.0
