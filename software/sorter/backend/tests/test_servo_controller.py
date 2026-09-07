import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import types
import unittest
from unittest.mock import patch


serial_stub = types.ModuleType("serial")
serial_tools_stub = types.ModuleType("serial.tools")
serial_list_ports_stub = types.ModuleType("serial.tools.list_ports")
serial_list_ports_stub.comports = lambda: []
serial_tools_stub.list_ports = serial_list_ports_stub
serial_stub.tools = serial_tools_stub

global_config_stub = types.ModuleType("global_config")
global_config_stub.GlobalConfig = object

irl_stub = types.ModuleType("irl")
parse_user_toml_stub = types.ModuleType("irl.parse_user_toml")
parse_user_toml_stub.ServoChannelConfig = object
parse_user_toml_stub.WaveshareServoConfig = object
irl_stub.parse_user_toml = parse_user_toml_stub

machine_platform_stub = types.ModuleType("machine_platform")
control_board_stub = types.ModuleType("machine_platform.control_board")
control_board_stub.ControlBoard = object
machine_platform_stub.control_board = control_board_stub

_stubs = {
    "serial": serial_stub,
    "serial.tools": serial_tools_stub,
    "serial.tools.list_ports": serial_list_ports_stub,
    "global_config": global_config_stub,
    "irl": irl_stub,
    "irl.parse_user_toml": parse_user_toml_stub,
    "machine_platform": machine_platform_stub,
    "machine_platform.control_board": control_board_stub,
}
_installed = [name for name, stub in _stubs.items() if sys.modules.setdefault(name, stub) is stub]

module_path = Path(__file__).resolve().parents[1] / "machine_platform" / "servo_controller.py"
spec = importlib.util.spec_from_file_location("servo_controller_under_test", module_path)
assert spec is not None and spec.loader is not None
servo_controller = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = servo_controller
try:
    spec.loader.exec_module(servo_controller)
finally:
    # The loaded module keeps references to the stubs; drop them from
    # sys.modules so other test modules import the real packages.
    for name in _installed:
        del sys.modules[name]

LayerServoAssignment = servo_controller.LayerServoAssignment
WaveshareServoController = servo_controller.WaveshareServoController


class _Logger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []

    def info(self, msg, *_args, **_kwargs) -> None:
        self.infos.append(str(msg))

    def warning(self, msg, *_args, **_kwargs) -> None:
        self.warnings.append(str(msg))


class WaveshareServoControllerTests(unittest.TestCase):
    def test_missing_trailing_assignments_are_treated_as_unassigned(self) -> None:
        controller = WaveshareServoController(
            SimpleNamespace(logger=_Logger()),
            port=None,
            assignments=[
                LayerServoAssignment(id=2, invert=True),
                LayerServoAssignment(id=None, invert=False),
            ],
            mcu_ports=[],
        )
        layout = SimpleNamespace(
            layers=[
                SimpleNamespace(enabled=True),
                SimpleNamespace(enabled=False),
                SimpleNamespace(enabled=False),
                SimpleNamespace(enabled=False),
            ]
        )

        assignments = controller._iter_layer_assignments(layout)

        self.assertEqual(4, len(assignments))
        self.assertEqual(2, assignments[0][1].id)
        self.assertIsNone(assignments[1][1].id)
        self.assertIsNone(assignments[2][1].id)
        self.assertIsNone(assignments[3][1].id)


class WaveshareResolvePortTests(unittest.TestCase):
    def _mk_controller(self, *, port: str | None = None, mcu_ports: list[str] | None = None):
        logger = _Logger()
        controller = WaveshareServoController(
            SimpleNamespace(logger=logger),
            port=port,
            assignments=[],
            mcu_ports=mcu_ports or [],
        )
        return controller, logger

    def test_configured_port_upgrades_to_stable_by_id_path(self) -> None:
        controller, logger = self._mk_controller(port="/dev/ttyACM0")
        stable = {"/dev/ttyACM0": "/dev/serial/by-id/usb-waveshare-bus"}
        with (
            patch.object(servo_controller, "stable_port_path", side_effect=lambda d: stable.get(d, d)),
            patch.object(servo_controller.os.path, "exists", return_value=True),
        ):
            self.assertEqual("/dev/serial/by-id/usb-waveshare-bus", controller._resolve_port())
        self.assertEqual([], logger.infos)

    def test_configured_missing_port_is_returned_but_logged(self) -> None:
        controller, logger = self._mk_controller(port="/dev/ttyACM7")
        with (
            patch.object(servo_controller, "stable_port_path", side_effect=lambda d: d),
            patch.object(servo_controller.os.path, "exists", return_value=False),
        ):
            self.assertEqual("/dev/ttyACM7", controller._resolve_port())
        self.assertTrue(any("/dev/ttyACM7" in msg for msg in logger.infos))

    def test_auto_detect_excludes_picos_and_mcu_ports_via_canonical_path(self) -> None:
        # The MCU is excluded by its by-id path even though comports() reports
        # the raw /dev/ttyACM node.
        controller, logger = self._mk_controller(mcu_ports=["/dev/serial/by-id/usb-mcu"])
        canonical = {"/dev/serial/by-id/usb-mcu": "/dev/ttyACM1"}
        comports = [
            SimpleNamespace(device="/dev/ttyACM2", vid=0x1234),
            SimpleNamespace(device="/dev/ttyACM0", vid=0x2E8A),  # Pico
            SimpleNamespace(device="/dev/ttyACM1", vid=0x5678),  # MCU twin
            SimpleNamespace(device="/dev/ttyACM3", vid=None),
        ]
        with (
            patch.object(servo_controller, "stable_port_path", side_effect=lambda d: d),
            patch.object(servo_controller, "canonical_port_path", side_effect=lambda p: canonical.get(p, p)),
            patch.object(servo_controller.serial.tools.list_ports, "comports", return_value=comports),
        ):
            self.assertEqual("/dev/ttyACM2", controller._resolve_port())
        self.assertEqual([], logger.warnings)

    def test_auto_detect_picks_first_sorted_stable_path_and_warns_on_ambiguity(self) -> None:
        controller, logger = self._mk_controller()
        stable = {
            "/dev/ttyACM5": "/dev/serial/by-id/usb-bus-b",
            "/dev/ttyACM2": "/dev/serial/by-id/usb-bus-a",
        }
        comports = [
            SimpleNamespace(device="/dev/ttyACM5", vid=0x1234),
            SimpleNamespace(device="/dev/ttyACM2", vid=0x1234),
        ]
        with (
            patch.object(servo_controller, "stable_port_path", side_effect=lambda d: stable[d]),
            patch.object(servo_controller, "canonical_port_path", side_effect=lambda p: p),
            patch.object(servo_controller.serial.tools.list_ports, "comports", return_value=comports),
        ):
            self.assertEqual("/dev/serial/by-id/usb-bus-a", controller._resolve_port())
        self.assertEqual(1, len(logger.warnings))
        self.assertIn("/dev/serial/by-id/usb-bus-b", logger.warnings[0])

    def test_auto_detect_without_candidates_returns_none(self) -> None:
        controller, _logger = self._mk_controller()
        with (
            patch.object(servo_controller.serial.tools.list_ports, "comports", return_value=[]),
        ):
            self.assertIsNone(controller._resolve_port())


if __name__ == "__main__":
    unittest.main()
