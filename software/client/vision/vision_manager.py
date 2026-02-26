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
from .types import CameraFrame
from .heatmap_diff import HeatmapDiff
from defs.consts import (
    CHANNEL_SECTION_COUNT, CHANNEL_SECTION_DEG,
    CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
    CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
)

TELEMETRY_INTERVAL_S = 30
CHANNEL_REGION_COUNT = CHANNEL_SECTION_COUNT
CHANNEL_REGION_DEG = CHANNEL_SECTION_DEG
CHANNEL_MASK_CONTRACT_PX = 30

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

        self._carousel_polygon: Optional[List[Tuple[float, float]]] = None
        self._channel_angles: Dict[str, float] = {}
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

    def stop(self) -> None:
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

        # load carousel polygon
        carousel_pts = polygon_data.get("carousel")
        if carousel_pts and len(carousel_pts) >= 3:
            self._carousel_polygon = [(float(p[0]), float(p[1])) for p in carousel_pts]
        else:
            self.gc.logger.warn("Carousel polygon not found. Run: scripts/channel_polygon_editor.py")
            return False

        # load channel angles
        self._channel_angles = saved.get("channel_angles", {})

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

        annotated = frame.raw.copy()

        # annotate with channel and carousel geometry
        annotated = self._annotateChannelGeometry(annotated)
        annotated = self._annotateCarouselPlatforms(annotated)

        # annotate c-channel heatmap diff overlay
        if self.heatmap_diff.has_baseline:
            annotated = self.heatmap_diff.annotateFrame(annotated, label="feeder", text_y=50)
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
            annotated = self._carousel_heatmap.annotateFrame(annotated, label="carousel", text_y=80)

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

        geometry = computeChannelGeometry(
            self._channel_polygons, self._channel_angles, self._channel_masks,
        )

        detections = []
        for bbox in bboxes:
            x1, y1, x2, y2 = bbox
            ch = determineObjectChannel(((x1 + x2) / 2.0, (y1 + y2) / 2.0), geometry)
            if ch is not None:
                detections.append(ChannelDetection(bbox=bbox, channel_id=ch.channel_id, channel=ch))
        return detections

    def getChannelGeometry(self):
        from defs.channel import ChannelGeometry
        from subsystems.feeder.analysis import computeChannelGeometry

        if self._channel_polygons is None:
            return ChannelGeometry(second_channel=None, third_channel=None)

        prof = self.gc.profiler
        prof.hit("vision.get_channel_geometry.calls")
        with prof.timer("vision.get_channel_geometry.total_ms"):
            return computeChannelGeometry(
                self._channel_polygons, self._channel_angles, self._channel_masks
            )

    @property
    def feeding_platform_corners(self) -> Optional[List[Tuple[float, float]]]:
        return self._carousel_polygon

    def _annotateChannelGeometry(self, annotated: np.ndarray) -> np.ndarray:
        if self._channel_polygons is None:
            return annotated

        annotated = annotated.copy()

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

            r1_angle = self._channel_angles.get(
                "third" if key == "third_channel" else "second", 0.0
            )

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
            result = cv2.pointPolygonTest(points, point, False)
            if result >= 0:
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
