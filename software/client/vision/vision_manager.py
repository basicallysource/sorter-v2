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
from defs.consts import FEEDER_OBJECT_CLASS_ID, FEEDER_CHANNEL_CLASS_ID
from blob_manager import VideoRecorder
from .camera import CaptureThread
from .inference import InferenceThread, CameraModelBinding
from .types import CameraFrame, VisionResult, DetectedMask

ANNOTATE_ARUCO_TAGS = True
ARUCO_TAG_CACHE_MS = 5000
FEEDER_MASK_CACHE_FRAMES = 3
TELEMETRY_INTERVAL_S = 30


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
            exclude_classes_from_plot=[FEEDER_CHANNEL_CLASS_ID],
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

        self._aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_ARUCO_ORIGINAL)
        self._aruco_params = aruco.DetectorParameters()
        self._aruco_tag_cache: Dict[int, Tuple[Tuple[float, float], float]] = {}
        self._feeder_mask_cache: deque = deque(maxlen=FEEDER_MASK_CACHE_FRAMES)

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
        if self._video_recorder:
            for camera in ["feeder", "classification_bottom", "classification_top"]:
                frame = self.getFrame(camera)
                if frame:
                    self._video_recorder.writeFrame(camera, frame.raw, frame.annotated)
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
                    (center_x - 10, center_y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 0),  # aqua/cyan
                    2,
                )

        # annotate with channel geometry
        annotated = self._annotateChannelGeometry(annotated)

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
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return {}

        current_time = time.time()
        gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
        detector = aruco.ArucoDetector(self._aruco_dict, self._aruco_params)
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

        return result

    def getFeederMasksByClass(self) -> Dict[int, List[DetectedMask]]:
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
            return aggregated

        # process current frame
        current_frame_all_masks: Dict[int, List[DetectedMask]] = {}
        current_frame_object_masks: List[DetectedMask] = []

        for result in results:
            if result.masks is not None:
                for i, mask in enumerate(result.masks):
                    class_id = int(result.boxes[i].cls.item())
                    confidence = float(result.boxes[i].conf.item())
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
                        scaled_mask = cv2.resize(
                            mask_data.astype(np.uint8),
                            (camera_width, camera_height),
                            interpolation=cv2.INTER_NEAREST,
                        ).astype(bool)
                    else:
                        scaled_mask = mask_data.astype(bool)

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

        return result_masks

    def getChannelGeometry(self, aruco_tag_config):
        from subsystems.feeder.analysis import computeChannelGeometry

        aruco_tags = self.getFeederArucoTags()
        return computeChannelGeometry(aruco_tags, aruco_tag_config)

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
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)
        top_crop = self._extractLargestObjectCrop(
            top_frame, self._classification_top_binding.latest_raw_results
        )
        bottom_crop = self._extractLargestObjectCrop(
            bottom_frame, self._classification_bottom_binding.latest_raw_results
        )
        return (top_crop, bottom_crop)

    def _extractLargestObjectCrop(
        self, frame: Optional[CameraFrame], raw_results
    ) -> Optional[np.ndarray]:
        if frame is None or raw_results is None or len(raw_results) == 0:
            return None

        boxes = raw_results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        best_box = None
        best_area = 0
        for box in boxes:
            class_id = int(box.cls[0])
            if class_id != 0:
                continue
            xyxy = box.xyxy[0].tolist()
            area = (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1])
            if area > best_area:
                best_area = area
                best_box = xyxy

        if best_box is None:
            return None

        x1, y1, x2, y2 = map(int, best_box)
        return frame.raw[y1:y2, x1:x2]

    def _encodeFrame(self, frame) -> str:
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode("utf-8")

    def getFrameEvent(self, camera_name: CameraName) -> Optional[FrameEvent]:
        frame = self.getFrame(camera_name.value)
        if frame is None:
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

        return FrameEvent(
            tag="frame",
            data=FrameData(
                camera=camera_name,
                timestamp=frame.timestamp,
                raw=raw_b64,
                annotated=annotated_b64,
                results=results_data,
            ),
        )

    def getAllFrameEvents(self) -> List[FrameEvent]:
        events = []
        for camera in CameraName:
            event = self.getFrameEvent(camera)
            if event:
                events.append(event)
        return events
