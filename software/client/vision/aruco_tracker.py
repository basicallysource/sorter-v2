import threading
import time
from typing import Dict, Tuple, Optional
import cv2
import cv2.aruco as aruco
import numpy as np

from global_config import GlobalConfig
from .camera import CaptureThread

ARUCO_TAG_CACHE_MS = 100
ARUCO_UPDATE_INTERVAL_MS = 120

# stationary tags (c-channel geometry, center markers, etc.) — lean hard into stability
ARUCO_STATIONARY_EMA_ALPHA = 0.025
ARUCO_STATIONARY_MAX_JUMP_PX = 10

# moving tags (carousel platforms) — allow more movement
ARUCO_MOVING_EMA_ALPHA = 0.3
ARUCO_MOVING_MAX_JUMP_PX = 80

ARUCO_TAG_DETECTION_PARAMS = {
    "minMarkerPerimeterRate": 0.003,
    "perspectiveRemovePixelPerCell": 4,
    "perspectiveRemoveIgnoredMarginPerCell": 0.3,
    "adaptiveThreshWinSizeMin": 3,
    "adaptiveThreshWinSizeMax": 53,
    "adaptiveThreshWinSizeStep": 4,
    "errorCorrectionRate": 1.0,
    "polygonalApproxAccuracyRate": 0.05,
    "minDistanceToBorder": 3,
    "maxErroneousBitsInBorderRate": 0.35,
    "cornerRefinementMethod": 0,
    "cornerRefinementWinSize": 5,
}


def mkArucoDetector() -> aruco.ArucoDetector:
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    params = aruco.DetectorParameters()
    for k, v in ARUCO_TAG_DETECTION_PARAMS.items():
        setattr(params, k, v)
    return aruco.ArucoDetector(dictionary, params)


def detectArucoTags(gray: np.ndarray, detector: aruco.ArucoDetector) -> Dict[int, Tuple[float, float]]:
    corners, ids, _ = detector.detectMarkers(gray)
    tags: Dict[int, Tuple[float, float]] = {}
    if ids is not None:
        for i, tag_id in enumerate(ids.flatten()):
            tag_corners = corners[i][0]
            cx = float(np.mean(tag_corners[:, 0]))
            cy = float(np.mean(tag_corners[:, 1]))
            tags[int(tag_id)] = (cx, cy)
    return tags


class ArucoTagSmoother:
    """Stateful EMA smoother with outlier rejection. Call update() each frame with raw detected tags.
    moving_ids: tag IDs that can move (carousel); all others treated as stationary."""

    def __init__(self, moving_ids: Optional[set] = None):
        self._moving_ids = moving_ids if moving_ids is not None else set()
        self._smoothed: Dict[int, Tuple[float, float]] = {}
        self._cache: Dict[int, Tuple[Tuple[float, float], float]] = {}

    def update(self, raw_tags: Dict[int, Tuple[float, float]]) -> Dict[int, Tuple[float, float]]:
        current_time = time.time()
        result: Dict[int, Tuple[float, float]] = {}
        detected_ids = set()

        for tag_id, (cx, cy) in raw_tags.items():
            moving = tag_id in self._moving_ids
            alpha = ARUCO_MOVING_EMA_ALPHA if moving else ARUCO_STATIONARY_EMA_ALPHA
            max_jump = ARUCO_MOVING_MAX_JUMP_PX if moving else ARUCO_STATIONARY_MAX_JUMP_PX

            if tag_id in self._smoothed:
                sx, sy = self._smoothed[tag_id]
                dist = ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5
                if dist > max_jump:
                    result[tag_id] = (sx, sy)
                    detected_ids.add(tag_id)
                    self._cache[tag_id] = ((sx, sy), current_time)
                    continue
                smooth_x = alpha * cx + (1 - alpha) * sx
                smooth_y = alpha * cy + (1 - alpha) * sy
            else:
                smooth_x, smooth_y = cx, cy

            self._smoothed[tag_id] = (smooth_x, smooth_y)
            result[tag_id] = (smooth_x, smooth_y)
            detected_ids.add(tag_id)
            self._cache[tag_id] = ((smooth_x, smooth_y), current_time)

        for tag_id, (position, timestamp) in list(self._cache.items()):
            if tag_id not in detected_ids:
                age_ms = (current_time - timestamp) * 1000
                if age_ms <= ARUCO_TAG_CACHE_MS:
                    result[tag_id] = position

        for tag_id in list(self._smoothed):
            if tag_id not in result:
                del self._smoothed[tag_id]

        return result


class ArucoTracker:
    def __init__(self, gc: GlobalConfig, feeder_capture: CaptureThread, moving_ids: Optional[set] = None):
        self.gc = gc
        self._feeder_capture = feeder_capture
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_processed_frame_ts = 0.0
        self._latest_tags: Dict[int, Tuple[float, float]] = {}
        self._last_update_ts = 0.0
        self._smoother = ArucoTagSmoother(moving_ids=moving_ids)
        self._detector = mkArucoDetector()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def getTags(self) -> Dict[int, Tuple[float, float]]:
        with self._lock:
            return dict(self._latest_tags)

    def getLastUpdateTimestamp(self) -> float:
        with self._lock:
            return self._last_update_ts

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self.gc.profiler.hit("aruco_tracker.loop.calls")
            self.gc.profiler.mark("aruco_tracker.loop.interval_ms")
            with self.gc.profiler.timer("aruco_tracker.loop.total_ms"):
                frame = self._feeder_capture.latest_frame
                if frame is None:
                    time.sleep(ARUCO_UPDATE_INTERVAL_MS / 1000.0)
                    continue

                if frame.timestamp <= self._last_processed_frame_ts:
                    time.sleep(ARUCO_UPDATE_INTERVAL_MS / 1000.0)
                    continue

                self._last_processed_frame_ts = frame.timestamp
                tags = self._detect(frame.raw)
                with self._lock:
                    self._latest_tags = tags
                    self._last_update_ts = time.time()

            time.sleep(ARUCO_UPDATE_INTERVAL_MS / 1000.0)

    def _detect(self, raw_frame: np.ndarray) -> Dict[int, Tuple[float, float]]:
        self.gc.profiler.hit("aruco_tracker.detect.calls")
        self.gc.profiler.startTimer("aruco_tracker.detect.total_ms")
        with self.gc.profiler.timer("aruco_tracker.detect.cvt_color_ms"):
            gray = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2GRAY)

        with self.gc.profiler.timer("aruco_tracker.detect.detect_markers_ms"):
            raw_tags = detectArucoTags(gray, self._detector)

        result = self._smoother.update(raw_tags)

        self.gc.profiler.observeValue(
            "aruco_tracker.detected_count", float(len(result))
        )
        self.gc.profiler.endTimer("aruco_tracker.detect.total_ms")
        return result
