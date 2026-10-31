"""Piece size against the layers' max-dimension limits during bin selection.

The tests marked "today" pin behaviour that must survive the change: a piece
bigger than the layer of the bin it was routed to still goes straight through
to the misc bottom bin. The rest cover the size check that now runs before a
free bin is claimed: a piece bigger than every usable layer claims nothing, and
a new key only takes a free bin in a layer that fits the piece.
"""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from defs.known_object import KnownObject, PieceStage
from irl.bin_layout import Bin, BinSection, BinSize, DistributionLayout, Layer
from runtime_stats import RuntimeStatsCollector
from server import shared_state
from sorting_profile import MISC_CATEGORY
from subsystems.distribution.chute import BinAddress, Chute
from subsystems.distribution.positioning import Positioning
from subsystems.shared_variables import SharedVariables


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    warning = warn = debug = error = info


def _servo(available: bool = True) -> SimpleNamespace:
    servo = SimpleNamespace(available=available, stopped=True)
    servo.isClosed = lambda: True
    servo.isOpen = lambda: False
    servo.open = MagicMock()
    servo.close = MagicMock()
    return servo


def _layer(
    limit: float | None,
    bins: list[Bin] | None = None,
) -> Layer:
    layer = Layer(sections=[BinSection(bins=bins or [Bin(size=BinSize.MEDIUM)])])
    layer.enabled = True
    layer.max_pieces_per_bin = None
    layer.max_dimension_mm = limit
    return layer


def _bin(category_ids: list[str] | None = None, not_in_inventory: bool = False) -> Bin:
    return Bin(
        size=BinSize.MEDIUM,
        category_ids=list(category_ids or []),
        not_in_inventory=not_in_inventory,
    )


@pytest.fixture(autouse=True)
def _isolated_machine_state(monkeypatch):
    monkeypatch.setattr(shared_state, "hardware_error", None)
    monkeypatch.setattr(shared_state, "command_queue", queue.Queue())
    shared_state.distribution_no_bin_passthrough_approvals.clear()
    with (
        patch("subsystems.distribution.positioning._incidentHandlingOff", return_value=True),
        patch("subsystems.distribution.positioning._persistBinCategories"),
        patch("subsystems.distribution.positioning._allowMultiCategoryBins", return_value=False),
        patch("bin_contents.get_current_bin_piece_counts", return_value={}),
    ):
        yield


def _positioning(layers: list[Layer], piece: KnownObject, servos=None) -> Positioning:
    servos = servos or [_servo() for _ in layers]
    gc = SimpleNamespace(
        logger=_Logger(),
        disable_servos=False,
        runtime_stats=RuntimeStatsCollector(),
        run_recorder=SimpleNamespace(markPaused=lambda: None, markRunning=lambda: None),
    )
    shared = SharedVariables(gc=gc, bus=None)
    shared.transport = SimpleNamespace(getPieceForDistributionPositioning=lambda: piece)
    chute = MagicMock(spec=Chute)
    chute.isBinReachable = MagicMock(return_value=True)
    chute.moveToBin = MagicMock(return_value=250)
    chute.stepper = SimpleNamespace(stopped=True)
    profile = SimpleNamespace(
        getCategoryIdForPart=lambda part_id, color_id: "cat_a",
        highValueCategoryId=lambda price: None,
    )
    return Positioning(
        irl=SimpleNamespace(servos=servos),
        gc=gc,
        shared=shared,
        chute=chute,
        layout=DistributionLayout(layers=layers),
        sorting_profile=profile,
        event_queue=queue.Queue(),
    )


def _piece(size_mm: float | None, not_in_inventory: bool | None = None) -> KnownObject:
    piece = KnownObject(part_id="3001", color_id="5")
    piece.max_dimension_mm = size_mm
    piece.not_in_inventory = not_in_inventory
    return piece


def _passed_through(piece: KnownObject) -> bool:
    return piece.destination_bin is None and piece.stage == PieceStage.distributing


# ------------------------------------------------------------------- today


def test_today_a_piece_that_fits_goes_to_its_bin() -> None:
    layers = [_layer(50, [_bin(["cat_a"])]), _layer(80)]
    piece = _piece(40)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (0, 0, 0)
    assert not piece.too_big_for_layer


def test_today_a_piece_too_big_for_the_layer_of_its_existing_bin_passes_through() -> None:
    layers = [_layer(50, [_bin(["cat_a"])]), _layer(80)]
    piece = _piece(60)
    positioning = _positioning(layers, piece)

    positioning.step()

    assert _passed_through(piece)
    assert piece.too_big_for_layer is True
    assert piece.intended_layer_index == 0
    assert piece.category_id == MISC_CATEGORY
    assert [servo.open.call_count for servo in positioning.irl.servos] == [1, 1]


def test_today_training_mode_bin_is_still_checked_against_its_layer() -> None:
    layers = [_layer(50, [_bin()]), _layer(80)]
    piece = _piece(60)
    positioning = _positioning(layers, piece)
    positioning._trainingBinAddress = lambda: BinAddress(0, 0, 0)

    positioning.step()

    assert _passed_through(piece)
    assert piece.too_big_for_layer is True
    assert piece.intended_layer_index == 0


def test_today_layers_without_a_limit_take_any_size() -> None:
    layers = [_layer(None, [_bin(["cat_a"])])]
    piece = _piece(500)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (0, 0, 0)
    assert not piece.too_big_for_layer


def test_today_a_piece_of_unknown_size_is_not_held_against_any_layer() -> None:
    layers = [_layer(50, [_bin(["cat_a"])])]
    piece = _piece(None)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (0, 0, 0)
    assert not piece.too_big_for_layer


# --------------------------------------------------------------- the change


def test_a_piece_bigger_than_every_layer_claims_no_bin() -> None:
    free_small, free_large = _bin(), _bin()
    layers = [_layer(50, [free_small]), _layer(80, [free_large])]
    piece = _piece(90)
    positioning = _positioning(layers, piece)

    next_state = positioning.step()

    assert next_state is not None and next_state.name == "READY"
    assert _passed_through(piece)
    assert piece.too_big_for_layer is True
    assert piece.intended_layer_index is None
    assert piece.category_id == MISC_CATEGORY
    assert free_small.category_ids == [] and free_large.category_ids == []
    assert [servo.open.call_count for servo in positioning.irl.servos] == [1, 1]
    assert shared_state.hardware_error is None


def test_a_piece_bigger_than_every_layer_passes_through_even_when_its_bin_exists() -> None:
    layers = [_layer(50, [_bin(["cat_a"])]), _layer(80)]
    piece = _piece(90)

    _positioning(layers, piece).step()

    assert _passed_through(piece)
    assert piece.too_big_for_layer is True


def test_one_layer_without_a_limit_means_nothing_is_too_big() -> None:
    layers = [_layer(50), _layer(None)]
    piece = _piece(500)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (1, 0, 0)
    assert not piece.too_big_for_layer


def test_only_usable_layers_count_for_the_size_check() -> None:
    layers = [_layer(50), _layer(80)]
    servos = [_servo(), _servo(available=False)]
    piece = _piece(60)

    _positioning(layers, piece, servos).step()

    assert _passed_through(piece)
    assert piece.too_big_for_layer is True
    assert layers[0].sections[0].bins[0].category_ids == []


def test_the_not_in_inventory_pool_is_checked_against_its_own_layers() -> None:
    layers = [
        _layer(50, [_bin(not_in_inventory=True)]),
        _layer(80, [_bin()]),
    ]
    piece = _piece(60, not_in_inventory=True)

    _positioning(layers, piece).step()

    assert _passed_through(piece)
    assert piece.too_big_for_layer is True
    assert layers[0].sections[0].bins[0].category_ids == []


def test_a_new_key_takes_a_free_bin_only_in_a_layer_that_fits() -> None:
    layers = [_layer(50), _layer(80)]
    piece = _piece(60)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (1, 0, 0)
    assert layers[0].sections[0].bins[0].category_ids == []
    assert layers[1].sections[0].bins[0].category_ids == ["cat_a"]


def test_a_new_key_takes_the_smallest_layer_that_fits() -> None:
    layers = [_layer(80), _layer(50)]
    piece = _piece(40)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (1, 0, 0)


def test_a_new_key_of_unknown_size_keeps_the_first_free_bin() -> None:
    layers = [_layer(80), _layer(50)]
    piece = _piece(None)

    _positioning(layers, piece).step()

    assert piece.destination_bin == (0, 0, 0)


def test_with_no_free_bin_that_fits_the_small_free_bin_stays_unclaimed() -> None:
    layers = [_layer(50), _layer(80, [_bin(["cat_b"])])]
    piece = _piece(60)
    positioning = _positioning(layers, piece)

    positioning.step()

    assert _passed_through(piece)
    assert layers[0].sections[0].bins[0].category_ids == []
