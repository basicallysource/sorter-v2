from __future__ import annotations

import pytest

from server import shared_state
from subsystems.sample_collection_speed import (
    microsteps_per_second_to_output_rpm,
    output_rpm_to_microsteps_per_second,
)


def teardown_function() -> None:
    for role in shared_state.SAMPLE_COLLECTION_SPEED_ROLES:
        shared_state.setSampleCollectionSpeedRpm(role, None)


def test_output_rpm_conversion_uses_channel_gear_ratio() -> None:
    assert output_rpm_to_microsteps_per_second(12.0, microsteps=8) == round(
        12.0 * 200 * 8 * (130 / 12) / 60
    )
    assert microsteps_per_second_to_output_rpm(3600, microsteps=8) == pytest.approx(
        12.4615,
        rel=1e-4,
    )


def test_shared_state_accepts_c4_alias_and_clears_value() -> None:
    shared_state.setSampleCollectionSpeedRpm("carousel", 6.5)

    assert shared_state.getSampleCollectionSpeedRpm("classification_channel") == 6.5
    assert shared_state.getSampleCollectionSpeedsRpmByRole()["classification_channel"] == 6.5

    shared_state.setSampleCollectionSpeedRpm("c4", None)
    assert shared_state.getSampleCollectionSpeedRpm("classification_channel") is None


def test_shared_state_allows_c4_up_to_role_specific_max() -> None:
    shared_state.setSampleCollectionSpeedRpm("c4", 50.0)

    assert shared_state.getSampleCollectionSpeedRpm("classification_channel") == 50.0
    assert shared_state.getSampleCollectionSpeedMaxRpm("c_channel_2") == 25.0
    assert shared_state.getSampleCollectionSpeedMaxRpm("c4") == 50.0
    assert shared_state.getSampleCollectionSpeedMaxRpmByRole()["classification_channel"] == 50.0


def test_shared_state_accepts_c1_alias() -> None:
    shared_state.setSampleCollectionSpeedRpm("c1", 0.01)

    assert shared_state.getSampleCollectionSpeedRpm("c_channel_1") == 0.01
    assert shared_state.getSampleCollectionSpeedsRpmByRole()["c_channel_1"] == 0.01


def test_shared_state_rejects_unsafe_or_unknown_speeds() -> None:
    with pytest.raises(ValueError):
        shared_state.setSampleCollectionSpeedRpm("c_channel_2", 0.009)
    with pytest.raises(ValueError):
        shared_state.setSampleCollectionSpeedRpm("c_channel_2", 25.001)
    with pytest.raises(ValueError):
        shared_state.setSampleCollectionSpeedRpm("c4", 50.001)
    with pytest.raises(ValueError):
        shared_state.setSampleCollectionSpeedRpm("c_channel_9", 4)
