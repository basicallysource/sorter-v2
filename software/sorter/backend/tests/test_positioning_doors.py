"""Where a piece goes, and what the doors do, on a chute nothing falls out of:
the fixed bottom door, the discard bin, a door in the way, and a door that
meets something."""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from defs.known_object import KnownObject
from hardware.door import Door
from irl.bin_layout import Bin, BinSection, BinSize, DistributionLayout, Layer
from machine_platform.doors import FixedDoor, MissingDoor
from runtime_stats import RuntimeStatsCollector
from sorting_profile import MISC_CATEGORY, SortingProfile
from subsystems.distribution.chute import BinAddress
from subsystems.distribution.chute_variants import CABLE_CAGE, SLIP_RING
from subsystems.distribution.positioning import (
    DISTRIBUTION_DOOR_BLOCKED_INCIDENT_KIND,
    DISTRIBUTION_NO_DISCARD_BIN_INCIDENT_KIND,
    Positioning,
)
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables


class _Logger:
    def info(self, *a, **k) -> None: ...
    def warning(self, *a, **k) -> None: ...
    warn = warning

    def error(self, *a, **k) -> None: ...
    def debug(self, *a, **k) -> None: ...


class _Profile(SortingProfile):
    def __init__(self, category_id: str) -> None:
        self._category_id = category_id

    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        return self._category_id

    def highValueCategoryId(self, _price) -> None:
        return None


class _ServoDoor(Door):
    """A door that records what it was told, and can be made to meet something."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.blocked = False
        self._fault: str | None = None

    @property
    def available(self) -> bool:
        return True

    @property
    def is_calibrated(self) -> bool:
        return True

    @property
    def stopped(self) -> bool:
        return True

    @property
    def fault(self) -> str | None:
        return self._fault

    def open(self) -> bool:
        self.log.append("open")
        self._fault = None
        return True

    def close(self) -> bool:
        self.log.append("close")
        self._fault = "The door met something while closing and backed off." if self.blocked else None
        return True

    def isOpen(self) -> bool:
        return bool(self.log) and self.log[-1] == "open"

    def isClosed(self) -> bool:
        return bool(self.log) and self.log[-1] == "close"


def _layout(categories: list[list[str]]) -> DistributionLayout:
    """One section a layer, the top layer first, with a bin for each category list."""
    layers = []
    for layer_categories in categories:
        bins = [Bin(size=BinSize.MEDIUM, category_ids=[c] if c else []) for c in layer_categories]
        layer = Layer(sections=[BinSection(bins=bins)])
        layer.enabled = True
        layer.max_pieces_per_bin = None
        layers.append(layer)
    return DistributionLayout(layers=layers)


class _Chute:
    def __init__(self, variant, discard_bin: BinAddress | None = None) -> None:
        self.variant = variant
        self.discard_bin = discard_bin
        self.moves: list[BinAddress] = []
        self.stepper = SimpleNamespace(stopped=True)
        self.checking = False

    def isDiscardBin(self, address: BinAddress) -> bool:
        return self.discard_bin is not None and self.discard_bin == address

    def isBinReachable(self, _address: BinAddress) -> bool:
        return True

    def positionCheckDue(self) -> bool:
        return False

    def moveToBin(self, address: BinAddress) -> int:
        self.moves.append(address)
        return 100


@pytest.fixture
def machine():
    """Builds a Positioning for a set of doors, a layout and a chute."""
    stats = RuntimeStatsCollector()
    gc = SimpleNamespace(
        logger=_Logger(),
        disable_servos=False,
        runtime_stats=stats,
        run_recorder=SimpleNamespace(markPaused=lambda: None, markRunning=lambda: None),
    )

    def build(doors, layout, chute, category="cat_a"):
        piece = KnownObject(part_id="3001", color_id="5")
        shared = SharedVariables(gc=gc, bus=None)
        shared.transport = SimpleNamespace(getPieceForDistributionPositioning=lambda: piece)
        positioning = Positioning(
            irl=SimpleNamespace(servos=doors),
            gc=gc,
            shared=shared,
            chute=chute,
            layout=layout,
            sorting_profile=_Profile(category),
            event_queue=queue.Queue(),
        )
        return positioning, piece

    with patch("subsystems.distribution.positioning._incidentHandlingOff", return_value=False), patch(
        "bin_contents.get_current_bin_piece_counts", return_value={}
    ):
        yield SimpleNamespace(build=build, stats=stats)


def _run(positioning) -> DistributionState | None:
    """Step until the state machine moves on, as its owner would."""
    for _ in range(10):
        result = positioning.step()
        if result is not None:
            return result
    return None


def test_a_piece_for_the_bottom_layer_opens_every_door_above_it(machine):
    top, middle = _ServoDoor(), _ServoDoor()
    doors = [top, middle, FixedDoor(2)]
    chute = _Chute(SLIP_RING, discard_bin=BinAddress(2, 0, 1))
    positioning, piece = machine.build(doors, _layout([["x"], ["y"], ["cat_a", ""]]), chute)
    assert _run(positioning) == DistributionState.READY
    assert piece.destination_bin == (2, 0, 0)
    assert top.log == ["open"] and middle.log == ["open"]
    assert chute.moves == [BinAddress(2, 0, 0)]


def test_a_piece_for_a_middle_layer_shuts_its_door_and_never_asks_the_fixed_one_to_open(machine):
    top, middle = _ServoDoor(), _ServoDoor()
    fixed = FixedDoor(2)
    chute = _Chute(SLIP_RING, discard_bin=BinAddress(2, 0, 0))
    positioning, piece = machine.build([top, middle, fixed], _layout([["x"], ["cat_a"], [""]]), chute)
    assert _run(positioning) == DistributionState.READY
    assert piece.destination_bin == (1, 0, 0)
    assert top.log == ["open"] and middle.log == ["close"]


def test_a_piece_no_bin_takes_goes_to_the_discard_bin_on_a_chute_nothing_falls_out_of(machine):
    top = _ServoDoor()
    chute = _Chute(SLIP_RING, discard_bin=BinAddress(1, 0, 1))
    positioning, piece = machine.build(
        [top, FixedDoor(1)], _layout([["x"], ["y", ""]]), chute, category=MISC_CATEGORY
    )
    assert _run(positioning) == DistributionState.READY
    assert piece.destination_bin == (1, 0, 1)
    assert piece.category_id == MISC_CATEGORY
    assert top.log == ["open"]
    assert chute.moves == [BinAddress(1, 0, 1)]


def test_the_discard_bin_is_never_given_a_category(machine):
    chute = _Chute(SLIP_RING, discard_bin=BinAddress(1, 0, 0))
    # The only empty bin is the discard bin: a new category must not take it.
    layout = _layout([["x"], [""]])
    positioning, piece = machine.build([_ServoDoor(), FixedDoor(1)], layout, chute, category="cat_new")
    with patch("subsystems.distribution.positioning._incidentHandlingOff", return_value=True):
        assert _run(positioning) == DistributionState.READY
    assert piece.destination_bin == (1, 0, 0)  # as a discard, not as cat_new's bin
    assert layout.layers[1].sections[0].bins[0].category_ids == []


def test_with_no_discard_bin_a_piece_no_bin_takes_waits_and_an_incident_says_so(machine):
    chute = _Chute(SLIP_RING, discard_bin=None)
    positioning, piece = machine.build(
        [_ServoDoor(), FixedDoor(1)], _layout([["x"], ["y"]]), chute, category=MISC_CATEGORY
    )
    assert _run(positioning) == DistributionState.IDLE
    assert piece.destination_bin is None
    assert machine.stats.activeIncident()["kind"] == DISTRIBUTION_NO_DISCARD_BIN_INCIDENT_KIND
    assert chute.moves == []


def test_on_a_chute_with_a_tray_under_it_the_piece_still_falls_through(machine):
    top, bottom = _ServoDoor(), _ServoDoor()
    chute = _Chute(CABLE_CAGE)
    positioning, piece = machine.build([top, bottom], _layout([["x"], ["y"]]), chute, category=MISC_CATEGORY)
    assert _run(positioning) == DistributionState.READY
    assert piece.destination_bin is None
    assert top.log == ["open"] and bottom.log == ["open"]
    assert chute.moves == []


def test_a_layer_under_a_door_that_cannot_be_opened_is_not_used(machine):
    # The top layer's servo is not set up: its door may be shut, so nothing
    # below it can be reached, and the piece is not let go.
    missing = MissingDoor(0, "No servo is set up for this layer's door.")
    middle = _ServoDoor()
    chute = _Chute(SLIP_RING, discard_bin=BinAddress(2, 0, 0))
    positioning, piece = machine.build([missing, middle, FixedDoor(2)], _layout([["x"], ["cat_a"], [""]]), chute)
    assert _run(positioning) == DistributionState.IDLE
    assert middle.log == []
    assert chute.moves == []


def test_a_door_that_meets_something_holds_the_piece_and_calls_the_operator(machine):
    top, middle = _ServoDoor(), _ServoDoor()
    middle.blocked = True
    chute = _Chute(SLIP_RING, discard_bin=BinAddress(2, 0, 0))
    positioning, piece = machine.build([top, middle, FixedDoor(2)], _layout([["x"], ["cat_a"], [""]]), chute)
    assert _run(positioning) == DistributionState.IDLE
    incident = machine.stats.activeIncident()
    assert incident["kind"] == DISTRIBUTION_DOOR_BLOCKED_INCIDENT_KIND
    assert incident["layer_number"] == 2
    # Nothing moves the door again until the operator has cleared it.
    middle.log.clear()
    assert positioning.step() == DistributionState.IDLE
    assert middle.log == []
    machine.stats.clearActiveIncident(kind=DISTRIBUTION_DOOR_BLOCKED_INCIDENT_KIND)
    middle.blocked = False
    assert _run(positioning) == DistributionState.READY
    assert middle.log == ["close"]
