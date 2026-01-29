from typing import Optional, List, Dict, Tuple
import base64
import time
import cv2
import cv2.aruco as aruco
import numpy as np

from global_config import GlobalConfig
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from blob_manager import VideoRecorder
from .camera import CaptureThread
from .inference import InferenceThread, CameraModelBinding
from .types import CameraFrame, VisionResult


class VisionManager:
    _feeder_capture: CaptureThread
    _classification_bottom_capture: CaptureThread
    _classification_top_capture: CaptureThread
    _inference: InferenceThread
    _feeder_binding: CameraModelBinding
    _classification_bottom_binding: CameraModelBinding
    _classification_top_binding: CameraModelBinding
    _video_recorder: Optional[VideoRecorder]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig):
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
            self._feeder_capture, feeder_model
        )
        self._classification_bottom_binding = self._inference.addBinding(
            self._classification_bottom_capture, classification_model
        )
        self._classification_top_binding = self._inference.addBinding(
            self._classification_top_capture, classification_model
        )

        self._video_recorder = VideoRecorder() if gc.should_write_camera_feeds else None

        self._aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self._aruco_params = aruco.DetectorParameters()

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
        if not self._video_recorder:
            return
        for camera in ["feeder", "classification_bottom", "classification_top"]:
            frame = self.getFrame(camera)
            if frame:
                self._video_recorder.writeFrame(camera, frame.raw, frame.annotated)

    @property
    def feeder_frame(self) -> Optional[CameraFrame]:
        return (
            self._feeder_binding.latest_annotated_frame
            or self._feeder_capture.latest_frame
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

        gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
        detector = aruco.ArucoDetector(self._aruco_dict, self._aruco_params)
        corners, ids, _ = detector.detectMarkers(gray)

        result: Dict[int, Tuple[float, float]] = {}
        if ids is not None:
            for i, tag_id in enumerate(ids.flatten()):
                tag_corners = corners[i][0]
                center_x = float(np.mean(tag_corners[:, 0]))
                center_y = float(np.mean(tag_corners[:, 1]))
                result[int(tag_id)] = (center_x, center_y)
        return result

    def getFeederMasksByClass(self) -> Dict[int, List[np.ndarray]]:
        results = self._feeder_binding.latest_raw_results
        if not results or len(results) == 0:
            return {}

        masks_by_class: Dict[int, List[np.ndarray]] = {}
        for result in results:
            if result.masks is not None:
                for i, mask in enumerate(result.masks):
                    class_id = int(result.boxes[i].cls.item())
                    mask_data = mask.data[0].cpu().numpy()
                    if class_id not in masks_by_class:
                        masks_by_class[class_id] = []
                    masks_by_class[class_id].append(mask_data)
        return masks_by_class

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

        result_data = None
        if frame.result:
            result_data = FrameResultData(
                class_id=frame.result.class_id,
                class_name=frame.result.class_name,
                confidence=frame.result.confidence,
                bbox=frame.result.bbox,
            )

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
                result=result_data,
            ),
        )

    def getAllFrameEvents(self) -> List[FrameEvent]:
        events = []
        for camera in CameraName:
            event = self.getFrameEvent(camera)
            if event:
                events.append(event)
        return events
