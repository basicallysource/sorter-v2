"""The patient link: a servo is asked again before it is called silent."""

import pytest

from hardware.feetech.link import GarbledReply, GuardMove, GuardReport, GuardState, NoReply, ServoLink
from hardware.feetech.patient_link import ATTEMPTS, PING_ATTEMPTS, PatientLink


class _Flaky(ServoLink):
    """A link whose next `lose` questions get no reply."""

    def __init__(self):
        self.lose = 0
        self.error: type[Exception] = NoReply
        self.calls: list[str] = []

    def _answer(self, name: str):
        self.calls.append(name)
        if self.lose > 0:
            self.lose -= 1
            raise self.error("No reply from servo 3.")

    def ping(self, servo_id):
        self._answer("ping")
        return 0

    def read(self, servo_id, address, count):
        self._answer("read")
        return 0, bytes(count)

    def write(self, servo_id, address, data):
        self._answer("write")

    def move(self, servo_id, move):
        self._answer("move")

    def probe(self, servo_id, probe):
        self._answer("probe")

    def state(self, servo_id):
        self.calls.append("state")
        return GuardReport(GuardState.IDLE, 0, 0, 0, 0, 0)

    def stop(self, servo_id, *, release):
        self._answer("stop")


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr("hardware.feetech.patient_link.PAUSE_S", 0)


def test_one_lost_reply_is_asked_again_and_answered():
    inner = _Flaky()
    link = PatientLink(inner)
    link.read(3, 56, 6)  # it has answered once, so it is somebody
    inner.lose = 1
    assert link.read(3, 56, 6) == (0, bytes(6))
    count = link.counts()[3]
    assert (count.asked, count.repeated, count.unanswered) == (2, 1, 0)
    assert [miss["what"] for miss in link.misses()] == ["read 56+6"]


def test_a_servo_that_never_answers_is_passed_on_after_every_attempt():
    inner = _Flaky()
    link = PatientLink(inner)
    link.read(3, 56, 6)
    inner.lose = ATTEMPTS
    inner.calls.clear()
    with pytest.raises(NoReply):
        link.read(3, 56, 6)
    assert inner.calls == ["read"] * ATTEMPTS
    assert link.counts()[3].unanswered == 1


def test_a_garbled_reply_is_asked_again_too():
    inner = _Flaky()
    link = PatientLink(inner)
    link.read(3, 56, 6)
    inner.lose, inner.error = 1, GarbledReply
    link.write(3, 40, b"\x00")
    assert link.counts()[3].repeated == 1


def test_a_move_that_got_no_reply_is_started_again():
    inner = _Flaky()
    link = PatientLink(inner)
    inner.lose = 2
    link.move(3, GuardMove(flags=0, goal=500, time_ms=100, speed=0, accel=0, stall_load=400, stall_ms=150, flat=3, arrived=6, backoff=20, timeout_ms=2000))
    assert inner.calls == ["move"] * 3


def test_an_id_nobody_has_is_pinged_twice_and_not_counted():
    inner = _Flaky()
    link = PatientLink(inner)
    inner.lose = 10
    with pytest.raises(NoReply):
        link.ping(77)
    assert inner.calls == ["ping"] * PING_ATTEMPTS
    assert link.counts() == {}
    assert link.misses() == []


def test_the_guards_record_is_read_once():
    inner = _Flaky()
    link = PatientLink(inner)
    assert link.state(3).state == GuardState.IDLE
    assert inner.calls == ["state"]
