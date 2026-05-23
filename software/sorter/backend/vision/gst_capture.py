"""Hardware MJPEG capture via the RK3588 VPU (GStreamer mppjpegdec).

Only usable on Rockchip platforms where the `mppjpegdec` GStreamer element is
present (Orange Pi 5 with the liujianfeng1994/rockchip-multimedia stack). On
every other platform — Mac dev, non-rockchip Linux — ``hw_jpeg_decode_available``
returns False and callers fall back to ``cv2.VideoCapture``. The GStreamer
imports are guarded so importing this module never fails where ``gi`` is absent.

``GstMjpegCapture`` duck-types the subset of the ``cv2.VideoCapture`` API the
capture loop uses (``read`` → BGR, ``release``, ``isOpened``, ``get``, ``set``)
so it drops into ``CaptureThread`` with minimal branching. The pipeline is

    v4l2src -> image/jpeg -> mppjpegdec -> NV12 -> appsink

and ``read`` converts NV12 -> BGR with NEON-accelerated ``cv2.cvtColor`` to match
the BGR frames the rest of the system expects.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import threading
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


def _query_mjpeg_sizes(device_index: int) -> List[Tuple[int, int]]:
    """Discrete MJPEG WxH modes the camera advertises (via v4l2-ctl)."""
    try:
        out = subprocess.run(
            ["v4l2-ctl", "-d", f"/dev/video{device_index}", "--list-formats-ext"],
            capture_output=True, text=True, timeout=4,
        ).stdout
    except Exception:
        return []
    sizes: List[Tuple[int, int]] = []
    in_mjpeg = False
    for line in out.splitlines():
        stripped = line.strip()
        m = re.search(r"\]:\s*'(\w+)'", line)
        if m:
            in_mjpeg = m.group(1).upper() in {"MJPG", "MJPEG"}
            continue
        if in_mjpeg:
            sm = re.search(r"Size:\s*Discrete\s+(\d+)x(\d+)", stripped)
            if sm:
                wh = (int(sm.group(1)), int(sm.group(2)))
                if wh not in sizes:
                    sizes.append(wh)
    return sizes


def _pick_capture_size(device_index: int, want_w: int, want_h: int) -> Tuple[int, int]:
    """Pick a real MJPEG mode: exact match if advertised, else the largest mode
    that fits within the requested size, else the camera's largest mode. Falls
    back to the requested size if the camera can't be queried (e.g. URL source)."""
    sizes = _query_mjpeg_sizes(device_index)
    if not sizes:
        return want_w, want_h
    if (want_w, want_h) in sizes:
        return want_w, want_h
    fits = [(w, h) for (w, h) in sizes if w <= want_w and h <= want_h]
    pool = fits or sizes
    return max(pool, key=lambda wh: wh[0] * wh[1])

_GST_IMPORT_OK = False
try:
    import gi

    gi.require_version("Gst", "1.0")
    gi.require_version("GstApp", "1.0")
    from gi.repository import Gst  # noqa: E402
    _GST_IMPORT_OK = True
except Exception:
    Gst = None  # type: ignore[assignment]

_init_lock = threading.Lock()
# Serializes pipeline bring-up across cameras. Initializing several mppjpegdec
# instances simultaneously races the MPP driver ("client N driver is not
# ready!") and the losers fail to reach PLAYING. The benchmark sidestepped this
# by staggering starts; we serialize + retry instead.
_open_lock = threading.Lock()
_gst_inited = False
_hw_avail_cache: Optional[bool] = None

_OPEN_ATTEMPTS = 3
_OPEN_RETRY_DELAY_S = 0.4

# Pull timeout per frame. 0.5 s is generous at 30 fps (~33 ms cadence) and
# bounds a stalled pipeline so the capture loop's reopen logic can kick in.
_PULL_TIMEOUT_NS = 500_000_000


def _ensure_gst_init() -> None:
    global _gst_inited
    if _gst_inited:
        return
    with _init_lock:
        if not _gst_inited and Gst is not None:
            Gst.init(None)
            _gst_inited = True


def hw_jpeg_decode_available() -> bool:
    """True only on a Rockchip box where the mppjpegdec element is registered."""
    global _hw_avail_cache
    if _hw_avail_cache is not None:
        return _hw_avail_cache
    ok = False
    try:
        disabled = os.environ.get("SORTER_DISABLE_HW_DECODE", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if _GST_IMPORT_OK and platform.system() == "Linux" and not disabled:
            _ensure_gst_init()
            ok = Gst.ElementFactory.find("mppjpegdec") is not None
    except Exception:
        ok = False
    _hw_avail_cache = ok
    if ok:
        log.warning("HW JPEG decode available (mppjpegdec) — using GStreamer capture path")
    return ok


class GstMjpegCapture:
    """cv2.VideoCapture-shaped wrapper around a HW MJPEG-decode pipeline."""

    def __init__(self, device_index: int, width: int, height: int, fps: int) -> None:
        self._device = int(device_index)
        req_w, req_h = int(width), int(height)
        # The configured mode may not be a real camera mode (e.g. a cam that
        # only advertises 1280x720 MJPEG configured at 1920x1080). cv2 silently
        # downgrades, but v4l2src caps are strict and would fail to negotiate —
        # so pick a mode the camera actually advertises.
        self._w, self._h = _pick_capture_size(self._device, req_w, req_h)
        if (self._w, self._h) != (req_w, req_h):
            log.warning(
                "GstMjpegCapture[/dev/video%d] %dx%d is not an advertised MJPEG mode; "
                "capturing at %dx%d instead",
                self._device, req_w, req_h, self._w, self._h,
            )
        self._fps = int(fps) if fps and fps > 0 else 30
        self._opened = False
        self._pipeline = None
        self._sink = None
        self._open()

    def _open(self) -> None:
        if not _GST_IMPORT_OK or Gst is None:
            return
        _ensure_gst_init()
        desc = (
            f"v4l2src device=/dev/video{self._device} io-mode=4 do-timestamp=true ! "
            f"image/jpeg,width={self._w},height={self._h},framerate={self._fps}/1 ! "
            f"mppjpegdec ! video/x-raw,format=NV12 ! "
            f"appsink name=sink max-buffers=1 drop=true sync=false"
        )
        # Serialize bring-up so concurrent cameras don't race the MPP driver.
        with _open_lock:
            for attempt in range(1, _OPEN_ATTEMPTS + 1):
                if self._try_open_once(desc):
                    self._opened = True
                    return
                self.release()
                if attempt < _OPEN_ATTEMPTS:
                    time.sleep(_OPEN_RETRY_DELAY_S)
            log.warning(
                "GstMjpegCapture[/dev/video%d %dx%d] failed to start after %d attempts; "
                "falling back to cv2",
                self._device, self._w, self._h, _OPEN_ATTEMPTS,
            )

    def _try_open_once(self, desc: str) -> bool:
        try:
            self._pipeline = Gst.parse_launch(desc)
            self._sink = self._pipeline.get_by_name("sink")
            self._pipeline.set_state(Gst.State.PLAYING)
            # V4L2 sources go to PLAYING asynchronously; block until the state
            # actually settles before trusting reads.
            state_ret, _, _ = self._pipeline.get_state(3 * Gst.SECOND)
            if state_ret != Gst.StateChangeReturn.SUCCESS:
                return False
            # Prove the HW path actually delivers a frame before committing to
            # it — otherwise an unsupported (w,h,fps) combo or a transient MPP
            # "driver not ready" would silently keep the loop on a frameless
            # pipeline instead of the cv2 fallback.
            ok, _frame = self._read_with_timeout(2_000_000_000)
            return bool(ok)
        except Exception as exc:
            log.warning("GstMjpegCapture open attempt failed for /dev/video%d: %r", self._device, exc)
            return False

    def _read_with_timeout(self, timeout_ns: int) -> Tuple[bool, Optional[np.ndarray]]:
        if self._sink is None:
            return False, None
        sample = self._sink.emit("try-pull-sample", timeout_ns)
        if sample is None:
            return False, None
        # Trust the negotiated caps for the real frame geometry (the camera may
        # deliver something other than what was requested).
        caps = sample.get_caps()
        if caps is not None and caps.get_size() > 0:
            st = caps.get_structure(0)
            ok_w, cw = st.get_int("width")
            ok_h, ch = st.get_int("height")
            if ok_w and ok_h and cw > 0 and ch > 0:
                self._w, self._h = cw, ch
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return False, None
        try:
            expected = self._w * self._h * 3 // 2
            if info.size < expected:
                return False, None
            # NV12: full-res Y plane followed by interleaved half-res UV.
            nv12 = (
                np.frombuffer(info.data, dtype=np.uint8, count=expected)
                .reshape(self._h * 3 // 2, self._w)
                .copy()
            )
        finally:
            buf.unmap(info)
        bgr = cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
        return True, bgr

    # ---- cv2.VideoCapture-compatible surface ----

    def isOpened(self) -> bool:
        return self._opened and self._pipeline is not None

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self._opened:
            return False, None
        return self._read_with_timeout(_PULL_TIMEOUT_NS)

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._w)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._h)
        if prop == cv2.CAP_PROP_FPS:
            return float(self._fps)
        # Unknown / device-control props: NaN so _read_capture_value treats it
        # as "unavailable" (device controls are applied via v4l2-ctl instead).
        return float("nan")

    def set(self, prop: int, value: float) -> bool:
        # Capture mode is baked into the pipeline caps; device controls go
        # through v4l2-ctl. Nothing settable through this surface.
        return False

    def release(self) -> None:
        self._opened = False
        if self._pipeline is not None and Gst is not None:
            try:
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        self._pipeline = None
        self._sink = None
