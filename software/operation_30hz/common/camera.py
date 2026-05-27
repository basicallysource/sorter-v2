"""Minimal V4L2 camera capture thread.

Mirrors live `vision/camera.py` shape: tight loop reads frames, stashes
`latest_frame` (and timestamp) in a slot. Optionally calls a per-frame
hook (used by rev02 so the same thread that captures also runs inference)."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np


log = logging.getLogger("camera")


@dataclass
class Frame:
    raw: np.ndarray  # BGR HWC uint8
    timestamp: float  # time.time() when captured


class CaptureThread:
    def __init__(
        self,
        name: str,
        device: str,
        width: int = 640,
        height: int = 480,
        fps_target: int = 30,
        on_frame: Optional[Callable[[Frame], None]] = None,
    ) -> None:
        self.name = name
        self.device = device
        self.width = width
        self.height = height
        self.fps_target = fps_target
        self.on_frame = on_frame
        self.latest_frame: Optional[Frame] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame_count = 0
        self._last_log = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"capture-{self.name}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _open(self) -> Optional[cv2.VideoCapture]:
        # /dev/videoN as integer index — cv2.VideoCapture wants the int
        try:
            idx = int(self.device.replace("/dev/video", ""))
        except ValueError:
            idx = self.device  # type: ignore
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            log.error("camera %s: failed to open %s", self.name, self.device)
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps_target)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        log.warning(
            "camera %s opened %s @ %dx%d fps=%d",
            self.name, self.device, self.width, self.height, self.fps_target,
        )
        return cap

    def _loop(self) -> None:
        cap = self._open()
        if cap is None:
            return
        try:
            while not self._stop.is_set():
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    time.sleep(0.01)
                    continue
                f = Frame(raw=bgr, timestamp=time.time())
                self.latest_frame = f
                self._frame_count += 1
                if self.on_frame is not None:
                    try:
                        self.on_frame(f)
                    except Exception as exc:
                        log.warning("camera %s on_frame failed: %s", self.name, exc)
                if time.perf_counter() - self._last_log > 5.0:
                    log.warning("camera %s frames=%d", self.name, self._frame_count)
                    self._last_log = time.perf_counter()
        finally:
            cap.release()

    @property
    def frame_count(self) -> int:
        return self._frame_count
