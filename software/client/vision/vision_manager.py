from typing import Optional, List, Dict, Tuple
from collections import deque
import base64
import time
import cv2
import cv2.aruco as aruco
import numpy as np

from global_config import GlobalConfig
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from defs.consts import (
    FEEDER_OBJECT_CLASS_ID,
    FEEDER_CHANNEL_CLASS_ID,
    FEEDER_CAROUSEL_CLASS_ID,
)
from blob_manager import VideoRecorder, getClassificationRegions
from .camera import CaptureThread
from .inference import InferenceThread, CameraModelBinding
from .types import CameraFrame, VisionResult, DetectedMask

ANNOTATE_ARUCO_TAGS = True
ARUCO_TAG_CACHE_MS = 100
FEEDER_MASK_CACHE_FRAMES = 3
TELEMETRY_INTERVAL_S = 30
CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX = 200
CAROUSEL_FEEDING_PLATFORM_CACHE_MAX_AGE_MS = 60000
CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX = 10
CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX = 50000
CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG = 70
OBJECT_DETECTION_MAX_AREA_SQ_PX = 100000
CLASSIFICATION_REGION_MIN_OVERLAP = 0.5

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
    "cornerRefinementMethod": 0,  # 0=none, 1=subpix, 2=contour, 3=apriltag
    "cornerRefinementWinSize": 5,
}


class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: CaptureThread
    _classification_bottom_capture: CaptureThread
    _classification_top_capture: CaptureThread
    _inference: InferenceThread
    _feeder_binding: CameraModelBinding
    _classification_bottom_binding: CameraModelBinding
    _classification_top_binding: CameraModelBinding
    _video_recorder: Optional[VideoRecorder]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig):
        self.gc = gc
        self._irl_config = irl_config
        self._feeder_camera_config = irl_config.feeder_camera
        self._feeder_capture = CaptureThread("feeder", irl_config.feeder_camera)
        self._classification_bottom_capture = CaptureThread(
            "classification_bottom", irl_config.classification_camera_bottom
        )
        self._classification_top_capture = CaptureThread(
            "classification_top", irl_config.classification_camera_top
        )

        self._inference = InferenceThread()

        feeder_model = (
            gc.feeder_vision_model_path if gc.feeder_vision_model_path else None
        )
        classification_model = (
            gc.classification_chamber_vision_model_path
            if gc.classification_chamber_vision_model_path
            else None
        )

        self._feeder_binding = self._inference.addBinding(
            self._feeder_capture,
            feeder_model,
            exclude_classes_from_plot=[
                FEEDER_CHANNEL_CLASS_ID,
                FEEDER_CAROUSEL_CLASS_ID,
            ],
        )
        self._classification_bottom_binding = self._inference.addBinding(
            self._classification_bottom_capture, classification_model
        )
        self._classification_top_binding = self._inference.addBinding(
            self._classification_top_capture, classification_model
        )

        regions = getClassificationRegions() or {}
        self._top_region: Optional[List] = regions.get("top")
        self._bottom_region: Optional[List] = regions.get("bottom")

        self._video_recorder = VideoRecorder() if gc.should_write_camera_feeds else None

        self._telemetry = None
        self._last_telemetry_save = 0.0

        self._aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self._aruco_params = aruco.DetectorParameters()
        # tuned for small tags on a wide-angle lens
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
        self._aruco_tag_cache: Dict[int, Tuple[Tuple[float, float], float]] = {}
        self._feeder_mask_cache: deque = deque(maxlen=FEEDER_MASK_CACHE_FRAMES)
        self._cached_feeding_platform_corners: Optional[List[Tuple[float, float]]] = (
            None
        )
        self._cached_feeding_platform_timestamp: float = 0.0

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def start(self) -> None:
        self._feeder_capture.start()
        self._classification_bottom_capture.start()
        self._classification_top_capture.start()
        self._inference.start()

    def stop(self) -> None:
        self._inference.stop()
        self._feeder_capture.stop()
        self._classification_bottom_capture.stop()
        self._classification_top_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def recordFrames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
            # update feeding platform cache on every frame
            with prof.timer("vision.record_frames.update_feeding_platform_cache_ms"):
                self.updateFeedingPlatformCache()

            if self._video_recorder:
                with prof.timer("vision.record_frames.video_recorder_write_ms"):
                    for camera in [
                        "feeder",
                        "classification_bottom",
                        "classification_top",
                    ]:
                        frame = self.getFrame(camera)
                        if frame:
                            self._video_recorder.writeFrame(
                                camera, frame.raw, frame.annotated
                            )
            with prof.timer("vision.record_frames.save_telemetry_frames_ms"):
                self._saveTelemetryFrames()

    def _saveTelemetryFrames(self) -> None:
        if self._telemetry is None:
            return
        now = time.time()
        if now - self._last_telemetry_save < TELEMETRY_INTERVAL_S:
            return
        self._last_telemetry_save = now

        CAMERA_NAME_MAP = {
            "feeder": "c_channel",
            "classification_bottom": "classification_chamber_bottom",
            "classification_top": "classification_chamber_top",
        }
        for internal_name, telemetry_name in CAMERA_NAME_MAP.items():
            frame = self.getFrame(internal_name)
            if frame and frame.annotated is not None:
                self._telemetry.saveCapture(
                    telemetry_name,
                    frame.raw,
                    frame.annotated,
                    "interval",
                    segmentation_map=frame.segmentation_map,
                )

    @property
    def feeder_frame(self) -> Optional[CameraFrame]:
        frame = (
            self._feeder_binding.latest_annotated_frame
            or self._feeder_capture.latest_frame
        )
        if frame is None:
            return None

        if not ANNOTATE_ARUCO_TAGS:
            return frame

        # annotate with ArUco tags
        annotated = frame.annotated if frame.annotated is not None else frame.raw
        gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
        detector = aruco.ArucoDetector(self._aruco_dict, self._aruco_params)
        corners, ids, _ = detector.detectMarkers(gray)

        if ids is not None:
            annotated = annotated.copy()
            aruco.drawDetectedMarkers(
                annotated, corners, ids, borderColor=(0, 255, 255)
            )

            # draw tag IDs in aqua/teal
            for i, tag_id in enumerate(ids.flatten()):
                tag_corners = corners[i][0]
                center_x = int(np.mean(tag_corners[:, 0]))
                center_y = int(np.mean(tag_corners[:, 1]))
                cv2.putText(
                    annotated,
                    str(tag_id),
                    (center_x - 20, center_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.6,
                    (0, 255, 0),  # bright green
                    3,
                )

        # annotate with channel and carousel geometry
        annotated = self._annotateChannelGeometry(annotated)
        annotated = self._annotateCarouselPlatforms(annotated)

        return CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=frame.results,
            timestamp=frame.timestamp,
            segmentation_map=frame.segmentation_map,
        )

    @property
    def classification_bottom_frame(self) -> Optional[CameraFrame]:
        return (
            self._classification_bottom_binding.latest_annotated_frame
            or self._classification_bottom_capture.latest_frame
        )

    @property
    def classification_top_frame(self) -> Optional[CameraFrame]:
        return (
            self._classification_top_binding.latest_annotated_frame
            or self._classification_top_capture.latest_frame
        )

    @property
    def feeder_result(self) -> Optional[VisionResult]:
        return self._feeder_binding.latest_result

    @property
    def classification_bottom_result(self) -> Optional[VisionResult]:
        return self._classification_bottom_binding.latest_result

    @property
    def classification_top_result(self) -> Optional[VisionResult]:
        return self._classification_top_binding.latest_result

    def getFrame(self, camera_name: str) -> Optional[CameraFrame]:
        if camera_name == "feeder":
            return self.feeder_frame
        elif camera_name == "classification_bottom":
            return self.classification_bottom_frame
        elif camera_name == "classification_top":
            return self.classification_top_frame
        return None

    def getResult(self, camera_name: str) -> Optional[VisionResult]:
        if camera_name == "feeder":
            return self.feeder_result
        elif camera_name == "classification_bottom":
            return self.classification_bottom_result
        elif camera_name == "classification_top":
            return self.classification_top_result
        return None

    def getFeederArucoTags(self) -> Dict[int, Tuple[float, float]]:
        prof = self.gc.profiler
        prof.hit("vision.get_feeder_aruco_tags.calls")
        prof.mark("vision.get_feeder_aruco_tags.interval_ms")
        prof.startTimer("vision.get_feeder_aruco_tags.total_ms")
        frame = self._feeder_capture.latest_frame
        if frame is None:
            prof.endTimer("vision.get_feeder_aruco_tags.total_ms")
            return {}

        current_time = time.time()
        with prof.timer("vision.get_feeder_aruco_tags.cvt_color_ms"):
            gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
        detector = aruco.ArucoDetector(self._aruco_dict, self._aruco_params)
        with prof.timer("vision.get_feeder_aruco_tags.detect_markers_ms"):
            corners, ids, _ = detector.detectMarkers(gray)

        result: Dict[int, Tuple[float, float]] = {}
        detected_ids = set()

        # add newly detected tags
        if ids is not None:
            for i, tag_id in enumerate(ids.flatten()):
                tag_corners = corners[i][0]
                center_x = float(np.mean(tag_corners[:, 0]))
                center_y = float(np.mean(tag_corners[:, 1]))
                tag_id_int = int(tag_id)
                result[tag_id_int] = (center_x, center_y)
                detected_ids.add(tag_id_int)
                # update cache
                self._aruco_tag_cache[tag_id_int] = ((center_x, center_y), current_time)

        # check cache for recently seen tags that weren't detected this frame
        for tag_id, (position, timestamp) in list(self._aruco_tag_cache.items()):
            if tag_id not in detected_ids:
                age_ms = (current_time - timestamp) * 1000
                if age_ms <= ARUCO_TAG_CACHE_MS:
                    result[tag_id] = position

        prof.observeValue(
            "vision.get_feeder_aruco_tags.detected_count", float(len(result))
        )
        prof.endTimer("vision.get_feeder_aruco_tags.total_ms")
        return result

    def getFeederMasksByClass(self) -> Dict[int, List[DetectedMask]]:
        prof = self.gc.profiler
        prof.hit("vision.get_feeder_masks_by_class.calls")
        prof.mark("vision.get_feeder_masks_by_class.interval_ms")
        prof.startTimer("vision.get_feeder_masks_by_class.total_ms")
        # Really needs refactoring
        # This function only caches object masks across frames.
        # Channel and carousel masks are stationary so we always return current frame only.
        # For objects: accumulate detections across multiple frames for stability.
        # This helps with detection reliability when pieces are moving.
        # Should eventually be refactored for proper object tracking and lifecycle management.
        # this means that if you count the number of objects, it's ~FEEDER_MASK_CACHE_FRAMES bigger than it should be

        results = self._feeder_binding.latest_raw_results
        if not results or len(results) == 0:
            # no new results, return cached objects only
            aggregated: Dict[int, List[DetectedMask]] = {}
            for object_masks in self._feeder_mask_cache:
                if FEEDER_OBJECT_CLASS_ID not in aggregated:
                    aggregated[FEEDER_OBJECT_CLASS_ID] = []
                aggregated[FEEDER_OBJECT_CLASS_ID].extend(object_masks)
            prof.observeValue(
                "vision.get_feeder_masks_by_class.cached_object_count",
                float(len(aggregated.get(FEEDER_OBJECT_CLASS_ID, []))),
            )
            prof.endTimer("vision.get_feeder_masks_by_class.total_ms")
            return aggregated

        # process current frame
        current_frame_all_masks: Dict[int, List[DetectedMask]] = {}
        current_frame_object_masks: List[DetectedMask] = []

        prof.startTimer("vision.get_feeder_masks_by_class.process_results_ms")
        for result in results:
            if result.masks is not None:
                for i, mask in enumerate(result.masks):
                    class_id = int(result.boxes[i].cls.item())
                    confidence = float(result.boxes[i].conf.item())
                    with prof.timer(
                        "vision.get_feeder_masks_by_class.mask_cpu_numpy_ms"
                    ):
                        mask_data = mask.data[0].cpu().numpy()

                    # get track ID if available, otherwise use index
                    instance_id = i
                    if result.boxes[i].id is not None:
                        instance_id = int(result.boxes[i].id.item())

                    # scale mask from model space to camera resolution
                    model_height, model_width = mask_data.shape
                    camera_height = self._feeder_camera_config.height
                    camera_width = self._feeder_camera_config.width

                    if model_height != camera_height or model_width != camera_width:
                        with prof.timer(
                            "vision.get_feeder_masks_by_class.mask_resize_ms"
                        ):
                            scaled_mask = cv2.resize(
                                mask_data.astype(np.uint8),
                                (camera_width, camera_height),
                                interpolation=cv2.INTER_NEAREST,
                            ).astype(bool)
                    else:
                        scaled_mask = mask_data.astype(bool)

                    # filter out objects that are too large
                    if class_id == FEEDER_OBJECT_CLASS_ID:
                        with prof.timer(
                            "vision.get_feeder_masks_by_class.mask_area_ms"
                        ):
                            mask_area = np.sum(scaled_mask)
                        if mask_area > OBJECT_DETECTION_MAX_AREA_SQ_PX:
                            continue  # skip this object, it's too large

                    detected_mask = DetectedMask(
                        mask=scaled_mask,
                        confidence=confidence,
                        class_id=class_id,
                        instance_id=instance_id,
                    )

                    if class_id not in current_frame_all_masks:
                        current_frame_all_masks[class_id] = []
                    current_frame_all_masks[class_id].append(detected_mask)

                    # cache only object masks
                    if class_id == FEEDER_OBJECT_CLASS_ID:
                        current_frame_object_masks.append(detected_mask)
        prof.endTimer("vision.get_feeder_masks_by_class.process_results_ms")

        # add only object masks to cache
        self._feeder_mask_cache.append(current_frame_object_masks)

        # build result: current frame for channels/carousel, aggregated cache for objects
        result_masks: Dict[int, List[DetectedMask]] = {}

        # add all non-object masks from current frame only
        for class_id, masks in current_frame_all_masks.items():
            if class_id != FEEDER_OBJECT_CLASS_ID:
                result_masks[class_id] = masks

        # aggregate object masks from cache
        result_masks[FEEDER_OBJECT_CLASS_ID] = []
        for object_masks in self._feeder_mask_cache:
            result_masks[FEEDER_OBJECT_CLASS_ID].extend(object_masks)

        prof.observeValue(
            "vision.get_feeder_masks_by_class.object_count",
            float(len(result_masks.get(FEEDER_OBJECT_CLASS_ID, []))),
        )
        prof.endTimer("vision.get_feeder_masks_by_class.total_ms")
        return result_masks

    def getChannelGeometry(self, aruco_tag_config):
        from subsystems.feeder.analysis import computeChannelGeometry

        prof = self.gc.profiler
        prof.hit("vision.get_channel_geometry.calls")
        with prof.timer("vision.get_channel_geometry.total_ms"):
            aruco_tags = self.getFeederArucoTags()
            return computeChannelGeometry(aruco_tags, aruco_tag_config)

    def getCarouselPlatforms(self):
        from irl.config import CarouselArucoTagConfig

        aruco_tags = self.getFeederArucoTags()
        platforms = []

        # check each of the 4 carousel platforms
        for i, platform_config in enumerate(
            [
                self._irl_config.aruco_tags.carousel_platform1,
                self._irl_config.aruco_tags.carousel_platform2,
                self._irl_config.aruco_tags.carousel_platform3,
                self._irl_config.aruco_tags.carousel_platform4,
            ]
        ):
            # get positions of all 4 corners, track which ones we found
            corner_ids = [
                platform_config.corner1_id,
                platform_config.corner2_id,
                platform_config.corner3_id,
                platform_config.corner4_id,
            ]
            detected_corners = {}
            for idx, corner_id in enumerate(corner_ids):
                if corner_id in aruco_tags:
                    detected_corners[idx] = aruco_tags[corner_id]

            # need at least 3 corners to define a platform
            if len(detected_corners) >= 3:
                corners = list(detected_corners.values())

                # if we have exactly 3 corners, infer the 4th
                # try all 3 possible 4th corners and pick the one that forms the best rectangle
                if len(detected_corners) == 3:
                    p0, p1, p2 = [np.array(c) for c in corners]

                    # three possible 4th corners for a parallelogram
                    candidates = [
                        p0 + p1 - p2,  # forms parallelogram with p2 opposite to p0+p1
                        p0 + p2 - p1,  # forms parallelogram with p1 opposite to p0+p2
                        p1 + p2 - p0,  # forms parallelogram with p0 opposite to p1+p2
                    ]

                    # pick the candidate that forms the most rectangular shape
                    # by checking which has the most similar opposite side lengths
                    best_candidate = candidates[0]
                    best_score = float("inf")

                    for candidate in candidates:
                        # form quadrilateral with the 3 detected + candidate
                        quad = [p0, p1, p2, candidate]

                        # compute all 6 pairwise distances
                        distances = []
                        for j in range(4):
                            for k in range(j + 1, 4):
                                dist = np.linalg.norm(quad[j] - quad[k])
                                distances.append(dist)

                        # for a rectangle, we expect 4 sides + 2 diagonals
                        # the 4 sides should form 2 pairs of equal length
                        # score by standard deviation of distances (lower is better)
                        score = np.std(distances)

                        if score < best_score:
                            best_score = score
                            best_candidate = candidate

                    corners.append(tuple(best_candidate))

                # order corners by angle from centroid (so they go around perimeter)
                if len(corners) >= 3:
                    corners_array = np.array(corners)
                    centroid = np.mean(corners_array, axis=0)

                    # compute angle of each corner from centroid
                    angles = []
                    for corner in corners:
                        dx = corner[0] - centroid[0]
                        dy = corner[1] - centroid[1]
                        angle = np.arctan2(dy, dx)
                        angles.append(angle)

                    # sort corners by angle
                    sorted_indices = np.argsort(angles)
                    corners = [corners[i] for i in sorted_indices]

                platforms.append(
                    {
                        "platform_id": i,
                        "corners": corners,
                    }
                )

        return platforms

    def _annotateChannelGeometry(self, annotated: np.ndarray) -> np.ndarray:
        from subsystems.feeder.analysis import computeChannelGeometry

        aruco_tags = self.getFeederArucoTags()
        geometry = computeChannelGeometry(
            aruco_tags,
            self._irl_config.aruco_tags,
        )

        annotated = annotated.copy()

        # get tag positions for both channels (only radius tags needed)
        third_r1_pos = aruco_tags.get(
            self._irl_config.aruco_tags.third_c_channel_radius1_id
        )
        third_r2_pos = aruco_tags.get(
            self._irl_config.aruco_tags.third_c_channel_radius2_id
        )

        second_r1_pos = aruco_tags.get(
            self._irl_config.aruco_tags.second_c_channel_radius1_id
        )
        second_r2_pos = aruco_tags.get(
            self._irl_config.aruco_tags.second_c_channel_radius2_id
        )

        # draw channel 3 (inner) - circle from two radius tags
        if geometry.third_channel:
            ch = geometry.third_channel
            center = (int(ch.center[0]), int(ch.center[1]))
            radius = int(ch.radius)

            # draw circle
            cv2.circle(annotated, center, radius, (255, 0, 255), 2)

            # draw diameter line through the two radius tags
            if third_r1_pos and third_r2_pos:
                cv2.line(
                    annotated,
                    (int(third_r1_pos[0]), int(third_r1_pos[1])),
                    (int(third_r2_pos[0]), int(third_r2_pos[1])),
                    (255, 0, 255),
                    2,
                )

            # draw quadrant divider lines
            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0
                angle_rad = np.radians(angle_deg)
                end_x = int(center[0] + radius * np.cos(angle_rad))
                end_y = int(center[1] + radius * np.sin(angle_rad))
                cv2.line(annotated, center, (end_x, end_y), (180, 0, 180), 1)

            # draw quadrant 0-3 labels
            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0 + 45.0
                angle_rad = np.radians(angle_deg)
                label_radius = radius * 0.7
                label_x = int(center[0] + label_radius * np.cos(angle_rad))
                label_y = int(center[1] + label_radius * np.sin(angle_rad))
                cv2.putText(
                    annotated,
                    str(q),
                    (label_x - 10, label_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 0, 255),
                    2,
                )

            # channel label
            cv2.putText(
                annotated,
                "Ch3",
                (center[0] - 20, center[1] - radius - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 0, 255),
                2,
            )

        # draw channel 2 (outer) - circle from two radius tags
        if geometry.second_channel:
            ch = geometry.second_channel
            center = (int(ch.center[0]), int(ch.center[1]))
            radius = int(ch.radius)

            # draw circle
            cv2.circle(annotated, center, radius, (0, 255, 255), 2)

            # draw diameter line through the two radius tags
            if second_r1_pos and second_r2_pos:
                cv2.line(
                    annotated,
                    (int(second_r1_pos[0]), int(second_r1_pos[1])),
                    (int(second_r2_pos[0]), int(second_r2_pos[1])),
                    (0, 255, 255),
                    2,
                )

            # draw quadrant divider lines
            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0
                angle_rad = np.radians(angle_deg)
                end_x = int(center[0] + radius * np.cos(angle_rad))
                end_y = int(center[1] + radius * np.sin(angle_rad))
                cv2.line(annotated, center, (end_x, end_y), (0, 180, 180), 1)

            # draw quadrant 0-3 labels
            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0 + 45.0
                angle_rad = np.radians(angle_deg)
                label_radius = radius * 0.7
                label_x = int(center[0] + label_radius * np.cos(angle_rad))
                label_y = int(center[1] + label_radius * np.sin(angle_rad))
                cv2.putText(
                    annotated,
                    str(q),
                    (label_x - 10, label_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                )

            # channel label
            cv2.putText(
                annotated,
                "Ch2",
                (center[0] - 20, center[1] - radius - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )

        return annotated

    def _annotateCarouselPlatforms(self, annotated: np.ndarray) -> np.ndarray:
        corners = self.feeding_platform_corners
        if corners is None:
            return annotated

        annotated = annotated.copy()

        # draw feeding platform in bright cyan
        color = (255, 255, 0)
        points = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
        cv2.polylines(annotated, [points], isClosed=True, color=color, thickness=2)

        # draw platform label
        center_x = int(np.mean([x for x, y in corners]))
        center_y = int(np.mean([y for x, y in corners]))
        cv2.putText(
            annotated,
            "FEED",
            (center_x - 20, center_y + 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
        )

        return annotated

    def _validateCornerAngles(
        self, corners: List[Tuple[float, float]], min_angle_deg: float
    ) -> tuple[bool, List[float]]:
        # check that all corner angles are >= min_angle_deg
        corners_array = np.array(corners)
        n = len(corners_array)
        angles = []

        for i in range(n):
            # get three consecutive points: previous, current, next
            prev = corners_array[(i - 1) % n]
            curr = corners_array[i]
            next_pt = corners_array[(i + 1) % n]

            # vectors from current corner to adjacent corners
            v1 = prev - curr
            v2 = next_pt - curr

            # calculate internal angle using dot product
            cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
            # clamp to [-1, 1] to avoid numerical errors
            cos_angle = np.clip(cos_angle, -1.0, 1.0)
            angle_rad = np.arccos(cos_angle)
            angle_deg = np.degrees(angle_rad)
            angles.append(angle_deg)

        valid = all(a >= min_angle_deg for a in angles)
        return valid, angles

    def _expandRectanglePerimeter(
        self, corners: List[Tuple[float, float]], expansion_px: float
    ) -> List[Tuple[float, float]]:
        # convert corners to numpy array
        corners_array = np.array(corners)

        # find rectangle center
        center = np.mean(corners_array, axis=0)

        # expand each corner outward from center
        expanded_corners = []
        for corner in corners_array:
            # direction from center to corner
            direction = corner - center
            distance = np.linalg.norm(direction)
            if distance > 0:
                direction = direction / distance  # normalize
                # move corner outward by expansion amount
                expanded_corner = corner + direction * expansion_px
                expanded_corners.append(tuple(expanded_corner))
            else:
                expanded_corners.append(tuple(corner))

        return expanded_corners

    def updateFeedingPlatformCache(self):
        prof = self.gc.profiler
        prof.hit("vision.update_feeding_platform_cache.calls")
        with prof.timer("vision.update_feeding_platform_cache.total_ms"):
            self._updateFeedingPlatformCacheInner()

    def _updateFeedingPlatformCacheInner(self):
        platforms = self.getCarouselPlatforms()
        if not platforms:
            return

        aruco_tags = self.getFeederArucoTags()
        reference_tag_id = self._irl_config.aruco_tags.third_c_channel_radius1_id

        if reference_tag_id not in aruco_tags:
            return

        reference_pos = np.array(aruco_tags[reference_tag_id])
        self.gc.logger.info(
            f"Comparing platforms to reference tag {reference_tag_id} "
            f"at position ({reference_pos[0]:.1f}, {reference_pos[1]:.1f})"
        )

        # find a valid platform within threshold distance of reference tag
        for platform in platforms:
            corners = platform["corners"]
            if len(corners) >= 3:
                # compute platform center
                center_x = np.mean([x for x, y in corners])
                center_y = np.mean([y for x, y in corners])
                platform_center = np.array([center_x, center_y])

                # compute distance to reference tag
                distance = np.linalg.norm(platform_center - reference_pos)

                self.gc.logger.info(
                    f"Platform {platform['platform_id']}: distance={distance:.1f}px "
                    f"(threshold={CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX}px)"
                )

                # if within threshold, validate and update cache
                if distance <= CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX:
                    expanded_corners = self._expandRectanglePerimeter(
                        corners, CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX
                    )

                    # calculate area using shoelace formula
                    corners_array = np.array(expanded_corners)
                    x = corners_array[:, 0]
                    y = corners_array[:, 1]
                    area = 0.5 * np.abs(
                        np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))
                    )

                    # validate area is within acceptable range
                    if area > CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX:
                        self.gc.logger.info(
                            f"Platform {platform['platform_id']} area too large: {area:.1f}px² "
                            f"(max={CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX}px²), skipping"
                        )
                        continue

                    # calculate and log corner angles on EXPANDED corners
                    angles_valid, corner_angles = self._validateCornerAngles(
                        expanded_corners, CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG
                    )
                    angles_str = ", ".join([f"{a:.1f}°" for a in corner_angles])
                    self.gc.logger.info(
                        f"Platform {platform['platform_id']} internal angles: [{angles_str}]"
                    )

                    if not angles_valid:
                        self.gc.logger.info(
                            f"Platform {platform['platform_id']} has invalid corner angles "
                            f"(min={CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG}°), skipping"
                        )
                        continue

                    self._cached_feeding_platform_corners = expanded_corners
                    self._cached_feeding_platform_timestamp = time.time()
                    self.gc.logger.info(
                        f"Cached feeding platform: area={area:.1f}px², corners={len(expanded_corners)}"
                    )
                    return

    @property
    def feeding_platform_corners(self) -> Optional[List[Tuple[float, float]]]:
        if self._cached_feeding_platform_corners is None:
            return None

        # check if cache is too old
        age_ms = (time.time() - self._cached_feeding_platform_timestamp) * 1000
        if age_ms > CAROUSEL_FEEDING_PLATFORM_CACHE_MAX_AGE_MS:
            return None

        return self._cached_feeding_platform_corners

    def isObjectOnCarouselPlatform(self, object_mask: np.ndarray) -> bool:
        corners = self.feeding_platform_corners
        if corners is None:
            return False

        # get object center of mass
        coords = np.argwhere(object_mask)
        if len(coords) == 0:
            return False

        center_y = int(np.mean(coords[:, 0]))
        center_x = int(np.mean(coords[:, 1]))
        point = (center_x, center_y)

        # check if object center is inside the cached feeding platform polygon
        if len(corners) >= 3:
            points = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
            # use cv2.pointPolygonTest to check if point is inside polygon
            result = cv2.pointPolygonTest(points, point, False)
            if result >= 0:  # inside or on the edge
                return True

        return False

    def captureFreshClassificationFrames(
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[CameraFrame], Optional[CameraFrame]]:
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            top = self._classification_top_binding.latest_annotated_frame
            bottom = self._classification_bottom_binding.latest_annotated_frame
            if (
                top
                and bottom
                and top.timestamp > start_time
                and bottom.timestamp > start_time
            ):
                return (top, bottom)
            time.sleep(0.05)
        return (
            self._classification_top_binding.latest_annotated_frame,
            self._classification_bottom_binding.latest_annotated_frame,
        )

    def getClassificationCrops(
        self, timeout_s: float = 1.0, confidence_threshold: float = 0.0
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)
        if not self.gc.use_segmentation_model_for_classification_chamber:
            top_crop = self._extractRegionBoundingBoxCrop(top_frame, self._top_region)
            bottom_crop = self._extractRegionBoundingBoxCrop(
                bottom_frame, self._bottom_region
            )
            return (top_crop, bottom_crop)

        top_crop = self._extractLargestObjectCrop(
            top_frame,
            self._classification_top_binding.latest_raw_results,
            self._top_region,
            confidence_threshold,
        )
        bottom_crop = self._extractLargestObjectCrop(
            bottom_frame,
            self._classification_bottom_binding.latest_raw_results,
            self._bottom_region,
            confidence_threshold,
        )
        return (top_crop, bottom_crop)

    def _extractRegionBoundingBoxCrop(
        self, frame: Optional[CameraFrame], region: Optional[List]
    ) -> Optional[np.ndarray]:
        if frame is None:
            return None

        h, w = frame.raw.shape[:2]
        if region is None or len(region) == 0:
            return frame.raw

        xs = [int(point[0]) for point in region]
        ys = [int(point[1]) for point in region]
        x1 = max(0, min(xs))
        y1 = max(0, min(ys))
        x2 = min(w, max(xs))
        y2 = min(h, max(ys))

        if x2 <= x1 or y2 <= y1:
            return None
        return frame.raw[y1:y2, x1:x2]

    def _extractLargestObjectCrop(
        self,
        frame: Optional[CameraFrame],
        raw_results,
        region: Optional[List] = None,
        confidence_threshold: float = 0.0,
    ) -> Optional[np.ndarray]:
        if frame is None or raw_results is None or len(raw_results) == 0:
            return None

        boxes = raw_results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        h, w = frame.raw.shape[:2]
        poly_mask = None
        if region is not None:
            pts = np.array(region, dtype=np.int32)
            poly_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(poly_mask, [pts], 1)

        best_box = None
        best_area = 0
        masks = raw_results[0].masks
        for i, box in enumerate(boxes):
            class_id = int(box.cls[0])
            if class_id != 0:
                continue

            # check confidence threshold
            confidence = float(box.conf[0])
            if confidence < confidence_threshold:
                continue

            xyxy = box.xyxy[0].tolist()
            area = (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1])
            if area <= best_area:
                continue
            if poly_mask is not None and masks is not None and i < len(masks):
                mask_data = masks[i].data[0].cpu().numpy()
                mh, mw = mask_data.shape
                if mh != h or mw != w:
                    mask_data = cv2.resize(
                        mask_data.astype(np.uint8),
                        (w, h),
                        interpolation=cv2.INTER_NEAREST,
                    )
                mask_bin = (mask_data > 0).astype(np.uint8)
                total = int(np.sum(mask_bin))
                if total > 0:
                    inside = int(np.sum(mask_bin & poly_mask))
                    if inside / total < CLASSIFICATION_REGION_MIN_OVERLAP:
                        continue
            best_area = area
            best_box = xyxy

        if best_box is None:
            return None

        x1, y1, x2, y2 = map(int, best_box)
        return frame.raw[y1:y2, x1:x2]

    def _encodeFrame(self, frame) -> str:
        with self.gc.profiler.timer("vision.encode_frame.imencode_ms"):
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.gc.profiler.timer("vision.encode_frame.base64_ms"):
            return base64.b64encode(buffer).decode("utf-8")

    def getFrameEvent(self, camera_name: CameraName) -> Optional[FrameEvent]:
        self.gc.profiler.hit(f"vision.get_frame_event.calls.{camera_name.value}")
        self.gc.profiler.startTimer("vision.get_frame_event.total_ms")
        frame = self.getFrame(camera_name.value)
        if frame is None:
            self.gc.profiler.endTimer("vision.get_frame_event.total_ms")
            return None

        results_data = [
            FrameResultData(
                class_id=r.class_id,
                class_name=r.class_name,
                confidence=r.confidence,
                bbox=r.bbox,
            )
            for r in frame.results
        ]

        raw_b64 = self._encodeFrame(frame.raw)
        annotated_b64 = (
            self._encodeFrame(frame.annotated) if frame.annotated is not None else None
        )

        event = FrameEvent(
            tag="frame",
            data=FrameData(
                camera=camera_name,
                timestamp=frame.timestamp,
                raw=raw_b64,
                annotated=annotated_b64,
                results=results_data,
            ),
        )
        self.gc.profiler.endTimer("vision.get_frame_event.total_ms")
        return event

    def getAllFrameEvents(self) -> List[FrameEvent]:
        self.gc.profiler.hit("vision.get_all_frame_events.calls")
        self.gc.profiler.startTimer("vision.get_all_frame_events.total_ms")
        events = []
        for camera in CameraName:
            event = self.getFrameEvent(camera)
            if event:
                events.append(event)
        self.gc.profiler.observeValue(
            "vision.get_all_frame_events.count", float(len(events))
        )
        self.gc.profiler.endTimer("vision.get_all_frame_events.total_ms")
        return events
