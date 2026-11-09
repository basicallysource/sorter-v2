"""Changing the pretend world while it runs: a Unix socket that takes one JSON
object a line (`{"cmd": "plug", ...}`) and answers one (`{"ok": true, ...}` or
`{"ok": false, "error": "..."}`). `ctl.py` is its command-line client.

Servos are named by their label (shown by `list`), or by their ID when only one
servo on that bus has it.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Any, Callable

from .firmware import Firmware
from .scenarios import make_servo
from .servos import Block, PretendServo
from .world import World


class ControlError(Exception):
    pass


class Control:
    def __init__(self, world: World, firmware: Firmware):
        self.world = world
        self.firmware = firmware
        self._next_label = 1
        self.commands: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list": lambda r: self.world.describe(),
            "plug": self.plug,
            "unplug": self.unplug,
            "turn": self.turn,
            "block": self.block,
            "unblock": self.unblock,
            "stops": self.stops,
            "hall": self.hall,
            "magnet": self.magnet,
            "chute-angle": self.chute_angle,
            "servo-power": self.servo_power,
            "line": self.line,
            "board": self.board,
            "motor-power": self.motor_power,
            "speed": self.speed,
        }
        with world.lock:
            for bus in (world.board_bus, world.adapter_bus):
                for servo in bus.servos:
                    self._label(servo)

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        command = self.commands.get(str(request.get("cmd", "")))
        if command is None:
            return {"ok": False, "error": f"Unknown command; known: {', '.join(sorted(self.commands))}."}
        try:
            with self.world.lock:
                return {"ok": True, "result": command(request)}
        except (ControlError, ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}

    # -- servos ---------------------------------------------------------------

    def _label(self, servo: PretendServo) -> None:
        if not servo.label:
            servo.label = f"s{self._next_label}"
            self._next_label += 1

    def _servo(self, request: dict[str, Any]) -> PretendServo:
        name = str(request.get("servo", ""))
        buses = [request["bus"]] if request.get("bus") else ["board", "adapter"]
        everything = [servo for bus in buses for servo in self.world.bus(bus).servos]
        named = [servo for servo in everything if servo.label == name]
        if named:
            return named[0]
        if name.isdigit():
            by_id = [servo for servo in everything if servo.current_id == int(name)]
            if len(by_id) == 1:
                return by_id[0]
            if len(by_id) > 1:
                labels = ", ".join(servo.label for servo in by_id)
                raise ControlError(f"Several servos have ID {name} ({labels}): name one by its label.")
        raise ControlError(f"No servo {name!r}. `list` shows them.")

    def plug(self, request: dict[str, Any]) -> dict:
        """Plug a servo in: one that was unplugged (by label), or a new one."""
        if request.get("servo"):
            servo = self._servo(request)
            servo.plugged = True
            servo.power_up()
            return servo.describe()
        entry = {key: request[key] for key in ("id", "model", "position", "lower", "upper", "speed", "label") if key in request}
        servo = make_servo(entry)
        if any(s.label == servo.label for b in ("board", "adapter") for s in self.world.bus(b).servos if servo.label):
            raise ControlError(f"A servo is already labelled {servo.label!r}.")
        self._label(servo)
        self.world.add_servo(request.get("bus") or "board", servo)
        return servo.describe()

    def unplug(self, request: dict[str, Any]) -> dict:
        servo = self._servo(request)
        servo.plugged = False
        servo.load = 0
        servo.velocity = 0.0
        return servo.describe()

    def turn(self, request: dict[str, Any]) -> dict:
        """Turn a door by hand. A servo holding with its torque on will not be turned."""
        servo = self._servo(request)
        if servo.torque and servo.plugged:
            raise ControlError(f"Servo {servo.label} has its torque on and holds where it is.")
        servo.push_to(float(request["position"]))
        return servo.describe()

    def block(self, request: dict[str, Any]) -> dict:
        """Put something in a door's way at a position, on whichever side of it that is."""
        servo = self._servo(request)
        position = float(request["position"])
        if position == servo.position:
            raise ControlError("A block goes beside the door, not where it already is.")
        servo.blocks.append(Block(position, above=position > servo.position))
        return servo.describe()

    def unblock(self, request: dict[str, Any]) -> dict:
        """Take a block out: the one at `position`, or all of them."""
        servo = self._servo(request)
        if request.get("position") is None:
            servo.blocks.clear()
        else:
            position = float(request["position"])
            servo.blocks = [block for block in servo.blocks if block.position != position]
        return servo.describe()

    def stops(self, request: dict[str, Any]) -> dict:
        servo = self._servo(request)
        servo.lower, servo.upper = float(request["lower"]), float(request["upper"])
        servo.position = max(servo.lower, min(servo.upper, servo.position))
        return servo.describe()

    def servo_power(self, request: dict[str, Any]) -> dict:
        bus = self.world.bus(request.get("bus") or "board")
        if _on(request):
            bus.restore_power()
        else:
            bus.cut_power()
        return {"powered": bus.powered}

    def line(self, request: dict[str, Any]) -> dict:
        bus = self.world.bus(request.get("bus") or "board")
        state = str(request.get("state"))
        if state not in ("stuck", "ok"):
            raise ControlError("The line is 'stuck' or 'ok'.")
        bus.stuck = state == "stuck"
        return {"stuck": bus.stuck}

    # -- the chute ------------------------------------------------------------

    def hall(self, request: dict[str, Any]) -> dict:
        state = str(request.get("state"))
        forced = {"active": True, "inactive": False, "auto": None}
        if state not in forced:
            raise ControlError("The hall sensor is held 'active' or 'inactive', or left on 'auto'.")
        self.world.chute.forced = forced[state]
        return self.world.describe()["chute"]

    def magnet(self, request: dict[str, Any]) -> dict:
        self.world.chute.magnet_angle = float(request["angle"]) % 360.0
        if request.get("width") is not None:
            self.world.chute.magnet_width = float(request["width"])
        return self.world.describe()["chute"]

    def chute_angle(self, request: dict[str, Any]) -> dict:
        """Turn the chute by hand to an angle (its stepper's count does not change)."""
        chute = self.world.chute
        chute.start_angle = (chute.start_angle + float(request["angle"]) - chute.angle) % 360.0
        return self.world.describe()["chute"]

    # -- the board ------------------------------------------------------------

    def board(self, request: dict[str, Any]) -> dict:
        state = str(request.get("state"))
        if state not in ("silent", "answer"):
            raise ControlError("Say 'silent' or 'answer'.")
        self.firmware.answering = state == "answer"
        return {"answering": self.firmware.answering}

    def motor_power(self, request: dict[str, Any]) -> dict:
        """The stepper drivers' supply: without it they hear and answer nothing."""
        on = _on(request)
        for chip in self.world.drivers:
            if on and not chip.powered:
                chip.power_on()
            chip.powered = on
        return {"powered": on}

    def speed(self, request: dict[str, Any]) -> dict:
        speed = float(request["speed"])
        if speed <= 0:
            raise ControlError("The speed is a positive factor.")
        self.world.set_speed(speed)
        return {"speed": speed}


def _on(request: dict[str, Any]) -> bool:
    state = str(request.get("state"))
    if state not in ("on", "off"):
        raise ControlError("Power is 'on' or 'off'.")
    return state == "on"


class ControlServer:
    """The Unix socket the control channel listens on."""

    def __init__(self, control: Control, path: str):
        self.control = control
        self.path = path
        socket_path = Path(path)
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.is_socket():
            socket_path.unlink()  # one left by a sim that did not exit cleanly
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(path)
        self._socket.listen(4)
        self._socket.settimeout(0.2)
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="sim-control", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _ = self._socket.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            threading.Thread(target=self._talk, args=(connection,), daemon=True).start()

    def _talk(self, connection: socket.socket) -> None:
        with connection, connection.makefile("rwb") as stream:
            for line in stream:
                try:
                    request = json.loads(line)
                    reply = self.control.dispatch(request) if isinstance(request, dict) else {"ok": False, "error": "Send a JSON object."}
                except json.JSONDecodeError as exc:
                    reply = {"ok": False, "error": f"Not JSON: {exc}"}
                stream.write(json.dumps(reply).encode() + b"\n")
                stream.flush()

    def close(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=1.0)
        self._socket.close()
        try:
            if Path(self.path).is_socket():
                os.unlink(self.path)
        except OSError:
            pass


def request(path: str, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """Send one command to a running sim and return its answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(path)
        with client.makefile("rwb") as stream:
            stream.write(json.dumps(payload).encode() + b"\n")
            stream.flush()
            return json.loads(stream.readline())
