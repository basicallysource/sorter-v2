import os
import tempfile
import unittest
from unittest.mock import patch

import db
from bin_contents import (
    clear_current_session_bins,
    get_active_sorting_session,
    get_bin_snapshot,
    get_bin_snapshot_pieces,
    get_current_bin_contents_snapshot,
    get_current_bin_piece_counts,
    get_current_bin_pieces,
    list_bin_snapshots,
    record_piece_distribution,
    start_new_sorting_session,
)


class BinContentsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def test_sorting_sessions_persist_current_bin_state_and_recent_pieces(self) -> None:
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

    def test_bin_piece_counts_follow_every_write_and_read_no_database_once_loaded(self) -> None:
        start_new_sorting_session(reason="test")
        self.assertEqual({}, get_current_bin_piece_counts())

        def _distribute(uuid: str, destination_bin: list[int]) -> None:
            record_piece_distribution({"uuid": uuid, "destination_bin": destination_bin, "distributed_at": 1.0})

        _distribute("piece-a", [0, 0, 0])
        _distribute("piece-b", [0, 0, 0])
        _distribute("piece-b", [0, 0, 0])
        _distribute("piece-c", [1, 0, 2])
        with patch.object(db, "_open", side_effect=AssertionError("the counts read the database")):
            self.assertEqual({(0, 0, 0): 2, (1, 0, 2): 1}, get_current_bin_piece_counts())

        start_new_sorting_session(reason="test")
        self.assertEqual({(0, 0, 0): 2, (1, 0, 2): 1}, get_current_bin_piece_counts())

        clear_current_session_bins(scope="bin", layer_index=0, section_index=0, bin_index=0)
        self.assertEqual({(0, 0, 0): 0, (1, 0, 2): 1}, get_current_bin_piece_counts())

        clear_current_session_bins(scope="all")
        self.assertEqual({(0, 0, 0): 0, (1, 0, 2): 0}, get_current_bin_piece_counts())

    def test_bin_snapshots_accumulate_layers_and_close_on_all_clear(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
