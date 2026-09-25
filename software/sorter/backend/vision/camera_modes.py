"""What a USB camera can capture, and the mode it runs in until someone picks one.

Three cameras share one USB 2.0 bus on the Orange Pi. Uncompressed YUYV at any
real resolution fills that bus by itself, so a camera nobody configured runs
MJPEG at its own resolution: 4K on a 4K camera, 720p on the rest.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

FOURK = (3840, 2160)
HD = (1280, 720)
TARGET_FPS = 30


def list_v4l2_modes(source: int) -> list[dict[str, Any]]:
    """Enumerate (fourcc, width, height, fps) tuples for /dev/videoN.

    Parses `v4l2-ctl --list-formats-ext` output. Returns one entry per
    unique (fourcc, width, height, fps) combination. Empty list on failure.
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", "--list-formats-ext"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    seen: set[tuple[str, int, int, int]] = set()
    modes: list[dict[str, Any]] = []
    current_fourcc: str | None = None
    current_size: tuple[int, int] | None = None
    fmt_pat = re.compile(r"\]\s*:\s*'([A-Za-z0-9]{4})'")
    size_pat = re.compile(r"Size:\s*Discrete\s+(\d+)x(\d+)")
    interval_pat = re.compile(r"\(\s*([0-9.]+)\s*fps\s*\)")

    for raw in result.stdout.splitlines():
        line = raw.strip()
        m = fmt_pat.search(line)
        if m:
            current_fourcc = m.group(1).upper()
            current_size = None
            continue
        m = size_pat.search(line)
        if m and current_fourcc is not None:
            current_size = (int(m.group(1)), int(m.group(2)))
            continue
        m = interval_pat.search(line)
        if m and current_fourcc is not None and current_size is not None:
            try:
                fps_val = int(round(float(m.group(1))))
            except ValueError:
                continue
            key = (current_fourcc, current_size[0], current_size[1], fps_val)
            if key not in seen:
                seen.add(key)
                modes.append({
                    "width": current_size[0],
                    "height": current_size[1],
                    "fps": fps_val,
                    "fourcc": current_fourcc,
                    "native_fourcc": current_fourcc,
                })

    return modes


def default_capture_mode(modes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """MJPEG at 3840x2160 if the camera has it, else 1280x720, else the largest
    MJPEG mode under 720p; 30 fps where offered. None when there is no MJPEG."""
    mjpeg = [m for m in modes if str(m.get("fourcc", "")).upper() == "MJPG"]
    if not mjpeg:
        return None

    def size(m: dict[str, Any]) -> tuple[int, int]:
        return (int(m["width"]), int(m["height"]))

    sizes = {size(m) for m in mjpeg}
    if FOURK in sizes:
        chosen = FOURK
    elif HD in sizes:
        chosen = HD
    else:
        small = [s for s in sizes if s[0] * s[1] <= HD[0] * HD[1]]
        chosen = max(small, key=lambda s: s[0] * s[1]) if small else min(sizes, key=lambda s: s[0] * s[1])
    rates = sorted(int(m["fps"]) for m in mjpeg if size(m) == chosen)
    at_most = [r for r in rates if r <= TARGET_FPS]
    fps = TARGET_FPS if TARGET_FPS in rates else (at_most[-1] if at_most else rates[0])
    return {"width": chosen[0], "height": chosen[1], "fps": fps, "fourcc": "MJPG"}
