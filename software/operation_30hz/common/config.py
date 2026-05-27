"""Bench config: 3 cameras + 1 model. Values picked to mirror the live
sorter's c_channel_2 / c_channel_3 / carousel triple.

Override via env vars when needed."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List


DEFAULT_MODEL = (
    "/home/orangepi/sorter-v2-fresh/software/sorter/backend/bundled_models/"
    "r3-c-channel-yolo11n-320/exports/sorter-npu-r3_yolo11n-320_rk3588-int8_c-channel_2026-05-23.rknn"
)


@dataclass
class CameraSpec:
    name: str
    device: str
    core_mask: str  # NPU_CORE_0 / _1 / _2 / _0_1_2 / _AUTO


@dataclass
class BenchConfig:
    duration_s: float
    cameras: List[CameraSpec]
    model_path: Path
    width: int
    height: int
    fps_target: int
    preview_port: int
    bus_command_ms: float  # simulated USB serial round trip
    workload_x: int  # multiplier for per-step subsystem work
    output_path: Path


def from_env(rev_label: str, duration_s: float, output_dir: Path, workload_x: int = 1) -> BenchConfig:
    model = Path(os.environ.get("OP30HZ_MODEL", DEFAULT_MODEL))
    cams = [
        CameraSpec(name="c_channel_2", device="/dev/video0", core_mask="NPU_CORE_0"),
        CameraSpec(name="c_channel_3", device="/dev/video2", core_mask="NPU_CORE_1"),
        CameraSpec(name="carousel",    device="/dev/video4", core_mask="NPU_CORE_2"),
    ]
    ts = int(__import__("time").time())
    return BenchConfig(
        duration_s=duration_s,
        cameras=cams,
        model_path=model,
        width=int(os.environ.get("OP30HZ_W", "640")),
        height=int(os.environ.get("OP30HZ_H", "480")),
        fps_target=int(os.environ.get("OP30HZ_FPS", "30")),
        preview_port=int(os.environ.get("OP30HZ_PORT", "8088")),
        bus_command_ms=float(os.environ.get("OP30HZ_BUS_MS", "5.0")),
        workload_x=workload_x,
        output_path=output_dir / f"{rev_label}_w{workload_x}_{ts}.json",
    )
