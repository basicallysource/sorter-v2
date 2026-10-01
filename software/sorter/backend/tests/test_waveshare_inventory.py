from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import machine_toml
from server import shared_state
from server.waveshare_inventory import WaveshareInventoryManager


class WaveshareInventoryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._hardware_state = shared_state.hardware_state
        self._tmpdir = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {machine_toml.ENV_VAR: str(Path(self._tmpdir.name) / "machine.toml")},
        )
        self._env.start()

    def tearDown(self) -> None:
        shared_state.hardware_state = self._hardware_state
        self._env.stop()
        self._tmpdir.cleanup()

    def _config(self, data: dict) -> None:
        with machine_toml.edit() as config:
            config.update(data)

    def test_refresh_caches_ports_and_servos_for_configured_port(self) -> None:
        self._config({"servo": {"port": "/dev/ttyUSB0"}})

        fake_service = Mock()
        fake_service.list_servo_infos.return_value = (
            [1, 3],
            [
                {"id": 1, "model_name": "SC15"},
                {"id": 3, "model_name": "SC15"},
            ],
        )

        shared_state.hardware_state = "standby"
        with (
            patch("server.waveshare_inventory.shared_state.getActiveIRL", return_value=None),
            patch(
                "server.waveshare_inventory.serial.tools.list_ports.comports",
                return_value=[
                    SimpleNamespace(
                        device="/dev/ttyUSB0",
                        product="USB Serial",
                        serial_number="ABC123",
                        vid=0x1234,
                    )
                ],
            ),
            patch("server.waveshare_inventory.get_waveshare_bus_service", return_value=fake_service),
        ):
            manager = WaveshareInventoryManager(scan_interval_s=999.0)
            status = manager.refresh()

        self.assertEqual(status["current_port"], "/dev/ttyUSB0")
        self.assertEqual([servo["id"] for servo in status["servos"]], [1, 3])
        self.assertEqual(status["all_servo_ids"], [1, 3])
        self.assertEqual(status["highest_seen_id"], 3)
        self.assertEqual(status["suggested_next_id"], 4)
        self.assertEqual(machine_toml.read()["servo"], {"port": "/dev/ttyUSB0", "highest_seen_id": 3})

    def test_refresh_during_homing_keeps_previous_snapshot_without_rescanning(self) -> None:
        self._config({"servo": {"port": "/dev/ttyUSB0", "highest_seen_id": 5}})

        fake_service = Mock()
        fake_service.list_servo_infos.return_value = (
            [5],
            [{"id": 5, "model_name": "SC15"}],
        )

        shared_state.hardware_state = "standby"
        with (
            patch("server.waveshare_inventory.shared_state.getActiveIRL", return_value=None),
            patch(
                "server.waveshare_inventory.serial.tools.list_ports.comports",
                return_value=[
                    SimpleNamespace(
                        device="/dev/ttyUSB0",
                        product="USB Serial",
                        serial_number="ABC123",
                        vid=0x1234,
                    )
                ],
            ),
            patch("server.waveshare_inventory.get_waveshare_bus_service", return_value=fake_service),
        ):
            manager = WaveshareInventoryManager(scan_interval_s=999.0)
            first_status = manager.refresh()

            shared_state.hardware_state = "homing"
            fake_service.reset_mock()
            second_status = manager.refresh()

        self.assertEqual([servo["id"] for servo in first_status["servos"]], [5])
        self.assertEqual([servo["id"] for servo in second_status["servos"]], [5])
        self.assertEqual(second_status["current_port"], "/dev/ttyUSB0")
        fake_service.list_servo_infos.assert_not_called()

    def test_automatic_refresh_skips_active_runtime_bus(self) -> None:
        self._config({"servo": {"port": "/dev/ttyUSB0"}})

        fake_service = Mock()
        fake_service.port = "/dev/ttyUSB0"
        fake_service.list_servo_infos.return_value = (
            [2],
            [{"id": 2, "model_name": "SC09"}],
        )
        fake_irl = SimpleNamespace(
            servo_controller=SimpleNamespace(bus_service=fake_service),
            interfaces={},
        )

        shared_state.hardware_state = "ready"
        with (
            patch("server.waveshare_inventory.shared_state.getActiveIRL", return_value=fake_irl),
            patch(
                "server.waveshare_inventory.serial.tools.list_ports.comports",
                return_value=[
                    SimpleNamespace(
                        device="/dev/ttyUSB0",
                        product="USB Serial",
                        serial_number="ABC123",
                        vid=0x1234,
                    )
                ],
            ),
        ):
            manager = WaveshareInventoryManager(scan_interval_s=999.0)
            first_status = manager.refresh(allow_active_runtime_scan=True)

            fake_service.list_servo_infos.return_value = (
                [3],
                [{"id": 3, "model_name": "SC09"}],
            )
            fake_service.reset_mock()
            second_status = manager.refresh()

            manual_status = manager.refresh(allow_active_runtime_scan=True)

        self.assertEqual([servo["id"] for servo in first_status["servos"]], [2])
        self.assertEqual([servo["id"] for servo in second_status["servos"]], [2])
        self.assertEqual(second_status["ports"][0].get("scan_skipped"), "active_runtime")
        fake_service.list_servo_infos.assert_called_once()
        self.assertEqual([servo["id"] for servo in manual_status["servos"]], [3])


if __name__ == "__main__":
    unittest.main()
