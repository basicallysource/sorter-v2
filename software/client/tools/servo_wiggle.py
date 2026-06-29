import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

dotenv_spec = importlib.util.find_spec("dotenv")
if dotenv_spec is not None:
    dotenv = importlib.util.module_from_spec(dotenv_spec)
    assert dotenv_spec.loader is not None
    dotenv_spec.loader.exec_module(dotenv)
    dotenv.load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface

POLL_INTERVAL_S = 0.01
DEFAULT_SERVO_TIMEOUT_MS = 3000
DEFAULT_SERVO_ACCELERATION = 4000
DEFAULT_SERVO_MIN_SPEED = 100
DEFAULT_SERVO_MAX_SPEED = 2000


def discover_servo_targets(gc) -> list[tuple[str, str, int, object]]:
    targets: list[tuple[str, str, int, object]] = []
    logger = gc.logger
    ports = MCUBus.enumerate_buses()
    if not ports:
        raise RuntimeError("No MCU buses found")

    for port in ports:
        logger.info(f"Servo wiggle loop: scanning SorterInterface devices on {port}")
        bus = MCUBus(port=port)
        devices = bus.scan_devices()
        if not devices:
            logger.warning(f"Servo wiggle loop: no devices found on {port}")
            continue

        for address in devices:
            sorter_interface = SorterInterface(bus, address, gc)
            board_name = sorter_interface.name
            logger.info(
                f"Servo wiggle loop: initialized interface {board_name} on {port} address={address} servos={len(sorter_interface.servos)}"
            )
            for servo in sorter_interface.servos:
                targets.append((port, board_name, address, servo))

    if not targets:
        raise RuntimeError("No servo channels detected on any SorterInterface device")

    return targets


def parse_channels(raw_value: str, max_channels: int) -> set[int] | None:
    if raw_value.strip().lower() == "all":
        return None

    selected: set[int] = set()
    for token in raw_value.split(","):
        token = token.strip()
        if not token:
            continue
        channel = int(token)
        if channel < 0 or channel >= max_channels:
            raise ValueError(f"Servo channel {channel} is out of range 0-{max_channels - 1}")
        selected.add(channel)

    if not selected:
        raise ValueError("--channels did not contain any valid channel numbers")

    return selected


def wait_for_servo_stop(servo, timeout_ms: int, label: str) -> None:
    start = time.monotonic()
    while not servo.stopped:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if elapsed_ms > timeout_ms:
            raise TimeoutError(f"Timed out waiting for servo to stop during: {label}")
        time.sleep(POLL_INTERVAL_S)


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Wiggle each servo one at a time in a loop to validate firmware behavior."
    )
    parser.add_argument(
        "--angle-a",
        type=int,
        default=20,
        help="First wiggle angle in degrees (default: 20)",
    )
    parser.add_argument(
        "--angle-b",
        type=int,
        default=70,
        help="Second wiggle angle in degrees (default: 70)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.25,
        help="Pause after each servo completes a wiggle (default: 0.25)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of full cycles to run (0 means forever)",
    )
    parser.add_argument(
        "--servo-timeout-ms",
        type=int,
        default=DEFAULT_SERVO_TIMEOUT_MS,
        help="Timeout for each servo move completion (default: 3000)",
    )
    parser.add_argument(
        "--dwell-seconds",
        type=float,
        default=0.4,
        help="How long to hold after each target angle is reached (default: 0.4)",
    )
    parser.add_argument(
        "--channels",
        type=str,
        default="all",
        help="Servo channels to test on each servo-capable board, e.g. '0,1,2' or 'all'",
    )
    parser.add_argument(
        "--min-speed",
        type=int,
        default=DEFAULT_SERVO_MIN_SPEED,
        help="Minimum servo speed in tenths of deg/s (default: 100)",
    )
    parser.add_argument(
        "--max-speed",
        type=int,
        default=DEFAULT_SERVO_MAX_SPEED,
        help="Maximum servo speed in tenths of deg/s (default: 2000)",
    )
    parser.add_argument(
        "--acceleration",
        type=int,
        default=DEFAULT_SERVO_ACCELERATION,
        help="Servo acceleration in tenths of deg/s^2 (default: 4000)",
    )
    parser.add_argument(
        "--disable-between-moves",
        action="store_true",
        help="Disable each servo after every wiggle pair (default keeps PWM enabled while testing)",
    )
    parser.add_argument(
        "--hold-angle",
        type=int,
        default=None,
        help="If set, hold each selected channel at this angle (0-180) instead of wiggling",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=0.0,
        help="How long to hold in hold mode (0 means until Ctrl+C)",
    )
    args, remaining_args = parser.parse_known_args()
    return args, remaining_args


def validate_args(args: argparse.Namespace) -> None:
    if not 0 <= args.angle_a <= 180:
        raise ValueError("--angle-a must be between 0 and 180")
    if not 0 <= args.angle_b <= 180:
        raise ValueError("--angle-b must be between 0 and 180")
    if args.angle_a == args.angle_b:
        raise ValueError("--angle-a and --angle-b must be different")
    if args.pause_seconds < 0:
        raise ValueError("--pause-seconds must be >= 0")
    if args.cycles < 0:
        raise ValueError("--cycles must be >= 0")
    if args.servo_timeout_ms <= 0:
        raise ValueError("--servo-timeout-ms must be positive")
    if args.dwell_seconds < 0:
        raise ValueError("--dwell-seconds must be >= 0")
    if args.min_speed < 0 or args.max_speed < 0:
        raise ValueError("--min-speed and --max-speed must be non-negative")
    if args.min_speed >= args.max_speed:
        raise ValueError("--min-speed must be less than --max-speed")
    if args.acceleration <= 0:
        raise ValueError("--acceleration must be positive")
    if args.hold_angle is not None and not 0 <= args.hold_angle <= 180:
        raise ValueError("--hold-angle must be between 0 and 180")
    if args.hold_seconds < 0:
        raise ValueError("--hold-seconds must be >= 0")


def wiggle_servo(
    servo,
    servo_label: str,
    angle_a: int,
    angle_b: int,
    timeout_ms: int,
    dwell_seconds: float,
    min_speed: int,
    max_speed: int,
    acceleration: int,
    disable_between_moves: bool,
    logger,
) -> None:
    servo.enabled = True
    servo.set_speed_limits(min_speed, max_speed)
    servo.set_acceleration(acceleration)

    logger.info(f"Servo wiggle loop: {servo_label} -> angle {angle_a}")
    if not servo.move_to(angle_a):
        raise RuntimeError(f"{servo_label} rejected move to {angle_a}")
    wait_for_servo_stop(servo, timeout_ms, f"{servo_label} move to {angle_a}")
    if dwell_seconds > 0:
        time.sleep(dwell_seconds)

    logger.info(f"Servo wiggle loop: {servo_label} -> angle {angle_b}")
    if not servo.move_to(angle_b):
        raise RuntimeError(f"{servo_label} rejected move to {angle_b}")
    wait_for_servo_stop(servo, timeout_ms, f"{servo_label} move to {angle_b}")
    if dwell_seconds > 0:
        time.sleep(dwell_seconds)

    if disable_between_moves:
        servo.enabled = False


def main() -> None:
    args, remaining_args = parse_args()
    validate_args(args)

    from global_config import make_global_config

    # mkGlobalConfig parses sys.argv for its own flags (e.g. --disable),
    # so pass through only args not consumed by this script.
    original_argv = sys.argv[:]
    try:
        sys.argv = [original_argv[0], *remaining_args]
        gc = make_global_config()
    finally:
        sys.argv = original_argv
    all_targets = discover_servo_targets(gc)
    selected_channels = parse_channels(args.channels, max_channels=16)

    targets = []
    for port, board_name, address, servo in all_targets:
        if selected_channels is not None and servo.channel not in selected_channels:
            continue
        targets.append((port, board_name, address, servo))

    if not targets:
        raise RuntimeError("No servo targets matched the selected channels")

    cycle_count = "infinite" if args.cycles == 0 else str(args.cycles)
    mode = "hold" if args.hold_angle is not None else "wiggle"
    gc.logger.info(
        f"Servo wiggle loop: initialized with raw_servo_targets={len(targets)}, mode={mode}, angles=({args.angle_a},{args.angle_b}), hold_angle={args.hold_angle}, cycles={cycle_count}, channels={args.channels}, disable_between_moves={args.disable_between_moves}"
    )
    gc.logger.info("Servo wiggle loop: running, press Ctrl+C to stop")

    cycle = 0
    try:
        if args.hold_angle is not None:
            for port, board_name, address, servo in targets:
                servo_label = (
                    f"servo channel {servo.channel} on {board_name} ({port} addr={address})"
                )
                servo.enabled = True
                servo.set_speed_limits(args.min_speed, args.max_speed)
                servo.set_acceleration(args.acceleration)
                gc.logger.info(f"Servo wiggle loop: {servo_label} -> hold angle {args.hold_angle}")
                if not servo.move_to(args.hold_angle):
                    raise RuntimeError(f"{servo_label} rejected hold move to {args.hold_angle}")
                wait_for_servo_stop(
                    servo,
                    timeout_ms=args.servo_timeout_ms,
                    label=f"{servo_label} hold move to {args.hold_angle}",
                )

            if args.hold_seconds == 0:
                while True:
                    time.sleep(1.0)
            else:
                end_time = time.monotonic() + args.hold_seconds
                while time.monotonic() < end_time:
                    time.sleep(0.1)
            return

        while args.cycles == 0 or cycle < args.cycles:
            gc.logger.info(f"Servo wiggle loop: starting cycle {cycle}")
            for port, board_name, address, servo in targets:
                servo_label = (
                    f"servo channel {servo.channel} on {board_name} ({port} addr={address})"
                )
                wiggle_servo(
                    servo=servo,
                    servo_label=servo_label,
                    angle_a=args.angle_a,
                    angle_b=args.angle_b,
                    timeout_ms=args.servo_timeout_ms,
                    dwell_seconds=args.dwell_seconds,
                    min_speed=args.min_speed,
                    max_speed=args.max_speed,
                    acceleration=args.acceleration,
                    disable_between_moves=args.disable_between_moves,
                    logger=gc.logger,
                )
                if args.pause_seconds > 0:
                    time.sleep(args.pause_seconds)
            cycle += 1
    except KeyboardInterrupt:
        gc.logger.info("Servo wiggle loop: interrupted by user")
    finally:
        gc.logger.info("Servo wiggle loop: shutting down interfaces")
        for port, board_name, address, servo in targets:
            try:
                servo.enabled = False
            except Exception as exc:
                gc.logger.warning(
                    f"Servo wiggle loop: failed to disable servo channel {servo.channel} on {board_name} ({port} addr={address}): {exc}"
                )


if __name__ == "__main__":
    main()
