"""FFmpeg/RKMPP hardware H.264 source for WebRTC packet tracks.

This is the concrete source-side half for the target WebRTC bridge: it consumes
raw frames from the existing single camera feed and drives an FFmpeg process
using ``h264_rkmpp``. The class deliberately has no software-H264 fallback.
"""

from __future__ import annotations

import asyncio
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np

from .h264_webrtc_bridge import EncodedH264Frame


H264_TIME_BASE = Fraction(1, 90000)
_START_CODE_3 = b"\x00\x00\x01"
_START_CODE_4 = b"\x00\x00\x00\x01"
_H264_VCL_NAL_TYPES = frozenset({1, 5})
_H264_NEW_AU_PREFIX_NAL_TYPES = frozenset({6, 7, 8, 9})


@dataclass(frozen=True)
class FfmpegRkmppConfig:
    ffmpeg_path: str
    fps: int = 30
    bitrate: str = "2500k"
    gop: int | None = None
    queue_size: int = 90


def selected_ffmpeg_rkmpp_path(selected_encoder_path: dict[str, Any] | None) -> str | None:
    if not isinstance(selected_encoder_path, dict):
        return None
    if selected_encoder_path.get("name") != "ffmpeg_rkmpp":
        return None
    if not selected_encoder_path.get("hardware") or not selected_encoder_path.get("production_ready"):
        return None
    command = selected_encoder_path.get("command")
    if isinstance(command, str) and command.strip():
        first = command.strip().split()[0]
        if first and first != "ffmpeg":
            return first
    path = selected_encoder_path.get("path")
    return str(path) if isinstance(path, str) and path.strip() else "ffmpeg"


def build_ffmpeg_rkmpp_command(
    *,
    config: FfmpegRkmppConfig,
    width: int,
    height: int,
) -> list[str]:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    fps = max(1, int(config.fps))
    gop = int(config.gop or fps)
    return [
        config.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s:v",
        f"{int(width)}x{int(height)}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "h264_rkmpp",
        "-b:v",
        str(config.bitrate),
        "-g",
        str(gop),
        "-bf",
        "0",
        "-f",
        "h264",
        "pipe:1",
    ]


def _annex_b_start_codes(buffer: bytes | bytearray) -> list[int]:
    starts: list[int] = []
    index = 0
    length = len(buffer)
    while index <= length - 3:
        if index <= length - 4 and buffer[index:index + 4] == _START_CODE_4:
            starts.append(index)
            index += 4
        elif buffer[index:index + 3] == _START_CODE_3:
            starts.append(index)
            index += 3
        else:
            index += 1
    return starts


def _start_code_size(nal: bytes) -> int:
    if nal.startswith(_START_CODE_4):
        return 4
    if nal.startswith(_START_CODE_3):
        return 3
    raise ValueError("H.264 Annex-B NAL must start with a start code")


def _annex_b_nal_type(nal: bytes) -> int | None:
    try:
        header_offset = _start_code_size(nal)
    except ValueError:
        return None
    if header_offset >= len(nal):
        return None
    return nal[header_offset] & 0x1F


def _rbsp_from_nal_payload(payload: bytes) -> bytes:
    rbsp = bytearray()
    zero_count = 0
    for byte in payload:
        if zero_count >= 2 and byte == 0x03:
            zero_count = 0
            continue
        rbsp.append(byte)
        zero_count = zero_count + 1 if byte == 0 else 0
    return bytes(rbsp)


def _bit_at(data: bytes, bit_index: int) -> int:
    return (data[bit_index // 8] >> (7 - (bit_index % 8))) & 1


def _read_unsigned_exp_golomb(data: bytes) -> int | None:
    total_bits = len(data) * 8
    bit_index = 0
    leading_zero_bits = 0
    while bit_index < total_bits and _bit_at(data, bit_index) == 0:
        leading_zero_bits += 1
        bit_index += 1
    if bit_index >= total_bits:
        return None
    bit_index += 1
    value = 1 << leading_zero_bits
    for shift in range(leading_zero_bits - 1, -1, -1):
        if bit_index >= total_bits:
            return None
        value |= _bit_at(data, bit_index) << shift
        bit_index += 1
    return value - 1


def _h264_first_mb_in_slice(nal: bytes) -> int | None:
    try:
        header_offset = _start_code_size(nal)
    except ValueError:
        return None
    if header_offset + 1 >= len(nal):
        return None
    nal_type = nal[header_offset] & 0x1F
    if nal_type not in _H264_VCL_NAL_TYPES:
        return None
    rbsp = _rbsp_from_nal_payload(nal[header_offset + 1:])
    return _read_unsigned_exp_golomb(rbsp)


class H264AnnexBAccessUnitParser:
    """Groups FFmpeg's Annex-B H.264 byte stream into WebRTC packet units."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._current_nals: list[bytes] = []
        self._current_has_vcl = False

    def push(self, chunk: bytes) -> list[bytes]:
        if chunk:
            self._buffer.extend(chunk)
        return self._drain_complete_nals()

    def flush(self) -> list[bytes]:
        units = self._drain_complete_nals(allow_final_nal=True)
        if self._current_nals:
            units.append(b"".join(self._current_nals))
            self._current_nals = []
            self._current_has_vcl = False
        self._buffer.clear()
        return units

    def _drain_complete_nals(self, *, allow_final_nal: bool = False) -> list[bytes]:
        units: list[bytes] = []
        while True:
            starts = _annex_b_start_codes(self._buffer)
            if not starts:
                if len(self._buffer) > 4:
                    del self._buffer[:-4]
                return units
            if starts[0] > 0:
                del self._buffer[:starts[0]]
                continue
            if len(starts) < 2:
                if allow_final_nal and len(self._buffer) > _start_code_size(bytes(self._buffer)):
                    nal = bytes(self._buffer)
                    self._buffer.clear()
                    units.extend(self._accept_nal(nal))
                return units

            nal_end = starts[1]
            nal = bytes(self._buffer[:nal_end])
            del self._buffer[:nal_end]
            units.extend(self._accept_nal(nal))

    def _accept_nal(self, nal: bytes) -> list[bytes]:
        nal_type = _annex_b_nal_type(nal)
        if nal_type is None:
            return []
        is_vcl = nal_type in _H264_VCL_NAL_TYPES
        starts_new_access_unit = False
        if self._current_nals and self._current_has_vcl:
            if nal_type in _H264_NEW_AU_PREFIX_NAL_TYPES:
                starts_new_access_unit = True
            elif is_vcl:
                first_mb = _h264_first_mb_in_slice(nal)
                starts_new_access_unit = first_mb is None or first_mb == 0

        if not starts_new_access_unit:
            self._current_nals.append(nal)
            self._current_has_vcl = self._current_has_vcl or is_vcl
            return []

        completed = b"".join(self._current_nals)
        self._current_nals = [nal]
        self._current_has_vcl = is_vcl
        return [completed]


class FfmpegRkmppH264Source:
    """Encode shared camera-feed frames with one FFmpeg RKMPP process."""

    def __init__(
        self,
        *,
        feed: Any,
        physical_source: str,
        config: FfmpegRkmppConfig,
    ) -> None:
        self.feed = feed
        self.physical_source = physical_source
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._stop = threading.Event()
        self._writer_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._packets: queue.Queue[EncodedH264Frame] = queue.Queue(maxsize=max(1, config.queue_size))
        self._stderr_lines: deque[str] = deque(maxlen=20)
        self._started_lock = threading.Lock()
        self._last_frame_ts: float | None = None
        self._packet_index = 0

    @property
    def active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def describe(self) -> dict[str, Any]:
        return {
            "physical_source": self.physical_source,
            "ffmpeg_path": self.config.ffmpeg_path,
            "codec": "h264_rkmpp",
            "active": self.active,
            "software_h264_fallback_allowed": False,
            "pipeline_profile": "staging_bgr24_cpu_pipe_to_h264_rkmpp",
            "input_memory": "cpu_bgr24_frames_from_camera_feed",
            "zero_copy_dmabuf": False,
            "hardware_scale_convert_in_source": False,
            "target_compliant": False,
            "input_from_single_capture_feed": True,
            "stdout_parser": "h264_annex_b_access_units",
            "stderr_tail": list(self._stderr_lines),
        }

    async def recv_encoded_h264(self) -> EncodedH264Frame:
        self._ensure_started()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._next_packet_blocking)

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except Exception:
                    process.kill()
        self._process = None

    def _ensure_started(self) -> None:
        with self._started_lock:
            if self.active:
                return
            frame = self._wait_for_frame()
            height, width = frame.shape[:2]
            command = build_ffmpeg_rkmpp_command(config=self.config, width=width, height=height)
            self._stop.clear()
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                name=f"ffmpeg-rkmpp-writer-{self.physical_source}",
                daemon=True,
            )
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"ffmpeg-rkmpp-reader-{self.physical_source}",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                name=f"ffmpeg-rkmpp-stderr-{self.physical_source}",
                daemon=True,
            )
            self._writer_thread.start()
            self._reader_thread.start()
            self._stderr_thread.start()

    def _wait_for_frame(self, timeout_s: float = 5.0) -> np.ndarray:
        deadline = time.time() + timeout_s
        while time.time() < deadline and not self._stop.is_set():
            frame_obj = self.feed.get_frame(annotated=False)
            if frame_obj is not None and getattr(frame_obj, "raw", None) is not None:
                return self._coerce_bgr24(frame_obj.raw)
            time.sleep(0.02)
        raise RuntimeError(f"no raw frame available for {self.physical_source}")

    @staticmethod
    def _coerce_bgr24(frame: np.ndarray) -> np.ndarray:
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("FFmpeg RKMPP source expects BGR24 frames")
        if frame.dtype != np.uint8:
            raise ValueError("FFmpeg RKMPP source expects uint8 frames")
        return np.ascontiguousarray(frame)

    def _writer_loop(self) -> None:
        assert self._process is not None
        stdin = self._process.stdin
        if stdin is None:
            return
        frame_interval = 1.0 / max(1, int(self.config.fps))
        while not self._stop.is_set() and self.active:
            frame_obj = self.feed.get_frame(annotated=False)
            if frame_obj is None or getattr(frame_obj, "raw", None) is None:
                time.sleep(0.02)
                continue
            frame_ts = float(getattr(frame_obj, "timestamp", 0.0) or 0.0)
            if self._last_frame_ts == frame_ts:
                time.sleep(min(0.01, frame_interval))
                continue
            self._last_frame_ts = frame_ts
            try:
                frame = self._coerce_bgr24(frame_obj.raw)
                stdin.write(frame.tobytes())
                stdin.flush()
            except Exception:
                self._stop.set()
                break
            time.sleep(frame_interval)

    def _reader_loop(self) -> None:
        assert self._process is not None
        stdout = self._process.stdout
        if stdout is None:
            return
        parser = H264AnnexBAccessUnitParser()
        try:
            while not self._stop.is_set() and self.active:
                chunk = stdout.read(4096)
                if not chunk:
                    break
                for access_unit in parser.push(chunk):
                    self._queue_access_unit(access_unit)
            for access_unit in parser.flush():
                self._queue_access_unit(access_unit)
        except Exception:
            self._stop.set()

    def _stderr_loop(self) -> None:
        assert self._process is not None
        stderr = self._process.stderr
        if stderr is None:
            return
        try:
            for raw_line in iter(stderr.readline, b""):
                if not raw_line or self._stop.is_set():
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    self._stderr_lines.append(line)
        except Exception:
            return

    def _queue_access_unit(self, data: bytes) -> None:
        if not data:
            return
        self._packet_index += 1
        pts = self._packet_index * int(90000 / max(1, int(self.config.fps)))
        encoded = EncodedH264Frame(data=data, pts=pts, time_base=H264_TIME_BASE)
        try:
            self._packets.put(encoded, timeout=0.5)
        except queue.Full:
            pass

    def _next_packet_blocking(self) -> EncodedH264Frame:
        while not self._stop.is_set():
            try:
                return self._packets.get(timeout=0.5)
            except queue.Empty:
                if self._process is not None and self._process.poll() is not None:
                    break
        raise RuntimeError(f"FFmpeg RKMPP H.264 source stopped for {self.physical_source}")


def create_ffmpeg_rkmpp_h264_source(**kwargs: Any) -> FfmpegRkmppH264Source:
    path = selected_ffmpeg_rkmpp_path(kwargs.get("selected_encoder_path"))
    if path is None:
        raise RuntimeError("selected encoder path is not production ffmpeg_rkmpp")
    return FfmpegRkmppH264Source(
        feed=kwargs["feed"],
        physical_source=str(kwargs["physical_source"]),
        config=FfmpegRkmppConfig(ffmpeg_path=path),
    )
