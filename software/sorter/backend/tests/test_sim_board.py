"""The backend's own board code (MCUBus, SorterInterface, BoardServoLink)
against the pretend v1.5 board (hardware/sim) over a pseudo-terminal.

The pretend world runs four times faster than real time; what is checked is
measured on its own clock, so a busy machine does not change the outcome."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

from hardware.bus import MCUBus
from hardware.feetech import registers
from hardware.feetech.board_link import BoardServoLink
from hardware.feetech.link import FLAG_SC, GarbledReply, GuardMove, GuardProbe, GuardState, LinkDown, NoReply
from hardware.sim import control as sim_control
from hardware.sim.board import SimBoard
from hardware.sim.scenarios import BUILT_IN
from hardware.sim.steppers import Tmc2209
from hardware.sorter_interface import SorterInterface

SPEED = 4.0
# A macOS pseudo-terminal takes only the standard rates, so name one there (as
# SORTER_HEADER_UART=path:115200 does). Elsewhere the backend's own rates are used.
PTY_BAUD = 115200 if sys.platform == "darwin" else None


@pytest.fixture
def rig():
    """A board with four doors (IDs 1 to 4, stops at 150 and 850), the backend's
    interface to it, and a control socket."""
    folder = tempfile.mkdtemp(prefix="sim-", dir="/tmp")  # short: a socket path has a length limit
    sim = SimBoard(
        scenario={"board_servos": BUILT_IN["four-doors"]},
        speed=SPEED,
        link=os.path.join(folder, "board"),
        control_path=os.path.join(folder, "control.sock"),
    ).start()
    bus = MCUBus(sim.board_path, baudrate=PTY_BAUD)
    gc = SimpleNamespace(logger=logging.getLogger("test_sim_board"))
    interface = SorterInterface(bus, 0, gc)
    yield SimpleNamespace(sim=sim, bus=bus, interface=interface, link=BoardServoLink(interface), folder=folder)
    bus.close()
    sim.stop()  # takes its symlink and socket with it
    os.rmdir(folder)


def ctl(rig, **payload):
    reply = sim_control.request(os.path.join(rig.folder, "control.sock"), payload)
    assert reply["ok"], reply
    return reply["result"]


def wait(predicate, timeout_s: float = 15.0, what: str = "it"):
    give_up_at = time.monotonic() + timeout_s
    while time.monotonic() < give_up_at:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"{what} did not happen in {timeout_s} s")


def wait_for_end(link: BoardServoLink, servo_id: int):
    reports = []
    wait(lambda: not reports.append(link.state(servo_id)) and not reports[-1].busy, what=f"servo {servo_id} ending")
    return reports[-1]


def test_detect_and_version(rig):
    info = rig.interface.board_info
    assert info["device_name"] == "DISTRIBUTION MB"
    assert info["stepper_names"] == [
        "chute_stepper",
        "c_channel_1_rotor",
        "c_channel_3_rotor",
        "carousel",
        "c_channel_2_rotor",
    ]
    assert (info["digital_input_count"], info["digital_output_count"], info["servo_count"]) == (1, 2, 0)
    assert len(rig.interface.steppers) == 5 and len(rig.interface.servos) == 0
    observability = rig.interface.get_observability_info()
    assert observability["hw"] == "basically_v1_5"
    assert observability["servo_bus"] is True and observability["servo_guard"] is True
    assert rig.interface.get_version()["variant"] == "distribution-v1-5"
    assert rig.interface.ping(b"hello") == b"hello"


def test_a_board_found_through_a_symlinked_header_uart(rig, monkeypatch):
    link = os.path.join(rig.folder, "board")
    assert os.path.realpath(link) == os.path.realpath(rig.sim.board_path)
    monkeypatch.setenv("SORTER_HEADER_UART", f"{link}:{PTY_BAUD}" if PTY_BAUD else link)
    assert link in MCUBus.enumerate_buses()
    rig.bus.close()  # the port is opened exclusively: one owner at a time
    bus = MCUBus(link)
    try:
        assert bus.scan_devices(0, 2) == [0]
    finally:
        bus.close()


def test_a_stepper_move_takes_time_and_ends_where_asked(rig):
    stepper = rig.interface.steppers[1]
    stepper.set_speed_limits(16, 4000)
    stepper.set_acceleration(20000)
    world = rig.sim.world
    began_us = world.now_us
    assert stepper.move_steps(4000)
    assert not stepper.stopped
    midway = []
    wait(lambda: 0 < stepper.position < 4000 and not midway.append(stepper.position), what="a reading mid-move")
    wait(lambda: stepper.stopped, what="the move ending")
    took_s = (world.now_us - began_us) / 1e6
    assert stepper.position == 4000
    expected_s = stepper.estimateMoveStepsMs(4000, max_speed=4000) / 1000
    assert expected_s * 0.9 <= took_s <= expected_s * 1.2 + 0.1, (took_s, expected_s)


def test_homing_the_chute_on_its_hall_sensor(rig):
    chute = rig.interface.steppers[0]
    hall = rig.interface.digital_inputs[0]
    assert hall.value is False, "away from the magnet, the sensor reads low"
    chute.home(2000, hall, home_pin_active_high=True)
    wait(lambda: chute.stopped, what="homing")
    assert chute.position == 0
    assert hall.value is True, "the hall sensor reads high where it stopped, over the magnet"
    angle = rig.sim.world.chute.angle
    assert abs(angle - (360 - 9)) < 0.5, f"stopped at the edge of the magnet window, not {angle}"


def test_driver_registers_read_back_and_count_writes(rig):
    stepper = rig.interface.steppers[3]
    before = stepper.read_driver_register(Tmc2209.IFCNT)
    stepper.write_driver_register(Tmc2209.SGTHRS, 77)
    stepper.set_microsteps(16)
    stepper.set_current(16, 8, 4)
    assert (stepper.read_driver_register(Tmc2209.IFCNT) - before) % 256 == 3
    assert stepper.read_driver_register(Tmc2209.SGTHRS) == 77
    assert (stepper.read_driver_register(Tmc2209.CHOPCONF) >> 24) & 0xF == 4  # 1/16
    assert stepper.read_driver_register(Tmc2209.IHOLD_IRUN) == (4 << 16) | (16 << 8) | 8
    assert stepper.read_driver_register(Tmc2209.IOIN) >> 24 == 0x21


def test_the_backends_stepper_setup_passes(rig):
    try:
        from hardware_settings.motors import motorNamed
        from hardware_settings.steppers import readStepperSettings
        from irl.config import _configureStepper
    except ImportError as exc:
        pytest.skip(f"the backend's setup code needs its full environment: {exc}")
    gc = SimpleNamespace(logger=logging.getLogger("test_sim_board"), no_power_development_mode=False)
    chute = motorNamed("chute")
    speeds = SimpleNamespace(default_steps_per_second=3000, acceleration_microsteps_per_second_sq=20000)
    _configureStepper(gc, rig.interface.steppers[0], chute, speeds, readStepperSettings(chute, {}))


def test_servo_ping_and_read(rig):
    link = rig.link
    assert link.ping(1) == 0
    status, model = link.read(1, registers.MODEL, 2)
    assert status == 0 and registers.model_for(model).name == "SC15"
    status, block = link.read(2, registers.PRESENT, registers.PRESENT_BYTES)
    present = registers.decode_present(registers.SC, block, status)
    assert present.position == 500 and present.volts == pytest.approx(6.1) and not present.moving
    with pytest.raises(NoReply):
        link.ping(9)


def test_a_guarded_move_stalls_against_something_in_the_way(rig):
    link = rig.link
    ctl(rig, cmd="block", servo="2", position=600)
    link.move(2, GuardMove(flags=FLAG_SC, goal=800))
    report = wait_for_end(link, 2)
    assert report.state == GuardState.STALLED
    assert abs(report.mark - 600) <= 3, "it says where it stalled"
    assert report.peak_load >= 400
    wait(lambda: abs(registers.SC.position(link.read(2, registers.PRESENT, 2)[1]) - 570) <= 3, what="backing off")


def test_a_probe_finds_a_stop(rig):
    link = rig.link
    link.probe(3, GuardProbe(flags=FLAG_SC, direction=-1, limit=0))
    report = wait_for_end(link, 3)
    assert report.state == GuardState.CONTACT
    assert abs(report.mark - 150) <= 3, "the lower hard stop"


def test_two_servos_with_one_id_garble(rig):
    ctl(rig, cmd="plug", id=4, position=700, lower=150, upper=850)
    with pytest.raises(GarbledReply):
        rig.link.ping(4)
    with pytest.raises(GarbledReply):
        rig.link.move(4, GuardMove(flags=FLAG_SC, goal=600))


def test_an_id_change_with_the_lock(rig):
    link = rig.link
    lock = registers.SC.lock_register
    link.write(1, lock, b"\x00")
    link.write(1, registers.ID, b"\x09")
    assert link.ping(9) == 0, "the new ID answers at once"
    with pytest.raises(NoReply):
        link.ping(1)
    link.write(9, lock, b"\x01")
    assert link.read(9, lock, 1)[1] == b"\x01"
    # Written while locked: it takes effect, and is gone after a power cut.
    link.write(9, registers.ID, b"\x0a")
    assert link.ping(10) == 0
    ctl(rig, cmd="servo-power", state="off")
    with pytest.raises(NoReply):
        link.ping(10)
    ctl(rig, cmd="servo-power", state="on")
    assert link.ping(9) == 0, "the ID saved while unlocked survives"
    with pytest.raises(NoReply):
        link.ping(10)


def test_a_silent_board_is_a_link_down_and_comes_back(rig):
    ctl(rig, cmd="board", state="silent")
    with pytest.raises(LinkDown):
        rig.link.ping(1)
    ctl(rig, cmd="board", state="answer")
    assert rig.link.ping(1) == 0


def test_a_door_turned_by_hand_stays_where_it_is_put(rig):
    ctl(rig, cmd="turn", servo="4", position=300)
    _, block = rig.link.read(4, registers.PRESENT, 2)
    assert registers.SC.position(block) == 300
    rig.link.move(4, GuardMove(flags=FLAG_SC, goal=400))
    reply = sim_control.request(os.path.join(rig.folder, "control.sock"), {"cmd": "turn", "servo": "4", "position": 200})
    assert not reply["ok"], "a servo holding with its torque on is not turned"
