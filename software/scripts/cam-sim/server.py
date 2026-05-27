"""MJPEG camera simulator.

Reads config.toml to know which cameras to serve and where to find images for
each. Serves each role as a looping MJPEG stream. If the source_dir for a role
doesn't exist or has no images, serves a blank frame.

Usage:
    uv run server.py
    uv run server.py --config /path/to/other/config.toml

Port map:
    feeder               → http://localhost:9000/
    carousel             → http://localhost:9001/
    c_channel_2          → http://localhost:9002/
    c_channel_3          → http://localhost:9003/
    classification_top   → http://localhost:9004/
    classification_channel → http://localhost:9005/
"""

from __future__ import annotations

import argparse
import sys
import time
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-reuse-def]

ROLE_PORTS: dict[str, int] = {
    "feeder":                  9000,
    "carousel":                9001,
    "c_channel_2":             9002,
    "c_channel_3":             9003,
    "classification_top":      9004,
    "classification_channel":  9005,
}

HERE = Path(__file__).parent
DEFAULT_CONFIG = HERE / "config.toml"


@dataclass
class CameraConfig:
    role: str
    source_dir: Path
    fps: float = 30.0
    width: int = 1280
    height: int = 720


def _load_config(path: Path) -> list[CameraConfig]:
    raw = tomllib.loads(path.read_text())
    cameras: list[CameraConfig] = []
    for role, cfg in raw.get("cameras", {}).items():
        if not isinstance(cfg, dict) or "source_dir" not in cfg:
            print(f"[config] skipping {role!r}: missing 'source_dir'", file=sys.stderr)
            continue
        cameras.append(CameraConfig(
            role=role,
            source_dir=Path(cfg["source_dir"]).expanduser(),
            fps=float(cfg.get("fps", 30.0)),
            width=int(cfg.get("width", 1280)),
            height=int(cfg.get("height", 720)),
        ))
    return cameras


def _load_frames(cam: CameraConfig) -> list[bytes]:
    if not cam.source_dir.exists():
        return []
    files = sorted(
        f for f in cam.source_dir.rglob("*")
        if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.is_file()
    )
    frames: list[bytes] = []
    for f in files:
        try:
            if f.suffix.lower() in (".jpg", ".jpeg"):
                frames.append(f.read_bytes())
            else:
                import cv2
                img = cv2.imread(str(f))
                if img is not None:
                    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    frames.append(buf.tobytes())
        except Exception:
            pass
    return frames


def _blank_frame(role: str, width: int = 1280, height: int = 720) -> bytes:
    import cv2
    import numpy as np
    img = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        img, f"[{role}] no frames",
        (40, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 80, 80), 2,
    )
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def _make_handler(frames: list[bytes], frame_delay: float) -> type:
    class _Handler(BaseHTTPRequestHandler):
        _frames = frames
        _delay = frame_delay

        def log_message(self, *_: object) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            i = 0
            try:
                while True:
                    jpg = self._frames[i % len(self._frames)]
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpg)).encode()
                        + b"\r\n\r\n"
                        + jpg
                        + b"\r\n"
                    )
                    self.wfile.flush()
                    time.sleep(self._delay)
                    i += 1
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return _Handler


def _serve(cam: CameraConfig) -> None:
    port = ROLE_PORTS.get(cam.role)
    if port is None:
        print(f"[{cam.role}] unknown role — not in ROLE_PORTS, skipping", file=sys.stderr)
        return

    frames = _load_frames(cam)
    if frames:
        print(f"[{cam.role}] {len(frames)} frame(s) from {cam.source_dir}")
    else:
        print(f"[{cam.role}] no images found at {cam.source_dir} — serving blank")
        frames = [_blank_frame(cam.role, cam.width, cam.height)]

    server = HTTPServer(("0.0.0.0", port), _make_handler(frames, 1.0 / cam.fps))
    server.allow_reuse_address = True
    server.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="MJPEG camera simulator — reads config.toml")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = ap.parse_args()

    if not args.config.exists():
        print(f"config.toml not found at {args.config}", file=sys.stderr)
        print("Copy config.example.toml → config.toml and set source_dir paths.", file=sys.stderr)
        sys.exit(1)

    cameras = _load_config(args.config)
    if not cameras:
        print("No cameras defined in config.toml [cameras.*]", file=sys.stderr)
        sys.exit(1)

    print("\nStarting cameras:")
    for cam in cameras:
        port = ROLE_PORTS.get(cam.role, "???")
        print(f"  {cam.role:<26} http://localhost:{port}/  ({cam.fps} fps)")
    print()

    threads = [
        threading.Thread(target=_serve, args=(cam,), daemon=True)
        for cam in cameras
    ]
    for t in threads:
        t.start()

    print("Press Ctrl+C to stop.")
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
