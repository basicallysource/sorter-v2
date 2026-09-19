"""[chute] operating speed and [stepper_acceleration_overrides] parsing."""
import logging
from types import SimpleNamespace

from irl.parse_user_toml import _parseStepperAccelerationOverrides, loadChuteCalibrationConfig, normalizePhysicalStepperBindingName
from subsystems.distribution.chute import Chute, DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC


def _gc():
    return SimpleNamespace(logger=logging.getLogger("test"))


def test_operating_speed_below_the_firmware_minimum_falls_back_to_the_default() -> None:
    cfg = loadChuteCalibrationConfig(_gc(), {"chute": {"operating_speed_microsteps_per_second": 5}})
    assert cfg.operating_speed_microsteps_per_second == DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC
    cfg = loadChuteCalibrationConfig(_gc(), {"chute": {"operating_speed_microsteps_per_second": 16}})
    assert cfg.operating_speed_microsteps_per_second == 16


def test_chute_never_pushes_a_speed_below_the_firmware_minimum() -> None:
    limits = []
    stepper = SimpleNamespace(set_speed_limits=lambda lo, hi: limits.append((lo, hi)), position_degrees=0.0)
    chute = Chute(_gc(), stepper=stepper, home_pin=SimpleNamespace(value=False), layout=SimpleNamespace(layers=[]),
                  operating_speed_microsteps_per_second=3)
    chute._applyOperatingSpeed()
    assert limits == [(16, 16)]


def test_acceleration_overrides_accept_legacy_physical_names() -> None:
    legacy = "first_c_channel_rotor"
    canonical = normalizePhysicalStepperBindingName(legacy)
    overrides = _parseStepperAccelerationOverrides(_gc(), {"stepper_acceleration_overrides": {legacy: 20000, "chute": 5000, "bad": -1}})
    assert overrides[canonical] == 20000
    assert overrides["chute"] == 5000
    assert "bad" not in overrides
