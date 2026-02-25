from typing import Optional, List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor
import base64
import time
import cv2
import numpy as np

from global_config import GlobalConfig
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from blob_manager import VideoRecorder
from classification.moondream import getDetection
from .camera import CaptureThread
from .aruco_tracker import ArucoTracker
from .types import CameraFrame, VisionResult
from .heatmap_diff import HeatmapDiff
from defs.consts import (
    CHANNEL_SECTION_COUNT, CHANNEL_SECTION_DEG,
    CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
    CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
)

ANNOTATE_ARUCO_TAGS = True
TELEMETRY_INTERVAL_S = 30
CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX = 200
CAROUSEL_FEEDING_PLATFORM_CACHE_MAX_AGE_MS = 60000
CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX = 45
CAROUSEL_FEEDING_PLATFORM_PERIMETER_CONTRACTION_PX = 25
CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX = 70000
CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG = 70
CAROUSEL_FEEDING_PLATFORM_MAX_ASPECT_RATIO = 2.0
CHANNEL_REGION_COUNT = CHANNEL_SECTION_COUNT
CHANNEL_REGION_DEG = CHANNEL_SECTION_DEG
CHANNEL_MASK_CONTRACT_PX = 20

class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: CaptureThread
    _classification_bottom_capture: CaptureThread
    _classification_top_capture: CaptureThread
    _video_recorder: Optional[VideoRecorder]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig):
        self.gc = gc
        self._irl_config = irl_config
        self._feeder_capture = CaptureThread("feeder", irl_config.feeder_camera)
        self._classification_bottom_capture = CaptureThread(
            "classification_bottom", irl_config.classification_camera_bottom
        )
        self._classification_top_capture = CaptureThread(
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
        self._channel_polygons: Optional[Dict[str, np.ndarray]] = None
        self._channel_mask: Optional[np.ndarray] = None
        self._channel_masks: Dict[str, np.ndarray] = {}

        self.heatmap_diff = HeatmapDiff()
        self._carousel_heatmap = HeatmapDiff()

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def start(self) -> None:
        self._feeder_capture.start()
        self._classification_bottom_capture.start()
        self._classification_top_capture.start()
        self._aruco_tracker.start()

    def stop(self) -> None:
        self._aruco_tracker.stop()
        self._feeder_capture.stop()
        self._classification_bottom_capture.stop()
        self._classification_top_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def loadFeederBaseline(self) -> bool:
        from blob_manager import getChannelPolygons, BLOB_DIR

        saved = getChannelPolygons()
        if saved is None:
            self.gc.logger.warn("Channel polygons not found. Run: scripts/channel_polygon_editor.py")
            return False

        polygon_data = saved.get("polygons", {})
        polys = {}
        for key in ("second_channel", "third_channel"):
            pts = polygon_data.get(key)
            if pts:
                polys[key] = np.array(pts, dtype=np.int32)

        if not polys:
            self.gc.logger.warn("Channel polygons empty. Run: scripts/channel_polygon_editor.py")
            return False

        self._channel_polygons = polys

        baseline_dir = BLOB_DIR / "feeder_baseline"
        min_path = baseline_dir / "baseline_min.png"
        max_path = baseline_dir / "baseline_max.png"
        if not (min_path.exists() and max_path.exists()):
            self.gc.logger.warn("Feeder baseline not found. Run: scripts/calibrate_feeder_baseline.py")
            return False

        baseline_min = cv2.imread(str(min_path), cv2.IMREAD_GRAYSCALE)
        baseline_max = cv2.imread(str(max_path), cv2.IMREAD_GRAYSCALE)
        if baseline_min is None or baseline_max is None:
            self.gc.logger.warn("Failed to read feeder baseline images.")
            return False

        # build contracted mask per channel and combined
        contract_kernel = None
        if CHANNEL_MASK_CONTRACT_PX != 0:
            k = abs(CHANNEL_MASK_CONTRACT_PX) * 2 + 1
            contract_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

        def _applyContract(m: np.ndarray) -> np.ndarray:
            if contract_kernel is None:
                return m
            if CHANNEL_MASK_CONTRACT_PX < 0:
                return cv2.erode(m, contract_kernel)
            return cv2.dilate(m, contract_kernel)

        channel_masks: Dict[str, np.ndarray] = {}
        for key, pts in polys.items():
            ch_mask = np.zeros(baseline_min.shape[:2], dtype=np.uint8)
            cv2.fillPoly(ch_mask, [pts], 255)
            channel_masks[key] = _applyContract(ch_mask)
        self._channel_masks = channel_masks

        mask = np.zeros(baseline_min.shape[:2], dtype=np.uint8)
        for ch_mask in channel_masks.values():
            mask = cv2.bitwise_or(mask, ch_mask)

        self._channel_mask = mask
        self.heatmap_diff.loadEnvelope(baseline_min, baseline_max, mask)
        self.gc.logger.info("Feeder baseline loaded")
        return True

    def recordFrames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
            # update feeding platform cache on every frame
            with prof.timer("vision.record_frames.update_feeding_platform_cache_ms"):
                self.updateFeedingPlatformCache()

            # push feeder frame to both heatmap ring buffers
            gray = self.getLatestFeederGray()
            if gray is not None:
                self.heatmap_diff.pushFrame(gray)
                self._carousel_heatmap.pushFrame(gray)

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
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None

        if not ANNOTATE_ARUCO_TAGS:
            return frame

        # annotate with ArUco tags
        annotated = frame.raw.copy()
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

        # annotate c-channel heatmap diff overlay
        if self.heatmap_diff.has_baseline:
            annotated = self.heatmap_diff.annotateFrame(annotated)
            from subsystems.feeder.analysis import getBboxSections
            for det in self.getFeederHeatmapDetections():
                x1, y1, x2, y2 = det.bbox
                secs = getBboxSections(det.bbox, det.channel)
                precise = bool(secs & set(CH3_PRECISE_SECTIONS if det.channel_id == 3 else CH2_PRECISE_SECTIONS))
                drop = bool(secs & set(CH3_DROPZONE_SECTIONS if det.channel_id == 3 else CH2_DROPZONE_SECTIONS))
                label = f"ch{det.channel_id} {sorted(secs)} p={precise} d={drop}"
                cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)

        # annotate carousel platform heatmap diff overlay
        if self._carousel_heatmap.has_baseline:
            annotated = self._carousel_heatmap.annotateFrame(annotated)

        return CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=frame.results,
            timestamp=frame.timestamp,
            segmentation_map=frame.segmentation_map,
        )

    def getLatestFeederGray(self) -> Optional[np.ndarray]:
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    @property
    def classification_bottom_frame(self) -> Optional[CameraFrame]:
        return self._classification_bottom_capture.latest_frame

    @property
    def classification_top_frame(self) -> Optional[CameraFrame]:
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

    def captureCarouselBaseline(self) -> bool:
        corners = self.feeding_platform_corners
        if corners is None:
            return False
        gray = self.getLatestFeederGray()
        if gray is None:
            return False
        return self._carousel_heatmap.captureBaseline(corners, gray.shape)

    def clearCarouselBaseline(self) -> None:
        self._carousel_heatmap.clearBaseline()

    def isCarouselTriggered(self) -> Tuple[bool, float, int]:
        score, hot_px = self._carousel_heatmap.computeDiff()
        from vision.heatmap_diff import TRIGGER_SCORE
        return score >= TRIGGER_SCORE, score, hot_px

    def getFeederHeatmapDetections(self):
        from defs.channel import ChannelDetection
        from subsystems.feeder.analysis import computeChannelGeometry, determineObjectChannel

        if not self.heatmap_diff.has_baseline or self._channel_polygons is None:
            return []

        bboxes = self.heatmap_diff.computeBboxes()
        if not bboxes:
            return []

        aruco_tags = self.getFeederArucoTags()
        geometry = computeChannelGeometry(
            self._channel_polygons, aruco_tags,
            self._irl_config.aruco_tags, self._channel_masks,
        )

        detections = []
        for bbox in bboxes:
            x1, y1, x2, y2 = bbox
            ch = determineObjectChannel(((x1 + x2) / 2.0, (y1 + y2) / 2.0), geometry)
            if ch is not None:
                detections.append(ChannelDetection(bbox=bbox, channel_id=ch.channel_id, channel=ch))
        return detections

    def getChannelGeometry(self, aruco_tag_config):
        from defs.channel import ChannelGeometry
        from subsystems.feeder.analysis import computeChannelGeometry

        if self._channel_polygons is None:
            return ChannelGeometry(second_channel=None, third_channel=None)

        prof = self.gc.profiler
        prof.hit("vision.get_channel_geometry.calls")
        with prof.timer("vision.get_channel_geometry.total_ms"):
            aruco_tags = self.getFeederArucoTags()
            return computeChannelGeometry(
                self._channel_polygons, aruco_tags, aruco_tag_config, self._channel_masks
            )

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
        if self._channel_polygons is None:
            return annotated

        annotated = annotated.copy()
        aruco_tags = self.getFeederArucoTags()

        channel_styles = {
            "third_channel":  {"color": (255, 0, 255),   "label": "Ch3"},
            "second_channel": {"color": (0, 255, 255),   "label": "Ch2"},
        }

        for key, style in channel_styles.items():
            pts = self._channel_polygons.get(key)
            if pts is None:
                continue
            color = style["color"]

            # draw contracted mask boundary if available, else raw polygon
            ch_mask = self._channel_masks.get(key)
            if ch_mask is not None:
                contours, _ = cv2.findContours(ch_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(annotated, contours, -1, color, 2)
            else:
                cv2.polylines(annotated, [pts], True, color, 2)

            center = np.mean(pts, axis=0)
            cx, cy = int(center[0]), int(center[1])
            disp_r = int(np.max(np.linalg.norm(pts - center, axis=1)))

            r1_angle = 0.0
            r1_id = (
                self._irl_config.aruco_tags.third_c_channel_radius1_id
                if key == "third_channel"
                else self._irl_config.aruco_tags.second_c_channel_radius1_id
            )
            r1_pos = aruco_tags.get(r1_id)
            if r1_pos:
                v = np.array(r1_pos) - center
                r1_angle = float(np.degrees(np.arctan2(v[1], v[0])))

            precise_sections = CH3_PRECISE_SECTIONS if key == "third_channel" else CH2_PRECISE_SECTIONS
            dropzone_sections = CH3_DROPZONE_SECTIONS if key == "third_channel" else CH2_DROPZONE_SECTIONS
            ch_mask = self._channel_masks.get(key)

            overlay = annotated.copy()
            for q in range(CHANNEL_REGION_COUNT):
                if q in precise_sections:
                    fill = (0, 80, 255)
                elif q in dropzone_sections:
                    fill = (0, 200, 80)
                else:
                    fill = None
                if fill is not None:
                    arc_pts = [(cx, cy)]
                    for a in np.linspace(
                        r1_angle + q * CHANNEL_REGION_DEG,
                        r1_angle + (q + 1) * CHANNEL_REGION_DEG,
                        8,
                    ):
                        arc_pts.append((
                            int(cx + disp_r * np.cos(np.radians(a))),
                            int(cy + disp_r * np.sin(np.radians(a))),
                        ))
                    cv2.fillPoly(overlay, [np.array(arc_pts, dtype=np.int32)], fill)
            if ch_mask is not None:
                overlay[ch_mask == 0] = annotated[ch_mask == 0]
            annotated = cv2.addWeighted(overlay, 0.36, annotated, 0.64, 0)

            dim_color = tuple(int(c * 0.7) for c in color)
            for q in range(CHANNEL_REGION_COUNT):
                angle_rad = np.radians(r1_angle + q * CHANNEL_REGION_DEG)
                ex = int(cx + disp_r * np.cos(angle_rad))
                ey = int(cy + disp_r * np.sin(angle_rad))
                cv2.line(annotated, (cx, cy), (ex, ey), dim_color, 1)

            for q in range(CHANNEL_REGION_COUNT):
                angle_rad = np.radians(r1_angle + q * CHANNEL_REGION_DEG + CHANNEL_REGION_DEG / 2.0)
                lx = int(cx + disp_r * 0.7 * np.cos(angle_rad))
                ly = int(cy + disp_r * 0.7 * np.sin(angle_rad))
                cv2.putText(annotated, str(q), (lx - 6, ly + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 0), 2)
                cv2.putText(annotated, str(q), (lx - 6, ly + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

            cv2.putText(annotated, style["label"], (cx - 20, cy - disp_r - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

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
        self, corners: List[Tuple[float, float]], expansion_px: float,
        contraction_px: float = 0.0,
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
            long_axis = edge_1
        else:
            short_axis = edge_1
            long_axis = edge_0

        short_norm = np.linalg.norm(short_axis)
        long_norm = np.linalg.norm(long_axis)
        if short_norm == 0:
            return [tuple(corner) for corner in corners_array]

        short_axis = short_axis / short_norm
        long_axis = long_axis / long_norm if long_norm > 0 else long_axis

        result = []
        for corner in corners_array:
            offset = corner - center
            short_proj = float(np.dot(offset, short_axis))
            long_proj = float(np.dot(offset, long_axis))
            new_corner = corner.copy()
            # expand along short axis
            if short_proj > 0:
                new_corner = new_corner + short_axis * expansion_px
            elif short_proj < 0:
                new_corner = new_corner - short_axis * expansion_px
            # contract along long axis
            if contraction_px > 0:
                if long_proj > 0:
                    new_corner = new_corner - long_axis * contraction_px
                elif long_proj < 0:
                    new_corner = new_corner + long_axis * contraction_px
            result.append(tuple(new_corner))

        return result

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
                        corners, CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX,
                        CAROUSEL_FEEDING_PLATFORM_PERIMETER_CONTRACTION_PX,
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

                    # compute aspect ratio from averaged opposite side lengths
                    ca = np.array(expanded_corners)
                    d0 = (np.linalg.norm(ca[1] - ca[0]) + np.linalg.norm(ca[3] - ca[2])) / 2.0
                    d1 = (np.linalg.norm(ca[2] - ca[1]) + np.linalg.norm(ca[0] - ca[3])) / 2.0
                    if min(d0, d1) > 0 and max(d0, d1) / min(d0, d1) > CAROUSEL_FEEDING_PLATFORM_MAX_ASPECT_RATIO:
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
            top = self._classification_top_capture.latest_frame
            bottom = self._classification_bottom_capture.latest_frame
            if (
                top
                and bottom
                and top.timestamp > start_time
                and bottom.timestamp > start_time
            ):
                return (top, bottom)
            time.sleep(0.05)
        return (
            self._classification_top_capture.latest_frame,
            self._classification_bottom_capture.latest_frame,
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
