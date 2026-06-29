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
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _apply_manual_controls(self, cap: "cv2.VideoCapture") -> None:
        """Apply optional manual exposure/white-balance/gain/hue/saturation locks over
        V4L2. Each control is skipped when its config value is None; auto flags are
        written before the corresponding manual value (drivers ignore manual values
        while auto is on). What we attempt and what the camera reports are logged, since
        not every camera accepts every property."""
        cfg = self._config
        if all(
            v is None
            for v in (
                cfg.auto_exposure,
                cfg.exposure,
                cfg.auto_wb,
                cfg.wb_temperature,
                cfg.auto_gain,
                cfg.gain,
                cfg.hue,
                cfg.saturation,
            )
        ):
            return

        print(f"[camera {self.name}] backend={cap.getBackendName()}", flush=True)

        def apply(prop_id: int, prop_name: str, value: float) -> None:
            accepted = cap.set(prop_id, value)
            reported = cap.get(prop_id)
            print(
                f"[camera {self.name}] set {prop_name}={value} -> "
                f"accepted={accepted}, reported={reported}",
                flush=True,
            )

        # Exposure: disable auto first, then set the manual value. V4L2 uses a menu:
        # 1 = manual, 3 = auto.
        if cfg.auto_exposure is not None:
            apply(cv2.CAP_PROP_AUTO_EXPOSURE, "AUTO_EXPOSURE", 3.0 if cfg.auto_exposure else 1.0)
        if cfg.exposure is not None:
            apply(cv2.CAP_PROP_EXPOSURE, "EXPOSURE", cfg.exposure)

        # White balance: disable auto first, then set the manual temperature.
        if cfg.auto_wb is not None:
            apply(cv2.CAP_PROP_AUTO_WB, "AUTO_WB", 1.0 if cfg.auto_wb else 0.0)
        if cfg.wb_temperature is not None:
            apply(cv2.CAP_PROP_WB_TEMPERATURE, "WB_TEMPERATURE", cfg.wb_temperature)

        # Gain: not every OpenCV build exposes CAP_PROP_AUTOGAIN; guard it.
        if cfg.auto_gain is not None:
            if hasattr(cv2, "CAP_PROP_AUTOGAIN"):
                apply(cv2.CAP_PROP_AUTOGAIN, "AUTOGAIN", 1.0 if cfg.auto_gain else 0.0)
            else:
                print(
                    f"[camera {self.name}] CAP_PROP_AUTOGAIN unavailable in this "
                    f"OpenCV build; relying on manual GAIN to override auto",
                    flush=True,
                )
        if cfg.gain is not None:
            apply(cv2.CAP_PROP_GAIN, "GAIN", cfg.gain)

        if cfg.hue is not None:
            apply(cv2.CAP_PROP_HUE, "HUE", cfg.hue)
        if cfg.saturation is not None:
            apply(cv2.CAP_PROP_SATURATION, "SATURATION", cfg.saturation)

    def _capture_loop(self) -> None:
        cap = cv2.VideoCapture(self._config.device_index, cv2.CAP_V4L2)
        self._cap = cap
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
        cap.set(cv2.CAP_PROP_FPS, self._config.fps)
        self._apply_manual_controls(cap)

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
