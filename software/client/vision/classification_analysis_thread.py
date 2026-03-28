import threading
import time
from typing import Callable, Tuple, List
import numpy as np

from .heatmap_diff import HeatmapDiff
from profiler import Profiler
from logger import Logger

ANALYSIS_INTERVAL_MS = 30
ANALYSIS_INTERVAL_S = ANALYSIS_INTERVAL_MS / 1000.0
MIN_BBOX_DIMENSION_PX = 100
MIN_BBOX_AREA_PX = 20000


class ClassificationAnalysisThread:
    _heatmap: HeatmapDiff
    _thread: threading.Thread | None
    _stop_event: threading.Event
    _lock: threading.Lock
    _latest_bboxes: List[Tuple[int, int, int, int]]
    _get_gray: Callable[[], np.ndarray | None]
    _profiler: Profiler
    _logger: Logger
    _name: str

    def __init__(
        self,
        name: str,
        heatmap: HeatmapDiff,
        get_gray: Callable[[], np.ndarray | None],
        profiler: Profiler,
        logger: Logger,
        min_bbox_dimension_px: int = MIN_BBOX_DIMENSION_PX,
        min_bbox_area_px: int = MIN_BBOX_AREA_PX,
    ):
        self._name = name
        self._heatmap = heatmap
        self._get_gray = get_gray
        self._profiler = profiler
        self._logger = logger
        self._min_bbox_dimension_px = min_bbox_dimension_px
        self._min_bbox_area_px = min_bbox_area_px
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_bboxes = []
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def getBboxes(self) -> List[Tuple[int, int, int, int]]:
        with self._lock:
            return list(self._latest_bboxes)

    def getCombinedBbox(self) -> Tuple[int, int, int, int] | None:
        with self._lock:
            if not self._latest_bboxes:
                return None
            return max(self._latest_bboxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))

    def _loop(self) -> None:
        prof = self._profiler
        prefix = f"classification_analysis.{self._name}"

        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            prof.hit(f"{prefix}.loop.calls")
            prof.mark(f"{prefix}.loop.interval_ms")

            with prof.timer(f"{prefix}.loop.total_ms"):
                with prof.timer(f"{prefix}.get_gray_ms"):
                    gray = self._get_gray()

                if gray is not None:
                    with prof.timer(f"{prefix}.push_frame_ms"):
                        self._heatmap.pushFrame(gray)

                bboxes: List[Tuple[int, int, int, int]] = []
                if self._heatmap.has_baseline:
                    with prof.timer(f"{prefix}.compute_bboxes_ms"):
                        raw_bboxes = self._heatmap.computeBboxes()
                    prof.observeValue(f"{prefix}.raw_bbox_count", float(len(raw_bboxes)))
                    for bbox in raw_bboxes:
                        w = bbox[2] - bbox[0]
                        h = bbox[3] - bbox[1]
                        area = w * h
                        if w < self._min_bbox_dimension_px or h < self._min_bbox_dimension_px or area < self._min_bbox_area_px:
                            prof.hit(f"{prefix}.bbox_rejected")
                            continue
                        bboxes.append(bbox)
                    prof.observeValue(f"{prefix}.bbox_count", float(len(bboxes)))

                with self._lock:
                    self._latest_bboxes = bboxes

            elapsed = time.monotonic() - loop_start
            sleep_time = ANALYSIS_INTERVAL_S - elapsed
            if sleep_time > 0:
                self._stop_event.wait(sleep_time)
