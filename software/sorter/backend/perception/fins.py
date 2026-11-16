"""The classification channel rotor's fins as the machine reads them, for the
live view.

One thread reads the fins off the classification camera about once a second,
the way homing does (subsystems/classification_channel/two_piece/spoke_home.py:
two frames at half size that must agree). Whether the rotor stands still is
judged from the camera alone: a reading is kept only when its two frames agree,
and dropped as soon as the picture changes (a coarse difference between frames,
checked several times a second), so a line drawn from it is not where a fin was
a while ago. The camera feeds (server/routers/camera_feeds.py) send it to the
page with each frame.

It never touches the cameras' or the detector's threads, and costs a sleeping
thread on a machine with no classification camera, zones or rotor to read.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Optional

import numpy as np

from zones.model import CAMERA_ROLE
from zones.store import revision as zonesRevision

CLASSIFICATION_CHANNEL = 4
# The classification camera's roles: the channel's own, and its older name.
ROLES = (CAMERA_ROLE[CLASSIFICATION_CHANNEL], "classification_channel")

POLL_S = 0.2
# How often the fins are read, and how soon after the picture stops changing
# or a reading fails.
READ_EVERY_S = 1.0
RETRY_S = 0.4
# A reading is two frames that agree this closely, in degrees, found this fast.
AGREE_DEG = 1.0
READ_TIMEOUT_S = 0.6
# A reading older than this is not shown.
FRESH_S = 2.0
# How often the rotor's fin count is read from the settings again.
SETTINGS_EVERY_S = 5.0
# The picture has changed (the rotor turns, or something moves on it) when more
# than this share of it differs by more than MOTION_LEVELS of 255 from the
# frame before. It is compared small: every MOTION_STRIDE th pixel, averaged
# in blocks of MOTION_BLOCK, so the camera's noise, pixel by pixel large
# enough to pass for change, averages out.
MOTION_STRIDE = 4
MOTION_BLOCK = 4
MOTION_LEVELS = 20
MOTION_SHARE = 0.003


@dataclass(frozen=True)
class FinReading:
    """Every fin's angle (the zones' image angles, degrees), and the ring they
    cross, in the pixels of a frame `frame_size` (width, height) large."""

    angles_deg: tuple[float, ...]
    center: tuple[float, float]
    inner_radius: float
    outer_radius: float
    frame_size: tuple[int, int]
    read_at: float

    def lines(self) -> list[list[float]]:
        """Each fin as a line from the hub's edge to the rim, as a flat
        [x1, y1, x2, y2] in 0..1 across and down the frame."""
        width, height = self.frame_size
        out: list[list[float]] = []
        for angle in self.angles_deg:
            cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            out.append(
                [
                    round((self.center[0] + self.inner_radius * cos) / width, 4),
                    round((self.center[1] + self.inner_radius * sin) / height, 4),
                    round((self.center[0] + self.outer_radius * cos) / width, 4),
                    round((self.center[1] + self.outer_radius * sin) / height, 4),
                ]
            )
        return out


class FinWatch:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._camera_service: Any = None
        self._logger: Any = None
        self._thread: Optional[threading.Thread] = None
        self._reading: Optional[FinReading] = None

    def start(self, camera_service: Any, logger: Any = None) -> None:
        """Watch this camera service's classification camera. Called again
        (perception is rebuilt at each home) it only takes the new service."""
        with self._lock:
            self._camera_service = camera_service
            self._logger = logger
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name="perception-fins")
                self._thread.start()

    def reading(self) -> Optional[FinReading]:
        """The fins as last read, or None while the picture changes, right
        after it stops, or when they could not be read."""
        reading = self._reading
        if reading is None or time.time() - reading.read_at > FRESH_S:
            return None
        return reading

    # --- the thread -------------------------------------------------------

    def _run(self) -> None:
        last_frame_at: Optional[float] = None
        last_sample: Optional[np.ndarray] = None
        next_read = 0.0
        warned_at = 0.0
        fin_count = 0
        settings_at = 0.0
        geometry_for: Optional[tuple] = None
        geometry: Any = None
        while True:
            time.sleep(POLL_S)
            try:
                capture = self._capture()
                frame = getattr(capture, "latest_frame", None)
                raw = getattr(frame, "raw", None)
                stamp = getattr(frame, "timestamp", None)
                if raw is None or stamp is None:
                    self._reading = None
                    last_sample = None
                    continue
                now = time.time()
                if stamp != last_frame_at:
                    last_frame_at = stamp
                    sample = _small(raw)
                    changed = (
                        last_sample is not None
                        and last_sample.shape == sample.shape
                        and float(np.mean(np.abs(sample - last_sample) > MOTION_LEVELS)) > MOTION_SHARE
                    )
                    last_sample = sample
                    if changed:
                        self._reading = None
                        next_read = now + RETRY_S
                        continue
                if now < next_read:
                    continue
                next_read = now + READ_EVERY_S

                # Imported here: the flow's modules import perception's.
                from subsystems.classification_channel.two_piece.spoke_home import (
                    DETECTOR_PARAMS,
                    loadSpokeHomeGeometry,
                    readFinAngle,
                )

                if now - settings_at > SETTINGS_EVERY_S:
                    settings_at = now
                    fin_count = _finCount()
                shape = (int(raw.shape[0]), int(raw.shape[1]))
                key = (zonesRevision(), shape)
                if geometry_for != key:
                    geometry_for = key
                    geometry = loadSpokeHomeGeometry(shape)
                if fin_count < 1 or geometry is None:
                    self._reading = None
                    continue
                annulus = geometry[0]
                result = readFinAngle(
                    capture,
                    annulus,
                    replace(DETECTOR_PARAMS, fin_count=fin_count),
                    newer_than=float(stamp) - 1e-6,
                    reads=2,
                    agree_deg=AGREE_DEG,
                    timeout_s=READ_TIMEOUT_S,
                )
                if result is None:
                    self._reading = None
                    next_read = time.time() + RETRY_S
                    continue
                pitch = 360.0 / fin_count
                angle = float(result.angle_deg) % pitch
                self._reading = FinReading(
                    angles_deg=tuple(round((angle + k * pitch) % 360.0, 2) for k in range(fin_count)),
                    center=(float(annulus.center_x), float(annulus.center_y)),
                    inner_radius=float(annulus.inner_radius),
                    outer_radius=float(annulus.outer_radius),
                    frame_size=(shape[1], shape[0]),
                    read_at=time.time(),
                )
            except Exception as exc:
                self._reading = None
                last_sample = None
                next_read = time.time() + SETTINGS_EVERY_S
                if time.time() - warned_at > 60.0:
                    warned_at = time.time()
                    self._warn(f"[fins] could not read the classification channel's fins: {exc}")

    def _capture(self) -> Any:
        getter = getattr(self._camera_service, "get_capture_thread_for_role", None)
        if getter is None:
            return None
        for role in ROLES:
            capture = getter(role)
            if capture is not None:
                return capture
        return None

    def _warn(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return
        try:
            logger.warning(message)
        except Exception:
            pass


def _small(raw: np.ndarray) -> np.ndarray:
    """The frame's green channel, small and smoothed, to compare with the next."""
    import cv2

    picked = raw[::MOTION_STRIDE, ::MOTION_STRIDE]
    picked = np.ascontiguousarray(picked[..., 1] if picked.ndim == 3 else picked)
    size = (max(1, picked.shape[1] // MOTION_BLOCK), max(1, picked.shape[0] // MOTION_BLOCK))
    return cv2.resize(picked, size, interpolation=cv2.INTER_AREA).astype(np.int16)


def _finCount() -> int:
    """How many fins the rotor has, from its settings; 0 when unknown."""
    try:
        from toml_config import getClassificationChannelRev01Config

        from subsystems.classification_channel.two_piece.rev01_config import configFromDict

        return max(0, int(configFromDict(getClassificationChannelRev01Config()).fin_count))
    except Exception:
        return 0


# One per process: perception is rebuilt at each home, and this outlives it.
fins = FinWatch()
