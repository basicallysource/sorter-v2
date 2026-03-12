import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import readchar
from global_config import mkGlobalConfig, GlobalConfig
from hardware.sorter_interface import StepperMotor, ServoMotor
from irl.config import mkIRLConfig, mkIRLInterface, IRLConfig, IRLInterface

STEP_COUNTS: list[int] = [1, 10, 50, 100, 200, 500, 750, 1000, 1500, 2000]
SERVO_ANGLE_STEPS: list[int] = [1, 5, 10, 15, 30, 45]


def printStatus(
    steppers: dict[str, StepperMotor],
    stepper_names: list[str],
    selected_idx: int,
    step_count_idx: int,
    servos: list[ServoMotor],
) -> None:
    name: str = stepper_names[selected_idx]
    stepper: StepperMotor = steppers[name]
    step_count: int = STEP_COUNTS[step_count_idx]
    quarter_degrees: int = 90
    print("\033[2J\033[H", end="")
    print("Motor Calibration Tool")
    print("======================")
    print(f"Selected: {name} (position: {stepper.position_degrees:.2f}°)")
    print()
    print("Stepper Controls:")
    print(
        f"  ←/→     Move stepper (current: {stepper.degrees_for_microsteps(step_count):.3f}°)"
    )
    print(f"  ↑/↓     Change microstep pulse ({', '.join(map(str, STEP_COUNTS))})")
    print(f"  A/D     Quarter turn ({quarter_degrees}°)")
    print("  Tab     Switch stepper")
    print("  Enter   Set current position as zero")
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
    irl_config: IRLConfig = mkIRLConfig()
    irl: IRLInterface = mkIRLInterface(irl_config, gc)

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

    servos: list[ServoMotor] = irl.servos

    printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)

    while True:
        key: str = readchar.readkey()
        name: str = stepper_names[selected_idx]
        stepper: StepperMotor = steppers[name]
        step_count: int = STEP_COUNTS[step_count_idx]

        if key == readchar.key.LEFT:
            stepper.move_degrees(-stepper.degrees_for_microsteps(step_count))
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key == readchar.key.RIGHT:
            stepper.move_degrees(stepper.degrees_for_microsteps(step_count))
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key.lower() == "a":
            stepper.move_degrees(-90)
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key.lower() == "d":
            stepper.move_degrees(90)
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key == readchar.key.UP:
            step_count_idx = min(step_count_idx + 1, len(STEP_COUNTS) - 1)
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key == readchar.key.DOWN:
            step_count_idx = max(step_count_idx - 1, 0)
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key == "\t":
            selected_idx = (selected_idx + 1) % len(stepper_names)
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key == readchar.key.ENTER:
            stepper.position_degrees = 0.0
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
            print(f"Zeroed {name} position")
        elif key in "1234":
            layer_idx: int = int(key) - 1
            if layer_idx < len(servos):
                servos[layer_idx].toggle()
                printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key.lower() == "s":
            servo_calibrate_loop(servos)
            printStatus(steppers, stepper_names, selected_idx, step_count_idx, servos)
        elif key.lower() == "q":
            print("Exiting...")
            for s in steppers.values():
                s.enabled = False
            sys.exit(0)


if __name__ == "__main__":
    main()
