from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import subprocess
import sys

import cv2

try:
    from cv2_enumerate_cameras import enumerate_cameras
except Exception:
    enumerate_cameras = None


@dataclass(frozen=True)
class MacOSCameraInfo:
    index: int
    name: str
    path: str | None
    vid: int | None
    pid: int | None
    backend: int
    location_id: int | None

    @property
    def is_usb(self) -> bool:
        return self.vid is not None and self.pid is not None and self.location_id is not None

    @property
    def is_virtual(self) -> bool:
        normalized = self.name.lower()
        return "virtual" in normalized


def parse_macos_location_id(path: str | None) -> int | None:
    if not path or not isinstance(path, str):
        return None
    normalized = path.strip()
    if not normalized.startswith("0x"):
        return None
    hex_digits = normalized[2:]
    if len(hex_digits) < 16:
        return None
    try:
        return int(hex_digits[:8], 16)
    except ValueError:
        return None


def _camera_from_payload(payload: dict) -> MacOSCameraInfo:
    path = payload.get("path")
    return MacOSCameraInfo(
        index=int(payload.get("index", -1)),
        name=str(payload.get("name", "Camera")),
        path=path if isinstance(path, str) else None,
        vid=int(payload["vid"]) if payload.get("vid") is not None else None,
        pid=int(payload["pid"]) if payload.get("pid") is not None else None,
        backend=int(payload.get("backend", cv2.CAP_AVFOUNDATION)),
        location_id=parse_macos_location_id(path if isinstance(path, str) else None),
    )


def _enumerate_macos_cameras_subprocess() -> tuple[MacOSCameraInfo, ...]:
    if enumerate_cameras is None:
        return ()

    helper = """
import json
import cv2
from cv2_enumerate_cameras import enumerate_cameras

cameras = []
for camera in enumerate_cameras(cv2.CAP_AVFOUNDATION):
    cameras.append({
        "index": int(getattr(camera, "index", -1)),
        "name": str(getattr(camera, "name", "Camera")),
        "path": getattr(camera, "path", None),
        "vid": getattr(camera, "vid", None),
        "pid": getattr(camera, "pid", None),
        "backend": int(getattr(camera, "backend", cv2.CAP_AVFOUNDATION)),
    })
print(json.dumps(cameras))
"""

    try:
        result = subprocess.run(
            [sys.executable, "-c", helper],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        )
    except Exception:
        return ()

    stdout = result.stdout.strip()
    if not stdout:
        return ()

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return ()

    if not isinstance(payload, list):
        return ()

    cameras: list[MacOSCameraInfo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            cameras.append(_camera_from_payload(item))
        except Exception:
            continue
    return tuple(cameras)


def _enumerate_macos_cameras_in_process() -> tuple[MacOSCameraInfo, ...]:
    if enumerate_cameras is None:
        return ()

    cameras: list[MacOSCameraInfo] = []
    try:
        enumerated = enumerate_cameras(cv2.CAP_AVFOUNDATION)
    except Exception:
        return ()

    for camera in enumerated:
        path = getattr(camera, "path", None)
        cameras.append(
            MacOSCameraInfo(
                index=int(getattr(camera, "index", -1)),
                name=str(getattr(camera, "name", f"Camera {len(cameras)}")),
                path=path if isinstance(path, str) else None,
                vid=int(getattr(camera, "vid", 0)) if getattr(camera, "vid", None) is not None else None,
                pid=int(getattr(camera, "pid", 0)) if getattr(camera, "pid", None) is not None else None,
                backend=int(getattr(camera, "backend", cv2.CAP_AVFOUNDATION)),
                location_id=parse_macos_location_id(path if isinstance(path, str) else None),
            )
        )

    return tuple(cameras)


@lru_cache(maxsize=1)
def enumerate_macos_cameras() -> tuple[MacOSCameraInfo, ...]:
    cameras = _enumerate_macos_cameras_subprocess()
    if cameras:
        return cameras
    return _enumerate_macos_cameras_in_process()


_ENUM_TTL_S = 30.0
_last_enum_time: float = 0.0


def refresh_macos_cameras(*, force: bool = False) -> tuple[MacOSCameraInfo, ...]:
    global _last_enum_time
    import time as _time

    now = _time.monotonic()
    if force or (now - _last_enum_time) >= _ENUM_TTL_S:
        enumerate_macos_cameras.cache_clear()
        _last_enum_time = now
    return enumerate_macos_cameras()


def get_macos_camera(index: int) -> MacOSCameraInfo | None:
    return next((camera for camera in enumerate_macos_cameras() if camera.index == index), None)
