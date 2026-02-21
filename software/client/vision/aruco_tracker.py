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
        self._last_update_ts = 0.0
        self._aruco_tag_cache: Dict[int, Tuple[Tuple[float, float], float]] = {}

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

        detector = aruco.ArucoDetector(self._aruco_dict, self._aruco_params)
        with self.gc.profiler.timer("aruco_tracker.detect.detect_markers_ms"):
            corners, ids, _ = detector.detectMarkers(gray)

        current_time = time.time()
        result: Dict[int, Tuple[float, float]] = {}
        detected_ids = set()

        if ids is not None:
            for i, tag_id in enumerate(ids.flatten()):
                tag_corners = corners[i][0]
                center_x = float(np.mean(tag_corners[:, 0]))
                center_y = float(np.mean(tag_corners[:, 1]))
                tag_id_int = int(tag_id)
                result[tag_id_int] = (center_x, center_y)
                detected_ids.add(tag_id_int)
                self._aruco_tag_cache[tag_id_int] = ((center_x, center_y), current_time)

        for tag_id, (position, timestamp) in list(self._aruco_tag_cache.items()):
            if tag_id not in detected_ids:
                age_ms = (current_time - timestamp) * 1000
                if age_ms <= ARUCO_TAG_CACHE_MS:
                    result[tag_id] = position

        self.gc.profiler.observeValue(
            "aruco_tracker.detected_count", float(len(result))
        )
        self.gc.profiler.endTimer("aruco_tracker.detect.total_ms")
        return result
