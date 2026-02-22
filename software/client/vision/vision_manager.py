from typing import Optional, List, Dict, Tuple
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import base64
import time
import cv2
import numpy as np

from global_config import GlobalConfig
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from defs.consts import FEEDER_OBJECT_CLASS_ID
from blob_manager import VideoRecorder
from classification.moondream import getDetection
from .camera import CaptureThread
from .aruco_tracker import ArucoTracker
from .inference import InferenceThread, CameraModelBinding
from .types import CameraFrame, VisionResult, DetectedMask

ANNOTATE_ARUCO_TAGS = True
FEEDER_DETECTION_CACHE_FRAMES = 3
TELEMETRY_INTERVAL_S = 30
INFERRED_FRAME_MAX_AGE_MS = 500
CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX = 200
CAROUSEL_FEEDING_PLATFORM_CACHE_MAX_AGE_MS = 60000
CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX = 30
CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX = 70000
CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG = 70
OBJECT_DETECTION_MAX_AREA_SQ_PX = 100000


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
            use_compact_bbox_annotation=True,
        )
        self._classification_bottom_binding = self._inference.addBinding(
            self._classification_bottom_capture, classification_model
        )
        self._classification_top_binding = self._inference.addBinding(
            self._classification_top_capture, classification_model
        )

        self._video_recorder = VideoRecorder() if gc.should_write_camera_feeds else None

        self._telemetry = None
        self._last_telemetry_save = 0.0

        self._aruco_tracker = ArucoTracker(gc, self._feeder_capture)
        self._feeder_detection_cache: deque = deque(
            maxlen=FEEDER_DETECTION_CACHE_FRAMES
        )
        self._feeder_detection_cache_last_append_timestamp: float = 0.0
        self._cached_feeding_platform_corners: Optional[List[Tuple[float, float]]] = (
            None
        )
        self._cached_feeding_platform_timestamp: float = 0.0

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def _pickNewestFrame(
        self,
        inferred_frame: Optional[CameraFrame],
        captured_frame: Optional[CameraFrame],
    ) -> Optional[CameraFrame]:
        if inferred_frame is None:
            return captured_frame
        if captured_frame is None:
            return inferred_frame
        frame_age_ms = (captured_frame.timestamp - inferred_frame.timestamp) * 1000.0
        if frame_age_ms <= INFERRED_FRAME_MAX_AGE_MS:
            return inferred_frame
        return captured_frame

    def start(self) -> None:
        self._feeder_capture.start()
        self._classification_bottom_capture.start()
        self._classification_top_capture.start()
        self._aruco_tracker.start()
        self._inference.start()

    def stop(self) -> None:
        self._inference.stop()
        self._aruco_tracker.stop()
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
        frame = self._pickNewestFrame(
            self._feeder_binding.latest_annotated_frame,
            self._feeder_capture.latest_frame,
        )
        if frame is None:
            return None

        if not ANNOTATE_ARUCO_TAGS:
            return frame

        # annotate with ArUco tags
        annotated = frame.annotated if frame.annotated is not None else frame.raw
        aruco_tags = self.getFeederArucoTags()
        if aruco_tags:
            annotated = annotated.copy()
            for tag_id, (center_x_f, center_y_f) in aruco_tags.items():
                center_x = int(center_x_f)
                center_y = int(center_y_f)
                cv2.circle(annotated, (center_x, center_y), 8, (0, 255, 255), 2)
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
        return self._pickNewestFrame(
            self._classification_bottom_binding.latest_annotated_frame,
            self._classification_bottom_capture.latest_frame,
        )

    @property
    def classification_top_frame(self) -> Optional[CameraFrame]:
        return self._pickNewestFrame(
            self._classification_top_binding.latest_annotated_frame,
            self._classification_top_capture.latest_frame,
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
        self.gc.profiler.hit("vision.get_feeder_aruco_tags.calls")
        self.gc.profiler.mark("vision.get_feeder_aruco_tags.interval_ms")
        with self.gc.profiler.timer("vision.get_feeder_aruco_tags.total_ms"):
            tags = self._aruco_tracker.getTags()
            self.gc.profiler.observeValue(
                "vision.get_feeder_aruco_tags.detected_count", float(len(tags))
            )
            return tags

    def getFeederDetectionsByClass(self) -> Dict[int, List[VisionResult]]:
        prof = self.gc.profiler
        prof.hit("vision.get_feeder_detections_by_class.calls")
        prof.mark("vision.get_feeder_detections_by_class.interval_ms")
        prof.startTimer("vision.get_feeder_detections_by_class.total_ms")

        results = self._feeder_binding.latest_raw_results
        if not results or len(results) == 0:
            aggregated: Dict[int, List[VisionResult]] = {}
            for object_detections in self._feeder_detection_cache:
                if FEEDER_OBJECT_CLASS_ID not in aggregated:
                    aggregated[FEEDER_OBJECT_CLASS_ID] = []
                aggregated[FEEDER_OBJECT_CLASS_ID].extend(
                    [
                        VisionResult(
                            class_id=d.class_id,
                            class_name=d.class_name,
                            confidence=d.confidence,
                            bbox=d.bbox,
                            timestamp=d.timestamp,
                            from_cache=True,
                            created_at=d.created_at,
                        )
                        for d in object_detections
                    ]
                )
            prof.observeValue(
                "vision.get_feeder_detections_by_class.cached_object_count",
                float(len(aggregated.get(FEEDER_OBJECT_CLASS_ID, []))),
            )
            prof.endTimer("vision.get_feeder_detections_by_class.total_ms")
            return aggregated

        current_frame_all_detections: Dict[int, List[VisionResult]] = {}
        current_frame_object_detections: List[VisionResult] = []

        prof.startTimer("vision.get_feeder_detections_by_class.process_results_ms")
        fallback_timestamp = time.time()
        if self._feeder_binding.latest_annotated_frame is not None:
            fallback_timestamp = self._feeder_binding.latest_annotated_frame.timestamp
        model_names = (
            self._feeder_binding.model.names
            if self._feeder_binding.model is not None
            else {}
        )

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls.item())
                confidence = float(box.conf.item())
                xyxy = list(map(int, box.xyxy[0].tolist()))
                bbox: Tuple[int, int, int, int] = (
                    xyxy[0],
                    xyxy[1],
                    xyxy[2],
                    xyxy[3],
                )
                bbox_area = max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])
                if (
                    class_id == FEEDER_OBJECT_CLASS_ID
                    and bbox_area > OBJECT_DETECTION_MAX_AREA_SQ_PX
                ):
                    continue

                detection = VisionResult(
                    class_id=class_id,
                    class_name=model_names.get(class_id, str(class_id)),
                    confidence=confidence,
                    bbox=bbox,
                    timestamp=fallback_timestamp,
                )
                if class_id not in current_frame_all_detections:
                    current_frame_all_detections[class_id] = []
                current_frame_all_detections[class_id].append(detection)
                if class_id == FEEDER_OBJECT_CLASS_ID:
                    current_frame_object_detections.append(detection)
        prof.endTimer("vision.get_feeder_detections_by_class.process_results_ms")

        if fallback_timestamp > self._feeder_detection_cache_last_append_timestamp:
            self._feeder_detection_cache.append(current_frame_object_detections)
            self._feeder_detection_cache_last_append_timestamp = fallback_timestamp

        result_detections: Dict[int, List[VisionResult]] = {}
        for class_id, detections in current_frame_all_detections.items():
            if class_id != FEEDER_OBJECT_CLASS_ID:
                result_detections[class_id] = detections

        result_detections[FEEDER_OBJECT_CLASS_ID] = []
        cache_len = len(self._feeder_detection_cache)
        for idx, object_detections in enumerate(self._feeder_detection_cache):
            from_cache = idx < cache_len - 1
            result_detections[FEEDER_OBJECT_CLASS_ID].extend(
                [
                    VisionResult(
                        class_id=d.class_id,
                        class_name=d.class_name,
                        confidence=d.confidence,
                        bbox=d.bbox,
                        timestamp=d.timestamp,
                        from_cache=from_cache,
                        created_at=d.created_at,
                    )
                    for d in object_detections
                ]
            )

        prof.observeValue(
            "vision.get_feeder_detections_by_class.object_count",
            float(len(result_detections.get(FEEDER_OBJECT_CLASS_ID, []))),
        )
        prof.endTimer("vision.get_feeder_detections_by_class.total_ms")
        return result_detections

    def getFeederMasksByClass(self) -> Dict[int, List[DetectedMask]]:
        detections_by_class = self.getFeederDetectionsByClass()
        camera_height = self._feeder_camera_config.height
        camera_width = self._feeder_camera_config.width
        masks_by_class: Dict[int, List[DetectedMask]] = {}

        for class_id, detections in detections_by_class.items():
            masks: List[DetectedMask] = []
            for instance_id, detection in enumerate(detections):
                if detection.bbox is None:
                    continue
                x1, y1, x2, y2 = detection.bbox
                x1 = max(0, min(camera_width, x1))
                y1 = max(0, min(camera_height, y1))
                x2 = max(0, min(camera_width, x2))
                y2 = max(0, min(camera_height, y2))
                if x2 <= x1 or y2 <= y1:
                    continue
                mask = np.zeros((camera_height, camera_width), dtype=bool)
                mask[y1:y2, x1:x2] = True
                masks.append(
                    DetectedMask(
                        mask=mask,
                        confidence=detection.confidence,
                        class_id=class_id,
                        instance_id=instance_id,
                        from_cache=detection.from_cache,
                        created_at=detection.created_at,
                    )
                )
            masks_by_class[class_id] = masks

        return masks_by_class

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
        corners_array = np.array(corners)
        center = np.mean(corners_array, axis=0)
        if len(corners_array) != 4:
            expanded_corners = []
            for corner in corners_array:
                direction = corner - center
                distance = np.linalg.norm(direction)
                if distance > 0:
                    direction = direction / distance
                    expanded_corners.append(tuple(corner + direction * expansion_px))
                else:
                    expanded_corners.append(tuple(corner))
            return expanded_corners

        edge_0 = corners_array[1] - corners_array[0]
        edge_1 = corners_array[2] - corners_array[1]
        edge_2 = corners_array[3] - corners_array[2]
        edge_3 = corners_array[0] - corners_array[3]

        dim_0_len = (np.linalg.norm(edge_0) + np.linalg.norm(edge_2)) / 2.0
        dim_1_len = (np.linalg.norm(edge_1) + np.linalg.norm(edge_3)) / 2.0

        if dim_0_len <= dim_1_len:
            short_axis = edge_0
        else:
            short_axis = edge_1

        axis_norm = np.linalg.norm(short_axis)
        if axis_norm == 0:
            return [tuple(corner) for corner in corners_array]

        short_axis = short_axis / axis_norm

        expanded_corners = []
        for corner in corners_array:
            offset = corner - center
            axis_proj = float(np.dot(offset, short_axis))
            if axis_proj > 0:
                expanded_corners.append(tuple(corner + short_axis * expansion_px))
            elif axis_proj < 0:
                expanded_corners.append(tuple(corner - short_axis * expansion_px))
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
                        continue

                    # calculate corner angles on expanded corners
                    angles_valid, corner_angles = self._validateCornerAngles(
                        expanded_corners, CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG
                    )

                    if not angles_valid:
                        continue

                    self._cached_feeding_platform_corners = expanded_corners
                    self._cached_feeding_platform_timestamp = time.time()
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
        _ = confidence_threshold
        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)
        with ThreadPoolExecutor(max_workers=2) as executor:
            top_future = executor.submit(
                self._getMoondreamClassificationCrop, top_frame, "top"
            )
            bottom_future = executor.submit(
                self._getMoondreamClassificationCrop, bottom_frame, "bottom"
            )
            top_crop = top_future.result()
            bottom_crop = bottom_future.result()
        return (top_crop, bottom_crop)

    def _getMoondreamClassificationCrop(
        self, frame: Optional[CameraFrame], camera_label: str
    ) -> Optional[np.ndarray]:
        if frame is None:
            return None

        try:
            box = getDetection(frame.raw)
        except Exception as e:
            self.gc.logger.warn(
                f"Moondream detect failed for {camera_label} classification frame: {e}"
            )
            return frame.raw

        if box is None:
            self.gc.logger.warn(
                f"Moondream found no lego piece in {camera_label} classification frame"
            )
            return frame.raw

        x_min, y_min, x_max, y_max = box
        return frame.raw[y_min:y_max, x_min:x_max]

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
