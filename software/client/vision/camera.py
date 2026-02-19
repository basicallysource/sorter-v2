import threading
import time
from typing import Optional
import cv2

from irl.config import CameraConfig
from .types import CameraFrame


class CaptureThread:
    _thread: Optional[threading.Thread]
    _stop_event: threading.Event
    _config: CameraConfig
    _cap: Optional[cv2.VideoCapture]
    latest_frame: Optional[CameraFrame]
    name: str

    def __init__(self, name: str, config: CameraConfig):
        self.name = name
        self._config = config
        self._thread = None
        self._stop_event = threading.Event()
        self._cap = None
        self.latest_frame = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._captureLoop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _captureLoop(self) -> None:
        cap = cv2.VideoCapture(self._config.device_index)
        self._cap = cap
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
        cap.set(cv2.CAP_PROP_FPS, self._config.fps)

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if ret:
                self.latest_frame = CameraFrame(
                    raw=frame, annotated=None, results=[], timestamp=time.time()
                )
            else:
                time.sleep(0.01)

        cap.release()
        self._cap = None
