"""The pretend world behind the board: steppers, the chute and its hall sensor,
the board's outputs, and two servo lines (the board's own and a USB adapter's).

Everything moves on one clock, in steps of one millisecond, on a thread of its
own. `speed` runs that clock faster (or slower) than the wall clock, so tests
need not wait. Every change, from the host or from the control channel, is made
under `lock`, between steps.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .servos import PretendServo, ServoBus
from .steppers import FULL_STEPS_PER_TURN, StepperMotion, Tmc2209

# The v1.5 board in the distribution role (hwcfg_basically_v1_5.h).
STEPPER_NAMES = ("chute_stepper", "c_channel_1_rotor", "c_channel_3_rotor", "carousel", "c_channel_2_rotor")
CHUTE_CHANNEL = 0
HALL_INPUT = 0
DIGITAL_INPUT_COUNT = 1
DIGITAL_OUTPUT_COUNT = 2

STEP_US = 1000
MAX_STEPS_PER_WAKE = 200  # a stalled process catches up this far, then lets time slip


@dataclass
class Chute:
    """The chute: a stepper through a drive, turning without limit, and a hall
    sensor that is active while a magnet window passes it."""

    stepper: StepperMotion
    gear_ratio: float = 6.0  # motor turns per chute turn
    start_angle: float = 120.0  # where the chute is when the world starts
    magnet_angle: float = 0.0  # the middle of the magnet window
    magnet_width: float = 18.0
    active_level: int = 0  # the input reads this while the sensor is active
    forced: bool | None = None  # held active or inactive by hand, or None

    @property
    def angle(self) -> float:
        turns = self.stepper.rotor_full_steps / (FULL_STEPS_PER_TURN * self.gear_ratio)
        return (self.start_angle + turns * 360.0) % 360.0

    def hall_active(self) -> bool:
        if self.forced is not None:
            return self.forced
        apart = abs((self.angle - self.magnet_angle + 180.0) % 360.0 - 180.0)
        return apart <= self.magnet_width / 2

    def level(self) -> int:
        return self.active_level if self.hall_active() else 1 - self.active_level


@dataclass
class Output:
    value: bool = False
    duty: int | None = None  # set when it was last driven by PWM


class World:
    def __init__(self, *, speed: float = 1.0):
        self.lock = threading.RLock()
        self.speed = speed
        self.now_us = 0  # sim time since the world began
        self.drivers = [Tmc2209() for _ in STEPPER_NAMES]
        self.steppers = [
            StepperMotion(name, driver, self.read_input) for name, driver in zip(STEPPER_NAMES, self.drivers)
        ]
        self.chute = Chute(self.steppers[CHUTE_CHANNEL])
        self.outputs = [Output() for _ in range(DIGITAL_OUTPUT_COUNT)]
        self.board_bus = ServoBus()
        self.adapter_bus = ServoBus()
        self._tickers: list[Callable[[int], None]] = []
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def read_input(self, channel: int) -> int:
        """An input pin's level. Inputs are pulled up; the hall sensor pulls its low."""
        if channel == HALL_INPUT:
            return self.chute.level()
        return 1

    def on_tick(self, ticker: Callable[[int], None]) -> None:
        """Call `ticker(now_us)` after every step: the firmware's main loop."""
        self._tickers.append(ticker)

    def step(self) -> None:
        """One millisecond of the world."""
        with self.lock:
            self.now_us += STEP_US
            for stepper in self.steppers:
                stepper.step_1ms()
            self.board_bus.step(STEP_US / 1e6)
            self.adapter_bus.step(STEP_US / 1e6)
            for ticker in self._tickers:
                ticker(self.now_us)

    def advance(self, milliseconds: int) -> None:
        """Run the world forward by hand (for a world with no thread)."""
        for _ in range(milliseconds):
            self.step()

    def start(self) -> None:
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="sim-world", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        speed = self.speed
        wall_start = time.monotonic()
        sim_start = self.now_us
        while not self._stopping.is_set():
            if self.speed != speed:
                # A new speed counts from now.
                speed, wall_start, sim_start = self.speed, time.monotonic(), self.now_us
            target_us = sim_start + int((time.monotonic() - wall_start) * speed * 1e6)
            steps = 0
            while self.now_us + STEP_US <= target_us and steps < MAX_STEPS_PER_WAKE:
                self.step()
                steps += 1
            if steps == MAX_STEPS_PER_WAKE:
                # Too far behind: let the lost time go rather than race to catch up.
                wall_start = time.monotonic()
                sim_start = self.now_us
            time.sleep(0.001)

    def set_speed(self, speed: float) -> None:
        """Change how fast the world runs, from now on."""
        if speed <= 0:
            raise ValueError("The speed is a positive factor.")
        self.speed = speed

    # -- servos ---------------------------------------------------------------

    def bus(self, name: str) -> ServoBus:
        if name == "board":
            return self.board_bus
        if name == "adapter":
            return self.adapter_bus
        raise ValueError(f"No servo bus named {name!r}: 'board' or 'adapter'.")

    def add_servo(self, bus: str, servo: PretendServo) -> PretendServo:
        with self.lock:
            self.bus(bus).servos.append(servo)
            servo.power_up()
            return servo

    def describe(self) -> dict:
        with self.lock:
            return {
                "time_s": round(self.now_us / 1e6, 3),
                "speed": self.speed,
                "steppers": [
                    {
                        "channel": index,
                        "name": stepper.name,
                        "position": stepper.position,
                        "moving": not stepper.is_stopped(),
                        "speed": stepper.current_speed if not stepper.is_stopped() else 0,
                        "microsteps": stepper.driver.microsteps,
                        "energized": stepper.hw_enabled and stepper.driver.current_on,
                        "motor_turns": round(stepper.rotor_full_steps / FULL_STEPS_PER_TURN, 4),
                    }
                    for index, stepper in enumerate(self.steppers)
                ],
                "chute": {
                    "angle": round(self.chute.angle, 2),
                    "magnet_angle": self.chute.magnet_angle,
                    "magnet_width": self.chute.magnet_width,
                    "hall_active": self.chute.hall_active(),
                    "hall_forced": self.chute.forced,
                    "input_level": self.chute.level(),
                },
                "outputs": [{"channel": i, "value": o.value, "duty": o.duty} for i, o in enumerate(self.outputs)],
                "board_bus": self._describe_bus(self.board_bus),
                "adapter_bus": self._describe_bus(self.adapter_bus),
            }

    @staticmethod
    def _describe_bus(bus: ServoBus) -> dict:
        return {"powered": bus.powered, "stuck": bus.stuck, "servos": [servo.describe() for servo in bus.servos]}
