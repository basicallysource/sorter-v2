"""Each stepper motor's TMC2209 driver settings and its direction.

FIELDS declares every setting once: the machine.toml table and key it is saved
under, its range and its default. readStepperSettings is the only reader and
saveStepperSettings the only writer. applyStepperSettings puts settings on a
driver the same way at start-up (irl/config.py, every setting) and when a
route changes some, so what a driver runs on is what was saved.

A setting that is not saved takes its default: the primary Hive's where it
holds one (hive_defaults, `steppers.*` for every motor and `steppers.<motor>`),
else the code's, the more specific winning, and last the feeder drive's for the
feeder's motors (defaultSettings).

A StealthChop driver tunes itself to the current it runs at, so a new current
starts that tuning over (resetDriverTuning).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping

import machine_toml
from hardware.sorter_interface import DISABLE_STALLGUARD

from .feeder import feederDrive
from .motors import SPARE_SOCKETS, Motor, motorSockets

CURRENTS = "stepper_current_overrides"
DRIVER = "stepper_driver"
STALLGUARD = "stepper_stallguard"
DIRECTIONS = "stepper_direction_inverts"

TMC_REG_GCONF = 0x00
TMC_REG_GSTAT = 0x01
TMC_REG_TCOOLTHRS = 0x14
TMC_REG_SGTHRS = 0x40
TMC_REG_COOLCONF = 0x42
TMC_REG_PWMCONF = 0x70
# PDN_DISABLE | MSTEP_REG_SELECT | MULTISTEP_FILT: the driver takes its settings,
# microstepping included, over UART. EN_SPREADCYCLE cleared is StealthChop.
GCONF_UART = 0x1C0
GCONF_EN_SPREADCYCLE = 1 << 2
# SEMIN=5, SEUP=1, SEMAX=2, SEDN=0. COOLCONF=0 switches CoolStep off.
COOLCONF_COOLSTEP = 5 | (1 << 5) | (2 << 8)
# TCOOLTHRS is the speed floor of both StallGuard's stall output and CoolStep;
# this value means "at every speed".
TCOOLTHRS_EVERY_SPEED = 0xFFFFF
# PWMCONF.pwm_autoscale: the driver sets its StealthChop PWM amplitude itself,
# from the coil current it measures.
PWMCONF_AUTOSCALE = 1 << 18
# GSTAT's flags (reset, drv_err, uv_cp). Each clears when written as 1.
GSTAT_FLAGS = 0x7
# How long a move under way gets to end before a live change of current resets
# the driver's tuning anyway.
TUNING_RESET_WAIT_S = 2.0
MICROSTEP_CHOICES = (1, 2, 4, 8, 16, 32, 64, 128, 256)


@dataclass(frozen=True)
class Field:
    name: str
    table: str
    key: str
    default: Any
    valid: Callable[[Any], bool]
    expects: str


def _intIn(low: int, high: int) -> Callable[[Any], bool]:
    return lambda value: type(value) is int and low <= value <= high


def _isBool(value: Any) -> bool:
    return isinstance(value, bool)


FIELDS: dict[str, Field] = {
    field.name: field
    for field in (
        Field("irun", CURRENTS, "irun", 16, _intIn(0, 31), "an integer from 0 to 31"),
        Field("ihold", CURRENTS, "ihold", 4, _intIn(0, 31), "an integer from 0 to 31"),
        Field("ihold_delay", CURRENTS, "ihold_delay", 8, _intIn(0, 15), "an integer from 0 to 15"),
        Field(
            "microsteps", DRIVER, "microsteps", 8,
            lambda value: type(value) is int and value in MICROSTEP_CHOICES,
            "one of 1, 2, 4, 8, 16, 32, 64, 128 or 256",
        ),
        Field("stealthchop", DRIVER, "stealthchop", True, _isBool, "true or false"),
        Field("coolstep", DRIVER, "coolstep", False, _isBool, "true or false"),
        Field("stallguard", STALLGUARD, "enabled", False, _isBool, "true or false"),
        # The StallGuard tuner (stallguard_tuner.py) keeps sgthrs and tcoolthrs.
        Field("stallguard_auto", STALLGUARD, "auto", False, _isBool, "true or false"),
        # Jam detection on the tuner's dial: the trigger as a percentage of
        # normal running at the speeds it checks; 0 is the tuner's stall-only trigger.
        Field("stallguard_sensitivity", STALLGUARD, "sensitivity", 0, _intIn(0, 90), "an integer from 0 to 90"),
        Field("sgthrs", STALLGUARD, "sgthrs", 50, _intIn(0, 255), "an integer from 0 to 255"),
        Field(
            "tcoolthrs", STALLGUARD, "tcoolthrs", 150,
            _intIn(0, TCOOLTHRS_EVERY_SPEED), f"an integer from 0 to {TCOOLTHRS_EVERY_SPEED}",
        ),
        # [stepper_direction_inverts] is one flat table keyed by motor name.
        Field("inverted", DIRECTIONS, "", False, _isBool, "true or false"),
    )
}

# Built-in values that differ by motor; the rest are FIELDS' defaults. The
# C-channel rotors run cool through their gears (a direct-drive feeder raises
# their current: feeder.DRIVES), and the chute and the carousel come with
# StallGuard tuned on the first machines.
MOTOR_DEFAULTS: dict[str, dict[str, Any]] = {
    "c_channel_1": {"irun": 4, "ihold": 1},
    "c_channel_2": {"irun": 4, "ihold": 1},
    "c_channel_3": {"irun": 4, "ihold": 1},
    "carousel": {"irun": 8, "ihold": 1, "stallguard": True, "sgthrs": 148, "tcoolthrs": 150},
    "chute": {"stallguard": True, "sgthrs": 55, "tcoolthrs": 150},
}

# What a motor's entry in these tables has always meant for a key it leaves
# out, whatever the motor's built-in default, so existing files read the same.
ENTRY_DEFAULTS: dict[str, dict[str, Any]] = {
    CURRENTS: {"irun": 16, "ihold": 4, "ihold_delay": 8},
    STALLGUARD: {"stallguard": True, "tcoolthrs": TCOOLTHRS_EVERY_SPEED},
}


@dataclass(frozen=True)
class StepperSettings:
    irun: int
    ihold: int
    ihold_delay: int
    microsteps: int
    stealthchop: bool
    coolstep: bool
    stallguard: bool
    stallguard_auto: bool
    stallguard_sensitivity: int
    sgthrs: int
    tcoolthrs: int
    inverted: bool
    # The settings machine.toml holds; the others are built-in defaults.
    saved: frozenset[str] = frozenset()

    def describe(self) -> str:
        # TCOOLTHRS is the value written, which a TMC2209 cannot read back.
        return (
            f"IRUN={self.irun} IHOLD={self.ihold} IHOLD_DELAY={self.ihold_delay}, "
            f"{self.microsteps} microsteps, StealthChop {_onOff(self.stealthchop)}, "
            f"CoolStep {_onOff(self.coolstep)}, StallGuard {_onOff(self.stallguard)} "
            f"(SGTHRS={self.sgthrs} TCOOLTHRS={tcoolthrsRegister(self)}"
            f"{', tuned automatically' if self.stallguard_auto else ''}), "
            f"direction {'inverted' if self.inverted else 'normal'}; "
            f"from machine.toml: {', '.join(sorted(self.saved)) or 'none, all built-in defaults'}"
        )


def defaultSettings(motor: Motor, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The motor's settings where nothing is saved, from the least specific to
    the most: FIELDS, the primary Hive's for every motor, MOTOR_DEFAULTS, the
    primary Hive's for this motor, and for a feeder motor its drive's (a Hive's
    are tuned on the geared feeder). A Hive value that is not a valid setting
    is ignored. Only the drive sets a direction: it follows how the motor is
    built in."""
    import hive_defaults

    hive = hive_defaults.namespace("steppers")
    values = {name: field.default for name, field in FIELDS.items()}
    for layer in (hive.get("*"), MOTOR_DEFAULTS.get(motor.name), hive.get(motor.name)):
        if not isinstance(layer, dict):
            continue
        for name, value in layer.items():
            field = FIELDS.get(name)
            if field is not None and field.table != DIRECTIONS and field.valid(value):
                values[name] = value
    for name, value in feederDrive(config).stepper_defaults.get(motor.name, {}).items():
        values[name] = value
    return values


def readStepperSettings(
    motor: Motor,
    config: Mapping[str, Any] | None = None,
    logger: Any = None,
) -> StepperSettings:
    """The motor's settings: what machine.toml holds, built-in defaults for the rest."""
    if config is None:
        config = machine_toml.read()
    values = defaultSettings(motor, config)
    saved: set[str] = set()
    for table in (CURRENTS, DRIVER, STALLGUARD):
        entry = _entry(config, table, motor)
        if entry is None:
            continue
        values.update(ENTRY_DEFAULTS.get(table, {}))
        for field in FIELDS.values():
            if field.table == table and field.key in entry:
                _take(field, entry[field.key], values, saved, f"{table}.{motor.key}.{field.key}", logger)
    directions = config.get(DIRECTIONS)
    if isinstance(directions, dict) and motor.name in directions:
        _take(FIELDS["inverted"], directions[motor.name], values, saved, f"{DIRECTIONS}.{motor.name}", logger)
    return StepperSettings(**values, saved=frozenset(saved))


def changedStepperSettings(
    motor: Motor,
    changes: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
) -> StepperSettings:
    """The motor's settings with `changes` made, not saved. Raises ValueError
    naming a setting that does not exist or a value out of its range."""
    for name, value in changes.items():
        field = FIELDS.get(name)
        if field is None:
            raise ValueError(f"There is no stepper setting '{name}'.")
        if not field.valid(value):
            raise ValueError(f"{name} must be {field.expects}, not {value!r}.")
    return replace(readStepperSettings(motor, config), **changes)


def saveStepperSettings(motor: Motor, changes: Mapping[str, Any]) -> StepperSettings:
    """Save some of a motor's settings; raises ValueError naming a bad one, saving none.

    A table entry it writes holds every setting of that table, the unchanged
    ones at their current values, so an entry never leans on ENTRY_DEFAULTS."""
    with machine_toml.edit() as config:
        updated = changedStepperSettings(motor, changes, config)
        for table in {FIELDS[name].table for name in changes}:
            if table == DIRECTIONS:
                _table(config, DIRECTIONS)[motor.name] = updated.inverted
                continue
            entry = _ownEntry(config, table, motor)
            for field in FIELDS.values():
                if field.table == table:
                    entry[field.key] = getattr(updated, field.name)
    return readStepperSettings(motor, config)


def applyStepperSettings(
    stepper: Any,
    settings: StepperSettings,
    fields: Iterable[str] | None = None,
    run: Callable[[str, Callable[[], Any]], Any] | None = None,
    *,
    rearm: bool = True,
) -> int:
    """Put settings on the stepper and its driver: every one (fields=None, as
    start-up does) or only those named. `run(action, command)` sends each
    command; start-up passes one that retries and stops init on failure.
    A new threshold or speed floor clears the stall latch and arms detection
    again, as a person changing them expects; `rearm=False` leaves both alone,
    for the tuner, which must never clear a stall it has not seen.
    On a machine that watches its drivers, a run or hold current other than
    the one a StealthChop driver was last sent starts its tuning over
    (resetDriverTuning), once a move under way has ended.
    Returns the driver register writes sent, which start-up checks against the
    driver's own count of writes it took."""
    run = run or _send
    changed = set(FIELDS) if fields is None else set(fields)
    stallguard_on = settings.stallguard and not DISABLE_STALLGUARD
    writes = 0

    def write(action: str, register: int, value: int) -> None:
        nonlocal writes
        run(action, lambda: stepper.write_driver_register(register, value))
        writes += 1

    if "stealthchop" in changed:
        write("set GCONF", TMC_REG_GCONF, GCONF_UART | (0 if settings.stealthchop else GCONF_EN_SPREADCYCLE))
    if "microsteps" in changed:
        run(f"set microsteps={settings.microsteps}", lambda: stepper.set_microsteps(settings.microsteps))
        writes += 1
    if changed & {"irun", "ihold", "ihold_delay"}:
        if settings.stealthchop and _currentDiffers(stepper, settings) and _watchesDrivers():
            _waitUntilStopped(stepper)
            writes += resetDriverTuning(
                stepper, (settings.irun, settings.ihold, settings.ihold_delay), settings.microsteps, run
            )
        else:
            run(
                f"set current IRUN={settings.irun} IHOLD={settings.ihold}",
                lambda: stepper.set_current(settings.irun, settings.ihold, settings.ihold_delay),
            )
            writes += 1
    if "coolstep" in changed:
        write("set CoolStep", TMC_REG_COOLCONF, COOLCONF_COOLSTEP if settings.coolstep else 0)
    if changed & {"stallguard", "sgthrs"}:
        write("set the StallGuard threshold", TMC_REG_SGTHRS, settings.sgthrs)
    if changed & {"stallguard", "tcoolthrs", "coolstep"}:
        write("set the StallGuard speed floor", TMC_REG_TCOOLTHRS, tcoolthrsRegister(settings))
    if changed & {"stallguard", "sgthrs", "tcoolthrs"}:
        # The stall monitor reads these. Detection is armed only on a motor
        # that has it on; a channel without a DIAG wire refuses the command.
        was_on = bool(getattr(stepper, "stallguard_enabled", False))
        stepper.stallguard_sgthrs = settings.sgthrs
        stepper.stallguard_tcoolthrs = settings.tcoolthrs
        stepper.stallguard_enabled = stallguard_on
        if rearm or "stallguard" in changed:
            if stallguard_on:
                run("clear its stall latch", stepper.clear_stall)
                run("arm stall detection", lambda: stepper.enable_stall_detection(True))
            elif was_on:
                run("disarm stall detection", lambda: stepper.enable_stall_detection(False))
    if "inverted" in changed:
        stepper.set_direction_inverted(settings.inverted)
    return writes


def resetDriverTuning(
    stepper: Any,
    current: tuple[int, int, int],
    microsteps: int,
    run: Callable[[str, Callable[[], Any]], Any] | None = None,
    *,
    clear_shutdown: bool = False,
) -> int:
    """Start the driver's automatic StealthChop tuning over, and send it
    `current` (IRUN, IHOLD, IHOLD_DELAY) and `microsteps` again.

    A StealthChop driver learns the PWM amplitude its motor needs at the
    current it is set to (PWM_OFS_AUTO, PWM_GRAD_AUTO). Run below the current
    it can regulate, it learns an amplitude far too high, and the first move
    at a real current then draws enough for its short-circuit protection to
    switch a coil off: the motor stands still while every move is answered
    with success. Writing PWMCONF with pwm_autoscale cleared and then as it
    was puts what it learned back to its start. The driver is off meanwhile,
    so no coil is driven on a half-set amplitude, and is switched on again
    only if it was on.

    `clear_shutdown` is for a driver that did switch itself off: with the
    driver off its short flags are gone, and clearing GSTAT takes drv_err
    with them. Returns the driver register writes sent."""
    run = run or _send
    irun, ihold, ihold_delay = current
    was_on = bool(getattr(stepper, "enabled", True)) and not getattr(stepper, "software_disabled", False)
    writes = 3  # switching it off, its current and its microstepping
    run("switch the driver off", lambda: stepper.enable_force(False))
    try:
        conf = run("read the driver's PWM settings", lambda: stepper.read_driver_register(TMC_REG_PWMCONF))
        if conf & PWMCONF_AUTOSCALE:
            run(
                "stop the driver's tuning",
                lambda: stepper.write_driver_register(TMC_REG_PWMCONF, conf & ~PWMCONF_AUTOSCALE),
            )
            run("start the driver's tuning over", lambda: stepper.write_driver_register(TMC_REG_PWMCONF, conf))
            writes += 2
        if clear_shutdown:
            run("clear the driver's error flags", lambda: stepper.write_driver_register(TMC_REG_GSTAT, GSTAT_FLAGS))
            writes += 1
        run(f"set current IRUN={irun} IHOLD={ihold}", lambda: stepper.set_current(irun, ihold, ihold_delay))
        run(f"set microsteps={microsteps}", lambda: stepper.set_microsteps(microsteps))
    finally:
        if was_on:
            run("switch the driver on", lambda: stepper.enable_force(True))
            writes += 1
    return writes


def _watchesDrivers() -> bool:
    """Whether this machine looks after its drivers' tuning (driver_watch.py):
    one that does not is sent a new current as it always was."""
    try:
        import driver_watch

        return driver_watch.watchEnabled()
    except Exception:
        return False


def _currentDiffers(stepper: Any, settings: StepperSettings) -> bool:
    """Whether the driver was last sent another run or hold current. Start-up
    has sent it none yet: it sends every setting to a driver whose tuning it
    has no reason to doubt, and resets nothing."""
    last = getattr(stepper, "last_set_current", None)
    return isinstance(last, dict) and (last.get("irun"), last.get("ihold")) != (settings.irun, settings.ihold)


def _waitUntilStopped(stepper: Any) -> None:
    """Give a move under way the time to end: a tuning reset switches the
    driver off for a moment, and a motor that is turning then loses steps."""
    give_up_at = time.monotonic() + TUNING_RESET_WAIT_S
    while time.monotonic() < give_up_at:
        try:
            if stepper.stopped:
                return
        except Exception:
            return
        time.sleep(0.02)


def tcoolthrsRegister(settings: StepperSettings) -> int:
    """TCOOLTHRS, shared by StallGuard and CoolStep: StallGuard's floor while it
    is on, every speed for CoolStep alone, and 0 (neither) otherwise."""
    if settings.stallguard and not DISABLE_STALLGUARD:
        return settings.tcoolthrs
    return TCOOLTHRS_EVERY_SPEED if settings.coolstep else 0


def _send(_action: str, command: Callable[[], Any]) -> Any:
    return command()


def _onOff(value: bool) -> str:
    return "on" if value else "off"


def _entryKeys(motor: Motor, config: Mapping[str, Any]) -> tuple[str, ...]:
    """The keys a motor's entry may be under in a per-motor table, the first
    winning: its key, older names for the same socket, and the spare socket
    [stepper_bindings] wired it to, which older files keyed it by."""
    keys = [motor.key, *motor.aliases]
    socket = motorSockets(config).get(motor.name)
    if socket in SPARE_SOCKETS:
        keys.append(socket)
    return tuple(keys)


def _entry(config: Mapping[str, Any], table_name: str, motor: Motor) -> dict[str, Any] | None:
    table = config.get(table_name)
    if not isinstance(table, dict):
        return None
    for key in _entryKeys(motor, config):
        entry = table.get(key)
        if isinstance(entry, dict):
            return entry
    return None


def _table(config: dict[str, Any], name: str) -> dict[str, Any]:
    table = config.get(name)
    if not isinstance(table, dict):
        table = {}
        config[name] = table
    return table


def _ownEntry(config: dict[str, Any], table_name: str, motor: Motor) -> dict[str, Any]:
    """The motor's entry under its own key, with anything saved under an older
    key folded in (its own key winning), so the file holds one entry for it."""
    keys = _entryKeys(motor, config)
    table = _table(config, table_name)
    merged: dict[str, Any] = {}
    for key in reversed(keys):
        entry = table.pop(key, None)
        if isinstance(entry, dict):
            merged.update(entry)
    table[motor.key] = merged
    return merged


def _take(
    field: Field,
    value: Any,
    values: dict[str, Any],
    saved: set[str],
    where: str,
    logger: Any,
) -> None:
    if field.valid(value):
        values[field.name] = value
        saved.add(field.name)
    elif logger is not None:
        logger.warning(f"Ignoring {where} = {value!r}: expected {field.expects}.")
