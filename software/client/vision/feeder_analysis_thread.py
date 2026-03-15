import threading
import time
from typing import Callable, Dict
import numpy as np

from .heatmap_diff import HeatmapDiff
from profiler import Profiler

FEEDER_ANALYSIS_INTERVAL_MS = 30
FEEDER_ANALYSIS_INTERVAL_S = FEEDER_ANALYSIS_INTERVAL_MS / 1000.0


class FeederAnalysisThread:
    _heatmap: HeatmapDiff
    _thread: threading.Thread | None
    _stop_event: threading.Event
    _lock: threading.Lock
    _latest_detections: list
    _get_gray: Callable[[], np.ndarray | None]
    _channel_polygons: Dict[str, np.ndarray] | None
    _channel_angles: Dict[str, float]
    _channel_masks: Dict[str, np.ndarray]
    _profiler: Profiler

    def __init__(
        self,
        heatmap: HeatmapDiff,
        get_gray: Callable[[], np.ndarray | None],
        channel_polygons: Dict[str, np.ndarray] | None,
        channel_angles: Dict[str, float],
        channel_masks: Dict[str, np.ndarray],
        profiler: Profiler,
    ):
        self._heatmap = heatmap
        self._get_gray = get_gray
        self._channel_polygons = channel_polygons
        self._channel_angles = channel_angles
        self._channel_masks = channel_masks
        self._profiler = profiler
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_detections = []
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def getDetections(self) -> list:
        with self._lock:
            return list(self._latest_detections)

    def _loop(self) -> None:
        from defs.channel import ChannelDetection
        from subsystems.feeder.analysis import computeChannelGeometry, determineObjectChannel

        prof = self._profiler

        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            prof.hit("feeder_analysis.loop.calls")
            prof.mark("feeder_analysis.loop.interval_ms")

            with prof.timer("feeder_analysis.loop.total_ms"):
                with prof.timer("feeder_analysis.get_gray_ms"):
                    gray = self._get_gray()

                if gray is not None:
                    with prof.timer("feeder_analysis.push_frame_ms"):
                        self._heatmap.pushFrame(gray)

                detections: list[ChannelDetection] = []
                if self._heatmap.has_baseline and self._channel_polygons is not None:
                    with prof.timer("feeder_analysis.compute_bboxes_ms"):
                        bboxes = self._heatmap.computeBboxes()
                    prof.observeValue("feeder_analysis.bbox_count", float(len(bboxes)))

                    if bboxes:
                        with prof.timer("feeder_analysis.compute_geometry_ms"):
                            geometry = computeChannelGeometry(
                                self._channel_polygons, self._channel_angles, self._channel_masks,
                            )
                        with prof.timer("feeder_analysis.determine_channels_ms"):
                            for bbox in bboxes:
                                x1, y1, x2, y2 = bbox
                                ch = determineObjectChannel(((x1 + x2) / 2.0, (y1 + y2) / 2.0), geometry)
                                if ch is not None:
                                    detections.append(ChannelDetection(bbox=bbox, channel_id=ch.channel_id, channel=ch))

                prof.observeValue("feeder_analysis.detection_count", float(len(detections)))

                with self._lock:
                    self._latest_detections = detections

            elapsed = time.monotonic() - loop_start
            sleep_time = FEEDER_ANALYSIS_INTERVAL_S - elapsed
            if sleep_time > 0:
                self._stop_event.wait(sleep_time)
