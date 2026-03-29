from typing import Optional, List, Dict, Tuple, Union
import base64
import time
import threading
import cv2
import numpy as np

from global_config import GlobalConfig, RegionProviderType
from irl.config import IRLConfig, IRLInterface, CameraColorProfile, CameraPictureSettings, mkCameraConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from defs.channel import ChannelDetection, PolygonChannel
from blob_manager import (
    VideoRecorder,
    getCarouselDetectionConfig,
    getClassificationDetectionConfig,
    getClassificationPolygons,
    getFeederDetectionConfig,
)
from .camera import CaptureThread
from .types import CameraFrame, VisionResult, DetectedMask
from .regions import RegionName, Region
from .aruco_region_provider import ArucoRegionProvider
from .default_region_provider import DefaultRegionProvider
from .handdrawn_region_provider import HanddrawnRegionProvider
from .classification_detection import ClassificationDetectionResult
from .gemini_sam_detector import GeminiSamDetector, DEFAULT_OPENROUTER_MODEL, normalize_openrouter_model
from .heatmap_diff import HeatmapDiff
from .mog2_channel_detector import Mog2ChannelDetector
from .feeder_analysis_thread import FeederAnalysisThread
from .classification_analysis_thread import ClassificationAnalysisThread
from .detection_registry import (
    DetectionRequest,
    DetectionScope,
    detection_algorithm_definition,
    scope_supports_detection_algorithm,
)
from .diff_configs import (
    CarouselDiffConfig,
    CarouselDetectionAlgorithm,
    FeederDetectionAlgorithm,
    ClassificationDiffConfig,
    ClassificationDetectionAlgorithm,
    DEFAULT_CAROUSEL_DIFF_CONFIG,
    DEFAULT_CLASSIFICATION_DIFF_CONFIG,
    normalizeCarouselDetectionAlgorithm,
    normalizeFeederDetectionAlgorithm,
    normalizeClassificationDetectionAlgorithm,
)

TELEMETRY_INTERVAL_S = 30
FRAME_ENCODE_INTERVAL_MS = 100
AUXILIARY_DETECTION_LOOP_INTERVAL_S = 1.0
AUXILIARY_SAMPLE_INTERVAL_S = 1.0


class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: CaptureThread
    _classification_bottom_capture: Optional[CaptureThread]
    _classification_top_capture: Optional[CaptureThread]
    _video_recorder: Optional[VideoRecorder]
    _region_provider: Union[ArucoRegionProvider, DefaultRegionProvider, HanddrawnRegionProvider]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig, irl: IRLInterface):
        self.gc = gc
        self._irl_config = irl_config
        self._irl = irl
        self._camera_layout = getattr(irl_config, "camera_layout", "default")
        self._disabled_cameras = set(gc.disable_video_streams)

        # split_feeder: separate cameras per c-channel + carousel
        self._c_channel_2_capture: Optional[CaptureThread] = None
        self._c_channel_3_capture: Optional[CaptureThread] = None
        self._carousel_capture: Optional[CaptureThread] = None

        if self._camera_layout == "split_feeder":
            if irl_config.c_channel_2_camera is not None:
                self._c_channel_2_capture = CaptureThread("c_channel_2", irl_config.c_channel_2_camera)
            if irl_config.c_channel_3_camera is not None:
                self._c_channel_3_capture = CaptureThread("c_channel_3", irl_config.c_channel_3_camera)
            if irl_config.carousel_camera is not None:
                self._carousel_capture = CaptureThread("carousel", irl_config.carousel_camera)
            # In split mode, feeder_capture points to c_channel_2 as a fallback for code that expects it
            self._feeder_capture = self._c_channel_2_capture or CaptureThread("feeder", irl_config.feeder_camera)
            # Classification cameras are optional in split_feeder — enabled when configured via URL or device index
            def _is_real_camera(cfg) -> bool:
                return cfg is not None and (cfg.url is not None or cfg.device_index >= 0)
            self._classification_top_capture = (
                CaptureThread("classification_top", irl_config.classification_camera_top)
                if _is_real_camera(irl_config.classification_camera_top) else None
            )
            self._classification_bottom_capture = (
                CaptureThread("classification_bottom", irl_config.classification_camera_bottom)
                if _is_real_camera(irl_config.classification_camera_bottom) else None
            )
        else:
            self._feeder_camera_config = irl_config.feeder_camera

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
            try:
                self._region_provider = HanddrawnRegionProvider()
            except RuntimeError:
                self._region_provider = DefaultRegionProvider()
        elif gc.region_provider == RegionProviderType.ARUCO:
            self._region_provider = ArucoRegionProvider(gc, self._feeder_capture, irl_config)

        self._feeder_detector: Mog2ChannelDetector | None = None
        self._carousel_heatmap: HeatmapDiff = HeatmapDiff()  # overwritten after configs set

        self._channel_polygons: Dict[str, np.ndarray] = {}
        self._channel_angles: Dict[str, float] = {}
        self._channel_masks: Dict[str, np.ndarray] = {}
        self._carousel_polygon: List[Tuple[float, float]] | None = None

        self._feeder_analysis: FeederAnalysisThread | None = None
        self._cached_feeder_frame: CameraFrame | None = None
        self._cached_feeder_frame_ts: float = 0.0

        # Per-channel detectors/analysis for split_feeder mode
        self._per_channel_detectors: Dict[str, Mog2ChannelDetector] = {}
        self._per_channel_analysis: Dict[str, FeederAnalysisThread] = {}
        self._cached_c_channel_2_frame: CameraFrame | None = None
        self._cached_c_channel_2_frame_ts: float = 0.0
        self._cached_c_channel_3_frame: CameraFrame | None = None
        self._cached_c_channel_3_frame_ts: float = 0.0
        self._cached_carousel_frame: CameraFrame | None = None
        self._cached_carousel_frame_ts: float = 0.0

        self._classification_masks: Dict[str, np.ndarray] = {}
        self._classification_mask_bboxes: Dict[str, Tuple[int, int, int, int]] = {}
        self._classification_polygon_resolution: Tuple[int, int] = (1920, 1080)
        self._loadClassificationPolygons()
        self._carousel_diff_config: CarouselDiffConfig = DEFAULT_CAROUSEL_DIFF_CONFIG
        self._diff_config: ClassificationDiffConfig = DEFAULT_CLASSIFICATION_DIFF_CONFIG
        self._loadClassificationDetectionConfig()
        self._feeder_detection_algorithm: FeederDetectionAlgorithm = "mog2"
        self._feeder_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
        self._feeder_sample_collection_enabled: bool = True
        self._carousel_detection_algorithm: CarouselDetectionAlgorithm = "heatmap_diff"
        self._carousel_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
        self._carousel_sample_collection_enabled: bool = True
        self._loadFeederDetectionConfig()
        self._loadCarouselDetectionConfig()
        self._carousel_heatmap = self._makeCarouselHeatmap()

        self._classification_top_heatmap: HeatmapDiff | None = None
        self._classification_bottom_heatmap: HeatmapDiff | None = None
        self._classification_top_analysis: ClassificationAnalysisThread | None = None
        self._classification_bottom_analysis: ClassificationAnalysisThread | None = None
        self._classification_dynamic_detection_cache: Dict[str, Tuple[float, ClassificationDetectionResult | None]] = {}
        self._feeder_dynamic_detection_cache: Dict[str, Tuple[float, ClassificationDetectionResult | None]] = {}
        self._carousel_dynamic_detection_cache: Tuple[float, ClassificationDetectionResult | None] | None = None
        self._classification_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
        self._gemini_sam_detector: GeminiSamDetector | None = None
        self._feeder_gemini_detectors: Dict[str, GeminiSamDetector] = {}
        self._carousel_gemini_detector: GeminiSamDetector | None = None
        self._aux_detection_stop = threading.Event()
        self._aux_detection_thread: threading.Thread | None = None
        self._auxiliary_last_sample_at: Dict[str, float] = {}

        self._cached_frame_events: List[FrameEvent] = []
        self._cached_frame_events_lock = threading.Lock()
        self._frame_encode_thread: threading.Thread | None = None
        self._frame_encode_stop = threading.Event()
        self._started = False

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def setArucoSmoothingTimeSeconds(self, smoothing_time_s: float) -> None:
        if isinstance(self._region_provider, ArucoRegionProvider):
            self._region_provider.setSmoothingTimeSeconds(smoothing_time_s)

    def start(self) -> None:
        self._started = True
        if self._camera_layout == "split_feeder":
            if self._c_channel_2_capture:
                self._c_channel_2_capture.start()
            if self._c_channel_3_capture:
                self._c_channel_3_capture.start()
            if self._carousel_capture:
                self._carousel_capture.start()
        else:
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
        self._aux_detection_stop.clear()
        self._aux_detection_thread = threading.Thread(
            target=self._auxiliaryDetectionLoop, daemon=True, name="auxiliary-detection-loop"
        )
        self._aux_detection_thread.start()

    def stop(self) -> None:
        self._started = False
        self._frame_encode_stop.set()
        self._aux_detection_stop.set()
        if self._frame_encode_thread:
            self._frame_encode_thread.join(timeout=2.0)
        if self._aux_detection_thread:
            self._aux_detection_thread.join(timeout=2.0)
        if self._feeder_analysis:
            self._feeder_analysis.stop()
        for analysis in self._per_channel_analysis.values():
            analysis.stop()
        self._per_channel_analysis.clear()
        self._stopClassificationAnalysis()
        self._region_provider.stop()
        if self._camera_layout == "split_feeder":
            if self._c_channel_2_capture:
                self._c_channel_2_capture.stop()
            if self._c_channel_3_capture:
                self._c_channel_3_capture.stop()
            if self._carousel_capture:
                self._carousel_capture.stop()
        else:
            self._feeder_capture.stop()
        if self._classification_bottom_capture:
            self._classification_bottom_capture.stop()
        if self._classification_top_capture:
            self._classification_top_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def _loadClassificationDetectionConfig(self) -> None:
        config = getClassificationDetectionConfig()
        candidate = config.get("algorithm") if isinstance(config, dict) else None
        self._diff_config.algorithm = normalizeClassificationDetectionAlgorithm(candidate)
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._classification_openrouter_model = normalize_openrouter_model(model)

    def _loadFeederDetectionConfig(self) -> None:
        config = getFeederDetectionConfig()
        candidate = config.get("algorithm") if isinstance(config, dict) else None
        self._feeder_detection_algorithm = normalizeFeederDetectionAlgorithm(candidate)
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._feeder_openrouter_model = normalize_openrouter_model(model)
        enabled = config.get("sample_collection_enabled") if isinstance(config, dict) else None
        self._feeder_sample_collection_enabled = True if enabled is None else bool(enabled)

    def _loadCarouselDetectionConfig(self) -> None:
        config = getCarouselDetectionConfig()
        candidate = config.get("algorithm") if isinstance(config, dict) else None
        self._carousel_detection_algorithm = normalizeCarouselDetectionAlgorithm(candidate)
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._carousel_openrouter_model = normalize_openrouter_model(model)
        enabled = config.get("sample_collection_enabled") if isinstance(config, dict) else None
        self._carousel_sample_collection_enabled = True if enabled is None else bool(enabled)

    def _stopClassificationAnalysis(self) -> None:
        if self._classification_top_analysis:
            self._classification_top_analysis.stop()
            self._classification_top_analysis = None
        if self._classification_bottom_analysis:
            self._classification_bottom_analysis.stop()
            self._classification_bottom_analysis = None
        self._classification_top_heatmap = None
        self._classification_bottom_heatmap = None

    def getClassificationDetectionAlgorithm(self) -> ClassificationDetectionAlgorithm:
        return normalizeClassificationDetectionAlgorithm(self._diff_config.algorithm)

    def getClassificationOpenRouterModel(self) -> str:
        return normalize_openrouter_model(self._classification_openrouter_model)

    def _detectionAlgorithmForScope(self, scope: DetectionScope) -> str:
        if scope == "classification":
            return self.getClassificationDetectionAlgorithm()
        if scope == "feeder":
            return self.getFeederDetectionAlgorithm()
        return self.getCarouselDetectionAlgorithm()

    def _openRouterModelForScope(self, scope: DetectionScope) -> str:
        if scope == "classification":
            return self.getClassificationOpenRouterModel()
        if scope == "feeder":
            return self.getFeederOpenRouterModel()
        return self.getCarouselOpenRouterModel()

    def usesDetectionBaseline(self, scope: DetectionScope) -> bool:
        definition = detection_algorithm_definition(self._detectionAlgorithmForScope(scope))
        return bool(definition is not None and definition.needs_baseline)

    def usesClassificationBaseline(self) -> bool:
        return self.usesDetectionBaseline("classification")

    def getFeederDetectionAlgorithm(self) -> FeederDetectionAlgorithm:
        return normalizeFeederDetectionAlgorithm(self._feeder_detection_algorithm)

    def getFeederOpenRouterModel(self) -> str:
        return normalize_openrouter_model(self._feeder_openrouter_model)

    def isFeederSampleCollectionEnabled(self) -> bool:
        return bool(self._feeder_sample_collection_enabled)

    def getCarouselDetectionAlgorithm(self) -> CarouselDetectionAlgorithm:
        return normalizeCarouselDetectionAlgorithm(self._carousel_detection_algorithm)

    def getCarouselOpenRouterModel(self) -> str:
        return normalize_openrouter_model(self._carousel_openrouter_model)

    def isCarouselSampleCollectionEnabled(self) -> bool:
        return bool(self._carousel_sample_collection_enabled)

    def usesCarouselBaseline(self) -> bool:
        return self.usesDetectionBaseline("carousel")

    def setClassificationDetectionAlgorithm(self, algorithm: ClassificationDetectionAlgorithm) -> bool:
        if not scope_supports_detection_algorithm("classification", algorithm):
            raise ValueError(f"Unsupported classification detection algorithm '{algorithm}'")
        normalized = normalizeClassificationDetectionAlgorithm(algorithm)
        self._diff_config.algorithm = normalized
        self._classification_dynamic_detection_cache.clear()
        self._stopClassificationAnalysis()
        if normalized == "baseline_diff" and self._started:
            return self.loadClassificationBaseline()
        return False

    def setClassificationOpenRouterModel(self, model: str) -> str:
        normalized = normalize_openrouter_model(model)
        self._classification_openrouter_model = normalized
        self._classification_dynamic_detection_cache.clear()
        if self._gemini_sam_detector is not None:
            self._gemini_sam_detector.setOpenRouterModel(normalized)
        return normalized

    def setFeederDetectionAlgorithm(self, algorithm: FeederDetectionAlgorithm) -> None:
        if not scope_supports_detection_algorithm("feeder", algorithm):
            raise ValueError(f"Unsupported feeder detection algorithm '{algorithm}'")
        self._feeder_detection_algorithm = normalizeFeederDetectionAlgorithm(algorithm)
        self._feeder_dynamic_detection_cache.clear()

    def setFeederOpenRouterModel(self, model: str) -> str:
        normalized = normalize_openrouter_model(model)
        self._feeder_openrouter_model = normalized
        self._feeder_dynamic_detection_cache.clear()
        for detector in self._feeder_gemini_detectors.values():
            detector.setOpenRouterModel(normalized)
        return normalized

    def setFeederSampleCollectionEnabled(self, enabled: bool) -> bool:
        self._feeder_sample_collection_enabled = bool(enabled)
        return self._feeder_sample_collection_enabled

    def setCarouselDetectionAlgorithm(self, algorithm: CarouselDetectionAlgorithm) -> None:
        if not scope_supports_detection_algorithm("carousel", algorithm):
            raise ValueError(f"Unsupported carousel detection algorithm '{algorithm}'")
        self._carousel_detection_algorithm = normalizeCarouselDetectionAlgorithm(algorithm)
        self._carousel_dynamic_detection_cache = None

    def setCarouselOpenRouterModel(self, model: str) -> str:
        normalized = normalize_openrouter_model(model)
        self._carousel_openrouter_model = normalized
        self._carousel_dynamic_detection_cache = None
        if self._carousel_gemini_detector is not None:
            self._carousel_gemini_detector.setOpenRouterModel(normalized)
        return normalized

    def setCarouselSampleCollectionEnabled(self, enabled: bool) -> bool:
        self._carousel_sample_collection_enabled = bool(enabled)
        return self._carousel_sample_collection_enabled

    def initFeederDetection(self) -> bool:
        from blob_manager import getChannelPolygons
        from subsystems.feeder.analysis import parseSavedChannelArcZones, zoneSectionsForChannel

        saved = getChannelPolygons()
        if saved is None:
            self.gc.logger.warn("Channel polygons not found. Run: scripts/polygon_editor.py")
            return False

        polygon_data = saved.get("polygons", {})
        raw_arc_params = saved.get("arc_params", {})
        polys: Dict[str, np.ndarray] = {}
        inner_polys: Dict[str, np.ndarray] = {}
        for key in ("second_channel", "third_channel"):
            pts = polygon_data.get(key)
            channel_key = "second" if key == "second_channel" else "third"
            arc = parseSavedChannelArcZones(channel_key, saved.get("channel_angles", {}), raw_arc_params)
            if arc is not None and arc.outer_radius > arc.inner_radius > 0:
                segment_count = 96
                outer_pts = np.array([
                    [
                        int(round(arc.center[0] + arc.outer_radius * np.cos((2 * np.pi * i) / segment_count))),
                        int(round(arc.center[1] + arc.outer_radius * np.sin((2 * np.pi * i) / segment_count))),
                    ]
                    for i in range(segment_count)
                ], dtype=np.int32)
                inner_pts = np.array([
                    [
                        int(round(arc.center[0] + arc.inner_radius * np.cos((2 * np.pi * i) / segment_count))),
                        int(round(arc.center[1] + arc.inner_radius * np.sin((2 * np.pi * i) / segment_count))),
                    ]
                    for i in range(segment_count)
                ], dtype=np.int32)
                polys[key] = outer_pts
                inner_polys[key] = inner_pts
            elif pts:
                polys[key] = np.array(pts, dtype=np.int32)

        if not polys:
            self.gc.logger.warn("Channel polygons empty. Run: scripts/polygon_editor.py")
            return False

        self._channel_polygons = polys
        self._channel_angles = saved.get("channel_angles", {})

        saved_res = saved.get("resolution", [1920, 1080])
        src_w, src_h = int(saved_res[0]), int(saved_res[1])

        carousel_pts = polygon_data.get("carousel")
        if carousel_pts and len(carousel_pts) >= 3:
            if self._camera_layout == "split_feeder" and self._carousel_capture is not None:
                # Scale carousel polygon from editor resolution to camera resolution
                frame = self._carousel_capture.latest_frame
                if frame is None:
                    for _ in range(20):
                        time.sleep(0.1)
                        frame = self._carousel_capture.latest_frame
                        if frame is not None:
                            break
                if frame is not None:
                    cam_h, cam_w = frame.raw.shape[:2]
                    sx, sy = cam_w / src_w, cam_h / src_h
                    self._carousel_polygon = [(float(p[0]) * sx, float(p[1]) * sy) for p in carousel_pts]
                else:
                    self._carousel_polygon = [(float(p[0]), float(p[1])) for p in carousel_pts]
            else:
                self._carousel_polygon = [(float(p[0]), float(p[1])) for p in carousel_pts]

        channel_steppers = {
            "second_channel": self._irl.c_channel_2_rotor_stepper,
            "third_channel": self._irl.c_channel_3_rotor_stepper,
        }

        def is_channel_rotating(name: str) -> bool:
            stepper = channel_steppers.get(name)
            if stepper is None:
                return False
            return not stepper.stopped

        if self._camera_layout == "split_feeder":
            return self._initSplitFeederDetection(
                polys, inner_polys, raw_arc_params, channel_steppers, is_channel_rotating,
            )

        gray = self.getLatestFeederGray()
        mask_shape = gray.shape[:2] if gray is not None else (1080, 1920)

        channel_masks: Dict[str, np.ndarray] = {}
        channel_zone_sections: Dict[str, Dict[str, set[int]]] = {}
        for key, pts in polys.items():
            ch_mask = np.zeros(mask_shape, dtype=np.uint8)
            cv2.fillPoly(ch_mask, [pts], 255)
            if key in inner_polys:
                cv2.fillPoly(ch_mask, [inner_polys[key]], 0)
            channel_masks[key] = ch_mask
            channel_key = "second" if key == "second_channel" else "third"
            arc = parseSavedChannelArcZones(channel_key, self._channel_angles, raw_arc_params)
            drop_sections, exit_sections = zoneSectionsForChannel(
                2 if channel_key == "second" else 3,
                float(self._channel_angles.get(channel_key, 0.0)),
                arc,
            )
            channel_zone_sections[channel_key] = {
                "drop": drop_sections,
                "exit": exit_sections,
            }
        self._channel_masks = channel_masks

        self._feeder_detector = Mog2ChannelDetector(
            channel_polygons=polys,
            channel_masks=channel_masks,
            channel_angles=self._channel_angles,
            channel_inner_polygons=inner_polys,
            channel_zone_sections=channel_zone_sections,
            is_channel_rotating=is_channel_rotating,
        )

        self._feeder_analysis = FeederAnalysisThread(
            detector=self._feeder_detector,
            get_gray=self.getLatestFeederGray,
            profiler=self.gc.profiler,
        )
        self._feeder_analysis.start()
        self.gc.logger.info("Feeder MOG2 detection initialized")
        return True

    def _initSplitFeederDetection(
        self,
        polys: Dict[str, np.ndarray],
        inner_polys: Dict[str, np.ndarray],
        raw_arc_params: dict,
        channel_steppers: dict,
        is_channel_rotating,
    ) -> bool:
        from blob_manager import getChannelPolygons
        from subsystems.feeder.analysis import parseSavedChannelArcZones, zoneSectionsForChannel

        saved = getChannelPolygons()
        saved_res = saved.get("resolution", [1920, 1080]) if saved else [1920, 1080]
        src_w, src_h = int(saved_res[0]), int(saved_res[1])

        channel_map = {
            "second_channel": ("c_channel_2", self._c_channel_2_capture),
            "third_channel": ("c_channel_3", self._c_channel_3_capture),
        }

        for key, (role, capture) in channel_map.items():
            if key not in polys or capture is None:
                continue

            # Wait briefly for first frame to get actual camera resolution
            frame = capture.latest_frame
            if frame is None:
                for _ in range(20):
                    time.sleep(0.1)
                    frame = capture.latest_frame
                    if frame is not None:
                        break

            if frame is not None:
                cam_h, cam_w = frame.raw.shape[:2]
            else:
                cam_h, cam_w = src_h, src_w
                self.gc.logger.warning(f"No frame from {role} yet, using saved resolution {src_w}x{src_h}")

            # Scale polygon coordinates from editor resolution to camera resolution
            scale_x = cam_w / src_w
            scale_y = cam_h / src_h

            def _scale_poly(pts: np.ndarray) -> np.ndarray:
                scaled = pts.astype(np.float64).copy()
                scaled[:, 0] *= scale_x
                scaled[:, 1] *= scale_y
                return scaled.astype(np.int32)

            scaled_poly = _scale_poly(polys[key])
            scaled_inner = _scale_poly(inner_polys[key]) if key in inner_polys else None

            ch_mask = np.zeros((cam_h, cam_w), dtype=np.uint8)
            cv2.fillPoly(ch_mask, [scaled_poly], 255)
            if scaled_inner is not None:
                cv2.fillPoly(ch_mask, [scaled_inner], 0)

            channel_key = "second" if key == "second_channel" else "third"

            # Scale arc params for zone section computation
            scaled_arc_params = dict(raw_arc_params)
            raw_arc = raw_arc_params.get(channel_key)
            if raw_arc and (scale_x != 1.0 or scale_y != 1.0):
                scaled_arc = dict(raw_arc)
                c = raw_arc.get("center", [0, 0])
                scaled_arc["center"] = [c[0] * scale_x, c[1] * scale_y]
                # Scale radii by average of scale factors (approximation for uniform scaling)
                r_scale = (scale_x + scale_y) / 2.0
                if "inner_radius" in scaled_arc:
                    scaled_arc["inner_radius"] = scaled_arc["inner_radius"] * r_scale
                if "outer_radius" in scaled_arc:
                    scaled_arc["outer_radius"] = scaled_arc["outer_radius"] * r_scale
                scaled_arc_params = dict(raw_arc_params)
                scaled_arc_params[channel_key] = scaled_arc

            # Scale channel angles (angles don't need scaling, but center offset does)
            scaled_channel_angles = dict(self._channel_angles)

            arc = parseSavedChannelArcZones(channel_key, scaled_channel_angles, scaled_arc_params)
            drop_sections, exit_sections = zoneSectionsForChannel(
                2 if channel_key == "second" else 3,
                float(scaled_channel_angles.get(channel_key, 0.0)),
                arc,
            )

            single_polys = {key: scaled_poly}
            single_masks = {key: ch_mask}
            single_inner = {key: scaled_inner} if scaled_inner is not None else {}
            single_zone_sections = {channel_key: {"drop": drop_sections, "exit": exit_sections}}

            def _make_rotating_check(name: str):
                return lambda n: is_channel_rotating(name)

            detector = Mog2ChannelDetector(
                channel_polygons=single_polys,
                channel_masks=single_masks,
                channel_angles=scaled_channel_angles,
                channel_inner_polygons=single_inner,
                channel_zone_sections=single_zone_sections,
                is_channel_rotating=_make_rotating_check(key),
            )
            self._per_channel_detectors[role] = detector

            def _make_gray_getter(cap: CaptureThread):
                def _get_gray() -> np.ndarray | None:
                    f = cap.latest_frame
                    if f is None:
                        return None
                    return cv2.cvtColor(f.raw, cv2.COLOR_BGR2GRAY)
                return _get_gray

            analysis = FeederAnalysisThread(
                detector=detector,
                get_gray=_make_gray_getter(capture),
                profiler=self.gc.profiler,
            )
            analysis.start()
            self._per_channel_analysis[role] = analysis
            self.gc.logger.info(f"Split-feeder MOG2 detection initialized for {role} ({cam_w}x{cam_h}, scale={scale_x:.2f}x{scale_y:.2f})")

        return bool(self._per_channel_detectors)

    def _makeCarouselHeatmap(self) -> HeatmapDiff:
        c = self._carousel_diff_config
        return HeatmapDiff(
            pixel_thresh=c.pixel_thresh,
            blur_kernel=c.blur_kernel,
            min_hot_pixels=c.min_hot_pixels,
            trigger_score=c.trigger_score,
            min_contour_area=c.min_contour_area,
            min_hot_thickness_px=c.min_hot_thickness_px,
            max_contour_aspect=c.max_contour_aspect,
            heat_gain=c.heat_gain,
            current_frames=c.current_frames,
        )

    def _makeClassificationHeatmap(self) -> HeatmapDiff:
        c = self._diff_config
        return HeatmapDiff(
            scale=0.25,
            gc=self.gc,
            pixel_thresh=c.pixel_thresh,
            blur_kernel=c.blur_kernel,
            min_hot_pixels=c.min_hot_pixels,
            trigger_score=c.trigger_score,
            min_contour_area=c.min_contour_area,
            min_hot_thickness_px=c.min_hot_thickness_px,
            max_contour_aspect=c.max_contour_aspect,
            heat_gain=c.heat_gain,
            current_frames=c.current_frames,
        )

    def loadClassificationBaseline(self) -> bool:
        from blob_manager import BLOB_DIR
        import glob as globmod

        cfg = self._diff_config

        self._stopClassificationAnalysis()

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

            calibration_frames: List[np.ndarray] = []
            for p in sorted(globmod.glob(str(baseline_dir / f"{cam_key}_frame_*.png"))):
                gray = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
                if gray is not None:
                    calibration_frames.append(gray)

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
                    calibration_frames = [cv2.resize(f, (cam_w, cam_h), interpolation=cv2.INTER_AREA) for f in calibration_frames]

            if len(calibration_frames) >= 2 and cfg.adaptive_std_k > 0:
                stddev = np.std(np.stack(calibration_frames, axis=0).astype(np.float32), axis=0)
                adaptive_margin = np.clip(stddev * cfg.adaptive_std_k, 0, 100).astype(np.uint8)
                baseline_min = np.clip(baseline_min.astype(np.int16) - adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)
                baseline_max = np.clip(baseline_max.astype(np.int16) + adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)

            if cfg.envelope_margin > 0:
                baseline_min = np.clip(baseline_min.astype(np.int16) - cfg.envelope_margin, 0, 255).astype(np.uint8)
                baseline_max = np.clip(baseline_max.astype(np.int16) + cfg.envelope_margin, 0, 255).astype(np.uint8)

            polygon = self._classification_masks.get(cam_key)
            if polygon is not None:
                scaled = self._scalePolygon(polygon, baseline_min.shape[1], baseline_min.shape[0])
                mask = np.zeros(baseline_min.shape[:2], dtype=np.uint8)
                cv2.fillPoly(mask, [scaled], 255)
            else:
                mask = np.ones(baseline_min.shape[:2], dtype=np.uint8) * 255
            mx, my, mw, mh = cv2.boundingRect(mask)
            self._classification_mask_bboxes[cam_key] = (mx, my, mx + mw, my + mh)

            heatmap = self._makeClassificationHeatmap()
            heatmap.loadEnvelope(baseline_min, baseline_max, mask)

            if cam_key == "top":
                self._classification_top_heatmap = heatmap
                self._classification_top_analysis = ClassificationAnalysisThread(
                    name="top",
                    heatmap=heatmap,
                    get_gray=self._getLatestClassificationTopGray,
                    profiler=self.gc.profiler,
                    logger=self.gc.logger,
                    min_bbox_dimension_px=cfg.min_bbox_dim,
                    min_bbox_area_px=cfg.min_bbox_area,
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
                    min_bbox_dimension_px=cfg.min_bbox_dim,
                    min_bbox_area_px=cfg.min_bbox_area,
                )
                self._classification_bottom_analysis.start()

            self.gc.logger.info(f"Classification {cam_key} baseline loaded (margin={cfg.envelope_margin}, adaptive_k={cfg.adaptive_std_k}, {len(calibration_frames)} cal frames)")
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
        if self.usesClassificationBaseline():
            if cam == "top" and self._classification_top_analysis:
                return self._classification_top_analysis.getBboxes()
            if cam == "bottom" and self._classification_bottom_analysis:
                return self._classification_bottom_analysis.getBboxes()
            return []

        detection = self._getDynamicClassificationDetection(cam)
        if detection is None:
            return []
        return list(detection.bboxes)

    def _getDynamicClassificationDetectionForFrame(
        self,
        cam: str,
        frame: CameraFrame,
        *,
        force: bool = False,
    ) -> ClassificationDetectionResult | None:
        cached = self._classification_dynamic_detection_cache.get(cam)
        if cached is not None and cached[0] == frame.timestamp:
            return cached[1]

        algorithm = self.getClassificationDetectionAlgorithm()

        # gemini_sam is a cloud API — only call when explicitly requested
        if algorithm == "gemini_sam" and not force:
            if cached is None:
                return None
            return cached[1] if abs(float(frame.timestamp) - float(cached[0])) <= 4.0 else None

        detection: ClassificationDetectionResult | None = None
        if algorithm == "gemini_sam":
            polygon = self._classification_masks.get(cam)
            scaled_polygon = None
            if polygon is not None and len(polygon) >= 3:
                h, w = frame.raw.shape[:2]
                scaled_polygon = self._scalePolygon(polygon, w, h)
            detection = self._runGeminiDetectionRequest(
                DetectionRequest(
                    scope="classification",
                    role=cam,
                    frame=frame.raw,
                    zone_polygon=scaled_polygon,
                    force=True,
                )
            )

        self._classification_dynamic_detection_cache[cam] = (frame.timestamp, detection)
        return detection

    def _getDynamicClassificationDetection(
        self, cam: str, *, force: bool = False,
    ) -> ClassificationDetectionResult | None:
        capture = self._classification_top_capture if cam == "top" else self._classification_bottom_capture
        if capture is None:
            return None
        frame = capture.latest_frame
        if frame is None:
            return None
        return self._getDynamicClassificationDetectionForFrame(cam, frame, force=force)

    def _classificationAnnotationLabel(self, cam: str) -> str:
        if self.usesClassificationBaseline():
            return f"class_{cam}"
        return f"class_{cam}:{self._diff_config.algorithm}"

    def getClassificationCombinedBbox(
        self,
        cam: str,
        *,
        force: bool = False,
        frame: CameraFrame | None = None,
    ) -> Tuple[int, int, int, int] | None:
        if self.usesClassificationBaseline():
            if cam == "top" and self._classification_top_analysis:
                return self._classification_top_analysis.getCombinedBbox()
            if cam == "bottom" and self._classification_bottom_analysis:
                return self._classification_bottom_analysis.getCombinedBbox()
            return None
        detection = (
            self._getDynamicClassificationDetectionForFrame(cam, frame, force=force)
            if frame is not None
            else self._getDynamicClassificationDetection(cam, force=force)
        )
        return detection.bbox if detection is not None else None

    def debugClassificationDetection(self, cam: str, *, include_capture: bool = False) -> Dict[str, object]:
        if cam not in {"top", "bottom"}:
            raise ValueError(f"Unsupported classification camera '{cam}'")

        capture = self._classification_top_capture if cam == "top" else self._classification_bottom_capture
        top_frame = self._classification_top_capture.latest_frame if self._classification_top_capture else None
        bottom_frame = self._classification_bottom_capture.latest_frame if self._classification_bottom_capture else None
        sample_capture = self._classificationSampleFromFrames(top_frame, bottom_frame) if include_capture else None

        def _finalize(payload: Dict[str, object]) -> Dict[str, object]:
            if include_capture:
                payload["_sample_capture"] = sample_capture
            return payload

        if capture is None:
            return _finalize({
                "camera": cam,
                "algorithm": self.getClassificationDetectionAlgorithm(),
                "found": False,
                "message": "No classification camera is configured for this view.",
            })

        frame = top_frame if cam == "top" else bottom_frame
        if frame is None:
            return _finalize({
                "camera": cam,
                "algorithm": self.getClassificationDetectionAlgorithm(),
                "found": False,
                "message": "No live frame is available yet.",
            })

        frame_h, frame_w = frame.raw.shape[:2]
        polygon = self._classification_masks.get(cam)
        scaled_polygon = self._scalePolygon(polygon, frame_w, frame_h) if polygon is not None else None

        zone_bbox: Tuple[int, int, int, int] | None = None
        zone_point_count = 0
        if scaled_polygon is not None and len(scaled_polygon) >= 3:
            x, y, w, h = cv2.boundingRect(scaled_polygon)
            zone_bbox = (int(x), int(y), int(x + w), int(y + h))
            zone_point_count = int(len(scaled_polygon))

        algorithm = self.getClassificationDetectionAlgorithm()
        result: Dict[str, object] = {
            "camera": cam,
            "algorithm": algorithm,
            "frame_resolution": [int(frame_w), int(frame_h)],
            "zone_bbox": list(zone_bbox) if zone_bbox is not None else None,
            "zone_point_count": zone_point_count,
        }

        if scaled_polygon is None:
            result.update(
                {
                    "found": False,
                    "message": "No classification zone is saved for this view.",
                }
            )
            return _finalize(result)

        if algorithm != "baseline_diff":
            detection = self._getDynamicClassificationDetection(cam, force=True)
            if detection is None:
                error_detail = ""
                if algorithm == "gemini_sam" and self._gemini_sam_detector is not None:
                    error_detail = self._gemini_sam_detector._last_error or ""
                message = f"{algorithm.replace('_', ' ')} did not find a piece in the current frame."
                if error_detail:
                    message = f"API error: {error_detail}"
                result.update({"found": False, "message": message})
                return _finalize(result)

            result.update(
                {
                    "found": True,
                    "bbox": list(detection.bbox) if detection.bbox is not None else None,
                    "candidate_bboxes": [list(candidate) for candidate in detection.bboxes],
                    "candidate_previews": [
                        self._encodeDebugCrop(frame.raw, candidate) for candidate in detection.bboxes
                    ],
                    "bbox_count": len(detection.bboxes),
                    "score": float(detection.score),
                    "message": f"{algorithm.replace('_', ' ')} found candidate pieces.",
                }
            )
            return _finalize(result)

        heatmap = self._classification_top_heatmap if cam == "top" else self._classification_bottom_heatmap
        analysis = self._classification_top_analysis if cam == "top" else self._classification_bottom_analysis
        if heatmap is None or analysis is None or not heatmap.has_baseline:
            result.update(
                {
                    "found": False,
                    "message": "Baseline diff is selected, but no live baseline is loaded yet.",
                }
            )
            return _finalize(result)

        bbox = analysis.getCombinedBbox()
        bboxes = analysis.getBboxes()
        result.update(
            {
                "bbox_count": len(bboxes),
                "bbox": list(bbox) if bbox is not None else None,
                "candidate_bboxes": [list(candidate) for candidate in bboxes],
                "candidate_previews": [
                    self._encodeDebugCrop(frame.raw, candidate) for candidate in bboxes
                ],
                "found": bbox is not None,
                "message": (
                    "Baseline diff found a candidate piece."
                    if bbox is not None
                    else "Baseline diff did not find a piece in the current frame."
                ),
            }
        )
        return _finalize(result)

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

    def _cropFrameToPolygonRegion(
        self,
        frame: np.ndarray,
        polygon: np.ndarray,
    ) -> tuple[np.ndarray, tuple[int, int]] | None:
        if polygon is None or len(polygon) < 3:
            return None
        h, w = frame.shape[:2]
        x, y, bw, bh = cv2.boundingRect(polygon.astype(np.int32))
        x2 = min(w, x + bw)
        y2 = min(h, y + bh)
        if x2 <= x or y2 <= y:
            return None
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
        masked = np.where(mask[:, :, np.newaxis] == 255, frame, 255)
        return masked[y:y2, x:x2].copy(), (int(x), int(y))

    def _channelInfoForRole(self, role: str) -> PolygonChannel | None:
        detector = self._per_channel_detectors.get(role)
        if detector is None:
            return None
        return detector.primaryChannel()

    def _feederRegionCrop(
        self,
        role: str,
        frame: np.ndarray,
    ) -> tuple[np.ndarray, tuple[int, int]]:
        channel = self._channelInfoForRole(role)
        if channel is None:
            return frame.copy(), (0, 0)
        cropped = self._cropFrameToPolygonRegion(frame, channel.polygon)
        return cropped if cropped is not None else (frame.copy(), (0, 0))

    def _carouselRegionCrop(self, frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
        if self._carousel_polygon is None or len(self._carousel_polygon) < 3:
            return frame.copy(), (0, 0)
        polygon = np.array(self._carousel_polygon, dtype=np.int32)
        cropped = self._cropFrameToPolygonRegion(frame, polygon)
        return cropped if cropped is not None else (frame.copy(), (0, 0))

    def _offsetDetectionResult(
        self,
        detection: ClassificationDetectionResult | None,
        offset_x: int,
        offset_y: int,
    ) -> ClassificationDetectionResult | None:
        if detection is None:
            return None

        def _offset(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            return (bbox[0] + offset_x, bbox[1] + offset_y, bbox[2] + offset_x, bbox[3] + offset_y)

        return ClassificationDetectionResult(
            bbox=_offset(detection.bbox) if detection.bbox is not None else None,
            bboxes=tuple(_offset(candidate) for candidate in detection.bboxes),
            score=detection.score,
            algorithm=detection.algorithm,
        )

    def _geminiDetectorForRequest(self, request: DetectionRequest) -> GeminiSamDetector:
        model = self._openRouterModelForScope(request.scope)
        if request.scope == "classification":
            if self._gemini_sam_detector is None:
                self._gemini_sam_detector = GeminiSamDetector(model)
            else:
                self._gemini_sam_detector.setOpenRouterModel(model)
            return self._gemini_sam_detector

        if request.scope == "feeder":
            detector = self._feeder_gemini_detectors.get(request.role)
            if detector is None:
                detector = GeminiSamDetector(model)
                self._feeder_gemini_detectors[request.role] = detector
            else:
                detector.setOpenRouterModel(model)
            return detector

        if self._carousel_gemini_detector is None:
            self._carousel_gemini_detector = GeminiSamDetector(model)
        else:
            self._carousel_gemini_detector.setOpenRouterModel(model)
        return self._carousel_gemini_detector

    def _runGeminiDetectionRequest(
        self,
        request: DetectionRequest,
    ) -> ClassificationDetectionResult | None:
        if request.frame is None:
            return None

        detector = self._geminiDetectorForRequest(request)
        crop = request.frame
        offset_x = 0
        offset_y = 0
        if request.zone_polygon is not None and len(request.zone_polygon) >= 3:
            cropped = self._cropFrameToPolygonRegion(request.frame, request.zone_polygon)
            if cropped is not None:
                crop, (offset_x, offset_y) = cropped
        detection = detector.detect(crop, force=request.force)
        if offset_x == 0 and offset_y == 0:
            return detection
        return self._offsetDetectionResult(detection, offset_x, offset_y)

    def _computeFeederGeminiDetection(
        self,
        role: str,
        frame: CameraFrame,
        *,
        force_call: bool,
    ) -> ClassificationDetectionResult | None:
        channel = self._channelInfoForRole(role)
        return self._runGeminiDetectionRequest(
            DetectionRequest(
                scope="feeder",
                role=role,
                frame=frame.raw,
                zone_polygon=channel.polygon if channel is not None else None,
                force=force_call,
            )
        )

    def _getCachedFeederDynamicDetection(self, role: str, frame_timestamp: float) -> ClassificationDetectionResult | None:
        cached = self._feeder_dynamic_detection_cache.get(role)
        if cached is None:
            return None
        if cached[0] == frame_timestamp:
            return cached[1]
        return cached[1] if abs(float(frame_timestamp) - float(cached[0])) <= 6.0 else None

    def _getFeederDynamicDetection(
        self,
        role: str,
        *,
        force: bool = False,
    ) -> ClassificationDetectionResult | None:
        capture = self.getCaptureThreadForRole(role)
        if capture is None:
            return None
        frame = capture.latest_frame
        if frame is None:
            return None
        cached = self._getCachedFeederDynamicDetection(role, frame.timestamp)
        if not force:
            return cached
        detection = self._computeFeederGeminiDetection(role, frame, force_call=True)
        self._feeder_dynamic_detection_cache[role] = (frame.timestamp, detection)
        return detection

    def _channelDetectionsFromDynamicResult(
        self,
        role: str,
        detection: ClassificationDetectionResult | None,
    ) -> list[ChannelDetection]:
        channel = self._channelInfoForRole(role)
        if channel is None or detection is None:
            return []
        return [
            ChannelDetection(
                bbox=tuple(int(value) for value in bbox),
                channel_id=channel.channel_id,
                channel=channel,
            )
            for bbox in detection.bboxes
        ]

    def _computeCarouselGeminiDetection(
        self,
        frame: CameraFrame,
        *,
        force_call: bool,
    ) -> ClassificationDetectionResult | None:
        polygon = (
            np.array(self._carousel_polygon, dtype=np.int32)
            if self._carousel_polygon is not None and len(self._carousel_polygon) >= 3
            else None
        )
        return self._runGeminiDetectionRequest(
            DetectionRequest(
                scope="carousel",
                role="carousel",
                frame=frame.raw,
                zone_polygon=polygon,
                force=force_call,
            )
        )

    def _getCarouselDynamicDetection(self, *, force: bool = False) -> ClassificationDetectionResult | None:
        capture = self._carousel_capture
        if capture is None:
            return None
        frame = capture.latest_frame
        if frame is None:
            return None
        cached = self._carousel_dynamic_detection_cache
        if cached is not None:
            if cached[0] == frame.timestamp:
                return cached[1]
            if not force and abs(float(frame.timestamp) - float(cached[0])) <= 6.0:
                return cached[1]
        if not force:
            return None
        detection = self._computeCarouselGeminiDetection(frame, force_call=True)
        self._carousel_dynamic_detection_cache = (frame.timestamp, detection)
        return detection

    def _captureAuxiliarySample(self, role: str) -> dict[str, np.ndarray | None]:
        capture = self.getCaptureThreadForRole(role)
        frame = capture.latest_frame if capture is not None else None
        if frame is None:
            return {"input_image": None, "frame": None}
        if role in {"c_channel_2", "c_channel_3"}:
            crop, _ = self._feederRegionCrop(role, frame.raw)
        elif role == "carousel":
            crop, _ = self._carouselRegionCrop(frame.raw)
        else:
            crop = frame.raw.copy()
        return {
            "input_image": crop,
            "frame": frame.raw.copy(),
        }

    def _sampleRoleScope(self, role: str) -> str:
        if role in {"c_channel_2", "c_channel_3"}:
            return "feeder"
        if role == "carousel":
            return "carousel"
        return "classification"

    def getFeederHeatmapDetections(self) -> list[ChannelDetection]:
        if self.getFeederDetectionAlgorithm() == "gemini_sam":
            if self._camera_layout != "split_feeder":
                return []
            detections: list[ChannelDetection] = []
            for role in ("c_channel_2", "c_channel_3"):
                detections.extend(
                    self._channelDetectionsFromDynamicResult(role, self._getFeederDynamicDetection(role, force=False))
                )
            return detections
        if self._per_channel_analysis:
            detections: list[ChannelDetection] = []
            for analysis in self._per_channel_analysis.values():
                detections.extend(analysis.getDetections())
            return detections
        if self._feeder_analysis is None:
            return []
        return self._feeder_analysis.getDetections()

    def captureCarouselBaseline(self) -> bool:
        if not self.usesCarouselBaseline():
            return True
        if self._carousel_polygon is None:
            return False
        if self._camera_layout == "split_feeder" and self._carousel_capture is not None:
            frame = self._carousel_capture.latest_frame
            if frame is None:
                return False
            gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
        else:
            gray = self.getLatestFeederGray()
            if gray is None:
                return False
        return self._carousel_heatmap.captureBaseline(self._carousel_polygon, gray.shape)

    def clearCarouselBaseline(self) -> None:
        if not self.usesCarouselBaseline():
            return
        self._carousel_heatmap.clearBaseline()

    def isCarouselTriggered(self) -> Tuple[bool, float, int]:
        if self.getCarouselDetectionAlgorithm() == "gemini_sam":
            detection = self._getCarouselDynamicDetection(force=False)
            bbox_count = len(detection.bboxes) if detection is not None else 0
            score = float(detection.score) if detection is not None else 0.0
            return bool(detection is not None and detection.bbox is not None), score, bbox_count
        score, hot_px = self._carousel_heatmap.computeDiff()
        from vision.heatmap_diff import TRIGGER_SCORE
        return score >= TRIGGER_SCORE, score, hot_px

    def recordFrames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
            if self._camera_layout == "split_feeder":
                # In split_feeder mode, push carousel camera frames for heatmap
                if self._carousel_capture:
                    frame = self._carousel_capture.latest_frame
                    if frame is not None:
                        gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
                        self._carousel_heatmap.pushFrame(gray)
            else:
                gray = self.getLatestFeederGray()
                if gray is not None:
                    self._carousel_heatmap.pushFrame(gray)

            if self._video_recorder:
                with prof.timer("vision.record_frames.video_recorder_write_ms"):
                    for cam in self._active_cameras:
                        frame = self.getFrame(cam.value)
                        if frame:
                            self._video_recorder.writeFrame(
                                cam.value, frame.raw, frame.annotated
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

        if self._camera_layout == "split_feeder":
            camera_name_map = {
                "c_channel_2": "c_channel_2",
                "c_channel_3": "c_channel_3",
                "carousel": "carousel",
            }
        else:
            camera_name_map = {
                "feeder": "c_channel",
                "classification_bottom": "classification_chamber_bottom",
                "classification_top": "classification_chamber_top",
            }
        for internal_name, telemetry_name in camera_name_map.items():
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

        if self._feeder_detector is not None:
            annotated = self._feeder_detector.annotateFrame(annotated)
            from subsystems.feeder.analysis import getBboxSections
            for det in self.getFeederHeatmapDetections():
                x1, y1, x2, y2 = det.bbox
                secs = getBboxSections(det.bbox, det.channel)
                exit_zone = bool(secs & det.channel.exit_sections)
                drop = bool(secs & det.channel.dropzone_sections)
                label = f"ch{det.channel_id} {sorted(secs)} e={exit_zone} d={drop}"
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

    _ROLE_TO_POLY_KEY = {
        "c_channel_2": "second_channel",
        "c_channel_3": "third_channel",
        "carousel": "carousel",
    }

    def _annotateSplitChannelFrame(
        self, role: str, capture: Optional[CaptureThread],
        cached_frame_attr: str, cached_ts_attr: str,
    ) -> Optional[CameraFrame]:
        if capture is None:
            return None
        frame = capture.latest_frame
        if frame is None:
            return None

        cached = getattr(self, cached_frame_attr)
        cached_ts = getattr(self, cached_ts_attr)
        if cached is not None and frame.timestamp == cached_ts:
            return cached

        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()

        # Draw zone overlays (section wedges, polygon outlines, section labels)
        poly_key = self._ROLE_TO_POLY_KEY.get(role)
        if poly_key and isinstance(self._region_provider, HanddrawnRegionProvider):
            annotated = self._region_provider.annotateFrameForChannel(annotated, poly_key)

        detector = self._per_channel_detectors.get(role)
        if self.getFeederDetectionAlgorithm() == "gemini_sam":
            detection = self._getFeederDynamicDetection(role, force=False)
            if detection is not None:
                for index, bbox in enumerate(detection.bboxes, start=1):
                    x1, y1, x2, y2 = [int(value) for value in bbox]
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (168, 85, 247), 2, cv2.LINE_AA)
                    cv2.putText(
                        annotated,
                        str(index),
                        (x1 + 6, max(18, y1 + 18)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (168, 85, 247),
                        2,
                        cv2.LINE_AA,
                    )
        elif detector is not None:
            annotated = detector.annotateFrame(annotated)
            from subsystems.feeder.analysis import getBboxSections
            analysis = self._per_channel_analysis.get(role)
            if analysis is not None:
                for det in analysis.getDetections():
                    x1, y1, x2, y2 = det.bbox
                    secs = getBboxSections(det.bbox, det.channel)
                    exit_zone = bool(secs & det.channel.exit_sections)
                    drop = bool(secs & det.channel.dropzone_sections)
                    label = f"ch{det.channel_id} {sorted(secs)} e={exit_zone} d={drop}"
                    cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)

        result = CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=[],
            timestamp=frame.timestamp,
        )
        setattr(self, cached_frame_attr, result)
        setattr(self, cached_ts_attr, frame.timestamp)
        return result

    @property
    def c_channel_2_frame(self) -> Optional[CameraFrame]:
        return self._annotateSplitChannelFrame(
            "c_channel_2", self._c_channel_2_capture,
            "_cached_c_channel_2_frame", "_cached_c_channel_2_frame_ts",
        )

    @property
    def c_channel_3_frame(self) -> Optional[CameraFrame]:
        return self._annotateSplitChannelFrame(
            "c_channel_3", self._c_channel_3_capture,
            "_cached_c_channel_3_frame", "_cached_c_channel_3_frame_ts",
        )

    @property
    def carousel_frame(self) -> Optional[CameraFrame]:
        if self._carousel_capture is None:
            return None
        frame = self._carousel_capture.latest_frame
        if frame is None:
            return None

        if self._cached_carousel_frame is not None and frame.timestamp == self._cached_carousel_frame_ts:
            return self._cached_carousel_frame

        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()

        # Draw carousel polygon overlay via region provider
        if isinstance(self._region_provider, HanddrawnRegionProvider):
            annotated = self._region_provider.annotateFrameForChannel(annotated, "carousel")

        if self.getCarouselDetectionAlgorithm() == "gemini_sam":
            detection = self._getCarouselDynamicDetection(force=False)
            if detection is not None:
                for index, bbox in enumerate(detection.bboxes, start=1):
                    x1, y1, x2, y2 = [int(value) for value in bbox]
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (168, 85, 247), 2, cv2.LINE_AA)
                    cv2.putText(
                        annotated,
                        str(index),
                        (x1 + 6, max(18, y1 + 18)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (168, 85, 247),
                        2,
                        cv2.LINE_AA,
                    )
        elif self._carousel_heatmap.has_baseline:
            annotated = self._carousel_heatmap.annotateFrame(annotated, label="carousel", text_y=80)

        result = CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=[],
            timestamp=frame.timestamp,
        )
        self._cached_carousel_frame = result
        self._cached_carousel_frame_ts = frame.timestamp
        return result

    def _buildFeederDetectionPayload(
        self,
        role: str,
        frame: CameraFrame,
        *,
        force: bool,
    ) -> Dict[str, object]:
        algorithm = self.getFeederDetectionAlgorithm()
        frame_h, frame_w = frame.raw.shape[:2]
        channel = self._channelInfoForRole(role)
        zone_bbox: Tuple[int, int, int, int] | None = None
        zone_point_count = 0
        if channel is not None:
            x, y, w, h = cv2.boundingRect(channel.polygon.astype(np.int32))
            zone_bbox = (int(x), int(y), int(x + w), int(y + h))
            zone_point_count = int(len(channel.polygon))

        result: Dict[str, object] = {
            "camera": role,
            "algorithm": algorithm,
            "frame_resolution": [int(frame_w), int(frame_h)],
            "zone_bbox": list(zone_bbox) if zone_bbox is not None else None,
            "zone_point_count": zone_point_count,
        }

        if algorithm == "gemini_sam":
            detection = self._getFeederDynamicDetection(role, force=force)
            if detection is None:
                message = "Cloud vision did not find a piece in the current frame."
                detector = self._feeder_gemini_detectors.get(role)
                error_detail = detector._last_error if detector is not None else None
                if isinstance(error_detail, str) and error_detail:
                    message = f"API error: {error_detail}"
                result.update(
                    {
                        "found": False,
                        "bbox": None,
                        "candidate_bboxes": [],
                        "bbox_count": 0,
                        "score": None,
                        "message": message,
                    }
                )
                return result

            result.update(
                {
                    "found": detection.bbox is not None,
                    "bbox": list(detection.bbox) if detection.bbox is not None else None,
                    "candidate_bboxes": [list(candidate) for candidate in detection.bboxes],
                    "bbox_count": len(detection.bboxes),
                    "score": float(detection.score),
                    "message": (
                        "Cloud vision found candidate pieces."
                        if detection.bbox is not None
                        else "Cloud vision did not find a piece in the current frame."
                    ),
                }
            )
            return result

        analysis = self._per_channel_analysis.get(role)
        detections = analysis.getDetections() if analysis is not None else []
        bboxes = [list(det.bbox) for det in detections]
        result.update(
            {
                "found": bool(detections),
                "bbox": bboxes[0] if bboxes else None,
                "candidate_bboxes": bboxes,
                "bbox_count": len(bboxes),
                "score": float(len(bboxes)),
                "message": (
                    "MOG2 found candidate pieces."
                    if bboxes
                    else "MOG2 did not find a piece in the current frame."
                ),
            }
        )
        return result

    def debugFeederDetection(self, role: str, *, include_capture: bool = False) -> Dict[str, object]:
        if role not in {"c_channel_2", "c_channel_3"}:
            raise ValueError(f"Unsupported feeder role '{role}'")
        capture = self.getCaptureThreadForRole(role)
        if capture is None:
            return {
                "camera": role,
                "algorithm": self.getFeederDetectionAlgorithm(),
                "found": False,
                "message": "No camera is configured for this channel.",
            }
        frame = capture.latest_frame
        if frame is None:
            return {
                "camera": role,
                "algorithm": self.getFeederDetectionAlgorithm(),
                "found": False,
                "message": "No live frame is available yet.",
            }
        result = self._buildFeederDetectionPayload(role, frame, force=True)
        candidates = result.get("candidate_bboxes")
        if isinstance(candidates, list):
            result["candidate_previews"] = [
                self._encodeDebugCrop(frame.raw, tuple(int(value) for value in candidate[:4]))
                for candidate in candidates
                if isinstance(candidate, list) and len(candidate) >= 4
            ]
        if include_capture:
            result["_sample_capture"] = self._captureAuxiliarySample(role)
        return result

    def _buildCarouselDetectionPayload(
        self,
        frame: CameraFrame,
        *,
        force: bool,
    ) -> Dict[str, object]:
        algorithm = self.getCarouselDetectionAlgorithm()
        frame_h, frame_w = frame.raw.shape[:2]
        zone_bbox: Tuple[int, int, int, int] | None = None
        zone_point_count = 0
        if self._carousel_polygon is not None and len(self._carousel_polygon) >= 3:
            polygon = np.array(self._carousel_polygon, dtype=np.int32)
            x, y, w, h = cv2.boundingRect(polygon)
            zone_bbox = (int(x), int(y), int(x + w), int(y + h))
            zone_point_count = int(len(polygon))

        result: Dict[str, object] = {
            "camera": "carousel",
            "algorithm": algorithm,
            "frame_resolution": [int(frame_w), int(frame_h)],
            "zone_bbox": list(zone_bbox) if zone_bbox is not None else None,
            "zone_point_count": zone_point_count,
        }

        if algorithm == "gemini_sam":
            detection = self._getCarouselDynamicDetection(force=force)
            if detection is None:
                error_detail = self._carousel_gemini_detector._last_error if self._carousel_gemini_detector else None
                message = "Cloud vision did not find a piece on the carousel."
                if isinstance(error_detail, str) and error_detail:
                    message = f"API error: {error_detail}"
                result.update(
                    {
                        "found": False,
                        "bbox": None,
                        "candidate_bboxes": [],
                        "bbox_count": 0,
                        "score": None,
                        "message": message,
                    }
                )
                return result

            result.update(
                {
                    "found": detection.bbox is not None,
                    "bbox": list(detection.bbox) if detection.bbox is not None else None,
                    "candidate_bboxes": [list(candidate) for candidate in detection.bboxes],
                    "bbox_count": len(detection.bboxes),
                    "score": float(detection.score),
                    "message": (
                        "Cloud vision found a carousel piece."
                        if detection.bbox is not None
                        else "Cloud vision did not find a piece on the carousel."
                    ),
                }
            )
            return result

        score, hot_px = self._carousel_heatmap.computeDiff()
        bboxes = [list(candidate) for candidate in self._carousel_heatmap.computeBboxes()]
        result.update(
            {
                "found": bool(bboxes),
                "bbox": bboxes[0] if bboxes else None,
                "candidate_bboxes": bboxes,
                "bbox_count": len(bboxes),
                "score": float(score),
                "hot_pixels": int(hot_px),
                "message": (
                    "Heatmap diff found a carousel trigger."
                    if bboxes
                    else "Heatmap diff did not detect a carousel drop."
                ),
            }
        )
        return result

    def debugCarouselDetection(self, *, include_capture: bool = False) -> Dict[str, object]:
        if self._carousel_capture is None:
            return {
                "camera": "carousel",
                "algorithm": self.getCarouselDetectionAlgorithm(),
                "found": False,
                "message": "No carousel camera is configured.",
            }
        frame = self._carousel_capture.latest_frame
        if frame is None:
            return {
                "camera": "carousel",
                "algorithm": self.getCarouselDetectionAlgorithm(),
                "found": False,
                "message": "No live frame is available yet.",
            }
        result = self._buildCarouselDetectionPayload(frame, force=True)
        candidates = result.get("candidate_bboxes")
        if isinstance(candidates, list):
            result["candidate_previews"] = [
                self._encodeDebugCrop(frame.raw, tuple(int(value) for value in candidate[:4]))
                for candidate in candidates
                if isinstance(candidate, list) and len(candidate) >= 4
            ]
        if include_capture:
            result["_sample_capture"] = self._captureAuxiliarySample("carousel")
        return result

    def _archiveAuxiliaryDetectionSample(self, role: str, payload: Dict[str, object]) -> None:
        sample = self._captureAuxiliarySample(role)
        input_image = sample.get("input_image")
        frame = sample.get("frame")
        if not isinstance(input_image, np.ndarray) or input_image.size == 0:
            return
        try:
            from server.classification_training import getClassificationTrainingManager
        except Exception:
            return

        bbox = payload.get("bbox")
        candidate_bboxes = payload.get("candidate_bboxes")
        getClassificationTrainingManager().saveAuxiliaryDetectionCapture(
            source="periodic_detection_snapshot",
            source_role=role,
            detection_scope=self._sampleRoleScope(role),
            capture_reason="positive_detection",
            detection_algorithm=str(payload.get("algorithm") or ""),
            detection_openrouter_model=(
                self.getFeederOpenRouterModel()
                if role in {"c_channel_2", "c_channel_3"} and self.getFeederDetectionAlgorithm() == "gemini_sam"
                else (
                    self.getCarouselOpenRouterModel()
                    if role == "carousel" and self.getCarouselDetectionAlgorithm() == "gemini_sam"
                    else None
                )
            ),
            detection_found=bool(payload.get("found")),
            detection_bbox=bbox if isinstance(bbox, list) else None,
            detection_candidate_bboxes=candidate_bboxes if isinstance(candidate_bboxes, list) else [],
            detection_bbox_count=int(payload.get("bbox_count") or 0),
            detection_score=float(payload.get("score")) if isinstance(payload.get("score"), (int, float)) else None,
            detection_message=payload.get("message") if isinstance(payload.get("message"), str) else None,
            input_image=input_image,
            source_frame=frame if isinstance(frame, np.ndarray) else None,
        )

    def _refreshAuxiliaryDetections(self) -> None:
        if self.getFeederDetectionAlgorithm() == "gemini_sam":
            for role in ("c_channel_2", "c_channel_3"):
                capture = self.getCaptureThreadForRole(role)
                frame = capture.latest_frame if capture is not None else None
                if frame is None:
                    continue
                cached = self._feeder_dynamic_detection_cache.get(role)
                if cached is not None and cached[0] == frame.timestamp:
                    continue
                detection = self._computeFeederGeminiDetection(role, frame, force_call=False)
                self._feeder_dynamic_detection_cache[role] = (frame.timestamp, detection)

        if self.getCarouselDetectionAlgorithm() == "gemini_sam" and self._carousel_capture is not None:
            frame = self._carousel_capture.latest_frame
            if frame is not None:
                cached = self._carousel_dynamic_detection_cache
                if cached is None or cached[0] != frame.timestamp:
                    detection = self._computeCarouselGeminiDetection(frame, force_call=False)
                    self._carousel_dynamic_detection_cache = (frame.timestamp, detection)

    def _maybeArchiveAuxiliarySnapshots(self) -> None:
        now = time.time()
        sample_candidates: list[tuple[str, Dict[str, object]]] = []

        if self.isFeederSampleCollectionEnabled():
            for role in ("c_channel_2", "c_channel_3"):
                capture = self.getCaptureThreadForRole(role)
                frame = capture.latest_frame if capture is not None else None
                if frame is None:
                    continue
                payload = self._buildFeederDetectionPayload(role, frame, force=False)
                if not bool(payload.get("found")):
                    continue
                sample_candidates.append((role, payload))

        if self.isCarouselSampleCollectionEnabled() and self._carousel_capture is not None:
            frame = self._carousel_capture.latest_frame
            if frame is not None:
                payload = self._buildCarouselDetectionPayload(frame, force=False)
                if bool(payload.get("found")):
                    sample_candidates.append(("carousel", payload))

        for role, payload in sample_candidates:
            last_saved = self._auxiliary_last_sample_at.get(role, 0.0)
            if now - last_saved < AUXILIARY_SAMPLE_INTERVAL_S:
                continue
            self._archiveAuxiliaryDetectionSample(role, payload)
            self._auxiliary_last_sample_at[role] = now

    def _auxiliaryDetectionLoop(self) -> None:
        while not self._aux_detection_stop.is_set():
            try:
                self._refreshAuxiliaryDetections()
                self._maybeArchiveAuxiliarySnapshots()
            except Exception as exc:
                self.gc.logger.warning(f"Auxiliary detection loop error: {exc}")
            self._aux_detection_stop.wait(AUXILIARY_DETECTION_LOOP_INTERVAL_S)

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
        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()
        uses_baseline = self.usesClassificationBaseline()
        if uses_baseline and heatmap is not None and heatmap.has_baseline:
            annotated = heatmap.annotateFrame(
                annotated,
                label=self._classificationAnnotationLabel(cam),
                text_y=30,
            )

        if not uses_baseline:
            detection = self._getDynamicClassificationDetection(cam, force=False)
            if detection is not None:
                for candidate in detection.bboxes:
                    x1, y1, x2, y2 = [int(value) for value in candidate]
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (168, 85, 247), 2, cv2.LINE_AA)
                if detection.bbox is not None:
                    x1, y1, x2, y2 = [int(value) for value in detection.bbox]
                    cv2.putText(
                        annotated,
                        "cloud",
                        (x1, max(16, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (168, 85, 247),
                        1,
                        cv2.LINE_AA,
                    )
        bbox = self.getClassificationCombinedBbox(cam) if uses_baseline else None
        if bbox is not None:
            margins = self._edgeBiasedMargins(bbox, cam)
            fh, fw = annotated.shape[:2]
            mx1 = max(0, bbox[0] - margins[0])
            my1 = max(0, bbox[1] - margins[1])
            mx2 = min(fw, bbox[2] + margins[2])
            my2 = min(fh, bbox[3] + margins[3])
            cv2.rectangle(annotated, (mx1, my1), (mx2, my2), (0, 200, 255), 2, cv2.LINE_AA)
            bias_parts = []
            base = self._diff_config.crop_margin_px
            for side, val in zip(["L", "T", "R", "B"], margins):
                if val != base:
                    bias_parts.append(f"{side}:{val}")
            bias_label = f"  ({', '.join(bias_parts)})" if bias_parts else ""
            method_label = (
                "baseline"
                if self.usesClassificationBaseline()
                else self._diff_config.algorithm.replace("_", " ")
            )
            cv2.putText(
                annotated,
                f"{method_label} crop +{base}px{bias_label}",
                (mx1, my1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 200, 255),
                1,
            )
        elif uses_baseline and (heatmap is None or not heatmap.has_baseline):
            return frame

        return CameraFrame(
            raw=frame.raw,
            annotated=annotated,
            results=frame.results,
            timestamp=frame.timestamp,
        )

    def _getCaptureFrame(self, capture: Optional[CaptureThread]) -> Optional[CameraFrame]:
        if capture is None:
            return None
        return capture.latest_frame

    def getCaptureThreadForRole(self, camera_name: str) -> Optional[CaptureThread]:
        if camera_name == "feeder":
            return self._feeder_capture
        if camera_name == "classification_bottom":
            return self._classification_bottom_capture
        if camera_name == "classification_top":
            return self._classification_top_capture
        if camera_name == "c_channel_2":
            return self._c_channel_2_capture
        if camera_name == "c_channel_3":
            return self._c_channel_3_capture
        if camera_name == "carousel":
            return self._carousel_capture
        return None

    def setCameraSourceForRole(
        self,
        camera_name: str,
        source: int | str | None,
    ) -> bool:
        capture_attr, config_attr = self._cameraRoleAttrs(camera_name)
        if capture_attr is None or config_attr is None:
            return False

        config = getattr(self._irl_config, config_attr, None)
        if config is None:
            config = mkCameraConfig(device_index=-1)
            setattr(self._irl_config, config_attr, config)

        if isinstance(source, str):
            config.url = source
            config.device_index = -1
        elif isinstance(source, int):
            config.url = None
            config.device_index = source
        else:
            config.url = None
            config.device_index = -1

        capture = getattr(self, capture_attr, None)
        if capture is None:
            if source is None:
                return True
            capture = CaptureThread(camera_name, config)
            setattr(self, capture_attr, capture)
            if self._started:
                capture.start()
        else:
            capture.setCameraSource(source)

        if self._camera_layout == "split_feeder" and camera_name == "c_channel_2":
            self._feeder_capture = capture

        return True

    def setPictureSettingsForRole(
        self,
        camera_name: str,
        settings: CameraPictureSettings,
    ) -> bool:
        capture = self.getCaptureThreadForRole(camera_name)
        if capture is None:
            return False
        capture.setPictureSettings(settings)
        return True

    def setDeviceSettingsForRole(
        self,
        camera_name: str,
        settings: dict[str, int | float | bool] | None,
        *,
        persist: bool = False,
    ) -> dict[str, int | float | bool] | None:
        capture = self.getCaptureThreadForRole(camera_name)
        if capture is None:
            return None
        config_attr = self._cameraRoleAttrs(camera_name)[1]
        if persist and config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.device_settings = dict(settings or {})
        return capture.setDeviceSettings(settings, persist=persist)

    def setColorProfileForRole(
        self,
        camera_name: str,
        profile: CameraColorProfile | None,
    ) -> bool:
        capture = self.getCaptureThreadForRole(camera_name)
        if capture is None:
            return False
        config_attr = self._cameraRoleAttrs(camera_name)[1]
        if config_attr is not None:
            config = getattr(self._irl_config, config_attr, None)
            if config is not None:
                config.color_profile = profile
        capture.setColorProfile(profile)
        return True

    def _cameraRoleAttrs(self, camera_name: str) -> tuple[str | None, str | None]:
        if camera_name == "feeder":
            return "_feeder_capture", "feeder_camera"
        if camera_name == "classification_bottom":
            return "_classification_bottom_capture", "classification_camera_bottom"
        if camera_name == "classification_top":
            return "_classification_top_capture", "classification_camera_top"
        if camera_name == "c_channel_2":
            return "_c_channel_2_capture", "c_channel_2_camera"
        if camera_name == "c_channel_3":
            return "_c_channel_3_capture", "c_channel_3_camera"
        if camera_name == "carousel":
            return "_carousel_capture", "carousel_camera"
        return None, None

    def getFrame(self, camera_name: str) -> Optional[CameraFrame]:
        if camera_name == "feeder":
            return self.feeder_frame
        elif camera_name == "classification_bottom":
            return self.classification_bottom_frame
        elif camera_name == "classification_top":
            return self.classification_top_frame
        elif camera_name == "c_channel_2":
            return self.c_channel_2_frame
        elif camera_name == "c_channel_3":
            return self.c_channel_3_frame
        elif camera_name == "carousel":
            return self.carousel_frame
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

    def _cropToBbox(self, frame: np.ndarray, bbox: Tuple[int, int, int, int],
                    margins: Tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        x1 = max(0, min(x1 - margins[0], w))
        y1 = max(0, min(y1 - margins[1], h))
        x2 = max(0, min(x2 + margins[2], w))
        y2 = max(0, min(y2 + margins[3], h))
        return frame[y1:y2, x1:x2]

    def _encodeDebugCrop(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        *,
        max_dim: int = 140,
    ) -> str | None:
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        bw = max(0, x2 - x1)
        bh = max(0, y2 - y1)
        if bw <= 0 or bh <= 0:
            return None

        pad = max(6, int(round(max(bw, bh) * 0.08)))
        cx1 = max(0, x1 - pad)
        cy1 = max(0, y1 - pad)
        cx2 = min(w, x2 + pad)
        cy2 = min(h, y2 + pad)
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None

        crop_h, crop_w = crop.shape[:2]
        largest_dim = max(crop_h, crop_w)
        if largest_dim > max_dim:
            scale = float(max_dim) / float(largest_dim)
            resized_w = max(1, int(round(crop_w * scale)))
            resized_h = max(1, int(round(crop_h * scale)))
            crop = cv2.resize(crop, (resized_w, resized_h), interpolation=cv2.INTER_AREA)

        return self._encodeFrame(crop)

    def _edgeBiasedMargins(self, bbox: Tuple[int, int, int, int],
                           mask_key: str) -> Tuple[int, int, int, int]:
        cfg = self._diff_config
        base = cfg.crop_margin_px
        mult = cfg.edge_bias_mult
        threshold = cfg.edge_bias_threshold_px
        mask_bbox = self._classification_mask_bboxes.get(mask_key)
        if mask_bbox is None or threshold <= 0:
            return (base, base, base, base)
        distances = (
            bbox[0] - mask_bbox[0],
            bbox[1] - mask_bbox[1],
            mask_bbox[2] - bbox[2],
            mask_bbox[3] - bbox[3],
        )
        result: list[int] = []
        for dist in distances:
            if dist >= threshold:
                result.append(base)
            else:
                proximity = 1.0 - (max(0, dist) / threshold)
                result.append(int(base * (1.0 + (mult - 1.0) * proximity)))
        return (result[0], result[1], result[2], result[3])

    def getClassificationCrops(
        self,
        timeout_s: float = 1.0,
        *,
        top_frame: CameraFrame | None = None,
        bottom_frame: CameraFrame | None = None,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if top_frame is None and bottom_frame is None:
            top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)

        top_crop: np.ndarray | None = None
        if top_frame is not None:
            bbox = self.getClassificationCombinedBbox("top", force=True, frame=top_frame)
            if bbox is not None:
                margins = self._edgeBiasedMargins(bbox, "top")
                top_crop = self._cropToBbox(top_frame.raw, bbox, margins)

        bottom_crop: np.ndarray | None = None
        if bottom_frame is not None:
            bbox = self.getClassificationCombinedBbox("bottom", force=True, frame=bottom_frame)
            if bbox is not None:
                margins = self._edgeBiasedMargins(bbox, "bottom")
                bottom_crop = self._cropToBbox(bottom_frame.raw, bbox, margins)

        return (top_crop, bottom_crop)

    def getClassificationZoneCrop(
        self,
        cam: str,
        timeout_s: float = 1.0,
    ) -> Optional[np.ndarray]:
        sample = self.captureClassificationSample(cam, timeout_s=timeout_s)
        zone = sample.get(f"{cam}_zone")
        return zone if isinstance(zone, np.ndarray) else None

    def _classificationZoneCropFromFrame(
        self,
        cam: str,
        frame: CameraFrame | None,
    ) -> Optional[np.ndarray]:
        if cam not in {"top", "bottom"}:
            return None
        if frame is None:
            return None

        polygon = self._classification_masks.get(cam)
        if polygon is None or len(polygon) < 3:
            return frame.raw.copy()

        frame_h, frame_w = frame.raw.shape[:2]
        scaled_polygon = self._scalePolygon(polygon, frame_w, frame_h)
        x, y, w, h = cv2.boundingRect(scaled_polygon)
        masked = self._maskToRegion(frame.raw, cam)
        x2 = min(frame_w, x + w)
        y2 = min(frame_h, y + h)
        if x2 <= x or y2 <= y:
            return None
        return masked[y:y2, x:x2].copy()

    def _classificationSampleFromFrames(
        self,
        top_frame: CameraFrame | None,
        bottom_frame: CameraFrame | None,
    ) -> Dict[str, np.ndarray | None]:
        return {
            "top_zone": self._classificationZoneCropFromFrame("top", top_frame),
            "bottom_zone": self._classificationZoneCropFromFrame("bottom", bottom_frame),
            "top_frame": top_frame.raw.copy() if top_frame is not None else None,
            "bottom_frame": bottom_frame.raw.copy() if bottom_frame is not None else None,
        }

    def getClassificationSampleFromFrames(
        self,
        top_frame: CameraFrame | None,
        bottom_frame: CameraFrame | None,
    ) -> Dict[str, np.ndarray | None]:
        return self._classificationSampleFromFrames(top_frame, bottom_frame)

    def captureClassificationSample(
        self,
        cam: str,
        timeout_s: float = 1.0,
    ) -> Dict[str, np.ndarray | None]:
        if cam not in {"top", "bottom"}:
            return {
                "top_zone": None,
                "bottom_zone": None,
                "top_frame": None,
                "bottom_frame": None,
            }

        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)
        return self._classificationSampleFromFrames(top_frame, bottom_frame)

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

    @property
    def _active_cameras(self) -> List[CameraName]:
        if self._camera_layout == "split_feeder":
            cams = [CameraName.c_channel_2, CameraName.c_channel_3, CameraName.carousel]
            if self._classification_top_capture:
                cams.append(CameraName.classification_top)
            if self._classification_bottom_capture:
                cams.append(CameraName.classification_bottom)
            return cams
        return [CameraName.feeder, CameraName.classification_bottom, CameraName.classification_top]

    def _frameEncodeLoop(self) -> None:
        while not self._frame_encode_stop.is_set():
            prof = self.gc.profiler
            prof.hit("vision.frame_encode_thread.calls")
            with prof.timer("vision.frame_encode_thread.total_ms"):
                events: List[FrameEvent] = []
                for camera in self._active_cameras:
                    event = self.getFrameEvent(camera)
                    if event:
                        events.append(event)
                with self._cached_frame_events_lock:
                    self._cached_frame_events = events
            self._frame_encode_stop.wait(FRAME_ENCODE_INTERVAL_MS / 1000.0)
