import os
import shlex
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT_DIR_PATH = os.getenv(
    "REPO_ROOT_DIR_PATH",
    str(Path(__file__).resolve().parents[2]),
)
ROOT_DIR = Path(REPO_ROOT_DIR_PATH)
CLIENT_DIR = ROOT_DIR / "software" / "client"
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from irl.device_discovery import promptForDevice
from utils.pick_menu import pickMenu

FIRMWARE_OPTIONS = {
    "firmware/feeder/feeder.ino": ROOT_DIR
    / "software"
    / "firmware"
    / "feeder"
    / "feeder.ino",
}

ARDUINO_FQBN = os.getenv("ARDUINO_FQBN", "arduino:avr:mega")
AVRDUDE_MCU = os.getenv("AVRDUDE_MCU", "atmega2560")
AVRDUDE_PROGRAMMER = os.getenv("AVRDUDE_PROGRAMMER", "wiring")
AVRDUDE_BAUD = os.getenv("AVRDUDE_BAUD", "115200")
AVRDUDE_EXTRA_ARGS = os.getenv("AVRDUDE_EXTRA_ARGS", "")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def pickFirmware() -> Path:
    options = list(FIRMWARE_OPTIONS.keys())
    choice_index = pickMenu(options)
    if choice_index is None:
        print("Selection cancelled")
        sys.exit(1)
    return FIRMWARE_OPTIONS[options[choice_index]]


def findHexFile(build_dir: Path) -> Path:
    hex_files = sorted(build_dir.glob("*.hex"))
    if not hex_files:
        raise FileNotFoundError("No .hex output found after compile")
    for hex_path in hex_files:
        if not hex_path.name.endswith(".with_bootloader.hex"):
            return hex_path
    return hex_files[0]


def compileSketch(sketch_path: Path, build_dir: Path) -> Path:
    cmd = [
        "arduino-cli",
        "compile",
        "--fqbn",
        ARDUINO_FQBN,
        "--output-dir",
        str(build_dir),
        str(sketch_path.parent),
    ]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Compile failed: "
            + " ".join(shlex.quote(part) for part in cmd)
            + f"\n{result.stderr.strip()}"
        )
    return findHexFile(build_dir)


def uploadHex(hex_path: Path, port: str) -> None:
    extra_args = shlex.split(AVRDUDE_EXTRA_ARGS) if AVRDUDE_EXTRA_ARGS else []
    cmd = [
        "avrdude",
        "-p",
        AVRDUDE_MCU,
        "-c",
        AVRDUDE_PROGRAMMER,
        "-P",
        port,
        "-b",
        AVRDUDE_BAUD,
        "-D",
        "-U",
        f"flash:w:{hex_path}:i",
        *extra_args,
    ]
    result = run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Upload failed: "
            + " ".join(shlex.quote(part) for part in cmd)
            + f"\n{result.stderr.strip()}"
        )


def main() -> int:
    port = promptForDevice("MCU", "MCU_PATH")
    sketch_path = pickFirmware()

    with TemporaryDirectory() as tmp_dir:
        build_dir = Path(tmp_dir)
        hex_path = compileSketch(sketch_path, build_dir)
        uploadHex(hex_path, port)

    print("Upload complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
