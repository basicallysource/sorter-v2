from __future__ import annotations

import queue
from types import SimpleNamespace

from defs.known_object import KnownObject, PieceStage
from server import shared_state
from server.routers import system
from subsystems.distribution.positioning import Positioning
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass


class _RuntimeStats:
    def observeStateTransition(self, *args, **kwargs) -> None:
        pass


class _GlobalConfig:
    def __init__(self) -> None:
        self.logger = _Logger()
        self.runtime_stats = _RuntimeStats()
        self.disable_servos = False


class _Servo:
    available = True

    def __init__(self) -> None:
        self.open_calls = 0

    def isClosed(self) -> bool:
        return True

    def open(self) -> None:
        self.open_calls += 1

    @property
    def stopped(self) -> bool:
        return True


class _Transport:
    def __init__(self, piece: KnownObject) -> None:
        self.piece = piece

    def getPieceForDistributionPositioning(self) -> KnownObject:
        return self.piece


def test_sample_collection_mode_endpoint_opens_all_layer_doors() -> None:
    previous_controller = shared_state.controller_ref
    try:
        servos = [_Servo(), _Servo(), _Servo()]
        shared = SharedVariables()
        controller = SimpleNamespace(
            coordinator=SimpleNamespace(shared=shared),
            irl=SimpleNamespace(servos=servos),
            gc=_GlobalConfig(),
        )
        shared_state.setController(controller)

        result = system.set_sample_collection_mode({"enabled": True})

        assert result["ok"] is True
        assert result["enabled"] is True
        assert result["doors"]["opened"] == 3
        assert [servo.open_calls for servo in servos] == [1, 1, 1]
    finally:
        shared_state.setController(previous_controller)


def test_distribution_positioning_keeps_all_doors_open_in_sample_mode() -> None:
    piece = KnownObject(part_id="3001", color_id="1")
    shared = SharedVariables()
    shared.sample_collection_mode = True
    shared.transport = _Transport(piece)
    servos = [_Servo(), _Servo()]
    irl = SimpleNamespace(servos=servos)
    layout = SimpleNamespace(
        layers=[
            SimpleNamespace(enabled=True),
            SimpleNamespace(enabled=True),
        ]
    )

    positioning = Positioning(
        irl,  # type: ignore[arg-type]
        _GlobalConfig(),  # type: ignore[arg-type]
        shared,
        SimpleNamespace(),  # type: ignore[arg-type]
        layout,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        queue.Queue(),
    )

    next_state = positioning.step()

    assert next_state == DistributionState.READY
    assert [servo.open_calls for servo in servos] == [1, 1]
    assert piece.stage == PieceStage.distributing
    assert piece.destination_bin is None
