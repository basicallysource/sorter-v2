import os
import random
import tempfile
import unittest

from subsystems.feeder.pulse_perception.autotune import (
    TUNABLE_PARAMS,
    computeTrialMetrics,
    normalizeSettings,
    sampleCandidate,
)


class FeederAutotuneSamplerTests(unittest.TestCase):
    def test_samples_stay_in_bounds(self) -> None:
        rng = random.Random(42)
        keys = [meta["key"] for meta in TUNABLE_PARAMS]
        bounds = {meta["key"]: (meta["min"], meta["max"]) for meta in TUNABLE_PARAMS}
        best = {key: bounds[key][1] for key in keys}
        for _ in range(200):
            kind, params = sampleCandidate(
                keys, best, rng, explore_probability=0.5, sigma_fraction=0.3
            )
            self.assertIn(kind, ("explore", "refine"))
            for key, value in params.items():
                lo, hi = bounds[key]
                self.assertGreaterEqual(value, lo)
                self.assertLessEqual(value, hi)

    def test_int_params_are_ints(self) -> None:
        rng = random.Random(7)
        int_keys = [m["key"] for m in TUNABLE_PARAMS if m["type"] == "int"]
        _, params = sampleCandidate(
            int_keys, None, rng, explore_probability=1.0, sigma_fraction=0.15
        )
        for value in params.values():
            self.assertIsInstance(value, int)

    def test_no_best_forces_explore(self) -> None:
        rng = random.Random(3)
        kind, _ = sampleCandidate(
            ["drop_pulse_output_deg"], None, rng,
            explore_probability=0.0, sigma_fraction=0.15,
        )
        self.assertEqual(kind, "explore")


class FeederAutotuneScoreTests(unittest.TestCase):
    def test_clean_trial_scores_ppm(self) -> None:
        metrics = computeTrialMetrics(
            measured_s=120.0, pieces_delivered=20, incidents=0, double_drops=0,
            incident_weight=10.0, max_double_drop_rate=0.05,
        )
        self.assertEqual(metrics["pieces_per_min"], 10.0)
        self.assertEqual(metrics["double_drop_rate"], 0.0)
        self.assertTrue(metrics["feasible"])
        self.assertEqual(metrics["score"], 10.0)

    def test_double_drop_rate_over_cap_is_infeasible(self) -> None:
        metrics = computeTrialMetrics(
            measured_s=120.0, pieces_delivered=20, incidents=0, double_drops=2,
            incident_weight=10.0, max_double_drop_rate=0.05,
        )
        self.assertEqual(metrics["double_drop_rate"], 0.1)
        self.assertFalse(metrics["feasible"])
        self.assertIsNone(metrics["score"])
        self.assertEqual(metrics["pieces_per_min"], 10.0)

    def test_rate_at_cap_is_feasible(self) -> None:
        metrics = computeTrialMetrics(
            measured_s=120.0, pieces_delivered=20, incidents=0, double_drops=1,
            incident_weight=10.0, max_double_drop_rate=0.05,
        )
        self.assertEqual(metrics["double_drop_rate"], 0.05)
        self.assertTrue(metrics["feasible"])

    def test_incidents_penalize_feasible_score(self) -> None:
        metrics = computeTrialMetrics(
            measured_s=120.0, pieces_delivered=20, incidents=1, double_drops=0,
            incident_weight=10.0, max_double_drop_rate=0.05,
        )
        self.assertEqual(metrics["score"], 10.0 - 10.0 * 0.5)

    def test_zero_measurement_gives_none(self) -> None:
        metrics = computeTrialMetrics(
            measured_s=0.0, pieces_delivered=0, incidents=0, double_drops=0,
            incident_weight=10.0, max_double_drop_rate=0.05,
        )
        self.assertIsNone(metrics["pieces_per_min"])
        self.assertIsNone(metrics["score"])
        self.assertFalse(metrics["feasible"])

    def test_double_drops_with_zero_pieces_infeasible(self) -> None:
        metrics = computeTrialMetrics(
            measured_s=60.0, pieces_delivered=0, incidents=0, double_drops=1,
            incident_weight=10.0, max_double_drop_rate=0.05,
        )
        self.assertFalse(metrics["feasible"])


class FeederAutotuneSettingsTests(unittest.TestCase):
    def test_defaults_and_clamps(self) -> None:
        settings = normalizeSettings(None)
        self.assertEqual(settings["trial_duration_s"], 120.0)
        self.assertEqual(
            settings["param_keys"], [m["key"] for m in TUNABLE_PARAMS]
        )
        clamped = normalizeSettings({"trial_duration_s": 1, "param_keys": ["bogus"]})
        self.assertEqual(clamped["trial_duration_s"], 20.0)
        self.assertEqual(
            clamped["param_keys"], [m["key"] for m in TUNABLE_PARAMS]
        )

    def test_param_key_filtering(self) -> None:
        settings = normalizeSettings(
            {"param_keys": ["drop_pulse_output_deg", "nope"], "max_trials": 5}
        )
        self.assertEqual(settings["param_keys"], ["drop_pulse_output_deg"])
        self.assertEqual(settings["max_trials"], 5)

    def test_max_double_drop_rate_clamped(self) -> None:
        settings = normalizeSettings({"max_double_drop_rate": 3.0})
        self.assertEqual(settings["max_double_drop_rate"], 0.5)
        settings = normalizeSettings({"max_double_drop_rate": 0.02})
        self.assertEqual(settings["max_double_drop_rate"], 0.02)


class FeederAutotuneStorageTests(unittest.TestCase):
    def test_run_and_trial_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(tmp, "state.sqlite")
            try:
                import importlib
                import local_state

                importlib.reload(local_state)
                run = local_state.createFeederAutotuneRun(
                    {"drop_pulse_output_deg": 30.0}, {"trial_duration_s": 60.0}
                )
                self.assertIsNotNone(run)
                self.assertEqual(run["status"], "active")
                trial_id = local_state.insertFeederAutotuneTrial(
                    run["id"], 0, "baseline", {"drop_pulse_output_deg": 30.0}
                )
                local_state.finalizeFeederAutotuneTrial(
                    trial_id,
                    status="done",
                    measured_s=60.0,
                    pieces_delivered=12,
                    incidents=0,
                    double_drops=1,
                    pieces_per_min=12.0,
                    double_drop_rate=1 / 12,
                    feasible=False,
                    score=9.0,
                )
                local_state.setFeederAutotuneBestTrial(run["id"], trial_id)
                local_state.finishFeederAutotuneRun(run["id"], "finished")

                fetched = local_state.getFeederAutotuneRun(run["id"])
                self.assertEqual(fetched["status"], "finished")
                self.assertEqual(fetched["best_trial_id"], trial_id)
                trials = local_state.listFeederAutotuneTrials(run["id"])
                self.assertEqual(len(trials), 1)
                self.assertEqual(trials[0]["pieces_delivered"], 12)
                self.assertEqual(trials[0]["feasible"], False)
                self.assertAlmostEqual(trials[0]["double_drop_rate"], 1 / 12)
                self.assertEqual(
                    trials[0]["params_json"], {"drop_pulse_output_deg": 30.0}
                )
                dataset = local_state.listFeederAutotuneDataset()
                self.assertEqual(len(dataset), 1)

                local_state.setFeederAutotuneBackground(
                    {"enabled": True, "settings": {}, "baseline_config": {}}
                )
                self.assertTrue(
                    local_state.getFeederAutotuneBackground()["enabled"]
                )
                local_state.setFeederAutotuneBackground(None)
                self.assertIsNone(local_state.getFeederAutotuneBackground())

                interrupted_run = local_state.createFeederAutotuneRun(
                    {"drop_pulse_output_deg": 25.0}, {}
                )
                local_state.insertFeederAutotuneTrial(
                    interrupted_run["id"], 0, "explore", {"drop_pulse_output_deg": 40.0}
                )
                recovered = local_state.interruptActiveFeederAutotuneRuns()
                self.assertEqual(len(recovered), 1)
                self.assertEqual(recovered[0]["id"], interrupted_run["id"])
                after = local_state.getFeederAutotuneRun(interrupted_run["id"])
                self.assertEqual(after["status"], "interrupted")
                aborted = local_state.listFeederAutotuneTrials(interrupted_run["id"])
                self.assertEqual(aborted[0]["status"], "aborted")
            finally:
                os.environ.pop("LOCAL_STATE_DB_PATH", None)
                import importlib
                import local_state

                importlib.reload(local_state)


if __name__ == "__main__":
    unittest.main()
