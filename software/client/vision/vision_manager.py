from typing import Optional, List, Dict, Tuple, Union
import base64
import time
import cv2
import numpy as np

from global_config import GlobalConfig
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from blob_manager import VideoRecorder
from .camera import CaptureThread
from .types import CameraFrame, VisionResult, DetectedMask
from .regions import RegionName, Region
from .aruco_region_provider import ArucoRegionProvider
from .default_region_provider import DefaultRegionProvider

TELEMETRY_INTERVAL_S = 30


class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: CaptureThread
    _classification_bottom_capture: Optional[CaptureThread]
    _classification_top_capture: Optional[CaptureThread]
    _video_recorder: Optional[VideoRecorder]
    _region_provider: Union[ArucoRegionProvider, DefaultRegionProvider]

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

        if gc.disable_aruco:
            self._region_provider = DefaultRegionProvider()
        else:
            self._region_provider = ArucoRegionProvider(gc, self._feeder_capture, irl_config)

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def setArucoSmoothingTimeSeconds(self, smoothing_time_s: float) -> None:
        if isinstance(self._region_provider, ArucoRegionProvider):
            self._region_provider.setSmoothingTimeSeconds(smoothing_time_s)

    def start(self) -> None:
        self._feeder_capture.start()
        if self._classification_bottom_capture:
            self._classification_bottom_capture.start()
        if self._classification_top_capture:
            self._classification_top_capture.start()
        self._region_provider.start()

    def stop(self) -> None:
        self._region_provider.stop()
        self._feeder_capture.stop()
        if self._classification_bottom_capture:
            self._classification_bottom_capture.stop()
        if self._classification_top_capture:
            self._classification_top_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def getRegions(self) -> dict[RegionName, Region]:
        prof = self.gc.profiler
        prof.hit("vision.get_regions.calls")
        with prof.timer("vision.get_regions.total_ms"):
            frame = self._feeder_capture.latest_frame
            if frame is None:
                return {}
            return self._region_provider.getRegions(frame.raw)

    def recordFrames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
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

        annotated = frame.annotated if frame.annotated is not None else frame.raw
        annotated = self._region_provider.annotateFrame(annotated)

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
        if isinstance(self._region_provider, ArucoRegionProvider):
            return self._region_provider.getTags()
        return {}

    def getFeederArucoTagsRaw(self) -> Dict[int, Tuple[float, float]]:
        if isinstance(self._region_provider, ArucoRegionProvider):
            return self._region_provider.getRawTags()
        return {}

    # stubbed — no inference engine
    def getFeederDetectionsByClass(self) -> Dict[int, List[VisionResult]]:
        return {}

    # stubbed — no inference engine
    def getFeederMasksByClass(self) -> Dict[int, List[DetectedMask]]:
        return {}

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
