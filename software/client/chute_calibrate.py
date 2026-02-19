from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import sys
import readchar
from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from subsystems.distribution.chute import BinAddress
from blob_manager import setStepperPosition

STEP_COUNTS = [
    1,
    5,
    10,
    25,
    50,
    75,
    100,
    150,
    200,
    250,
    300,
    400,
    500,
    750,
    1000,
    1500,
    2000,
]


def main():
    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    layout = irl.distribution_layout
    chute = irl.chute
    stepper = irl.chute_stepper

    layer_idx = 0
    section_idx = 0
    bin_idx = 0
    step_count_idx = 2
    manual_mode = False

    layer = layout.layers[layer_idx]
    num_sections = len(layer.sections)

    def getNumBins():
        return len(layer.sections[section_idx].bins)

    def printStatus():
        print("\033[2J\033[H", end="")
        print("Chute Calibration Tool")
        print("======================")
        print(f"Mode: {'MANUAL CONTROL' if manual_mode else 'BIN NAVIGATION'}")
        print(f"Stepper position: {stepper.current_position_steps} steps")
        print(f"Chute angle: {chute.current_angle:.1f}°")
        print()

        if manual_mode:
            step_count = STEP_COUNTS[step_count_idx]
            print(f"Step size: {step_count}")
            print()
            print("Controls:")
            print(f"  ←/→     Move stepper ({step_count} steps)")
            print(f"  ↑/↓     Change step count ({', '.join(map(str, STEP_COUNTS))})")
            print("  H       Move to zero position")
            print("  Z       Set current position as zero")
            print("  Tab     Switch to bin navigation mode")
            print("  Q       Quit")
        else:
            print("Layout (6 sections x 3 bins each):")
            print()
            for s in range(num_sections):
                row = ""
                for b in range(len(layer.sections[s].bins)):
                    if s == section_idx and b == bin_idx:
                        row += "[*] "
                    else:
                        row += "[ ] "
                print(f"  Section {s}: {row}")
            print()
            print(f"Selected: Section {section_idx}, Bin {bin_idx}")
            print()
            print("Controls:")
            print("  ←/→     Change bin within section")
            print("  ↑/↓     Change section")
            print("  Enter   Move chute to selected bin")
            print("  H       Move to zero position")
            print("  Z       Set current position as zero")
            print("  Tab     Switch to manual control mode")
            print("  Q       Quit")
        print()

    printStatus()

    while True:
        key = readchar.readkey()

        if manual_mode:
            step_count = STEP_COUNTS[step_count_idx]
            if key == readchar.key.LEFT:
                stepper.moveSteps(-step_count)
                printStatus()
            elif key == readchar.key.RIGHT:
                stepper.moveSteps(step_count)
                printStatus()
            elif key == readchar.key.UP:
                step_count_idx = min(step_count_idx + 1, len(STEP_COUNTS) - 1)
                printStatus()
            elif key == readchar.key.DOWN:
                step_count_idx = max(step_count_idx - 1, 0)
                printStatus()
            elif key.lower() == "h":
                print("Moving to zero position...")
                chute.home()
                printStatus()
                print(f"Moved to zero (current angle: {chute.current_angle:.1f}°)")
            elif key.lower() == "z":
                stepper.current_position_steps = 0
                setStepperPosition(stepper.name, 0)
                printStatus()
                print("Zeroed stepper and chute angle")
            elif key == "\t":
                manual_mode = False
                printStatus()
            elif key.lower() == "q":
                print("Exiting...")
                stepper.disable()
                sys.exit(0)
        else:
            if key == readchar.key.LEFT:
                bin_idx = (bin_idx - 1) % getNumBins()
                printStatus()
            elif key == readchar.key.RIGHT:
                bin_idx = (bin_idx + 1) % getNumBins()
                printStatus()
            elif key == readchar.key.UP:
                section_idx = (section_idx - 1) % num_sections
                bin_idx = min(bin_idx, getNumBins() - 1)
                printStatus()
            elif key == readchar.key.DOWN:
                section_idx = (section_idx + 1) % num_sections
                bin_idx = min(bin_idx, getNumBins() - 1)
                printStatus()
            elif key == readchar.key.ENTER:
                address = BinAddress(layer_idx, section_idx, bin_idx)
                target_angle = chute.getAngleForBin(address)
                print(
                    f"Moving to section {section_idx}, bin {bin_idx} (angle: {target_angle:.1f}°)..."
                )
                chute.moveToBin(address)
                printStatus()
                print(f"Moved to angle {chute.current_angle:.1f}°")
            elif key.lower() == "h":
                print("Moving to zero position...")
                chute.home()
                printStatus()
                print(f"Moved to zero (current angle: {chute.current_angle:.1f}°)")
            elif key.lower() == "z":
                stepper.current_position_steps = 0
                setStepperPosition(stepper.name, 0)
                printStatus()
                print("Zeroed stepper and chute angle")
            elif key == "\t":
                manual_mode = True
                printStatus()
            elif key.lower() == "q":
                print("Exiting...")
                stepper.disable()
                sys.exit(0)


if __name__ == "__main__":
    main()
