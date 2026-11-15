"""The feeder's drive: a geared feeder (130:12) or a direct-drive one, and the
defaults that follow it: the feeder motors' current and direction, their
speeds and accelerations, the feeder's move speeds and autotune bounds, and
the shakes, each scaled so the channels move as they do on the geared feeder."""

from __future__ import annotations

import pytest

import machine_toml
from hardware_settings.feeder import DIRECT, DRIVES, GEARED, GEARED_RATIO, driveSaved, feederDrive, saveFeederDrive
from hardware_settings.motors import motorNamed
from hardware_settings.steppers import readStepperSettings
from irl.config import (
    FEEDER_MOTOR_DEFAULT_STEPS_PER_SECOND,
    FIRMWARE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ,
    IRLConfig,
    setFeederStepperConfigs,
)
from recovery.profiles import TUNED_GEAR_RATIO, forGearing, shakeProfile
from subsystems.feeder.pulse_perception import autotune
from subsystems.feeder.pulse_perception.config import (
    PulsePerceptionConfig,
    configFromDict,
    defaultConfig,
    fieldMeta,
)
from subsystems.distribution.chute_variants import SLIP_RING

DIRECT_FEEDER = {"feeder": {"drive": "direct"}}


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine.toml of the test's own, written with `write`."""
    path = tmp_path / "machine.toml"
    monkeypatch.setenv(machine_toml.ENV_VAR, str(path))

    def write(text: str) -> None:
        path.write_text(text, encoding="utf-8")

    write("")
    return write


def test_no_feeder_table_is_the_geared_feeder() -> None:
    assert feederDrive({}).name == GEARED
    assert feederDrive({}).gear_ratio == pytest.approx(130 / 12)


def test_a_direct_drive_feeder_turns_its_channels_one_to_one() -> None:
    assert feederDrive(DIRECT_FEEDER).gear_ratio == 1.0


def test_an_unknown_drive_is_taken_as_geared_with_a_warning() -> None:
    logger = _Logger()
    assert feederDrive({"feeder": {"drive": "belt"}}, logger).name == GEARED
    assert "belt" in logger.warnings[0]


def test_a_rate_tuned_on_the_geared_feeder_turns_a_direct_channel_as_fast() -> None:
    assert DRIVES[GEARED].motorRate(2000) == 2000
    assert DRIVES[DIRECT].motorRate(2000) == round(2000 / GEARED_RATIO) == 185


def test_direct_drive_raises_the_feeder_motors_current_and_flips_c1() -> None:
    c1 = readStepperSettings(motorNamed("c_channel_1"), DIRECT_FEEDER)
    c2 = readStepperSettings(motorNamed("c_channel_2"), DIRECT_FEEDER)
    assert (c1.irun, c1.inverted) == (16, True)
    assert (c2.irun, c2.inverted) == (16, False)
    assert "irun" not in c1.saved and "inverted" not in c1.saved


def test_the_geared_feeder_keeps_its_defaults_and_other_motors_ignore_the_drive() -> None:
    c1 = readStepperSettings(motorNamed("c_channel_1"), {})
    assert (c1.irun, c1.inverted) == (4, False)
    assert readStepperSettings(motorNamed("carousel"), DIRECT_FEEDER).irun == 8


def test_saved_settings_win_over_the_drive() -> None:
    config = {
        **DIRECT_FEEDER,
        "stepper_direction_inverts": {"c_channel_1": False},
        "stepper_current_overrides": {"c_channel_1_rotor": {"irun": 24, "ihold": 1, "ihold_delay": 8}},
    }
    c1 = readStepperSettings(motorNamed("c_channel_1"), config)
    assert (c1.irun, c1.inverted) == (24, False)


def test_the_feeder_motors_speed_limit_and_acceleration_follow_the_drive() -> None:
    irl_config = IRLConfig()
    setFeederStepperConfigs(irl_config, DRIVES[DIRECT])
    stepper = irl_config.c_channel_2_rotor_stepper
    assert stepper.default_steps_per_second == round(FEEDER_MOTOR_DEFAULT_STEPS_PER_SECOND / GEARED_RATIO)
    assert stepper.acceleration_microsteps_per_second_sq == round(
        FIRMWARE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ / GEARED_RATIO
    )
    setFeederStepperConfigs(irl_config, DRIVES[GEARED])
    assert irl_config.c_channel_2_rotor_stepper.default_steps_per_second == FEEDER_MOTOR_DEFAULT_STEPS_PER_SECOND


def test_feeder_move_speeds_default_to_the_drive_and_saved_ones_win(machine) -> None:
    geared = PulsePerceptionConfig()
    assert defaultConfig(DRIVES[GEARED]).ch2_move_speed_usteps_per_s == geared.ch2_move_speed_usteps_per_s
    machine('[feeder]\ndrive = "direct"\n')
    direct_speed = round(geared.ch2_move_speed_usteps_per_s / GEARED_RATIO)
    assert defaultConfig().ch2_move_speed_usteps_per_s == direct_speed
    assert configFromDict({}).ch2_move_speed_usteps_per_s == direct_speed
    assert configFromDict({"ch2_move_speed_usteps_per_s": 300}).ch2_move_speed_usteps_per_s == 300
    meta = {field["key"]: field for field in fieldMeta()}
    assert meta["ch2_move_speed_usteps_per_s"]["default"] == direct_speed
    # Distances are in channel degrees, the same on every drive.
    assert defaultConfig().drop_pulse_output_deg == geared.drop_pulse_output_deg


def test_autotune_searches_the_same_channel_speeds_on_a_direct_drive(machine) -> None:
    machine('[feeder]\ndrive = "direct"\n')
    bounds = {meta["key"]: meta for meta in autotune.tunableParams()}
    assert bounds["ch1_move_speed_usteps_per_s"]["min"] == round(800 / GEARED_RATIO)
    assert bounds["ch1_move_speed_usteps_per_s"]["max"] == round(5000 / GEARED_RATIO)
    assert bounds["drop_pulse_output_deg"]["max"] == 90.0


def test_a_shake_moves_a_direct_drive_channel_as_it_moves_a_geared_one() -> None:
    brief = shakeProfile("brief")
    assert forGearing(brief, TUNED_GEAR_RATIO) is brief
    direct = forGearing(brief, 1.0)
    assert direct.amplitude_deg == pytest.approx(brief.amplitude_deg / TUNED_GEAR_RATIO)
    assert direct.speed == round(brief.speed / TUNED_GEAR_RATIO)
    assert direct.acceleration == round(brief.acceleration / TUNED_GEAR_RATIO)
    assert direct.cycles == brief.cycles


def test_a_board_writes_down_its_drive_once(machine) -> None:
    assert not driveSaved()
    saveFeederDrive(DIRECT)
    assert driveSaved()
    assert feederDrive().name == DIRECT
    with pytest.raises(ValueError):
        saveFeederDrive("belt")


def test_the_sorter_v3_has_four_layers() -> None:
    assert SLIP_RING.layer_bins == (24, 18, 12, 6)
