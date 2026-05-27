"""rev02 — same workload, restructured for parallelism.

Architecture (the proposed fix):
  - 3 capture threads. Each one ALSO runs RKNN inference on its own frame
    and writes BOTH latest_frame and latest_detection to per-camera slots.
    No separate inference thread, no pool, no dispatcher tree.
  - 3 subsystem threads (feeder, classification, distribution). Each runs
    in its own loop at its own rate. Reads detection slots. Sends bus
    commands. Nothing waits on another subsystem.
  - Preview overlay handler reads the detection slot — never runs inference.
  - One bus arbiter: the existing MockBus lock already serializes per-call,
    which is enough for the bench. (In real life this would be a dedicated
    serial-writer thread reading per-subsystem outbound queues.)
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.bus import MockBus
from common.camera import CaptureThread, Frame
from common.config import BenchConfig
from common.convert import (
    channel_detections_from_result,
    full_filter_pipeline,
    synthetic_bboxes,
)
from common.metrics import Metrics, Timer
from common.preview import make_server, run_server_in_thread
from common.rknn_runner import RknnRunner


log = logging.getLogger("rev02")

# Each subsystem thread runs at its own rate. We use the same LOOP_TICK_MS
# the live main loop uses (20ms) so the comparison is honest: same per-tick
# pace, the only architectural difference is parallelism and producer/consumer
# separation.
LOOP_TICK_MS = 20


class _DetectionSlot:
    """Latest-result slot. Atomic single-reference write; readers see whatever
    the producer most recently wrote."""
    __slots__ = ("_ref",)

    def __init__(self) -> None:
        self._ref: Optional[tuple[float, object]] = None

    def write(self, ts: float, det: object) -> None:
        # Single assignment of a tuple reference is atomic under the GIL.
        self._ref = (ts, det)

    def read(self) -> Optional[tuple[float, object]]:
        return self._ref


class Rev02:
    def __init__(self, cfg: BenchConfig, metrics: Metrics) -> None:
        self.cfg = cfg
        self.metrics = metrics
        self.bus = MockBus(cfg.bus_command_ms, metrics)

        self.runners: Dict[str, RknnRunner] = {
            cam.name: RknnRunner(cfg.model_path, imgsz=320, core_mask_name=cam.core_mask)
            for cam in cfg.cameras
        }

        # One detection slot per camera. Producer = capture thread for that
        # camera. Consumers = subsystem threads + preview handler.
        self.slots: Dict[str, _DetectionSlot] = {
            cam.name: _DetectionSlot() for cam in cfg.cameras
        }

        # Capture-with-inference threads. The on_frame hook IS the inference
        # producer — same thread that read the V4L2 frame runs RKNN on it
        # and writes the slot.
        self.captures: Dict[str, CaptureThread] = {}
        for cam in cfg.cameras:
            self.captures[cam.name] = CaptureThread(
                cam.name, cam.device, cfg.width, cfg.height, cfg.fps_target,
                on_frame=self._make_capture_inference_hook(cam.name),
            )

        self._stop = threading.Event()
        self._subsys_threads = []

    def _make_capture_inference_hook(self, role: str):
        runner = self.runners[role]
        metrics = self.metrics
        slot = self.slots[role]
        def hook(frame: Frame) -> None:
            with Timer(metrics, f"infer.{role}.ms"):
                n, _ = runner.infer(frame.raw)
            metrics.hit_by_thread(f"infer.{role}.by_thread")
            slot.write(frame.timestamp, {"bboxes": synthetic_bboxes(50), "n": n})
        return hook

    # --- subsystem loops ---
    def _feeder_loop(self) -> None:
        sleep_s = LOOP_TICK_MS / 1000.0
        workload_x = self.cfg.workload_x
        while not self._stop.is_set():
            tick_start = time.perf_counter()
            self.metrics.hit_by_thread("subsystem.feeder.step.by_thread")
            with Timer(self.metrics, "subsystem.feeder.step_ms"):
                ages_ms = []
                for role in ("c_channel_2", "c_channel_3", "carousel"):
                    with Timer(self.metrics, f"subsystem.feeder.{role}.convert_ms"):
                        entry = self.slots[role].read()
                        if entry is None:
                            continue
                        ts, det = entry
                        ages_ms.append((time.time() - ts) * 1000.0)
                        for _ in range(workload_x):
                            _ = full_filter_pipeline(role, det["bboxes"])
                self.bus.send("c_channel_3_rotor_move")
                if ages_ms:
                    self.metrics.observe("frame_to_decision_feeder_ms", min(ages_ms))
            time.sleep(sleep_s)
            self.metrics.observe(
                "subsystem.feeder.interval_ms",
                (time.perf_counter() - tick_start) * 1000.0,
            )

    def _classification_loop(self) -> None:
        sleep_s = LOOP_TICK_MS / 1000.0
        while not self._stop.is_set():
            tick_start = time.perf_counter()
            self.metrics.hit_by_thread("subsystem.classification.step.by_thread")
            with Timer(self.metrics, "subsystem.classification.step_ms"):
                entry = self.slots["carousel"].read()
                if entry is not None:
                    ts, det = entry
                    for _ in range(self.cfg.workload_x):
                        _ = full_filter_pipeline("carousel", det["bboxes"])
                    self.metrics.observe(
                        "frame_to_decision_classification_ms",
                        (time.time() - ts) * 1000.0,
                    )
                self.bus.send("chute_stepper_set_speed")
            time.sleep(sleep_s)
            self.metrics.observe(
                "subsystem.classification.interval_ms",
                (time.perf_counter() - tick_start) * 1000.0,
            )

    def _distribution_loop(self) -> None:
        sleep_s = LOOP_TICK_MS / 1000.0
        while not self._stop.is_set():
            tick_start = time.perf_counter()
            self.metrics.hit_by_thread("subsystem.distribution.step.by_thread")
            with Timer(self.metrics, "subsystem.distribution.step_ms"):
                pass
            time.sleep(sleep_s)
            self.metrics.observe(
                "subsystem.distribution.interval_ms",
                (time.perf_counter() - tick_start) * 1000.0,
            )

    # --- preview path: pure slot read, no inference ---
    def _preview_overlay(self, role: str, frame_bgr: np.ndarray) -> np.ndarray:
        # Just read the slot. The capture thread is already running inference.
        _ = self.slots[role].read()
        return frame_bgr

    def start(self) -> None:
        for cap in self.captures.values():
            cap.start()
        self.server = make_server(
            {name: (lambda c=cap: c.latest_frame.raw if c.latest_frame else None)
             for name, cap in self.captures.items()},
            self._preview_overlay,
            self.cfg.preview_port,
            self.metrics,
        )
        self.server_thread = run_server_in_thread(self.server)
        for target, name in (
            (self._feeder_loop, "feeder"),
            (self._classification_loop, "classification"),
            (self._distribution_loop, "distribution"),
        ):
            t = threading.Thread(target=target, daemon=True, name=f"subsystem-{name}")
            t.start()
            self._subsys_threads.append(t)

        # Drive preview just like rev01 so the comparison is apples to apples.
        self._client_stop = threading.Event()
        self._client_threads = []
        for cam in self.cfg.cameras:
            t = threading.Thread(
                target=self._drive_preview_client,
                args=(cam.name,),
                daemon=True,
                name=f"preview-client-{cam.name}",
            )
            t.start()
            self._client_threads.append(t)

    def _drive_preview_client(self, role: str) -> None:
        import urllib.request
        url = f"http://127.0.0.1:{self.cfg.preview_port}/preview/{role}"
        while not self._client_stop.is_set():
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    while not self._client_stop.is_set():
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
            except Exception:
                time.sleep(0.5)

    def stop(self) -> None:
        self._stop.set()
        self._client_stop.set()
        for t in self._subsys_threads:
            t.join(timeout=2.0)
        for cap in self.captures.values():
            cap.stop()
