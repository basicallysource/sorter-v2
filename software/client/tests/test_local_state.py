import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest

from local_state import (
    get_api_keys,
    get_bin_categories,
    get_channel_polygons,
    get_classification_polygons,
    get_classification_training_state,
    get_machine_id,
    get_set_progress_state,
    get_servo_states,
    get_sorting_profile_sync_state,
    get_sorthive_config,
    initialize_local_state,
)


class LocalStateMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.client_dir = Path(self._tmpdir.name)
        self.machine_params_path = self.client_dir / "machine_params.toml"
        self.local_state_db_path = self.client_dir / "local_state.sqlite"
        self.blob_dir = self.client_dir / "blob"
        self.blob_dir.mkdir(parents=True, exist_ok=True)

        self.machine_params_path.write_text(
            "\n".join(
                [
                    "[machine]",
                    'nickname = "Bench"',
                    "",
                    "[classification_training]",
                    'processor = "local_archive"',
                    'session_id = "session-123"',
                    'session_dir = "/tmp/session-123"',
                    "",
                    "[api_keys]",
                    'openrouter = "from-toml"',
                    "",
                    "[[sorthive.targets]]",
                    'id = "target-1"',
                    'name = "Primary"',
                    'url = "https://example.test"',
                    'api_token = "secret-token"',
                    "enabled = true",
                    'machine_id = "remote-machine"',
                    "",
                    "[sorting_profile_sync]",
                    'target_id = "target-1"',
                    'version_id = "version-1"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        (self.client_dir / "data.json").write_text(
            json.dumps(
                {
                    "machine_id": "machine-from-data-json",
                    "stepper_positions": {"carousel": 12},
                    "servo_positions": {"layer_0": 90},
                    "bin_categories": [[[ ["misc"] ]]],
                    "channel_polygons": {"source": "data-json"},
                    "classification_polygons": {"source": "data-json"},
                    "classification_training": {"processor": "legacy"},
                    "api_keys": {"openrouter": "from-data-json"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.client_dir / "polygons.json").write_text(
            json.dumps(
                {
                    "channel_polygons": {"source": "polygons-json", "polygons": {"second_channel": [[1, 2], [3, 4], [5, 6]]}},
                    "classification_polygons": {"source": "polygons-json", "polygons": {"top": [[10, 20], [30, 40], [50, 60]]}},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.client_dir / "servo_states.json").write_text(
            json.dumps({"0": {"is_open": True}}),
            encoding="utf-8",
        )
        (self.blob_dir / "set_progress.json").write_text(
            json.dumps(
                {
                    "artifact_hash": "artifact-1",
                    "updated_at": 123.0,
                    "progress": {"set_1": {"1-3001": 2}},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)
        os.environ["LOCAL_STATE_DB_PATH"] = str(self.local_state_db_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params

        if self._old_local_state_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_local_state_db

        self._tmpdir.cleanup()

    def test_initialize_local_state_migrates_legacy_sources_and_cleans_machine_params(self) -> None:
        initialize_local_state()

        self.assertEqual("machine-from-data-json", get_machine_id())
        self.assertEqual([[[["misc"]]]], get_bin_categories())
        self.assertEqual("polygons-json", get_channel_polygons()["source"])
        self.assertEqual("polygons-json", get_classification_polygons()["source"])
        self.assertEqual("local_archive", get_classification_training_state()["processor"])
        self.assertEqual({"openrouter": "from-toml"}, get_api_keys())
        self.assertEqual("target-1", get_sorthive_config()["targets"][0]["id"])
        self.assertEqual("version-1", get_sorting_profile_sync_state()["version_id"])
        self.assertEqual({"0": {"is_open": True}}, get_servo_states())
        self.assertEqual("artifact-1", get_set_progress_state()["artifact_hash"])

        with open(self.machine_params_path, "rb") as handle:
            cleaned = tomllib.load(handle)

        self.assertIn("machine", cleaned)
        self.assertNotIn("classification_training", cleaned)
        self.assertNotIn("api_keys", cleaned)
        self.assertNotIn("sorthive", cleaned)
        self.assertNotIn("sorting_profile_sync", cleaned)


if __name__ == "__main__":
    unittest.main()
