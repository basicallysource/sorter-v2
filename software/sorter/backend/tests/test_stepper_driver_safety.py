import unittest

from hardware.tmc2209_status import (
    active_temperature_flags,
    overtemperature_fault_flags,
    parse_drv_status,
)
from irl.parse_user_toml import (
    StepperDriverOverride,
    applyStepperDriverOverride,
    loadMachineConfig,
)
from rt.services.stepper_thermal_guard import StepperThermalGuard


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str, *args) -> None:
        self.errors.append(msg % args if args else msg)

    def warning(self, msg: str, *args) -> None:
        self.warnings.append(msg % args if args else msg)

    def info(self, msg: str, *args) -> None:
        self.infos.append(msg % args if args else msg)


class _GC:
    def __init__(self) -> None:
        self.logger = _Logger()


class _Stepper:
    def __init__(self, raw_status: int = 0) -> None:
        self.raw_status = raw_status
        self.writes: list[tuple[int, int]] = []
        self.speeds: list[int] = []
        self.enabled = True

    def read_driver_register(self, address: int) -> int:
        if address == 0x00:
            return 0
        return self.raw_status

    def write_driver_register(self, address: int, value: int) -> None:
        self.writes.append((address, value))

    def set_microsteps(self, microsteps: int) -> None:
        self.microsteps = microsteps

    def move_at_speed(self, speed: int) -> bool:
        self.speeds.append(speed)
        return True


class Tmc2209StatusTests(unittest.TestCase):
    def test_parse_drv_status_exposes_overtemperature_flags(self) -> None:
        status = parse_drv_status((1 << 0) | (1 << 1) | (1 << 11))

        self.assertTrue(status["otpw"])
        self.assertTrue(status["ot"])
        self.assertTrue(status["t157"])
        self.assertEqual(["ot", "otpw"], overtemperature_fault_flags(status))
        self.assertEqual(["ot", "otpw", "t157"], active_temperature_flags(status))


class StepperDriverConfigTests(unittest.TestCase):
    def test_load_machine_config_parses_driver_overrides(self) -> None:
        config = loadMachineConfig(
            _GC(),
            {
                "stepper_driver_overrides": {
                    "c_channel_2_rotor": {
                        "microsteps": 8,
                        "coolstep": True,
                        "stealthchop": False,
                    }
                }
            },
        )

        override = config.stepper_driver_overrides["c_channel_2_rotor"]
        self.assertEqual(8, override.microsteps)
        self.assertTrue(override.coolstep)
        self.assertFalse(override.stealthchop)

    def test_apply_driver_override_writes_coolstep_registers(self) -> None:
        stepper = _Stepper()

        applyStepperDriverOverride(
            stepper,
            "c_channel_2_rotor",
            {"c_channel_2_rotor": StepperDriverOverride(microsteps=8, coolstep=True)},
            _GC(),
        )

        self.assertEqual(8, getattr(stepper, "microsteps", None))
        self.assertIn((0x00, 1 << 2), stepper.writes)
        self.assertIn((0x42, 0x225), stepper.writes)
        self.assertIn((0x14, 0xFFFFF), stepper.writes)

    def test_apply_driver_override_uses_exclusive_stealthchop_mode(self) -> None:
        stepper = _Stepper()

        applyStepperDriverOverride(
            stepper,
            "c_channel_2_rotor",
            {"c_channel_2_rotor": StepperDriverOverride(stealthchop=True)},
            _GC(),
        )

        self.assertIn((0x42, 0), stepper.writes)
        self.assertIn((0x14, 0), stepper.writes)
        self.assertIn((0x00, 0), stepper.writes)


class StepperThermalGuardTests(unittest.TestCase):
    def test_check_once_reports_prewarn_as_fault(self) -> None:
        faults = []
        guard = StepperThermalGuard(
            steppers={"c_channel_2": _Stepper(raw_status=1 << 0)},
            on_fault=faults.append,
            logger=_Logger(),
            interval_s=1.0,
        )

        fault = guard.check_once()

        self.assertIsNotNone(fault)
        assert fault is not None
        self.assertEqual("c_channel_2", fault.stepper_name)
        self.assertEqual(("otpw",), fault.fault_flags)

    def test_halt_all_stops_motion_and_disables_stepper(self) -> None:
        stepper = _Stepper()
        guard = StepperThermalGuard(
            steppers={"c_channel_2": stepper},
            on_fault=lambda _fault: None,
            logger=_Logger(),
        )

        guard._halt_all()

        self.assertEqual([0], stepper.speeds)
        self.assertFalse(stepper.enabled)


if __name__ == "__main__":
    unittest.main()
