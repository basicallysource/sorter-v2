"""A setting saved the way the API saves it is what the hardware gets at the
next start, read back under the key it was saved under.

Each test saves through a route function, then runs hardware start-up
(irl.config._bindHardware with mkIRLConfig, as main.py does) against fake
boards that read the same machine.toml, and checks what reached the drivers,
the servos and the chute.
"""

from __future__ import annotations

import tomllib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from hardware_settings.motors import MOTORS
from hardware_settings.steppers import readStepperSettings, saveStepperSettings
from irl.config import IRLInterface, _bindHardware, mkIRLConfig
from irl.bin_layout import getBinLayout
from machine_platform.control_board import BoardIdentity, DiscoveredStepper
from server import shared_state
from server.routers import chute as chute_routes
from server.routers import servos as servo_routes
from server.routers import setup as setup_routes
from server.routers import stallguard as stallguard_routes
from server.routers import steppers as stepper_routes
from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter

TMC_GCONF = 0x00
TMC_IFCNT = 0x02
TMC_TCOOLTHRS = 0x14
TMC_SGTHRS = 0x40
TMC_COOLCONF = 0x42

# One board drives all five motors, wired the way the kit's distribution board is.
SOCKETS = ["chute_stepper", "c_channel_1_rotor", "c_channel_3_rotor", "carousel", "c_channel_2_rotor"]


class _Logger:
    """Keeps the lines start-up logs, which are what a person reads back."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str, *_args, **_kwargs) -> None:
        self.lines.append(str(message))

    warning = warn = error = debug = info


class _Driver:
    """A stepper on a TMC2209 that keeps what it was sent."""

    def __init__(self, channel: int) -> None:
        self.channel = channel
        self.current_position_steps = 0
        self.position_degrees = 0.0
        self.registers: dict[int, int] = {}
        self.ifcnt = 0
        self.microsteps: int | None = None
        self.last_set_current: dict[str, int] | None = None
        self.speed_limits: tuple[int, int] | None = None
        self.moves: list[tuple[float, tuple[int, int] | None]] = []
        self.direction_inverted = False
        self.stallguard_sgthrs: int | None = None
        self.stallguard_tcoolthrs = 0xFFFFF
        self.stallguard_enabled = False
        self.detection_on = False
        self.stalled = False

    def _took(self) -> None:
        self.ifcnt = (self.ifcnt + 1) % 256

    def read_driver_register(self, address: int) -> int:
        return self.ifcnt if address == TMC_IFCNT else self.registers.get(address, 0)

    def write_driver_register(self, address: int, value: int) -> None:
        self.registers[address] = value
        self._took()

    def set_microsteps(self, microsteps: int) -> None:
        self.microsteps = microsteps
        self._took()

    def set_current(self, irun: int, ihold: int, ihold_delay: int) -> None:
        self.last_set_current = {"irun": irun, "ihold": ihold, "ihold_delay": ihold_delay}
        self._took()

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits = (min_speed, max_speed)

    def set_default_acceleration(self, _acceleration: int) -> None:
        pass

    def set_acceleration(self, _acceleration: int) -> None:
        pass

    def clear_stall(self) -> None:
        pass

    def enable_stall_detection(self, enable: bool) -> None:
        self.detection_on = enable

    def set_hardware_name(self, name: str) -> None:
        self.hardware_name = name

    def set_name(self, name: str) -> None:
        self.name = name

    def set_direction_inverted(self, inverted: bool) -> None:
        self.direction_inverted = inverted

    def estimateMoveDegreesMs(self, _degrees: float, max_speed: int = 5000) -> int:
        return 100

    def move_degrees(self, degrees: float, **_kwargs) -> bool:
        self.moves.append((degrees, self.speed_limits))
        return True


class _Board:
    """A distribution board whose sockets each hold a driver."""

    servos = ()
    input_aliases = {"chute_home": 0}
    chute_home_active_high = False

    def __init__(self, sockets: list[str]) -> None:
        self.identity = BoardIdentity("basically_rp2040", "distribution", "DISTRIBUTION MB", "/dev/board", 0)
        self.interface = SimpleNamespace(name="DISTRIBUTION MB")
        self.board_key = "distribution"
        self.drivers = {socket: _Driver(channel) for channel, socket in enumerate(sockets)}
        self._steppers = tuple(DiscoveredStepper(socket, socket, driver) for socket, driver in self.drivers.items())

    @property
    def logical_stepper_names(self) -> tuple[str, ...]:
        return tuple(stepper.canonical_name for stepper in self._steppers)

    def iter_steppers(self) -> tuple[DiscoveredStepper, ...]:
        return self._steppers

    def get_input(self, channel: int) -> SimpleNamespace:
        return SimpleNamespace(channel=channel, value=False)


class _Servo:
    """A PCA9685 layer servo that keeps the speeds it was given."""

    def __init__(self) -> None:
        self.speeds: tuple | None = None
        self.limits: tuple[int, int] | None = None

    def set_preset_angles(self, *_angles) -> None:
        pass

    def set_motion_speeds(self, open_speed, close_speed, homing_speed) -> None:
        self.speeds = (open_speed, close_speed, homing_speed)

    def apply_homing_speed(self) -> None:
        if self.speeds is not None and self.speeds[2] is not None:
            self.limits = (10, self.speeds[2] * 10)

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.limits = (min_speed, max_speed)


@pytest.fixture(autouse=True)
def machine(tmp_path, monkeypatch):
    path = tmp_path / "machine.toml"
    path.write_text("")
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(path))
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    # The hardware is down unless a test brings up a running motor.
    monkeypatch.setattr(shared_state, "controller_ref", None)
    monkeypatch.setattr(shared_state, "hardware_runtime_irl", None)
    return path


def _saved(path) -> dict:
    return tomllib.loads(path.read_text())


def _start(board: _Board, servos: list[_Servo] | None = None, logger: _Logger | None = None) -> IRLInterface:
    """Hardware start-up as main.py runs it, against the fake board."""
    gc = SimpleNamespace(
        logger=logger or _Logger(),
        no_power_development_mode=False,
        disable_c_channels=[],
        disable_carousel=False,
        disable_servos=False,
        disable_chute=False,
    )
    servo_controller = SimpleNamespace(create_layer_servos=lambda _layout: list(servos or []))
    irl = IRLInterface()
    with (
        patch("irl.config.MCUBus.enumerate_buses", return_value=[]),
        patch("irl.config.discover_control_boards", return_value=[board]),
        patch("irl.config.discoverLedOutputs", return_value=[]),
        patch("irl.config.LedController"),
        patch("irl.config.build_servo_controller", return_value=servo_controller),
        patch("irl.config.time.sleep"),
    ):
        _bindHardware(irl, mkIRLConfig(), gc)
    return irl


def test_a_driver_current_saved_through_the_api_is_what_the_motor_gets_at_start(machine) -> None:
    response = stepper_routes.set_tmc_settings("chute", stepper_routes.TmcSettingsRequest(irun=24, ihold=4))

    assert response["hardware_ready"] is False
    assert (response["irun"], response["ihold"]) == (24, 4)
    assert _saved(machine)["stepper_current_overrides"]["chute_stepper"] == {"irun": 24, "ihold": 4, "ihold_delay": 8}
    board = _Board(SOCKETS)
    log = _Logger()
    irl = _start(board, logger=log)
    assert irl.chute_stepper is board.drivers["chute_stepper"]
    assert board.drivers["chute_stepper"].last_set_current == {"irun": 24, "ihold": 4, "ihold_delay": 8}
    configured = next(line for line in log.lines if line.startswith("Stepper 'chute' configured"))
    assert "IRUN=24 IHOLD=4 IHOLD_DELAY=8" in configured
    assert "from machine.toml: ihold, ihold_delay, irun" in configured
    assert configured.endswith("driver took 6 writes")


def test_a_motor_with_nothing_saved_gets_its_built_in_current_and_the_api_shows_that(machine) -> None:
    board = _Board(SOCKETS)
    _start(board)

    assert board.drivers["c_channel_1_rotor"].last_set_current == {"irun": 4, "ihold": 1, "ihold_delay": 8}
    assert board.drivers["carousel"].last_set_current == {"irun": 8, "ihold": 1, "ihold_delay": 8}
    assert board.drivers["chute_stepper"].last_set_current == {"irun": 16, "ihold": 4, "ihold_delay": 8}
    shown = stepper_routes.get_tmc_settings("c_channel_1")
    assert (shown["irun"], shown["ihold"], shown["saved"]) == (4, 1, [])


def test_microstepping_chopper_mode_and_coolstep_are_saved_and_applied_at_start(machine) -> None:
    stepper_routes.set_tmc_settings(
        "c_channel_2", stepper_routes.TmcSettingsRequest(microsteps=16, stealthchop=False, coolstep=True)
    )

    assert _saved(machine)["stepper_driver"]["c_channel_2_rotor"] == {
        "microsteps": 16,
        "stealthchop": False,
        "coolstep": True,
    }
    board = _Board(SOCKETS)
    _start(board)
    changed = board.drivers["c_channel_2_rotor"]
    assert changed.microsteps == 16
    assert changed.registers[TMC_GCONF] == 0x1C0 | 0x4  # SpreadCycle
    assert changed.registers[TMC_COOLCONF] == 0x225
    assert changed.registers[TMC_TCOOLTHRS] == 0xFFFFF  # CoolStep alone runs at every speed
    untouched = board.drivers["c_channel_1_rotor"]
    assert untouched.microsteps == 8
    assert untouched.registers[TMC_GCONF] == 0x1C0
    assert untouched.registers[TMC_COOLCONF] == 0


def test_stall_detection_saved_through_the_api_is_armed_at_start(machine) -> None:
    stallguard_routes.set_stallguard_config(
        "carousel", stallguard_routes.StallGuardConfigBody(sgthrs=90, tcoolthrs=180, enabled=True)
    )
    stepper_routes.set_tmc_settings("carousel", stepper_routes.TmcSettingsRequest(coolstep=True))
    stallguard_routes.set_stallguard_config("chute", stallguard_routes.StallGuardConfigBody(enabled=False))

    assert _saved(machine)["stepper_stallguard"]["carousel"] == {
        "enabled": True, "auto": False, "sgthrs": 90, "tcoolthrs": 180,
    }
    board = _Board(SOCKETS)
    _start(board)
    carousel = board.drivers["carousel"]
    assert carousel.registers[TMC_SGTHRS] == 90
    assert carousel.registers[TMC_TCOOLTHRS] == 180  # StallGuard's speed floor, CoolStep or not
    assert (carousel.stallguard_enabled, carousel.detection_on, carousel.stallguard_sgthrs) == (True, True, 90)
    chute = board.drivers["chute_stepper"]
    assert (chute.stallguard_enabled, chute.detection_on) == (False, False)
    assert chute.registers[TMC_TCOOLTHRS] == 0


def test_a_direction_saved_for_c4_inverts_the_carousel_motor_at_start(machine) -> None:
    setup_routes.set_stepper_direction("c_channel_4", setup_routes.StepperDirectionPayload(inverted=True))

    assert _saved(machine)["stepper_direction_inverts"] == {"carousel": True}
    board = _Board(SOCKETS)
    _start(board)
    assert board.drivers["carousel"].direction_inverted is True
    assert board.drivers["chute_stepper"].direction_inverted is False


def test_a_motor_wired_to_another_socket_keeps_its_saved_settings(machine) -> None:
    machine.write_text('[stepper_bindings]\nchute = "distribution_aux_1"\n')
    stepper_routes.set_tmc_settings("chute", stepper_routes.TmcSettingsRequest(irun=20, ihold=5))

    board = _Board(SOCKETS + ["distribution_aux_1"])
    irl = _start(board)
    rewired = board.drivers["distribution_aux_1"]
    assert irl.chute_stepper is rewired
    assert rewired.last_set_current == {"irun": 20, "ihold": 5, "ihold_delay": 8}
    assert board.drivers["chute_stepper"].last_set_current is None


def test_older_keys_are_read_and_a_save_folds_them_into_one_entry(machine) -> None:
    machine.write_text("[stepper_current_overrides.first_c_channel_rotor]\nirun = 10\n")
    board = _Board(SOCKETS)
    _start(board)
    # A key an entry leaves out keeps the meaning it always had (IHOLD 4).
    assert board.drivers["c_channel_1_rotor"].last_set_current == {"irun": 10, "ihold": 4, "ihold_delay": 8}

    stepper_routes.set_tmc_settings("c_channel_1", stepper_routes.TmcSettingsRequest(ihold=2))

    assert _saved(machine)["stepper_current_overrides"] == {
        "c_channel_1_rotor": {"irun": 10, "ihold": 2, "ihold_delay": 8},
    }
    board = _Board(SOCKETS)
    _start(board)
    assert board.drivers["c_channel_1_rotor"].last_set_current == {"irun": 10, "ihold": 2, "ihold_delay": 8}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("irun", 21),
        ("ihold", 7),
        ("ihold_delay", 3),
        ("microsteps", 32),
        ("stealthchop", False),
        ("coolstep", True),
        ("stallguard", True),
        ("sgthrs", 77),
        ("tcoolthrs", 333),
        ("inverted", True),
    ],
)
def test_every_stepper_setting_reads_back_under_the_key_it_was_saved_under(machine, name, value) -> None:
    for motor in MOTORS:
        saveStepperSettings(motor, {name: value})
        settings = readStepperSettings(motor)
        assert getattr(settings, name) == value, motor.name
        assert name in settings.saved, motor.name


def test_an_out_of_range_setting_is_refused_and_nothing_is_saved(machine) -> None:
    with pytest.raises(HTTPException) as caught:
        stepper_routes.set_tmc_settings("chute", stepper_routes.TmcSettingsRequest(irun=40, ihold=3))

    assert caught.value.status_code == 400
    assert _saved(machine) == {}


def test_a_change_reaches_the_running_driver_without_dropping_stall_detection(machine, monkeypatch) -> None:
    driver = _Driver(0)
    driver.stallguard_enabled = True  # the chute's built-in StallGuard, armed at start
    monkeypatch.setattr(shared_state, "hardware_runtime_irl", SimpleNamespace(chute_stepper=driver))

    response = stepper_routes.set_tmc_settings("chute", stepper_routes.TmcSettingsRequest(irun=26, coolstep=False))

    assert driver.last_set_current == {"irun": 26, "ihold": 4, "ihold_delay": 8}
    assert driver.registers[TMC_COOLCONF] == 0
    assert driver.registers[TMC_TCOOLTHRS] == 150  # StallGuard's floor stays, not 0
    assert response["hardware_ready"] is True
    assert response["driver"]["irun"] == 26
    assert _saved(machine)["stepper_current_overrides"]["chute_stepper"]["irun"] == 26


def test_a_change_the_running_driver_refuses_is_not_saved(machine, monkeypatch) -> None:
    # Saved anyway, it would stop the next start on the same refusal.
    class _NoDiagWire(_Driver):
        def enable_stall_detection(self, enable: bool) -> None:
            raise RuntimeError("No DIAG pin on channel 4")

    driver = _NoDiagWire(4)
    monkeypatch.setattr(shared_state, "hardware_runtime_irl", SimpleNamespace(c_channel_2_rotor_stepper=driver))

    with pytest.raises(HTTPException) as caught:
        stallguard_routes.set_stallguard_config(
            "c_channel_2", stallguard_routes.StallGuardConfigBody(sgthrs=60, tcoolthrs=150, enabled=True)
        )

    assert caught.value.status_code == 502
    assert _saved(machine) == {}
    assert driver.stallguard_enabled is False


def test_the_chute_runs_at_its_saved_operating_speed_from_the_first_move_after_start(machine) -> None:
    chute_routes.save_chute_hardware_config(
        chute_routes.ChuteHardwareSettingsPayload(operating_speed_microsteps_per_second=1500)
    )

    assert _saved(machine)["chute"]["operating_speed_microsteps_per_second"] == 1500
    board = _Board(SOCKETS)
    log = _Logger()
    irl = _start(board, logger=log)
    assert any(line.startswith("Chute configured:") and "operating speed 1500 µsteps/s" in line for line in log.lines)
    stepper = board.drivers["chute_stepper"]
    assert stepper.speed_limits == (16, 3000)  # start-up's limit, before any chute move
    irl.chute.moveToAngle(60.0)
    assert stepper.moves[-1][1] == (16, 1500)
    stepper.set_speed_limits(16, 800)  # a jog leaves its own speed behind
    irl.chute.moveToAngle(120.0)
    assert stepper.moves[-1][1] == (16, 1500)


def test_saving_the_chute_from_the_setup_wizard_keeps_its_saved_speed(machine) -> None:
    machine.write_text("[chute]\noperating_speed_microsteps_per_second = 1500\n")

    # The setup wizard's calibration step sends these three and no speed.
    chute_routes.save_chute_hardware_config(
        chute_routes.ChuteHardwareSettingsPayload(first_bin_center=58.23, pillar_width_deg=8.88, endstop_active_high=True)
    )

    saved = _saved(machine)["chute"]
    assert saved["operating_speed_microsteps_per_second"] == 1500
    assert saved["first_section_offset_deg"] == 58.23
    assert saved["section_width_deg"] == round(60 - 8.88, 4)
    board = _Board(SOCKETS)
    irl = _start(board)
    assert irl.chute.operating_speed_microsteps_per_second == 1500
    assert irl.chute.first_section_offset_deg == 58.23


def test_servo_speeds_survive_the_setup_wizards_servo_save_and_apply_at_start(machine) -> None:
    servo_routes.save_servo_speeds(
        servo_routes.ServoSpeedSettingsPayload(open_speed=300, close_speed=400, homing_speed=500)
    )
    layer_count = len(getBinLayout().layers)

    # The setup wizard's servo step saves the wiring and sends no speeds.
    servo_routes.save_servo_hardware_config(
        servo_routes.ServoHardwareSettingsPayload(
            backend="pca9685",
            channels=[{"id": index, "invert": False} for index in range(layer_count)],
        )
    )

    saved = _saved(machine)["servo"]
    assert (saved["open_speed"], saved["close_speed"], saved["homing_speed"]) == (300, 400, 500)
    servos = [_Servo() for _ in range(layer_count)]
    _start(_Board(SOCKETS), servos)
    for servo in servos:
        assert servo.speeds == (300, 400, 500)
        assert servo.limits == (10, 5000)


def test_a_servo_speed_put_back_to_default_is_the_firmware_default_live_and_at_start(machine, monkeypatch) -> None:
    machine.write_text("[servo]\nhoming_speed = 500\n")
    live = _Servo()
    live.set_motion_speeds(None, None, 500)
    monkeypatch.setattr(shared_state, "hardware_runtime_irl", SimpleNamespace(servos=[live]))

    servo_routes.save_servo_speeds(servo_routes.ServoSpeedSettingsPayload(homing_speed=None))

    assert "homing_speed" not in _saved(machine).get("servo", {})
    assert live.limits == (10, 15000)
    monkeypatch.setattr(shared_state, "hardware_runtime_irl", None)
    servos = [_Servo() for _ in range(len(getBinLayout().layers))]
    _start(_Board(SOCKETS), servos)
    assert all(servo.limits == (10, 15000) for servo in servos)


def test_the_c4_platter_converts_with_the_carousels_saved_microstepping(machine) -> None:
    assert C4FiveSectorPlatter.from_irl_config(SimpleNamespace()).microsteps == 8

    stepper_routes.set_tmc_settings("c_channel_4", stepper_routes.TmcSettingsRequest(microsteps=16))

    assert _saved(machine)["stepper_driver"]["carousel"]["microsteps"] == 16
    assert C4FiveSectorPlatter.from_irl_config(SimpleNamespace()).microsteps == 16
