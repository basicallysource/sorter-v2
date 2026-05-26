from types import SimpleNamespace

import numpy as np

from defs.known_object import KnownObject
from subsystems.classification_channel.simple_state_machine_rev01.discharging import (
    Discharging,
)
from subsystems.classification_channel.states import ClassificationChannelState

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


def test_rev01_config_parses_kick_off_output_deg() -> None:
    cfg = configFromDict({"kick_off_output_deg": 72.0})

    assert cfg.kick_off_output_deg == 72.0


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class _Stepper:
    def __init__(self) -> None:
        self.stopped = True
        self.moves: list[int] = []
        self.speed_limits: list[tuple[int, int]] = []

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((int(min_speed), int(max_speed)))

    def move_steps(self, steps: int) -> bool:
        self.moves.append(int(steps))
        self.stopped = True
        return True


class _Vision:
    def getClassificationChannelDetectionCandidates(self):
        return []

    def getCarouselPolygon(self):
        return [[0, 0], [1, 0], [1, 1], [0, 1]]


def test_rev01_discharging_uses_forward_kick_off_move() -> None:
    stepper = _Stepper()
    state = Discharging(
        irl=SimpleNamespace(carousel_stepper=stepper),
        irl_config=SimpleNamespace(
            classification_channel_config=SimpleNamespace(),
        ),
        gc=SimpleNamespace(logger=_Logger()),
        shared=SimpleNamespace(),
        transport=SimpleNamespace(),
        vision=_Vision(),
        event_queue=SimpleNamespace(put=lambda *args, **kwargs: None),
        context=SimpleNamespace(
            config=Rev01Config(
                kick_off_output_deg=72.0,
                discharge_speed_usteps_per_s=3000,
                discharge_timeout_s=15.0,
            ),
            discharging_started_at=0.0,
            known_object=KnownObject(),
        ),
    )

    next_state = state.step()

    assert next_state == ClassificationChannelState.IDLE
    assert stepper.moves == [3467]
