from __future__ import annotations

import asyncio

import av
import pytest
from aiortc.codecs.h264 import H264Encoder

from vision.h264_webrtc_bridge import (
    EncodedH264Frame,
    HardwareH264PacketTrack,
    HardwareH264SourceFanout,
    coerce_hardware_h264_packet,
    describe_hardware_webrtc_bridge,
)


H264_IDR_ACCESS_UNIT = b"\x00\x00\x00\x01\x65\x88\x84"


def test_encoded_h264_frame_becomes_timestamped_av_packet() -> None:
    packet = EncodedH264Frame(data=H264_IDR_ACCESS_UNIT, pts=90000).to_packet()

    assert isinstance(packet, av.Packet)
    assert bytes(packet) == H264_IDR_ACCESS_UNIT
    assert packet.pts == 90000
    assert packet.dts == 90000
    assert packet.time_base.numerator == 1
    assert packet.time_base.denominator == 90000


def test_aiortc_h264_packetizer_accepts_bridge_packet_without_raw_frame_encode() -> None:
    packet = EncodedH264Frame(data=H264_IDR_ACCESS_UNIT, pts=90000).to_packet()

    payloads, timestamp = H264Encoder().pack(packet)

    assert timestamp == 90000
    assert payloads
    assert payloads[0][0] & 0x1F == 5


def test_bridge_rejects_raw_video_frame_and_unclocked_bytes() -> None:
    raw = av.VideoFrame(width=4, height=4, format="yuv420p")

    with pytest.raises(TypeError, match="raw video frames are forbidden"):
        coerce_hardware_h264_packet(raw)

    with pytest.raises(TypeError, match="wrapped with pts/time_base"):
        coerce_hardware_h264_packet(H264_IDR_ACCESS_UNIT)


def test_bridge_rejects_packet_without_timebase() -> None:
    packet = av.Packet(H264_IDR_ACCESS_UNIT)
    packet.pts = 1

    with pytest.raises(ValueError, match="time_base"):
        coerce_hardware_h264_packet(packet)


class _AsyncH264Source:
    def __init__(self) -> None:
        self.calls = 0

    async def recv_encoded_h264(self):
        self.calls += 1
        return EncodedH264Frame(data=H264_IDR_ACCESS_UNIT, pts=180000 + self.calls)


class _QueuedH264Source:
    def __init__(self) -> None:
        self.calls = 0
        self.delivered = 0
        self.queue: asyncio.Queue[EncodedH264Frame] = asyncio.Queue()

    async def recv_encoded_h264(self):
        self.calls += 1
        frame = await self.queue.get()
        self.delivered += 1
        return frame


def test_hardware_h264_packet_track_recv_returns_preencoded_packet() -> None:
    track = HardwareH264PacketTrack(_AsyncH264Source())

    packet = asyncio.run(track.recv())

    assert isinstance(packet, av.Packet)
    assert packet.pts == 180001
    assert bytes(packet) == H264_IDR_ACCESS_UNIT


def test_hardware_h264_fanout_broadcasts_one_upstream_frame_to_multiple_tracks() -> None:
    async def run() -> None:
        source = _QueuedH264Source()
        fanout = HardwareH264SourceFanout(source)
        first = fanout.subscribe()
        second = fanout.subscribe()
        try:
            first_task = asyncio.create_task(first.recv_encoded_h264())
            second_task = asyncio.create_task(second.recv_encoded_h264())
            await source.queue.put(EncodedH264Frame(data=H264_IDR_ACCESS_UNIT, pts=180000))
            first_frame, second_frame = await asyncio.gather(
                first_task,
                second_task,
            )
            assert first_frame.pts == second_frame.pts
            assert source.delivered == 1
            assert fanout.active_subscriber_count == 2

            first.close()
            assert fanout.active_subscriber_count == 1
        finally:
            second.close()
            await fanout.stop()

    asyncio.run(run())


def test_bridge_capability_reports_packet_track_available_but_not_integrated() -> None:
    payload = describe_hardware_webrtc_bridge()

    assert payload["packet_track_available"] is True
    assert payload["h264_packetizer_available"] is True
    assert payload["uses_pre_encoded_packets"] is True
    assert payload["raw_frame_input_allowed"] is False
    assert payload["software_h264_fallback_allowed"] is False
    assert payload["integrated_with_hardware_encoder"] is False
    assert payload["source_factory_registered"] is False
    assert payload["implemented"] is False


def test_bridge_capability_separates_source_integration_from_runtime_readiness() -> None:
    payload = describe_hardware_webrtc_bridge(
        source_factory_registered=True,
        runtime_hardware_encoder_ready=False,
    )

    assert payload["packet_track_available"] is True
    assert payload["source_factory_registered"] is True
    assert payload["runtime_hardware_encoder_ready"] is False
    assert payload["integrated_with_hardware_encoder"] is True
    assert payload["implemented"] is True
    assert "runtime hardware encoder is not ready" in payload["reason"]
