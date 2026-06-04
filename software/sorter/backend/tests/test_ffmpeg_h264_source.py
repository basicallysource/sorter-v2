from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from vision.ffmpeg_h264_source import (
    FfmpegRkmppConfig,
    FfmpegRkmppH264Source,
    H264AnnexBAccessUnitParser,
    build_ffmpeg_rkmpp_command,
    create_ffmpeg_rkmpp_h264_source,
    selected_ffmpeg_rkmpp_path,
)
from vision.types import CameraFrame


def test_build_ffmpeg_rkmpp_command_forces_hardware_encoder_and_raw_pipe() -> None:
    command = build_ffmpeg_rkmpp_command(
        config=FfmpegRkmppConfig(ffmpeg_path="/opt/ffmpeg-rockchip/bin/ffmpeg", fps=30),
        width=1280,
        height=720,
    )

    assert command[0] == "/opt/ffmpeg-rockchip/bin/ffmpeg"
    assert "-f" in command
    assert "rawvideo" in command
    assert "bgr24" in command
    assert "1280x720" in command
    assert "h264_rkmpp" in command
    assert "libx264" not in command
    assert "openh264" not in command
    assert command[-2:] == ["h264", "pipe:1"]


def test_selected_ffmpeg_rkmpp_path_accepts_only_production_hardware_path() -> None:
    assert selected_ffmpeg_rkmpp_path(None) is None
    assert selected_ffmpeg_rkmpp_path({"name": "gstreamer_software_h264"}) is None
    assert selected_ffmpeg_rkmpp_path(
        {
            "name": "ffmpeg_rkmpp",
            "hardware": True,
            "production_ready": False,
            "command": "/opt/ffmpeg-rockchip/bin/ffmpeg -c:v h264_rkmpp ...",
        }
    ) is None
    assert selected_ffmpeg_rkmpp_path(
        {
            "name": "ffmpeg_rkmpp",
            "hardware": True,
            "production_ready": True,
            "command": "/opt/ffmpeg-rockchip/bin/ffmpeg -c:v h264_rkmpp ...",
        }
    ) == "/opt/ffmpeg-rockchip/bin/ffmpeg"


def test_annex_b_parser_groups_parameter_sets_with_picture_access_unit() -> None:
    sps = b"\x00\x00\x00\x01\x67\x42\x00\x1f"
    pps = b"\x00\x00\x00\x01\x68\xce\x3c\x80"
    idr = b"\x00\x00\x00\x01\x65\x88\x84"
    first_access_unit = sps + pps + idr
    second_access_unit = sps + pps + idr
    parser = H264AnnexBAccessUnitParser()

    completed = parser.push(first_access_unit + second_access_unit)

    assert completed == [first_access_unit]
    assert parser.flush() == [second_access_unit]


def test_annex_b_parser_handles_chunked_pipe_reads_without_losing_start_codes() -> None:
    sps = b"\x00\x00\x00\x01\x67\x42"
    pps = b"\x00\x00\x01\x68\xce"
    idr = b"\x00\x00\x00\x01\x65\x88\x84"
    first_access_unit = sps + pps + idr
    second_access_unit = sps + pps + idr
    parser = H264AnnexBAccessUnitParser()
    completed: list[bytes] = []

    stream = first_access_unit + second_access_unit
    for index in range(0, len(stream), 2):
        completed.extend(parser.push(stream[index:index + 2]))

    assert completed == [first_access_unit]
    assert parser.flush() == [second_access_unit]


class _Feed:
    def __init__(self, frame: np.ndarray | None) -> None:
        self.frame = frame
        self.calls: list[tuple[bool, bool]] = []

    def get_frame(self, *, annotated: bool, color_correct: bool):
        self.calls.append((annotated, color_correct))
        if self.frame is None:
            return None
        return CameraFrame(raw=self.frame, annotated=None, results=[], timestamp=123.0)


def test_ffmpeg_source_waits_for_raw_frame_from_existing_feed() -> None:
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    feed = _Feed(frame)
    source = FfmpegRkmppH264Source(
        feed=feed,
        physical_source="video:5",
        config=FfmpegRkmppConfig(ffmpeg_path="ffmpeg"),
    )

    raw = source._wait_for_frame(timeout_s=0.1)

    assert raw.shape == (4, 6, 3)
    assert raw.flags["C_CONTIGUOUS"]
    assert feed.calls == [(False, True)]


def test_ffmpeg_source_rejects_non_bgr24_frames() -> None:
    source = FfmpegRkmppH264Source(
        feed=_Feed(None),
        physical_source="video:5",
        config=FfmpegRkmppConfig(ffmpeg_path="ffmpeg"),
    )

    with pytest.raises(ValueError, match="BGR24"):
        source._coerce_bgr24(np.zeros((4, 6), dtype=np.uint8))
    with pytest.raises(ValueError, match="uint8"):
        source._coerce_bgr24(np.zeros((4, 6, 3), dtype=np.float32))


def test_ffmpeg_source_queues_timestamped_access_units_for_packet_track() -> None:
    source = FfmpegRkmppH264Source(
        feed=_Feed(None),
        physical_source="video:5",
        config=FfmpegRkmppConfig(ffmpeg_path="ffmpeg", fps=30),
    )
    access_unit = b"\x00\x00\x00\x01\x65\x88\x84"

    source._queue_access_unit(access_unit)

    encoded = source._packets.get_nowait()
    assert encoded.data == access_unit
    assert encoded.pts == 3000
    assert encoded.time_base.numerator == 1
    assert encoded.time_base.denominator == 90000


def test_create_ffmpeg_rkmpp_source_factory_requires_selected_hardware_encoder() -> None:
    with pytest.raises(RuntimeError, match="production ffmpeg_rkmpp"):
        create_ffmpeg_rkmpp_h264_source(
            physical_source="video:5",
            feed=_Feed(np.zeros((4, 6, 3), dtype=np.uint8)),
            selected_encoder_path={"name": "gstreamer_software_h264"},
        )

    source = create_ffmpeg_rkmpp_h264_source(
        physical_source="video:5",
        feed=_Feed(np.zeros((4, 6, 3), dtype=np.uint8)),
        selected_encoder_path={
            "name": "ffmpeg_rkmpp",
            "hardware": True,
            "production_ready": True,
            "command": "/opt/ffmpeg-rockchip/bin/ffmpeg -c:v h264_rkmpp ...",
        },
    )

    assert source.describe()["codec"] == "h264_rkmpp"
    assert source.describe()["software_h264_fallback_allowed"] is False
    assert source.describe()["pipeline_profile"] == "staging_bgr24_cpu_pipe_to_h264_rkmpp"
    assert source.describe()["input_memory"] == "cpu_bgr24_frames_from_camera_feed"
    assert source.describe()["zero_copy_dmabuf"] is False
    assert source.describe()["hardware_scale_convert_in_source"] is False
    assert source.describe()["target_compliant"] is False
    assert source.config.ffmpeg_path == "/opt/ffmpeg-rockchip/bin/ffmpeg"
