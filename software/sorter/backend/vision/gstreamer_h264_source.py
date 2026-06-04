"""WebRTC H.264 source backed by the active GStreamer MPP capture runtime."""

from __future__ import annotations

from typing import Any


class GStreamerCaptureH264Source:
    """Expose CaptureThread's encoded H.264 appsink without owning the camera."""

    def __init__(self, *, feed: Any, physical_source: str) -> None:
        self.feed = feed
        self.physical_source = str(physical_source)
        device = getattr(feed, "device", None)
        capture_thread = getattr(device, "capture_thread", None)
        if capture_thread is None or not hasattr(capture_thread, "recv_encoded_h264"):
            raise RuntimeError("camera feed does not expose a GStreamer H.264 capture source")
        self._capture_thread = capture_thread

    @property
    def active(self) -> bool:
        describe = getattr(self._capture_thread, "describeEncodedH264Source", None)
        if not callable(describe):
            return False
        try:
            return bool(describe().get("active"))
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        describe = getattr(self._capture_thread, "describeEncodedH264Source", None)
        backend = describe() if callable(describe) else {}
        return {
            "physical_source": self.physical_source,
            "codec": "h264",
            "active": self.active,
            "software_h264_fallback_allowed": False,
            "pipeline_profile": "gstreamer_v4l2_mpp_tee_h264",
            "input_memory": "gstreamer_v4l2_dmabuf_mpp_decoded_frames",
            "zero_copy_dmabuf": True,
            "hardware_scale_convert_in_source": True,
            "target_compliant": bool(backend.get("target_compliant")),
            "input_from_single_capture_feed": True,
            "backend": backend,
        }

    async def recv_encoded_h264(self):
        return await self._capture_thread.recv_encoded_h264()

    def stop(self) -> None:
        # The underlying CaptureThread owns the camera and must remain alive for
        # calibration/detection and other roles sharing the same physical source.
        return None


def create_gstreamer_capture_h264_source(**kwargs: Any) -> GStreamerCaptureH264Source:
    return GStreamerCaptureH264Source(
        feed=kwargs["feed"],
        physical_source=str(kwargs["physical_source"]),
    )
