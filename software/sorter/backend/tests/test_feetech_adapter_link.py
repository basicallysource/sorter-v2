"""AdapterServoLink against the pretend USB servo adapter (hardware/sim): raw
Feetech packets over a pseudo-terminal, with the guard running in the link.

Each test runs against an adapter that does not hear itself, one that echoes
what it sends (taken for an echo by default), and one the link is told echoes."""

from __future__ import annotations

import sys
import time

import pytest

from hardware.feetech import registers
from hardware.feetech.adapter_link import AdapterServoLink
from hardware.feetech.link import (
    FLAG_RELEASE_ON_ARRIVAL,
    FLAG_SC,
    GarbledReply,
    GuardMove,
    GuardProbe,
    GuardState,
    LinkDown,
    NoReply,
)
from hardware.sim.board import SimBoard

# A macOS pseudo-terminal takes only the standard rates.
BAUDRATE = 115200 if sys.platform == "darwin" else 1_000_000

SERVOS = [
    {"id": 1, "position": 300},
    {"id": 2, "position": 300, "upper": 520},
    {"id": 3, "position": 400, "upper": 655},
    {"id": 7, "position": 500},
    {"id": 7, "position": 520},
]


@pytest.fixture(params=[(False, None), (True, None), (True, True)], ids=["quiet", "echo-auto", "echo-told"])
def rig(request):
    adapter_echo, link_echo = request.param
    sim = SimBoard(scenario={"adapter_servos": SERVOS}, adapter=True, adapter_echo=adapter_echo).start()
    link = AdapterServoLink(sim.adapter_path, baudrate=BAUDRATE, echo=link_echo)
    yield sim, link
    link.close()
    sim.stop()


def wait_for_end(link: AdapterServoLink, servo_id: int, timeout_s: float = 15.0):
    give_up_at = time.monotonic() + timeout_s
    while time.monotonic() < give_up_at:
        report = link.state(servo_id)
        if not report.busy:
            return report
        time.sleep(0.02)
    raise AssertionError(f"servo {servo_id} still busy after {timeout_s} s: {link.state(servo_id)}")


def test_ping_and_read(rig):
    _, link = rig
    assert link.ping(1) == 0
    status, model = link.read(1, registers.MODEL, 2)
    assert status == 0 and registers.model_for(model).name == "SC15"
    status, block = link.read(1, registers.PRESENT, registers.PRESENT_BYTES)
    present = registers.decode_present(registers.SC, block, status)
    assert present.position == 300
    assert present.volts == pytest.approx(6.1)


def test_a_guarded_move_arrives(rig):
    _, link = rig
    link.move(1, GuardMove(flags=FLAG_SC | FLAG_RELEASE_ON_ARRIVAL, goal=640))
    report = wait_for_end(link, 1)
    assert report.state == GuardState.ARRIVED
    assert abs(report.position - 640) <= 8
    assert link.read(1, registers.TORQUE, 1)[1] == b"\x00", "let go on arrival"


def test_a_move_into_a_stop_stalls_and_backs_off(rig):
    _, link = rig
    link.move(2, GuardMove(flags=FLAG_SC, goal=700))
    report = wait_for_end(link, 2)
    assert report.state == GuardState.STALLED
    assert abs(report.mark - 520) <= 3, "stall marked at the stop"
    time.sleep(0.5)
    _, block = link.read(2, registers.PRESENT, 2)
    assert abs(registers.SC.position(block) - 490) <= 3, "backed off 30 counts"


def test_a_probe_finds_a_stop(rig):
    _, link = rig
    link.probe(3, GuardProbe(flags=FLAG_SC, direction=1, limit=1023))
    report = wait_for_end(link, 3)
    assert report.state == GuardState.CONTACT
    assert abs(report.mark - 655) <= 3


def test_a_write_ends_the_watch(rig):
    _, link = rig
    link.move(1, GuardMove(flags=FLAG_SC, goal=900))
    assert link.state(1).busy
    link.write(1, registers.TORQUE, b"\x00")
    assert link.state(1).state == GuardState.IDLE


def test_silence_for_an_absent_id(rig):
    _, link = rig
    with pytest.raises(NoReply):
        link.ping(9)
    with pytest.raises(NoReply):
        link.move(9, GuardMove(flags=FLAG_SC, goal=500))


def test_two_servos_with_one_id_garble(rig):
    _, link = rig
    with pytest.raises(GarbledReply):
        link.ping(7)
    with pytest.raises(GarbledReply):
        link.read(7, registers.PRESENT, registers.PRESENT_BYTES)


def test_unplugged_and_unpowered_servos_are_silent(rig):
    sim, link = rig
    assert sim.control.dispatch({"cmd": "unplug", "servo": "1", "bus": "adapter"})["ok"]
    with pytest.raises(NoReply):
        link.ping(1)
    assert sim.control.dispatch({"cmd": "servo-power", "state": "off", "bus": "adapter"})["ok"]
    with pytest.raises(NoReply):
        link.ping(2)


def test_a_closed_link_is_down(rig):
    _, link = rig
    link.close()
    with pytest.raises(LinkDown):
        link.ping(1)
