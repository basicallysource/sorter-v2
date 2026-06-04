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

    def stop(self) -> None:
        with self._lock:
            pipeline = self._pipeline
            modules = self._modules
            self._active = False
            self._pipeline = None
            self._raw_sink = None
            self._h264_sink = None
            if pipeline is not None and modules is not None:
                try:
                    pipeline.set_state(modules.Gst.State.NULL)
                except Exception as exc:
                    self._last_error = str(exc)

    def _next_h264_frame_blocking(self) -> EncodedH264Frame:
        try:
            return self._h264_queue.get(timeout=5.0)
        except queue.Empty as exc:
            raise GStreamerTargetRuntimeError("Timed out waiting for target H.264 sample.") from exc

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
