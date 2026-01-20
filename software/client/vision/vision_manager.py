from typing import Optional

from global_config import GlobalConfig
from irl.config import IRLConfig
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
