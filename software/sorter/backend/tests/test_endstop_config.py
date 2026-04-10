import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from irl.parse_user_toml import (
    DEFAULT_CAROUSEL_HOME_PIN_CHANNEL,
    DEFAULT_CHUTE_HOME_PIN_CHANNEL,
    loadCarouselCalibrationConfig,
    loadChuteCalibrationConfig,
)
from server.routers import hardware


class _Logger:
    def warning(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass


class _GC:
    logger = _Logger()


class EndstopConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gc = _GC()

    def test_parse_defaults_match_setup_wiring(self) -> None:
        carousel = loadCarouselCalibrationConfig(self.gc, {})
        chute = loadChuteCalibrationConfig(self.gc, {})

        self.assertEqual(DEFAULT_CAROUSEL_HOME_PIN_CHANNEL, carousel.home_pin_channel)
        self.assertEqual(DEFAULT_CHUTE_HOME_PIN_CHANNEL, chute.home_pin_channel)

    def test_router_defaults_expose_safe_home_pin_channels(self) -> None:
        with patch("server.routers.hardware._active_irl", return_value=None):
            carousel = hardware._carousel_settings_from_config({})
            chute = hardware._chute_settings_from_config({})

        self.assertEqual(DEFAULT_CAROUSEL_HOME_PIN_CHANNEL, carousel["home_pin_channel"])
        self.assertEqual(DEFAULT_CHUTE_HOME_PIN_CHANNEL, chute["home_pin_channel"])


class ChuteConfigPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.machine_params_path = Path(self._tmpdir.name) / "machine_params.toml"
        self.machine_params_path.write_text(
            "\n".join(
                [
                    "[chute]",
                    f"home_pin_channel = {DEFAULT_CHUTE_HOME_PIN_CHANNEL}",
                    "first_bin_center = 8.25",
                    "pillar_width_deg = 8.25",
                    "endstop_active_high = false",
                    "operating_speed_microsteps_per_second = 800",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        self._tmpdir.cleanup()

    def test_save_chute_settings_preserves_home_pin_channel(self) -> None:
        payload = hardware.ChuteHardwareSettingsPayload(
            first_bin_center=9.0,
            pillar_width_deg=7.5,
            endstop_active_high=True,
            operating_speed_microsteps_per_second=1200,
        )

        with patch("server.routers.hardware.shared_state.controller_ref", None):
            response = hardware.save_chute_hardware_config(payload)

        self.assertTrue(response["ok"])
        self.assertEqual(
            DEFAULT_CHUTE_HOME_PIN_CHANNEL,
            response["settings"]["home_pin_channel"],
        )
        saved = self.machine_params_path.read_text(encoding="utf-8")
        self.assertIn(
            f"home_pin_channel = {DEFAULT_CHUTE_HOME_PIN_CHANNEL}",
            saved,
        )


if __name__ == "__main__":
    unittest.main()
