import unittest
from unittest.mock import patch

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

    def test_snapshot_includes_channel_throughput_and_active_ppm(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=100.0, now_monotonic=10.0)

        collector.observeFeederSignals(
            {"stepper_busy_ch2": True},
            now_wall=101.0,
            now_monotonic=11.0,
        )
        collector.observeStateTransition(
            "classification.occupancy",
            None,
            "classification_channel.rotate_pipeline",
            now_wall=101.0,
            now_monotonic=11.0,
        )
        collector.observeChannelExit("c_channel_2", exited_at=105.0, global_id=101)
        collector.observeChannelExit(
            "classification_channel",
            exited_at=112.0,
            piece_uuid="piece-classified",
            global_id=202,
        )
        collector.observeKnownObject(
            {
                "uuid": "piece-classified",
                "classification_status": "classified",
                "classified_at": 111.0,
                "distributed_at": 114.0,
            }
        )
        collector.observeKnownObject(
            {
                "uuid": "piece-unknown",
                "classification_status": "unknown",
                "classified_at": 115.0,
            }
        )
        collector.observeFeederSignals(
            {"stepper_busy_ch2": False},
            now_wall=111.0,
            now_monotonic=21.0,
        )
        collector.observeStateTransition(
            "classification.occupancy",
            "classification_channel.rotate_pipeline",
            "classification_channel.wait_piece_trigger",
            now_wall=121.0,
            now_monotonic=31.0,
        )
        collector.setLifecycleState("ready", now_wall=160.0, now_monotonic=70.0)

        snapshot = collector.snapshot()
        channels = snapshot["channel_throughput"]

        self.assertEqual(1, channels["c_channel_2"]["exit_count"])
        self.assertAlmostEqual(1.0, channels["c_channel_2"]["overall_ppm"])
        self.assertAlmostEqual(6.0, channels["c_channel_2"]["active_ppm"])
        self.assertAlmostEqual(10.0, channels["c_channel_2"]["active_time_s"])

        c4 = channels["classification_channel"]
        self.assertEqual(1, c4["exit_count"])
        self.assertAlmostEqual(20.0, c4["active_time_s"])
        self.assertEqual(1, c4["outcomes"]["classified_success"]["count"])
        self.assertEqual(1, c4["outcomes"]["distributed_success"]["count"])
        self.assertEqual(1, c4["outcomes"]["unknown"]["count"])
        self.assertEqual(0, c4["outcomes"]["multi_drop_fail"]["count"])


class RuntimeStatsRecognizerCountersTests(unittest.TestCase):
    def test_snapshot_exposes_recognizer_counters_under_counts(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)

        collector.observeRecognizerCounter("recognize_fired_total")
        collector.observeRecognizerCounter("recognize_fired_total")
        collector.observeRecognizerCounter("recognize_skipped_no_crops")
        collector.observeRecognizerCounter("brickognize_empty_result")
        collector.observeRecognizerCounter("brickognize_timeout_total")
        collector.observeRecognizerCounter("unknown_counter_name")  # ignored

        counts = collector.snapshot()["counts"]
        self.assertEqual(2, counts["recognize_fired_total"])
        self.assertEqual(1, counts["recognize_skipped_no_crops"])
        self.assertEqual(1, counts["brickognize_empty_result"])
        self.assertEqual(1, counts["brickognize_timeout_total"])

    def test_classification_zone_lost_counter_bumps_and_surfaces_in_snapshot(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)

        for _ in range(3):
            collector.observeClassificationZoneLost()

        feeder = collector.snapshot()["feeder"]
        self.assertEqual(3, feeder["classification_zone_lost_total"])


class RuntimeStatsDossierSeedTests(unittest.TestCase):
    def test_observe_known_object_can_seed_counts_while_stopped(self) -> None:
        collector = RuntimeStatsCollector()

        collector.observeKnownObject(
            {
                "uuid": "piece-classified",
                "stage": "distributed",
                "classification_status": "classified",
                "classified_at": 100.0,
                "distributed_at": 104.0,
            },
            count_when_stopped=True,
        )

        snapshot = collector.snapshot()
        self.assertEqual(1, snapshot["counts"]["pieces_seen"])
        self.assertEqual(1, snapshot["counts"]["classified"])
        self.assertEqual(1, snapshot["counts"]["distributed"])
        self.assertEqual(
            1,
            snapshot["channel_throughput"]["classification_channel"]["outcomes"][
                "classified_success"
            ]["count"],
        )
        self.assertEqual(
            1,
            snapshot["channel_throughput"]["classification_channel"]["outcomes"][
                "distributed_success"
            ]["count"],
        )

    def test_service_snapshot_falls_back_to_piece_dossiers_without_collector(self) -> None:
        from server.services import runtime_stats as runtime_stats_service

        dossiers = [
            {
                "uuid": "piece-a",
                "stage": "distributed",
                "classification_status": "classified",
                "classified_at": 200.0,
                "distributed_at": 204.0,
            }
        ]

        with (
            patch.object(runtime_stats_service, "_collector", return_value=None),
            patch("local_state.list_piece_dossiers", return_value=dossiers),
        ):
            snapshot = runtime_stats_service.snapshot()

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(1, snapshot["counts"]["pieces_seen"])
        self.assertEqual(1, snapshot["counts"]["classified"])
        self.assertEqual(1, snapshot["counts"]["distributed"])


if __name__ == "__main__":
    unittest.main()
