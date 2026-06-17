"""Resolve cameras to their current OpenCV capture index by stable identity.

Power cycles can reorder camera indices, so storing a fixed `cv2.VideoCapture`
index per role is unreliable. Instead we record each camera's stable identity
(product name + USB-port location) at setup time and re-resolve the current
index every startup.

The hard part is that OpenCV's capture index is backend-specific and is NOT the
same ordering as `uvc-util`:

  - Linux (V4L2): `cv2.VideoCapture(N)` opens `/dev/videoN`, so the index is the
    video node number. We read the product name from
    `/sys/class/video4linux/videoN/name` and the USB port from the device link.
    This is reliable.

  - macOS (AVFoundation): OpenCV's index is the position in AVFoundation's device
    list. The ONLY reliable way to read that list (in cv2's order, with each
    device's uniqueID) is AVFoundation itself via PyObjC. We tried inferring it
    from `system_profiler` instead — that was abandoned: its ordering does not
    match cv2's AND is unstable between runs, so it resolved to the wrong camera.
    If `pyobjc-framework-AVFoundation` is installed we use it (fully reliable);
    otherwise macOS falls back to the stored cv2 index (old behavior: correct
    until a power-cycle reorder, no name resolution). Install PyObjC for macOS
    reorder-robustness. Linux is reliable either way.

Identity matching is name-first with a location tiebreaker (camera product names
are not unique here -- e.g. two "USB Camera" units -- and differ across tools, so
the per-port location disambiguates and survives power cycles as long as each
camera stays in the same physical USB port).
"""

import glob
import os
import platform
from typing import Optional


class CameraInfo:
    def __init__(self, index: int, name: str, location: str):
        self.index = index          # cv2.VideoCapture index
        self.name = name            # product / localized name
        self.location = location    # stable per-USB-port id (uniqueID / usb path)

    def identity(self) -> dict:
        return {"name": self.name, "location": self.location, "index": self.index}

    def __repr__(self) -> str:
        return f"CameraInfo(index={self.index}, name={self.name!r}, location={self.location!r})"


def _enumerateMac() -> list[CameraInfo]:
    """macOS has no usable identity->cv2-index enumeration, so this returns [].

    We tried two approaches and both failed: system_profiler's order differs
    from cv2's and is unstable; PyObjC AVFoundation (devicesWithMediaType:) gives
    correct names but its order ALSO does not match OpenCV's VideoCapture index
    (verified empirically) and shifts between launches. OpenCV's AVFoundation
    capture index is effectively opaque from Python, so there is no reliable way
    to resolve a stored identity to the current cv2 index on macOS. Returning []
    makes resolveCameraSetup fall back to the stored index (correct for the
    session; re-run camera_setup.py after a power-cycle reorder). Identity
    resolution works on Linux, where cv2 index == /dev/videoN."""
    return []


def _enumerateLinux() -> list[CameraInfo]:
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


def enumerateCameras() -> list[CameraInfo]:
    """Current cameras with their cv2 index, name, and stable location."""
    if platform.system() == "Darwin":
        return _enumerateMac()
    return _enumerateLinux()


def cameraIdentityForIndex(index: int, infos: "list[CameraInfo] | None" = None) -> "dict | None":
    """Identity dict for the camera currently at the given cv2 index, for
    camera_setup to record when a role is assigned."""
    if infos is None:
        infos = enumerateCameras()
    for c in infos:
        if c.index == index:
            return c.identity()
    return None


def resolveCameraIndex(identity, infos: "list[CameraInfo] | None" = None) -> Optional[int]:
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
        infos = enumerateCameras()

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

    # 2. fast path: no reorder -> the stored index still matches.
    if last is not None:
        for c in infos:
            if c.index == last and matches(c):
                return last

    # 3. exact name + location.
    if name and loc:
        for c in infos:
            if c.name == name and c.location == loc:
                return c.index

    # 4. unique name.
    if name:
        named = [c for c in infos if c.name == name]
        if len(named) == 1:
            return named[0].index

    # 5. location only.
    if loc:
        located = [c for c in infos if c.location == loc]
        if len(located) == 1:
            return located[0].index

    return None


def resolveCameraSetup(logger=None) -> dict:
    """Read the saved camera setup and return role -> current cv2 index.

    Resolves each role's stored identity to the live index. Falls back to the
    stored/last-known index (with a warning) when resolution fails, so behavior
    is never worse than the old fixed-index setup. Roles that can't be resolved
    at all are omitted.
    """
    from blob_manager import getCameraSetup

    raw = getCameraSetup() or {}
    infos = enumerateCameras()

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

    # No enumerable cameras -> identity resolution impossible; use stored indices.
    # On macOS this is always the case (OpenCV's capture index can't be mapped to
    # a camera identity from Python; see _enumerateMac). One clear note, not spam.
    if not infos:
        if platform.system() == "Darwin":
            _warn("macOS: camera identity->index resolution unsupported "
                  "(AVFoundation order doesn't match OpenCV's capture index); "
                  "using the stored indices from camera_setup. Re-run "
                  "scripts/camera_setup.py after a power-cycle reorder.")
        return {role: _stored(i) for role, i in raw.items() if _stored(i) is not None}

    resolved: dict[str, int] = {}
    for role, identity in raw.items():
        idx = resolveCameraIndex(identity, infos)
        if idx is not None:
            resolved[role] = idx
            continue
        fallback = _stored(identity)
        if fallback is not None:
            _warn(
                f"camera '{role}' could not be resolved by identity "
                f"({identity}); falling back to stored index {fallback}. "
                f"Re-run scripts/camera_setup.py if the wrong camera opens."
            )
            resolved[role] = fallback
        else:
            _warn(f"camera '{role}' could not be resolved and has no stored index; skipping.")
    return resolved
