import threading
import time
from collections import deque
from typing import Dict, Tuple, Optional, Deque
import cv2
import cv2.aruco as aruco
import numpy as np

from global_config import GlobalConfig
from .camera import CaptureThread

ARUCO_TAG_CACHE_MS = 100
ARUCO_UPDATE_INTERVAL_MS = 120
ARUCO_OUTLIER_MAX_JUMP_PX = 120.0
ARUCO_OUTLIER_REACQUIRE_TIMEOUT_S = 1.0

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


class ArucoTracker:
    def __init__(self, gc: GlobalConfig, feeder_capture: CaptureThread):
        self.gc = gc
        self._feeder_capture = feeder_capture
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_processed_frame_ts = 0.0
        self._latest_tags: Dict[int, Tuple[float, float]] = {}
        self._latest_raw_tags: Dict[int, Tuple[float, float]] = {}
        self._last_update_ts = 0.0
        self._aruco_tag_cache: Dict[int, Tuple[Tuple[float, float], float]] = {}
        self._aruco_tag_history: Dict[int, Deque[Tuple[float, Tuple[float, float]]]] = {}
        self._aruco_last_accepted_raw: Dict[int, Tuple[Tuple[float, float], float]] = {}
        self._smoothing_time_s: float = 0.35

        self._aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self._aruco_params = aruco.DetectorParameters()
        self._aruco_params.minMarkerPerimeterRate = ARUCO_TAG_DETECTION_PARAMS[
            "minMarkerPerimeterRate"
        ]
        self._aruco_params.perspectiveRemovePixelPerCell = ARUCO_TAG_DETECTION_PARAMS[
            "perspectiveRemovePixelPerCell"
        ]
        self._aruco_params.perspectiveRemoveIgnoredMarginPerCell = (
            ARUCO_TAG_DETECTION_PARAMS["perspectiveRemoveIgnoredMarginPerCell"]
        )
        self._aruco_params.adaptiveThreshWinSizeMin = ARUCO_TAG_DETECTION_PARAMS[
            "adaptiveThreshWinSizeMin"
        ]
        self._aruco_params.adaptiveThreshWinSizeMax = ARUCO_TAG_DETECTION_PARAMS[
            "adaptiveThreshWinSizeMax"
        ]
        self._aruco_params.adaptiveThreshWinSizeStep = ARUCO_TAG_DETECTION_PARAMS[
            "adaptiveThreshWinSizeStep"
        ]
        self._aruco_params.errorCorrectionRate = ARUCO_TAG_DETECTION_PARAMS[
            "errorCorrectionRate"
        ]
        self._aruco_params.polygonalApproxAccuracyRate = ARUCO_TAG_DETECTION_PARAMS[
            "polygonalApproxAccuracyRate"
        ]
        self._aruco_params.minDistanceToBorder = ARUCO_TAG_DETECTION_PARAMS[
            "minDistanceToBorder"
        ]
        self._aruco_params.maxErroneousBitsInBorderRate = ARUCO_TAG_DETECTION_PARAMS[
            "maxErroneousBitsInBorderRate"
        ]
        self._aruco_params.cornerRefinementMethod = ARUCO_TAG_DETECTION_PARAMS[
            "cornerRefinementMethod"
        ]
        self._aruco_params.cornerRefinementWinSize = ARUCO_TAG_DETECTION_PARAMS[
            "cornerRefinementWinSize"
        ]

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

    def getRawTags(self) -> Dict[int, Tuple[float, float]]:
        with self._lock:
            return dict(self._latest_raw_tags)

    def getLastUpdateTimestamp(self) -> float:
        with self._lock:
            return self._last_update_ts

    def setSmoothingTimeSeconds(self, smoothing_time_s: float) -> None:
        safe_value = float(max(0.0, smoothing_time_s))
        with self._lock:
            self._smoothing_time_s = safe_value

    def getSmoothingTimeSeconds(self) -> float:
        with self._lock:
            return self._smoothing_time_s

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
                raw_tags, smoothed_tags = self._detect(frame.raw)
                with self._lock:
                    self._latest_raw_tags = raw_tags
                    self._latest_tags = smoothed_tags
                    self._last_update_ts = time.time()

            time.sleep(ARUCO_UPDATE_INTERVAL_MS / 1000.0)

    def _detect(
        self, raw_frame: np.ndarray
    ) -> Tuple[Dict[int, Tuple[float, float]], Dict[int, Tuple[float, float]]]:
        self.gc.profiler.hit("aruco_tracker.detect.calls")
        self.gc.profiler.startTimer("aruco_tracker.detect.total_ms")
        with self.gc.profiler.timer("aruco_tracker.detect.cvt_color_ms"):
            gray = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2GRAY)

        detector = aruco.ArucoDetector(self._aruco_dict, self._aruco_params)
        with self.gc.profiler.timer("aruco_tracker.detect.detect_markers_ms"):
            corners, ids, _ = detector.detectMarkers(gray)

        current_time = time.time()
        smoothing_time_s = self.getSmoothingTimeSeconds()
        raw_result: Dict[int, Tuple[float, float]] = {}
        result: Dict[int, Tuple[float, float]] = {}
        detected_ids = set()

        if ids is not None:
            for i, tag_id in enumerate(ids.flatten()):
                tag_corners = corners[i][0]
                center_x = float(np.mean(tag_corners[:, 0]))
                center_y = float(np.mean(tag_corners[:, 1]))
                tag_id_int = int(tag_id)
                raw_center = (center_x, center_y)

                previous_accepted = self._aruco_last_accepted_raw.get(tag_id_int)
                if previous_accepted is not None:
                    previous_pos, previous_ts = previous_accepted
                    previous_age_s = current_time - previous_ts
                    if previous_age_s <= ARUCO_OUTLIER_REACQUIRE_TIMEOUT_S:
                        distance_px = float(
                            np.hypot(
                                raw_center[0] - previous_pos[0],
                                raw_center[1] - previous_pos[1],
                            )
                        )
                        if distance_px > ARUCO_OUTLIER_MAX_JUMP_PX:
                            self.gc.profiler.hit("aruco_tracker.detect.outlier_rejected")
                            continue

                raw_result[tag_id_int] = raw_center
                self._aruco_last_accepted_raw[tag_id_int] = (raw_center, current_time)

                if smoothing_time_s > 0.0:
                    history = self._aruco_tag_history.setdefault(tag_id_int, deque())
                    if previous_accepted is not None:
                        _, previous_ts = previous_accepted
                        if current_time - previous_ts > ARUCO_OUTLIER_REACQUIRE_TIMEOUT_S:
                            history.clear()
                    history.append((current_time, raw_center))
                    cutoff = current_time - smoothing_time_s
                    while history and history[0][0] < cutoff:
                        history.popleft()

                    required_persistence_s = 0.5 * smoothing_time_s
                    history_duration_s = (
                        history[-1][0] - history[0][0] if len(history) >= 2 else 0.0
                    )
                    if history_duration_s > required_persistence_s:
                        avg_x = float(np.mean([point[0] for _, point in history]))
                        avg_y = float(np.mean([point[1] for _, point in history]))
                        smoothed_center = (avg_x, avg_y)
                    else:
                        smoothed_center = raw_center
                else:
                    self._aruco_tag_history.pop(tag_id_int, None)
                    smoothed_center = (center_x, center_y)

                result[tag_id_int] = smoothed_center
                detected_ids.add(tag_id_int)
                self._aruco_tag_cache[tag_id_int] = (smoothed_center, current_time)

        for tag_id, (position, timestamp) in list(self._aruco_tag_cache.items()):
            if tag_id not in detected_ids:
                age_ms = (current_time - timestamp) * 1000
                if age_ms <= ARUCO_TAG_CACHE_MS:
                    result[tag_id] = position
                    # For "raw" output, prefer the last accepted raw position if available,
                    # to avoid polluting raw_result with smoothed cache values.
                    last_raw = self._aruco_last_accepted_raw.get(tag_id)
                    if last_raw is not None:
                        raw_position, _ = last_raw
                        raw_result.setdefault(tag_id, raw_position)
                    else:
                        # Fallback to the cached position to preserve previous behavior
                        raw_result.setdefault(tag_id, position)

        stale_cutoff = current_time - max(smoothing_time_s, ARUCO_TAG_CACHE_MS / 1000.0)
        for tag_id, history in list(self._aruco_tag_history.items()):
            while history and history[0][0] < stale_cutoff:
                history.popleft()
            if not history:
                self._aruco_tag_history.pop(tag_id, None)

        for tag_id, (_, ts) in list(self._aruco_last_accepted_raw.items()):
            if current_time - ts > ARUCO_OUTLIER_REACQUIRE_TIMEOUT_S:
                self._aruco_last_accepted_raw.pop(tag_id, None)

        self.gc.profiler.observeValue(
            "aruco_tracker.detected_count", float(len(result))
        )
        self.gc.profiler.endTimer("aruco_tracker.detect.total_ms")
        return raw_result, result
