import unittest

from runtime_stats import RuntimeStatsCollector


class RuntimeStatsCollectorBinClearTests(unittest.TestCase):
    def test_clear_layer_hides_older_contents_but_keeps_newer_pieces(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)

        collector.observeKnownObject(
            {
                "uuid": "piece-old-layer",
                "destination_bin": [0, 0, 0],
                "distributed_at": 10.0,
                "part_id": "3001",
                "classification_status": "classified",
            }
        )
        collector.observeKnownObject(
            {
                "uuid": "piece-other-layer",
                "destination_bin": [1, 0, 0],
                "distributed_at": 11.0,
                "part_id": "3002",
                "classification_status": "classified",
            }
        )

        before = collector.binContentsSnapshot()
        self.assertEqual(2, len(before["bins"]))

        collector.clearBinContents(scope="layer", layer_index=0, cleared_at=20.0)

        after_clear = collector.binContentsSnapshot()
        self.assertEqual(1, len(after_clear["bins"]))
        self.assertEqual("1:0:0", after_clear["bins"][0]["bin_key"])

        collector.observeKnownObject(
            {
                "uuid": "piece-new-layer",
                "destination_bin": [0, 0, 0],
                "distributed_at": 21.0,
                "part_id": "3003",
                "classification_status": "classified",
            }
        )

        after_new_piece = collector.binContentsSnapshot()
        by_key = {entry["bin_key"]: entry for entry in after_new_piece["bins"]}
        self.assertEqual(2, len(by_key))
        self.assertEqual(1, by_key["0:0:0"]["piece_count"])
        self.assertEqual("piece-new-layer", by_key["0:0:0"]["recent_pieces"][0]["uuid"])
        self.assertEqual(1, by_key["1:0:0"]["piece_count"])

    def test_clear_bin_only_affects_target_bin(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)

        collector.observeKnownObject(
            {
                "uuid": "piece-target",
                "destination_bin": [0, 0, 0],
                "distributed_at": 10.0,
                "part_id": "3001",
                "classification_status": "classified",
            }
        )
        collector.observeKnownObject(
            {
                "uuid": "piece-neighbor",
                "destination_bin": [0, 0, 1],
                "distributed_at": 11.0,
                "part_id": "3002",
                "classification_status": "classified",
            }
        )

        collector.clearBinContents(scope="bin", layer_index=0, section_index=0, bin_index=0, cleared_at=20.0)

        after_clear = collector.binContentsSnapshot()
        by_key = {entry["bin_key"]: entry for entry in after_clear["bins"]}
        self.assertNotIn("0:0:0", by_key)
        self.assertEqual(1, by_key["0:0:1"]["piece_count"])


if __name__ == "__main__":
    unittest.main()
