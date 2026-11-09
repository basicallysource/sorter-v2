"""Setting up serial servo doors, and a door at work, against the pretend v1.5
board (hardware/sim): which servo is which, where a door stops, and what a door
says when something is in its way."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

from hardware.bus import MCUBus
from hardware.feetech.board_link import BoardServoLink
from hardware.sim import control as sim_control
from hardware.sim.board import SimBoard
from hardware.sim.scenarios import BUILT_IN
from hardware.sorter_interface import SorterInterface
from hardware_settings.doors import DoorSetting
from machine_platform import door_setup
from machine_platform.door_setup import DoorSetupError, HandWatch
from machine_platform.doors import BusServoDoor

SPEED = 4.0
PTY_BAUD = 115200 if sys.platform == "darwin" else None
LOGGER = logging.getLogger("test_door_setup")


def _rig(scenario: str):
    folder = tempfile.mkdtemp(prefix="sim-", dir="/tmp")  # short: a socket path has a length limit
    sim = SimBoard(
        scenario={"board_servos": BUILT_IN[scenario]},
        speed=SPEED,
        link=os.path.join(folder, "board"),
        control_path=os.path.join(folder, "control.sock"),
    ).start()
    bus = MCUBus(sim.board_path, baudrate=PTY_BAUD)
    interface = SorterInterface(bus, 0, SimpleNamespace(logger=LOGGER))

    def ctl(**payload):
        reply = sim_control.request(os.path.join(folder, "control.sock"), payload)
        assert reply["ok"], reply
        return reply["result"]

    def close():
        bus.close()
        sim.stop()
        os.rmdir(folder)

    return SimpleNamespace(link=BoardServoLink(interface), ctl=ctl, close=close)


@pytest.fixture
def doors():
    """Four doors with servos 1 to 4, each stopping at 150 and 850."""
    rig = _rig("four-doors")
    yield rig
    rig.close()


@pytest.fixture
def new_servos():
    """Three brand-new servos plugged in at once: all answer as number 1."""
    rig = _rig("new-servos")
    yield rig
    rig.close()


def _wait(predicate, timeout_s: float = 15.0, what: str = "it"):
    give_up_at = time.monotonic() + timeout_s
    while time.monotonic() < give_up_at:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"{what} did not happen in {timeout_s} s")


def test_a_scan_tells_servos_sharing_a_number_from_one_servo(new_servos):
    found = door_setup.scanBus(new_servos.link)
    assert [(servo.servo_id, servo.state) for servo in found] == [(1, "shared")]
    # Unplug all but one, as the person is told to.
    new_servos.ctl(cmd="unplug", servo="s2")
    new_servos.ctl(cmd="unplug", servo="s3")
    found = door_setup.scanBus(new_servos.link)
    assert [(servo.servo_id, servo.state, servo.model) for servo in found] == [(1, "ok", "SC15")]


def test_a_new_servo_gets_a_number_of_its_own_so_the_next_one_is_alone(new_servos):
    new_servos.ctl(cmd="unplug", servo="s2")
    new_servos.ctl(cmd="unplug", servo="s3")
    first = door_setup.claimServo(new_servos.link, 1, layer_index=0)
    assert first.servo_id == door_setup.doorIdFor(0) == 11
    # The next new servo is plugged into the chain: it is alone on number 1.
    new_servos.ctl(cmd="plug", servo="s2")
    found = {servo.servo_id: servo.state for servo in door_setup.scanBus(new_servos.link)}
    assert found == {1: "ok", 11: "ok"}
    second = door_setup.claimServo(new_servos.link, 1, layer_index=1)
    assert second.servo_id == 12
    # A servo that already has a number of its own keeps it.
    assert door_setup.claimServo(new_servos.link, 12, layer_index=2).servo_id == 12


def test_a_door_turned_by_hand_says_which_servo_is_on_it(doors):
    watch = HandWatch(doors.link, door_setup.scanBus(doors.link))
    assert watch.moved() is None
    doors.ctl(cmd="turn", servo="s3", position=430)
    assert watch.moved() == 3
    assert watch.positions()[3] >= door_setup.HAND_MOVE_DEG
    # Two doors turned: it cannot say which was meant.
    doors.ctl(cmd="turn", servo="s1", position=600)
    assert watch.moved() is None


def test_the_slow_search_finds_both_stops_and_keeps_a_little_inside_them(doors):
    said: list[str] = []
    travel = door_setup.findTravel(doors.link, 2, said=said.append)
    assert abs(travel.low_stop - 150) <= 3 and abs(travel.high_stop - 850) <= 3
    margin = travel.low - travel.low_stop
    assert margin == travel.high_stop - travel.high > 0
    assert travel.open_ended == ()
    assert 130 < travel.degrees < 140  # 700 counts of an SC15
    assert len(said) == 2
    # It is left let go.
    assert door_setup.BusServo.identify(doors.link, 2).torque_on() is False


def test_a_door_that_hardly_turns_is_not_set_up(doors):
    doors.ctl(cmd="stops", servo="s4", lower=480, upper=520)
    with pytest.raises(DoorSetupError, match="only turns"):
        door_setup.findTravel(doors.link, 4)


def test_a_door_opens_and_shuts_and_says_when_something_is_in_its_way(doors):
    door = BusServoDoor(LOGGER, doors.link, layer_index=0, setting=DoorSetting(servo_id=1, closed=800, open=200))
    assert door.available and door.is_calibrated

    assert door.close()
    _wait(lambda: door.stopped, what="the door shutting")
    assert door.fault is None and door.isClosed()

    assert door.open()
    _wait(lambda: door.stopped, what="the door opening")
    assert door.fault is None and door.isOpen()

    # Something in its way: it stops, backs off and says so.
    doors.ctl(cmd="block", servo="s1", position=500)
    assert door.close()
    _wait(lambda: door.stopped, what="the door meeting the block")
    assert door.fault is not None and "met something" in door.fault
    assert not door.isClosed()

    # Its way cleared, the next move is clean again.
    doors.ctl(cmd="unblock", servo="s1")
    assert door.close()
    _wait(lambda: door.stopped, what="the door shutting")
    assert door.fault is None and door.isClosed()


def test_a_door_that_is_not_calibrated_is_never_moved(doors):
    door = BusServoDoor(LOGGER, doors.link, layer_index=1, setting=DoorSetting(servo_id=2))
    assert door.available and not door.is_calibrated
    assert door.close() is False and door.open() is False
    assert door_setup.BusServo.identify(doors.link, 2).torque_on() is False


def test_a_door_whose_servo_is_unplugged_is_unavailable_until_it_is_back(doors, monkeypatch):
    monkeypatch.setattr("machine_platform.doors.RETRY_AFTER_S", 0.0)
    doors.ctl(cmd="unplug", servo="s2")
    door = BusServoDoor(LOGGER, doors.link, layer_index=1, setting=DoorSetting(servo_id=2, closed=800, open=200))
    assert not door.available
    assert door.close() is False
    assert "does not answer" in door.feedback()["error"]
    doors.ctl(cmd="plug", servo="s2")
    assert door.available
    assert door.close()
