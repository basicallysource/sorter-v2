"""rev01 — faithful reproduction of the live sorter's coordinator-hot-path
bottleneck shape.

Architecture (same as live code):
  - 3 capture threads, each just reads frames into latest_frame.
  - Inference is NOT done by the capture thread. It is done by:
      (a) the FastAPI request-handler thread (anyio worker pool) as a
          side effect of rendering the preview overlay, AND
      (b) the coordinator thread inline during classification.step()
          (the "carousel on main thread" leak).
  - Detections sit in shared caches: _det_object_cache, _det_dynamic_cache,
    _carousel_cache — three separate slots, same misshapen split as live.
  - One coordinator thread runs feeder.step() -> classification.step() ->
    distribution.step() sequentially in a tight loop.
  - feeder.step() reads ALL 3 role caches, runs a Python list comprehension
    per role to convert into a domain object, and sends a mock bus command.
  - classification.step() reads carousel cache; if missing/stale, runs
    inference inline (FAITHFUL LEAK — this is the [INFER_ON_MAIN_THREAD]
    bug captured 2026-05-27).
  - Bus is a single lock with a fixed simulated round-trip per call.

Expected result on the Pi: coordinator ~0.6 Hz, frame->decision ~1s median.
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


log = logging.getLogger("rev01")

# Mirror live LOOP_TICK_MS (defs/consts.py): main loop sleeps 20ms per tick.
# This is in the real code — not a fake delay.
LOOP_TICK_MS = 20


class Rev01:
    def __init__(self, cfg: BenchConfig, metrics: Metrics) -> None:
        self.cfg = cfg
        self.metrics = metrics
        self.bus = MockBus(cfg.bus_command_ms, metrics)

        # One RKNN runner per camera, each pinned to its own NPU core (mirrors
        # live code's per-role processor map). Shared between any thread that
        # asks (preview handler, coordinator). The runner's internal lock
        # serializes calls per runner.
        self.runners: Dict[str, RknnRunner] = {
            cam.name: RknnRunner(cfg.model_path, imgsz=320, core_mask_name=cam.core_mask)
            for cam in cfg.cameras
        }

        # Capture threads — frame producers only. No inference in their loop.
        self.captures: Dict[str, CaptureThread] = {}
        for cam in cfg.cameras:
            self.captures[cam.name] = CaptureThread(
                cam.name, cam.device, cfg.width, cfg.height, cfg.fps_target,
                on_frame=None,
            )

        # Three separate detection slots — the same misshapen split the live
        # code has: object cache, dynamic cache, carousel cache. Coordinator
        # reads the object cache. Preview handler writes the object cache.
        # Carousel cache is special-cased by classification.step().
        self._det_object_cache: Dict[str, tuple[float, object]] = {}
        self._det_carousel_cache: Optional[tuple[float, object]] = None
        self._cache_lock = threading.RLock()

        self._stop = threading.Event()
        self._coord_thread: Optional[threading.Thread] = None

    # --- detection side-effect-on-render (faithful leak) ---
    def _run_inference_for_role(self, role: str, frame_bgr: np.ndarray) -> object:
        runner = self.runners[role]
        with Timer(self.metrics, f"infer.{role}.ms"):
            n, _ = runner.infer(frame_bgr)
        self.metrics.hit_by_thread(f"infer.{role}.by_thread")
        # Same shape as live: raw bboxes attached to the detection result so
        # downstream convert can filter+wrap them. RKNN returned `n` output
        # tensors — we don't decode them (that's outside the bench's concern),
        # so we use a fixed synthetic bbox list whose count matches the live
        # workload (20 raw candidates per detection on average).
        return {"bboxes": synthetic_bboxes(50), "ts": time.time()}

    # called by the FastAPI handler thread, on every served frame.
    # Faithful to the live overlay lambda: calls inference, runs the channel-
    # detection convert (polygon filter + ChannelDetection list comp), writes
    # the cache. The convert is the GIL-heavy Python work that matters.
    def _preview_overlay(self, role: str, frame_bgr: np.ndarray) -> np.ndarray:
        det = self._run_inference_for_role(role, frame_bgr)
        # Live preview overlay path runs the full dispatcher filter pipeline
        # (score, ignored-region, NMS, channel polygon) — same here.
        with Timer(self.metrics, f"preview.{role}.convert_ms"):
            _ = full_filter_pipeline(role, det["bboxes"])
        with self._cache_lock:
            self._det_object_cache[role] = (time.time(), det)
            if role == "carousel":
                self._det_carousel_cache = (time.time(), det)
        return frame_bgr

    # --- coordinator subsystem steps ---
    def _feeder_step(self) -> None:
        with Timer(self.metrics, "coordinator.feeder_ms"):
            # Read all three role caches, convert via a Python list comp per
            # role. This is the GIL-starved 400ms hot spot in live code.
            with self._cache_lock:
                snapshot = dict(self._det_object_cache)
            workload_x = self.cfg.workload_x
            for role in ("c_channel_2", "c_channel_3", "carousel"):
                with Timer(self.metrics, f"coordinator.feeder.{role}.convert_ms"):
                    entry = snapshot.get(role)
                    if entry is None:
                        continue
                    _, det = entry
                    # Coordinator runs the multi-stage dispatcher per role
                    # per tick. workload_x scales the amount of per-role work
                    # to model what the live subsystem state machines do
                    # beyond a single filter pass — exit-zone checks, busy
                    # timers, downstream readiness, IgnoredRegion overlay
                    # data, multi-channel analysis, etc.
                    for _ in range(workload_x):
                        _ = full_filter_pipeline(role, det["bboxes"])
            self.bus.send("c_channel_3_rotor_move")

    def _classification_step(self) -> None:
        with Timer(self.metrics, "coordinator.classification_ms"):
            # FAITHFUL LEAK: if the carousel cache is missing or stale,
            # run inference inline on this thread. That's exactly what
            # _buildCarouselDetectionPayload does in live code.
            now = time.time()
            with self._cache_lock:
                entry = self._det_carousel_cache
            stale = entry is None or (now - entry[0]) > 0.15
            if stale:
                frame = self.captures["carousel"].latest_frame
                if frame is not None:
                    det = self._run_inference_for_role("carousel", frame.raw)
                    with self._cache_lock:
                        self._det_carousel_cache = (time.time(), det)
            self.bus.send("chute_stepper_set_speed")

    def _distribution_step(self) -> None:
        with Timer(self.metrics, "coordinator.distribution_ms"):
            pass

    def _coordinator_loop(self) -> None:
        # Mirrors live main.py: each iteration runs controller.step() (which
        # runs coordinator.step() when state is RUNNING), then sleeps
        # LOOP_TICK_MS = 20ms. Real code, not a fake delay.
        sleep_s = LOOP_TICK_MS / 1000.0
        while not self._stop.is_set():
            tick_start = time.perf_counter()
            self.metrics.hit_by_thread("coordinator.step.by_thread")
            with Timer(self.metrics, "coordinator.step.total_ms"):
                self._feeder_step()
                self._classification_step()
                self._distribution_step()
            with self._cache_lock:
                snap = dict(self._det_object_cache)
            ages_ms = [(time.time() - ts) * 1000.0 for ts, _ in snap.values()]
            if ages_ms:
                self.metrics.observe("frame_to_decision_ms", min(ages_ms))
            time.sleep(sleep_s)
            self.metrics.observe(
                "coordinator.step.interval_ms",
                (time.perf_counter() - tick_start) * 1000.0,
            )

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
        self._coord_thread = threading.Thread(
            target=self._coordinator_loop, daemon=True, name="coordinator"
        )
        self._coord_thread.start()

        # Drive preview traffic — without a client pulling frames the
        # AnyIO handler thread never runs. Spawn an internal "client" that
        # GETs all three previews continuously.
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
                    # Read bytes off the MJPEG stream to keep the handler
                    # generator alive. Drop the bytes — we just want the
                    # encoder/handler thread doing the work.
                    while not self._client_stop.is_set():
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
            except Exception:
                time.sleep(0.5)

    def stop(self) -> None:
        self._stop.set()
        self._client_stop.set()
        if self._coord_thread:
            self._coord_thread.join(timeout=2.0)
        for cap in self.captures.values():
            cap.stop()
        # Server is daemon; let process exit kill it
