from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

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


@lru_cache(maxsize=1)
def enumerate_macos_cameras() -> tuple[MacOSCameraInfo, ...]:
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


def refresh_macos_cameras() -> tuple[MacOSCameraInfo, ...]:
    enumerate_macos_cameras.cache_clear()
    return enumerate_macos_cameras()


def get_macos_camera(index: int) -> MacOSCameraInfo | None:
    return next((camera for camera in enumerate_macos_cameras() if camera.index == index), None)
