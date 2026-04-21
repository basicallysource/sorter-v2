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
    get_hive_config,
    get_piece_dossier,
    get_piece_dossier_by_tracked_global_id,
    get_persistent_tracker_ignored_regions,
    initialize_local_state,
    list_piece_dossiers,
    record_piece_distribution,
    remember_piece_dossier,
    remember_recent_known_object,
    set_persistent_tracker_ignored_regions,
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

    def test_piece_dossiers_merge_and_lookup_by_uuid_and_track(self) -> None:
        initialize_local_state()
        session = start_new_sorting_session(reason="test_piece_dossier")

        remember_piece_dossier(
            {
                "uuid": "piece-1",
                "tracked_global_id": 41,
                "created_at": 10.0,
                "updated_at": 12.0,
                "stage": "created",
                "classification_status": "pending",
                "thumbnail": "thumb-1",
                "classification_channel_zone_center_deg": 123.4,
            }
        )
        remember_piece_dossier(
            {
                "uuid": "piece-1",
                "tracked_global_id": 41,
                "created_at": 10.0,
                "updated_at": 15.0,
                "stage": "distributed",
                "classification_status": "classified",
                "part_id": "3001",
                "part_name": "Brick 2 x 4",
                "distributed_at": 15.0,
            }
        )

        piece = get_piece_dossier("piece-1")
        self.assertIsNotNone(piece)
        self.assertEqual("piece-1", piece["uuid"])
        self.assertEqual(session["id"], piece["session_id"])
        self.assertEqual("3001", piece["part_id"])
        self.assertEqual("thumb-1", piece["thumbnail"])
        self.assertEqual("distributed", piece["stage"])
        self.assertEqual(15.0, piece["distributed_at"])

        by_track = get_piece_dossier_by_tracked_global_id(41)
        self.assertIsNotNone(by_track)
        self.assertEqual("piece-1", by_track["uuid"])

        listed = list_piece_dossiers(limit=20)
        self.assertEqual(["piece-1"], [entry["uuid"] for entry in listed])

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

    def test_persistent_tracker_ignored_regions_roundtrip(self) -> None:
        initialize_local_state()

        set_persistent_tracker_ignored_regions(
            "carousel",
            [
                {
                    "center_px": [120.0, 240.0],
                    "radius_px": 48.0,
                    "center_angle_rad": 1.5,
                    "center_radius_px": 210.0,
                    "angle_tolerance_rad": 0.12,
                    "radius_tolerance_px": 9.0,
                    "suppression_count": 3,
                }
            ],
        )

        regions = get_persistent_tracker_ignored_regions("carousel")
        self.assertEqual(1, len(regions))
        self.assertEqual([120.0, 240.0], regions[0]["center_px"])
        self.assertEqual(48.0, regions[0]["radius_px"])
        self.assertEqual(3, regions[0]["suppression_count"])


if __name__ == "__main__":
    unittest.main()
