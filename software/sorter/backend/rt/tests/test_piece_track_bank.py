"""Foundation tests for the PieceTrackBank.

Stage 1 of the vision-corrected virtual-pocket architecture rollout
(see ``docs/lab/sorter-tracking-architecture-recommendation.md``). The
bank is exercised here in isolation — no runtime, no perception
runner, no orchestrator. That comes in stage 2.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rt.perception.piece_track_bank import (
    AssociationOutcome,
    CameraTrayCalibration,
    Measurement,
    MeasurementNoise,
    PieceLifecycleState,
    PieceTrackBank,
    PieceTrackBankConfig,
    ProcessNoise,
    is_chute_blocking,
    is_dispatch_eligible,
    wrap_diff_rad,
    wrap_rad,
)


def _make_bank(
    *,
    channel: str = "c4",
    confirm_min_detections: int = 3,
    confirm_min_real: int = 1,
    coast_after_silence_s: float = 0.6,
    finalize_lost_after_silence_s: float = 4.0,
    measurement_noise: MeasurementNoise | None = None,
) -> PieceTrackBank:
    cfg = PieceTrackBankConfig(
        channel=channel,
        calibration=CameraTrayCalibration(cx=0.0, cy=0.0),
        confirm_min_detections=confirm_min_detections,
        confirm_min_real=confirm_min_real,
        coast_after_silence_s=coast_after_silence_s,
        finalize_lost_after_silence_s=finalize_lost_after_silence_s,
        measurement_noise=measurement_noise or MeasurementNoise(),
        initial_sigma_a_rad=math.radians(2.0),
        initial_sigma_r_px=4.0,
    )
    return PieceTrackBank(cfg)


def _meas(a_deg: float, r: float = 100.0, **kwargs) -> Measurement:
    return Measurement(
        a_meas=math.radians(a_deg),
        r_meas=r,
        score=kwargs.pop("score", 0.9),
        confirmed_real=kwargs.pop("confirmed_real", True),
        **kwargs,
    )


# ----------------------------------------------------------------------
# Geometry helpers


def test_wrap_rad_keeps_input_in_pmpi() -> None:
    assert wrap_rad(0.0) == 0.0
    assert math.isclose(wrap_rad(math.pi + 0.1), -math.pi + 0.1, abs_tol=1e-9)
    assert math.isclose(wrap_rad(-math.pi - 0.1), math.pi - 0.1, abs_tol=1e-9)


def test_wrap_diff_takes_short_way_around() -> None:
    a = math.radians(170.0)
    b = math.radians(-170.0)
    diff = wrap_diff_rad(a, b)
    assert math.isclose(math.degrees(diff), -20.0, abs_tol=1e-6)


def test_calibration_polar_round_trip() -> None:
    cal = CameraTrayCalibration(cx=320.0, cy=240.0)
    theta, r = cal.to_polar(420.0, 240.0)  # +x of center
    assert math.isclose(theta, 0.0, abs_tol=1e-9)
    assert math.isclose(r, 100.0, abs_tol=1e-9)
    theta, r = cal.to_polar(320.0, 340.0)  # +y of center -> +pi/2
    assert math.isclose(theta, math.pi / 2.0, abs_tol=1e-9)
    assert math.isclose(r, 100.0, abs_tol=1e-9)


# ----------------------------------------------------------------------
# Birth / association / update


def test_bank_admits_first_measurement_as_tentative_birth() -> None:
    bank = _make_bank()
    outcome = bank.associate_and_update(
        [_meas(a_deg=30.0)], now_t=0.0, encoder_rad=0.0
    )
    assert outcome.births == 1
    assert outcome.updates == []
    assert len(bank) == 1
    track = next(iter(bank.tracks()))
    assert track.lifecycle_state is PieceLifecycleState.TENTATIVE
    assert math.isclose(math.degrees(track.angle_rad), 30.0, abs_tol=1e-6)


def test_repeated_close_measurements_associate_to_same_piece() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=30.0)], now_t=0.0, encoder_rad=0.0
    )
    bank.predict_all(t=0.05, encoder_rad=0.0)
    outcome = bank.associate_and_update(
        [_meas(a_deg=30.5)], now_t=0.05, encoder_rad=0.0
    )
    assert outcome.births == 0
    assert len(outcome.updates) == 1
    assert len(bank) == 1


def test_far_measurement_creates_separate_piece() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=30.0)], now_t=0.0, encoder_rad=0.0
    )
    outcome = bank.associate_and_update(
        [_meas(a_deg=180.0)], now_t=0.05, encoder_rad=0.0
    )
    assert outcome.births == 1
    assert len(bank) == 2


def test_kalman_update_pulls_state_toward_measurement() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=30.0)], now_t=0.0, encoder_rad=0.0
    )
    track_before = next(iter(bank.tracks()))
    cov_before = float(track_before.state_covariance[0, 0])

    bank.predict_all(t=0.05, encoder_rad=0.0)
    bank.associate_and_update(
        [_meas(a_deg=31.0)], now_t=0.05, encoder_rad=0.0
    )
    track_after = bank.track(track_before.piece_uuid)
    assert track_after is not None
    assert math.degrees(track_after.angle_rad) > 30.0
    assert math.degrees(track_after.angle_rad) < 31.0
    # Covariance must shrink after a clean update.
    assert float(track_after.state_covariance[0, 0]) < cov_before


def test_promotion_to_confirmed_after_min_detections() -> None:
    bank = _make_bank(confirm_min_detections=3, confirm_min_real=2)
    for i, t in enumerate([0.0, 0.05, 0.10]):
        bank.predict_all(t=t, encoder_rad=0.0)
        bank.associate_and_update(
            [_meas(a_deg=30.0 + 0.2 * i, confirmed_real=True)],
            now_t=t,
            encoder_rad=0.0,
        )
    track = next(iter(bank.tracks()))
    assert track.lifecycle_state is PieceLifecycleState.CONFIRMED_UNCLASSIFIED


def test_silence_demotes_to_lost_coasting_then_finalizes() -> None:
    bank = _make_bank(coast_after_silence_s=0.5, finalize_lost_after_silence_s=1.5)
    bank.associate_and_update(
        [_meas(a_deg=30.0)], now_t=0.0, encoder_rad=0.0
    )
    # Promote first so the demotion path is exercised.
    track = next(iter(bank.tracks()))
    track.lifecycle_state = PieceLifecycleState.CONFIRMED_UNCLASSIFIED

    bank.predict_all(t=0.6, encoder_rad=0.0)
    bank.associate_and_update([], now_t=0.6, encoder_rad=0.0)
    track = next(iter(bank.tracks()))
    assert track.lifecycle_state is PieceLifecycleState.LOST_COASTING

    bank.predict_all(t=2.0, encoder_rad=0.0)
    bank.associate_and_update([], now_t=2.0, encoder_rad=0.0)
    assert len(bank) == 0


def test_raw_id_alias_ties_measurement_back_to_existing_piece() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=30.0, raw_track_id=42)], now_t=0.0, encoder_rad=0.0
    )
    piece_uuid = next(iter(bank.tracks())).piece_uuid
    bank.predict_all(t=0.05, encoder_rad=0.0)
    bank.associate_and_update(
        [_meas(a_deg=30.5, raw_track_id=42)], now_t=0.05, encoder_rad=0.0
    )
    track = bank.find_by_raw_id(42)
    assert track is not None
    assert track.piece_uuid == piece_uuid


def test_mismatched_raw_id_still_associates_when_geometry_dominates() -> None:
    """A measurement whose raw id already aliases a different piece is
    soft-penalised, not rejected. If the geometric match is clearly with
    track A, we still update A — keeping identity stable across raw-id
    churn from the underlying tracker."""
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=30.0, raw_track_id=42)], now_t=0.0, encoder_rad=0.0
    )
    bank.predict_all(t=0.05, encoder_rad=0.0)
    bank.associate_and_update(
        [_meas(a_deg=180.0, raw_track_id=99)], now_t=0.05, encoder_rad=0.0
    )
    assert len(bank) == 2
    bank.predict_all(t=0.10, encoder_rad=0.0)
    # Same physical piece at angle 30, but tracker re-assigned its raw id.
    bank.associate_and_update(
        [_meas(a_deg=30.5, raw_track_id=99)], now_t=0.10, encoder_rad=0.0
    )
    assert len(bank) == 2  # no spurious birth — geometry stayed dominant


# ----------------------------------------------------------------------
# Lifecycle state classifiers


def test_dispatch_eligible_only_for_classified_confident() -> None:
    assert is_dispatch_eligible(PieceLifecycleState.CLASSIFIED_CONFIDENT)
    assert not is_dispatch_eligible(PieceLifecycleState.CLASSIFIED_IDENTITY_UNCERTAIN)
    assert not is_dispatch_eligible(PieceLifecycleState.CLUSTERED)
    assert not is_dispatch_eligible(PieceLifecycleState.LOST_COASTING)


def test_chute_blocking_covers_every_alive_state() -> None:
    blocking = {
        PieceLifecycleState.TENTATIVE,
        PieceLifecycleState.CONFIRMED_UNCLASSIFIED,
        PieceLifecycleState.CLASSIFIED_CONFIDENT,
        PieceLifecycleState.CLASSIFIED_IDENTITY_UNCERTAIN,
        PieceLifecycleState.LOST_COASTING,
        PieceLifecycleState.CLUSTERED,
        PieceLifecycleState.REJECT_ONLY,
    }
    for s in blocking:
        assert is_chute_blocking(s)
    assert not is_chute_blocking(PieceLifecycleState.EJECTED)
    assert not is_chute_blocking(PieceLifecycleState.FINALIZED_LOST)


# ----------------------------------------------------------------------
# Posterior singleton query


def test_singleton_check_passes_for_lone_piece_in_chute() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0)], now_t=0.0, encoder_rad=0.0
    )
    track = next(iter(bank.tracks()))
    bank.bind_classification(
        track.piece_uuid, class_label="3001", class_confidence=0.95
    )
    chute_center = math.radians(30.0)
    encoder = math.radians(30.0)
    # Tray-frame angle = 0 + encoder 30 = world angle 30 (chute center).
    assert bank.is_singleton_in_chute(
        track.piece_uuid,
        chute_center_rad=chute_center,
        chute_half_width_rad=math.radians(14.0),
        encoder_rad=encoder,
    )


def test_singleton_check_blocks_when_second_piece_in_chute() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0), _meas(a_deg=8.0)],
        now_t=0.0,
        encoder_rad=0.0,
    )
    a_piece, b_piece = list(bank.tracks())
    bank.bind_classification(
        a_piece.piece_uuid, class_label="3001", class_confidence=0.95
    )
    bank.bind_classification(
        b_piece.piece_uuid, class_label="3002", class_confidence=0.95
    )
    chute_center = math.radians(30.0)
    encoder = math.radians(30.0)
    # World angles: a=30 (center), b=38 (within 14 deg half-width)
    assert not bank.is_singleton_in_chute(
        a_piece.piece_uuid,
        chute_center_rad=chute_center,
        chute_half_width_rad=math.radians(14.0),
        encoder_rad=encoder,
    )


def test_singleton_check_respects_finalized_pieces() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0), _meas(a_deg=8.0)],
        now_t=0.0,
        encoder_rad=0.0,
    )
    a_piece, b_piece = list(bank.tracks())
    bank.bind_classification(
        a_piece.piece_uuid, class_label="3001", class_confidence=0.95
    )
    # b is finalized — must not contribute to the chute occupancy any more.
    bank.finalize(b_piece.piece_uuid)
    chute_center = math.radians(30.0)
    encoder = math.radians(30.0)
    assert bank.is_singleton_in_chute(
        a_piece.piece_uuid,
        chute_center_rad=chute_center,
        chute_half_width_rad=math.radians(14.0),
        encoder_rad=encoder,
    )


def test_chute_window_occupants_returns_blocking_tracks_only() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0), _meas(a_deg=5.0), _meas(a_deg=180.0)],
        now_t=0.0,
        encoder_rad=0.0,
    )
    encoder = math.radians(30.0)
    occupants = bank.chute_window_occupants(
        chute_center_rad=math.radians(30.0),
        chute_half_width_rad=math.radians(14.0),
        encoder_rad=encoder,
    )
    # Two pieces at world-angle 30 and 35 are inside the +/- 14 deg
    # window; the piece at 210 deg is outside.
    assert len(occupants) == 2


# ----------------------------------------------------------------------
# Predict propagation under encoder


def test_predict_propagates_velocity() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0)], now_t=0.0, encoder_rad=0.0
    )
    track = next(iter(bank.tracks()))
    # Inject a known angular velocity.
    track.state_mean[2] = math.radians(60.0)  # 60 deg/s tray-frame drift
    bank.predict_all(t=1.0, encoder_rad=0.0)
    assert math.isclose(math.degrees(track.angle_rad), 60.0, abs_tol=1e-6)


def test_predict_inflates_covariance_under_silence() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0)], now_t=0.0, encoder_rad=0.0
    )
    cov_before = float(next(iter(bank.tracks())).state_covariance[0, 0])
    bank.predict_all(t=2.0, encoder_rad=0.0)
    cov_after = float(next(iter(bank.tracks())).state_covariance[0, 0])
    assert cov_after > cov_before


# ----------------------------------------------------------------------
# Landing-lease API


def test_lease_grants_when_landing_arc_is_clear() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=180.0)], now_t=0.0, encoder_rad=0.0
    )
    lease = bank.request_landing_lease(
        predicted_arrival_t=0.5,
        predicted_landing_a=math.radians(0.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
    )
    assert lease is not None


def test_lease_denies_when_existing_track_will_be_in_landing_arc() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0)], now_t=0.0, encoder_rad=0.0
    )
    # Existing track sits at 0 and we ask to land at 10° within 30°
    # spacing — should refuse.
    lease = bank.request_landing_lease(
        predicted_arrival_t=0.5,
        predicted_landing_a=math.radians(10.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
    )
    assert lease is None


def test_lease_grants_when_existing_track_will_have_drifted_past() -> None:
    bank = _make_bank()
    bank.associate_and_update(
        [_meas(a_deg=0.0)], now_t=0.0, encoder_rad=0.0
    )
    track = next(iter(bank.tracks()))
    # Inject an angular velocity so the track moves clear before arrival.
    track.state_mean[2] = math.radians(120.0)  # 120 deg/s
    lease = bank.request_landing_lease(
        predicted_arrival_t=0.5,  # track at 0 + 120*0.5 = 60° at arrival
        predicted_landing_a=math.radians(0.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
    )
    assert lease is not None


def test_lease_denies_two_overlapping_grants() -> None:
    bank = _make_bank()
    first = bank.request_landing_lease(
        predicted_arrival_t=0.5,
        predicted_landing_a=math.radians(0.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
    )
    assert first is not None
    # A second request landing within the same 30° arc must refuse
    # because the first lease is still held.
    second = bank.request_landing_lease(
        predicted_arrival_t=0.6,
        predicted_landing_a=math.radians(15.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
    )
    assert second is None


def test_lease_expires_after_ttl() -> None:
    bank = _make_bank()
    lease = bank.request_landing_lease(
        predicted_arrival_t=0.5,
        predicted_landing_a=math.radians(0.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
        lease_ttl_s=0.5,
    )
    assert lease is not None
    # After the lease TTL the slot frees up and a new request grants.
    second = bank.request_landing_lease(
        predicted_arrival_t=1.5,
        predicted_landing_a=math.radians(0.0),
        min_spacing_rad=math.radians(30.0),
        now_t=1.0,
    )
    assert second is not None


def test_consume_lease_removes_pending() -> None:
    bank = _make_bank()
    lease = bank.request_landing_lease(
        predicted_arrival_t=0.5,
        predicted_landing_a=math.radians(0.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.0,
    )
    assert lease is not None
    assert bank.consume_landing_lease(lease) is True
    assert bank.consume_landing_lease(lease) is False
    # Once consumed the slot frees up.
    second = bank.request_landing_lease(
        predicted_arrival_t=0.5,
        predicted_landing_a=math.radians(5.0),
        min_spacing_rad=math.radians(30.0),
        now_t=0.1,
    )
    assert second is not None
