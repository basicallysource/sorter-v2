import os
from pathlib import Path
import tempfile
import unittest

from blob_manager import getFeederDetectionConfig
from server import shared_state
from server.routers import detection


class FeederDetectionConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_vision_manager = shared_state.vision_manager
        self._tmpdir = tempfile.TemporaryDirectory()
        self.machine_params_path = Path(self._tmpdir.name) / "machine_params.toml"
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)
        shared_state.vision_manager = None

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        shared_state.vision_manager = self._old_vision_manager
        self._tmpdir.cleanup()

    def test_feeder_detection_algorithm_can_be_saved_per_role(self) -> None:
        detection.save_feeder_detection_config(
            detection.AuxiliaryDetectionConfigPayload(
                algorithm="mog2",
                openrouter_model="google/gemini-3-flash-preview",
            ),
            role=None,
        )

        detection.save_feeder_detection_config(
            detection.AuxiliaryDetectionConfigPayload(
                algorithm="gemini_sam",
                openrouter_model="google/gemini-3-flash-preview",
            ),
            role="carousel",
        )

        saved = getFeederDetectionConfig()
        self.assertIsInstance(saved, dict)
        self.assertEqual("mog2", saved["algorithm"])
        self.assertEqual("gemini_sam", saved["algorithm_by_role"]["carousel"])
        self.assertEqual("mog2", saved["algorithm_by_role"]["c_channel_2"])
        self.assertEqual("mog2", saved["algorithm_by_role"]["c_channel_3"])

        carousel_config = detection.get_feeder_detection_config(role="carousel")
        channel_config = detection.get_feeder_detection_config(role="c_channel_2")

        self.assertEqual("gemini_sam", carousel_config["algorithm"])
        self.assertEqual("mog2", channel_config["algorithm"])


if __name__ == "__main__":
    unittest.main()
