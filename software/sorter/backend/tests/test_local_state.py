import json
import local_state
import os
import sqlite3
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from local_state import (
    build_piece_detail_payload,
    clear_current_session_bins,
    clear_piece_segments_for_session,
    get_api_keys,
    get_bin_categories,
    get_current_bin_contents_snapshot,
    get_channel_polygons,
    get_classification_polygons,
    get_classification_training_state,
    get_machine_id,
    get_piece_segment_counts,
    get_recent_known_objects,
    get_active_sorting_session,
    get_set_progress_state,
    get_servo_states,
    get_sorting_profile_sync_state,
    get_hive_config,
    get_piece_dossier,
    get_piece_dossier_by_tracked_global_id,
    initialize_local_state,
    list_piece_dossiers,
    list_piece_segments,
    record_piece_distribution,
    remember_piece_dossier,
    remember_piece_segment,
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

    def test_piece_dossiers_merge_and_lookup_by_uuid_and_track(self) -> None:
        initialize_local_state()
        session = start_new_sorting_session(reason="test_piece_dossier")

        remember_piece_dossier(
            "piece-1",
            {
                "tracked_global_id": 41,
                "created_at": 10.0,
                "updated_at": 12.0,
                "stage": "created",
                "classification_status": "pending",
                "thumbnail": "thumb-1",
                "classification_channel_zone_center_deg": 123.4,
            },
        )
        remember_piece_dossier(
            "piece-1",
            {
                "tracked_global_id": 41,
                "created_at": 10.0,
                "updated_at": 15.0,
                "stage": "distributed",
                "classification_status": "classified",
                "part_id": "3001",
                "part_name": "Brick 2 x 4",
                "distributed_at": 15.0,
            },
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

    def test_drops_legacy_persistent_tracker_ignored_regions_on_boot(self) -> None:
        """Whitelist refactor migration: any legacy ``persistent_tracker_
        ignored_regions:<role>`` rows left behind by the old blacklist
        tracker must be purged the first time ``initialize_local_state``
        runs.
        """

        initialize_local_state()
        # Hand-write legacy rows directly so we don't depend on the old
        # setter helpers that were removed.
        with sqlite3.connect(local_state.local_state_db_path()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state_entries(key, json_value, updated_at) "
                "VALUES (?, ?, ?)",
                (
                    "persistent_tracker_ignored_regions:c_channel_3",
                    json.dumps([{"center_px": [640.0, 360.0], "radius_px": 72.0}]),
                    1234.0,
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO state_entries(key, json_value, updated_at) "
                "VALUES (?, ?, ?)",
                (
                    "persistent_tracker_ignored_regions:carousel",
                    json.dumps([{"center_px": [120.0, 240.0], "radius_px": 48.0}]),
                    1234.0,
                ),
            )
            conn.commit()

        # Re-running initialize triggers the migration.
        initialize_local_state()

        with sqlite3.connect(local_state.local_state_db_path()) as conn:
            remaining = conn.execute(
                "SELECT key FROM state_entries WHERE key LIKE ?",
                ("persistent_tracker_ignored_regions:%",),
            ).fetchall()
        self.assertEqual([], remaining)


class PieceSegmentsSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmpdir.name)
        self.machine_params_path = tmp_dir / "machine_params.toml"
        self.local_state_db_path = tmp_dir / "local_state.sqlite"

        # Minimal machine_params.toml so migrations have a source file.
        self.machine_params_path.write_text(
            "\n".join(
                [
                    "[machine]",
                    'nickname = "SegmentBench"',
                ]
            )
            + "\n",
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

    def _make_segment_payload(
        self,
        *,
        tracked_global_id: int = 77,
        first_seen_ts: float = 100.0,
        last_seen_ts: float = 105.0,
        hit_count: int = 4,
        path: list | None = None,
        sector_snapshots: list | None = None,
        recognize_result: dict | None = None,
        snapshot_path: str | None = "piece_crops/xyz/seg0/snapshot.jpg",
    ) -> dict:
        return {
            "tracked_global_id": tracked_global_id,
            "first_seen_ts": first_seen_ts,
            "last_seen_ts": last_seen_ts,
            "hit_count": hit_count,
            "channel_center_x": 320.0,
            "channel_center_y": 240.0,
            "channel_radius_inner": 80.0,
            "channel_radius_outer": 160.0,
            "snapshot_width": 640,
            "snapshot_height": 480,
            "snapshot_path": snapshot_path,
            "path": path if path is not None else [[100.0, 300.0, 240.0], [101.0, 320.0, 250.0]],
            "sector_snapshots": (
                sector_snapshots
                if sector_snapshots is not None
                else [
                    {
                        "captured_ts": 100.5,
                        "start_angle_deg": 10.0,
                        "end_angle_deg": 30.0,
                        "r_inner": 80.0,
                        "r_outer": 160.0,
                        "jpeg_path": "piece_crops/xyz/seg0/wedge0.jpg",
                        "piece_jpeg_path": "piece_crops/xyz/seg0/piece0.jpg",
                        "bbox": {"x": 10, "y": 20, "w": 30, "h": 40},
                    }
                ]
            ),
            "recognize_result": recognize_result,
        }

    def test_schema_v5_migration_additive_only(self) -> None:
        # Seed a schema_version=4 database with a minimal piece_dossiers row,
        # mimicking a pre-v5 install.
        db_path = self.local_state_db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        seed_conn = sqlite3.connect(db_path)
        seed_conn.row_factory = sqlite3.Row
        seed_conn.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sorting_sessions (
                id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                profile_id TEXT,
                profile_name TEXT,
                version_id TEXT,
                version_number INTEGER,
                version_label TEXT,
                artifact_hash TEXT,
                started_at REAL NOT NULL,
                ended_at REAL,
                status TEXT NOT NULL,
                reason TEXT
            );
            CREATE TABLE piece_dossiers (
                piece_uuid TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tracked_global_id INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_event_at REAL NOT NULL,
                stage TEXT NOT NULL,
                classification_status TEXT NOT NULL,
                first_carousel_seen_ts REAL,
                classification_channel_zone_center_deg REAL,
                distributed_at REAL,
                payload_json TEXT NOT NULL
            );
            """
        )
        seed_conn.execute(
            "INSERT INTO metadata(key, value) VALUES(?, ?)",
            ("schema_version", "4"),
        )
        seed_conn.execute(
            "INSERT INTO sorting_sessions(id, machine_id, started_at, status) "
            "VALUES(?, ?, ?, ?)",
            ("session-legacy", "bench", 50.0, "active"),
        )
        seed_conn.execute(
            "INSERT INTO metadata(key, value) VALUES(?, ?)",
            ("active_sorting_session_id", "session-legacy"),
        )
        seed_conn.execute(
            "INSERT INTO piece_dossiers("
            "piece_uuid, session_id, tracked_global_id, created_at, updated_at, "
            "last_event_at, stage, classification_status, "
            "first_carousel_seen_ts, classification_channel_zone_center_deg, "
            "distributed_at, payload_json) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-piece",
                "session-legacy",
                11,
                50.0,
                51.0,
                51.0,
                "created",
                "pending",
                None,
                None,
                None,
                json.dumps({"uuid": "legacy-piece", "tracked_global_id": 11}),
            ),
        )
        seed_conn.commit()
        seed_conn.close()

        # Run the real initializer — should perform additive migration to v5.
        initialize_local_state()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            version_row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            self.assertEqual("5", str(version_row["value"]))

            # piece_dossiers row must be untouched.
            dossier_row = conn.execute(
                "SELECT piece_uuid, tracked_global_id FROM piece_dossiers "
                "WHERE piece_uuid = 'legacy-piece'"
            ).fetchone()
            self.assertIsNotNone(dossier_row)
            self.assertEqual(11, dossier_row["tracked_global_id"])

            # New piece_segments table must exist and be empty.
            table_row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='piece_segments'"
            ).fetchone()
            self.assertIsNotNone(table_row)
            count_row = conn.execute(
                "SELECT COUNT(*) AS c FROM piece_segments"
            ).fetchone()
            self.assertEqual(0, int(count_row["c"]))

            # Indexes must exist.
            idx_rows = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND tbl_name='piece_segments'"
                ).fetchall()
            }
            self.assertIn("piece_segments_piece_seq_idx", idx_rows)
            self.assertIn("piece_segments_session_role_idx", idx_rows)
        finally:
            conn.close()

    def test_remember_and_list_piece_segments(self) -> None:
        initialize_local_state()
        start_new_sorting_session(reason="segments_test")
        remember_piece_dossier(
            "piece-seg-1",
            {
                "tracked_global_id": 77,
                "created_at": 100.0,
                "updated_at": 100.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )

        for seq in (1, 0, 2):
            payload = self._make_segment_payload(
                first_seen_ts=100.0 + seq,
                last_seen_ts=105.0 + seq,
                hit_count=4 + seq,
                path=[[100.0 + seq, 300.0, 240.0]],
                sector_snapshots=[
                    {
                        "captured_ts": 100.0 + seq,
                        "start_angle_deg": float(seq * 10),
                        "end_angle_deg": float(seq * 10 + 20),
                        "r_inner": 80.0,
                        "r_outer": 160.0,
                        "jpeg_path": f"piece_crops/seg{seq}.jpg",
                        "piece_jpeg_path": f"piece_crops/piece{seq}.jpg",
                        "bbox": {"x": seq, "y": seq, "w": 10, "h": 10},
                    }
                ],
                recognize_result={"part_id": "3001", "score": 0.9},
            )
            remember_piece_segment(
                "piece-seg-1",
                "c_channel_3" if seq % 2 == 0 else "carousel",
                seq,
                payload,
            )

        segments = list_piece_segments("piece-seg-1")
        self.assertEqual([0, 1, 2], [entry["sequence"] for entry in segments])

        first = segments[0]
        self.assertEqual("c_channel_3", first["role"])
        self.assertEqual(77, first["tracked_global_id"])
        self.assertEqual(4, first["hit_count"])
        self.assertEqual(100.0, first["first_seen_ts"])
        self.assertEqual(105.0, first["last_seen_ts"])
        self.assertEqual([[100.0, 300.0, 240.0]], first["path"])
        self.assertEqual(1, len(first["sector_snapshots"]))
        self.assertEqual(0.0, first["sector_snapshots"][0]["start_angle_deg"])
        self.assertEqual({"part_id": "3001", "score": 0.9}, first["recognize_result"])

        second = segments[1]
        self.assertEqual("carousel", second["role"])
        self.assertEqual(1, second["sequence"])

        third = segments[2]
        self.assertEqual("c_channel_3", third["role"])
        self.assertEqual(6, third["hit_count"])

    def test_remember_piece_segment_upsert_preserves_created_at(self) -> None:
        initialize_local_state()
        start_new_sorting_session(reason="segments_upsert")
        remember_piece_dossier(
            "piece-upsert",
            {
                "tracked_global_id": 42,
                "created_at": 10.0,
                "updated_at": 10.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )

        first_payload = self._make_segment_payload(
            tracked_global_id=42,
            first_seen_ts=100.0,
            last_seen_ts=101.0,
            hit_count=2,
        )
        first_payload["created_at"] = 100.0
        remember_piece_segment("piece-upsert", "c_channel_3", 0, first_payload)

        conn = sqlite3.connect(self.local_state_db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, created_at FROM piece_segments "
                "WHERE piece_uuid = 'piece-upsert' AND sequence = 0"
            ).fetchone()
            self.assertIsNotNone(row)
            original_id = int(row["id"])
            self.assertEqual(100.0, float(row["created_at"]))
        finally:
            conn.close()

        second_payload = self._make_segment_payload(
            tracked_global_id=42,
            first_seen_ts=99.0,
            last_seen_ts=200.0,
            hit_count=9,
            path=[[200.0, 350.0, 260.0], [201.0, 360.0, 270.0]],
            recognize_result={"part_id": "3002"},
        )
        # created_at in payload should NOT overwrite existing.
        second_payload["created_at"] = 999.0
        remember_piece_segment("piece-upsert", "carousel", 0, second_payload)

        segments = list_piece_segments("piece-upsert")
        self.assertEqual(1, len(segments))
        entry = segments[0]
        self.assertEqual(100.0, entry["created_at"])  # preserved
        self.assertEqual(9, entry["hit_count"])
        self.assertEqual("carousel", entry["role"])
        self.assertEqual(200.0, entry["last_seen_ts"])
        self.assertEqual({"part_id": "3002"}, entry["recognize_result"])
        self.assertEqual(
            [[200.0, 350.0, 260.0], [201.0, 360.0, 270.0]],
            entry["path"],
        )

        # Row id must remain the same (in-place update, not replace).
        conn = sqlite3.connect(self.local_state_db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id FROM piece_segments "
                "WHERE piece_uuid = 'piece-upsert' AND sequence = 0"
            ).fetchone()
            self.assertEqual(original_id, int(row["id"]))
        finally:
            conn.close()

    def test_clear_piece_segments_for_session(self) -> None:
        initialize_local_state()

        session_a = start_new_sorting_session(reason="sess_a")
        remember_piece_dossier(
            "piece-a",
            {
                "tracked_global_id": 1,
                "created_at": 1.0,
                "updated_at": 1.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        remember_piece_segment(
            "piece-a",
            "c_channel_3",
            0,
            self._make_segment_payload(tracked_global_id=1, first_seen_ts=1.0),
        )
        remember_piece_segment(
            "piece-a",
            "carousel",
            1,
            self._make_segment_payload(tracked_global_id=1, first_seen_ts=2.0),
        )

        session_b = start_new_sorting_session(reason="sess_b")
        remember_piece_dossier(
            "piece-b",
            {
                "tracked_global_id": 2,
                "created_at": 10.0,
                "updated_at": 10.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        remember_piece_segment(
            "piece-b",
            "c_channel_3",
            0,
            self._make_segment_payload(tracked_global_id=2, first_seen_ts=10.0),
        )

        removed = clear_piece_segments_for_session(session_a["id"])
        self.assertEqual(2, removed)

        self.assertEqual([], list_piece_segments("piece-a"))
        remaining = list_piece_segments("piece-b")
        self.assertEqual(1, len(remaining))
        self.assertEqual(session_b["id"], remaining[0]["session_id"])

    def test_get_piece_segment_counts_bulk(self) -> None:
        initialize_local_state()
        start_new_sorting_session(reason="segment_counts")
        remember_piece_dossier(
            "piece-with-segs",
            {
                "tracked_global_id": 11,
                "created_at": 1.0,
                "updated_at": 1.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        remember_piece_dossier(
            "piece-without-segs",
            {
                "tracked_global_id": 12,
                "created_at": 1.0,
                "updated_at": 1.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        for seq in range(3):
            remember_piece_segment(
                "piece-with-segs",
                "c_channel_3" if seq % 2 == 0 else "carousel",
                seq,
                self._make_segment_payload(tracked_global_id=11, first_seen_ts=float(seq)),
            )

        counts = get_piece_segment_counts(
            piece_uuids=["piece-with-segs", "piece-without-segs", "piece-unknown"]
        )
        self.assertEqual(3, counts.get("piece-with-segs"))
        # Omitted keys mean zero; the list endpoint treats that as False.
        self.assertNotIn("piece-without-segs", counts)
        self.assertNotIn("piece-unknown", counts)

        # Empty / None inputs must not blow up.
        self.assertEqual({}, get_piece_segment_counts(piece_uuids=[]))
        self.assertEqual({}, get_piece_segment_counts())

    def test_build_piece_detail_payload_merges_dossier_and_segments(self) -> None:
        initialize_local_state()
        start_new_sorting_session(reason="build_detail_payload")
        remember_piece_dossier(
            "piece-detail",
            {
                "tracked_global_id": 9000,
                "created_at": 50.0,
                "updated_at": 55.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        remember_piece_segment(
            "piece-detail",
            "c_channel_3",
            0,
            self._make_segment_payload(tracked_global_id=9000, first_seen_ts=50.0),
        )
        remember_piece_segment(
            "piece-detail",
            "carousel",
            1,
            self._make_segment_payload(
                tracked_global_id=9000,
                first_seen_ts=60.0,
                last_seen_ts=65.0,
            ),
        )

        payload = build_piece_detail_payload("piece-detail")
        self.assertIsNotNone(payload)
        assert payload is not None  # for type narrowing
        self.assertEqual("piece-detail", payload.get("uuid"))
        self.assertEqual(9000, payload.get("tracked_global_id"))
        self.assertIn("track_detail", payload)
        track_detail = payload["track_detail"]
        self.assertFalse(track_detail["live"])
        self.assertEqual(
            [0, 1], [seg["sequence"] for seg in track_detail["segments"]]
        )
        self.assertEqual("c_channel_3", track_detail["segments"][0]["role"])
        self.assertEqual("carousel", track_detail["segments"][1]["role"])

    def test_build_piece_detail_payload_returns_none_without_dossier(self) -> None:
        initialize_local_state()
        self.assertIsNone(build_piece_detail_payload("no-such-piece"))
        self.assertIsNone(build_piece_detail_payload(""))
        self.assertIsNone(build_piece_detail_payload("   "))

    def test_list_piece_dossiers_excludes_stubs_by_default(self) -> None:
        """Ghost-stub rows (pending + no distributed_at + no segments) are
        hidden from the default list_piece_dossiers() call but still available
        via include_stubs=True for debug tooling."""
        initialize_local_state()
        start_new_sorting_session(reason="stub_filter")

        # Two pure ghost stubs: pending, no distributed_at, no segments.
        remember_piece_dossier(
            "stub-1",
            {
                "tracked_global_id": 101,
                "created_at": 1.0,
                "updated_at": 1.0,
                "last_event_at": 1.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        remember_piece_dossier(
            "stub-2",
            {
                "tracked_global_id": 102,
                "created_at": 2.0,
                "updated_at": 2.0,
                "last_event_at": 2.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )

        # One pending piece that has an attached segment → not a stub.
        remember_piece_dossier(
            "with-segment",
            {
                "tracked_global_id": 103,
                "created_at": 3.0,
                "updated_at": 3.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )
        remember_piece_segment(
            "with-segment",
            "c_channel_3",
            0,
            self._make_segment_payload(tracked_global_id=103, first_seen_ts=3.0),
        )

        # One classified piece (terminal status, no segment needed).
        remember_piece_dossier(
            "classified",
            {
                "tracked_global_id": 104,
                "created_at": 4.0,
                "updated_at": 4.0,
                "stage": "distributed",
                "classification_status": "classified",
                "distributed_at": 4.5,
            },
        )

        default_uuids = {entry["uuid"] for entry in list_piece_dossiers(limit=50)}
        self.assertEqual({"with-segment", "classified"}, default_uuids)

        all_uuids = {
            entry["uuid"]
            for entry in list_piece_dossiers(limit=50, include_stubs=True)
        }
        self.assertEqual(
            {"stub-1", "stub-2", "with-segment", "classified"},
            all_uuids,
        )

    def test_list_piece_dossiers_includes_confirmed_pending_without_segments(
        self,
    ) -> None:
        """H2 regression: rt runtime publishes PIECE_REGISTERED with
        ``confirmed_real=True`` before any segment has been captured. The
        old gate hid those rows from ``/api/tracked/pieces`` and the UI
        showed an empty list. They must be visible as soon as the tracker
        confirms the piece, even if no segment or classifier result has
        landed yet."""
        initialize_local_state()
        start_new_sorting_session(reason="h2_confirmed_pending")

        # Confirmed pending piece, no segments, fresh last_event_at.
        remember_piece_dossier(
            "rt-confirmed-1",
            {
                "tracked_global_id": 901,
                "confirmed_real": True,
                "classification_status": "pending",
            },
            status="registered",
        )
        # Unconfirmed legacy stub — must stay hidden.
        remember_piece_dossier(
            "legacy-stub-1",
            {
                "tracked_global_id": 902,
                "created_at": 1.0,
                "updated_at": 1.0,
                "stage": "created",
                "classification_status": "pending",
            },
        )

        default_uuids = {entry["uuid"] for entry in list_piece_dossiers(limit=50)}
        self.assertIn("rt-confirmed-1", default_uuids)
        self.assertNotIn("legacy-stub-1", default_uuids)

        # The stage "registered" set via ``status=`` must persist.
        confirmed = get_piece_dossier("rt-confirmed-1")
        self.assertIsNotNone(confirmed)
        assert confirmed is not None
        self.assertEqual("registered", confirmed.get("stage"))
        self.assertTrue(confirmed.get("confirmed_real"))


if __name__ == "__main__":
    unittest.main()
