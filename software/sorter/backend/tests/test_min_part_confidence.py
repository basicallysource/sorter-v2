"""Minimum part confidence and the settle gate before the burst."""
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
from subsystems.classification_channel.simple_state_machine_rev01.base import (
    classificationStatusForScore,
)
from subsystems.classification_channel.two_piece import _bboxCenterShift, _STILL_MAX_SHIFT_PX


def test_score_below_minimum_is_low_confidence() -> None:
    assert classificationStatusForScore(0.51, 0.6) is ClassificationStatus.low_confidence
    assert classificationStatusForScore(0.6, 0.6) is ClassificationStatus.classified
    assert classificationStatusForScore(0.89, 0.6) is ClassificationStatus.classified
    assert classificationStatusForScore(None, 0.6) is ClassificationStatus.low_confidence
    assert classificationStatusForScore("bad", 0.6) is ClassificationStatus.low_confidence


def test_center_shift_ignores_the_unset_box_and_measures_real_movement() -> None:
    assert _bboxCenterShift((0, 0, 0, 0), (100, 100, 200, 200)) == 0.0
    assert _bboxCenterShift((100, 100, 200, 200), (103, 100, 203, 200)) == 3.0
    assert _bboxCenterShift((100, 100, 200, 200), (120, 100, 220, 200)) > _STILL_MAX_SHIFT_PX
