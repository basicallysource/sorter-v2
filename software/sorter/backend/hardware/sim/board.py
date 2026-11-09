"""A whole pretend board, put together and started as one: the world, the
firmware, the board's terminal, optionally a pretend servo adapter and the
control channel."""

from __future__ import annotations

from typing import Any

from .control import Control, ControlServer
from .firmware import Firmware
from .ports import AdapterPort, BoardPort
from .scenarios import make_servo
from .world import World


class SimBoard:
    def __init__(
        self,
        *,
        scenario: dict[str, Any] | None = None,
        speed: float | None = None,
        adapter: bool = False,
        adapter_echo: bool = False,
        link: str | None = None,
        adapter_link: str | None = None,
        control_path: str | None = None,
    ):
        scenario = scenario or {}
        self.world = World(speed=speed if speed is not None else float(scenario.get("speed", 1.0)))
        chute = scenario.get("chute", {})
        for key in ("start_angle", "magnet_angle", "magnet_width", "gear_ratio", "active_level"):
            if key in chute:
                setattr(self.world.chute, key, type(getattr(self.world.chute, key))(chute[key]))
        for entry in scenario.get("board_servos", []):
            self.world.add_servo("board", make_servo(entry))
        for entry in scenario.get("adapter_servos", []):
            self.world.add_servo("adapter", make_servo(entry))
        self.firmware = Firmware(self.world)
        self.control = Control(self.world, self.firmware)
        self.board_port = BoardPort(self.firmware, link)
        self.adapter_port = (
            AdapterPort(self.world, self.world.adapter_bus, echo=adapter_echo, link=adapter_link) if adapter else None
        )
        self.control_server = ControlServer(self.control, control_path) if control_path else None

    @property
    def board_path(self) -> str:
        return self.board_port.path

    @property
    def adapter_path(self) -> str | None:
        return self.adapter_port.path if self.adapter_port is not None else None

    def start(self) -> "SimBoard":
        self.world.start()
        self.board_port.start()
        if self.adapter_port is not None:
            self.adapter_port.start()
        if self.control_server is not None:
            self.control_server.start()
        return self

    def stop(self) -> None:
        if self.control_server is not None:
            self.control_server.close()
        if self.adapter_port is not None:
            self.adapter_port.close()
        self.board_port.close()
        self.world.stop()

    def __enter__(self) -> "SimBoard":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()
