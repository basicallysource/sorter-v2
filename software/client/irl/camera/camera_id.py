import platform
import subprocess
import re
from pathlib import Path


def getAllDeviceNames() -> dict[int, str]:
    system = platform.system()
    if system == "Linux":
        devices = {}
        for i in range(20):
            name_file = Path(f"/sys/class/video4linux/video{i}/name")
            if name_file.exists():
                devices[i] = name_file.read_text().strip()
        return devices

    elif system == "Darwin":
        try:
            result = subprocess.run(
                ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True,
                text=True,
                timeout=5,
            )
            devices = {}
            in_video = False
            for line in result.stderr.splitlines():
                if "AVFoundation video devices" in line:
                    in_video = True
                    continue
                if "AVFoundation audio devices" in line:
                    break
                if in_video:
                    m = re.search(r"\[(\d+)\]\s+(.+)", line)
                    if m:
                        devices[int(m.group(1))] = m.group(2).strip()
            return devices
        except Exception:
            return {}

    elif system == "Windows":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-PnpDevice -Class Camera | Select-Object -ExpandProperty FriendlyName",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            names = [
                line.strip() for line in result.stdout.splitlines() if line.strip()
            ]
            return {i: name for i, name in enumerate(names)}
        except Exception:
            return {}

    return {}


def findIndexByName(name: str, exclude: set[int] = set()) -> int | None:
    for index, n in getAllDeviceNames().items():
        if n == name and index not in exclude:
            return index
    return None
