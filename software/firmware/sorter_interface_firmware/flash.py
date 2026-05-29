"""OTA flash a Pico board by triggering a bootloader reboot over USB, then copying the UF2."""

import argparse
import glob
import json
import os
import platform
import shutil
import struct
import sys
import time
from zlib import crc32

import serial
import serial.tools.list_ports


PICO_VID = 0x2E8A
PICO_PID = 0x000A
CMD_INIT = 0x00
CMD_REBOOT_BOOTLOADER = 0x02
CMD_GET_VERSION = 0x04


def _cobs_encode(message: bytes) -> bytearray:
    outbuf = bytearray(b"\x01")
    counter_idx = 0
    for mb in message:
        if mb == 0:
            counter_idx = len(outbuf)
        outbuf.append(mb)
        outbuf[counter_idx] += 1
    return outbuf


def _cobs_decode(buff: bytes) -> bytearray:
    msgbuf = bytearray()
    buff = bytearray(buff)
    s = buff.pop(0)
    while buff:
        c = buff.pop(0)
        if c == 0:
            raise ValueError("COBS packet contains zeroes")
        if s == 1:
            msgbuf.append(0)
            s = c
        else:
            msgbuf.append(c)
            s -= 1
    if s > 1:
        raise ValueError("COBS corrupted count")
    return msgbuf


def _build_frame(address: int, command: int, channel: int, payload: bytes) -> bytes:
    header = struct.pack("<BBBB", address, command, channel, len(payload)) + payload
    msg = header + struct.pack("<I", crc32(header) & 0xFFFFFFFF)
    return bytes(_cobs_encode(msg)) + b"\x00"


def _send_recv(ser: serial.Serial, address: int, command: int, channel: int, payload: bytes) -> bytes:
    ser.reset_input_buffer()
    ser.write(_build_frame(address, command, channel, payload))
    resp = ser.read_until(b"\x00", 254)
    if not resp or resp[-1] != 0:
        raise TimeoutError("No response")
    decoded = _cobs_decode(resp[:-1])
    if (crc32(decoded[:-4]) & 0xFFFFFFFF) != struct.unpack("<I", decoded[-4:])[0]:
        raise ValueError("CRC mismatch")
    if decoded[1] & 0x80:
        raise RuntimeError(f"Device error: {decoded[4:-4]}")
    return bytes(decoded[4 : 4 + decoded[3]])


def _enumerate_picos() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports() if p.vid == PICO_VID and p.pid == PICO_PID]


def _identify_board(port: str) -> str | None:
    try:
        with serial.Serial(port, baudrate=576000, timeout=0.5) as ser:
            payload = _send_recv(ser, 0x00, CMD_INIT, 0, b"")
            return json.loads(payload.decode()).get("device_name")
    except Exception:
        return None


def _reboot_to_bootloader(port: str) -> None:
    with serial.Serial(port, baudrate=576000, timeout=0.5) as ser:
        ser.write(_build_frame(0x00, CMD_REBOOT_BOOTLOADER, 0, b""))
        time.sleep(0.1)


LINUX_MOUNT_POINT = "/mnt/rpi-rp2-flash"


def _find_rpi_rp2_blockdev() -> str | None:
    """Return the block device path for RPI-RP2 if present (Linux only)."""
    try:
        import subprocess
        result = subprocess.run(
            ["lsblk", "-o", "NAME,LABEL", "-J"], capture_output=True, text=True
        )
        import json as _json
        data = _json.loads(result.stdout)
        for dev in data.get("blockdevices", []):
            for child in dev.get("children", [dev]):
                if child.get("label") == "RPI-RP2":
                    return f"/dev/{child['name']}"
    except Exception:
        pass
    return None


def _find_rpi_rp2() -> str | None:
    if platform.system() == "Darwin":
        path = "/Volumes/RPI-RP2"
        return path if os.path.isdir(path) else None
    for pattern in ["/media/*/RPI-RP2", "/run/media/*/RPI-RP2", "/mnt/RPI-RP2"]:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    if os.path.ismount(LINUX_MOUNT_POINT):
        return LINUX_MOUNT_POINT
    return None


def _wait_for_mount(timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = _find_rpi_rp2()
        if path:
            return path
        if platform.system() != "Darwin":
            dev = _find_rpi_rp2_blockdev()
            if dev:
                import subprocess
                os.makedirs(LINUX_MOUNT_POINT, exist_ok=True)
                subprocess.run(["mount", dev, LINUX_MOUNT_POINT], check=True)
                return LINUX_MOUNT_POINT
        time.sleep(0.5)
    raise TimeoutError(f"RPI-RP2 did not mount within {timeout:.0f}s")


def _wait_for_unmount(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _find_rpi_rp2_blockdev() is None:
            if platform.system() != "Darwin" and os.path.ismount(LINUX_MOUNT_POINT):
                import subprocess
                subprocess.run(["umount", LINUX_MOUNT_POINT], check=False)
            return
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="OTA flash a Pico board via USB bootloader reboot")
    parser.add_argument("--board", required=True, choices=["feeder", "distribution"])
    parser.add_argument("--uf2", help="Path to .uf2 (default: build-<board>/sorter_interface_firmware.uf2)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    uf2_path = args.uf2 or os.path.join(script_dir, f"build-{args.board}", "sorter_interface_firmware.uf2")
    if not os.path.isfile(uf2_path):
        sys.exit(f"UF2 not found: {uf2_path}")

    target_name = "FEEDER MB" if args.board == "feeder" else "DISTRIBUTION MB"

    # Check if board is already in bootloader mode before scanning serial ports
    if _find_rpi_rp2():
        print(f"RPI-RP2 already mounted in bootloader mode — flashing directly.")
        target_port = None
    elif platform.system() != "Darwin" and _find_rpi_rp2_blockdev():
        print(f"RPI-RP2 block device found (not yet mounted) — flashing directly.")
        target_port = None
    else:
        print("Scanning for Pico boards...")
        ports = _enumerate_picos()
        if not ports:
            sys.exit("No Pico boards found over USB")

        target_port = None
        for port in ports:
            name = _identify_board(port)
            marker = " <-- target" if name == target_name else ""
            print(f"  {port}: {name or '(unresponsive)'}{marker}")
            if name == target_name:
                target_port = port

        if not target_port:
            if platform.system() != "Darwin" and _find_rpi_rp2_blockdev():
                print(f"Board '{target_name}' not found on serial but RPI-RP2 is in bootloader — flashing directly.")
            else:
                sys.exit(f"Board '{target_name}' not found")
        else:
            print(f"Rebooting {target_name} to bootloader...")
            _reboot_to_bootloader(target_port)

    print("Waiting for RPI-RP2 drive...")
    try:
        mount = _wait_for_mount()
    except TimeoutError as e:
        sys.exit(str(e))

    print(f"Flashing {os.path.basename(uf2_path)} -> {mount}/")
    shutil.copy2(uf2_path, mount)

    print("Waiting for board to reboot...")
    _wait_for_unmount()
    print("Done.")


if __name__ == "__main__":
    main()
