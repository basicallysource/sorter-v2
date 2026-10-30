"""The chute's position check: it finds the home switch from above, the way
homing does, and reads how far the chute had drifted from the step count where
the switch triggers."""

from types import SimpleNamespace

import pytest

import machine_toml
from hardware_settings.chute import readChuteSettings, saveChuteSettings
from subsystems.distribution import position_check
from subsystems.distribution.chute import Chute

MICROSTEPS = 8
# 15° of chute above the switch, in motor microsteps (gear ratio 4.8).
CHECK_FROM_STEPS = round(position_check.CHECK_FROM_DEG * 4.8 / 360 * 200 * MICROSTEPS)


class Logger:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def info(self, message, *a, **k) -> None:
        self.lines.append(("info", message))

    def warning(self, message, *a, **k) -> None:
        self.lines.append(("warning", message))

    def error(self, message, *a, **k) -> None:
        self.lines.append(("error", message))


class Stepper:
    """A chute stepper whose homing move counts down from where the check
    starts and triggers the switch at `trigger_at`, zeroing the count as the
    firmware does. `trigger_at=None` never finds the switch."""

    def __init__(self, pin, trigger_at: int | None = 0, per_read: int = 8) -> None:
        self._pin = pin
        self._trigger_at = trigger_at
        self._per_read = per_read
        self._position = 0
        self._homing = False
        self.homes = 0
        self.halted = False

    def degrees_for_microsteps(self, steps: float) -> float:
        return steps / (200 * MICROSTEPS) * 360.0

    def microsteps_for_degrees(self, degrees: float) -> int:
        return round(degrees / 360.0 * 200 * MICROSTEPS)

    @property
    def position_degrees(self) -> float:
        return self.degrees_for_microsteps(self._position)

    def estimateMoveDegreesMs(self, degrees: float, max_speed: int = 5000) -> int:
        return 500

    def set_speed_limits(self, low: int, high: int) -> None:
        pass

    def move_degrees_blocking(self, degrees: float, timeout_ms: int = 5000) -> bool:
        self._position += self.microsteps_for_degrees(degrees)
        return True

    def home(self, speed, pin, home_pin_active_high=True) -> None:
        self.homes += 1
        self._homing = True
        if self._trigger_at is not None and self._position <= self._trigger_at:
            self._trigger()

    def _trigger(self) -> None:
        self._homing = False
        self._position = 0
        self._pin.value = True

    @property
    def stopped(self) -> bool:
        return not self._homing

    @property
    def position(self) -> int:
        if self._homing:
            self._position -= self._per_read
            if self._trigger_at is not None and self._position <= self._trigger_at:
                reading = self._position
                self._trigger()
                return reading
        return self._position

    def move_at_speed(self, speed, force=False) -> bool:
        self._homing = False
        self.halted = True
        return True


def mkChute(trigger_at: int | None = 0, every: int = 3) -> Chute:
    pin = SimpleNamespace(value=False)
    gc = SimpleNamespace(logger=Logger(), disable_chute=False)
    chute = Chute(
        gc, stepper=Stepper(pin, trigger_at), home_pin=pin, layout=SimpleNamespace(layers=[]),
        position_check=True, position_check_every=every,
    )
    chute._homed = True
    return chute


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(tmp_path / "machine.toml"))
    monkeypatch.setattr(position_check, "START_GRACE_S", 0.0)


def test_a_chute_on_its_count_finds_the_switch_where_homing_did():
    chute = mkChute(trigger_at=0)
    check = chute.checkPosition()
    assert check.ok and not check.beyond_range
    # The last reading before the switch: within one reading's travel of 0.
    assert 0 <= check.drift_steps <= 8
    assert not check.lost_steps
    assert chute.homed and chute.pieces_since_check == 0


def test_lost_steps_show_as_drift_and_the_chute_is_back_on_its_position():
    # The switch comes 64 µsteps (3°) early: steps lost moving away from it.
    chute = mkChute(trigger_at=64)
    check = chute.checkPosition()
    assert check.ok and check.lost_steps
    assert 64 <= check.drift_steps < 72
    assert check.drift_deg == pytest.approx(check.drift_steps / 1600 * 360 / 4.8, abs=0.001)
    assert chute.homed and chute.stepper.position == 0
    assert any(level == "warning" and "lost steps" in line for level, line in chute.logger.lines)


def test_a_chute_past_the_switch_is_off_by_more_than_it_can_measure():
    chute = mkChute(trigger_at=CHECK_FROM_STEPS + 100)
    check = chute.checkPosition()
    assert check.ok and check.beyond_range
    assert check.drift_deg == position_check.CHECK_FROM_DEG


def test_no_switch_stops_the_chute_and_leaves_it_unhomed(monkeypatch):
    monkeypatch.setattr(position_check, "CHECK_TIMEOUT_S", 0.05)
    chute = mkChute(trigger_at=None)
    check = chute.checkPosition()
    assert not check.ok and "no switch" in check.error
    assert chute.stepper.halted and not chute.homed


def test_it_falls_due_every_so_many_pieces():
    chute = mkChute(every=3)
    chute.moveToAngle = lambda target, max_speed=None: 100
    chute.getAngleForBin = lambda address: 90.0
    for _ in range(2):
        chute.moveToBin(SimpleNamespace(layer_index=0, section_index=0, bin_index=0))
    assert not chute.positionCheckDue()
    chute.moveToBin(SimpleNamespace(layer_index=0, section_index=0, bin_index=0))
    assert chute.positionCheckDue()
    chute.checkPosition()
    assert not chute.positionCheckDue()
    chute.setPositionCheck(False, 3)
    chute.pieces_since_check = 10
    assert not chute.positionCheckDue()


def test_what_the_checks_found_adds_up():
    mkChute(trigger_at=0).checkPosition()
    mkChute(trigger_at=64).checkPosition()
    summary = position_check.summary()
    assert (summary["checks"], summary["lost_steps"], summary["failed"]) == (2, 1, 0)
    assert summary["largest_deg"] >= 3.0
    assert summary["recent"][0]["drift_steps"] >= 64


def test_it_is_off_until_turned_on_and_saves_how_often():
    settings = readChuteSettings({})
    assert (settings.position_check, settings.position_check_every) == (False, 50)
    saveChuteSettings({"position_check": True, "position_check_every": 20})
    saved = readChuteSettings(machine_toml.read())
    assert (saved.position_check, saved.position_check_every) == (True, 20)
    with pytest.raises(ValueError):
        saveChuteSettings({"position_check_every": 0})
