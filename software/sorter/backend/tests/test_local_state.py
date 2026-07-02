import json
import local_state
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from local_state import (
    clear_current_session_bins,
    get_api_keys,
    get_bin_categories,
    get_current_bin_contents_snapshot,
    get_channel_polygons,
    get_classification_polygons,
    get_classification_training_state,
    get_machine_id,
    get_recent_known_objects,
    get_active_sorting_session,
    get_set_progress_state,
    get_servo_states,
    get_sorting_profile_sync_state,
    get_bin_snapshot,
    get_bin_snapshot_pieces,
    get_current_bin_pieces,
    get_hive_config,
    initialize_local_state,
    list_bin_snapshots,
    record_piece_distribution,
    remember_recent_known_object,
    start_new_sorting_session,
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
                    "[[hive.targets]]",
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
        self.assertEqual("target-1", get_hive_config()["targets"][0]["id"])
        self.assertEqual("version-1", get_sorting_profile_sync_state()["version_id"])
        self.assertEqual({"0": {"is_open": True}}, get_servo_states())
        self.assertEqual("artifact-1", get_set_progress_state()["artifact_hash"])

        with open(self.machine_params_path, "rb") as handle:
            cleaned = tomllib.load(handle)

        self.assertIn("machine", cleaned)
        self.assertNotIn("classification_training", cleaned)
        self.assertNotIn("api_keys", cleaned)
        self.assertNotIn("hive", cleaned)
        self.assertNotIn("sorting_profile_sync", cleaned)

    def test_recent_known_objects_are_persisted_and_deduplicated(self) -> None:
        initialize_local_state()

        remember_recent_known_object({"uuid": "piece-1", "part_id": "3001", "updated_at": 1.0})
        remember_recent_known_object({"uuid": "piece-2", "part_id": "3002", "updated_at": 2.0})
        remember_recent_known_object({"uuid": "piece-1", "part_id": "3001", "updated_at": 3.0})

        recent = get_recent_known_objects()
        self.assertEqual(["piece-1", "piece-2"], [entry["uuid"] for entry in recent])
        self.assertEqual(3.0, recent[0]["updated_at"])

    def test_sorting_sessions_persist_current_bin_state_and_recent_pieces(self) -> None:
        initialize_local_state()

        session = start_new_sorting_session(reason="test")
        self.assertEqual(session["id"], get_active_sorting_session()["id"])

        record_piece_distribution(
            {
                "uuid": "piece-a",
                "destination_bin": [0, 0, 0],
                "distributed_at": 10.0,
                "part_id": "3001",
                "color_id": "15",
                "color_name": "White",
                "category_id": "bricks",
                "classification_status": "classified",
                "thumbnail": "thumb-a",
            }
        )
        record_piece_distribution(
            {
                "uuid": "piece-b",
                "destination_bin": [0, 0, 0],
                "distributed_at": 12.0,
                "part_id": "3002",
                "color_id": "14",
                "color_name": "Yellow",
                "category_id": "bricks",
                "classification_status": "classified",
                "thumbnail": "thumb-b",
            }
        )

        snapshot = get_current_bin_contents_snapshot()
        self.assertEqual(session["id"], snapshot["session"]["id"])
        self.assertEqual(1, len(snapshot["bins"]))
        current_bin = snapshot["bins"][0]
        self.assertEqual(2, current_bin["piece_count"])
        self.assertEqual(2, current_bin["unique_item_count"])
        self.assertEqual(2, len(current_bin["recent_pieces"]))
        self.assertEqual("piece-b", current_bin["recent_pieces"][0]["uuid"])

        clear_current_session_bins(scope="bin", layer_index=0, section_index=0, bin_index=0)
        cleared = get_current_bin_contents_snapshot()
        self.assertEqual([], cleared["bins"])

    def test_bin_snapshots_accumulate_layers_and_close_on_all_clear(self) -> None:
        initialize_local_state()
        start_new_sorting_session(reason="test")

        def _distribute(uuid: str, destination_bin: list[int], distributed_at: float, part_id: str) -> None:
            record_piece_distribution(
                {
                    "uuid": uuid,
                    "destination_bin": destination_bin,
                    "distributed_at": distributed_at,
                    "created_at": distributed_at - 5.0,
                    "classified_at": distributed_at - 2.0,
                    "part_id": part_id,
                    "color_id": "15",
                    "color_name": "White",
                    "category_id": "bricks",
                    "classification_status": "classified",
                }
            )

        _distribute("piece-a", [0, 0, 0], 10.0, "3001")
        _distribute("piece-b", [0, 0, 0], 12.0, "3002")
        _distribute("piece-c", [0, 1, 2], 14.0, "3003")

        current_pieces = get_current_bin_pieces()
        self.assertEqual(["piece-a", "piece-b", "piece-c"], [p["piece_uuid"] for p in current_pieces])

        bin_categories = [[[["bricks"], [], []], [[], [], ["plates"]]]]
        clear_current_session_bins(
            scope="bin", layer_index=0, section_index=0, bin_index=0, bin_categories=bin_categories
        )

        snapshots = list_bin_snapshots()
        self.assertEqual(1, len(snapshots))
        self.assertEqual("open", snapshots[0]["status"])
        self.assertEqual(2, snapshots[0]["piece_count"])

        _distribute("piece-d", [0, 0, 0], 16.0, "3004")
        result = clear_current_session_bins(scope="all", bin_categories=bin_categories)
        snapshot_id = result["snapshot_id"]
        self.assertIsNotNone(snapshot_id)

        snapshots = list_bin_snapshots()
        self.assertEqual(1, len(snapshots))
        self.assertEqual("closed", snapshots[0]["status"])
        self.assertEqual(snapshot_id, snapshots[0]["id"])
        self.assertEqual(4, snapshots[0]["piece_count"])
        self.assertEqual(3, snapshots[0]["layer_count"])
        self.assertEqual(2, snapshots[0]["bin_count"])

        detail = get_bin_snapshot(snapshot_id)
        self.assertEqual(3, len(detail["layers"]))
        first_layer = detail["layers"][0]
        self.assertEqual(["bricks"], first_layer["category_ids"])
        self.assertEqual({"3001", "3002"}, {item["part_id"] for item in first_layer["items"]})
        second_layer = detail["layers"][1]
        self.assertEqual(["3004"], [item["part_id"] for item in second_layer["items"]])

        pieces = get_bin_snapshot_pieces(snapshot_id)
        self.assertEqual(
            {"piece-a", "piece-b", "piece-c", "piece-d"},
            {p["piece_uuid"] for p in pieces},
        )
        first_piece = next(p for p in pieces if p["piece_uuid"] == "piece-a")
        self.assertEqual(5.0, first_piece["created_at"])
        self.assertEqual(8.0, first_piece["classified_at"])
        self.assertEqual(10.0, first_piece["distributed_at"])
        self.assertIn("profile_id", first_piece)
        self.assertIn("profile_name", first_piece)

        self.assertEqual([], get_current_bin_pieces())

        clear_current_session_bins(scope="all")
        self.assertEqual(1, len(list_bin_snapshots()))

    def test_connection_context_closes_sqlite_connections(self) -> None:
        class FakeConnection:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        fake_conn = FakeConnection()

        with patch("local_state._connect", return_value=fake_conn):
            with local_state._connection() as conn:
                self.assertIs(fake_conn, conn)
                self.assertFalse(fake_conn.closed)

        self.assertTrue(fake_conn.closed)


if __name__ == "__main__":
    unittest.main()
