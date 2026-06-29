"""Resolve cameras to their current OpenCV capture index by stable identity.

Power cycles can reorder camera indices, so storing a fixed `cv2.VideoCapture` index per
role is unreliable. Instead we record each camera's stable identity (product name + USB-port
location) at assignment time and re-resolve the current index every startup.

Linux/V4L2 only: `cv2.VideoCapture(N)` opens `/dev/videoN`, so the index is the video node
number. We read the product name from `/sys/class/video4linux/videoN/name` and the USB port
from the device symlink. Identity matching is name-first with a location tiebreaker (product
names are not unique here — e.g. two "USB Camera" units — so the per-port location
disambiguates and survives power cycles as long as each camera stays in the same USB port).
"""

import glob
import os
from typing import Optional


class CameraInfo:
    def __init__(self, index: int, name: str, location: str):
        self.index = index          # cv2.VideoCapture index (== /dev/videoN)
        self.name = name            # product name from sysfs
        self.location = location    # stable per-USB-port id

    def identity(self) -> dict:
        return {"name": self.name, "location": self.location, "index": self.index}

    def __repr__(self) -> str:
        return f"CameraInfo(index={self.index}, name={self.name!r}, location={self.location!r})"


def enumerate_cameras() -> list[CameraInfo]:
    """Current cameras with their cv2 index, product name, and stable USB location."""
    infos: list[CameraInfo] = []
    for path in sorted(
        glob.glob("/sys/class/video4linux/video*"),
        key=lambda p: int(p.rsplit("video", 1)[1]),
    ):
        try:
            n = int(path.rsplit("video", 1)[1])
        except ValueError:
            continue
        try:
            with open(os.path.join(path, "name")) as f:
                name = f.read().strip()
        except OSError:
            name = ""
        # Stable USB-port location from the device symlink (e.g. "1-2.3:1.0").
        loc = ""
        try:
            loc = os.path.basename(os.path.realpath(os.path.join(path, "device")))
        except OSError:
            pass
        infos.append(CameraInfo(n, name, loc))
    return infos


def camera_identity_for_index(index: int, infos: "list[CameraInfo] | None" = None) -> "dict | None":
    """Identity dict for the camera currently at the given cv2 index, recorded when a role
    is assigned in the Setup wizard."""
    if infos is None:
        infos = enumerate_cameras()
    for c in infos:
        if c.index == index:
            return c.identity()
    return None


def resolve_camera_index(identity, infos: "list[CameraInfo] | None" = None) -> Optional[int]:
    """Current cv2 index for a stored identity, or None if it can't be resolved.

    Order of preference:
      1. legacy plain-int identity -> return as-is (can't resolve by name).
      2. fast path: the last-known index still holds a matching camera.
      3. exact name + location match.
      4. unique name match.
      5. location-only match.
    """
    if isinstance(identity, int):
        return identity
    if not isinstance(identity, dict):
        return None
    if infos is None:
        infos = enumerate_cameras()

    name = identity.get("name")
    loc = identity.get("location")
    last = identity.get("index")

    def matches(c: CameraInfo) -> bool:
        if name and loc:
            return c.name == name and c.location == loc
        if loc:
            return c.location == loc
        if name:
            return c.name == name
        return False

    if last is not None:
        for c in infos:
            if c.index == last and matches(c):
                return last
    if name and loc:
        for c in infos:
            if c.name == name and c.location == loc:
                return c.index
    if name:
        named = [c for c in infos if c.name == name]
        if len(named) == 1:
            return named[0].index
    if loc:
        located = [c for c in infos if c.location == loc]
        if len(located) == 1:
            return located[0].index
    return None


def resolve_camera_setup(logger=None) -> dict:
    """Read the saved camera setup and return role -> current cv2 index.

    Resolves each role's stored identity to the live index, falling back to the stored
    index (with a warning) when resolution fails. Roles that can't be resolved at all are
    omitted.
    """
    from blob_manager import get_camera_setup

    raw = get_camera_setup() or {}
    infos = enumerate_cameras()

    def _warn(msg: str) -> None:
        if logger is not None:
            logger.warn(msg)
        else:
            print(f"[camera_resolver] {msg}")

    def _stored(identity):
        if isinstance(identity, int):
            return identity
        if isinstance(identity, dict):
            return identity.get("index")
        return None

    if not infos:
        return {role: _stored(i) for role, i in raw.items() if _stored(i) is not None}

    resolved: dict[str, int] = {}
    for role, identity in raw.items():
        idx = resolve_camera_index(identity, infos)
        if idx is not None:
            resolved[role] = idx
            continue
        fallback = _stored(identity)
        if fallback is not None:
            _warn(
                f"camera '{role}' could not be resolved by identity ({identity}); "
                f"falling back to stored index {fallback}. Re-assign cameras in Setup "
                f"if the wrong camera opens."
            )
            resolved[role] = fallback
        else:
            _warn(f"camera '{role}' could not be resolved and has no stored index; skipping.")
    return resolved
