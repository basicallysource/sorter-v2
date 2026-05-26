import numpy as np

from subsystems.classification_channel.simple_state_machine_rev01.classifying import (
    Classifying,
)
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import (
    Rev01Config,
    configFromDict,
)
from subsystems.classification_channel.simple_state_machine_rev01.vision import Rev01Vision


def test_rev01_crop_bbox_uses_exact_bounds() -> None:
    frame = np.arange(6 * 8 * 3, dtype=np.uint8).reshape((6, 8, 3))

    crop = Rev01Vision.cropBbox(frame, (2, 1, 6, 5))

    assert crop is not None
    assert crop.shape == (4, 4, 3)
    assert np.array_equal(crop, frame[1:5, 2:6])


def test_rev01_select_recognition_crops_keeps_even_spread() -> None:
    crops = [np.full((2, 2, 3), idx, dtype=np.uint8) for idx in range(12)]

    classify = Classifying.__new__(Classifying)
    classify.ctx = type("Ctx", (), {"config": Rev01Config(max_captures=8)})()
    selected = classify.selectRecognitionCrops(crops)

    assert len(selected) == 8
    selected_ids = [int(crop[0, 0, 0]) for crop in selected]
    assert selected_ids == [0, 2, 3, 5, 6, 8, 9, 11]


def test_rev01_config_parses_capture_sweep_output_deg() -> None:
    cfg = configFromDict({"capture_sweep_output_deg": 135.5})

    assert cfg.capture_sweep_output_deg == 135.5
