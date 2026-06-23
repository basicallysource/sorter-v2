#!/usr/bin/env python3
"""Minimal stepper jog test — drives each motor through the firmware protocol.

This is the software-driven equivalent of the MicroPython spin test: it talks
to the flashed firmware over USB (the custom COBS/CRC protocol) and commands
real moves. Only depends on pyserial (via hardware.bus); no GlobalConfig, no
cameras, no ONNX — so it's a safe first "can the software move the motors?".

Run from the backend directory with the venv active:
    cd software/sorter/backend
    source .venv/bin/activate
    python scripts/jog_test.py            # jog every channel, +/- half a rev
    python scripts/jog_test.py 2          # jog only channel 2 (the C4 carousel)
    python scripts/jog_test.py 0 1.0      # jog channel 0 by +/- 1.0 revolution

Channel order matches the firmware's stepper_names:
    ch0 = second_c_channel_rotor (C2)
    ch1 = third_c_channel_rotor  (C3)
    ch2 = carousel               (C4 classification)
"""

import os
import sys
import struct
import time

# Make the backend package importable no matter where this is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hardware.bus import MCUBus, MCUDevice  # noqa: E402

# Command codes (see hardware/sorter_interface.py InterfaceCommandCode).
STEPPER_MOVE_STEPS = 0x10
STEPPER_IS_STOPPED = 0x14

# Matches the firmware hwcfg: 200 full steps/rev * 1/8 microstepping.
USTEPS_PER_REV = 200 * 8  # 1600


def wait_stopped(dev: MCUDevice, channel: int, timeout: float = 15.0) -> bool:
    """Poll the firmware until the given channel reports stopped (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = dev.send_command(STEPPER_IS_STOPPED, channel, b"")
        if res.payload and res.payload[0]:
            return True
        time.sleep(0.05)
    return False


def jog(dev: MCUDevice, channel: int, revolutions: float) -> None:
    steps = int(round(USTEPS_PER_REV * revolutions))
    res = dev.send_command(STEPPER_MOVE_STEPS, channel, struct.pack("<i", steps))
    acked = bool(res.payload and res.payload[0])
    print(f"    ch{channel}: move {revolutions:+.2f} rev ({steps:+d} microsteps) -> ack={acked}")
    if acked:
        wait_stopped(dev, channel)


def main() -> int:
    only_channel = int(sys.argv[1]) if len(sys.argv) > 1 else None
    revs = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5

    buses = MCUBus.enumerate_buses()
    if not buses:
        print("No board found. Is the Pico plugged in, and is any other program "
              "(Thonny, another script, the backend) holding the serial port open?")
        return 1

    bus = MCUBus(port=buses[0])
    dev = MCUDevice(bus, 0)
    info = dev.detect()
    names = info.get("stepper_names", [])
    print(f"Board: {info.get('device_name')}  steppers: {names}")

    channels = [only_channel] if only_channel is not None else list(range(len(names)))
    for ch in channels:
        if ch < 0 or ch >= len(names):
            print(f"  channel {ch} out of range (board has {len(names)} steppers)")
            continue
        print(f"  Jogging ch{ch} ({names[ch]})")
        jog(dev, ch, revs)        # forward
        time.sleep(0.3)
        jog(dev, ch, -revs)       # back to start
        time.sleep(0.3)

    print("Done. (Motors remain energized/holding; unplug or run the backend to release.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
