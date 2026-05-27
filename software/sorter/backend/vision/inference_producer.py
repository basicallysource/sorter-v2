"""Rev03 — per-camera inference producer threads.

Architecture rationale: the live system was at 0.6 Hz because inference fired
as a side effect of preview rendering (AnyIO worker threads) and on the
coordinator main thread (carousel inline), while the coordinator's hot
read-path ran a pure-Python ChannelDetection list comp that GIL-starved
against ~15 other Python threads. Wall-clock per role: 130 ms for sub-ms work.

This module breaks that. One dedicated producer thread per camera owns:
    capture.latest_frame  →  RKNN inference  →  filter to channel  →  slot.write()

Producers never compete with each other for the GIL during inference (the NPU
call releases it), and each producer's polygon-filter step is its own thread's
problem, not the coordinator's. Coordinator becomes a pure consumer that reads
slot refs and decides — no inference, no convert, no image processing.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Dict, List, Optional, Tuple, cast, TYPE_CHECKING

import numpy as np

from .detection_registry import DetectionScope

if TYPE_CHECKING:
    from defs.channel import ChannelDetection
    from .classification_detection import ClassificationDetectionResult
    from .vision_manager import VisionManager


# Tuple shape stored in a slot:
#   (frame_timestamp, raw_detection_result, channel_detections)
# - raw_detection_result keeps backward compatibility with overlay drawing
#   code that expects ClassificationDetectionResult.
# - channel_detections is pre-converted (polygon filter + ChannelDetection
#   list comp) by the producer thread. The coordinator reads this directly
#   and skips the 130 ms-per-role Python convert that was the bottleneck.
SlotEntry = Tuple[
    float,
    Optional["ClassificationDetectionResult"],
    List["ChannelDetection"],
]


class LatestDetectionSlot:
    """Single atomic-ref slot. Producer overwrites; consumers read whatever
    the most recent write was. Tuple assignment is atomic under the GIL, so
    no lock is needed for the slot itself."""

    __slots__ = ("_ref",)

    def __init__(self) -> None:
        self._ref: Optional[SlotEntry] = None

    def write(
        self,
        ts: float,
        det: Optional["ClassificationDetectionResult"],
        channel_dets: List["ChannelDetection"],
    ) -> None:
        self._ref = (ts, det, channel_dets)

    def read(self) -> Optional[SlotEntry]:
        return self._ref


class InferenceProducer:
    """One thread per camera. Capture → infer → filter → write slot."""

    def __init__(
        self,
        role: str,
        vision_manager: "VisionManager",
        *,
        scope: str = "feeder",
        conf_threshold: Optional[float] = None,
        idle_sleep_s: float = 0.005,
        no_frame_sleep_s: float = 0.010,
    ) -> None:
        self.role = role
        self._vm = vision_manager
        self._scope = scope
        self._conf_threshold = conf_threshold
        self._idle_sleep_s = idle_sleep_s
        self._no_frame_sleep_s = no_frame_sleep_s

        self.slot = LatestDetectionSlot()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"producer-{role}"
        )
        self._last_frame_ts: float = -1.0

        # SORT tracker runs on its own thread, fed by a small queue. This
        # pipelines inference (NPU, GIL released) against the tracker's
        # pure-Python work instead of running them serially on the producer
        # thread. maxsize=2 + drop-oldest keeps frame-memory bounded and
        # tracking on the freshest data; the producer already subsamples to
        # whatever rate inference can sustain, so dropping a backlog frame
        # under load loses nothing the inline path would have kept.
        self._tracker_q: "queue.Queue[Tuple[Optional[ClassificationDetectionResult], float, np.ndarray]]" = queue.Queue(maxsize=2)
        self._tracker_thread = threading.Thread(
            target=self._tracker_loop, daemon=True, name=f"tracker-{role}"
        )

        # Counters for /perf telemetry — also visible via runtime_stats.
        self._iter_count = 0
        self._skipped_same_frame = 0
        self._skipped_no_frame = 0
        self._inferred = 0
        self._errors = 0
        self._tracker_dropped = 0

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._tracker_thread.start()
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self._tracker_thread.is_alive():
            self._tracker_thread.join(timeout=timeout)

    def _resolve_algorithm(self) -> Optional[str]:
        vm = self._vm
        if self._scope == "carousel" and not vm._feederTrackerRoles().__contains__("carousel"):
            return vm.getCarouselDetectionAlgorithm()
        return vm.getFeederDetectionAlgorithm(self.role)

    def _capture_thread(self):
        return self._vm.getCaptureThreadForRole(self.role)

    def _loop(self) -> None:
        vm = self._vm
        prof = vm.gc.profiler
        runtime_stats = vm.gc.runtime_stats
        is_local = vm._isLocalModelDetectionAlgorithm

        while not self._stop.is_set():
            self._iter_count += 1
            prof.hit(f"producer.{self.role}.iterations")
            try:
                capture = self._capture_thread()
                if capture is None:
                    self._skipped_no_frame += 1
                    self._stop.wait(self._no_frame_sleep_s)
                    continue
                frame = capture.latest_frame
                if frame is None:
                    self._skipped_no_frame += 1
                    self._stop.wait(self._no_frame_sleep_s)
                    continue
                # Skip if same frame as last iteration — no work to do.
                if frame.timestamp == self._last_frame_ts:
                    self._skipped_same_frame += 1
                    self._stop.wait(self._idle_sleep_s)
                    continue

                algorithm = self._resolve_algorithm()
                if algorithm is None or not is_local(algorithm):
                    # Non-local algorithm (gemini, mog2, etc.) — leave the
                    # legacy code path responsible; producer idles.
                    self._stop.wait(0.05)
                    continue

                wall_t0 = time.perf_counter()
                raw = vm._runHiveDetection(
                    algorithm,
                    frame.raw,
                    scope=cast(DetectionScope, self._scope),
                    role=self.role,
                    conf_threshold=self._conf_threshold,
                )
                infer_ms = (time.perf_counter() - wall_t0) * 1000.0
                filter_t0 = time.perf_counter()
                filtered = vm._filterFeederDetectionResultToChannel(self.role, raw)
                # Pre-convert to ChannelDetection list on THIS thread so the
                # coordinator's read path is a pure ref read.
                channel_dets = vm._channelDetectionsFromDynamicResult(
                    self.role, filtered
                )
                convert_ms = (time.perf_counter() - filter_t0) * 1000.0
                wall_ms = (time.perf_counter() - wall_t0) * 1000.0

                self._last_frame_ts = frame.timestamp
                self.slot.write(frame.timestamp, filtered, channel_dets)
                self._inferred += 1
                prof.hit(f"producer.{self.role}.inferred")
                runtime_stats.observePerfMs(f"producer.{self.role}.cycle_ms", wall_ms)
                runtime_stats.observePerfMs(f"producer.{self.role}.infer_ms", infer_ms)
                runtime_stats.observePerfMs(f"producer.{self.role}.convert_ms", convert_ms)
                runtime_stats.observePerfMs(
                    f"producer.{self.role}.frame_age_ms",
                    max(0.0, (time.time() - float(frame.timestamp)) * 1000.0),
                )

                # Mirror to legacy caches so any read paths we didn't migrate
                # (sample collection, gemini routes) keep functioning with
                # fresh data.
                vm._feeder_object_detection_cache[self.role] = (frame.timestamp, filtered)
                vm._feeder_dynamic_detection_cache[self.role] = (frame.timestamp, filtered)
                if self.role == "carousel":
                    vm._carousel_dynamic_detection_cache = (frame.timestamp, filtered)

                # Hand the tracker its work on the dedicated thread. Drop the
                # oldest queued item under backpressure rather than block the
                # producer (keeps inference at full NPU cadence).
                self._enqueue_tracker(filtered, frame.timestamp, frame.raw)

            except Exception as exc:
                self._errors += 1
                prof.hit(f"producer.{self.role}.errors")
                try:
                    vm.gc.logger.warning(
                        f"InferenceProducer[{self.role}] error: {exc}"
                    )
                except Exception:
                    pass
                self._stop.wait(0.1)

    def _enqueue_tracker(
        self,
        filtered: "Optional[ClassificationDetectionResult]",
        ts: float,
        frame_raw: "np.ndarray",
    ) -> None:
        item = (filtered, ts, frame_raw)
        try:
            self._tracker_q.put_nowait(item)
        except queue.Full:
            try:
                self._tracker_q.get_nowait()
                self._tracker_dropped += 1
                self._vm.gc.profiler.hit(f"producer.{self.role}.tracker_dropped")
            except queue.Empty:
                pass
            try:
                self._tracker_q.put_nowait(item)
            except queue.Full:
                pass

    def _tracker_loop(self) -> None:
        vm = self._vm
        prof = vm.gc.profiler
        runtime_stats = vm.gc.runtime_stats
        while not self._stop.is_set():
            try:
                filtered, ts, frame_raw = self._tracker_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                t0 = time.perf_counter()
                vm._updateFeederTracker(self.role, filtered, ts, frame_bgr=frame_raw)
                runtime_stats.observePerfMs(
                    f"tracker.{self.role}.update_ms",
                    (time.perf_counter() - t0) * 1000.0,
                )
            except Exception as tex:
                prof.hit(f"tracker.{self.role}.errors")
                vm.gc.logger.warning(f"tracker-{self.role} update error: {tex}")


class ProducerRegistry:
    """Owns the per-role producer threads. Start/stop together."""

    def __init__(self, vision_manager: "VisionManager") -> None:
        self._vm = vision_manager
        self._producers: Dict[str, InferenceProducer] = {}

    def __contains__(self, role: str) -> bool:
        return role in self._producers

    def get(self, role: str) -> Optional[InferenceProducer]:
        return self._producers.get(role)

    def slot(self, role: str) -> Optional[LatestDetectionSlot]:
        prod = self._producers.get(role)
        return prod.slot if prod is not None else None

    def roles(self):
        return tuple(self._producers.keys())

    def add(
        self,
        role: str,
        *,
        scope: str = "feeder",
        conf_threshold: Optional[float] = None,
    ) -> InferenceProducer:
        if role in self._producers:
            return self._producers[role]
        prod = InferenceProducer(
            role,
            self._vm,
            scope=scope,
            conf_threshold=conf_threshold,
        )
        self._producers[role] = prod
        return prod

    def start_all(self) -> None:
        for prod in self._producers.values():
            if not prod.is_alive:
                prod.start()

    def stop_all(self, timeout: float = 2.0) -> None:
        for prod in self._producers.values():
            prod.stop(timeout=timeout)
        self._producers.clear()
