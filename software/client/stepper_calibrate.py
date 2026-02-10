import sys
import readchar
from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from blob_manager import setStepperPosition

STEP_COUNTS = [1, 10, 50, 100, 200]


def main():
    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)

    steppers = {
        "carousel": irl.carousel_stepper,
        "chute": irl.chute_stepper,
        "c_channel_1": irl.first_c_channel_rotor_stepper,
        "c_channel_2": irl.second_c_channel_rotor_stepper,
        "c_channel_3": irl.third_c_channel_rotor_stepper,
    }
    stepper_names = list(steppers.keys())
    selected_idx = 0
    step_count_idx = 1

    def printStatus():
        name = stepper_names[selected_idx]
        stepper = steppers[name]
        step_count = STEP_COUNTS[step_count_idx]
        quarter_steps = stepper.total_steps_per_rev // 4
        print("\033[2J\033[H", end="")
        print("Stepper Calibration Tool")
        print("========================")
        print(f"Selected: {name} (position: {stepper.current_position_steps} steps)")
        print()
        print("Controls:")
        print(f"  ←/→     Move stepper (current: {step_count} steps)")
        print(f"  ↑/↓     Change step count ({', '.join(map(str, STEP_COUNTS))})")
        print(f"  A/D     Quarter turn ({quarter_steps} steps)")
        print("  Tab     Switch stepper")
        print("  Enter   Set current position as zero")
        print("  Q       Quit")
        print()

    printStatus()

    while True:
        key = readchar.readkey()
        name = stepper_names[selected_idx]
        stepper = steppers[name]
        step_count = STEP_COUNTS[step_count_idx]

        if key == readchar.key.LEFT:
            stepper.moveSteps(-step_count)
            printStatus()
        elif key == readchar.key.RIGHT:
            stepper.moveSteps(step_count)
            printStatus()
        elif key.lower() == "a":
            quarter = stepper.total_steps_per_rev // 4
            stepper.moveSteps(-quarter)
            printStatus()
        elif key.lower() == "d":
            quarter = stepper.total_steps_per_rev // 4
            stepper.moveSteps(quarter)
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
            stepper.current_position_steps = 0
            setStepperPosition(name, 0)
            printStatus()
            print(f"Zeroed {name} position")
        elif key.lower() == "q":
            print("Exiting...")
            for s in steppers.values():
                s.disable()
            sys.exit(0)


if __name__ == "__main__":
    main()
