from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import sys
import readchar
from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface

STEP_COUNTS = [1, 10, 50, 100, 200, 500, 750, 1000, 1500, 2000]


def main():
    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)

    steppers = {
        "carousel": irl.carousel_stepper,
        "c_channel_1": irl.first_c_channel_rotor_stepper,
        "c_channel_2": irl.second_c_channel_rotor_stepper,
        "c_channel_3": irl.third_c_channel_rotor_stepper,
    }
    if irl.chute_stepper is not None:
        steppers["chute"] = irl.chute_stepper
    stepper_names = list(steppers.keys())
    selected_idx = 0
    step_count_idx = 1

    def printStatus():
        name = stepper_names[selected_idx]
        stepper = steppers[name]
        step_count = STEP_COUNTS[step_count_idx]
        quarter_degrees = 90
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
        for i, (layer, servo) in enumerate(
            zip(irl.distribution_layout.layers, irl.servos)
        ):
            state = "open" if servo.isOpen() else "closed"
            print(
                f"  {i + 1}       Toggle layer {i} servo (pin {layer.servo_pin}, currently {state} at {servo.current_angle}°)"
            )
        print()
        print("  Q       Quit")
        print()

    printStatus()

    while True:
        key = readchar.readkey()
        name = stepper_names[selected_idx]
        stepper = steppers[name]
        step_count = STEP_COUNTS[step_count_idx]

        if key == readchar.key.LEFT:
            stepper.move_degrees(-stepper.degrees_for_microsteps(step_count))
            printStatus()
        elif key == readchar.key.RIGHT:
            stepper.move_degrees(stepper.degrees_for_microsteps(step_count))
            printStatus()
        elif key.lower() == "a":
            stepper.move_degrees(-90)
            printStatus()
        elif key.lower() == "d":
            stepper.move_degrees(90)
            printStatus()
        elif key == readchar.key.UP:
            step_count_idx = min(step_count_idx + 1, len(STEP_COUNTS) - 1)
            printStatus()
        elif key == readchar.key.DOWN:
            step_count_idx = max(step_count_idx - 1, 0)
            printStatus()
        elif key == "\t":
            selected_idx = (selected_idx + 1) % len(stepper_names)
            printStatus()
        elif key == readchar.key.ENTER:
            stepper.position_degrees = 0.0
            printStatus()
            print(f"Zeroed {name} position")
        elif key in "1234":
            layer_idx = int(key) - 1
            if layer_idx < len(irl.servos):
                irl.servos[layer_idx].toggle()
                printStatus()
        elif key.lower() == "q":
            print("Exiting...")
            for s in steppers.values():
                s.enabled = False
            sys.exit(0)


if __name__ == "__main__":
    main()
