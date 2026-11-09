"""Setting up the layer doors' serial servos: which servo turns which door, and
the positions each door turns between (machine_platform/door_setup.py says how).

Everything here needs the hardware started, since the servos are reached
through the control board. Nothing here moves a door that is not calibrated,
except the search for its stops, which a person asks for and which never pushes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hardware.feetech import registers
from hardware.feetech.link import GuardState, ServoLink, ServoLinkError
from hardware.feetech.servo import BusServo
from hardware_settings.chute import readChuteSettings
from hardware_settings.doors import DoorSetting, readDoorSettings, saveDoorSetting, servoBackend
from irl.bin_layout import getBinLayout
from machine_platform import door_setup
from machine_platform.door_setup import DoorSetupError
from machine_platform.doors import releaseAll
from machine_platform.servo_controller import BoardBusServoController
from server import shared_state
from server.routers.steppers import _ensure_not_homing

router = APIRouter()

NOT_STARTED = "Start the hardware first: the door servos are reached through the control board."


class DoorServoPayload(BaseModel):
    # The servo's ID on the bus, or left out for a layer with no servo.
    servo_id: Optional[int] = None


class DoorEndPayload(BaseModel):
    end: str  # "closed" or "open"


class DoorNudgePayload(BaseModel):
    end: str
    degrees: float


class DoorMovePayload(BaseModel):
    to: str  # "closed" or "open"


class DoorAnswerPayload(BaseModel):
    # Whether the door, as it stands now, is shut across the chute.
    closed_now: bool


class ServoIdPayload(BaseModel):
    new_id: int


@dataclass
class _Search:
    """One search for a door's stops, and the question it ends in."""

    layer_index: int
    servo_id: int
    state: str = "running"  # running, asking, done, failed
    message: str = "Starting"
    travel: Optional[door_setup.Travel] = None
    cancel: threading.Event = field(default_factory=threading.Event)


_lock = threading.Lock()
_last_scan: list[Any] = []
_watch: Optional[door_setup.HandWatch] = None
_search: Optional[_Search] = None


# --- what is there ---


def _controller() -> BoardBusServoController | None:
    irl = shared_state.getActiveIRL()
    controller = getattr(irl, "servo_controller", None) if irl is not None else None
    return controller if isinstance(controller, BoardBusServoController) else None


def _link() -> ServoLink:
    """The live servo bus, or the reason there is none, as an HTTP error."""
    _ensure_not_homing("set up the doors")
    controller = _controller()
    if controller is None:
        raise HTTPException(status_code=409, detail=NOT_STARTED)
    if controller.firmware_too_old or controller.link is None:
        raise HTTPException(
            status_code=409,
            detail="The control board's firmware is too old to move serial servos safely. Update it first.",
        )
    return controller.link


def _layerCount() -> int:
    irl = shared_state.getActiveIRL()
    layout = getattr(irl, "distribution_layout", None) if irl is not None else None
    if layout is not None:
        return len(layout.layers)
    return len(getBinLayout().layers)


def _fixedLayer(layer_count: int) -> int | None:
    return layer_count - 1 if readChuteSettings().variant.fixed_bottom_door and layer_count > 0 else None


def _setting(layer_index: int) -> DoorSetting:
    settings = readDoorSettings()
    return settings[layer_index] if layer_index < len(settings) else DoorSetting()


def _checkLayer(layer_index: int) -> None:
    count = _layerCount()
    if not 0 <= layer_index < count:
        raise HTTPException(status_code=404, detail="There is no such layer.")
    if layer_index == _fixedLayer(count):
        raise HTTPException(status_code=409, detail="This layer's door has no servo: it is always shut.")


def _servoOf(layer_index: int) -> int:
    servo_id = _setting(layer_index).servo_id
    if servo_id is None:
        raise HTTPException(status_code=409, detail="No servo is set up for this layer's door yet.")
    return servo_id


def _refreshDoor(layer_index: int) -> None:
    """Make the running hardware's door for this layer the one now saved."""
    irl = shared_state.getActiveIRL()
    controller = _controller()
    if irl is None or controller is None or layer_index >= len(irl.servos):
        return
    irl.servos[layer_index] = controller.doorFor(layer_index, _setting(layer_index))


def _searchPayload() -> Dict[str, Any] | None:
    search = _search
    if search is None:
        return None
    payload: Dict[str, Any] = {
        "layer_index": search.layer_index,
        "servo_id": search.servo_id,
        "state": search.state,
        "message": search.message,
    }
    if search.travel is not None:
        payload["travel_degrees"] = search.travel.degrees
        payload["open_ended"] = list(search.travel.open_ended)
    return payload


def _state() -> Dict[str, Any]:
    controller = _controller()
    layer_count = _layerCount()
    fixed_layer = _fixedLayer(layer_count)
    irl = shared_state.getActiveIRL()
    live_doors = list(getattr(irl, "servos", []) or []) if controller is not None else []
    layers = []
    owners: Dict[int, int] = {}
    for index in range(layer_count):
        setting = _setting(index)
        if setting.servo_id is not None:
            owners[setting.servo_id] = index
        layer: Dict[str, Any] = {
            "layer_index": index,
            "kind": "fixed" if index == fixed_layer else "servo",
            "servo_id": None if index == fixed_layer else setting.servo_id,
            "calibrated": index == fixed_layer or setting.calibrated,
            "closed_position": setting.closed,
            "open_position": setting.open,
            "available": None,
            "error": None,
            "is_open": None,
            "position": None,
            "model": None,
        }
        if index < len(live_doors) and hasattr(live_doors[index], "feedback"):
            try:
                live = live_doors[index].feedback()
                for key in ("available", "error", "is_open", "position", "model", "volts", "temperature_c"):
                    if key in live:
                        layer[key] = live[key]
            except Exception as exc:
                layer["error"] = str(exc)
        layers.append(layer)
    reason = None
    if controller is None:
        reason = NOT_STARTED
    elif controller.firmware_too_old:
        reason = "The control board's firmware is too old to move serial servos safely. Update it first."
    servos = [
        {
            "servo_id": found.servo_id,
            "state": found.state,
            "model": found.model,
            "position": found.position,
            "volts": found.volts,
            "temperature_c": found.temperature_c,
            "factory_id": found.servo_id == registers.FACTORY_ID,
            "layer_index": owners.get(found.servo_id),
        }
        for found in _last_scan
    ]
    return {
        "backend": servoBackend() or ("bus" if controller is not None else None),
        "ready": reason is None,
        "reason": reason,
        "layer_count": layer_count,
        "fixed_layer": fixed_layer,
        "layers": layers,
        "servos": servos,
        "shared_ids": [servo["servo_id"] for servo in servos if servo["state"] == "shared"],
        "watching": _watch is not None,
        "search": _searchPayload(),
    }


def _ok(message: str | None = None) -> Dict[str, Any]:
    return {"ok": True, "message": message, "doors": _state()}


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/api/doors")
def get_doors() -> Dict[str, Any]:
    return _state()


# --- which servo is which ---


@router.post("/api/doors/scan")
def scan_doors() -> Dict[str, Any]:
    """Ask the bus what is on it."""
    global _last_scan
    link = _link()
    try:
        with _lock:
            _last_scan = door_setup.scanBus(link)
    except ServoLinkError as exc:
        raise _fail(exc)
    found = [servo for servo in _last_scan if servo.state == "ok"]
    shared = [servo.servo_id for servo in _last_scan if servo.state == "shared"]
    if shared:
        message = (
            f"Several servos answer as number {shared[0]} at once, so none of them can be told apart. "
            "New servos all come as number 1: unplug all but one of them, then scan again."
        )
    elif not _last_scan:
        message = "No servo answers. Check the servo cable and that the servos have power."
    else:
        message = f"Found {len(found)} servo{'s' if len(found) != 1 else ''}."
    return _ok(message)


@router.post("/api/doors/servos/{servo_id}/id")
def set_servo_id(servo_id: int, payload: ServoIdPayload) -> Dict[str, Any]:
    """Give a servo another number, kept through power off."""
    link = _link()
    try:
        BusServo.identify(link, servo_id).set_id(payload.new_id)
    except (ServoLinkError, ValueError) as exc:
        raise _fail(exc)
    scan_doors()
    return _ok(f"Servo {servo_id} is now servo {payload.new_id}.")


@router.post("/api/doors/watch/start")
def start_hand_watch() -> Dict[str, Any]:
    """Let every servo go and watch for the one a person turns by hand."""
    global _watch
    link = _link()
    if not _last_scan:
        scan_doors()
    try:
        with _lock:
            _watch = door_setup.HandWatch(link, _last_scan)
    except DoorSetupError as exc:
        raise _fail(exc)
    return _ok("Every servo is let go. Turn one door by hand.")


@router.get("/api/doors/watch")
def read_hand_watch() -> Dict[str, Any]:
    watch = _watch
    if watch is None:
        raise HTTPException(status_code=409, detail="Nothing is being watched. Start the watch first.")
    _link()
    return {"ok": True, "turned_degrees": watch.positions(), "moved": watch.moved()}


@router.post("/api/doors/watch/stop")
def stop_hand_watch() -> Dict[str, Any]:
    global _watch
    _watch = None
    return _ok()


@router.post("/api/doors/layers/{layer_index}/servo")
def set_layer_servo(layer_index: int, payload: DoorServoPayload) -> Dict[str, Any]:
    """Say which servo turns this layer's door, or that none does. A new servo
    (still number 1) is given a number of its own."""
    global _watch
    _checkLayer(layer_index)
    link = _link()
    servo_id = payload.servo_id
    message = "This layer's door has no servo now."
    if servo_id is not None:
        try:
            servo_id = door_setup.claimServo(link, servo_id, layer_index).servo_id
        except DoorSetupError as exc:
            raise _fail(exc)
        message = f"Servo {servo_id} turns layer {layer_index + 1}'s door."
    try:
        saveDoorSetting(layer_index, servo_id=servo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _watch = None
    for index in range(_layerCount()):
        if index != _fixedLayer(_layerCount()):
            _refreshDoor(index)
    scan_doors()
    return _ok(message)


# --- where a door stops ---


def _runSearch(search: _Search, link: ServoLink) -> None:
    def said(message: str) -> None:
        search.message = message

    try:
        travel = door_setup.findTravel(link, search.servo_id, said=said, cancelled=search.cancel.is_set)
        search.travel = travel
        # Show one end and ask which it is: the servo cannot know.
        said("Turning the door to one end")
        report = door_setup.moveGuarded(link, search.servo_id, travel.high)
        if report.state != GuardState.ARRIVED:
            raise DoorSetupError("The door did not reach the end it had just found. Check that nothing is in its way.")
        search.state = "asking"
        search.message = f"Is layer {search.layer_index + 1}'s door shut across the chute now?"
    except DoorSetupError as exc:
        search.state = "failed"
        search.message = str(exc)
    except Exception as exc:  # a thread must not die silently
        search.state = "failed"
        search.message = f"The search stopped: {exc}"


@router.post("/api/doors/layers/{layer_index}/find-stops")
def find_door_stops(layer_index: int) -> Dict[str, Any]:
    """Start the slow search for where this door stops at each end. It ends by
    asking which end is which (`/answer`)."""
    global _search, _watch
    _checkLayer(layer_index)
    link = _link()
    servo_id = _servoOf(layer_index)
    with _lock:
        if _search is not None and _search.state == "running":
            raise HTTPException(status_code=409, detail="Another door is being measured. Wait for it, or stop it.")
        _watch = None
        _search = _Search(layer_index=layer_index, servo_id=servo_id)
        threading.Thread(target=_runSearch, args=(_search, link), daemon=True, name="door-find-stops").start()
    return _ok("The door will turn slowly to each of its stops. Keep fingers clear.")


@router.post("/api/doors/find-stops/stop")
def stop_finding_stops() -> Dict[str, Any]:
    search = _search
    if search is not None and search.state == "running":
        search.cancel.set()
    return _ok()


@router.post("/api/doors/layers/{layer_index}/answer")
def answer_which_end(layer_index: int, payload: DoorAnswerPayload) -> Dict[str, Any]:
    """Say whether the door, standing at the end the search left it at, is shut.
    That settles which position is closed and which is open, and saves both."""
    global _search
    link = _link()
    search = _search
    if search is None or search.layer_index != layer_index or search.state != "asking" or search.travel is None:
        raise HTTPException(status_code=409, detail="This door is not waiting for an answer.")
    travel = search.travel
    closed, opened = (travel.high, travel.low) if payload.closed_now else (travel.low, travel.high)
    try:
        saveDoorSetting(layer_index, closed=closed, open=opened)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    search.state = "done"
    search.message = "Saved"
    _refreshDoor(layer_index)
    try:
        # Leave it open, out of the way.
        door_setup.moveGuarded(link, search.servo_id, opened)
    except DoorSetupError as exc:
        return _ok(f"Saved, but the door did not open afterwards: {exc}")
    return _ok(f"Layer {layer_index + 1}'s door is set up.")


@router.post("/api/doors/layers/{layer_index}/mark")
def mark_door_by_hand(layer_index: int, payload: DoorEndPayload) -> Dict[str, Any]:
    """Keep where the door is right now as its closed or open position. For
    setting a door by hand: let it go, hold it in place, mark it."""
    _checkLayer(layer_index)
    link = _link()
    if payload.end not in ("closed", "open"):
        raise HTTPException(status_code=400, detail="A door's end is closed or open.")
    try:
        position = door_setup.readPosition(link, _servoOf(layer_index))
        saveDoorSetting(layer_index, **{payload.end: position})
    except (DoorSetupError, ValueError) as exc:
        raise _fail(exc)
    _refreshDoor(layer_index)
    return _ok(f"Layer {layer_index + 1}'s door is {payload.end} where it stands now.")


@router.post("/api/doors/layers/{layer_index}/nudge")
def nudge_door_end(layer_index: int, payload: DoorNudgePayload) -> Dict[str, Any]:
    """Move one of a door's two positions by a few degrees and show it there."""
    _checkLayer(layer_index)
    link = _link()
    if payload.end not in ("closed", "open"):
        raise HTTPException(status_code=400, detail="A door's end is closed or open.")
    if abs(payload.degrees) > 10:
        raise HTTPException(status_code=400, detail="A nudge is ten degrees at most.")
    setting = _setting(layer_index)
    current = setting.closed if payload.end == "closed" else setting.open
    if setting.servo_id is None or current is None:
        raise HTTPException(status_code=409, detail="This door has no such position yet. Find its stops first.")
    try:
        position = door_setup.nudged(link, setting.servo_id, current, payload.degrees)
        report = door_setup.moveGuarded(link, setting.servo_id, position)
    except DoorSetupError as exc:
        raise _fail(exc)
    if report.state != GuardState.ARRIVED:
        raise HTTPException(
            status_code=409,
            detail="The door met something before it got there, so the position was not changed.",
        )
    saveDoorSetting(layer_index, **{payload.end: position})
    _refreshDoor(layer_index)
    return _ok()


@router.post("/api/doors/layers/{layer_index}/move")
def move_door(layer_index: int, payload: DoorMovePayload) -> Dict[str, Any]:
    """Open or close a door that is set up, to see it work."""
    _checkLayer(layer_index)
    link = _link()
    if payload.to not in ("closed", "open"):
        raise HTTPException(status_code=400, detail="A door is moved to closed or open.")
    setting = _setting(layer_index)
    if not setting.calibrated:
        raise HTTPException(status_code=409, detail="This door is not set up yet, so it is not moved.")
    goal = setting.closed if payload.to == "closed" else setting.open
    assert setting.servo_id is not None and goal is not None
    try:
        report = door_setup.moveGuarded(link, setting.servo_id, goal)
    except DoorSetupError as exc:
        raise _fail(exc)
    if report.state == GuardState.STALLED:
        raise HTTPException(status_code=409, detail="The door met something on the way and backed off.")
    if report.state != GuardState.ARRIVED:
        raise HTTPException(status_code=409, detail="The door did not get there.")
    return _ok()


@router.post("/api/doors/release")
def release_doors() -> Dict[str, Any]:
    """Let every door servo go."""
    link = _link()
    try:
        releaseAll(link)
    except ServoLinkError as exc:
        raise _fail(exc)
    return _ok("Every door servo is let go.")
