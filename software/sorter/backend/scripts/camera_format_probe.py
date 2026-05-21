"""
Diagnostic for USB camera bandwidth issues.

Run from the backend directory on the Pi (it needs cv2 from the backend venv):

    cd ~/sorter-v2/software/sorter/backend
    uv run python scripts/camera_format_probe.py            # per-cam probe
    uv run python scripts/camera_format_probe.py --multi    # also try all cams simultaneously

For each /dev/videoN that is a capture device:
  - dumps v4l2 supported formats
  - opens with cv2 three ways (no fourcc, force MJPG, force YUYV) at 1920x1080@30
  - reports the fourcc / resolution / fps that actually got negotiated, and whether a frame was readable
  - estimates bandwidth (bits/s) for the negotiated mode

`--multi` opens every capture-capable cam at once in MJPG @ 1920x1080@30 and reports
which combinations the USB controller can actually sustain. This is the test that
distinguishes "we're requesting the wrong pixel format" from "we're physically out
of USB iso bandwidth."
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

import cv2

VIDEO_GLOB = [f"/dev/video{i}" for i in range(16)]


@dataclass
class CapResult:
    label: str
    fourcc: str
    width: int
    height: int
    fps: float
    frame_ok: bool
    open_ms: float
    err: Optional[str] = None


def fourccToStr(value: float | int) -> str:
    v = int(value)
    if v <= 0:
        return "----"
    return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))


def runCmd(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (out.stdout or "") + (out.stderr or "")
    except Exception as e:
        return f"<error: {e}>"


def listCaptureDevices() -> list[tuple[int, str]]:
    devices: list[tuple[int, str]] = []
    for path in VIDEO_GLOB:
        info = runCmd(["v4l2-ctl", "-d", path, "--info"])
        if "Video Capture" not in info:
            continue
        # UVC cams expose a metadata sub-device (e.g. video1) alongside the real capture node.
        # Both report "Video Capture" in --info but only the real node lists pixel formats.
        formats = runCmd(["v4l2-ctl", "-d", path, "--list-formats"])
        if not re.search(r"\[\d+\]:", formats):
            continue
        m = re.search(r"Card type\s*:\s*(.+)", info)
        name = m.group(1).strip() if m else "?"
        idx = int(path.rsplit("video", 1)[1])
        devices.append((idx, name))
    return devices


def dumpFormats(path: str) -> str:
    raw = runCmd(["v4l2-ctl", "-d", path, "--list-formats-ext"])
    lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") or s.startswith("Pixel Format") or s.startswith("Size:") or s.startswith("Interval:"):
            lines.append("    " + s)
    return "\n".join(lines)


def probeOne(index: int, fourcc: Optional[str], width: int, height: int, fps: int, label: str) -> CapResult:
    t0 = time.monotonic()
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        return CapResult(label, "----", 0, 0, 0.0, False, (time.monotonic() - t0) * 1000, "open failed")

    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc.upper()))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    actual_fourcc = fourccToStr(cap.get(cv2.CAP_PROP_FOURCC))
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    err: Optional[str] = None
    frame_ok = False
    try:
        ret, frame = cap.read()
        if ret and frame is not None:
            frame_ok = True
            actual_h, actual_w = frame.shape[:2]
        else:
            err = "read returned no frame"
    except Exception as e:
        err = f"read raised: {e}"
    finally:
        cap.release()

    return CapResult(label, actual_fourcc, actual_w, actual_h, actual_fps, frame_ok, (time.monotonic() - t0) * 1000, err)


def estimateBandwidthBitsPerSec(fourcc: str, w: int, h: int, fps: float) -> float:
    if w <= 0 or h <= 0 or fps <= 0:
        return 0.0
    if fourcc.upper() == "MJPG":
        # MJPEG: rough average ~0.3 bits/pixel after compression on typical webcam content
        return w * h * fps * 0.3
    # YUYV / YUY2 / others: 16 bpp uncompressed
    return w * h * fps * 16.0


def fmtMbps(bits_per_sec: float) -> str:
    return f"{bits_per_sec / 1e6:7.1f} Mbps"


def reportOne(idx: int, name: str) -> None:
    print(f"\n=== /dev/video{idx}  ({name}) ===")
    print("  v4l2 advertised formats:")
    fmts = dumpFormats(f"/dev/video{idx}")
    print(fmts if fmts else "    <none>")

    print("  cv2 negotiation @ 1920x1080@30:")
    for label, fourcc in (("default ", None), ("MJPG    ", "MJPG"), ("YUYV    ", "YUYV")):
        r = probeOne(idx, fourcc, 1920, 1080, 30, label)
        bw = estimateBandwidthBitsPerSec(r.fourcc, r.width, r.height, r.fps)
        ok = "OK " if r.frame_ok else "no frame"
        err = f"  ({r.err})" if r.err else ""
        print(
            f"    request={r.label} -> got fourcc={r.fourcc} {r.width}x{r.height}@{r.fps:>4.1f}  "
            f"~{fmtMbps(bw)}  {ok}  open={r.open_ms:5.0f}ms{err}"
        )


def reportSimultaneous(indices: list[int], fourcc: str, width: int, height: int, fps: int) -> None:
    print(f"\n=== Simultaneous open: {len(indices)} cams @ {width}x{height}@{fps} fourcc={fourcc} ===")
    caps: list[tuple[int, cv2.VideoCapture, str]] = []
    for idx in indices:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f"  /dev/video{idx}: open failed")
            cap.release()
            caps.append((idx, cap, "open-failed"))
            continue
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc.upper()))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        caps.append((idx, cap, "open"))

    # Try to read one frame from each; STREAMON fires on first read.
    total_bw = 0.0
    for idx, cap, status in caps:
        if status == "open-failed":
            continue
        try:
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                got_fourcc = fourccToStr(cap.get(cv2.CAP_PROP_FOURCC))
                got_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                bw = estimateBandwidthBitsPerSec(got_fourcc, w, h, got_fps)
                total_bw += bw
                print(f"  /dev/video{idx}: OK  fourcc={got_fourcc} {w}x{h}@{got_fps:.1f}  ~{fmtMbps(bw)}")
            else:
                print(f"  /dev/video{idx}: STREAMON failed (no frame)")
        except Exception as e:
            print(f"  /dev/video{idx}: read raised {e}")

    print(f"  total estimated bandwidth: ~{fmtMbps(total_bw)}  (USB 2.0 bus ceiling ~340 Mbps practical / 480 Mbps nominal)")

    for _, cap, _ in caps:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--multi", action="store_true", help="also open all capture-capable cams simultaneously in MJPG")
    parser.add_argument("--multi-fourcc", default="MJPG")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    devices = listCaptureDevices()
    if not devices:
        print("No /dev/video* capture devices found. Is v4l2-ctl installed and are cameras plugged in?")
        return 1

    print("Capture devices:")
    for idx, name in devices:
        print(f"  /dev/video{idx:<2}  {name}")

    # USB bus topology — useful when the bandwidth math doesn't add up.
    print("\nUSB topology (relevant for bandwidth ceilings):")
    print(runCmd(["lsusb", "-t"]))

    for idx, name in devices:
        reportOne(idx, name)

    if args.multi:
        reportSimultaneous([i for i, _ in devices], args.multi_fourcc, args.width, args.height, args.fps)

    return 0


if __name__ == "__main__":
    sys.exit(main())
