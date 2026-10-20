"""Automatic StallGuard tuning: the speed floor follows the operating speed, and
the trigger follows what the motor's load reads in normal running."""

import logging

import pytest

import hive_defaults
import stallguard_tuner as tuner
from hardware.sorter_interface import StepperMove
from hardware_settings.motors import motorNamed
from hardware_settings.steppers import TMC_REG_SGTHRS, TMC_REG_TCOOLTHRS, readStepperSettings

CHUTE = motorNamed("chute")
SPEED = 2000
# What the chute's driver reads at 2000 µsteps/s, 1/8 microstepping.
CRUISE_TSTEP = 194


class Gc:
    logger = logging.getLogger("test_stallguard_tuner")


class Stepper:
    """The driver as the tuner sees it: TSTEP and SG_RESULT to read, the
    threshold registers to write, and a stall latch it must never clear."""

    def __init__(self) -> None:
        self.last_move = None
        self.stalled = False
        self.stallguard_enabled = True
        self.stallguard_sgthrs = 10
        self.stallguard_tcoolthrs = 201
        self.tstep = CRUISE_TSTEP
        self.sg = 200
        self.reads = 0
        self.written: list[tuple[int, int]] = []
        self.latch_cleared = 0
        self.armed: list[bool] = []

    def read_driver_register(self, register: int) -> int:
        self.reads += 1
        return {tuner.REG_TSTEP: self.tstep, tuner.REG_SG_RESULT: self.sg}[register]

    def write_driver_register(self, register: int, value: int) -> None:
        self.written.append((register, value))

    def clear_stall(self) -> None:
        self.latch_cleared += 1

    def enable_stall_detection(self, enable: bool) -> None:
        self.armed.append(enable)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    toml = tmp_path / "machine.toml"
    toml.write_text(
        "[stepper_current_overrides.chute_stepper]\nirun = 24\nihold = 4\nihold_delay = 8\n\n"
        "[stepper_stallguard.chute_stepper]\nsgthrs = 10\ntcoolthrs = 201\nenabled = true\nauto = true\n"
    )
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(toml))
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    hive_defaults.invalidate()
    yield
    hive_defaults.invalidate()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0


def runMoves(t, tuning, stepper, clock, count, readings=None, *, speed=SPEED, stalls=False):
    """`count` one-second moves at `speed`, each sampled every 50 ms. Readings
    cycle through `readings` (normal running between 190 and 259 by default)."""
    readings = readings or [190 + (i * 37) % 70 for i in range(70)]
    n = 0
    for _ in range(count):
        stepper.last_move = StepperMove(clock.now, 1000, speed, 1.0)
        start = clock.now
        for k in range(21):
            clock.now = start + k * tuner.SAMPLE_INTERVAL_S
            stepper.sg = readings[n % len(readings)]
            n += 1
            t.stepMotor(tuning, stepper, SPEED, clock.now)
        stepper.stalled = stalls
        clock.now = start + 1.0 + tuner.STALL_SEEN_S + 0.1
        t.stepMotor(tuning, stepper, SPEED, clock.now)
        stepper.stalled = False
        clock.now += 0.2


def test_the_speed_floor_sits_a_quarter_above_the_cruise():
    assert tuner.floorFor(2000, 8) == 235
    assert tuner.floorFor(1500, 8) == 313
    # It judges everything faster than 80 % of the operating speed.
    assert tuner.speedAt(tuner.floorFor(2000, 8), 8) == 1596


def test_it_learns_the_trigger_from_normal_running(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    runMoves(t, tuning, stepper, clock, 1)
    # While it learns: a trigger no normal running comes near, the floor set for the speed.
    assert (readStepperSettings(CHUTE).sgthrs, readStepperSettings(CHUTE).tcoolthrs) == (6, 235)
    assert tuning.status()["state"] == "learning"

    runMoves(t, tuning, stepper, clock, 40)
    status = tuning.status()
    assert status["state"] == "tuned"
    assert status["normal_low"] == 190
    # sqrt(4 x 190 / 2) = 19.5: trips at 20, ten times over a stall, under a tenth of normal.
    assert (status["sgthrs"], status["tcoolthrs"]) == (10, 235)
    assert readStepperSettings(CHUTE).sgthrs == 10
    assert (TMC_REG_SGTHRS, 10) in stepper.written and (TMC_REG_TCOOLTHRS, 235) in stepper.written
    # It never clears a stall latch or re-arms detection behind the stall monitor.
    assert stepper.latch_cleared == 0 and stepper.armed == []
    assert [c["sgthrs"] for c in status["changes"]] == [[6, 10], [10, 6]]


def test_readings_under_the_speed_floor_are_left_out(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    stepper.tstep = 400  # the bottom of a ramp, slower than the floor
    runMoves(t, tuning, stepper, clock, 40, readings=[3])
    assert tuning.status()["readings"] == 0


def test_a_move_that_stalls_is_left_out(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    runMoves(t, tuning, stepper, clock, 3, readings=[2], stalls=True)
    assert tuning.status()["readings"] == 0
    runMoves(t, tuning, stepper, clock, 1)
    assert tuning.status()["readings"] == 21


def test_it_notices_the_motor_working_harder(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    runMoves(t, tuning, stepper, clock, 40)
    assert not tuning.status()["working_harder"]
    runMoves(t, tuning, stepper, clock, 20, readings=[100 + i for i in range(30)])
    status = tuning.status()
    assert status["working_harder"]
    assert (status["normal_low"], status["baseline_low"]) == (100, 190)
    # Normal running reads lower now, so the trigger comes down with it.
    assert status["sgthrs"] == 7


def test_a_new_speed_starts_learning_over(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    runMoves(t, tuning, stepper, clock, 40)
    t.stepMotor(tuning, stepper, 1500, clock.now)
    clock.now += 2.0
    t.stepMotor(tuning, stepper, 1500, clock.now)
    status = tuning.status()
    assert status["state"] == "learning" and status["baseline_low"] is None
    assert (status["sgthrs"], status["tcoolthrs"]) == (6, 313)


def test_what_it_learned_lasts_through_a_restart(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    runMoves(t, t.tuning("chute"), stepper, clock, 40)
    stepper.written.clear()

    again = tuner.StallGuardTuner(Gc())
    tuning = again.tuning("chute")
    again.stepMotor(tuning, stepper, SPEED, clock.now)
    status = tuning.status()
    assert status["state"] == "tuned" and status["normal_low"] == 190
    assert stepper.written == []


def test_it_leaves_a_motor_alone_while_a_recording_holds_it(machine):
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    stepper.last_move = StepperMove(clock.now, 1000, SPEED, 1.0)
    t.stepMotor(tuning, stepper, SPEED, clock.now, busy=True)
    assert tuning.status()["state"] == "waiting"
    assert stepper.reads == 0 and stepper.written == []


def test_it_does_nothing_with_tuning_off(machine):
    from server.routers.steppers import save_stepper_settings

    save_stepper_settings(CHUTE, {"stallguard_auto": False})
    t, stepper, clock = tuner.StallGuardTuner(Gc()), Stepper(), Clock()
    tuning = t.tuning("chute")
    runMoves(t, tuning, stepper, clock, 40)
    assert tuning.status()["state"] == "off"
    assert stepper.reads == 0 and stepper.written == []


def test_a_threshold_set_by_hand_turns_tuning_off(machine):
    from server.routers.stallguard import StallGuardConfigBody, set_stallguard_config

    unchanged = set_stallguard_config("chute", StallGuardConfigBody(sgthrs=10, enabled=True))
    assert unchanged.auto
    by_hand = set_stallguard_config("chute", StallGuardConfigBody(sgthrs=20))
    assert not by_hand.auto and by_hand.sgthrs == 20
    assert not readStepperSettings(CHUTE).stallguard_auto


def test_tuning_is_off_until_turned_on(tmp_path, monkeypatch):
    toml = tmp_path / "machine.toml"
    toml.write_text("[stepper_stallguard.chute_stepper]\nsgthrs = 10\ntcoolthrs = 201\nenabled = true\n")
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(toml))
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    hive_defaults.invalidate()
    assert not readStepperSettings(CHUTE).stallguard_auto
    assert not readStepperSettings(CHUTE, {}).stallguard_auto
    hive_defaults.invalidate()
