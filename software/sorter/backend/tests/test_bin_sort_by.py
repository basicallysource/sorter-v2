"""A bin is named by what machine.toml [bins] sort_by says: the category, the
part, the color or a mix. Positioning looks the bin up by that key."""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import toml_config
from defs.known_object import ClassificationStatus, KnownObject
from subsystems.distribution.chute import BinAddress
from subsystems.distribution.positioning import Positioning

from test_c4_multi_drop_doors import _Logger, _Servo, _mkShared


def _route(sort_by: list[str], *, high_value: str | None = None, part_id: str | None = "3001") -> str:
    shared = _mkShared()
    log: list[str] = []
    servos = [_Servo(log, i) for i in range(2)]
    gc = SimpleNamespace(
        logger=_Logger(),
        runtime_stats=SimpleNamespace(observeStateTransition=lambda *a, **k: None),
        disable_servos=False,
    )
    layout = SimpleNamespace(layers=[SimpleNamespace(enabled=True, max_dimension_mm=None) for _ in servos])
    chute = SimpleNamespace(
        moveToBin=lambda address: 100,
        isBinReachable=lambda address: True,
        stepper=SimpleNamespace(stopped=True),
    )
    profile = SimpleNamespace(
        getCategoryIdForPart=lambda part_id, color_id: "bricks",
        highValueCategoryId=lambda price: high_value,
    )
    positioning = Positioning(
        SimpleNamespace(servos=servos), gc, shared, chute, layout, profile, queue.Queue()  # type: ignore[arg-type]
    )
    keys: list[str] = []

    def find(key, not_in_inventory=False):
        keys.append(key)
        return BinAddress(1, 0, 0), False

    positioning._findOrAssignBinForCategory = find  # type: ignore[method-assign]
    piece = KnownObject(part_id=part_id, color_id="5")
    piece.classification_status = ClassificationStatus.classified
    shared.transport.placePieceForDistribution(piece)
    with patch.object(
        toml_config, "getBinAssignmentConfig", return_value={"sort_by": sort_by}
    ):
        positioning.step()
    assert len(keys) == 1
    # The record keeps the profile's category (or the high-value one) whatever
    # the bin is named by.
    assert piece.category_id == (high_value or "bricks")
    return keys[0]


@pytest.mark.parametrize(
    "sort_by, expected",
    [
        (["category"], "bricks"),
        (["part"], "part:3001"),
        (["color"], "color:5"),
        (["category", "color"], "category:bricks|color:5"),
        (["part", "color"], "part:3001|color:5"),
    ],
)
def test_positioning_looks_a_bin_up_by_the_sort_key(sort_by: list[str], expected: str) -> None:
    assert _route(sort_by) == expected


def test_high_value_pieces_keep_going_to_their_category_bin() -> None:
    assert _route(["part", "color"], high_value="valuable") == "valuable"


def test_settings_round_trip_and_reject_unknown(tmp_path, monkeypatch) -> None:
    path = tmp_path / "machine.toml"
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(path))
    assert toml_config.getBinAssignmentConfig()["sort_by"] == ["category"]
    merged = toml_config.setBinAssignmentConfig({"sort_by": ["color", "category"]})
    assert merged["sort_by"] == ["category", "color"]
    assert toml_config.getBinAssignmentConfig()["sort_by"] == ["category", "color"]
    with pytest.raises(ValueError):
        toml_config.setBinAssignmentConfig({"sort_by": ["size"]})
    assert toml_config.getBinAssignmentConfig()["sort_by"] == ["category", "color"]


def test_part_names_are_cached_between_layout_polls(monkeypatch) -> None:
    from server.routers import bins

    calls: list[list[str]] = []
    monkeypatch.setattr(bins, "partNames", lambda ids: calls.append(list(ids)) or {"3001": "Brick 2 x 4"})
    monkeypatch.setattr(bins, "_part_names_memo", None)
    assert bins._part_names_cached(["3001"]) == {"3001": "Brick 2 x 4"}
    assert bins._part_names_cached(["3001"]) == {"3001": "Brick 2 x 4"}
    assert len(calls) == 1
    assert bins._part_names_cached([]) == {}


def test_unreadable_sort_by_falls_back_to_category(monkeypatch) -> None:
    from subsystems.distribution import positioning

    def boom():
        raise RuntimeError("bad toml")

    monkeypatch.setattr(toml_config, "getBinAssignmentConfig", boom)
    assert positioning._binSortBy() == ("category",)


def _applied(monkeypatch, tmp_path, artifact: dict, start: list[str]) -> tuple[list[str], list[str]]:
    from server.routers import sorting_profiles

    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(tmp_path / "machine.toml"))
    toml_config.setBinAssignmentConfig({"sort_by": start})
    cleared: list[str] = []
    monkeypatch.setattr(
        sorting_profiles, "clear_bin_category_assignments", lambda scope: cleared.append(scope)
    )
    now = sorting_profiles._apply_bin_sort_by(artifact, already_cleared=False)
    assert toml_config.getBinAssignmentConfig()["sort_by"] == now
    return now, cleared


def test_a_profile_sets_the_naming_and_clears_the_bins_it_made_stale(monkeypatch, tmp_path) -> None:
    now, cleared = _applied(monkeypatch, tmp_path, {"bin_sort_by": ["color", "part"]}, ["category"])
    assert now == ["part", "color"]
    assert cleared == ["all"]


def test_a_profile_without_naming_goes_back_to_category(monkeypatch, tmp_path) -> None:
    now, cleared = _applied(monkeypatch, tmp_path, {}, ["part"])
    assert now == ["category"]
    assert cleared == ["all"]


def test_the_same_naming_keeps_the_bins(monkeypatch, tmp_path) -> None:
    now, cleared = _applied(monkeypatch, tmp_path, {"bin_sort_by": ["part"]}, ["part"])
    assert now == ["part"]
    assert cleared == []
