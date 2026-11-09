"""Pretend steppers and their TMC2209 drivers.

`StepperMotion` is the firmware's motion generator (Stepper.cpp) in Python: the
same states, integer speed ramps and homing, advanced one millisecond at a time
(the firmware's motion update rate) with the step generator's ten ticks of that
millisecond done at once. Each step it issues turns a pretend rotor, unless the
driver has no current, so a position can be read while a move runs and a chute
can be read off the rotor.

`Tmc2209` is the driver chip: its registers, read back as written, plus the ones
a real chip computes (IFCNT counts the writes it took, IOIN carries its version,
TSTEP, DRV_STATUS and SG_RESULT follow the motion).
"""

from __future__ import annotations

from typing import Callable

STEP_TICK_RATE_HZ = 10_000
STEP_MOTION_UPDATE_RATE_HZ = 1_000
STEPPER_MAX_SPEED = 60_000
TICKS_PER_UPDATE = STEP_TICK_RATE_HZ // STEP_MOTION_UPDATE_RATE_HZ

STOPPED, ACCELERATING, CRUISING, BRAKING = range(4)

FULL_STEPS_PER_TURN = 200


def _trunc_div(a: int, b: int) -> int:
    """C integer division: rounds toward zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _c_mod(a: int, b: int) -> int:
    return a - _trunc_div(a, b) * b


class Tmc2209:
    GCONF = 0x00
    GSTAT = 0x01
    IFCNT = 0x02
    SLAVECONF = 0x03
    IOIN = 0x06
    IHOLD_IRUN = 0x10
    TSTEP = 0x12
    TCOOLTHRS = 0x14
    SGTHRS = 0x40
    SG_RESULT = 0x41
    COOLCONF = 0x42
    MSCNT = 0x6A
    CHOPCONF = 0x6C
    DRV_STATUS = 0x6F
    PWM_CONF = 0x70
    PWM_SCALE = 0x71
    PWM_AUTO = 0x72

    VERSION = 0x21  # IOIN bits 24 to 31

    def __init__(self):
        self.powered = True  # the motor supply: an unpowered driver hears nothing
        self.power_on()

    def power_on(self) -> None:
        # The chip's own reset values, as far as anything here reads them.
        self._registers: dict[int, int] = {
            self.GCONF: 0x00000041,
            self.CHOPCONF: 0x10000053,
            self.IHOLD_IRUN: 0x00001F10,
            self.PWM_CONF: 0xC10D0024,
        }
        self._gstat = 0x1  # reset
        self.ifcnt = 0

    def write(self, register: int, value: int) -> bool:
        if not self.powered:
            return False
        value &= 0xFFFFFFFF
        if register == self.GSTAT:
            self._gstat &= ~value  # writing a 1 clears the flag
        elif register not in (self.IFCNT, self.IOIN, self.TSTEP, self.SG_RESULT, self.MSCNT, self.DRV_STATUS):
            self._registers[register] = value
        self.ifcnt = (self.ifcnt + 1) & 0xFF
        return True

    def read(self, register: int, motion: "StepperMotion | None" = None) -> int | None:
        """The register's value, or None when the driver does not answer."""
        if not self.powered:
            return None
        speed = abs(motion.current_speed) if motion is not None and not motion.is_stopped() else 0
        if register == self.IFCNT:
            return self.ifcnt
        if register == self.GSTAT:
            return self._gstat
        if register == self.IOIN:
            return (self.VERSION << 24) | 0x40  # DIR low, ENN low, PDN_UART high
        if register == self.TSTEP:
            if speed == 0:
                return 0xFFFFF
            # Clocks (12 MHz) between 1/256 microsteps.
            return min(0xFFFFF, int(12_000_000 / (speed * 256 / self.microsteps)))
        if register == self.SG_RESULT:
            return 0 if speed == 0 else 300
        if register == self.MSCNT:
            return (motion.position * (256 // self.microsteps)) & 0x3FF if motion is not None else 0
        if register == self.DRV_STATUS:
            irun = (self._registers.get(self.IHOLD_IRUN, 0) >> 8) & 0x1F
            ihold = self._registers.get(self.IHOLD_IRUN, 0) & 0x1F
            standstill = speed == 0
            value = ((ihold if standstill else irun) << 16) | (1 << 30)  # CS_ACTUAL, stealth
            if standstill:
                value |= 1 << 31
            return value
        if register == self.PWM_SCALE:
            return 0x00000020
        if register == self.PWM_AUTO:
            return 0x000E0024
        return self._registers.get(register, 0)

    @property
    def microsteps(self) -> int:
        mres = (self._registers.get(self.CHOPCONF, 0) >> 24) & 0xF
        return 256 >> min(mres, 8)

    @property
    def current_on(self) -> bool:
        return (self._registers.get(self.CHOPCONF, 0) & 0xF) != 0


class StepperMotion:
    """One stepper as the firmware moves it (Stepper.cpp), and its rotor."""

    def __init__(self, name: str, driver: Tmc2209, read_input: Callable[[int], int]):
        self.name = name
        self.driver = driver
        self._read_input = read_input  # an input channel's level, 0 or 1
        self.accel = 10_000
        self.max_speed = 2_000
        self.min_speed = 16
        self._saved = (0, 0, 0)
        self.state = STOPPED
        self.mc_distance = -1
        self.mc_speed = -1
        self.mc_dir = 1
        self.mc_home_input = -1
        self.mc_home_polarity = True
        self.steps_moved = 0
        self.steps_frac = 0
        self.brake_distance = 0
        self.current_speed = 0
        self.current_speed_frac = 0
        self.current_dir = 1
        self.position = 0  # the firmware's absolute position, in microsteps
        self.jitter_active = False
        self.jitter_amplitude = 0
        self.jitter_strokes_remaining = 0
        self.jitter_dir = 1
        self.stall_pin = -1
        self.stall_enabled = False
        self.stalled = False
        # The board's two enable gates: the nEN pin and the chopper.
        self.hw_enabled = False
        # Where the rotor really is, in full steps. It turns only when energized.
        self.rotor_full_steps = 0.0

    # -- commands (the firmware's Stepper methods) -----------------------------

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        max_speed = min(max_speed, STEPPER_MAX_SPEED)
        min_speed = min(min_speed, STEPPER_MAX_SPEED)
        if min_speed > max_speed:
            return
        self.min_speed = min_speed
        self.max_speed = max_speed

    def set_acceleration(self, acceleration: int) -> None:
        self.accel = acceleration

    def is_stopped(self) -> bool:
        return self.state == STOPPED

    def move_steps(self, distance: int) -> bool:
        if self.jitter_active or self.state != STOPPED:
            return False
        if distance == 0:
            return True
        self.mc_distance = abs(distance)
        self.mc_dir = 1 if distance > 0 else -1
        self.mc_speed = -1
        self.mc_home_input = -1
        self.current_speed = self.min_speed
        self.current_speed_frac = 0
        self.current_dir = self.mc_dir
        self.steps_moved = 0
        self.steps_frac = 0
        self.brake_distance = self.mc_distance // 2
        self.state = ACCELERATING
        return True

    def move_at_speed(self, speed: int) -> bool:
        if self.jitter_active:
            return False
        if speed == 0:
            self.mc_speed = 0
            self.mc_distance = -1
            self.mc_home_input = -1
            self.mc_dir = self.current_dir
            self.steps_moved = 0
            self.steps_frac = 0
            if self.state == STOPPED:
                self.current_speed = 0
                self.current_speed_frac = 0
                return True
            self.state = BRAKING
            return True
        self.mc_dir = 1 if speed > 0 else -1
        self.mc_speed = min(abs(speed), STEPPER_MAX_SPEED)
        self.mc_distance = -1
        self.mc_home_input = -1
        if self.state == STOPPED:
            self.current_dir = self.mc_dir
            self.current_speed = self.min_speed
            self.current_speed_frac = 0
            self.state = ACCELERATING
        elif self.current_speed == self.mc_speed and self.current_dir == self.mc_dir:
            self.state = CRUISING
        elif self.current_dir != self.mc_dir or self.current_speed > self.mc_speed:
            self.state = BRAKING
        else:
            self.state = ACCELERATING
        self.steps_moved = 0
        self.steps_frac = 0
        return True

    def jitter(self, amplitude: int, cycles: int, speed: int, accel: int) -> bool:
        if self.jitter_active or self.state != STOPPED:
            return False
        if amplitude <= 0 or cycles <= 0 or speed <= 0 or accel <= 0:
            return False
        self._saved = (self.accel, self.max_speed, self.min_speed)
        self.set_acceleration(accel)
        self.set_speed_limits(self.min_speed, speed)
        self.jitter_amplitude = amplitude
        self.jitter_strokes_remaining = cycles * 2
        self.jitter_dir = 1
        self.jitter_active = True
        self._begin_jitter_stroke()
        return True

    def _begin_jitter_stroke(self) -> None:
        amplitude = self.jitter_amplitude
        if amplitude <= 0:
            self.state = STOPPED
            self.jitter_strokes_remaining = 0
            self.jitter_amplitude = 0
            self.jitter_active = False
            return
        self.mc_distance = amplitude
        self.mc_dir = self.jitter_dir
        self.mc_speed = -1
        self.mc_home_input = -1
        self.current_speed = self.min_speed
        self.current_speed_frac = 0
        self.current_dir = self.jitter_dir
        self.steps_moved = 0
        self.steps_frac = 0
        self.brake_distance = amplitude // 2
        self.state = ACCELERATING

    def home(self, home_speed: int, input_channel: int, polarity: bool) -> None:
        self.move_at_speed(home_speed)
        self.mc_home_input = input_channel
        self.mc_home_polarity = polarity

    def enable_stall_detection(self, enable: bool) -> None:
        self.stall_enabled = enable
        if enable:
            self.stalled = False

    # -- time -----------------------------------------------------------------

    def _home_reached(self) -> bool:
        return self.mc_home_input >= 0 and bool(self._read_input(self.mc_home_input)) == self.mc_home_polarity

    def _stop_homed(self) -> None:
        self.state = STOPPED
        self.current_speed = 0
        self.position = 0
        self.mc_home_input = -1

    def step_1ms(self) -> None:
        """One motion update (motion_update_tick), then the step generator's ten
        ticks of this millisecond (stepgen_tick)."""
        self._motion_update()
        self._step_generate()

    def _turn_rotor(self, steps: int) -> None:
        if self.hw_enabled and self.driver.current_on:
            self.rotor_full_steps += steps / self.driver.microsteps

    def _step_generate(self) -> None:
        if self.state == STOPPED:
            return
        homing = self.mc_home_input >= 0
        if homing and self._home_reached():
            self._stop_homed()
            return
        self.steps_frac += self.current_speed * TICKS_PER_UPDATE
        # Either side of zero by a whole step is a step (a reversal negates the
        # fraction), in the current direction.
        steps = _trunc_div(self.steps_frac, STEP_TICK_RATE_HZ)
        self.steps_frac -= steps * STEP_TICK_RATE_HZ
        steps = abs(steps)
        if self.mc_distance > 0:
            steps = min(steps, self.mc_distance - self.steps_moved)
        if homing:
            # The firmware checks the input every tick: step one at a time.
            for _ in range(steps):
                self.steps_moved += 1
                self.position += self.current_dir
                self._turn_rotor(self.current_dir)
                if self._home_reached():
                    self._stop_homed()
                    return
        else:
            self.steps_moved += steps
            self.position += self.current_dir * steps
            self._turn_rotor(self.current_dir * steps)
        if self.mc_distance > 0 and self.steps_moved >= self.mc_distance:
            self.state = STOPPED
            self.current_speed = 0

    def _motion_update(self) -> None:
        if self.state == STOPPED:
            if self.jitter_strokes_remaining > 0:
                self.jitter_strokes_remaining -= 1
                if self.jitter_strokes_remaining > 0:
                    self.jitter_dir = -self.jitter_dir
                    self._begin_jitter_stroke()
                else:
                    self.jitter_amplitude = 0
                    self.jitter_active = False
                    self.accel, self.max_speed, self.min_speed = self._saved
            return
        if self.state == ACCELERATING:
            self.current_speed_frac += self.accel
            self.current_speed += _trunc_div(self.current_speed_frac, STEP_MOTION_UPDATE_RATE_HZ)
            self.current_speed_frac = _c_mod(self.current_speed_frac, STEP_MOTION_UPDATE_RATE_HZ)
            if self.mc_speed > 0 and self.current_speed >= self.mc_speed:
                self.current_speed = self.mc_speed
                self.current_speed_frac = 0
                self.state = CRUISING
            elif self.mc_speed < 0 and self.current_speed >= self.max_speed:
                self.current_speed = self.max_speed
                self.current_speed_frac = 0
                self.brake_distance = self.mc_distance - self.steps_moved
                self.state = CRUISING
        if self.state in (ACCELERATING, CRUISING):
            if self.mc_home_input >= 0 and self._home_reached():
                self._stop_homed()
                return
            if self.steps_moved >= self.brake_distance and self.mc_distance > 0:
                self.state = BRAKING
            return
        if self.state == BRAKING:
            self.current_speed_frac += self.accel
            self.current_speed -= _trunc_div(self.current_speed_frac, STEP_MOTION_UPDATE_RATE_HZ)
            self.current_speed_frac = _c_mod(self.current_speed_frac, STEP_MOTION_UPDATE_RATE_HZ)
            if self.current_speed <= self.min_speed:
                self.current_speed = self.min_speed
                self.current_speed_frac = 0
                if self.mc_speed > 0 and self.current_dir != self.mc_dir:
                    self.current_dir = self.mc_dir
                    self.steps_frac = -self.steps_frac
                    self.state = ACCELERATING
                elif self.mc_speed == 0:
                    self.state = STOPPED
                else:
                    self.state = CRUISING
            if self.mc_speed > 0 and self.mc_dir == self.current_dir and self.current_speed >= self.mc_speed:
                self.current_speed = self.mc_speed
                self.current_speed_frac = 0
                self.state = CRUISING
