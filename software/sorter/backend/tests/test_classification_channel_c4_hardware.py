import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from irl.config import mkIRLConfig
from server import shared_state
from server.routers import setup, steppers


class ClassificationChannelC4HardwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.machine_params_path = Path(self._tmpdir.name) / "machine_params.toml"
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        self._tmpdir.cleanup()

    def test_classification_setup_uses_c_channel_stepper_config_for_c4(self) -> None:
        self.machine_params_path.write_text(
            """
[machine_setup]
type = "classification_channel"

[cameras]
layout = "split_feeder"
c_channel_2 = 0
c_channel_3 = 1
classification_channel = 2
""".strip()
        )

        config = mkIRLConfig()

        self.assertEqual(8, config.carousel_stepper.microsteps)
        self.assertEqual(4000, config.carousel_stepper.default_steps_per_second)
        self.assertIs(config.c_channel_4_rotor_stepper, config.carousel_stepper)

    def test_stepper_api_exposes_c4_as_alias_for_carousel_port(self) -> None:
        stepper = object()
        irl = SimpleNamespace(carousel_stepper=stepper)

        with patch("server.routers.steppers.shared_state.getActiveIRL", return_value=irl):
            mapping = steppers._stepper_mapping()

        self.assertIs(mapping["c_channel_4"], stepper)
        self.assertIs(mapping["carousel"], stepper)

    def test_setup_direction_c4_persists_to_carousel_backing_axis(self) -> None:
        self.machine_params_path.write_text(
            """
[machine_setup]
type = "classification_channel"
""".strip()
        )
        stepper = SimpleNamespace(
            direction_inverted=False,
            set_direction_inverted=lambda value: setattr(stepper, "direction_inverted", value),
        )
        irl = SimpleNamespace(carousel_stepper=stepper)

        with patch("server.routers.setup.shared_state.getActiveIRL", return_value=irl):
            response = setup.set_stepper_direction(
                "c_channel_4",
                setup.StepperDirectionPayload(inverted=True),
            )

        persisted = tomllib.loads(self.machine_params_path.read_text())
        self.assertTrue(persisted["stepper_direction_inverts"]["carousel"])
        self.assertEqual("c_channel_4", response["stepper"])
        self.assertTrue(response["applied_live"])
        self.assertTrue(stepper.direction_inverted)
        self.assertIn(
            "c_channel_4",
            {entry["name"] for entry in response["steppers"]},
        )

    def test_c4_sector_move_can_plan_without_live_hardware(self) -> None:
        with patch("server.routers.steppers.shared_state.controller_ref", None):
            response = steppers.classification_channel_sector_move(
                from_sector=0,
                to_sector=1,
                direction="cw",
                execute=False,
            )

        self.assertTrue(response.success)
        self.assertFalse(response.executed)
        self.assertEqual("c_channel_4", response.stepper)
        self.assertEqual(1, response.sector_delta)
        self.assertEqual(3467, response.motor_microsteps)
        self.assertAlmostEqual(130 / 12, response.gear_ratio)
        self.assertEqual(8, response.microsteps)

    def test_c4_sector_move_endpoint_defaults_to_plan_only(self) -> None:
        app = FastAPI()
        app.include_router(steppers.router)

        with patch("server.routers.steppers.shared_state.controller_ref", None):
            with TestClient(app) as client:
                response = client.post(
                    "/api/classification-channel/sector-move",
                    params={
                        "from_sector": 0,
                        "to_sector": 1,
                        "direction": "cw",
                    },
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertFalse(payload["executed"])
        self.assertEqual("c_channel_4", payload["stepper"])
        self.assertEqual(3467, payload["motor_microsteps"])

    def test_c4_sector_move_surfaces_motion_profile_warnings_without_executing(self) -> None:
        irl_config = SimpleNamespace(
            classification_channel_config=SimpleNamespace(),
            feeder_config=SimpleNamespace(
                classification_channel_eject=SimpleNamespace(
                    microsteps_per_second=6400,
                    acceleration_microsteps_per_second_sq=2500,
                )
            ),
            c_channel_4_rotor_stepper=SimpleNamespace(
                microsteps=8,
                default_steps_per_second=4000,
            ),
        )
        controller = SimpleNamespace(coordinator=SimpleNamespace(irl_config=irl_config))

        old_controller = shared_state.controller_ref
        shared_state.controller_ref = controller
        try:
            response = steppers.classification_channel_sector_move(
                from_sector=0,
                to_sector=1,
                direction="cw",
                execute=False,
            )
        finally:
            shared_state.controller_ref = old_controller

        self.assertTrue(response.success)
        self.assertFalse(response.executed)
        self.assertEqual(6400, response.max_speed_microsteps_per_second)
        self.assertEqual(6400, response.requested_max_speed_microsteps_per_second)
        self.assertEqual(4000, response.configured_stepper_default_speed_microsteps_per_second)
        self.assertTrue(response.warnings)
        self.assertIn("exceeds the configured stepper default", response.warnings[0])

    def test_c4_sector_move_executes_exact_microsteps_on_c4_axis(self) -> None:
        class Stepper:
            def __init__(self) -> None:
                self.enabled = False
                self.stopped = True
                self.speed_limits: list[tuple[int, int]] = []
                self.accelerations: list[int] = []
                self.moves: list[int] = []

            def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
                self.speed_limits.append((int(min_speed), int(max_speed)))

            def set_acceleration(self, acceleration: int) -> None:
                self.accelerations.append(int(acceleration))

            def move_steps(self, steps: int) -> bool:
                self.moves.append(int(steps))
                return True

        stepper = Stepper()
        irl_config = SimpleNamespace(
            classification_channel_config=SimpleNamespace(),
            feeder_config=SimpleNamespace(
                classification_channel_eject=SimpleNamespace(
                    microsteps_per_second=3400,
                    acceleration_microsteps_per_second_sq=2500,
                )
            ),
            c_channel_4_rotor_stepper=SimpleNamespace(microsteps=8),
        )
        controller = SimpleNamespace(coordinator=SimpleNamespace(irl_config=irl_config))
        irl = SimpleNamespace(c_channel_4_rotor_stepper=stepper)

        old_controller = shared_state.controller_ref
        shared_state.controller_ref = controller
        try:
            with patch("server.routers.steppers.shared_state.getActiveIRL", return_value=irl):
                response = steppers.classification_channel_sector_move(
                    from_sector=0,
                    to_sector=4,
                    direction="shortest",
                    execute=True,
                )
        finally:
            shared_state.controller_ref = old_controller
            shared_state.pulse_locks.pop("c_channel_4", None)

        self.assertTrue(response.success)
        self.assertTrue(response.executed)
        self.assertEqual(-1, response.sector_delta)
        self.assertEqual(-3466, response.motor_microsteps)
        self.assertTrue(stepper.enabled)
        self.assertEqual([(16, 3400)], stepper.speed_limits)
        self.assertEqual([2500], stepper.accelerations)
        self.assertEqual([-3466], stepper.moves)

    def test_c4_sector_move_rejects_unknown_direction(self) -> None:
        with self.assertRaises(Exception) as excinfo:
            steppers.classification_channel_sector_move(
                from_sector=0,
                to_sector=1,
                direction="sideways",
                execute=False,
            )
        self.assertEqual(400, getattr(excinfo.exception, "status_code", None))
