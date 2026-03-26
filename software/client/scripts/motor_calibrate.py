import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import readchar
from global_config import mkGlobalConfig, GlobalConfig
from hardware.sorter_interface import StepperMotor, ServoMotor
from irl.config import mkIRLConfig, mkIRLInterface, IRLConfig, IRLInterface, StepperConfig
from blob_manager import getChuteCalibration, setChuteCalibration
from subsystems.distribution.chute import Chute

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

STEP_COUNTS: list[int] = [1, 10, 50, 100, 200, 500, 750, 1000, 1500, 2000, 3000, 5000, 8000, 16000]
SERVO_ANGLE_STEPS: list[int] = [1, 5, 10, 15, 30, 45]
SPEED_PRESETS: list[int] = [100, 250, 500, 1000, 2000, 4000, 8000]
DEFAULT_SPEED_IDX: int = 3  # 1000
CHUTE_REVOLVE_ANGLE: float = 347 #max reachable before hitting end switch
CHUTE_MIN_ANGLE: float = 4
BINS_PER_LAYER: int = 12
DEG_PER_SECTION: float = 60.0


def angleForBin(cal: dict[str, float], bin_number: int, bins_per_section: int = 2) -> float:
    section = bin_number // bins_per_section
    bin_in_section = bin_number % bins_per_section
    usable = DEG_PER_SECTION - cal["pillar_width"]
    bin_width = usable / bins_per_section
    return cal["first_bin_center"] + section * DEG_PER_SECTION + bin_in_section * bin_width


def chuteCalibrateLoop(chute: Chute, step_count_idx: int) -> dict[str, float] | None:
    stepper = chute.stepper

    def _printCalScreen(stage: str, instructions: str) -> None:
        print("\033[2J\033[H", end="")
        print("Chute Calibration Wizard")
        print("========================")
        print(f"Stage: {stage}")
        print(f"Chute angle: {chute.current_angle:.2f}°")
        print()
        print(instructions)
        print()
        step_count = STEP_COUNTS[step_count_idx]
        print(f"  ←/→     Nudge chute ({stepper.degrees_for_microsteps(step_count):.3f}° stepper)")
        print(f"  ↑/↓     Change step size")
        print(f"  Enter   Confirm position")
        print(f"  Q       Cancel calibration")
        print()

    print("Homing chute before calibration...")
    chute.home()

    _printCalScreen(
        "1/2 — Aim at BIN 1 (first bin after home)",
        "Nudge the chute until it points at the CENTER of the first bin.\n"
        "This bin is in the middle of a section (pillar is ahead of it)."
    )

    while True:
        key = readchar.readkey()
        step_count = STEP_COUNTS[step_count_idx]
        if key == readchar.key.LEFT:
            stepper.move_degrees(-stepper.degrees_for_microsteps(step_count))
        elif key == readchar.key.RIGHT:
            stepper.move_degrees(stepper.degrees_for_microsteps(step_count))
        elif key == readchar.key.UP:
            step_count_idx = min(step_count_idx + 1, len(STEP_COUNTS) - 1)
        elif key == readchar.key.DOWN:
            step_count_idx = max(step_count_idx - 1, 0)
        elif key == readchar.key.ENTER:
            break
        elif key.lower() == "q":
            return None
        else:
            continue
        _printCalScreen(
            "1/2 — Aim at BIN 1 (first bin after home)",
            "Nudge the chute until it points at the CENTER of the first bin.\n"
            "This bin is in the middle of a section (pillar is ahead of it)."
        )

    home_to_bin1 = chute.current_angle

    _printCalScreen(
        "2/2 — Aim at BIN 2 (next bin, across the pillar)",
        "Nudge the chute until it points at the CENTER of the next bin.\n"
        "This bin is ACROSS the support pillar from bin 1."
    )

    while True:
        key = readchar.readkey()
        step_count = STEP_COUNTS[step_count_idx]
        if key == readchar.key.LEFT:
            stepper.move_degrees(-stepper.degrees_for_microsteps(step_count))
        elif key == readchar.key.RIGHT:
            stepper.move_degrees(stepper.degrees_for_microsteps(step_count))
        elif key == readchar.key.UP:
            step_count_idx = min(step_count_idx + 1, len(STEP_COUNTS) - 1)
        elif key == readchar.key.DOWN:
            step_count_idx = max(step_count_idx - 1, 0)
        elif key == readchar.key.ENTER:
            break
        elif key.lower() == "q":
            return None
        else:
            continue
        _printCalScreen(
            "2/2 — Aim at BIN 2 (section 0, second bin)",
            "Nudge the chute until it points at the CENTER of the second bin.\n"
            "This is the bin AFTER the support pillar, still in the same section."
        )

    gap = chute.current_angle - home_to_bin1
    if gap < 30:
        pillar_width = DEG_PER_SECTION - 2 * gap
    else:
        pillar_width = 2 * (gap - 30)

    cal: dict[str, float] = {
        "first_bin_center": round(home_to_bin1, 3),
        "pillar_width": round(pillar_width, 3),
    }

    setChuteCalibration(cal)

    usable = DEG_PER_SECTION - cal["pillar_width"]
    print("\033[2J\033[H", end="")
    print("Chute Calibration Complete")
    print("==========================")
    print(f"  FIRST_BIN_CENTER = {cal['first_bin_center']:.1f}")
    print(f"  PILLAR_WIDTH_DEG = {cal['pillar_width']:.1f}")
    print()
    print(f"  usable per section: {usable:.3f}°")
    print(f"  bin width (2/section): {usable / 2:.3f}°")
    print(f"  gap between calibrated bins: {gap:.3f}°")
    print()
    print("Paste these into chute.py. Saved to blob storage.")
    print("Press any key to continue.")
    readchar.readkey()
    return cal


def printStatus(
    steppers: dict[str, StepperMotor],
    stepper_names: list[str],
    selected_idx: int,
    step_count_idx: int,
    speed_idxs: dict[str, int],
    servos: list[ServoMotor],
    chute=None,
    chute_cal: dict[str, float] | None = None,
) -> None:
    name: str = stepper_names[selected_idx]
    stepper: StepperMotor = steppers[name]
    step_count: int = STEP_COUNTS[step_count_idx]
    speed: int = SPEED_PRESETS[speed_idxs[name]]
    quarter_degrees: int = 90
    print("\033[2J\033[H", end="")
    print("Motor Calibration Tool")
    print("======================")
    if name == "chute" and chute is not None:
        print(f"Selected: {name} (stepper: {stepper.position_degrees:.2f}°, chute: {chute.current_angle:.2f}°)")
    else:
        print(f"Selected: {name} (position: {stepper.position_degrees:.2f}°)")
    print()
    print("Stepper Controls:")
    print(
        f"  ←/→     Move stepper (current: {stepper.degrees_for_microsteps(step_count):.3f}°)"
    )
    print(f"  ↑/↓     Change microstep pulse ({', '.join(map(str, STEP_COUNTS))})")
    print(f"  W/E     Change max speed (current: {speed} µsteps/s)")
    print(f"  A/D     Quarter turn ({quarter_degrees}°)")
    if name == "carousel":
        print("  L       Loop carousel (-90° turns)")
        print("  H       Home carousel (+95°, set zero)")
    print("  Tab     Switch stepper")
    print("  Enter   Set current position as zero")
    if name == "chute":
        print("  H       Home chute via sensor")
        print("  G       Go to chute angle (0-360)")
        print(f"  R       Revolve chute (0° ↔ {CHUTE_REVOLVE_ANGLE:.0f}°)")
        print("  T       Random movement test")
        print("  B       Go to bin (1-12)")
        print("  C       Chute calibration wizard")
        print()
        if chute_cal is not None and "pillar_width" in chute_cal:
            usable = DEG_PER_SECTION - chute_cal["pillar_width"]
            print("Chute Calibration:")
            print(f"  FIRST_BIN_CENTER = {chute_cal['first_bin_center']:.1f}")
            print(f"  PILLAR_WIDTH_DEG = {chute_cal['pillar_width']:.1f}")
            print(f"  bin width (2/section): {usable / 2:.3f}°")
        elif chute_cal is not None:
            print("Chute Calibration: STALE (re-run calibration with C)")
        else:
            print("Chute Calibration: NOT SET (press C to calibrate)")
    print()
    print("Servo Controls (per layer):")
    for i, servo in enumerate(servos):
        state: str = "open" if servo.isOpen() else "closed"
        print(
            f"  {i + 1}       Toggle layer {i} servo (currently {state} at {servo.angle}°)"
        )
    print()
    print("  S       Enter servo calibration mode")
    print("  Q       Quit")
    print()


def printServoCalStatus(
    servos: list[ServoMotor],
    selected_idx: int,
    angle_step_idx: int,
) -> None:
    servo: ServoMotor = servos[selected_idx]
    step: int = SERVO_ANGLE_STEPS[angle_step_idx]
    print("\033[2J\033[H", end="")
    print("Servo Calibration Mode")
    print("======================")
    print(f"Selected: servo {selected_idx} (current angle: {servo.angle}°)")
    print()
    print(f"  ←/→     Move servo by {step}°")
    print(f"  ↑/↓     Change step size ({', '.join(map(str, SERVO_ANGLE_STEPS))})")
    print("  Tab     Switch servo")
    print()
    for i, s in enumerate(servos):
        marker: str = " >> " if i == selected_idx else "    "
        print(f"{marker}servo {i}: {s.angle}°")
    print()
    print("  G       Go to angle (type a number)")
    print("  Q       Back to main menu")
    print()


def servo_calibrate_loop(servos: list[ServoMotor]) -> None:
    selected_idx: int = 0
    angle_step_idx: int = 2  # default 10°

    printServoCalStatus(servos, selected_idx, angle_step_idx)

    while True:
        key: str = readchar.readkey()
        servo: ServoMotor = servos[selected_idx]

        if key == readchar.key.LEFT:
            new_angle: int = max(0, servo.angle - SERVO_ANGLE_STEPS[angle_step_idx])
            servo.move_to_and_release(new_angle)
        elif key == readchar.key.RIGHT:
            new_angle = min(180, servo.angle + SERVO_ANGLE_STEPS[angle_step_idx])
            servo.move_to_and_release(new_angle)
        elif key == readchar.key.UP:
            angle_step_idx = min(angle_step_idx + 1, len(SERVO_ANGLE_STEPS) - 1)
        elif key == readchar.key.DOWN:
            angle_step_idx = max(angle_step_idx - 1, 0)
        elif key == "\t":
            selected_idx = (selected_idx + 1) % len(servos)
        elif key.lower() == "g":
            print("\033[2J\033[H", end="")
            angle_str: str = input(f"Enter angle (0-180) for servo {selected_idx}: ")
            try:
                target: int = int(angle_str)
                if 0 <= target <= 180:
                    servo.move_to_and_release(target)
                else:
                    print("Angle must be 0-180")
                    readchar.readkey()
            except ValueError:
                print("Invalid number")
                readchar.readkey()
        elif key.lower() == "q":
            return
        else:
            continue

        printServoCalStatus(servos, selected_idx, angle_step_idx)


def main() -> None:
    gc: GlobalConfig = mkGlobalConfig()
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"motor_calibrate_{timestamp}.log"
    gc.logger._log_file = open(log_path, "a")
    irl_config: IRLConfig = mkIRLConfig()
    irl: IRLInterface = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    steppers: dict[str, StepperMotor] = {
        "carousel": irl.carousel_stepper,
        "chute": irl.chute_stepper,
        "c_channel_1": irl.first_c_channel_rotor_stepper,
        "c_channel_2": irl.second_c_channel_rotor_stepper,
        "c_channel_3": irl.third_c_channel_rotor_stepper,
    }
    stepper_names: list[str] = list(steppers.keys())
    selected_idx: int = 0
    step_count_idx: int = 1

    stepper_config_map: dict[str, StepperConfig] = {
        "carousel": irl_config.carousel_stepper,
        "chute": irl_config.chute_stepper,
        "c_channel_1": irl_config.first_c_channel_rotor_stepper,
        "c_channel_2": irl_config.second_c_channel_rotor_stepper,
        "c_channel_3": irl_config.third_c_channel_rotor_stepper,
    }

    def _closestSpeedIdx(target: int) -> int:
        best = 0
        for i, preset in enumerate(SPEED_PRESETS):
            if abs(preset - target) < abs(SPEED_PRESETS[best] - target):
                best = i
        return best

    speed_idxs: dict[str, int] = {
        name: _closestSpeedIdx(stepper_config_map[name].default_steps_per_second)
        for name in stepper_names
    }

    servos: list[ServoMotor] = irl.servos
    chute_cal: dict[str, float] | None = getChuteCalibration()

    def _printMain() -> None:
        printStatus(steppers, stepper_names, selected_idx, step_count_idx, speed_idxs, servos, irl.chute, chute_cal)

    _printMain()

    try:
        while True:
            key: str = readchar.readkey()
            name: str = stepper_names[selected_idx]
            stepper: StepperMotor = steppers[name]
            step_count: int = STEP_COUNTS[step_count_idx]

            if key == readchar.key.LEFT:
                stepper.move_degrees(-stepper.degrees_for_microsteps(step_count))
                _printMain()
            elif key == readchar.key.RIGHT:
                stepper.move_degrees(stepper.degrees_for_microsteps(step_count))
                _printMain()
            elif key.lower() == "a":
                stepper.move_degrees(-90)
                _printMain()
            elif key.lower() == "d":
                stepper.move_degrees(90)
                _printMain()
            elif key == readchar.key.UP:
                step_count_idx = min(step_count_idx + 1, len(STEP_COUNTS) - 1)
                _printMain()
            elif key == readchar.key.DOWN:
                step_count_idx = max(step_count_idx - 1, 0)
                _printMain()
            elif key.lower() == "w":
                speed_idxs[name] = min(speed_idxs[name] + 1, len(SPEED_PRESETS) - 1)
                stepper.set_speed_limits(16, SPEED_PRESETS[speed_idxs[name]])
                _printMain()
            elif key.lower() == "e":
                speed_idxs[name] = max(speed_idxs[name] - 1, 0)
                stepper.set_speed_limits(16, SPEED_PRESETS[speed_idxs[name]])
                _printMain()
            elif key == "\t":
                selected_idx = (selected_idx + 1) % len(stepper_names)
                _printMain()
            elif key == readchar.key.ENTER:
                stepper.position_degrees = 0.0
                _printMain()
                print(f"Zeroed {name} position")
            elif key.isdigit() and 1 <= int(key) <= 16:
                layer_idx: int = int(key) - 1
                if layer_idx < len(servos):
                    servos[layer_idx].toggle()
                    _printMain()
            elif key.lower() == "g" and name == "chute":
                print("\033[2J\033[H", end="")
                angle_str = input("Enter chute angle (0-360): ")
                try:
                    target = float(angle_str)
                    if 0 <= target <= 360:
                        irl.chute.moveToAngle(target)
                        while not irl.chute.stepper.stopped:
                            time.sleep(0.01)
                    else:
                        print("Angle must be 0-360")
                        readchar.readkey()
                except ValueError:
                    print("Invalid number")
                    readchar.readkey()
                _printMain()
            elif key.lower() == "h" and name == "chute":
                print("Homing chute...")
                irl.chute.home()
                _printMain()
            elif key.lower() == "r" and name == "chute":
                print("Homing chute...")
                irl.chute.home()
                print(f"Revolving chute (0° ↔ {CHUTE_REVOLVE_ANGLE:.0f}°). Press Q to stop.")
                chute_at_zero = True
                import select, sys as _sys, tty, termios
                old_settings = termios.tcgetattr(_sys.stdin)
                tty.setcbreak(_sys.stdin.fileno())
                try:
                    while True:
                        if chute_at_zero:
                            irl.chute.moveToAngle(CHUTE_REVOLVE_ANGLE)
                        else:
                            irl.chute.home()
                            chute_at_zero = not chute_at_zero
                            continue
                        # Wait for move to finish, checking for Q
                        while not irl.chute.stepper.stopped:
                            if select.select([_sys.stdin], [], [], 0)[0]:
                                ch = _sys.stdin.read(1)
                                if ch.lower() == "q":
                                    raise StopIteration
                            time.sleep(0.01)
                        chute_at_zero = not chute_at_zero
                except StopIteration:
                    pass
                finally:
                    termios.tcsetattr(_sys.stdin, termios.TCSADRAIN, old_settings)
                _printMain()
            elif key.lower() == "t" and name == "chute":
                import random, select, sys as _sys, tty, termios
                print("Homing chute...")
                irl.chute.home()
                print("Random movement test. Press Q to stop.")
                old_settings = termios.tcgetattr(_sys.stdin)
                tty.setcbreak(_sys.stdin.fileno())
                try:
                    current = CHUTE_MIN_ANGLE
                    irl.chute.moveToAngle(current)
                    while not irl.chute.stepper.stopped:
                        time.sleep(0.01)
                    while True:
                        delta = random.choice([-1, 1]) * random.choice([10, 15, 30, 50, 70, 90, 120, 150, 180])
                        target = max(CHUTE_MIN_ANGLE, min(CHUTE_REVOLVE_ANGLE, current + delta))
                        if target == current:
                            continue
                        gc.logger.info(f"Chute random test: {current:.0f}° -> {target:.0f}°")
                        irl.chute.moveToAngle(target)
                        while not irl.chute.stepper.stopped:
                            if select.select([_sys.stdin], [], [], 0)[0]:
                                ch = _sys.stdin.read(1)
                                if ch.lower() == "q":
                                    raise StopIteration
                            time.sleep(0.01)
                        current = target
                except StopIteration:
                    pass
                finally:
                    termios.tcsetattr(_sys.stdin, termios.TCSADRAIN, old_settings)
                _printMain()
            elif key.lower() == "b" and name == "chute":
                if chute_cal is None or "pillar_width" not in chute_cal:
                    print("No calibration set. Run calibration first (C).")
                    print("Press any key...")
                    readchar.readkey()
                else:
                    print("\033[2J\033[H", end="")
                    print("Bin Targeting (1-12)")
                    print("====================")
                    for b in range(BINS_PER_LAYER):
                        s = b // 2
                        bi = b % 2
                        a = angleForBin(chute_cal, b)
                        print(f"  Bin {b + 1:2d}  (section {s}, bin {bi})  → {a:.2f}°")
                    print()
                    bin_str = input("Enter bin number (1-12): ")
                    try:
                        bin_num = int(bin_str)
                        if 1 <= bin_num <= BINS_PER_LAYER:
                            target_angle = angleForBin(chute_cal, bin_num - 1)
                            print(f"Moving to bin {bin_num} at {target_angle:.2f}°...")
                            irl.chute.moveToAngle(target_angle)
                            while not irl.chute.stepper.stopped:
                                time.sleep(0.01)
                        else:
                            print(f"Must be 1-{BINS_PER_LAYER}")
                            readchar.readkey()
                    except ValueError:
                        print("Invalid number")
                        readchar.readkey()
                _printMain()
            elif key.lower() == "c" and name == "chute":
                result = chuteCalibrateLoop(irl.chute, step_count_idx)
                if result is not None:
                    chute_cal = result
                _printMain()
            elif key.lower() == "l" and name == "carousel":
                import select, sys as _sys, tty, termios
                print("Looping carousel (-90° turns). Press Q to stop.")
                old_settings = termios.tcgetattr(_sys.stdin)
                tty.setcbreak(_sys.stdin.fileno())
                try:
                    while True:
                        stepper.move_degrees(-90)
                        while not stepper.stopped:
                            if select.select([_sys.stdin], [], [], 0)[0]:
                                ch = _sys.stdin.read(1)
                                if ch.lower() == "q":
                                    raise StopIteration
                            time.sleep(0.01)
                        time.sleep(0.5)
                        if select.select([_sys.stdin], [], [], 0)[0]:
                            ch = _sys.stdin.read(1)
                            if ch.lower() == "q":
                                raise StopIteration
                except StopIteration:
                    pass
                finally:
                    termios.tcsetattr(_sys.stdin, termios.TCSADRAIN, old_settings)
                _printMain()
            elif key.lower() == "h" and name == "carousel":
                print("Homing carousel (+95°, zeroing)...")
                stepper.move_degrees(95)
                while not stepper.stopped:
                    time.sleep(0.01)
                stepper.position_degrees = 0.0
                _printMain()
            elif key.lower() == "s":
                servo_calibrate_loop(servos)
                _printMain()
            elif key.lower() == "q":
                print("Exiting...")
                break
    finally:
        irl.disableSteppers()


if __name__ == "__main__":
    main()
