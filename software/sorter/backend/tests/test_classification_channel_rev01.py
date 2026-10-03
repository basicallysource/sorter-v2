import numpy as np

from subsystems.classification_channel.two_piece.base import Rev01BaseState
from subsystems.classification_channel.two_piece.rev01_config import (
    Rev01Config,
    configFromDict,
)


def test_rev01_crop_bbox_uses_exact_bounds() -> None:
    frame = np.arange(6 * 8 * 3, dtype=np.uint8).reshape((6, 8, 3))

    crop = Rev01BaseState.cropBbox(frame, (2, 1, 6, 5))

    assert crop is not None
    assert crop.shape == (4, 4, 3)
    assert np.array_equal(crop, frame[1:5, 2:6])


def test_rev01_config_parses_capture_sweep_output_deg() -> None:
    cfg = configFromDict({"capture_sweep_output_deg": 135.5})

    assert cfg.capture_sweep_output_deg == 135.5


def test_rev01_config_parses_kick_off_output_deg() -> None:
    cfg = configFromDict({"kick_off_output_deg": 180.0})

    assert cfg.kick_off_output_deg == 180.0


def test_rev01_config_parses_verify_discharge_fields() -> None:
    cfg = configFromDict(
        {
            "verify_discharge_wait_ms": 750,
            "verify_discharge_max_jitter_attempts": 5,
        }
    )

    assert cfg.verify_discharge_wait_ms == 750
    assert cfg.verify_discharge_max_jitter_attempts == 5
