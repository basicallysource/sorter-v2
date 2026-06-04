"""Hardware H.264 packet bridge primitives for WebRTC.

aiortc's public track API normally deals in raw ``VideoFrame`` objects, which
would force libx264 software encoding inside ``RTCRtpSender``. The target camera
transport cannot use that path. aiortc 1.14 also accepts pre-encoded
``av.Packet`` values from a track and only RTP-packetizes them via
``H264Encoder.pack``. This module owns that boundary.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Protocol

import av
from av.frame import Frame
from av.packet import Packet
from aiortc.mediastreams import VIDEO_TIME_BASE, MediaStreamTrack


H264_90KHZ_TIME_BASE = VIDEO_TIME_BASE
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EncodedH264Frame:
    """One hardware-encoded H.264 access unit.

    ``data`` must be an Annex-B/AVCC-compatible access unit that aiortc's H.264
    packer can split into NAL units. ``pts`` is in ``time_base`` units; the
    default is WebRTC's 90 kHz video clock.
    """

    data: bytes
    pts: int
    time_base: Fraction = H264_90KHZ_TIME_BASE
    source_timestamp: float | None = None

    def to_packet(self) -> Packet:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("encoded H.264 frame data must be non-empty bytes")
        if not isinstance(self.pts, int) or self.pts < 0:
            raise ValueError("encoded H.264 frame pts must be a non-negative integer")
        packet = av.Packet(self.data)
        packet.pts = self.pts
        packet.dts = self.pts
        packet.time_base = self.time_base
        return packet


class EncodedH264Source(Protocol):
    def recv_encoded_h264(self) -> EncodedH264Frame | Packet: ...


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class HardwareH264PacketTrack(MediaStreamTrack):
    """A WebRTC video track that emits pre-encoded H.264 packets only."""

    kind = "video"

    def __init__(self, source: EncodedH264Source, *, on_stop: Any | None = None) -> None:
        super().__init__()
        self._source = source
        self._on_stop = on_stop
        self._stopped_once = False

    async def recv(self) -> Packet:
        if not hasattr(self._source, "recv_encoded_h264"):
            raise TypeError("hardware H.264 source must expose recv_encoded_h264()")
        item = await _maybe_await(self._source.recv_encoded_h264())
        return coerce_hardware_h264_packet(item)

    def stop(self) -> None:
        if self._stopped_once:
            return
        self._stopped_once = True
        super().stop()
        if callable(self._on_stop):
            self._on_stop()


def clone_hardware_h264_frame(item: Any) -> EncodedH264Frame:
    """Return an immutable encoded frame suitable for fanout to many tracks."""

    if isinstance(item, EncodedH264Frame):
        return item
    packet = coerce_hardware_h264_packet(item)
    return EncodedH264Frame(
        data=bytes(packet),
        pts=int(packet.pts),
        time_base=packet.time_base,
    )


class HardwareH264FanoutSubscription:
    def __init__(self, fanout: "HardwareH264SourceFanout") -> None:
        self._fanout = fanout
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=fanout.queue_size)
        self._closed = False

    async def recv_encoded_h264(self) -> EncodedH264Frame:
        item = await self._queue.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fanout.unsubscribe(self)

    def _push(self, item: EncodedH264Frame | BaseException) -> None:
        if self._closed:
            return
        while self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(item)


class HardwareH264SourceFanout:
    """Broadcast one hardware H.264 source to many WebRTC tracks.

    The upstream source is consumed by a single reader task. Each browser peer
    receives its own subscription queue so slow views drop stale packets instead
    of causing another encoder or blocking the capture pipeline.
    """

    def __init__(self, source: EncodedH264Source, *, queue_size: int = 2) -> None:
        if not hasattr(source, "recv_encoded_h264"):
            raise TypeError("hardware H.264 source must expose recv_encoded_h264()")
        self.source = source
        self.queue_size = max(1, int(queue_size))
        self._subscriptions: set[HardwareH264FanoutSubscription] = set()
        self._reader_task: asyncio.Task[Any] | None = None
        self._subscriber_event = asyncio.Event()
        self._stopped = False

    @property
    def active_subscriber_count(self) -> int:
        return len(self._subscriptions)

    def subscribe(self) -> HardwareH264FanoutSubscription:
        if self._stopped:
            raise RuntimeError("hardware H.264 fanout is stopped")
        subscription = HardwareH264FanoutSubscription(self)
        self._subscriptions.add(subscription)
        self._subscriber_event.set()
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(self._read_loop())
        return subscription

    def unsubscribe(self, subscription: HardwareH264FanoutSubscription) -> None:
        self._subscriptions.discard(subscription)
        if not self._subscriptions:
            self._subscriber_event.clear()

    async def stop(self) -> None:
        self._stopped = True
        subscriptions = list(self._subscriptions)
        self._subscriptions.clear()
        self._subscriber_event.set()
        for subscription in subscriptions:
            subscription._push(RuntimeError("hardware H.264 fanout stopped"))
            subscription._closed = True
        task = self._reader_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        stop = getattr(self.source, "stop", None)
        if callable(stop):
            result = stop()
            if inspect.isawaitable(result):
                await result

    async def _read_loop(self) -> None:
        # Imported lazily to avoid a circular import (gstreamer_target_runtime
        # imports EncodedH264Frame from this module).
        from .gstreamer_target_runtime import (
            GStreamerTargetRestartingError,
            GStreamerTargetRuntimeError,
        )

        # While the capture pipeline rebuilds (camera remap), recv raises a
        # *restarting* transient. Tolerate it so the live peer survives the
        # switch and resumes — only give up if the source stays down past this
        # grace window. This is what stops a routine camera switch from tearing
        # every WebRTC peer down (and triggering the client retry storm).
        restart_grace_s = 10.0
        restarting_since: float | None = None
        try:
            while not self._stopped:
                if not self._subscriptions:
                    await self._subscriber_event.wait()
                    continue
                try:
                    item = await _maybe_await(self.source.recv_encoded_h264())
                except GStreamerTargetRestartingError:
                    now = time.monotonic()
                    if restarting_since is None:
                        restarting_since = now
                    elif now - restarting_since >= restart_grace_s:
                        raise GStreamerTargetRuntimeError(
                            "Hardware H.264 source did not recover within the restart grace window."
                        )
                    await asyncio.sleep(0.15)
                    continue
                restarting_since = None
                frame = clone_hardware_h264_frame(item)
                for subscription in list(self._subscriptions):
                    subscription._push(frame)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Hardware H.264 fanout reader stopped after upstream error: %s", exc)
            # Genuine, non-transient failure: mark stopped so new subscriptions
            # get a clear error instead of spawning another doomed reader, then
            # poison the current subscribers so their tracks end cleanly.
            self._stopped = True
            for subscription in list(self._subscriptions):
                subscription._push(exc)


def coerce_hardware_h264_packet(item: Any) -> Packet:
    """Return an ``av.Packet`` and reject raw-frame/software-encode inputs."""

    if isinstance(item, EncodedH264Frame):
        return item.to_packet()
    if isinstance(item, Packet):
        if item.pts is None:
            raise ValueError("pre-encoded H.264 packet requires pts")
        if item.time_base is None:
            raise ValueError("pre-encoded H.264 packet requires time_base")
        if not bytes(item):
            raise ValueError("pre-encoded H.264 packet data must be non-empty")
        return item
    if isinstance(item, Frame):
        raise TypeError("raw video frames are forbidden on the hardware H.264 WebRTC bridge")
    if isinstance(item, bytes):
        raise TypeError("encoded H.264 bytes must be wrapped with pts/time_base metadata")
    raise TypeError(f"unsupported hardware H.264 bridge item: {type(item).__name__}")


def describe_hardware_webrtc_bridge(
    *,
    source_factory_registered: bool = False,
    runtime_hardware_encoder_ready: bool = False,
) -> dict[str, Any]:
    """Describe whether the encoded-packet WebRTC bridge can be used.

    The packet track itself is available once aiortc and PyAV can import. The
    bridge is considered implemented once a real hardware source factory is
    registered. Runtime hardware readiness stays a separate gate so a bad
    kernel/image cannot be mistaken for a missing code path.
    """

    packet_track_available = False
    packer_available = False
    aiortc_version = None
    av_version = None
    try:
        import aiortc
        from aiortc.codecs.h264 import H264Encoder

        aiortc_version = getattr(aiortc, "__version__", None)
        av_version = getattr(av, "__version__", None)
        packer_available = callable(getattr(H264Encoder, "pack", None))
        packet_track_available = packer_available
    except Exception:
        packet_track_available = False

    implemented = bool(packet_track_available and source_factory_registered)
    return {
        "implemented": implemented,
        "packet_track_available": packet_track_available,
        "h264_packetizer_available": packer_available,
        "integrated_with_hardware_encoder": bool(source_factory_registered),
        "source_factory_registered": bool(source_factory_registered),
        "runtime_hardware_encoder_ready": bool(runtime_hardware_encoder_ready),
        "encoded_frame_input": "av.Packet_or_EncodedH264Frame",
        "media_track": "HardwareH264PacketTrack",
        "uses_pre_encoded_packets": True,
        "raw_frame_input_allowed": False,
        "software_h264_fallback_allowed": False,
        "aiortc_version": aiortc_version,
        "av_version": av_version,
        "reason": (
            "Hardware H.264 packet track is available, the source factory is registered, and runtime encoder probe passed."
            if implemented and runtime_hardware_encoder_ready
            else "Hardware H.264 packet track and source factory are integrated; runtime hardware encoder is not ready on this host."
            if implemented
            else "Packet bridge exists, but no hardware H.264 source factory is registered yet."
            if packet_track_available
            else "aiortc/PyAV H.264 packet bridge support is unavailable."
        ),
    }
