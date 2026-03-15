from typing import Optional, List, Dict, Tuple, Union
import base64
import time
import threading
import cv2
import numpy as np

from global_config import GlobalConfig, RegionProviderType
from irl.config import IRLConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from defs.channel import ChannelDetection
from blob_manager import VideoRecorder, getClassificationPolygons
from .camera import CaptureThread
from .types import CameraFrame, VisionResult, DetectedMask
from .regions import RegionName, Region
from .aruco_region_provider import ArucoRegionProvider
from .default_region_provider import DefaultRegionProvider
from .handdrawn_region_provider import HanddrawnRegionProvider
from .heatmap_diff import HeatmapDiff
from .feeder_analysis_thread import FeederAnalysisThread
from .classification_analysis_thread import ClassificationAnalysisThread

TELEMETRY_INTERVAL_S = 30
CHANNEL_MASK_CONTRACT_PX = 30
FRAME_ENCODE_INTERVAL_MS = 100


class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: CaptureThread
    _classification_bottom_capture: Optional[CaptureThread]
    _classification_top_capture: Optional[CaptureThread]
    _video_recorder: Optional[VideoRecorder]
    _region_provider: Union[ArucoRegionProvider, DefaultRegionProvider, HanddrawnRegionProvider]

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

        if gc.region_provider == RegionProviderType.HANDDRAWN:
            self._region_provider = HanddrawnRegionProvider()
        elif gc.region_provider == RegionProviderType.ARUCO:
            self._region_provider = ArucoRegionProvider(gc, self._feeder_capture, irl_config)

        self.heatmap_diff = HeatmapDiff(scale=0.25)
        self._carousel_heatmap = HeatmapDiff()

        self._channel_polygons: Dict[str, np.ndarray] = {}
        self._channel_angles: Dict[str, float] = {}
        self._channel_masks: Dict[str, np.ndarray] = {}
        self._carousel_polygon: List[Tuple[float, float]] | None = None

        self._feeder_analysis: FeederAnalysisThread | None = None
        self._cached_feeder_frame: CameraFrame | None = None
        self._cached_feeder_frame_ts: float = 0.0

        self._classification_masks: Dict[str, np.ndarray] = {}
        self._classification_polygon_resolution: Tuple[int, int] = (1920, 1080)
        self._loadClassificationPolygons()

        self._classification_top_heatmap: HeatmapDiff | None = None
        self._classification_bottom_heatmap: HeatmapDiff | None = None
        self._classification_top_analysis: ClassificationAnalysisThread | None = None
        self._classification_bottom_analysis: ClassificationAnalysisThread | None = None

        self._cached_frame_events: List[FrameEvent] = []
        self._cached_frame_events_lock = threading.Lock()
        self._frame_encode_thread: threading.Thread | None = None
        self._frame_encode_stop = threading.Event()

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
        self._frame_encode_stop.clear()
        self._frame_encode_thread = threading.Thread(
            target=self._frameEncodeLoop, daemon=True
        )
        self._frame_encode_thread.start()

    def stop(self) -> None:
        self._frame_encode_stop.set()
        if self._frame_encode_thread:
            self._frame_encode_thread.join(timeout=2.0)
        if self._feeder_analysis:
            self._feeder_analysis.stop()
        if self._classification_top_analysis:
            self._classification_top_analysis.stop()
        if self._classification_bottom_analysis:
            self._classification_bottom_analysis.stop()
        self._region_provider.stop()
        self._feeder_capture.stop()
        if self._classification_bottom_capture:
            self._classification_bottom_capture.stop()
        if self._classification_top_capture:
            self._classification_top_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def loadFeederBaseline(self) -> bool:
        from blob_manager import getChannelPolygons, BLOB_DIR

        saved = getChannelPolygons()
        if saved is None:
            self.gc.logger.warn("Channel polygons not found. Run: scripts/polygon_editor.py")
            return False

        polygon_data = saved.get("polygons", {})
        polys: Dict[str, np.ndarray] = {}
        for key in ("second_channel", "third_channel"):
            pts = polygon_data.get(key)
            if pts:
                polys[key] = np.array(pts, dtype=np.int32)

        if not polys:
            self.gc.logger.warn("Channel polygons empty. Run: scripts/polygon_editor.py")
            return False

        self._channel_polygons = polys
        self._channel_angles = saved.get("channel_angles", {})

        carousel_pts = polygon_data.get("carousel")
        if carousel_pts and len(carousel_pts) >= 3:
            self._carousel_polygon = [(float(p[0]), float(p[1])) for p in carousel_pts]

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

        self.heatmap_diff.loadEnvelope(baseline_min, baseline_max, mask)

        self._feeder_analysis = FeederAnalysisThread(
            heatmap=self.heatmap_diff,
            get_gray=self.getLatestFeederGray,
            channel_polygons=self._channel_polygons,
            channel_angles=self._channel_angles,
            channel_masks=self._channel_masks,
            profiler=self.gc.profiler,
        )
        self._feeder_analysis.start()
        self.gc.logger.info("Feeder baseline loaded")
        return True

    def loadClassificationBaseline(self) -> bool:
        from blob_manager import BLOB_DIR

        baseline_dir = BLOB_DIR / "classification_baseline"
        loaded_any = False

        for cam_key, capture in [("top", self._classification_top_capture), ("bottom", self._classification_bottom_capture)]:
            if capture is None:
                continue
            min_path = baseline_dir / f"{cam_key}_baseline_min.png"
            max_path = baseline_dir / f"{cam_key}_baseline_max.png"
            if not (min_path.exists() and max_path.exists()):
                self.gc.logger.warn(f"Classification {cam_key} baseline not found. Run: scripts/calibrate_classification_baseline.py")
                continue

            baseline_min = cv2.imread(str(min_path), cv2.IMREAD_GRAYSCALE)
            baseline_max = cv2.imread(str(max_path), cv2.IMREAD_GRAYSCALE)
            if baseline_min is None or baseline_max is None:
                self.gc.logger.warn(f"Failed to read classification {cam_key} baseline images.")
                continue

            frame = capture.latest_frame
            if frame is not None:
                cam_h, cam_w = frame.raw.shape[:2]
                bl_h, bl_w = baseline_min.shape[:2]
                if cam_w != bl_w or cam_h != bl_h:
                    self.gc.logger.info(
                        f"Classification {cam_key} baseline {bl_w}x{bl_h} -> camera {cam_w}x{cam_h}, rescaling"
                    )
                    baseline_min = cv2.resize(baseline_min, (cam_w, cam_h), interpolation=cv2.INTER_AREA)
                    baseline_max = cv2.resize(baseline_max, (cam_w, cam_h), interpolation=cv2.INTER_AREA)

            polygon = self._classification_masks.get(cam_key)
            if polygon is not None:
                scaled = self._scalePolygon(polygon, baseline_min.shape[1], baseline_min.shape[0])
                mask = np.zeros(baseline_min.shape[:2], dtype=np.uint8)
                cv2.fillPoly(mask, [scaled], 255)
            else:
                mask = np.ones(baseline_min.shape[:2], dtype=np.uint8) * 255

            heatmap = HeatmapDiff(scale=0.25, gc=self.gc)
            heatmap.loadEnvelope(baseline_min, baseline_max, mask)

            if cam_key == "top":
                self._classification_top_heatmap = heatmap
                self._classification_top_analysis = ClassificationAnalysisThread(
                    name="top",
                    heatmap=heatmap,
                    get_gray=self._getLatestClassificationTopGray,
                    profiler=self.gc.profiler,
                    logger=self.gc.logger,
                )
                self._classification_top_analysis.start()
            else:
                self._classification_bottom_heatmap = heatmap
                self._classification_bottom_analysis = ClassificationAnalysisThread(
                    name="bottom",
                    heatmap=heatmap,
                    get_gray=self._getLatestClassificationBottomGray,
                    profiler=self.gc.profiler,
                    logger=self.gc.logger,
                )
                self._classification_bottom_analysis.start()

            self.gc.logger.info(f"Classification {cam_key} baseline loaded")
            loaded_any = True

        return loaded_any

    def _getLatestClassificationTopGray(self) -> np.ndarray | None:
        if self._classification_top_capture is None:
            return None
        frame = self._classification_top_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    def _getLatestClassificationBottomGray(self) -> np.ndarray | None:
        if self._classification_bottom_capture is None:
            return None
        frame = self._classification_bottom_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    def getClassificationBboxes(self, cam: str) -> List[Tuple[int, int, int, int]]:
        if cam == "top" and self._classification_top_analysis:
            return self._classification_top_analysis.getBboxes()
        if cam == "bottom" and self._classification_bottom_analysis:
            return self._classification_bottom_analysis.getBboxes()
        return []

    def getClassificationCombinedBbox(self, cam: str) -> Tuple[int, int, int, int] | None:
        if cam == "top" and self._classification_top_analysis:
            return self._classification_top_analysis.getCombinedBbox()
        if cam == "bottom" and self._classification_bottom_analysis:
            return self._classification_bottom_analysis.getCombinedBbox()
        return None

    def getLatestFeederGray(self) -> np.ndarray | None:
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    def getRegions(self) -> dict[RegionName, Region]:
        prof = self.gc.profiler
        prof.hit("vision.get_regions.calls")
        with prof.timer("vision.get_regions.total_ms"):
            frame = self._feeder_capture.latest_frame
            if frame is None:
                return {}
            return self._region_provider.getRegions(frame.raw)

    def getFeederHeatmapDetections(self) -> list[ChannelDetection]:
        if self._feeder_analysis is None:
            return []
        return self._feeder_analysis.getDetections()

    def captureCarouselBaseline(self) -> bool:
        if self._carousel_polygon is None:
            return False
        gray = self.getLatestFeederGray()
        if gray is None:
            return False
        return self._carousel_heatmap.captureBaseline(self._carousel_polygon, gray.shape)

    def clearCarouselBaseline(self) -> None:
        self._carousel_heatmap.clearBaseline()

    def isCarouselTriggered(self) -> Tuple[bool, float, int]:
        score, hot_px = self._carousel_heatmap.computeDiff()
        from vision.heatmap_diff import TRIGGER_SCORE
        return score >= TRIGGER_SCORE, score, hot_px

    def recordFrames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
            gray = self.getLatestFeederGray()
            if gray is not None:
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

        if self._cached_feeder_frame is not None and frame.timestamp == self._cached_feeder_frame_ts:
            return self._cached_feeder_frame

        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()
        annotated = self._region_provider.annotateFrame(annotated)

        if self.heatmap_diff.has_baseline:
            annotated = self.heatmap_diff.annotateFrame(annotated, label="feeder", text_y=50)
            from subsystems.feeder.analysis import getBboxSections
            from defs.consts import (
                CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
                CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
            )
            for det in self.getFeederHeatmapDetections():
                x1, y1, x2, y2 = det.bbox
                secs = getBboxSections(det.bbox, det.channel)
                precise = bool(secs & set(CH3_PRECISE_SECTIONS if det.channel_id == 3 else CH2_PRECISE_SECTIONS))
                drop = bool(secs & set(CH3_DROPZONE_SECTIONS if det.channel_id == 3 else CH2_DROPZONE_SECTIONS))
                label = f"ch{det.channel_id} {sorted(secs)} p={precise} d={drop}"
                cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)

        if self._carousel_heatmap.has_baseline:
            annotated = self._carousel_heatmap.annotateFrame(annotated, label="carousel", text_y=80)

        result = CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=[],
            timestamp=frame.timestamp,
        )
        self._cached_feeder_frame = result
        self._cached_feeder_frame_ts = frame.timestamp
        return result

    @property
    def feeding_platform_corners(self) -> List[Tuple[float, float]] | None:
        return self._carousel_polygon

    @property
    def classification_bottom_frame(self) -> Optional[CameraFrame]:
        if self._classification_bottom_capture is None:
            return None
        frame = self._classification_bottom_capture.latest_frame
        if frame is None:
            return None
        return self._annotateClassificationFrame(frame, "bottom", self._classification_bottom_heatmap)

    @property
    def classification_top_frame(self) -> Optional[CameraFrame]:
        if self._classification_top_capture is None:
            return None
        frame = self._classification_top_capture.latest_frame
        if frame is None:
            return None
        return self._annotateClassificationFrame(frame, "top", self._classification_top_heatmap)

    def _annotateClassificationFrame(
        self, frame: CameraFrame, cam: str, heatmap: HeatmapDiff | None
    ) -> CameraFrame:
        if heatmap is None or not heatmap.has_baseline:
            return frame
        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()
        annotated = heatmap.annotateFrame(annotated, label=f"class_{cam}", text_y=30)
        return CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=frame.results,
            timestamp=frame.timestamp,
        )

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

    def _loadClassificationPolygons(self) -> None:
        saved = getClassificationPolygons()
        if saved is None:
            return
        res = saved.get("resolution")
        if res and len(res) == 2:
            self._classification_polygon_resolution = (int(res[0]), int(res[1]))
        polygons = saved.get("polygons", {})
        for key in ("top", "bottom"):
            pts = polygons.get(key)
            if pts and len(pts) >= 3:
                self._classification_masks[key] = np.array(pts, dtype=np.int32)

    def _scalePolygon(self, polygon: np.ndarray, frame_w: int, frame_h: int) -> np.ndarray:
        src_w, src_h = self._classification_polygon_resolution
        if src_w == frame_w and src_h == frame_h:
            return polygon
        scale_x = frame_w / src_w
        scale_y = frame_h / src_h
        scaled = polygon.astype(np.float64)
        scaled[:, 0] *= scale_x
        scaled[:, 1] *= scale_y
        return scaled.astype(np.int32)

    def _maskToRegion(self, frame: np.ndarray, key: str) -> np.ndarray:
        polygon = self._classification_masks.get(key)
        if polygon is None:
            return frame
        h, w = frame.shape[:2]
        polygon = self._scalePolygon(polygon, w, h)
        white = np.full_like(frame, 255)
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [polygon], 255)
        result = np.where(mask[:, :, np.newaxis] == 255, frame, white)
        return result

    def _cropToBbox(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        x1 = max(0, min(x1, w))
        y1 = max(0, min(y1, h))
        x2 = max(0, min(x2, w))
        y2 = max(0, min(y2, h))
        return frame[y1:y2, x1:x2]

    def getClassificationCrops(
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)

        top_crop: np.ndarray | None = None
        if top_frame is not None:
            bbox = self.getClassificationCombinedBbox("top")
            if bbox is not None:
                top_crop = self._cropToBbox(top_frame.raw, bbox)
            else:
                top_crop = self._maskToRegion(top_frame.raw, "top")

        bottom_crop: np.ndarray | None = None
        if bottom_frame is not None:
            bbox = self.getClassificationCombinedBbox("bottom")
            if bbox is not None:
                bottom_crop = self._cropToBbox(bottom_frame.raw, bbox)
            else:
                bottom_crop = self._maskToRegion(bottom_frame.raw, "bottom")

        return (top_crop, bottom_crop)

    def _encodeFrame(self, frame: np.ndarray) -> str:
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
        with self._cached_frame_events_lock:
            return list(self._cached_frame_events)

    def _frameEncodeLoop(self) -> None:
        while not self._frame_encode_stop.is_set():
            prof = self.gc.profiler
            prof.hit("vision.frame_encode_thread.calls")
            with prof.timer("vision.frame_encode_thread.total_ms"):
                events: List[FrameEvent] = []
                for camera in CameraName:
                    event = self.getFrameEvent(camera)
                    if event:
                        events.append(event)
                with self._cached_frame_events_lock:
                    self._cached_frame_events = events
            self._frame_encode_stop.wait(FRAME_ENCODE_INTERVAL_MS / 1000.0)
