import threading
import time
from typing import Callable
import numpy as np

from .mog2_channel_detector import Mog2ChannelDetector
from defs.channel import ChannelDetection
from profiler import Profiler

FEEDER_ANALYSIS_INTERVAL_MS = 30
FEEDER_ANALYSIS_INTERVAL_S = FEEDER_ANALYSIS_INTERVAL_MS / 1000.0


class FeederAnalysisThread:
    _detector: Mog2ChannelDetector
    _thread: threading.Thread | None
    _stop_event: threading.Event
    _lock: threading.Lock
    _latest_detections: list[ChannelDetection]
    _get_gray: Callable[[], np.ndarray | None]
    _profiler: Profiler

    def __init__(
        self,
        detector: Mog2ChannelDetector,
        get_gray: Callable[[], np.ndarray | None],
        profiler: Profiler,
    ):
        self._detector = detector
        self._get_gray = get_gray
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

    def getDetections(self) -> list[ChannelDetection]:
        with self._lock:
            return list(self._latest_detections)

    def _loop(self) -> None:
        prof = self._profiler

        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            prof.hit("feeder_analysis.loop.calls")
            prof.mark("feeder_analysis.loop.interval_ms")

            with prof.timer("feeder_analysis.loop.total_ms"):
                with prof.timer("feeder_analysis.get_gray_ms"):
                    gray = self._get_gray()

                detections: list[ChannelDetection] = []
                if gray is not None:
                    with prof.timer("feeder_analysis.detect_ms"):
                        detections = self._detector.detect(gray)

                prof.observeValue("feeder_analysis.detection_count", float(len(detections)))

                with self._lock:
                    self._latest_detections = detections

            elapsed = time.monotonic() - loop_start
            sleep_time = FEEDER_ANALYSIS_INTERVAL_S - elapsed
            if sleep_time > 0:
                self._stop_event.wait(sleep_time)
