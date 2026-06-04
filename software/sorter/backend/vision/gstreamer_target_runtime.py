"""Runtime wrapper for the GStreamer/Rockchip target capture pipeline.

The target runtime owns exactly one GStreamer pipeline per physical camera. The
pipeline has one ``v4l2src`` capture owner, a tee, one raw-frame appsink for the
backend ring buffer, and one H.264 appsink for WebRTC packet tracks.

The module is intentionally lazy: importing it must work on development hosts
without PyGObject/GStreamer. Missing runtime pieces are reported through
capability metadata instead of silently falling back to OpenCV or software H.264.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable

import numpy as np
import cv2

from .gstreamer_target_capture import (
    TARGET_PIPELINE_NAME,
    GStreamerTargetCaptureConfig,
    GStreamerTargetCaptureContract,
)
from .h264_webrtc_bridge import EncodedH264Frame
from .types import CameraFrame


GST_SECOND = 1_000_000_000
WEBRTC_H264_TIME_BASE = Fraction(1, 90_000)


class GStreamerTargetRuntimeError(RuntimeError):
    pass


class GStreamerTargetRestartingError(GStreamerTargetRuntimeError):
    """The pipeline is (re)building and has no H.264 sample *yet*.

    Distinct from the base error so the WebRTC fanout can treat a camera-switch
    transient as "wait and retry" instead of a fatal stream failure that tears
    the peer down. A genuine encoder stall (active pipeline, silent beyond the
    watchdog) still raises the base ``GStreamerTargetRuntimeError``.
    """

    pass


@dataclass(frozen=True)
class GStreamerRuntimeModules:
    Gst: Any
    GLib: Any


def load_gstreamer_runtime_modules() -> GStreamerRuntimeModules:
    try:
        import gi  # type: ignore

        gi.require_version("Gst", "1.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import GLib, Gst  # type: ignore
    except Exception as exc:
        raise GStreamerTargetRuntimeError(f"GStreamer/PyGObject runtime is unavailable: {exc}") from exc

    try:
        Gst.init(None)
    except Exception as exc:
        raise GStreamerTargetRuntimeError(f"Could not initialize GStreamer: {exc}") from exc
    return GStreamerRuntimeModules(Gst=Gst, GLib=GLib)


def describe_gstreamer_target_runtime() -> dict[str, Any]:
    try:
        load_gstreamer_runtime_modules()
        return {
            "implemented": True,
            "runtime_importable": True,
            "implementation": TARGET_PIPELINE_NAME,
            "raw_ring_branch": True,
            "h264_webrtc_branch": True,
            "software_h264_fallback_allowed": False,
            "reason": "PyGObject/GStreamer runtime imports and the target runtime module is implemented.",
        }
    except Exception as exc:
        return {
            "implemented": True,
            "runtime_importable": False,
            "implementation": TARGET_PIPELINE_NAME,
            "raw_ring_branch": True,
            "h264_webrtc_branch": True,
            "software_h264_fallback_allowed": False,
            "reason": str(exc),
        }


def gst_pts_to_webrtc_pts(pts_ns: int | None, *, fallback_index: int, fps: int) -> int:
    if isinstance(pts_ns, int) and pts_ns >= 0:
        return int(pts_ns * 90_000 // GST_SECOND)
    return int(max(0, fallback_index) * 90_000 // max(1, int(fps)))


def gst_pts_to_seconds(pts_ns: int | None) -> float:
    if isinstance(pts_ns, int) and pts_ns >= 0:
        return float(pts_ns) / float(GST_SECOND)
    return time.time()


def coerce_bgr_sample_bytes(payload: bytes | memoryview, *, width: int, height: int) -> np.ndarray:
    expected = int(width) * int(height) * 3
    data = bytes(payload)
    if len(data) != expected:
        raise ValueError(f"raw BGR sample has {len(data)} bytes; expected {expected}")
    return np.frombuffer(data, dtype=np.uint8).reshape((int(height), int(width), 3)).copy()


def coerce_nv12_sample_bytes(payload: bytes | memoryview, *, width: int, height: int) -> np.ndarray:
    width = int(width)
    height = int(height)
    expected = width * height * 3 // 2
    data = bytes(payload)
    padded_height = height
    if len(data) != expected:
        rows, remainder = divmod(len(data), width)
        if remainder != 0 or rows * 2 % 3 != 0:
            raise ValueError(f"raw NV12 sample has {len(data)} bytes; expected {expected}")
        candidate_height = rows * 2 // 3
        if candidate_height < height or candidate_height % 2 != 0:
            raise ValueError(f"raw NV12 sample has {len(data)} bytes; expected {expected}")
        padded_height = candidate_height
    yuv = np.frombuffer(data, dtype=np.uint8).reshape((padded_height * 3 // 2, width))
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
    return bgr[:height, :, :].copy()


class GStreamerTargetCaptureRuntime:
    """Own one integrated capture pipeline and expose both target branches."""

    def __init__(
        self,
        config: GStreamerTargetCaptureConfig,
        *,
        module_loader: Callable[[], GStreamerRuntimeModules] = load_gstreamer_runtime_modules,
        raw_frame_callback: Callable[[CameraFrame], None] | None = None,
        raw_ring_size: int = 90,
        h264_queue_size: int = 90,
    ) -> None:
        config.validate()
        self.config = config
        self.contract = GStreamerTargetCaptureContract(config).describe()
        self._module_loader = module_loader
        self._raw_frame_callback = raw_frame_callback
        self._raw_ring: deque[CameraFrame] = deque(maxlen=max(1, int(raw_ring_size)))
        self._h264_queue: queue.Queue[EncodedH264Frame] = queue.Queue(maxsize=max(1, int(h264_queue_size)))
        self._lock = threading.Lock()
        self._modules: GStreamerRuntimeModules | None = None
        self._pipeline: Any | None = None
        self._raw_sink: Any | None = None
        self._h264_sink: Any | None = None
        self._active = False
        self._packet_index = 0
        self._last_error: str | None = None
        # Bus watch + liveness tracking so a post-PLAYING failure stops being
        # silent and "rebuilding" can be told apart from "active but dead".
        self._bus: Any | None = None
        self._bus_thread: threading.Thread | None = None
        self._bus_stop = threading.Event()
        self._active_since: float | None = None
        self._last_h264_at: float | None = None
        self._frames_since_start = 0
        # How long the pipeline may be active yet silent before we call it dead
        # rather than merely restarting. A camera remap rebuilds in ~1-3s here,
        # so this must comfortably exceed that.
        self._h264_watchdog_s = 4.0

    @property
    def active(self) -> bool:
        return self._active

    @property
    def raw_ring_depth(self) -> int:
        return len(self._raw_ring)

    def latest_raw_frame(self) -> CameraFrame | None:
        if not self._raw_ring:
            return None
        return self._raw_ring[-1]

    def drain_raw_ring(self, max_frames: int) -> list[CameraFrame]:
        if max_frames <= 0:
            return []
        frames = list(self._raw_ring)
        if len(frames) <= max_frames:
            return frames
        return frames[-max_frames:]

    async def recv_encoded_h264(self) -> EncodedH264Frame:
        self.start()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._next_h264_frame_blocking)

    def describe_capture_backend(self) -> dict[str, Any]:
        return {
            "implementation": TARGET_PIPELINE_NAME,
            "source": self.config.device_path,
            "requested_mode": {
                "width": int(self.config.width),
                "height": int(self.config.height),
                "fps": int(self.config.fps),
                "fourcc": self.config.normalized_fourcc(),
            },
            "owns_capture_device": True,
            "single_capture_owner": True,
            "raw_ring_branch": True,
            "h264_webrtc_branch": True,
            "hardware_scale_convert": False,
            "zero_copy_dmabuf": True,
            "target_compliant": True,
            "active": self.active,
            "raw_ring_depth": self.raw_ring_depth,
            "h264_queue_depth": self._h264_queue.qsize(),
            "software_h264_fallback_allowed": False,
            "pipeline_contract": self.contract,
            "last_error": self._last_error,
            "reason": "Integrated GStreamer v4l2src tee target backend.",
        }

    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            modules = self._module_loader()
            Gst = modules.Gst
            pipeline = Gst.parse_launch(self.contract["launch_pipeline"])
            raw_sink = pipeline.get_by_name(self.config.raw_sink_name)
            h264_sink = pipeline.get_by_name(self.config.h264_sink_name)
            if raw_sink is None:
                raise GStreamerTargetRuntimeError(f"Raw appsink {self.config.raw_sink_name!r} is missing.")
            if h264_sink is None:
                raise GStreamerTargetRuntimeError(f"H.264 appsink {self.config.h264_sink_name!r} is missing.")

            raw_sink.connect("new-sample", self._on_raw_sample)
            h264_sink.connect("new-sample", self._on_h264_sample)
            result = pipeline.set_state(Gst.State.PLAYING)
            if result == Gst.StateChangeReturn.FAILURE:
                raise GStreamerTargetRuntimeError("Target GStreamer pipeline failed to enter PLAYING.")

            self._modules = modules
            self._pipeline = pipeline
            self._raw_sink = raw_sink
            self._h264_sink = h264_sink
            self._active = True
            self._last_error = None
            self._active_since = time.monotonic()
            self._last_h264_at = None
            self._frames_since_start = 0

            # Watch the pipeline bus on a daemon thread (polled, so it does not
            # depend on a running GLib main loop — the appsink callbacks fire on
            # the streaming thread regardless). An ERROR/EOS after PLAYING flips
            # us inactive with a real reason instead of surfacing only as the
            # H.264 read timeout. Guarded so a pipeline double without get_bus
            # (or an environment without a real bus) simply skips the watch.
            get_bus = getattr(pipeline, "get_bus", None)
            bus = get_bus() if callable(get_bus) else None
            if bus is not None:
                self._bus = bus
                self._bus_stop.clear()
                self._bus_thread = threading.Thread(
                    target=self._bus_poll_loop,
                    args=(bus, Gst),
                    name=f"gst-bus-{self.config.raw_sink_name}",
                    daemon=True,
                )
                self._bus_thread.start()

    def stop(self) -> None:
        with self._lock:
            pipeline = self._pipeline
            modules = self._modules
            bus_thread = self._bus_thread
            self._bus_stop.set()
            self._active = False
            self._pipeline = None
            self._raw_sink = None
            self._h264_sink = None
            self._bus = None
            self._bus_thread = None
            if pipeline is not None and modules is not None:
                try:
                    pipeline.set_state(modules.Gst.State.NULL)
                except Exception as exc:
                    self._last_error = str(exc)
        # Join outside the lock — the poll loop never takes _lock, but it can be
        # parked in a 100ms timed_pop, so bound the wait.
        if bus_thread is not None and bus_thread.is_alive():
            bus_thread.join(timeout=1.0)

    def _bus_poll_loop(self, bus: Any, Gst: Any) -> None:
        """Drain ERROR/EOS off the pipeline bus so async failures are visible.

        Polled (not add_signal_watch) so it works without a running GLib main
        loop. On a hard message it records the reason and flips the runtime
        inactive, which lets the H.264 read distinguish a real failure from a
        warm-up/remap transient instead of always raising the 5s timeout.
        """
        msg_types = Gst.MessageType.ERROR | Gst.MessageType.EOS
        poll_ns = 100 * Gst.MSECOND
        while not self._bus_stop.is_set():
            try:
                message = bus.timed_pop_filtered(poll_ns, msg_types)
            except Exception:
                break
            if message is None:
                continue
            if message.type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                detail = getattr(err, "message", None) or str(err)
                self._last_error = f"{detail} ({debug})" if debug else str(detail)
                self._active = False
            elif message.type == Gst.MessageType.EOS:
                self._last_error = "Target pipeline reached EOS unexpectedly."
                self._active = False

    def _next_h264_frame_blocking(self) -> EncodedH264Frame:
        # A bus-reported error is a real failure — surface it immediately so the
        # caller tears down rather than spinning.
        if self._last_error is not None:
            raise GStreamerTargetRuntimeError(self._last_error)
        if not self._active:
            raise GStreamerTargetRestartingError("Target pipeline is not active (rebuilding).")
        try:
            return self._h264_queue.get(timeout=1.0)
        except queue.Empty as exc:
            if self._last_error is not None:
                raise GStreamerTargetRuntimeError(self._last_error) from exc
            if not self._active:
                raise GStreamerTargetRestartingError(
                    "Target pipeline went inactive while waiting."
                ) from exc
            # Active but silent: a transient (warm-up or mid-remap) until it has
            # been silent longer than a healthy encoder ever is — only then fatal.
            reference = self._last_h264_at or self._active_since or time.monotonic()
            if time.monotonic() - reference >= self._h264_watchdog_s:
                raise GStreamerTargetRuntimeError(
                    "Target pipeline active but produced no H.264 within the watchdog window."
                ) from exc
            raise GStreamerTargetRestartingError(
                "Target pipeline active but momentarily silent; retrying."
            ) from exc

    def _on_raw_sample(self, sink: Any) -> Any:
        flow_ok = self._flow_return("OK")
        flow_error = self._flow_return("ERROR")
        try:
            sample = sink.emit("pull-sample")
            frame = self._raw_frame_from_sample(sample)
            self._raw_ring.append(frame)
            if self._raw_frame_callback is not None:
                self._raw_frame_callback(frame)
            return flow_ok
        except Exception as exc:
            self._last_error = str(exc)
            return flow_error

    def _on_h264_sample(self, sink: Any) -> Any:
        flow_ok = self._flow_return("OK")
        flow_error = self._flow_return("ERROR")
        try:
            sample = sink.emit("pull-sample")
            encoded = self._h264_frame_from_sample(sample)
            while self._h264_queue.full():
                try:
                    self._h264_queue.get_nowait()
                except queue.Empty:
                    break
            self._h264_queue.put_nowait(encoded)
            self._frames_since_start += 1
            self._last_h264_at = time.monotonic()
            return flow_ok
        except Exception as exc:
            self._last_error = str(exc)
            return flow_error

    def _flow_return(self, name: str) -> Any:
        if self._modules is None:
            return name
        return getattr(self._modules.Gst.FlowReturn, name)

    def _raw_frame_from_sample(self, sample: Any) -> CameraFrame:
        payload = self._sample_bytes(sample)
        timestamp = self._sample_timestamp(sample)
        raw = coerce_nv12_sample_bytes(payload, width=self.config.width, height=self.config.height)
        return CameraFrame(
            raw=raw,
            annotated=None,
            results=[],
            timestamp=timestamp,
            uncorrected_raw=raw.copy(),
        )

    def _h264_frame_from_sample(self, sample: Any) -> EncodedH264Frame:
        payload = self._sample_bytes(sample)
        buffer = sample.get_buffer()
        pts_ns = int(buffer.pts) if isinstance(getattr(buffer, "pts", None), int) and buffer.pts >= 0 else None
        self._packet_index += 1
        return EncodedH264Frame(
            data=payload,
            pts=gst_pts_to_webrtc_pts(pts_ns, fallback_index=self._packet_index, fps=self.config.fps),
            time_base=WEBRTC_H264_TIME_BASE,
            source_timestamp=gst_pts_to_seconds(pts_ns),
        )

    def _sample_timestamp(self, sample: Any) -> float:
        buffer = sample.get_buffer()
        pts = getattr(buffer, "pts", None)
        return gst_pts_to_seconds(int(pts) if isinstance(pts, int) else None)

    def _sample_bytes(self, sample: Any) -> bytes:
        if sample is None:
            raise ValueError("GStreamer appsink returned no sample.")
        buffer = sample.get_buffer()
        if buffer is None:
            raise ValueError("GStreamer sample does not contain a buffer.")
        map_flags = 1
        if self._modules is not None:
            map_flags = getattr(getattr(self._modules.Gst, "MapFlags", None), "READ", 1)
        ok, map_info = buffer.map(map_flags)
        if not ok:
            raise ValueError("Could not map GStreamer sample buffer.")
        try:
            return bytes(map_info.data)
        finally:
            buffer.unmap(map_info)
