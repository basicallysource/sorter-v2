import unittest

from runtime_stats import C4_WAITING_FOR_PIECE, RuntimeStatsCollector, _calcMsSummary, _calcValueSummary


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

    def test_c4_active_ppm_leaves_out_waiting_for_a_piece(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=100.0, now_monotonic=10.0)

        def enter(prev: str | None, state: str, t: float) -> None:
            collector.observeStateTransition(
                "classification", prev, state, now_wall=90.0 + t, now_monotonic=t
            )

        enter(None, C4_WAITING_FOR_PIECE, 10.0)
        enter(C4_WAITING_FOR_PIECE, "waiting", 40.0)
        enter("waiting", "ejecting", 50.0)
        collector.observeC4Exit()
        enter("ejecting", C4_WAITING_FOR_PIECE, 70.0)
        collector.setLifecycleState("ready", now_wall=190.0, now_monotonic=100.0)

        c4 = collector.snapshot()["channel_throughput"]["classification_channel"]
        self.assertEqual(1, c4["exit_count"])
        # 10 s waiting on its own pieces and 20 s ejecting; the 60 s waiting for
        # the feeder is not C4 working.
        self.assertAlmostEqual(30.0, c4["active_time_s"])
        self.assertAlmostEqual(2.0, c4["active_ppm"])

    def test_snapshot_exposes_and_clears_active_incident(self) -> None:
        collector = RuntimeStatsCollector()

        collector.setActiveIncident(
            {
                "kind": "exit_stuck",
                "source_kind": "classification_exit_release",
                "piece_uuid": "piece-stuck",
                "status": "waiting_for_operator",
            }
        )

        snapshot = collector.snapshot()
        self.assertEqual("exit_stuck", snapshot["active_incident"]["kind"])
        self.assertEqual("classification_exit_release", snapshot["active_incident"]["source_kind"])
        self.assertEqual("piece-stuck", snapshot["active_incident"]["piece_uuid"])
        active = collector.activeIncident()
        self.assertIsNotNone(active)
        active["piece_uuid"] = "mutated"
        self.assertEqual("piece-stuck", collector.activeIncident()["piece_uuid"])

        collector.clearActiveIncident(
            kind="exit_stuck",
            piece_uuid="piece-stuck",
        )

        self.assertIsNone(collector.snapshot()["active_incident"])

    def test_live_snapshot_is_only_what_the_dashboard_shows(self) -> None:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)
        collector.observeStateTransition("feeder", None, "idle", now_wall=2.0, now_monotonic=2.0)
        collector.observePerfMs("main.loop.interval_ms", 10.0)

        live = collector.snapshot(live=True)

        self.assertEqual(
            {"counts", "throughput", "channel_throughput", "state_machines", "bus_recent", "active_incident", "incident_card"},
            set(live),
        )
        self.assertEqual({"current_state": "idle", "entered_at": 2.0}, live["state_machines"]["feeder"])
        self.assertEqual(collector.snapshot()["counts"], live["counts"])


class RuntimeStatsReapStuckPiecesTests(unittest.TestCase):
    def _running(self) -> RuntimeStatsCollector:
        collector = RuntimeStatsCollector()
        collector.setLifecycleState("running", now_wall=1.0, now_monotonic=1.0)
        return collector

    def test_reaps_silent_undistributed_piece_past_timeout(self) -> None:
        collector = self._running()
        collector.observeKnownObject(
            {
                "uuid": "piece-stuck",
                "classification_status": "classified",
                "stage": "created",
                "created_at": 100.0,
                "updated_at": 100.0,
            }
        )

        # Still within the window: nothing reaped.
        self.assertEqual([], collector.reapStuckPieces(now=120.0, timeout_s=30.0))
        self.assertIsNone(collector.lookupKnownObject("piece-stuck").get("dead"))

        reaped = collector.reapStuckPieces(now=131.0, timeout_s=30.0)
        self.assertEqual(1, len(reaped))
        self.assertEqual("piece-stuck", reaped[0]["uuid"])
        self.assertTrue(reaped[0]["dead"])
        self.assertTrue(collector.lookupKnownObject("piece-stuck")["dead"])
        self.assertEqual(1, collector.snapshot()["counts"]["stuck_reaped_total"])

    def test_reaping_is_idempotent_per_piece(self) -> None:
        collector = self._running()
        collector.observeKnownObject(
            {"uuid": "p", "stage": "created", "created_at": 0.0, "updated_at": 0.0}
        )
        self.assertEqual(1, len(collector.reapStuckPieces(now=100.0, timeout_s=30.0)))
        # Already dead — not reaped or counted again.
        self.assertEqual([], collector.reapStuckPieces(now=200.0, timeout_s=30.0))
        self.assertEqual(1, collector.snapshot()["counts"]["stuck_reaped_total"])

    def test_does_not_reap_distributed_or_aborted_pieces(self) -> None:
        collector = self._running()
        collector.observeKnownObject(
            {
                "uuid": "done",
                "stage": "distributed",
                "distributed_at": 5.0,
                "updated_at": 5.0,
            }
        )
        collector.observeKnownObject(
            {"uuid": "gone", "stage": "created", "aborted": True, "updated_at": 5.0}
        )
        self.assertEqual([], collector.reapStuckPieces(now=1000.0, timeout_s=30.0))

    def test_no_reaping_while_not_running(self) -> None:
        collector = RuntimeStatsCollector()
        # Observed while not running: only the lookup is populated.
        collector.observeKnownObject(
            {"uuid": "p", "stage": "created", "updated_at": 0.0}
        )
        self.assertEqual([], collector.reapStuckPieces(now=1000.0, timeout_s=30.0))

    def test_progress_after_reap_self_recovers(self) -> None:
        collector = self._running()
        collector.observeKnownObject(
            {"uuid": "p", "stage": "created", "created_at": 0.0, "updated_at": 0.0}
        )
        self.assertEqual(1, len(collector.reapStuckPieces(now=100.0, timeout_s=30.0)))
        self.assertTrue(collector.lookupKnownObject("p")["dead"])

        # A later event for the same piece (it actually progressed) carries the
        # model default dead=False, clearing the reaped flag.
        collector.observeKnownObject(
            {"uuid": "p", "stage": "distributed", "distributed_at": 101.0, "dead": False, "updated_at": 101.0}
        )
        self.assertFalse(collector.lookupKnownObject("p")["dead"])
        self.assertEqual([], collector.reapStuckPieces(now=200.0, timeout_s=30.0))


if __name__ == "__main__":
    unittest.main()


class SummaryTests(unittest.TestCase):
    def test_summaries_report_mean_median_and_spread(self) -> None:
        self.assertEqual(
            {"n": 4, "avg_ms": 2.5, "med_ms": 2.5, "p90_ms": 4.0, "min_ms": 1.0, "max_ms": 4.0, "last_ms": 4.0},
            _calcMsSummary([3.0, 1.0, 2.0, 4.0]),
        )
        self.assertEqual(
            {"n": 3, "avg": 2.0, "med": 2.0, "p90": 3.0, "min": 1.0, "max": 3.0},
            _calcValueSummary([3, 1, 2]),
        )
        self.assertEqual({"n": 0}, _calcMsSummary([]))
