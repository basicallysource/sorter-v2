from typing import Optional, List, Dict, Tuple
import base64
import time
import cv2
import numpy as np

from global_config import GlobalConfig
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from blob_manager import VideoRecorder
from .camera import CaptureThread
from .aruco_tracker import ArucoTracker
from .types import CameraFrame, VisionResult, DetectedMask

ANNOTATE_ARUCO_TAGS = True
TELEMETRY_INTERVAL_S = 30
CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX = 200
CAROUSEL_FEEDING_PLATFORM_CACHE_MAX_AGE_MS = 60000
CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX = 30
CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX = 70000
CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG = 70


class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: CaptureThread
    _classification_bottom_capture: Optional[CaptureThread]
    _classification_top_capture: Optional[CaptureThread]
    _video_recorder: Optional[VideoRecorder]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig):
        self.gc = gc
        self._irl_config = irl_config
        self._feeder_camera_config = irl_config.feeder_camera
        self._disabled_cameras = set(gc.disable_video_streams)

        if "feeder" in self._disabled_cameras:
            raise RuntimeError("Cannot disable feeder camera — it is required for operation")

        self._feeder_capture = CaptureThread("feeder", irl_config.feeder_camera)

        if "classification_bottom" in self._disabled_cameras and "classification_top" in self._disabled_cameras:
            raise RuntimeError("Cannot disable both classification cameras — at least one is required")

        self._classification_bottom_capture = None if "classification_bottom" in self._disabled_cameras else CaptureThread(
            "classification_bottom", irl_config.classification_camera_bottom
        )
        self._classification_top_capture = None if "classification_top" in self._disabled_cameras else CaptureThread(
            "classification_top", irl_config.classification_camera_top
        )

        self._video_recorder = VideoRecorder() if gc.should_write_camera_feeds else None

        self._telemetry = None
        self._last_telemetry_save = 0.0

        self._aruco_tracker = ArucoTracker(gc, self._feeder_capture)
        self._cached_feeding_platform_corners: Optional[List[Tuple[float, float]]] = (
            None
        )
        self._cached_feeding_platform_timestamp: float = 0.0

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def setArucoSmoothingTimeSeconds(self, smoothing_time_s: float) -> None:
        self._aruco_tracker.setSmoothingTimeSeconds(smoothing_time_s)

    def start(self) -> None:
        self._feeder_capture.start()
        if self._classification_bottom_capture:
            self._classification_bottom_capture.start()
        if self._classification_top_capture:
            self._classification_top_capture.start()
        self._aruco_tracker.start()

    def stop(self) -> None:
        self._aruco_tracker.stop()
        self._feeder_capture.stop()
        if self._classification_bottom_capture:
            self._classification_bottom_capture.stop()
        if self._classification_top_capture:
            self._classification_top_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def recordFrames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
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
            if frame and frame.raw is not None:
                self._telemetry.saveCapture(
                    telemetry_name,
                    frame.raw,
                    frame.annotated,
                    "interval",
                )

    @property
    def feeder_frame(self) -> Optional[CameraFrame]:
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None

        if not ANNOTATE_ARUCO_TAGS:
            return frame

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

        annotated = self._annotateChannelGeometry(annotated)
        annotated = self._annotateCarouselPlatforms(annotated)

        return CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=[],
            timestamp=frame.timestamp,
        )

    @property
    def classification_bottom_frame(self) -> Optional[CameraFrame]:
        if self._classification_bottom_capture is None:
            return None
        return self._classification_bottom_capture.latest_frame

    @property
    def classification_top_frame(self) -> Optional[CameraFrame]:
        if self._classification_top_capture is None:
            return None
        return self._classification_top_capture.latest_frame

    def getFrame(self, camera_name: str) -> Optional[CameraFrame]:
        if camera_name == "feeder":
            return self.feeder_frame
        elif camera_name == "classification_bottom":
            return self.classification_bottom_frame
        elif camera_name == "classification_top":
            return self.classification_top_frame
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

    def getFeederArucoTagsRaw(self) -> Dict[int, Tuple[float, float]]:
        return self._aruco_tracker.getRawTags()

    # stubbed — no inference engine
    def getFeederDetectionsByClass(self) -> Dict[int, List[VisionResult]]:
        return {}

    # stubbed — no inference engine
    def getFeederMasksByClass(self) -> Dict[int, List[DetectedMask]]:
        return {}

    def getChannelGeometry(self, aruco_tag_config):
        from subsystems.feeder.analysis import computeChannelGeometry

        prof = self.gc.profiler
        prof.hit("vision.get_channel_geometry.calls")
        with prof.timer("vision.get_channel_geometry.total_ms"):
            aruco_tags = self.getFeederArucoTags()
            return computeChannelGeometry(aruco_tags, aruco_tag_config)

    def getCarouselPlatforms(self):
        aruco_tags = self.getFeederArucoTags()
        platforms = []

        for i, platform_config in enumerate(
            [
                self._irl_config.aruco_tags.carousel_platform1,
                self._irl_config.aruco_tags.carousel_platform2,
                self._irl_config.aruco_tags.carousel_platform3,
                self._irl_config.aruco_tags.carousel_platform4,
            ]
        ):
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

            if len(detected_corners) >= 3:
                corners = list(detected_corners.values())

                if len(detected_corners) == 3:
                    p0, p1, p2 = [np.array(c) for c in corners]

                    candidates = [
                        p0 + p1 - p2,
                        p0 + p2 - p1,
                        p1 + p2 - p0,
                    ]

                    best_candidate = candidates[0]
                    best_score = float("inf")

                    for candidate in candidates:
                        quad = [p0, p1, p2, candidate]

                        distances = []
                        for j in range(4):
                            for k in range(j + 1, 4):
                                dist = np.linalg.norm(quad[j] - quad[k])
                                distances.append(dist)

                        score = np.std(distances)

                        if score < best_score:
                            best_score = score
                            best_candidate = candidate

                    corners.append(tuple(best_candidate))

                if len(corners) >= 3:
                    corners_array = np.array(corners)
                    centroid = np.mean(corners_array, axis=0)

                    angles = []
                    for corner in corners:
                        dx = corner[0] - centroid[0]
                        dy = corner[1] - centroid[1]
                        angle = np.arctan2(dy, dx)
                        angles.append(angle)

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

        # draw channel 3 (inner)
        if geometry.third_channel:
            ch = geometry.third_channel
            center = (int(ch.center[0]), int(ch.center[1]))
            radius = int(ch.radius)

            if ch.shape == "ellipse" and ch.ellipse_axes is not None:
                axes = (int(ch.ellipse_axes[0]), int(ch.ellipse_axes[1]))
                cv2.ellipse(
                    annotated,
                    center,
                    axes,
                    ch.ellipse_angle_deg,
                    0,
                    360,
                    (255, 0, 255),
                    2,
                )
            else:
                cv2.circle(annotated, center, radius, (255, 0, 255), 2)

            if ch.radius_points:
                for rp in ch.radius_points:
                    cv2.circle(annotated, (int(rp[0]), int(rp[1])), 4, (255, 0, 255), -1)

            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0
                angle_rad = np.radians(angle_deg)
                end_x = int(center[0] + radius * np.cos(angle_rad))
                end_y = int(center[1] + radius * np.sin(angle_rad))
                cv2.line(annotated, center, (end_x, end_y), (180, 0, 180), 1)

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

            cv2.putText(
                annotated,
                f"Ch3 {ch.mode}",
                (center[0] - 20, center[1] - radius - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 0, 255),
                2,
            )

        # draw channel 2 (outer)
        if geometry.second_channel:
            ch = geometry.second_channel
            center = (int(ch.center[0]), int(ch.center[1]))
            radius = int(ch.radius)

            if ch.shape == "ellipse" and ch.ellipse_axes is not None:
                axes = (int(ch.ellipse_axes[0]), int(ch.ellipse_axes[1]))
                cv2.ellipse(
                    annotated,
                    center,
                    axes,
                    ch.ellipse_angle_deg,
                    0,
                    360,
                    (0, 255, 255),
                    2,
                )
            else:
                cv2.circle(annotated, center, radius, (0, 255, 255), 2)

            if ch.radius_points:
                for rp in ch.radius_points:
                    cv2.circle(annotated, (int(rp[0]), int(rp[1])), 4, (0, 255, 255), -1)

            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0
                angle_rad = np.radians(angle_deg)
                end_x = int(center[0] + radius * np.cos(angle_rad))
                end_y = int(center[1] + radius * np.sin(angle_rad))
                cv2.line(annotated, center, (end_x, end_y), (0, 180, 180), 1)

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

            cv2.putText(
                annotated,
                f"Ch2 {ch.mode}",
                (center[0] - 20, center[1] - radius - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
            )

        return annotated

    def _annotateCarouselPlatforms(self, annotated: np.ndarray) -> np.ndarray:
        corners = self.feeding_platform_corners
        if corners is None:
            return annotated

        annotated = annotated.copy()

        color = (255, 255, 0)
        points = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
        cv2.polylines(annotated, [points], isClosed=True, color=color, thickness=2)

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
        corners_array = np.array(corners)
        n = len(corners_array)
        angles = []

        for i in range(n):
            prev = corners_array[(i - 1) % n]
            curr = corners_array[i]
            next_pt = corners_array[(i + 1) % n]

            v1 = prev - curr
            v2 = next_pt - curr

            cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
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

        for platform in platforms:
            corners = platform["corners"]
            if len(corners) >= 3:
                center_x = np.mean([x for x, y in corners])
                center_y = np.mean([y for x, y in corners])
                platform_center = np.array([center_x, center_y])

                distance = np.linalg.norm(platform_center - reference_pos)

                if distance <= CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX:
                    expanded_corners = self._expandRectanglePerimeter(
                        corners, CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX
                    )

                    corners_array = np.array(expanded_corners)
                    x = corners_array[:, 0]
                    y = corners_array[:, 1]
                    area = 0.5 * np.abs(
                        np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))
                    )

                    if area > CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX:
                        continue

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

        age_ms = (time.time() - self._cached_feeding_platform_timestamp) * 1000
        if age_ms > CAROUSEL_FEEDING_PLATFORM_CACHE_MAX_AGE_MS:
            return None

        return self._cached_feeding_platform_corners

    # stubbed — no inference engine
    def isObjectOnCarouselPlatform(self, object_mask: np.ndarray) -> bool:
        return False

    def captureFreshClassificationFrames(
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[CameraFrame], Optional[CameraFrame]]:
        has_top = self._classification_top_capture is not None
        has_bottom = self._classification_bottom_capture is not None
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            top = self._classification_top_capture.latest_frame if self._classification_top_capture else None
            bottom = self._classification_bottom_capture.latest_frame if self._classification_bottom_capture else None
            top_ready = not has_top or (top and top.timestamp > start_time)
            bottom_ready = not has_bottom or (bottom and bottom.timestamp > start_time)
            if top_ready and bottom_ready:
                return (top, bottom)
            time.sleep(0.05)
        return (
            self._classification_top_capture.latest_frame if self._classification_top_capture else None,
            self._classification_bottom_capture.latest_frame if self._classification_bottom_capture else None,
        )

    # stubbed — returns raw frames, no crop detection
    def getClassificationCrops(
        self, timeout_s: float = 1.0, confidence_threshold: float = 0.0
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)
        top_crop = top_frame.raw if top_frame is not None else None
        bottom_crop = bottom_frame.raw if bottom_frame is not None else None
        return (top_crop, bottom_crop)

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
