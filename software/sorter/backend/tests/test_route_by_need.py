"""Set extraction: a part goes to the first set that still needs it."""
import logging
from types import SimpleNamespace

from irl.bin_layout import BinLayoutConfig, LayerConfig, applyCategories, mkLayoutFromConfig
from set_progress import SetProgressTracker
from sorting_profile import MISC_CATEGORY
from subsystems.distribution.positioning import Positioning


def _tracker(monkeypatch) -> SetProgressTracker:
    monkeypatch.setattr("set_progress.get_set_progress_state", lambda: None)
    monkeypatch.setattr("set_progress.set_set_progress_state", lambda *a, **k: None)
    inventories = {
        "set_a": {"set_num": "1-1", "name": "A", "parts": [{"part_num": "3700", "color_id": "11", "quantity": 1}]},
        "set_b": {"set_num": "2-1", "name": "B", "parts": [{"part_num": "3700", "color_id": "11", "quantity": 2}]},
        "set_c": {"set_num": "3-1", "name": "C", "parts": [{"part_num": "3700", "color_id": "11", "quantity": 1}]},
    }
    return SetProgressTracker(inventories, "hash")


def _positioning(tracker, categories):
    layout = mkLayoutFromConfig(BinLayoutConfig(layers=[LayerConfig(sections=[["medium", "medium", "medium"]])]))
    applyCategories(layout, categories)
    p = object.__new__(Positioning)
    p.gc = SimpleNamespace(set_progress_tracker=tracker)
    p.layout = layout
    p.logger = logging.getLogger("test")
    p.sorting_profile = SimpleNamespace(categoryLabel=lambda c: c)
    return p


def test_tracker_names_the_first_set_with_remaining_need(monkeypatch) -> None:
    t = _tracker(monkeypatch)
    assert t.categoryNeeding("3700", "11") == "set_a"
    t.record("3700", "11", "set_a")
    assert t.categoryNeeding("3700", "11") == "set_b"
    t.record("3700", "11", "set_b"); t.record("3700", "11", "set_b")
    assert t.categoryNeeding("3700", "11", allowed=lambda c: c != "set_c") is None
    assert t.categoryNeeding("3700", "11") == "set_c"
    assert t.categoryNeeding("9999", "11") is None
    assert t.isSetCategory("set_a") and not t.isSetCategory("printed")


def test_piece_is_rerouted_to_the_set_that_still_needs_it(monkeypatch) -> None:
    t = _tracker(monkeypatch)
    p = _positioning(t, [[[["set_a"], ["set_b"], ["set_c"]]]])
    piece = SimpleNamespace(part_id="3700", color_id="11")
    assert p._routeByNeed(piece, "set_a") == "set_a"
    t.record("3700", "11", "set_a")
    assert p._routeByNeed(piece, "set_a") == "set_b"
    t.record("3700", "11", "set_b"); t.record("3700", "11", "set_b"); t.record("3700", "11", "set_c")
    assert p._routeByNeed(piece, "set_a") == MISC_CATEGORY


def test_sets_without_a_bin_in_this_run_are_skipped(monkeypatch) -> None:
    t = _tracker(monkeypatch)
    p = _positioning(t, [[[["set_a"], [], ["set_c"]]]])
    t.record("3700", "11", "set_a")
    assert p._routeByNeed(SimpleNamespace(part_id="3700", color_id="11"), "set_a") == "set_c"


def test_secondary_categories_are_untouched(monkeypatch) -> None:
    t = _tracker(monkeypatch)
    p = _positioning(t, [[[["set_a"], ["printed"], []]]])
    assert p._routeByNeed(SimpleNamespace(part_id="3005", color_id="1"), "printed") == "printed"
