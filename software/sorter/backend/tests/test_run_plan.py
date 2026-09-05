"""Run selection: layer roles decide which bins a rule may take, the operator
picks the primary rules of a run, everything unplanned passes through, and the
set progress sync forwards each set's Hive instance id."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from defs.known_object import KnownObject
from irl.bin_layout import BinLayoutConfig, LayerConfig, applyCategories, getBinLayout, mkLayoutFromConfig, saveBinLayout
from local_state import get_bin_categories, get_run_plan, initialize_local_state, set_bin_categories
from run_plan import activeRules, defaultPrimarySelection, planCategories, roleCapacity
from runtime_stats import RuntimeStatsCollector
from server import shared_state
from server.routers import hardware, sorting_profiles
from set_progress import SetProgressTracker
from server.set_progress_sync import SetProgressSyncWorker
from sorting_profile import JsonSortingProfile, ruleRole
from subsystems.distribution.chute import Chute
from subsystems.distribution.positioning import Positioning
from subsystems.distribution.states import DistributionState
from subsystems.bus import TickBus
from subsystems.shared_variables import SharedVariables


def _rule(rule_id: str, rule_type: str = "set", **extra) -> dict:
    return {"id": rule_id, "name": rule_id.upper(), "rule_type": rule_type, "disabled": False, **extra}


RULES = [
    _rule("set_a", set_num="1234-1", set_instance_id="inst-a", set_meta={"name": "Set A"}),
    _rule("set_b", set_num="5678-1"),
    _rule("set_c", set_num="9999-1"),
    _rule("printed", "filter"),
    _rule("minifig", "filter"),
    _rule("skipped", "filter", disabled=True),
    _rule("side_set", role="secondary", set_num="1111-1"),
]

# Layer 0: primary, 1 section x 2 bins. Layer 1: secondary, 2 sections x 1 bin,
# second section disabled. Layer 2: disabled primary layer.
CONFIG = BinLayoutConfig(layers=[
    LayerConfig(sections=[["medium", "medium"]]),
    LayerConfig(sections=[["medium"], ["medium"]], role="secondary", section_enabled=[True, False]),
    LayerConfig(sections=[["medium"]], enabled=False),
])


class RuleRoleTests(unittest.TestCase):
    def test_default_role_follows_rule_type_and_explicit_role_wins(self) -> None:
        self.assertEqual("primary", ruleRole(_rule("x", "set")))
        self.assertEqual("secondary", ruleRole(_rule("x", "filter")))
        self.assertEqual("secondary", ruleRole(_rule("x", "set", role="secondary")))
        self.assertEqual("primary", ruleRole(_rule("x", "filter", role="primary")))
        self.assertEqual("secondary", ruleRole(_rule("x", "filter", role="bogus")))


class PlanCategoriesTests(unittest.TestCase):
    def test_capacity_counts_only_enabled_layers_and_sections(self) -> None:
        self.assertEqual({"primary": 2, "secondary": 1}, roleCapacity(CONFIG))

    def test_default_selection_is_the_first_n_primary_rules(self) -> None:
        self.assertEqual(["set_a", "set_b"], defaultPrimarySelection(RULES, CONFIG))

    def test_selected_primaries_fill_primary_bins_in_rule_order(self) -> None:
        categories = planCategories(CONFIG, RULES, ["set_c", "set_a"])
        self.assertEqual([[["set_a"], ["set_c"]]], categories[0])

    def test_secondaries_fill_secondary_bins_and_leftovers_stay_unassigned(self) -> None:
        categories = planCategories(CONFIG, RULES, ["set_a"])
        self.assertEqual([[["set_a"], []]], categories[0])
        self.assertEqual([[["printed"]], [[]]], categories[1], "disabled section gets nothing")
        self.assertEqual([[[]]], categories[2], "disabled layer gets nothing")
        assigned = {cid for layer in categories for section in layer for b in section for cid in b}
        self.assertEqual({"set_a", "printed"}, assigned)

    def test_disabled_rules_never_take_a_bin(self) -> None:
        config = BinLayoutConfig(layers=[LayerConfig(sections=[["medium"] * 5], role="secondary")])
        categories = planCategories(config, activeRules({"rules": RULES}), [])
        self.assertEqual([[["printed"], ["minifig"], ["side_set"], [], []]], categories[0])


class _LocalStateCase(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {k: os.environ.get(k) for k in ("MACHINE_SPECIFIC_PARAMS_PATH", "LOCAL_STATE_DB_PATH")}
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        (root / "machine_params.toml").write_text("[machine]\nnickname = \"Bench\"\n", encoding="utf-8")
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(root / "machine_params.toml")
        os.environ["LOCAL_STATE_DB_PATH"] = str(root / "local_state.sqlite")
        initialize_local_state()
        saveBinLayout(CONFIG)
        self.profile_path = root / "profile.json"
        self.profile_path.write_text(json.dumps({"part_to_category": {}, "rules": RULES, "artifact_hash": "h1"}))
        self._saved = (shared_state.gc_ref, shared_state.controller_ref)
        shared_state.gc_ref = SimpleNamespace(sorting_profile_path=str(self.profile_path), runtime_stats=None)
        shared_state.controller_ref = None

    def tearDown(self) -> None:
        shared_state.gc_ref, shared_state.controller_ref = self._saved
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmpdir.cleanup()


class RunPlanEndpointTests(_LocalStateCase):
    def test_apply_profile_plan_takes_the_first_primaries_and_reports_them_selected(self) -> None:
        artifact = json.loads(self.profile_path.read_text())
        self.assertEqual(3, sorting_profiles._plan_profile_run(artifact))
        self.assertEqual([[[["set_a"], ["set_b"]]], [[["printed"]], [[]]], [[[]]]], get_bin_categories())
        self.assertEqual(["set_a", "set_b"], get_run_plan()["primary_rule_ids"])

        view = sorting_profiles.get_run_plan_view()
        self.assertTrue(view["planned"])
        self.assertEqual({"primary": 2, "secondary": 1}, view["capacity"])
        self.assertEqual(
            [("set_a", True), ("set_b", True), ("set_c", False)],
            [(rule["id"], rule["selected"]) for rule in view["primary"]],
        )
        self.assertEqual("inst-a", view["primary"][0]["set_instance_id"])
        self.assertEqual({"name": "Set A"}, view["primary"][0]["set_meta"])
        self.assertEqual({"layer_index": 0, "section_index": 0, "bin_index": 1}, view["primary"][1]["bin"])
        self.assertIsNone(view["primary"][2]["bin"])
        self.assertEqual(
            [("printed", {"layer_index": 1, "section_index": 0, "bin_index": 0}), ("minifig", None), ("side_set", None)],
            [(rule["id"], rule["bin"]) for rule in view["secondary"]],
        )

    def test_selection_replaces_the_plan_and_is_validated(self) -> None:
        result = sorting_profiles.apply_run_plan_selection(
            sorting_profiles.RunPlanPayload(primary_rule_ids=["set_c"])
        )
        self.assertEqual(2, result["assigned_count"])
        self.assertEqual([[[["set_c"], []]], [[["printed"]], [[]]], [[[]]]], get_bin_categories())
        self.assertEqual([False, False, True], [rule["selected"] for rule in result["primary"]])

        with self.assertRaises(HTTPException) as too_many:
            sorting_profiles.apply_run_plan_selection(
                sorting_profiles.RunPlanPayload(primary_rule_ids=["set_a", "set_b", "set_c"])
            )
        self.assertEqual(400, too_many.exception.status_code)
        with self.assertRaises(HTTPException) as unknown:
            sorting_profiles.apply_run_plan_selection(
                sorting_profiles.RunPlanPayload(primary_rule_ids=["printed"])
            )
        self.assertEqual(400, unknown.exception.status_code)

    def test_without_a_plan_selected_means_holds_a_bin(self) -> None:
        set_bin_categories([[[[], ["set_b"]]], [[[]], [[]]], [[[]]]])
        view = sorting_profiles.get_run_plan_view()
        self.assertFalse(view["planned"])
        self.assertEqual([False, True, False], [rule["selected"] for rule in view["primary"]])

    def test_reset_all_bins_ends_the_plan(self) -> None:
        sorting_profiles._plan_profile_run(json.loads(self.profile_path.read_text()))
        with patch.object(hardware, "clear_current_session_bins", return_value={"ok": True}):
            hardware.clear_bin_category_assignments(scope="all")
        self.assertIsNone(get_run_plan())


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    warning = warn = error = info


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass

    enterState = exitState = hit

    def timer(self, *args, **kwargs):
        return contextlib.nullcontext()


class PlannedPassthroughTests(_LocalStateCase):
    """A rule left out of the plan must neither claim a free bin nor raise the
    no-bin incident; without a plan the dynamic claim still works."""

    def _positioning(self, profile: JsonSortingProfile) -> tuple[Positioning, MagicMock]:
        gc = SimpleNamespace(
            logger=_Logger(), profiler=_Profiler(), runtime_stats=RuntimeStatsCollector(), set_progress_tracker=None,
            disable_servos=True, use_channel_bus=False, sorting_profile_path=str(self.profile_path),
        )
        shared = SharedVariables(gc=gc, bus=TickBus())
        shared.transport = SimpleNamespace(
            getPieceForDistributionPositioning=lambda: KnownObject(part_id="3001", color_id="5")
        )
        chute = MagicMock(spec=Chute)
        chute.isBinReachable = MagicMock(return_value=True)
        layout = mkLayoutFromConfig(getBinLayout())
        applyCategories(layout, get_bin_categories())
        positioning = Positioning(
            irl=SimpleNamespace(servos=[]), gc=gc, shared=shared, chute=chute,
            layout=layout, sorting_profile=profile, event_queue=queue.Queue(),
        )
        return positioning, chute

    def _profile(self) -> JsonSortingProfile:
        artifact = json.loads(self.profile_path.read_text())
        artifact["part_to_category"] = {"any_color-3001": "set_c"}
        self.profile_path.write_text(json.dumps(artifact))
        return JsonSortingProfile(SimpleNamespace(sorting_profile_path=str(self.profile_path), logger=_Logger()))

    def test_unplanned_rule_passes_through_under_a_plan(self) -> None:
        profile = self._profile()
        sorting_profiles._apply_run_plan(json.loads(self.profile_path.read_text()), ["set_a"])
        positioning, chute = self._positioning(profile)
        with patch.object(Positioning, "_openAllDoorsForPassthrough") as open_all:
            self.assertEqual(DistributionState.READY, positioning.step())
        open_all.assert_called_once()
        chute.moveToBin.assert_not_called()
        self.assertEqual([[[["set_a"], []]], [[["printed"]], [[]]], [[[]]]], get_bin_categories(), "free bin not claimed")

    def test_without_a_plan_the_rule_claims_the_free_bin(self) -> None:
        profile = self._profile()
        set_bin_categories([[[["set_a"], []]], [[[]], [[]]], [[[]]]])
        positioning, chute = self._positioning(profile)
        with patch.object(Positioning, "_selectDoor", return_value=True), patch.object(Positioning, "_startChuteMove"):
            positioning.step()
        self.assertEqual([[[["set_a"], ["set_c"]]], [[[]], [[]]], [[[]]]], get_bin_categories())


class ProfileRuleMetadataTests(_LocalStateCase):
    def test_profile_exposes_rule_roles_and_set_instance_ids(self) -> None:
        profile = JsonSortingProfile(SimpleNamespace(sorting_profile_path=str(self.profile_path), logger=_Logger()))
        self.assertEqual("primary", profile.ruleRole("set_a"))
        self.assertEqual("secondary", profile.ruleRole("printed"))
        self.assertEqual("secondary", profile.ruleRole("side_set"))
        self.assertIsNone(profile.ruleRole("misc"))
        self.assertEqual({"set_a": "inst-a"}, profile.set_instance_ids)


class SetProgressSyncPayloadTests(_LocalStateCase):
    INVENTORIES = {
        "set_a": {"set_num": "1234-1", "name": "Set A", "parts": [{"part_num": "3001", "color_id": "5", "quantity": 2}]},
        "set_b": {"set_num": "5678-1", "name": "Set B", "parts": [{"part_num": "3002", "color_id": "1", "quantity": 1}]},
    }

    def test_sync_payload_carries_the_set_instance_id_per_set(self) -> None:
        tracker = SetProgressTracker(self.INVENTORIES, "h1", set_instance_ids={"set_a": "inst-a"})
        tracker.record("3001", "5", "set_a")
        items = tracker.get_sync_payload()["items"]
        by_category = {item["category_id"]: item for item in items}
        self.assertEqual("inst-a", by_category["set_a"]["set_instance_id"])
        self.assertIsNone(by_category["set_b"]["set_instance_id"])
        self.assertEqual(1, by_category["set_a"]["quantity_found"])
        self.assertEqual(
            ["inst-a", None], [entry["set_instance_id"] for entry in tracker.get_progress()["sets"]]
        )

    def test_worker_report_forwards_tracker_items_verbatim(self) -> None:
        tracker = SetProgressTracker(self.INVENTORIES, "h1", set_instance_ids={"set_a": "inst-a"})
        shared_state.gc_ref = SimpleNamespace(set_progress_tracker=tracker)
        target = {"id": "t1", "enabled": True, "url": "https://hive.test", "api_token": "tok"}
        with (
            patch("server.set_progress_sync.getSortingProfileSyncState", return_value={"target_id": "t1", "version_id": "v1"}),
            patch("server.set_progress_sync._load_targets", return_value=[target]),
            patch("server.set_progress_sync.telemetryAllows", return_value=True),
        ):
            report = SetProgressSyncWorker()._build_report()
        self.assertEqual({"version_id": "v1", "artifact_hash": "h1"}, {k: report["payload"][k] for k in ("version_id", "artifact_hash")})
        self.assertEqual(
            {("set_a", "inst-a"), ("set_b", None)},
            {(item["category_id"], item["set_instance_id"]) for item in report["payload"]["items"]},
        )
