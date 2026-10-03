"""The sorter running a profile: the compiled program (first rule that takes
a piece), kits that pass pieces on once they have enough, and the flat part
map profiles compiled before the program still use."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from set_progress import SetProgressTracker
from sorting_profile import JsonSortingProfile, ProfileRouter, categoryResolver, profileSummary

PROGRAM = {
    "format": 1,
    "rules": [
        {"category": "kit", "kit": {"3001": ["5"], "3020": [None]}},
        {"category": "red-bricks", "parts": ["3001", "3003"], "colors": ["5"]},
        {"category": "bricks", "parts": ["3001", "3003", "3004"], "colors": None},
        {"category": "clear", "parts": None, "colors": ["12"]},
    ],
    "fallback": {"by": "category", "map": {"3020": "bl_26", "3068b": "bl_37"}},
    "default": "misc",
}
INVENTORIES = {
    "kit": {
        "rule_id": "kit",
        "set_num": "kit:order-42",
        "name": "Order 42",
        "parts": [
            {"part_num": "3001", "color_id": 5, "quantity": 2},
            {"part_num": "3020", "color_id": -1, "quantity": 1},
        ],
    }
}


@pytest.fixture()
def no_saved_progress(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr("set_progress.get_set_progress_state", lambda: saved.get("state"))
    monkeypatch.setattr("set_progress.set_set_progress_state", lambda state: saved.__setitem__("state", state))
    return saved


def _profile(tmp_path, artifact: dict) -> JsonSortingProfile:
    path = tmp_path / "active_sorting_profile.json"
    path.write_text(json.dumps(artifact))
    logger = SimpleNamespace(warn=lambda *_: None, warning=lambda *_: None, info=lambda *_: None)
    return JsonSortingProfile(SimpleNamespace(sorting_profile_path=str(path), logger=logger))


class TestProgram:
    def test_first_rule_that_takes_the_piece(self):
        router = ProfileRouter(PROGRAM)
        assert router.route("3003", "5") == "red-bricks"
        assert router.route("3003", "7") == "bricks"
        assert router.route("3068b", "12") == "clear"
        assert router.route("unknown-part", "12") == "clear"

    def test_fallback_then_default(self):
        router = ProfileRouter(PROGRAM)
        assert router.route("3068b", "7") == "bl_37"
        assert router.route("unknown-part", "7") == "misc"

    def test_an_unknown_color_only_matches_rules_for_any_color(self):
        router = ProfileRouter(PROGRAM)
        assert router.route("3003", "any_color") == "bricks"
        assert router.route("3003", None) == "bricks"

    def test_color_fallback(self):
        router = ProfileRouter({**PROGRAM, "fallback": {"by": "color"}})
        assert router.route("3068b", "7") == "color_7"
        assert router.route("3068b", None) == "misc"


class TestKits:
    def test_a_kit_takes_its_parts_until_it_has_enough(self, tmp_path, no_saved_progress):
        profile = _profile(tmp_path, {"program": PROGRAM, "set_inventories": INVENTORIES, "profile_type": "set"})
        tracker = SetProgressTracker(INVENTORIES, artifact_hash="h")
        profile.setKitProgress(tracker)

        assert profile.getCategoryIdForPart("3001", "5") == "kit"
        tracker.record("3001", "5", "kit")
        assert profile.getCategoryIdForPart("3001", "5") == "kit"
        tracker.record("3001", "5", "kit")
        # two of two found: the next red 2 x 4 goes on to the next rule
        assert profile.getCategoryIdForPart("3001", "5") == "red-bricks"

    def test_an_any_color_line_fills_with_any_color(self, tmp_path, no_saved_progress):
        profile = _profile(tmp_path, {"program": PROGRAM, "set_inventories": INVENTORIES, "profile_type": "set"})
        tracker = SetProgressTracker(INVENTORIES, artifact_hash="h")
        profile.setKitProgress(tracker)
        assert profile.getCategoryIdForPart("3020", "7") == "kit"
        tracker.record("3020", "7", "kit")
        assert profile.getCategoryIdForPart("3020", "11") == "bl_26"

    def test_without_a_tracker_a_kit_keeps_taking(self, tmp_path):
        profile = _profile(tmp_path, {"program": PROGRAM})
        assert profile.getCategoryIdForPart("3001", "5") == "kit"


class TestFlatMap:
    def test_a_profile_from_before_the_program(self, tmp_path):
        profile = _profile(
            tmp_path,
            {"part_to_category": {"5-3001": "red", "any_color-3001": "bricks"}, "default_category_id": "misc"},
        )
        assert profile.getCategoryIdForPart("3001", "5") == "red"
        assert profile.getCategoryIdForPart("3001", "7") == "bricks"
        assert profile.getCategoryIdForPart("3002", "7") == "misc"

    def test_the_resolver_reads_both(self):
        assert categoryResolver({"program": PROGRAM})("3003", "7") == "bricks"
        assert categoryResolver({"part_to_category": {"any_color-3003": "b"}})("3003", "7") == "b"


def test_the_summary_leaves_the_program_out(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"name": "P", "program": PROGRAM, "stats": {"matched": 42}}))
    summary = profileSummary(path)
    assert "program" not in summary
    assert summary["part_count"] == 42


class TestStartingOnADefault:
    def _setup(self, monkeypatch, tmp_path, *, active: bool, profiles: list[dict]):
        from server import shared_state
        from server.routers import sorting_profiles as router

        path = tmp_path / "active_sorting_profile.json"
        if active:
            path.write_text("{}")
        logger = SimpleNamespace(info=lambda *_: None, warning=lambda *_: None)
        monkeypatch.setattr(shared_state, "gc_ref", SimpleNamespace(sorting_profile_path=str(path), logger=logger))
        monkeypatch.setattr(router, "_load_targets", lambda: [{"id": "t1", "name": "Hive", "enabled": True}])
        monkeypatch.setattr(router, "_fetch_target_library", lambda target: {"profiles": profiles})
        applied: list = []
        monkeypatch.setattr(router, "apply_sorting_profile", lambda payload: applied.append(payload) or {"ok": True})
        return router, applied

    def test_a_new_sorter_starts_on_the_first_default(self, monkeypatch, tmp_path):
        profiles = [
            {"id": "mine", "name": "Mine", "is_default": False, "latest_published_version": {"id": "v0"}},
            {"id": "colors", "name": "Colors", "is_default": True, "default_rank": 2, "latest_published_version": {"id": "v2"}},
            {"id": "bl", "name": "BrickLink categories", "is_default": True, "default_rank": 1, "latest_published_version": {"id": "v1", "version_number": 3}},
        ]
        router, applied = self._setup(monkeypatch, tmp_path, active=False, profiles=profiles)
        router.apply_first_default_profile_if_none()
        assert [(p.profile_id, p.version_id, p.version_number) for p in applied] == [("bl", "v1", 3)]

    def test_a_sorter_with_a_profile_keeps_it(self, monkeypatch, tmp_path):
        router, applied = self._setup(
            monkeypatch, tmp_path, active=True,
            profiles=[{"id": "bl", "is_default": True, "default_rank": 1, "latest_published_version": {"id": "v1"}}],
        )
        assert router.apply_first_default_profile_if_none() is None
        assert applied == []


class TestApplyingFromHive:
    class _Client:
        api_url = "https://hive.example"

        def __init__(self, fail_on: str | None = None):
            self.fail_on = fail_on
            self.calls: list[str] = []

        def _call(self, name, value):
            self.calls.append(name)
            if self.fail_on == name:
                from server.hive_models import HiveError

                raise HiveError(409, "This profile needs newer sorter software. Update the sorter to run it.")
            return value

        def assign_profile(self, profile_id, version_id):
            return self._call("assign", {"ok": True})

        def profile_artifact(self, version_id):
            return self._call("artifact", {"program": PROGRAM, "artifact_hash": "abc", "name": "P", "rules": []})

        def report_profile_activation(self, version_id, artifact_hash):
            return self._call("activate", {"artifact_hash": artifact_hash})

    def _apply(self, monkeypatch, tmp_path, client):
        from server import shared_state
        from server.routers import sorting_profiles as router

        path = tmp_path / "active_sorting_profile.json"
        monkeypatch.setattr(shared_state, "gc_ref", SimpleNamespace(sorting_profile_path=str(path), logger=None))
        monkeypatch.setattr(shared_state, "publishSortingProfileStatus", lambda status: None)
        monkeypatch.setattr(router, "_get_target_or_404", lambda target_id: {"id": target_id, "name": "Hive", "url": "https://hive.example"})
        monkeypatch.setattr(router, "_target_client", lambda target: client)
        monkeypatch.setattr(router, "_reload_runtime_profile", lambda: True)
        monkeypatch.setattr(router, "start_new_sorting_session", lambda reason: None)
        saved: dict = {}
        monkeypatch.setattr(router, "set_sorting_profile_sync_state", lambda state: saved.update(state))
        monkeypatch.setattr(router, "get_sorting_profile_sync_state", lambda: saved)
        payload = router.ApplySortingProfilePayload(target_id="t1", profile_id="p1", profile_name="P", version_id="v1")
        return router.apply_sorting_profile(payload), path, saved

    def test_the_program_is_written_and_reported(self, monkeypatch, tmp_path):
        client = self._Client()
        result, path, saved = self._apply(monkeypatch, tmp_path, client)
        assert client.calls == ["assign", "artifact", "activate"]
        assert json.loads(path.read_text())["program"] == PROGRAM
        assert saved["artifact_hash"] == "abc"
        assert result["activation_error"] is None

    def test_a_profile_this_sorter_cannot_run_is_refused_with_hives_reason(self, monkeypatch, tmp_path):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as refused:
            self._apply(monkeypatch, tmp_path, self._Client(fail_on="artifact"))
        assert refused.value.status_code == 409
        assert "newer sorter software" in refused.value.detail


def test_asking_the_machine_where_a_piece_goes(monkeypatch, tmp_path):
    from server import shared_state
    from server.routers import sorting_profiles as router

    path = tmp_path / "active_sorting_profile.json"
    path.write_text(json.dumps({"program": PROGRAM, "categories": {"bricks": {"name": "Bricks", "kind": "rule"}}}))
    logger = SimpleNamespace(warn=lambda *_: None, warning=lambda *_: None, info=lambda *_: None)
    monkeypatch.setattr(shared_state, "gc_ref", SimpleNamespace(sorting_profile_path=str(path), logger=logger))
    monkeypatch.setattr(shared_state, "controller_ref", None)
    answer = router.route_piece("3003", "7")
    assert (answer["category_id"], answer["category_name"]) == ("bricks", "Bricks")
    assert router.route_piece("3068b", None)["category_id"] == "bl_37"
