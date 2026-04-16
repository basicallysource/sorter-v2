from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server import shared_state
from server.waveshare_inventory import WaveshareInventoryManager


class WaveshareInventoryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._hardware_state = shared_state.hardware_state

    def tearDown(self) -> None:
        shared_state.hardware_state = self._hardware_state

    def test_refresh_caches_ports_and_servos_for_configured_port(self) -> None:
        config_holder = {"servo": {"port": "/dev/ttyUSB0"}}

        def fake_read_machine_params_config():
            return "/tmp/machine_params.toml", config_holder

        def fake_write_machine_params_config(path: str, data: dict) -> None:
            del path
            config_holder.clear()
            config_holder.update(data)

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
            patch("server.waveshare_inventory.read_machine_params_config", side_effect=fake_read_machine_params_config),
            patch("server.waveshare_inventory.write_machine_params_config", side_effect=fake_write_machine_params_config),
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

    def test_refresh_during_homing_keeps_previous_snapshot_without_rescanning(self) -> None:
        config_holder = {"servo": {"port": "/dev/ttyUSB0", "highest_seen_id": 5}}

        def fake_read_machine_params_config():
            return "/tmp/machine_params.toml", config_holder

        fake_service = Mock()
        fake_service.list_servo_infos.return_value = (
            [5],
            [{"id": 5, "model_name": "SC15"}],
        )

        shared_state.hardware_state = "standby"
        with (
            patch("server.waveshare_inventory.read_machine_params_config", side_effect=fake_read_machine_params_config),
            patch("server.waveshare_inventory.write_machine_params_config"),
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


if __name__ == "__main__":
    unittest.main()
