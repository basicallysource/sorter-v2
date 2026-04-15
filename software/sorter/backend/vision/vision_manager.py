from typing import Optional, List, Dict, Tuple, Union, cast, Any
from pathlib import Path
import base64
import time
import threading
from dataclasses import dataclass, field, replace
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
    CarouselDetectionAlgorithm,
    ClassificationDetectionAlgorithm,
    FeederDetectionAlgorithm,
    detection_algorithm_definition,
    normalize_detection_algorithm,
    scope_supports_detection_algorithm,
)
from .diff_configs import (
    CarouselDiffConfig,
    ClassificationDiffConfig,
    DEFAULT_CAROUSEL_DIFF_CONFIG,
    DEFAULT_CLASSIFICATION_DIFF_CONFIG,
)

TELEMETRY_INTERVAL_S = 30
AUXILIARY_DETECTION_LOOP_INTERVAL_S = 0.25
OPENROUTER_MAX_CONCURRENCY = 10
OPENROUTER_FAILURE_BACKOFF_S = 2.0
OPENROUTER_BACKGROUND_RETRY_PADDING_S = 0.35


@dataclass(frozen=True)
class AuxiliaryTeacherCaptureRequest:
    role: str
    scope: DetectionScope
    source: str
    capture_reason: str
    due_at: float
    created_at: float
    trigger_algorithm: str | None = None
    trigger_metadata: dict[str, Any] = field(default_factory=dict)
    frame_snapshot: np.ndarray | None = None


class VisionManager:
    _irl_config: IRLConfig
    _video_recorder: Optional[VideoRecorder]
    _region_provider: Union[ArucoRegionProvider, DefaultRegionProvider, HanddrawnRegionProvider]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig, irl: IRLInterface, camera_service=None):
        from .camera_service import CameraService

        self.gc = gc
        self._irl_config = irl_config
        self._irl = irl
        self._camera_layout = getattr(irl_config, "camera_layout", "default")
        self._disabled_cameras = set(gc.disable_video_streams)

        # CameraService owns all capture threads
        self._camera_service: CameraService = camera_service

        # Backward-compatible aliases — used by property delegates below
        # (kept so the hundreds of existing self._*_capture references keep working)

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

        # Per-channel detectors/analysis for split_feeder mode
        self._per_channel_detectors: Dict[str, Mog2ChannelDetector] = {}
        self._per_channel_analysis: Dict[str, FeederAnalysisThread] = {}

        self._classification_masks: Dict[str, np.ndarray] = {}
        self._classification_mask_bboxes: Dict[str, Tuple[int, int, int, int]] = {}
        self._classification_polygon_resolution: Tuple[int, int] = (1920, 1080)
        self._loadClassificationPolygons()
        self._carousel_diff_config: CarouselDiffConfig = DEFAULT_CAROUSEL_DIFF_CONFIG
        self._diff_config: ClassificationDiffConfig = DEFAULT_CLASSIFICATION_DIFF_CONFIG
        self._loadClassificationDetectionConfig()
        self._feeder_detection_algorithm: FeederDetectionAlgorithm = "mog2"
        self._feeder_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
        self._feeder_sample_collection_enabled: bool = False
        self._feeder_sample_collection_enabled_by_role: Dict[str, bool] = {
            "c_channel_2": False,
            "c_channel_3": False,
        }
        self._carousel_detection_algorithm: CarouselDetectionAlgorithm = "heatmap_diff"
        self._carousel_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
        self._carousel_sample_collection_enabled: bool = False
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
        self._auxiliary_capture_requests: list[AuxiliaryTeacherCaptureRequest] = []
        self._auxiliary_capture_lock = threading.Lock()
        self._openrouter_request_lock = threading.Lock()
        self._openrouter_next_allowed_at: float = 0.0
        self._openrouter_semaphore = threading.BoundedSemaphore(OPENROUTER_MAX_CONCURRENCY)

        self._started = False

    # ---- Capture-thread property delegates (CameraService owns the threads) ----

    @property
    def _feeder_capture(self) -> Optional[CaptureThread]:
        if self._camera_service is None:
            return None
        return self._camera_service.get_capture_thread_for_role("feeder")

    @_feeder_capture.setter
    def _feeder_capture(self, value):
        pass  # no-op: CameraService manages this

    @property
    def _classification_bottom_capture(self) -> Optional[CaptureThread]:
        if self._camera_service is None:
            return None
        return self._camera_service.get_capture_thread_for_role("classification_bottom")

    @_classification_bottom_capture.setter
    def _classification_bottom_capture(self, value):
        pass

    @property
    def _classification_top_capture(self) -> Optional[CaptureThread]:
        if self._camera_service is None:
            return None
        return self._camera_service.get_capture_thread_for_role("classification_top")

    @_classification_top_capture.setter
    def _classification_top_capture(self, value):
        pass

    @property
    def _c_channel_2_capture(self) -> Optional[CaptureThread]:
        if self._camera_service is None:
            return None
        return self._camera_service.get_capture_thread_for_role("c_channel_2")

    @_c_channel_2_capture.setter
    def _c_channel_2_capture(self, value):
        pass

    @property
    def _c_channel_3_capture(self) -> Optional[CaptureThread]:
        if self._camera_service is None:
            return None
        return self._camera_service.get_capture_thread_for_role("c_channel_3")

    @_c_channel_3_capture.setter
    def _c_channel_3_capture(self, value):
        pass

    @property
    def _carousel_capture(self) -> Optional[CaptureThread]:
        if self._camera_service is None:
            return None
        return self._camera_service.get_capture_thread_for_role("carousel")

    @_carousel_capture.setter
    def _carousel_capture(self, value):
        pass

    def setTelemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def setArucoSmoothingTimeSeconds(self, smoothing_time_s: float) -> None:
        if isinstance(self._region_provider, ArucoRegionProvider):
            self._region_provider.setSmoothingTimeSeconds(smoothing_time_s)

    def _initOverlays(self) -> None:
        """Register overlays on CameraFeed instances based on current detection config."""
        if self._camera_service is None:
            return

        from .overlays import (
            RegionOverlay,
            ChannelRegionOverlay,
            DetectorOverlay,
            DynamicDetectionOverlay,
            HeatmapOverlay,
            ClassificationOverlay,
        )

        _ROLE_TO_POLY_KEY = {
            "c_channel_2": "second_channel",
            "c_channel_3": "third_channel",
            "carousel": "carousel",
        }

        if self._camera_layout == "split_feeder":
            # Per-channel feeds
            for role in ("c_channel_2", "c_channel_3"):
                feed = self._camera_service.get_feed(role)
                if feed is None:
                    continue
                feed.clear_overlays()
                poly_key = _ROLE_TO_POLY_KEY.get(role)
                if poly_key:
                    feed.add_overlay(ChannelRegionOverlay(self._region_provider, poly_key))
                if self.getFeederDetectionAlgorithm() == "gemini_sam":
                    feed.add_overlay(DynamicDetectionOverlay(
                        lambda r=role: self._getFeederDynamicDetection(r, force=False)
                    ))
                else:
                    detector = self._per_channel_detectors.get(role)
                    analysis = self._per_channel_analysis.get(role)
                    if detector is not None and analysis is not None:
                        feed.add_overlay(DetectorOverlay(detector, analysis.getDetections))

            # Carousel feed
            carousel_feed = self._camera_service.get_feed("carousel")
            if carousel_feed is not None:
                carousel_feed.clear_overlays()
                carousel_feed.add_overlay(ChannelRegionOverlay(self._region_provider, "carousel"))
                if self.getCarouselDetectionAlgorithm() == "gemini_sam":
                    carousel_feed.add_overlay(DynamicDetectionOverlay(
                        lambda: self._getCarouselDynamicDetection(force=False)
                    ))
                elif self._carousel_heatmap.has_baseline:
                    carousel_feed.add_overlay(HeatmapOverlay(self._carousel_heatmap, label="carousel", text_y=80))
        else:
            # Default layout — feeder feed
            feeder_feed = self._camera_service.get_feed("feeder")
            if feeder_feed is not None:
                feeder_feed.clear_overlays()
                feeder_feed.add_overlay(RegionOverlay(self._region_provider))
                if self._feeder_detector is not None:
                    feeder_feed.add_overlay(DetectorOverlay(
                        self._feeder_detector,
                        self.getFeederHeatmapDetections,
                    ))
                if self._carousel_heatmap.has_baseline:
                    feeder_feed.add_overlay(HeatmapOverlay(self._carousel_heatmap, label="carousel", text_y=80))

        # Classification feeds (both layouts)
        for cam_key in ("top", "bottom"):
            role = f"classification_{cam_key}"
            feed = self._camera_service.get_feed(role)
            if feed is None:
                continue
            feed.clear_overlays()
            heatmap_attr = f"_classification_{cam_key}_heatmap"
            feed.add_overlay(ClassificationOverlay(
                cam=cam_key,
                get_heatmap=lambda attr=heatmap_attr: getattr(self, attr, None),
                uses_baseline=self.usesClassificationBaseline,
                get_combined_bbox=self.getClassificationCombinedBbox,
                get_edge_biased_margins=self._edgeBiasedMargins,
                get_dynamic_detection=self._getDynamicClassificationDetection,
                get_diff_config=lambda: self._diff_config,
                get_annotation_label=self._classificationAnnotationLabel,
            ))

    def start(self) -> None:
        self._started = True
        # CameraService.start() already started capture threads + frame encode loop
        self._region_provider.start()
        self._initOverlays()
        self._aux_detection_stop.clear()
        self._aux_detection_thread = threading.Thread(
            target=self._auxiliaryDetectionLoop, daemon=True, name="auxiliary-detection-loop"
        )
        self._aux_detection_thread.start()

    def stop(self) -> None:
        self._started = False
        self._aux_detection_stop.set()
        with self._auxiliary_capture_lock:
            self._auxiliary_capture_requests = []
        if self._aux_detection_thread:
            self._aux_detection_thread.join(timeout=2.0)
        self._stopFeederDetection()
        self._stopClassificationAnalysis()
        self._region_provider.stop()
        # CameraService.stop() handles capture thread shutdown
        if self._video_recorder:
            self._video_recorder.close()

    def _loadClassificationDetectionConfig(self) -> None:
        config = getClassificationDetectionConfig()
        candidate = config.get("algorithm") if isinstance(config, dict) else None
        self._diff_config.algorithm = self._normalizeClassificationDetectionAlgorithm(candidate)
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._classification_openrouter_model = normalize_openrouter_model(model)

    def _loadFeederDetectionConfig(self) -> None:
        config = getFeederDetectionConfig()
        candidate = config.get("algorithm") if isinstance(config, dict) else None
        self._feeder_detection_algorithm = self._normalizeFeederDetectionAlgorithm(candidate)
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._feeder_openrouter_model = normalize_openrouter_model(model)
        enabled = config.get("sample_collection_enabled") if isinstance(config, dict) else None
        by_role = (
            config.get("sample_collection_enabled_by_role")
            if isinstance(config, dict) and isinstance(config.get("sample_collection_enabled_by_role"), dict)
            else None
        )
        resolved_by_role: Dict[str, bool] = {}
        for role in ("c_channel_2", "c_channel_3"):
            role_value = by_role.get(role) if isinstance(by_role, dict) else enabled
            resolved_by_role[role] = False if role_value is None else bool(role_value)
        self._feeder_sample_collection_enabled_by_role = resolved_by_role
        self._feeder_sample_collection_enabled = any(resolved_by_role.values())

    def _loadCarouselDetectionConfig(self) -> None:
        config = getCarouselDetectionConfig()
        candidate = config.get("algorithm") if isinstance(config, dict) else None
        self._carousel_detection_algorithm = self._normalizeCarouselDetectionAlgorithm(candidate)
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._carousel_openrouter_model = normalize_openrouter_model(model)
        enabled = config.get("sample_collection_enabled") if isinstance(config, dict) else None
        self._carousel_sample_collection_enabled = False if enabled is None else bool(enabled)

    def _stopClassificationAnalysis(self) -> None:
        if self._classification_top_analysis:
            self._classification_top_analysis.stop()
            self._classification_top_analysis = None
        if self._classification_bottom_analysis:
            self._classification_bottom_analysis.stop()
            self._classification_bottom_analysis = None
        self._classification_top_heatmap = None
        self._classification_bottom_heatmap = None

    def _stopFeederDetection(self) -> None:
        if self._feeder_analysis:
            self._feeder_analysis.stop()
            self._feeder_analysis = None
        for analysis in self._per_channel_analysis.values():
            analysis.stop()
        self._per_channel_analysis.clear()
        self._per_channel_detectors.clear()
        self._feeder_detector = None

    def getClassificationDetectionAlgorithm(self) -> ClassificationDetectionAlgorithm:
        return self._normalizeClassificationDetectionAlgorithm(self._diff_config.algorithm)

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

    def _normalizeClassificationDetectionAlgorithm(
        self,
        value: str | None,
    ) -> ClassificationDetectionAlgorithm:
        return cast(
            ClassificationDetectionAlgorithm,
            normalize_detection_algorithm("classification", value),
        )

    def _normalizeFeederDetectionAlgorithm(self, value: str | None) -> FeederDetectionAlgorithm:
        return cast(
            FeederDetectionAlgorithm,
            normalize_detection_algorithm("feeder", value),
        )

    def _normalizeCarouselDetectionAlgorithm(
        self,
        value: str | None,
    ) -> CarouselDetectionAlgorithm:
        return cast(
            CarouselDetectionAlgorithm,
            normalize_detection_algorithm("carousel", value),
        )

    @staticmethod
    def _detectionScoreValue(
        detection: ClassificationDetectionResult | None,
        *,
        default: float | None = None,
    ) -> float | None:
        if detection is None or detection.score is None:
            return default
        return float(detection.score)

    def getFeederDetectionAlgorithm(self) -> FeederDetectionAlgorithm:
        return self._normalizeFeederDetectionAlgorithm(self._feeder_detection_algorithm)

    def getFeederOpenRouterModel(self) -> str:
        return normalize_openrouter_model(self._feeder_openrouter_model)

    def supportsFeederSampleCollection(self, role: str | None = None) -> bool:
        if self._camera_layout != "split_feeder":
            return False
        if role == "c_channel_2":
            return self._c_channel_2_capture is not None
        if role == "c_channel_3":
            return self._c_channel_3_capture is not None
        return self._c_channel_2_capture is not None or self._c_channel_3_capture is not None

    def isFeederSampleCollectionEnabled(self, role: str | None = None) -> bool:
        if role in {"c_channel_2", "c_channel_3"}:
            return self.supportsFeederSampleCollection(role) and bool(
                self._feeder_sample_collection_enabled_by_role.get(role)
            )
        if not self.supportsFeederSampleCollection():
            return False
        return any(
            self.isFeederSampleCollectionEnabled(channel_role)
            for channel_role in ("c_channel_2", "c_channel_3")
        )

    def getCarouselDetectionAlgorithm(self) -> CarouselDetectionAlgorithm:
        return self._normalizeCarouselDetectionAlgorithm(self._carousel_detection_algorithm)

    def getCarouselOpenRouterModel(self) -> str:
        return normalize_openrouter_model(self._carousel_openrouter_model)

    def supportsCarouselSampleCollection(self) -> bool:
        return self._carousel_capture is not None

    def isCarouselSampleCollectionEnabled(self) -> bool:
        return self.supportsCarouselSampleCollection() and self._carousel_sample_collection_enabled

    def usesCarouselBaseline(self) -> bool:
        return self.usesDetectionBaseline("carousel")

    def setClassificationDetectionAlgorithm(self, algorithm: ClassificationDetectionAlgorithm) -> bool:
        if not scope_supports_detection_algorithm("classification", algorithm):
            raise ValueError(f"Unsupported classification detection algorithm '{algorithm}'")
        normalized = self._normalizeClassificationDetectionAlgorithm(algorithm)
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
        self._feeder_detection_algorithm = self._normalizeFeederDetectionAlgorithm(algorithm)
        self._feeder_dynamic_detection_cache.clear()

    def setFeederOpenRouterModel(self, model: str) -> str:
        normalized = normalize_openrouter_model(model)
        self._feeder_openrouter_model = normalized
        self._feeder_dynamic_detection_cache.clear()
        for detector in self._feeder_gemini_detectors.values():
            detector.setOpenRouterModel(normalized)
        return normalized

    def setFeederSampleCollectionEnabled(self, enabled: bool, role: str | None = None) -> bool:
        if role is not None and role not in {"c_channel_2", "c_channel_3"}:
            raise ValueError(f"Unsupported feeder role '{role}'")
        if role in {"c_channel_2", "c_channel_3"}:
            self._feeder_sample_collection_enabled_by_role[role] = (
                bool(enabled) if self.supportsFeederSampleCollection(role) else False
            )
            self._feeder_sample_collection_enabled = any(
                self._feeder_sample_collection_enabled_by_role.values()
            )
            return self._feeder_sample_collection_enabled_by_role[role]
        resolved_enabled = bool(enabled) if self.supportsFeederSampleCollection() else False
        for channel_role in ("c_channel_2", "c_channel_3"):
            self._feeder_sample_collection_enabled_by_role[channel_role] = (
                resolved_enabled if self.supportsFeederSampleCollection(channel_role) else False
            )
        self._feeder_sample_collection_enabled = any(
            self._feeder_sample_collection_enabled_by_role.values()
        )
        return self._feeder_sample_collection_enabled

    def setCarouselDetectionAlgorithm(self, algorithm: CarouselDetectionAlgorithm) -> None:
        if not scope_supports_detection_algorithm("carousel", algorithm):
            raise ValueError(f"Unsupported carousel detection algorithm '{algorithm}'")
        self._carousel_detection_algorithm = self._normalizeCarouselDetectionAlgorithm(algorithm)
        self._carousel_dynamic_detection_cache = None

    def setCarouselOpenRouterModel(self, model: str) -> str:
        normalized = normalize_openrouter_model(model)
        self._carousel_openrouter_model = normalized
        self._carousel_dynamic_detection_cache = None
        if self._carousel_gemini_detector is not None:
            self._carousel_gemini_detector.setOpenRouterModel(normalized)
        return normalized

    def setCarouselSampleCollectionEnabled(self, enabled: bool) -> bool:
        self._carousel_sample_collection_enabled = (
            bool(enabled) if self.supportsCarouselSampleCollection() else False
        )
        return self._carousel_sample_collection_enabled

    def _loadCarouselPolygon(
        self,
        polygon_data: Dict[str, Any],
        *,
        source_resolution: tuple[int, int],
    ) -> bool:
        self._carousel_polygon = None
        carousel_pts = polygon_data.get("carousel")
        if not carousel_pts or len(carousel_pts) < 3:
            return False

        src_w, src_h = source_resolution
        if self._camera_layout == "split_feeder" and self._carousel_capture is not None:
            # Scale carousel polygon from editor resolution to the live carousel camera.
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
                return True

        self._carousel_polygon = [(float(p[0]), float(p[1])) for p in carousel_pts]
        return True

    def reloadPolygons(self) -> None:
        from blob_manager import getChannelPolygons
        if isinstance(self._region_provider, HanddrawnRegionProvider):
            self._region_provider.reloadPolygons()
        saved = getChannelPolygons()
        if saved is not None:
            polygon_data = saved.get("polygons", {})
            saved_res = saved.get("resolution", [1920, 1080])
            src_w, src_h = int(saved_res[0]), int(saved_res[1])
            self._loadCarouselPolygon(polygon_data, source_resolution=(src_w, src_h))

    def initFeederDetection(self, *, manual_feed_mode: bool = False) -> bool:
        from blob_manager import getChannelPolygons
        from subsystems.feeder.analysis import parseSavedChannelArcZones, zoneSectionsForChannel

        self._stopFeederDetection()
        self._channel_polygons = {}
        self._channel_masks = {}
        self._channel_angles = {}
        self._carousel_polygon = None

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

        saved_res = saved.get("resolution", [1920, 1080])
        src_w, src_h = int(saved_res[0]), int(saved_res[1])
        carousel_ready = self._loadCarouselPolygon(
            polygon_data,
            source_resolution=(src_w, src_h),
        )

        if manual_feed_mode:
            if carousel_ready:
                self.gc.logger.info(
                    "Feeder detection initialized in manual carousel feed mode; channel automation stays disabled."
                )
            else:
                self.gc.logger.warning(
                    "Manual carousel feed mode is enabled, but no carousel trigger polygon is configured."
                )
            return carousel_ready

        if not polys:
            self.gc.logger.warn("Channel polygons empty. Run: scripts/polygon_editor.py")
            return False

        self._channel_polygons = polys
        self._channel_angles = saved.get("channel_angles", {})

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
            get_gray=self.getLatestFeederRaw,
            profiler=self.gc.profiler,
        )
        self._feeder_analysis.start()
        self.gc.logger.info("Feeder MOG2 detection initialized")
        if self._camera_service is not None:
            self._initOverlays()
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

            def _make_frame_getter(cap: CaptureThread):
                def _get_frame() -> np.ndarray | None:
                    f = cap.latest_frame
                    if f is None:
                        return None
                    return f.raw
                return _get_frame

            analysis = FeederAnalysisThread(
                detector=detector,
                get_gray=_make_frame_getter(capture),
                profiler=self.gc.profiler,
            )
            analysis.start()
            self._per_channel_analysis[role] = analysis
            self.gc.logger.info(f"Split-feeder MOG2 detection initialized for {role} ({cam_w}x{cam_h}, scale={scale_x:.2f}x{scale_y:.2f})")

        result = bool(self._per_channel_detectors)
        if result and self._camera_service is not None:
            self._initOverlays()
        return result

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
            scale=c.classification_scale,
            gc=self.gc,
            pixel_thresh=c.pixel_thresh,
            color_thresh_ab=c.color_thresh_ab,
            blur_kernel=c.blur_kernel,
            min_hot_pixels=c.min_hot_pixels,
            trigger_score=c.trigger_score,
            min_contour_area=c.min_contour_area,
            min_hot_thickness_px=c.min_hot_thickness_px,
            hot_erode_iters=c.hot_erode_iters,
            hot_regrow_iters=c.hot_regrow_iters,
            max_contour_aspect=c.max_contour_aspect,
            heat_gain=c.heat_gain,
            current_frames=c.current_frames,
        )

    def _loadPrecomputedBaseline(self, baseline_dir: Path, cam_key: str, mode: str) -> tuple[np.ndarray, np.ndarray] | None:
        mode_suffix = f"_{mode}" if mode != "gray" else ""
        min_path = baseline_dir / f"{cam_key}_precomputed{mode_suffix}_min.npy"
        max_path = baseline_dir / f"{cam_key}_precomputed{mode_suffix}_max.npy"
        if not min_path.exists() or not max_path.exists():
            return None
        return np.load(str(min_path)), np.load(str(max_path))

    def _loadPngBaseline(self, baseline_dir: Path, cam_key: str, mode: str) -> tuple[np.ndarray, np.ndarray] | None:
        import glob as globmod

        cfg = self._diff_config
        baseline_min_path, baseline_max_path = self._classificationBaselinePaths(baseline_dir, cam_key, mode)
        read_mode = cv2.IMREAD_COLOR if mode == "lab" else cv2.IMREAD_GRAYSCALE
        baseline_min = cv2.imread(str(baseline_min_path), read_mode)
        baseline_max = cv2.imread(str(baseline_max_path), read_mode)
        if baseline_min is None or baseline_max is None:
            return None

        calibration_frames: List[np.ndarray] = []
        frame_pattern = f"{cam_key}_frame_lab_*.png" if mode == "lab" else f"{cam_key}_frame_*.png"
        for p in sorted(globmod.glob(str(baseline_dir / frame_pattern))):
            cal_frame = cv2.imread(p, read_mode)
            if cal_frame is not None:
                calibration_frames.append(cal_frame)

        if len(calibration_frames) >= 2 and cfg.adaptive_std_k > 0:
            stddev = np.std(np.stack(calibration_frames, axis=0).astype(np.float32), axis=0)
            adaptive_margin = np.clip(stddev * cfg.adaptive_std_k, 0, 100).astype(np.uint8)
            baseline_min = np.clip(baseline_min.astype(np.int16) - adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)
            baseline_max = np.clip(baseline_max.astype(np.int16) + adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)

        if cfg.envelope_margin > 0:
            baseline_min = np.clip(baseline_min.astype(np.int16) - cfg.envelope_margin, 0, 255).astype(np.uint8)
            baseline_max = np.clip(baseline_max.astype(np.int16) + cfg.envelope_margin, 0, 255).astype(np.uint8)

        self.gc.logger.info(f"Classification {cam_key} loaded from PNG fallback ({len(calibration_frames)} cal frames)")
        return baseline_min, baseline_max

    def loadClassificationBaseline(self) -> bool:
        from blob_manager import BLOB_DIR

        cfg = self._diff_config
        mode = self._classificationColorMode()

        self._stopClassificationAnalysis()

        baseline_dir = BLOB_DIR / "classification_baseline"
        loaded_any = False

        for cam_key, capture in [("top", self._classification_top_capture), ("bottom", self._classification_bottom_capture)]:
            if capture is None:
                continue

            result = self._loadPrecomputedBaseline(baseline_dir, cam_key, mode)
            if result is not None:
                baseline_min, baseline_max = result
                self.gc.logger.info(f"Classification {cam_key} loaded from precomputed npy")
            else:
                result = self._loadPngBaseline(baseline_dir, cam_key, mode)
                if result is None:
                    self.gc.logger.warn(f"Classification {cam_key} {mode} baseline not found. Run: scripts/calibrate_classification_baseline.py")
                    continue
                baseline_min, baseline_max = result

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

            loaded_any = True

        if loaded_any and self._camera_service is not None:
            self._initOverlays()
        return loaded_any

    def _getLatestClassificationTopGray(self) -> np.ndarray | None:
        if self._classification_top_capture is None:
            return None
        frame = self._classification_top_capture.latest_frame
        if frame is None:
            return None
        return self._classificationDiffFrame(frame.raw)

    def _getLatestClassificationBottomGray(self) -> np.ndarray | None:
        if self._classification_bottom_capture is None:
            return None
        frame = self._classification_bottom_capture.latest_frame
        if frame is None:
            return None
        return self._classificationDiffFrame(frame.raw)

    def getClassificationBboxes(self, cam: str) -> List[Tuple[int, int, int, int]]:
        return self.getClassificationDetectionCandidates(cam)

    def getClassificationDetectionCandidates(
        self,
        cam: str,
        *,
        force: bool = False,
        frame: CameraFrame | None = None,
    ) -> List[Tuple[int, int, int, int]]:
        if self.usesClassificationBaseline():
            if cam == "top" and self._classification_top_analysis:
                return self._classification_top_analysis.getBboxes()
            if cam == "bottom" and self._classification_bottom_analysis:
                return self._classification_bottom_analysis.getBboxes()
            return []

        detection = (
            self._getDynamicClassificationDetectionForFrame(cam, frame, force=force)
            if frame is not None
            else self._getDynamicClassificationDetection(cam, force=force)
        )
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
                    "score": self._detectionScoreValue(detection),
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

    def getLatestFeederLab(self) -> np.ndarray | None:
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2LAB)

    def getLatestFeederRaw(self) -> np.ndarray | None:
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None
        return frame.raw

    def _classificationColorMode(self) -> str:
        mode = str(self._diff_config.color_mode).lower()
        if mode not in ("gray", "lab"):
            raise ValueError(f"Invalid classification color_mode: {self._diff_config.color_mode}")
        return mode

    def _classificationDiffFrame(self, raw: np.ndarray) -> np.ndarray:
        mode = self._classificationColorMode()
        if mode == "lab":
            return cv2.cvtColor(raw, cv2.COLOR_BGR2LAB)
        return cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)

    def _classificationBaselinePaths(self, baseline_dir, cam_key: str, mode: str):
        if mode == "lab":
            return (
                baseline_dir / f"{cam_key}_baseline_lab_min.png",
                baseline_dir / f"{cam_key}_baseline_lab_max.png",
            )
        return (
            baseline_dir / f"{cam_key}_baseline_min.png",
            baseline_dir / f"{cam_key}_baseline_max.png",
        )

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
                self._gemini_sam_detector = GeminiSamDetector(model, zone="classification_chamber")
            else:
                self._gemini_sam_detector.setOpenRouterModel(model)
            return self._gemini_sam_detector

        if request.scope == "feeder":
            detector = self._feeder_gemini_detectors.get(request.role)
            if detector is None:
                detector = GeminiSamDetector(model, zone="c_channel")
                self._feeder_gemini_detectors[request.role] = detector
            else:
                detector.setOpenRouterModel(model)
            return detector

        if self._carousel_gemini_detector is None:
            self._carousel_gemini_detector = GeminiSamDetector(model, zone="carousel")
        else:
            self._carousel_gemini_detector.setOpenRouterModel(model)
        return self._carousel_gemini_detector

    def _openrouterRetryDelay(self) -> float:
        with self._openrouter_request_lock:
            retry_after = self._openrouter_next_allowed_at - time.time()
        return max(OPENROUTER_BACKGROUND_RETRY_PADDING_S, retry_after + OPENROUTER_BACKGROUND_RETRY_PADDING_S)

    def _runGeminiDetectionRequestWithThrottle(
        self,
        request: DetectionRequest,
    ) -> tuple[ClassificationDetectionResult | None, bool]:
        if request.frame is None:
            return None, False

        detector = self._geminiDetectorForRequest(request)
        crop = request.frame
        offset_x = 0
        offset_y = 0
        if request.zone_polygon is not None and len(request.zone_polygon) >= 3:
            cropped = self._cropFrameToPolygonRegion(request.frame, request.zone_polygon)
            if cropped is not None:
                crop, (offset_x, offset_y) = cropped
        background_request = bool(request.metadata.get("background"))
        with self._openrouter_request_lock:
            wait_s = max(0.0, self._openrouter_next_allowed_at - time.time())
        if background_request and wait_s > 0.0:
            return None, True
        slot_acquired = self._openrouter_semaphore.acquire(blocking=not background_request)
        if not slot_acquired:
            return None, True
        try:
            if wait_s > 0.0:
                self.gc.logger.info(
                    "Waiting %.2fs before OpenRouter call for %s/%s",
                    wait_s,
                    request.scope,
                    request.role,
                )
                time.sleep(wait_s)
            detection = detector.detect(crop, force=request.force or background_request)
            error_detail = detector._last_error if isinstance(detector._last_error, str) and detector._last_error else None
            if error_detail:
                with self._openrouter_request_lock:
                    self._openrouter_next_allowed_at = max(
                        self._openrouter_next_allowed_at,
                        time.time() + OPENROUTER_FAILURE_BACKOFF_S,
                    )
        finally:
            self._openrouter_semaphore.release()
        if offset_x == 0 and offset_y == 0:
            return detection, False
        return self._offsetDetectionResult(detection, offset_x, offset_y), False

    def _runGeminiDetectionRequest(
        self,
        request: DetectionRequest,
    ) -> ClassificationDetectionResult | None:
        detection, _ = self._runGeminiDetectionRequestWithThrottle(request)
        return detection

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
                bbox=cast(Tuple[int, int, int, int], tuple(int(value) for value in bbox[:4])),
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

    def _captureAuxiliarySampleFromFrame(self, role: str, frame_raw: np.ndarray) -> dict[str, np.ndarray | None]:
        if role in {"c_channel_2", "c_channel_3"}:
            crop, _ = self._feederRegionCrop(role, frame_raw)
        elif role == "carousel":
            crop, _ = self._carouselRegionCrop(frame_raw)
        else:
            crop = frame_raw.copy()
        return {
            "input_image": crop,
            "frame": frame_raw.copy(),
        }

    def _captureAuxiliarySample(self, role: str) -> dict[str, np.ndarray | None]:
        capture = self.getCaptureThreadForRole(role)
        frame = capture.latest_frame if capture is not None else None
        if frame is None:
            return {"input_image": None, "frame": None}
        return self._captureAuxiliarySampleFromFrame(role, frame.raw)

    def _sampleRoleScope(self, role: str) -> str:
        if role in {"c_channel_2", "c_channel_3"}:
            return "feeder"
        if role == "carousel":
            return "carousel"
        return "classification"

    def _sampleCollectionEnabledForRole(self, role: str) -> bool:
        if role in {"c_channel_2", "c_channel_3"}:
            return self.isFeederSampleCollectionEnabled(role)
        if role == "carousel":
            return self.isCarouselSampleCollectionEnabled()
        return False

    def _queueAuxiliaryTeacherCapture(
        self,
        *,
        role: str,
        capture_reason: str,
        due_at: float,
        trigger_algorithm: str | None,
        trigger_metadata: dict[str, Any] | None = None,
        frame_snapshot: np.ndarray | None = None,
    ) -> None:
        if not self._sampleCollectionEnabledForRole(role):
            return
        request = AuxiliaryTeacherCaptureRequest(
            role=role,
            scope=cast(DetectionScope, self._sampleRoleScope(role)),
            source="live_aux_teacher_capture",
            capture_reason=capture_reason,
            due_at=due_at,
            created_at=time.time(),
            trigger_algorithm=trigger_algorithm,
            trigger_metadata=dict(trigger_metadata or {}),
            frame_snapshot=frame_snapshot.copy() if isinstance(frame_snapshot, np.ndarray) else None,
        )
        with self._auxiliary_capture_lock:
            self._auxiliary_capture_requests.append(request)

    def scheduleFeederTeacherCaptureAfterMove(
        self,
        role: str,
        *,
        delay_s: float,
        move_label: str,
        pulse_degrees: float,
    ) -> None:
        if role not in {"c_channel_2", "c_channel_3"}:
            return
        self._queueAuxiliaryTeacherCapture(
            role=role,
            capture_reason="channel_move_complete",
            due_at=time.time() + max(0.0, delay_s),
            trigger_algorithm=self.getFeederDetectionAlgorithm(),
            trigger_metadata={
                "trigger_move_label": move_label,
                "trigger_move_delay_ms": int(round(max(0.0, delay_s) * 1000.0)),
                "trigger_pulse_degrees": float(pulse_degrees),
            },
        )

    def scheduleCarouselTeacherCaptureOnClassicTrigger(
        self,
        *,
        score: float | None,
        hot_pixels: int | None,
    ) -> None:
        if self.getCarouselDetectionAlgorithm() == "gemini_sam":
            return
        frame_snapshot: np.ndarray | None = None
        if self._carousel_capture is not None and self._carousel_capture.latest_frame is not None:
            frame_snapshot = self._carousel_capture.latest_frame.raw.copy()
        self._queueAuxiliaryTeacherCapture(
            role="carousel",
            capture_reason="carousel_classic_trigger",
            due_at=time.time(),
            trigger_algorithm=self.getCarouselDetectionAlgorithm(),
            trigger_metadata={
                "trigger_score": float(score) if isinstance(score, (int, float)) else None,
                "trigger_hot_pixels": int(hot_pixels) if isinstance(hot_pixels, int) else None,
                "trigger_used_frozen_frame": bool(frame_snapshot is not None),
            },
            frame_snapshot=frame_snapshot,
        )

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

    def getFeederDetectionAvailability(self, *, max_frame_age_s: float = 1.5) -> tuple[bool, str | None]:
        now = time.time()
        algorithm = self.getFeederDetectionAlgorithm()

        if self._camera_layout == "split_feeder":
            required_roles = {
                "c_channel_2": self._c_channel_2_capture,
                "c_channel_3": self._c_channel_3_capture,
            }
            for role, capture in required_roles.items():
                if capture is None:
                    return False, f"{role} camera is not configured."
                frame = capture.latest_frame
                if frame is None:
                    return False, f"{role} camera has no live frame."
                if now - frame.timestamp > max_frame_age_s:
                    return False, f"{role} camera frame is stale."
                if algorithm != "gemini_sam" and role not in self._per_channel_analysis:
                    return False, f"{role} feeder detector is not running."
            return True, None

        if self._feeder_capture is None:
            return False, "feeder camera is not configured."
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return False, "feeder camera has no live frame."
        if now - frame.timestamp > max_frame_age_s:
            return False, "feeder camera frame is stale."
        if algorithm != "gemini_sam" and self._feeder_analysis is None:
            return False, "feeder detector is not running."
        return True, None

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
            score = self._detectionScoreValue(detection, default=0.0) or 0.0
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
        feed = self._camera_service.get_feed("feeder")
        return feed.get_frame(annotated=True) if feed else None

    @property
    def c_channel_2_frame(self) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed("c_channel_2")
        return feed.get_frame(annotated=True) if feed else None

    @property
    def c_channel_3_frame(self) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed("c_channel_3")
        return feed.get_frame(annotated=True) if feed else None

    @property
    def carousel_frame(self) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed("carousel")
        return feed.get_frame(annotated=True) if feed else None

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
                    "score": self._detectionScoreValue(detection),
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
                self._encodeDebugCrop(
                    frame.raw,
                    cast(Tuple[int, int, int, int], tuple(int(value) for value in candidate[:4])),
                )
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
                    "score": self._detectionScoreValue(detection),
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
                self._encodeDebugCrop(
                    frame.raw,
                    cast(Tuple[int, int, int, int], tuple(int(value) for value in candidate[:4])),
                )
                for candidate in candidates
                if isinstance(candidate, list) and len(candidate) >= 4
            ]
        if include_capture:
            result["_sample_capture"] = self._captureAuxiliarySample("carousel")
        return result

    def _processPendingAuxiliaryTeacherCaptures(self) -> None:
        now = time.time()
        ready: list[AuxiliaryTeacherCaptureRequest] = []
        with self._auxiliary_capture_lock:
            pending: list[AuxiliaryTeacherCaptureRequest] = []
            for request in self._auxiliary_capture_requests:
                if request.due_at <= now:
                    ready.append(request)
                else:
                    pending.append(request)
            self._auxiliary_capture_requests = pending
        for request in ready:
            self._executeAuxiliaryTeacherCapture(request)

    def _executeAuxiliaryTeacherCapture(self, request: AuxiliaryTeacherCaptureRequest) -> None:
        if not self._sampleCollectionEnabledForRole(request.role):
            return

        frame_raw: np.ndarray | None = (
            request.frame_snapshot.copy()
            if isinstance(request.frame_snapshot, np.ndarray)
            else None
        )
        if frame_raw is None:
            capture = self.getCaptureThreadForRole(request.role)
            frame = capture.latest_frame if capture is not None else None
            if frame is None:
                self.gc.logger.info(
                    f"Auxiliary teacher capture skipped for {request.role}: no live frame available"
                )
                return
            frame_raw = frame.raw.copy()

        sample_capture = self._captureAuxiliarySampleFromFrame(request.role, frame_raw)
        input_image = sample_capture.get("input_image")
        source_frame = sample_capture.get("frame")
        if not isinstance(input_image, np.ndarray) or input_image.size == 0:
            self.gc.logger.info(
                f"Auxiliary teacher capture skipped for {request.role}: no cropped input image"
            )
            return

        detection, rate_limited = self._runGeminiDetectionRequestWithThrottle(
            DetectionRequest(
                scope=request.scope,
                role=request.role,
                frame=input_image,
                force=True,
                metadata={"background": True, "capture_reason": request.capture_reason},
            )
        )
        if rate_limited:
            retry_delay = self._openrouterRetryDelay()
            with self._auxiliary_capture_lock:
                self._auxiliary_capture_requests.append(
                    replace(request, due_at=time.time() + retry_delay)
                )
            self.gc.logger.info(
                "Deferred auxiliary teacher capture for %s by %.2fs to respect OpenRouter rate limits",
                request.role,
                retry_delay,
            )
            return

        message = "Gemini teacher capture found no piece."
        if detection is not None and detection.bbox is not None:
            message = "Gemini teacher capture found candidate pieces."
        elif request.scope == "feeder":
            detector = self._feeder_gemini_detectors.get(request.role)
            if detector is not None and isinstance(detector._last_error, str) and detector._last_error:
                message = f"Gemini teacher capture error: {detector._last_error}"
        elif request.scope == "carousel":
            detector = self._carousel_gemini_detector
            if detector is not None and isinstance(detector._last_error, str) and detector._last_error:
                message = f"Gemini teacher capture error: {detector._last_error}"

        try:
            from server.classification_training import getClassificationTrainingManager

            getClassificationTrainingManager().saveAuxiliaryDetectionCapture(
                source=request.source,
                source_role=request.role,
                detection_scope=request.scope,
                capture_reason=request.capture_reason,
                detection_algorithm="gemini_sam",
                detection_openrouter_model=self._openRouterModelForScope(request.scope),
                detection_found=bool(detection is not None and detection.bbox is not None),
                detection_bbox=(
                    list(detection.bbox)
                    if detection is not None and detection.bbox is not None
                    else None
                ),
                detection_candidate_bboxes=(
                    [list(candidate) for candidate in detection.bboxes]
                    if detection is not None
                    else []
                ),
                detection_bbox_count=len(detection.bboxes) if detection is not None else 0,
                detection_score=self._detectionScoreValue(detection),
                detection_message=message,
                input_image=input_image,
                source_frame=source_frame if isinstance(source_frame, np.ndarray) else None,
                extra_metadata={
                    "teacher_capture": True,
                    "teacher_capture_requested_at": request.created_at,
                    "teacher_capture_due_at": request.due_at,
                    "teacher_capture_used_frozen_frame": bool(
                        isinstance(request.frame_snapshot, np.ndarray)
                    ),
                    "trigger_algorithm": request.trigger_algorithm,
                    **request.trigger_metadata,
                },
            )
        except Exception as exc:
            self.gc.logger.warning(
                f"Failed to archive auxiliary teacher capture for {request.role}: {exc}"
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

    def _auxiliaryDetectionLoop(self) -> None:
        while not self._aux_detection_stop.is_set():
            try:
                self._refreshAuxiliaryDetections()
                self._processPendingAuxiliaryTeacherCaptures()
            except Exception as exc:
                self.gc.logger.warning(f"Auxiliary detection loop error: {exc}")
            self._aux_detection_stop.wait(AUXILIARY_DETECTION_LOOP_INTERVAL_S)

    @property
    def feeding_platform_corners(self) -> List[Tuple[float, float]] | None:
        return self._carousel_polygon

    @property
    def classification_bottom_frame(self) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed("classification_bottom")
        return feed.get_frame(annotated=True) if feed else None

    @property
    def classification_top_frame(self) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed("classification_top")
        return feed.get_frame(annotated=True) if feed else None

    def _annotateClassificationFrame(
        self, frame: CameraFrame, cam: str, heatmap: HeatmapDiff | None
    ) -> CameraFrame:
        """Legacy helper — still used by captureClassificationCrops."""
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
        return self._camera_service.get_capture_thread_for_role(camera_name)

    def setCameraSourceForRole(
        self,
        camera_name: str,
        source: int | str | None,
    ) -> bool:
        return self._camera_service.set_camera_source_for_role(camera_name, source)

    def setPictureSettingsForRole(
        self,
        camera_name: str,
        settings: CameraPictureSettings,
    ) -> bool:
        return self._camera_service.set_picture_settings_for_role(camera_name, settings)

    def setDeviceSettingsForRole(
        self,
        camera_name: str,
        settings: dict[str, int | float | bool] | None,
        *,
        persist: bool = False,
    ) -> dict[str, int | float | bool] | None:
        return self._camera_service.set_device_settings_for_role(camera_name, settings, persist=persist)

    def getDeviceSettingsForRole(
        self,
        camera_name: str,
    ) -> dict[str, int | float | bool] | None:
        return self._camera_service.get_device_settings_for_role(camera_name)

    def describeDeviceControlsForRole(
        self,
        camera_name: str,
    ) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]] | None:
        return self._camera_service.describe_device_controls_for_role(camera_name)

    def setColorProfileForRole(
        self,
        camera_name: str,
        profile: CameraColorProfile | None,
    ) -> bool:
        return self._camera_service.set_color_profile_for_role(camera_name, profile)

    def getFrame(self, camera_name: str) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed(camera_name)
        return feed.get_frame(annotated=True) if feed else None

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

        _, buffer = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode("utf-8")

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

    def _classificationZoneBBoxFromFrame(
        self,
        cam: str,
        frame: CameraFrame | None,
    ) -> Tuple[int, int, int, int] | None:
        if cam not in {"top", "bottom"}:
            return None
        if frame is None:
            return None

        frame_h, frame_w = frame.raw.shape[:2]
        polygon = self._classification_masks.get(cam)
        if polygon is None or len(polygon) < 3:
            return (0, 0, int(frame_w), int(frame_h))

        scaled_polygon = self._scalePolygon(polygon, frame_w, frame_h)
        x, y, w, h = cv2.boundingRect(scaled_polygon)
        x2 = min(frame_w, x + w)
        y2 = min(frame_h, y + h)
        if x2 <= x or y2 <= y:
            return None
        return (int(x), int(y), int(x2), int(y2))

    def getClassificationZoneBBox(
        self,
        cam: str,
        *,
        frame: CameraFrame | None = None,
    ) -> Tuple[int, int, int, int] | None:
        if frame is None:
            capture = self._classification_top_capture if cam == "top" else self._classification_bottom_capture
            frame = capture.latest_frame if capture is not None else None
        return self._classificationZoneBBoxFromFrame(cam, frame)

    def _classificationZoneCropFromFrame(
        self,
        cam: str,
        frame: CameraFrame | None,
    ) -> Optional[np.ndarray]:
        if cam not in {"top", "bottom"}:
            return None
        if frame is None:
            return None

        zone_bbox = self._classificationZoneBBoxFromFrame(cam, frame)
        if zone_bbox is None:
            return None
        x, y, x2, y2 = zone_bbox
        masked = self._maskToRegion(frame.raw, cam)
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

    @property
    def _active_cameras(self) -> List[CameraName]:
        return self._camera_service.active_cameras
