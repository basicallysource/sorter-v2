from dotenv import load_dotenv
from pathlib import Path
import sys

CLIENT_ROOT = Path(__file__).resolve().parent.parent
if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))

load_dotenv(CLIENT_ROOT / ".env")

import time
import argparse

from irl.device_discovery import discoverMCU
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cycle steppers by UART/channel address order (0,1,2,3)."
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=800,
        help="Microsteps/sec while active (default: 800)",
    )
    parser.add_argument(
        "--run-seconds",
        type=float,
        default=1.0,
        help="How long each motor runs (default: 1.0s)",
    )
    parser.add_argument(
        "--between-seconds",
        type=float,
        default=3.0,
        help="Pause between motors (default: 3.0s)",
    )
    parser.add_argument(
        "--loop-wait-seconds",
        type=float,
        default=10.0,
        help="Pause after channel 3 before repeating (default: 10.0s)",
    )
    parser.add_argument(
        "--forward",
        action="store_true",
        help="Run motors in original direction (default is opposite)",
    )
    args = parser.parse_args()

    mcu_port = discoverMCU()
    bus = MCUBus(port=mcu_port)
    devices = bus.scan_devices()
    if not devices:
        raise RuntimeError(f"No Pico devices found on {mcu_port}")

    sorter_interface = SorterInterface(bus, devices[0])
    steppers = sorter_interface.steppers

    speed = abs(args.speed) if args.forward else -abs(args.speed)

    print(f"Connected on {mcu_port}")
    print(f"Detected {len(steppers)} stepper channels")
    print(
        f"Pattern: run {args.run_seconds}s, pause {args.between_seconds}s, "
        f"loop pause {args.loop_wait_seconds}s"
    )
    print("Order: channel 0 -> 1 -> 2 -> 3")

    try:
        while True:
            for channel in range(4):
                if channel >= len(steppers):
                    print(f"Channel {channel} not available; skipping")
                    continue

                stepper = steppers[channel]
                stepper.enabled = True

                print(f"[CH {channel}] START @ speed {speed}")
                stepper.move_at_speed(speed)
                time.sleep(args.run_seconds)

                stepper.move_at_speed(0)
                print(f"[CH {channel}] STOP")

                if channel < 3:
                    print(f"Pause {args.between_seconds}s")
                    time.sleep(args.between_seconds)

            print(f"Loop pause {args.loop_wait_seconds}s")
            time.sleep(args.loop_wait_seconds)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received. Cleaning up...")
    finally:
        try:
            sorter_interface.shutdown()
        except Exception as e:
            print(f"Interface shutdown error: {e}")

        for _ in range(2):
            for idx, stepper in enumerate(steppers):
                try:
                    stepper.enabled = False
                except Exception as e:
                    print(f"[CH {idx}] disable failed during cleanup: {e}")
            time.sleep(0.05)

        print("Cleanup complete. Exiting.")


if __name__ == "__main__":
    main()
