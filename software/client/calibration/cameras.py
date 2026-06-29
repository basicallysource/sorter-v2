"""Web-driven camera assignment (replaces scripts/camera_setup.py).

The old script opened a cv2 window and you pressed F/B/T to tag the live camera with a
role. Here the same job is driven from the browser: list the cameras that actually deliver
frames, preview any one as an MJPEG stream, assign roles, and save. Assignments are stored
by stable identity (name + USB-port location) via blob_manager, so a power-cycle reorder
still resolves each role to the right camera (see hardware/camera_resolver.py).

Only one capture is held at a time (the one being previewed) to stay within USB bandwidth
on the shared hub.
"""

from __future__ import annotations

import threading
import time
from typing import Iterator, Optional

import cv2

from blob_manager import (
    get_camera_setup,
    set_camera_setup,
    get_excluded_camera_indices,
    set_excluded_camera_indices,
)
from hardware.camera_resolver import enumerate_cameras, camera_identity_for_index

# Roles a physical camera can be tagged with. This machine has no single feeder camera
# (the feed is split across dedicated c_channel_2 / c_channel_3 cameras) and a single
# classification camera ("classification"). The required roles must be assigned before the
# sorter can run; carousel is assignable but not required to gate.
REQUIRED_ROLES = ["c_channel_2", "c_channel_3", "classification"]
OPTIONAL_ROLES = ["carousel"]
ALL_ROLES = REQUIRED_ROLES + OPTIONAL_ROLES

_WARMUP_FRAMES = 5
_JPEG_QUALITY = 80


def _setup_index(value) -> Optional[int]:
    """A saved setup entry is either a legacy int index or an identity dict."""
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return value.get("index")
    return None


def _open_capture(index: int) -> "cv2.VideoCapture | None":
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    return cap


class CameraAssignmentSession:
    """Owns the cameras while the user assigns roles in the browser."""

    def __init__(self, gc):
        self.gc = gc
        self._lock = threading.Lock()
        self._cap: Optional[cv2.VideoCapture] = None
        self._cap_index: Optional[int] = None

        self.setup: dict = dict(get_camera_setup() or {})
        self.excluded: set[int] = set(get_excluded_camera_indices())
        self._infos = enumerate_cameras()

    # ----- discovery -----------------------------------------------------

    def list_cameras(self) -> list[dict]:
        """Probe each enumerated node; return the ones that deliver frames, with the
        roles currently assigned to each."""
        cameras: list[dict] = []
        with self._lock:
            self._release_locked()
            self._infos = enumerate_cameras()
            for info in self._infos:
                if info.index in self.excluded:
                    cameras.append(self._describe(info, working=False, excluded=True))
                    continue
                working = self._probe_locked(info.index)
                cameras.append(self._describe(info, working=working, excluded=False))
        return cameras

    def _describe(self, info, working: bool, excluded: bool) -> dict:
        roles = [r for r, v in self.setup.items() if _setup_index(v) == info.index]
        return {
            "index": info.index,
            "name": info.name,
            "location": info.location,
            "working": working,
            "excluded": excluded,
            "roles": roles,
        }

    def _probe_locked(self, index: int) -> bool:
        cap = _open_capture(index)
        if cap is None:
            return False
        try:
            for _ in range(_WARMUP_FRAMES):
                ok, _frame = cap.read()
                if ok:
                    return True
            return False
        finally:
            cap.release()

    # ----- preview -------------------------------------------------------

    def _ensure_capture_locked(self, index: int) -> None:
        if self._cap_index == index and self._cap is not None:
            return
        self._release_locked()
        cap = _open_capture(index)
        if cap is None:
            raise RuntimeError(f"camera index {index} could not be opened")
        for _ in range(_WARMUP_FRAMES):
            cap.read()
        self._cap = cap
        self._cap_index = index

    def stream(self, index: int, should_stop=None) -> Iterator[bytes]:
        """MJPEG multipart generator for one camera index.

        ``should_stop`` is an optional predicate (e.g. server shutdown) so the stream
        ends promptly instead of holding the connection open during Ctrl-C.
        """
        while True:
            if should_stop is not None and should_stop():
                break
            with self._lock:
                if self._closed():
                    break
                try:
                    self._ensure_capture_locked(index)
                    ok, frame = self._cap.read()  # type: ignore[union-attr]
                except RuntimeError:
                    ok, frame = False, None
            if not ok or frame is None:
                frame = self._placeholder(index)
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(buf)).encode()
                + b"\r\n\r\n"
                + buf.tobytes()
                + b"\r\n"
            )
            time.sleep(0.03)

    @staticmethod
    def _placeholder(index: int):
        import numpy as np

        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(
            img, f"camera {index} unavailable", (40, 240),
            cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2,
        )
        return img

    # ----- mutations -----------------------------------------------------

    def assign(self, role: str, index: int) -> None:
        if role not in ALL_ROLES:
            raise ValueError(f"unknown role {role!r}")
        with self._lock:
            # Drop any other role->index conflicts so one physical camera keeps a
            # consistent identity, then record by stable identity.
            self.setup[role] = camera_identity_for_index(index, self._infos) or index

    def unassign(self, role: str) -> None:
        with self._lock:
            self.setup.pop(role, None)

    def exclude(self, index: int) -> None:
        with self._lock:
            self.excluded.add(index)
            for role, val in list(self.setup.items()):
                if _setup_index(val) == index:
                    del self.setup[role]
            if self._cap_index == index:
                self._release_locked()

    def include(self, index: int) -> None:
        with self._lock:
            self.excluded.discard(index)

    def status(self) -> dict:
        assigned = {r: _setup_index(v) for r, v in self.setup.items()}
        missing = [r for r in REQUIRED_ROLES if r not in self.setup]
        return {
            "assigned": assigned,
            "missing_required": missing,
            "excluded": sorted(self.excluded),
            "roles": ALL_ROLES,
            "required_roles": REQUIRED_ROLES,
        }

    # ----- lifecycle -----------------------------------------------------

    def save(self) -> None:
        with self._lock:
            set_camera_setup(self.setup)
            set_excluded_camera_indices(sorted(self.excluded))

    def close(self) -> None:
        with self._lock:
            self._cap_index = -1  # signal streams to stop
            self._release_locked()

    def _closed(self) -> bool:
        return self._cap_index == -1

    def _release_locked(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._cap_index != -1:
            self._cap_index = None
