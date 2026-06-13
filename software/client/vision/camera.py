import os
import shutil
import subprocess
import threading
import time
from typing import Optional
import cv2

from irl.config import CameraConfig
from .types import CameraFrame

# macOS-only: OpenCV's AVFoundation backend ignores UVC control property sets, so
# we lock exposure/white-balance/gain out-of-band by shelling out to the uvc-util
# utility (https://github.com/jtfrey/uvc-util). Resolve the binary from this env
# var first, then PATH.
UVC_UTIL_ENV_VAR = "UVC_UTIL_PATH"


def _resolveUvcUtil() -> Optional[str]:
    env_path = os.environ.get(UVC_UTIL_ENV_VAR)
    if env_path and os.path.exists(env_path):
        return env_path
    return shutil.which("uvc-util")


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

    def _applyManualControls(self, cap: "cv2.VideoCapture") -> None:
        """Apply optional manual exposure/white-balance/gain locks. Each control
        is skipped when its config value is None. Auto flags are written before
        the corresponding manual value (drivers ignore manual values while auto
        is on). We log what we attempted and what the camera reports back, since
        not every camera/backend accepts every property."""
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

        backend = cap.getBackendName()
        is_v4l2 = backend == "V4L2"
        print(f"[camera {self.name}] backend={backend}", flush=True)

        if backend == "AVFOUNDATION":
            # AVFoundation ignores these property sets (they return accepted=False
            # and report 0.0). The locks are applied out-of-band via uvc-util after
            # the first frame; see _applyControlsViaUvcUtil.
            print(
                f"[camera {self.name}] native control unsupported on AVFOUNDATION; "
                f"deferring to uvc-util",
                flush=True,
            )
            return

        def apply(prop_id: int, prop_name: str, value: float) -> None:
            accepted = cap.set(prop_id, value)
            reported = cap.get(prop_id)
            print(
                f"[camera {self.name}] set {prop_name}={value} -> "
                f"accepted={accepted}, reported={reported}",
                flush=True,
            )

        # Exposure: disable auto first, then set the manual value.
        if cfg.auto_exposure is not None:
            # CAP_PROP_AUTO_EXPOSURE semantics are backend-dependent: V4L2 uses
            # a menu (1=manual, 3=auto); most other backends treat it as 0/1.
            if is_v4l2:
                ae_value = 3.0 if cfg.auto_exposure else 1.0
            else:
                ae_value = 1.0 if cfg.auto_exposure else 0.0
            apply(cv2.CAP_PROP_AUTO_EXPOSURE, "AUTO_EXPOSURE", ae_value)
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

    def _applyControlsViaUvcUtil(self) -> None:
        """Lock controls out-of-band via uvc-util (macOS/AVFoundation path). Called
        after the first frame so the AVFoundation session is fully started and won't
        reset the values back to auto. No-op unless a uvc_device_name is configured."""
        cfg = self._config
        name = cfg.uvc_device_name
        if name is None:
            return

        binary = _resolveUvcUtil()
        if binary is None:
            print(
                f"[camera {self.name}] uvc-util not found (set {UVC_UTIL_ENV_VAR} or "
                f"add it to PATH); cannot lock controls",
                flush=True,
            )
            return

        # (uvc-util control, value) in apply order: disable auto before the manual
        # value, since the camera ignores manual settings while auto is engaged.
        settings: list[tuple[str, str]] = []
        if cfg.auto_exposure is not None:
            # auto-exposure-mode is a bitmap: 1 = manual, 8 = aperture-priority (auto).
            settings.append(("auto-exposure-mode", "8" if cfg.auto_exposure else "1"))
        if cfg.exposure is not None:
            settings.append(("exposure-time-abs", str(int(cfg.exposure))))
        if cfg.auto_wb is not None:
            settings.append(
                ("auto-white-balance-temp", "true" if cfg.auto_wb else "false")
            )
        if cfg.wb_temperature is not None:
            settings.append(("white-balance-temp", str(int(cfg.wb_temperature))))
        # These cameras expose no UVC auto-gain control; gain is manual-only, so
        # cfg.auto_gain has no uvc-util equivalent and is intentionally skipped.
        if cfg.gain is not None:
            settings.append(("gain", str(int(cfg.gain))))
        if cfg.hue is not None:
            settings.append(("hue", str(int(cfg.hue))))
        if cfg.saturation is not None:
            settings.append(("saturation", str(int(cfg.saturation))))

        for control, value in settings:
            try:
                subprocess.run(
                    [binary, "-N", name, "-s", f"{control}={value}"],
                    check=False, capture_output=True, text=True, timeout=5,
                )
                readback = subprocess.run(
                    [binary, "-N", name, "-o", control],
                    check=False, capture_output=True, text=True, timeout=5,
                )
                reported = readback.stdout.strip() or readback.stderr.strip()
            except (subprocess.SubprocessError, OSError) as e:
                print(
                    f"[camera {self.name}] uvc-util {control}={value} failed: {e}",
                    flush=True,
                )
                continue
            print(
                f"[camera {self.name}] uvc-util set {control}={value} -> "
                f"reported={reported}",
                flush=True,
            )

    def _captureLoop(self) -> None:
        cap = cv2.VideoCapture(self._config.device_index)
        self._cap = cap
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
        cap.set(cv2.CAP_PROP_FPS, self._config.fps)
        self._applyManualControls(cap)

        external_controls_applied = False
        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if ret:
                if not external_controls_applied:
                    self._applyControlsViaUvcUtil()
                    external_controls_applied = True
                self.latest_frame = CameraFrame(
                    raw=frame, annotated=None, results=[], timestamp=time.time()
                )
            else:
                time.sleep(0.01)

        cap.release()
        self._cap = None
