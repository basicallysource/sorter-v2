"""
Reproduce the camera cold-start power transient that causes Pi brownouts.

Run from the backend directory on the Pi:

    cd ~/sorter-v2/software/sorter/backend
    uv run python scripts/camera_coldstart_probe.py
    uv run python scripts/camera_coldstart_probe.py --indices 0 2 4
    uv run python scripts/camera_coldstart_probe.py --delay 0.5   # stagger opens by 0.5s each
    uv run python scripts/camera_coldstart_probe.py --duration 5  # stream for 5s per cam

Opens every detected capture camera simultaneously in parallel threads, each using
MJPG via _open_capture_source — the same path taken by CaptureThread in the live
camera service. STREAMON fires on the first cap.read(), so all threads blocking on
that read at the same time is what spikes the 5V rail.

The existing camera_format_probe.py --multi test does NOT reproduce the brownout
because it serializes the STREAMON calls (opens all caps then reads sequentially).
This script fires all STREAMON calls in parallel, matching the live assign flow.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

import cv2


def _runCmd(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (out.stdout or "") + (out.stderr or "")
    except Exception as e:
        return f"<error: {e}>"


def listCaptureDevices() -> list[tuple[int, str]]:
    devices: list[tuple[int, str]] = []
    for i in range(16):
        path = f"/dev/video{i}"
        info = _runCmd(["v4l2-ctl", "-d", path, "--info"])
        if "Video Capture" not in info:
            continue
        formats = _runCmd(["v4l2-ctl", "-d", path, "--list-formats"])
        if not re.search(r"\[\d+\]:", formats):
            continue
        m = re.search(r"Card type\s*:\s*(.+)", info)
        name = m.group(1).strip() if m else "?"
        devices.append((i, name))
    return devices


def _tryV4l2ctlSetFormat(source: int, fourcc: str) -> None:
    try:
        subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{source}", "--set-fmt-video", f"pixelformat={fourcc}"],
            capture_output=True,
            timeout=3,
        )
    except Exception:
        pass


def _openCapture(source: int, fourcc: str = "MJPG") -> cv2.VideoCapture:
    """Mirror of vision.camera._open_capture_source for Linux."""
    _tryV4l2ctlSetFormat(source, fourcc)
    params: list[int] = [
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(*fourcc.upper()),
    ]
    try:
        return cv2.VideoCapture(source, cv2.CAP_V4L2, params)
    except Exception:
        return cv2.VideoCapture(source)


@dataclass
class CamResult:
    index: int
    name: str
    open_ok: bool = False
    first_frame_ok: bool = False
    frames_read: int = 0
    open_ms: float = 0.0
    first_frame_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


def _camWorker(
    index: int,
    name: str,
    start_event: threading.Event,
    result: CamResult,
    duration: float,
    delay: float,
) -> None:
    if delay > 0:
        time.sleep(delay)

    t_open = time.monotonic()
    cap = _openCapture(index)
    result.open_ms = (time.monotonic() - t_open) * 1000

    if not cap.isOpened():
        cap.release()
        result.errors.append("open() failed")
        return
    result.open_ok = True

    # Wait for all threads to be ready, then all call cap.read() at the same time.
    # This fires STREAMON simultaneously across all cameras — the power spike.
    start_event.wait()

    t_first = time.monotonic()
    try:
        ret, frame = cap.read()
        result.first_frame_ms = (time.monotonic() - t_first) * 1000
        if ret and frame is not None:
            result.first_frame_ok = True
            result.frames_read = 1
        else:
            result.errors.append("first read() returned no frame")
    except Exception as e:
        result.errors.append(f"first read() raised: {e}")
        cap.release()
        return

    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            ret, frame = cap.read()
            if ret and frame is not None:
                result.frames_read += 1
            else:
                result.errors.append("read() returned no frame mid-stream")
                break
        except Exception as e:
            result.errors.append(f"read() raised mid-stream: {e}")
            break

    cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel camera cold-start probe (brownout reproducer)")
    parser.add_argument(
        "--indices",
        nargs="+",
        type=int,
        default=None,
        help="Camera /dev/videoN indices to open. Defaults to all detected capture devices.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds between each camera open (0 = all simultaneous, which is the crash trigger).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        help="Seconds to keep each camera streaming after first frame (default 8s).",
    )
    parser.add_argument(
        "--fourcc",
        default="MJPG",
        help="Pixel format to request (default MJPG, same as camera service).",
    )
    args = parser.parse_args()

    if args.indices:
        devices = [(i, f"/dev/video{i}") for i in args.indices]
    else:
        devices = listCaptureDevices()

    if not devices:
        print("No capture devices found. Are cameras plugged in and v4l2-ctl installed?")
        return 1

    print(f"Cameras to open ({len(devices)}):")
    for idx, name in devices:
        print(f"  /dev/video{idx}  {name}")

    print(f"\nUSB topology:")
    print(_runCmd(["lsusb", "-t"]))

    print(
        f"Opening {len(devices)} camera(s) in parallel"
        + (f" with {args.delay}s stagger" if args.delay > 0 else " simultaneously (brownout trigger)")
        + f", streaming {args.duration}s each, fourcc={args.fourcc}"
    )
    print("If the Pi goes offline from here, that's a brownout.\n")

    results = [CamResult(index=idx, name=name) for idx, name in devices]
    start_event = threading.Event()
    threads: list[threading.Thread] = []

    for i, (result, (idx, name)) in enumerate(zip(results, devices)):
        t = threading.Thread(
            target=_camWorker,
            args=(idx, name, start_event, result, args.duration, args.delay * i),
            daemon=True,
        )
        threads.append(t)

    t_launch = time.monotonic()
    for t in threads:
        t.start()

    # Brief pause so all threads are in _openCapture before the start gun.
    time.sleep(0.1 + args.delay * len(devices))
    start_event.set()
    print(f"  [t+{(time.monotonic() - t_launch)*1000:.0f}ms] STREAMON fired — all threads unblocked\n")

    for t in threads:
        t.join()

    elapsed = time.monotonic() - t_launch
    print(f"Done in {elapsed:.1f}s. Results:\n")

    all_ok = True
    for r in results:
        status = "OK" if r.first_frame_ok else "FAIL"
        err_str = "  errors: " + "; ".join(r.errors) if r.errors else ""
        print(
            f"  /dev/video{r.index} ({r.name}): {status}"
            f"  open={r.open_ms:.0f}ms"
            f"  first_frame={r.first_frame_ms:.0f}ms"
            f"  frames={r.frames_read}"
            f"{err_str}"
        )
        if not r.first_frame_ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
