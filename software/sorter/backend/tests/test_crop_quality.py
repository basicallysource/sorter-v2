from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from subsystems.classification_channel import crop_quality
from subsystems.classification_channel.simple_state_machine_rev01.base import (
    Rev01BaseState,
)
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import (
    Rev01Config,
)

# Real crops from Spencer's hand-labeled Hive dataset (2026-07-22): `star_*` are
# high_quality-starred frames, `blur_*` motion_blur, `empty_*` no_piece_in_frame,
# `cutoff_*` not_contained. Files sharing a piece id are frames of the SAME
# at-rest burst, so assertions on them are controlled comparisons.
FIXTURES = Path(__file__).parent / "fixtures" / "crop_quality"


def _load(name: str) -> np.ndarray:
    img = cv2.imread(str(FIXTURES / name))
    assert img is not None, f"missing fixture {name}"
    return img


def _syntheticPiece(blur: int = 0, shift: int = 0) -> np.ndarray:
    rng = np.random.default_rng(7)
    img = np.full((120, 120, 3), 235, dtype=np.uint8)
    piece = np.zeros((60, 60, 3), dtype=np.uint8)
    piece[:, :, 2] = 180
    piece[:, :, 1] = 40
    texture = rng.integers(-30, 30, size=(60, 60, 1))
    piece = np.clip(piece.astype(np.int32) + texture, 0, 255).astype(np.uint8)
    x = 30 + shift
    img[30:90, x : min(120, x + 60)] = piece[:, : max(0, min(60, 120 - x))]
    if blur > 0:
        img = cv2.blur(img, (blur, blur))
    return img


def test_score_crop_returns_finite_metrics_on_real_crops() -> None:
    for name in ("star_e683f68f_seq3.jpg", "blur_e683f68f_seq0.jpg", "empty_e8fd40f8_seq0.jpg"):
        q = crop_quality.scoreCrop(_load(name))
        assert np.isfinite(q.fft_hf_ratio) and 0.0 <= q.fft_hf_ratio <= 1.0
        assert np.isfinite(q.lap_var_piece_norm) and q.lap_var_piece_norm >= 0.0
        assert np.isfinite(q.lap_var)
        assert 0.0 <= q.mask_frac <= 1.0


def test_score_crop_is_deterministic() -> None:
    img = _load("star_e683f68f_seq3.jpg")
    a = crop_quality.scoreCrop(img)
    b = crop_quality.scoreCrop(img)
    assert a == b


def test_starred_frame_beats_blurred_frame_of_same_burst() -> None:
    star = crop_quality.scoreCrop(_load("star_e683f68f_seq3.jpg"))
    blur = crop_quality.scoreCrop(_load("blur_e683f68f_seq0.jpg"))
    assert star.fft_hf_ratio > blur.fft_hf_ratio
    assert star.lap_var_piece_norm > blur.lap_var_piece_norm


def test_selection_beats_raw_laplacian_on_background_contrast_trap() -> None:
    # The burst that motivated all of this: the blurred frame contains a sharp
    # white chute edge, so RAW whole-crop Laplacian scores it ABOVE the crisp
    # white-piece-on-white-background frame. The quality selection must still
    # rank the starred frame first.
    blur = crop_quality.scoreCrop(_load("blur_highlap_e4c45701_seq0.jpg"))
    star = crop_quality.scoreCrop(_load("star_lowlap_e4c45701_seq1.jpg"))
    assert blur.lap_var > star.lap_var  # the trap raw Laplacian falls into
    selected = crop_quality.selectBurstIndices([blur, star], 1)
    assert selected == [1]


def test_selection_drops_empty_frame() -> None:
    empty = crop_quality.scoreCrop(_load("empty_e8fd40f8_seq0.jpg"))
    star = crop_quality.scoreCrop(_load("star_e8fd40f8_seq1.jpg"))
    selected = crop_quality.selectBurstIndices([empty, star], 2)
    assert 1 in selected
    assert 0 not in selected


def test_selection_drops_cutoff_frame_via_burst_area() -> None:
    qs = [
        crop_quality.scoreCrop(_load("cutoff_0d64830e_seq0.jpg")),
        crop_quality.scoreCrop(_load("mid_0d64830e_seq1.jpg")),
        crop_quality.scoreCrop(_load("star_0d64830e_seq2.jpg")),
    ]
    selected = crop_quality.selectBurstIndices(qs, 3)
    assert 0 not in selected
    assert 2 in selected


def test_selection_always_returns_at_least_one() -> None:
    lone_blur = crop_quality.scoreCrop(_load("blur_e683f68f_seq0.jpg"))
    assert crop_quality.selectBurstIndices([lone_blur], 4) == [0]
    empty = crop_quality.scoreCrop(_load("empty_e8fd40f8_seq0.jpg"))
    assert crop_quality.selectBurstIndices([empty], 4) == [0]


def test_selection_returns_capture_order_and_respects_cap() -> None:
    sharp = _syntheticPiece()
    qs = [crop_quality.scoreCrop(sharp) for _ in range(4)]
    selected = crop_quality.selectBurstIndices(qs, 2)
    assert len(selected) == 2
    assert selected == sorted(selected)


def test_synthetic_blur_ranks_below_sharp() -> None:
    sharp = crop_quality.scoreCrop(_syntheticPiece())
    blurred = crop_quality.scoreCrop(_syntheticPiece(blur=7))
    assert sharp.fft_hf_ratio > blurred.fft_hf_ratio
    assert sharp.lap_var_piece_norm > blurred.lap_var_piece_norm
    assert crop_quality.bestIndex([blurred, sharp]) == 1


def test_relative_margin_ships_fewer_frames_when_burst_is_mixed() -> None:
    sharp = crop_quality.scoreCrop(_syntheticPiece())
    blurred = crop_quality.scoreCrop(_syntheticPiece(blur=9))
    selected = crop_quality.selectBurstIndices([blurred, sharp, sharp], 3)
    assert 0 not in selected
    assert len(selected) == 2


def test_burst_capture_complete_is_fixed_window_only() -> None:
    ctx = SimpleNamespace(
        config=Rev01Config(max_captures=3, capture_at_rest_ms=350.0),
        captured_crops=[],
        capturing_started_at=100.0,
    )
    assert Rev01BaseState.burstCaptureComplete(ctx, 100.01) == (False, "")
    ctx.captured_crops = [1]
    assert Rev01BaseState.burstCaptureComplete(ctx, 100.01) == (False, "")
    ctx.captured_crops = [1, 2, 3]
    assert Rev01BaseState.burstCaptureComplete(ctx, 100.01) == (True, "frame_cap")
    ctx.captured_crops = [1]
    assert Rev01BaseState.burstCaptureComplete(ctx, 100.40) == (True, "window")
