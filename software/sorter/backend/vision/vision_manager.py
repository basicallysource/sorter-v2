from typing import Optional, List, Dict, Tuple, Union, cast, Any
from pathlib import Path
import base64
import time
import threading
from dataclasses import dataclass, field, is_dataclass, replace
import cv2
import numpy as np

from global_config import GlobalConfig, RegionProviderType
from irl.config import IRLConfig, IRLInterface, CameraColorProfile, CameraPictureSettings, mkCameraConfig
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from defs.channel import ChannelDetection, PolygonChannel
from blob_manager import (
    VideoRecorder,
    getCarouselDetectionConfig,
    getClassificationChannelDetectionConfig,
    getClassificationDetectionConfig,
    getClassificationPolygons,
    getFeederDetectionConfig,
)
from role_aliases import CLASSIFICATION_CHANNEL_ROLE
from .camera import CaptureThread
from .burst_store import BurstFrameStore
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


# Minimum seconds between consecutive ``hive:*`` inferences per (scope, role).
# Live frame-encode runs at ~10 Hz and each ONNX inference is ~30-50 ms on CPU;
# without this guard the encode thread serializes and the dashboard stream
# stutters. Override via ``SORTER_HIVE_INFERENCE_INTERVAL_S`` env var for tuning.
import os as _os
HIVE_INFERENCE_MIN_INTERVAL_S: float = float(
    _os.environ.get("SORTER_HIVE_INFERENCE_INTERVAL_S", "0.2")
)


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
        self._feeder_detection_algorithm_by_role: Dict[str, FeederDetectionAlgorithm] = {
            "c_channel_2": "mog2",
            "c_channel_3": "mog2",
            "carousel": "mog2",
        }
        self._feeder_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
        self._feeder_sample_collection_enabled: bool = False
        self._feeder_sample_collection_enabled_by_role: Dict[str, bool] = {
            "c_channel_2": False,
            "c_channel_3": False,
            "carousel": False,
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
        self._hive_ml_processors: Dict[str, Any] = {}
        from .tracking import build_feeder_tracker_system, TrackedPiece, DropZoneBurstCollector  # noqa: F401
        (
            self._piece_handoff_manager,
            self._feeder_trackers,
            self._piece_history,
        ) = build_feeder_tracker_system(
            roles=self._feederTrackerRoles(),
            exit_observer=getattr(gc.runtime_stats, "observeChannelExit", None),
            ghost_reject_observer=getattr(gc.runtime_stats, "observeHandoffGhostReject", None),
            embedding_rebind_observer=getattr(gc.runtime_stats, "observeHandoffEmbeddingRebind", None),
            stale_pending_observer=getattr(gc.runtime_stats, "observeHandoffStalePendingDropped", None),
            id_switch_suspect_observer=getattr(gc.runtime_stats, "observeTrackerIdSwitchSuspect", None),
        )
        self._drop_zone_burst_collector = DropZoneBurstCollector(self._piece_history)
        # Phase 3: segment-archival side-channel. VisionManager creates the
        # buffer before piece_transport exists (transport lives inside the
        # classification-channel runtime), so we stash ``None`` here and
        # let ``attachPieceTransportForSegmentArchival`` set it later. The
        # callback is thread-safe: it only reads ``_piece_transport`` via
        # a local and uses piece_transport's own locking.
        self._piece_transport: Any | None = None
        self._piece_history.set_on_segment_archived(self._archive_segment_to_dossier)
        # Fresh burst store for the C3→C4 drop-zone "fashion-shoot" feature.
        # Pre-event frames from the c_channel_3 + carousel capture-thread ring
        # buffers are drained at trigger time; post-event frames are merged in
        # 2 s later via a threading.Timer.
        self._burst_store = BurstFrameStore(max_pieces=50)
        self._burst_timers: Dict[int, threading.Timer] = {}
        self._burst_lock = threading.Lock()
        self._feeder_track_cache: Dict[str, Tuple[float, list]] = {}
        self._classification_channel_zone_overlay: list[dict[str, Any]] = []
        self._classification_channel_zone_overlay_meta: dict[str, Any] = {}
        # Gate: tracker updates only happen while the sorter is actually
        # running. Toggled from SorterController.resume/pause/stop so we
        # don't accumulate tracks while the operator is calibrating or idle.
        self._feeder_tracker_active: bool = False
        self._aux_detection_stop = threading.Event()
        self._aux_detection_thread: threading.Thread | None = None
        self._auxiliary_capture_requests: list[AuxiliaryTeacherCaptureRequest] = []
        self._auxiliary_capture_lock = threading.Lock()
        self._aux_feeder_refresh_cursor: int = 0
        self._openrouter_request_lock = threading.Lock()
        self._openrouter_next_allowed_at: float = 0.0
        self._openrouter_semaphore = threading.BoundedSemaphore(OPENROUTER_MAX_CONCURRENCY)

        self._started = False

    def _usesClassificationChannelSetup(self) -> bool:
        irl_config = getattr(self, "_irl_config", None)
        machine_setup = getattr(irl_config, "machine_setup", None)
        return bool(
            machine_setup is not None
            and getattr(machine_setup, "uses_classification_channel", False)
        )

    def _feederTrackerRoles(self) -> tuple[str, ...]:
        if self._usesClassificationChannelSetup():
            return ("c_channel_2", "c_channel_3", "carousel")
        return ("c_channel_2", "c_channel_3")

    def _publicFeederRole(self, role: str) -> str:
        if role == "carousel" and self._usesClassificationChannelSetup():
            return CLASSIFICATION_CHANNEL_ROLE
        return role

    def _internalFeederRole(self, role: str | None) -> str | None:
        if role == CLASSIFICATION_CHANNEL_ROLE:
            return "carousel"
        return role

    def _channelPolygonKeyForRole(self, role: str) -> str | None:
        if role == "c_channel_2":
            return "second_channel"
        if role == "c_channel_3":
            return "third_channel"
        if role == "carousel" and self._usesClassificationChannelSetup():
            return "classification_channel"
        return None

    def _channelAngleKeyForPolygonKey(self, polygon_key: str) -> str | None:
        if polygon_key == "second_channel":
            return "second"
        if polygon_key == "third_channel":
            return "third"
        if polygon_key == "classification_channel":
            return "classification_channel"
        return None

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
            ClassificationChannelZoneOverlay,
            IgnoredRegionOverlay,
            TrackOverlay,
        )
        from vision.overlays.telemetry import TelemetryOverlay

        _ROLE_TO_POLY_KEY = {
            "c_channel_2": "second_channel",
            "c_channel_3": "third_channel",
            "carousel": "classification_channel" if self._usesClassificationChannelSetup() else "carousel",
        }

        if self._camera_layout == "split_feeder":
            # Per-channel feeds
            for role in self._feederTrackerRoles():
                feed = self._camera_service.get_feed(role)
                if feed is None:
                    continue
                feed.clear_overlays()
                poly_key = _ROLE_TO_POLY_KEY.get(role)
                if poly_key:
                    feed.add_overlay(ChannelRegionOverlay(self._region_provider, poly_key))
                feeder_algo = self.getFeederDetectionAlgorithm(role)
                if self._isDynamicDetectionAlgorithm(feeder_algo):
                    detection_cache: dict[str, object] = {"frame_ts": None, "result": None}

                    def _ensure_detection(r=role, cache=detection_cache):
                        capture = self.getCaptureThreadForRole(r)
                        frame = capture.latest_frame if capture is not None else None
                        frame_ts = frame.timestamp if frame is not None else None
                        if cache["frame_ts"] != frame_ts:
                            cache["frame_ts"] = frame_ts
                            cache["result"] = self._getFeederDynamicDetection(
                                r, force=False
                            )
                        return cache["result"]

                    # TrackOverlay replaces DynamicDetectionOverlay. Triggering
                    # _getFeederDynamicDetection on each render tick is what
                    # keeps the Hive inference (throttled) + tracker cache warm;
                    # the overlay itself reads the freshly-updated track list.
                    def _tracks_for(r=role):
                        _ensure_detection(r)
                        return self.getFeederTracks(r)

                    if role == "carousel" and self._usesClassificationChannelSetup():
                        feed.add_overlay(DynamicDetectionOverlay(_ensure_detection))
                    feed.add_overlay(
                        IgnoredRegionOverlay(
                            lambda r=role: self.getFeederIgnoredDetectionOverlayData(r)
                        )
                    )
                    feed.add_overlay(TrackOverlay(_tracks_for))
                    if role == "carousel" and self._usesClassificationChannelSetup():
                        feed.add_overlay(
                            ClassificationChannelZoneOverlay(
                                self.getClassificationChannelZoneOverlayData
                            )
                        )
                else:
                    detector = self._per_channel_detectors.get(role)
                    analysis = self._per_channel_analysis.get(role)
                    if detector is not None and analysis is not None:
                        feed.add_overlay(DetectorOverlay(detector, analysis.getDetections))
            if not self._usesClassificationChannelSetup():
                carousel_feed = self._camera_service.get_feed("carousel")
                if carousel_feed is not None:
                    carousel_feed.clear_overlays()
                    carousel_feed.add_overlay(ChannelRegionOverlay(self._region_provider, "carousel"))
                    carousel_algo = self.getCarouselDetectionAlgorithm()
                    if carousel_algo == "gemini_sam" or carousel_algo.startswith("hive:"):
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

        # Telemetry overlay on every feed — res / fps / exposure / gain /
        # focus / wb / auto-modes rendered bottom-right. Category "telemetry"
        # so the frontend can hide it via show_regions=false style filters.
        for role, feed in self._camera_service.feeds.items():
            if feed is None:
                continue

            def _stats_for(r=role):
                capture = self.getCaptureThreadForRole(r)
                if capture is None:
                    return None
                try:
                    return capture.getTelemetrySnapshot()
                except Exception:
                    return None

            feed.add_overlay(TelemetryOverlay(_stats_for))

    def start(self) -> None:
        self._started = True
        # CameraService.start() already started capture threads + frame encode loop
        self._region_provider.start()
        # Populate handoff zones from saved polygons so the tracker can
        # inherit IDs across cameras even before the user triggers a Home cycle.
        try:
            self.reloadPolygons()
        except Exception as exc:
            self.gc.logger.warning(f"reloadPolygons at start failed: {exc}")
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
        by_role = (
            config.get("algorithm_by_role")
            if isinstance(config, dict) and isinstance(config.get("algorithm_by_role"), dict)
            else None
        )
        model = config.get("openrouter_model") if isinstance(config, dict) else None
        self._feeder_openrouter_model = normalize_openrouter_model(model)
        enabled = config.get("sample_collection_enabled") if isinstance(config, dict) else None
        sample_collection_by_role = (
            config.get("sample_collection_enabled_by_role")
            if isinstance(config, dict) and isinstance(config.get("sample_collection_enabled_by_role"), dict)
            else None
        )
        resolved_algorithms: Dict[str, FeederDetectionAlgorithm] = {}
        resolved_by_role: Dict[str, bool] = {}
        for role in self._feederTrackerRoles():
            public_role = self._publicFeederRole(role)
            role_algorithm = (
                by_role.get(role) if isinstance(by_role, dict) and role in by_role else None
            )
            if role_algorithm is None and isinstance(by_role, dict):
                role_algorithm = by_role.get(public_role)
            if role_algorithm is None:
                role_algorithm = candidate
            resolved_algorithms[role] = self._normalizeFeederDetectionAlgorithm(role_algorithm)
            role_value = (
                sample_collection_by_role.get(role)
                if isinstance(sample_collection_by_role, dict)
                else enabled
            )
            if role_value is None and isinstance(sample_collection_by_role, dict):
                role_value = sample_collection_by_role.get(public_role)
            resolved_by_role[role] = False if role_value is None else bool(role_value)
        self._feeder_detection_algorithm_by_role = resolved_algorithms
        self._feeder_sample_collection_enabled_by_role = resolved_by_role
        self._feeder_sample_collection_enabled = any(resolved_by_role.values())

    def _loadCarouselDetectionConfig(self) -> None:
        config = (
            getClassificationChannelDetectionConfig()
            if self._usesClassificationChannelSetup()
            else getCarouselDetectionConfig()
        )
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
    def _isDynamicDetectionAlgorithm(algorithm: str | None) -> bool:
        return bool(
            isinstance(algorithm, str)
            and (algorithm == "gemini_sam" or algorithm.startswith("hive:"))
        )

    def _feederRoleUsesDynamicDetection(self, role: str) -> bool:
        return self._isDynamicDetectionAlgorithm(self.getFeederDetectionAlgorithm(role))

    @staticmethod
    def _detectionScoreValue(
        detection: ClassificationDetectionResult | None,
        *,
        default: float | None = None,
    ) -> float | None:
        if detection is None or detection.score is None:
            return default
        return float(detection.score)

    def getFeederDetectionAlgorithm(self, role: str | None = None) -> FeederDetectionAlgorithm:
        normalized_role = self._internalFeederRole(role)
        if normalized_role in self._feederTrackerRoles():
            return self._normalizeFeederDetectionAlgorithm(
                self._feeder_detection_algorithm_by_role.get(normalized_role)
            )
        return self._normalizeFeederDetectionAlgorithm(self._feeder_detection_algorithm)

    def getFeederDetectionAlgorithms(self) -> Dict[str, FeederDetectionAlgorithm]:
        return {
            self._publicFeederRole(role): self.getFeederDetectionAlgorithm(role)
            for role in self._feederTrackerRoles()
        }

    def getFeederOpenRouterModel(self) -> str:
        return normalize_openrouter_model(self._feeder_openrouter_model)

    def supportsFeederSampleCollection(self, role: str | None = None) -> bool:
        normalized_role = self._internalFeederRole(role)
        if self._camera_layout != "split_feeder":
            return False
        if normalized_role == "c_channel_2":
            return self._c_channel_2_capture is not None
        if normalized_role == "c_channel_3":
            return self._c_channel_3_capture is not None
        if normalized_role == "carousel":
            return self._usesClassificationChannelSetup() and self._carousel_capture is not None
        return any(
            self.supportsFeederSampleCollection(channel_role)
            for channel_role in self._feederTrackerRoles()
        )

    def isFeederSampleCollectionEnabled(self, role: str | None = None) -> bool:
        normalized_role = self._internalFeederRole(role)
        if normalized_role in self._feederTrackerRoles():
            return self.supportsFeederSampleCollection(normalized_role) and bool(
                self._feeder_sample_collection_enabled_by_role.get(normalized_role)
            )
        if not self.supportsFeederSampleCollection():
            return False
        return any(
            self.isFeederSampleCollectionEnabled(channel_role)
            for channel_role in self._feederTrackerRoles()
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
        self._hive_ml_processors.clear()
        self._stopClassificationAnalysis()
        self._initOverlays()
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

    def setFeederDetectionAlgorithm(
        self,
        algorithm: FeederDetectionAlgorithm,
        role: str | None = None,
    ) -> None:
        if not scope_supports_detection_algorithm("feeder", algorithm):
            raise ValueError(f"Unsupported feeder detection algorithm '{algorithm}'")
        normalized = self._normalizeFeederDetectionAlgorithm(algorithm)
        normalized_role = self._internalFeederRole(role)
        if normalized_role is not None and normalized_role not in self._feederTrackerRoles():
            raise ValueError(f"Unsupported feeder role '{role}'")
        if normalized_role in self._feederTrackerRoles():
            self._feeder_detection_algorithm_by_role[normalized_role] = normalized
        else:
            self._feeder_detection_algorithm = normalized
            for channel_role in self._feederTrackerRoles():
                self._feeder_detection_algorithm_by_role[channel_role] = normalized
        self._feeder_dynamic_detection_cache.clear()
        self._hive_ml_processors.clear()
        self.resetFeederTrackers()
        self._initOverlays()

    def setFeederOpenRouterModel(self, model: str) -> str:
        normalized = normalize_openrouter_model(model)
        self._feeder_openrouter_model = normalized
        self._feeder_dynamic_detection_cache.clear()
        for detector in self._feeder_gemini_detectors.values():
            detector.setOpenRouterModel(normalized)
        return normalized

    def setFeederSampleCollectionEnabled(self, enabled: bool, role: str | None = None) -> bool:
        feeder_roles = self._feederTrackerRoles()
        normalized_role = self._internalFeederRole(role)
        if normalized_role is not None and normalized_role not in feeder_roles:
            raise ValueError(f"Unsupported feeder role '{role}'")
        if normalized_role in feeder_roles:
            self._feeder_sample_collection_enabled_by_role[normalized_role] = (
                bool(enabled) if self.supportsFeederSampleCollection(normalized_role) else False
            )
            self._feeder_sample_collection_enabled = any(
                self._feeder_sample_collection_enabled_by_role.values()
            )
            return self._feeder_sample_collection_enabled_by_role[normalized_role]
        resolved_enabled = bool(enabled) if self.supportsFeederSampleCollection() else False
        for channel_role in feeder_roles:
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
        self._hive_ml_processors.clear()
        self._initOverlays()

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
        polygon_key = "classification_channel" if self._usesClassificationChannelSetup() else "carousel"
        carousel_pts = polygon_data.get(polygon_key)
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
            # Configure handoff zones right away so the tracker works even
            # before the user runs System Home.
            self._configureHandoffZonesFromSaved(polygon_data, saved_res)

    def _configureChannelGeometryFromSaved(self, saved: dict) -> None:
        """Push channel center + inner/outer radii into feeder trackers.

        The tracker uses this to slice the piece's trajectory into angular
        sectors and snapshot each sector as the piece passes through it.
        Radii/center are scaled from the saved capture resolution to each
        role's live camera resolution.
        """
        try:
            from subsystems.feeder.analysis import parseSavedChannelArcZones
        except Exception:
            return
        saved_res = saved.get("resolution") or [1920, 1080]
        try:
            src_w = int(saved_res[0])
            src_h = int(saved_res[1])
        except (TypeError, ValueError):
            return
        if src_w <= 0 or src_h <= 0:
            return
        channel_angles = saved.get("channel_angles") or {}
        arc_params = saved.get("arc_params") or {}
        role_to_key = {"c_channel_2": "second", "c_channel_3": "third"}
        if self._usesClassificationChannelSetup():
            role_to_key["carousel"] = "classification_channel"
        for role, channel_key in role_to_key.items():
            arc = parseSavedChannelArcZones(channel_key, channel_angles, arc_params)
            if arc is None or arc.outer_radius <= arc.inner_radius or arc.inner_radius <= 0:
                continue
            tracker = self._feeder_trackers.get(role)
            if tracker is None:
                continue
            capture = self.getCaptureThreadForRole(role)
            frame = capture.latest_frame if capture is not None else None
            if frame is None:
                sx = sy = 1.0
            else:
                cam_h, cam_w = frame.raw.shape[:2]
                sx = cam_w / src_w
                sy = cam_h / src_h
            cx = arc.center[0] * sx
            cy = arc.center[1] * sy
            # Mean scale for radii — the channel is circular, so sx≈sy in practice.
            rs = (sx + sy) / 2.0
            r_in = arc.inner_radius * rs
            r_out = arc.outer_radius * rs
            tracker.set_channel_geometry((cx, cy), r_in, r_out, sector_count=18)

    def _configureHandoffZonesFromSaved(self, polygon_data: dict, saved_res) -> None:
        """Set up c_channel_2 exit / c_channel_3 entry zones from saved polygons.

        Polygon coordinates are stored in the capture resolution written to
        disk (``saved_res``); the active camera may run at a different
        resolution (e.g. 1280×720 on the live feed while the stored polygon
        is in 1920×1080). Rescale per role using the role's current capture.
        """
        try:
            src_w, src_h = int(saved_res[0]), int(saved_res[1])
        except (TypeError, ValueError):
            return
        if src_w <= 0 or src_h <= 0:
            return
        role_to_key = {"c_channel_2": "second_channel", "c_channel_3": "third_channel"}
        if self._usesClassificationChannelSetup():
            role_to_key["carousel"] = "classification_channel"

        def _rect_to_polygon(x1, y1, x2, y2):
            return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

        def _role_scale(role: str) -> tuple[float, float]:
            capture = self.getCaptureThreadForRole(role)
            frame = capture.latest_frame if capture is not None else None
            if frame is None:
                return 1.0, 1.0
            cam_h, cam_w = frame.raw.shape[:2]
            return cam_w / src_w, cam_h / src_h

        for role, key in role_to_key.items():
            pts = polygon_data.get(key)
            if not isinstance(pts, list) or len(pts) < 3:
                continue
            try:
                poly = np.array([[float(p[0]), float(p[1])] for p in pts], dtype=np.int32)
            except (TypeError, ValueError):
                continue
            x, y, w, h = cv2.boundingRect(poly)
            sx, sy = _role_scale(role)
            if role == "c_channel_2":
                ex1 = (x + w // 2) * sx
                self._piece_handoff_manager.set_zones(
                    role,
                    exit_polygon=_rect_to_polygon(
                        ex1, y * sy, (x + w) * sx, (y + h) * sy
                    ),
                )
            elif role == "c_channel_3":
                en2 = (x + w // 2) * sx
                self._piece_handoff_manager.set_zones(
                    role,
                    entry_polygon=_rect_to_polygon(
                        x * sx, y * sy, en2, (y + h) * sy
                    ),
                )
                if self._usesClassificationChannelSetup():
                    ex1 = (x + w // 2) * sx
                    self._piece_handoff_manager.set_zones(
                        role,
                        exit_polygon=_rect_to_polygon(
                            ex1, y * sy, (x + w) * sx, (y + h) * sy
                        ),
                    )
            elif role == "carousel":
                en2 = (x + w // 2) * sx
                self._piece_handoff_manager.set_zones(
                    role,
                    entry_polygon=_rect_to_polygon(
                        x * sx, y * sy, en2, (y + h) * sy
                    ),
                )

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
            self.gc.logger.warn("Channel polygons not found. Draw them from the Settings → Zones editor.")
            return False

        polygon_data = saved.get("polygons", {})
        raw_arc_params = saved.get("arc_params", {})
        polys: Dict[str, np.ndarray] = {}
        inner_polys: Dict[str, np.ndarray] = {}
        channel_polygon_keys = ["second_channel", "third_channel"]
        if self._usesClassificationChannelSetup():
            channel_polygon_keys.append("classification_channel")
        for key in channel_polygon_keys:
            pts = polygon_data.get(key)
            channel_key = self._channelAngleKeyForPolygonKey(key)
            if channel_key is None:
                continue
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
            self.gc.logger.warn("Channel polygons empty. Draw them from the Settings → Zones editor.")
            return False

        self._channel_polygons = polys
        self._channel_angles = saved.get("channel_angles", {})
        # Tracker reset + zones — new polygons mean we can't trust old track positions.
        self.resetFeederTrackers()
        self._configureFeederHandoffZones(polys)
        self._configureChannelGeometryFromSaved(saved)

        channel_steppers = {
            "second_channel": self._irl.c_channel_2_rotor_stepper,
            "third_channel": self._irl.c_channel_3_rotor_stepper,
        }
        if self._usesClassificationChannelSetup():
            channel_steppers["classification_channel"] = self._irl.carousel_stepper

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
            channel_key = self._channelAngleKeyForPolygonKey(key)
            if channel_key is None:
                continue
            arc = parseSavedChannelArcZones(channel_key, self._channel_angles, raw_arc_params)
            drop_sections, exit_sections = zoneSectionsForChannel(
                2 if channel_key == "second" else 3 if channel_key == "third" else 4,
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
        if self._usesClassificationChannelSetup():
            channel_map["classification_channel"] = ("carousel", self._carousel_capture)

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

            channel_key = self._channelAngleKeyForPolygonKey(key)
            if channel_key is None:
                continue

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
                2 if channel_key == "second" else 3 if channel_key == "third" else 4,
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
                    self.gc.logger.warn(f"Classification {cam_key} {mode} baseline not found. Capture a baseline from the Settings → Classification page.")
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

        # Hive inference is local but CPU-bound; throttle on the live path so
        # the frame-encode thread doesn't serialize a ~40ms ONNX call per frame.
        if algorithm.startswith("hive:") and not force:
            if cached is not None:
                last_ts, last_det = cached
                if frame.timestamp - float(last_ts) < HIVE_INFERENCE_MIN_INTERVAL_S:
                    return last_det

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
        elif algorithm.startswith("hive:"):
            detection = self._runHiveDetection(algorithm, frame.raw, scope="classification", role=cam)

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
        # Clamp to frame bounds. Arc-derived channel polygons (e.g. third_channel)
        # can extend above y=0; numpy slicing with negative start would wrap
        # from the end of the array and collapse the crop to 1-2 rows.
        x = max(0, x)
        y = max(0, y)
        x2 = min(w, x + bw)
        y2 = min(h, y + bh)
        if x2 <= x or y2 <= y:
            return None
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
        masked = np.where(mask[:, :, np.newaxis] == 255, frame, 255)
        return masked[y:y2, x:x2].copy(), (int(x), int(y))

    def _channelInfoForRole(self, role: str) -> PolygonChannel | None:
        detector = getattr(self, "_per_channel_detectors", {}).get(role)
        if detector is None:
            key = self._channelPolygonKeyForRole(role)
            capture = self.getCaptureThreadForRole(role)
            frame = capture.latest_frame if capture is not None else None
            if key is None or frame is None:
                return None
            h, w = frame.raw.shape[:2]
            polygon = self._loadSavedPolygon(key, w, h)
            if polygon is None or len(polygon) < 3:
                return None
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
            channel_id = 2 if key == "second_channel" else 3 if key == "third_channel" else 4
            center = tuple(np.mean(polygon, axis=0).tolist())
            angle_key = self._channelAngleKeyForPolygonKey(key)
            return PolygonChannel(
                channel_id=channel_id,
                polygon=polygon.astype(np.int32),
                center=center,
                radius1_angle_image=float(
                    getattr(self, "_channel_angles", {}).get(angle_key or "", 0.0)
                ),
                mask=mask,
            )
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

    def _isPointInsideChannelMask(
        self,
        channel: PolygonChannel | None,
        point: tuple[float, float],
    ) -> bool:
        if channel is None:
            return True
        mask = getattr(channel, "mask", None)
        if not isinstance(mask, np.ndarray) or mask.ndim < 2:
            return True
        x = int(round(float(point[0])))
        y = int(round(float(point[1])))
        if x < 0 or y < 0 or y >= mask.shape[0] or x >= mask.shape[1]:
            return False
        return bool(mask[y, x] > 0)

    def _bboxCenterPoint(
        self,
        bbox: tuple[int, int, int, int],
    ) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0)

    def _isFeederDetectionBboxPlausibleForRole(
        self,
        role: str,
        bbox: tuple[int, int, int, int],
    ) -> bool:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        if width <= 0 or height <= 0:
            return False
        if role == "carousel":
            # Classification-channel ghosts frequently show up as paper-thin
            # strips on the frame edge. Real LEGO parts under the hood are
            # much larger than that, so reject implausibly skinny boxes.
            if min(width, height) < 10:
                return False
            if (width * height) < 180:
                return False
        return True

    def _isFeederDetectionBboxIgnoredForRole(
        self,
        role: str,
        bbox: tuple[int, int, int, int],
    ) -> bool:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        area = width * height
        cx, cy = self._bboxCenterPoint(bbox)
        capture = self.getCaptureThreadForRole(role)
        frame = (
            capture.latest_frame.raw
            if capture is not None and capture.latest_frame is not None
            else None
        )
        if frame is None:
            return False
        frame_h, frame_w = frame.shape[:2]
        if frame_w <= 0 or frame_h <= 0:
            return False
        cx_norm = float(cx) / float(frame_w)
        cy_norm = float(cy) / float(frame_h)
        for spec in self._ignoredFeederDetectionZoneSpecs(role):
            if not (
                float(spec["x1"]) <= cx_norm <= float(spec["x2"])
                and float(spec["y1"]) <= cy_norm <= float(spec["y2"])
            ):
                continue
            min_area = spec.get("min_area")
            max_area = spec.get("max_area")
            if min_area is not None and area < int(min_area):
                continue
            if max_area is not None and area > int(max_area):
                continue
            return True
        return False

    def _ignoredFeederDetectionZoneSpecs(self, role: str) -> list[dict[str, object]]:
        return []

    def _trackerIgnoredStaticRegions(
        self,
        role: str,
        *,
        timestamp: float | None = None,
    ) -> list[dict[str, object]]:
        normalized_role = self._internalFeederRole(role)
        tracker = getattr(self, "_feeder_trackers", {}).get(normalized_role)
        if tracker is None:
            return []
        accessor = getattr(tracker, "get_ignored_static_regions", None)
        if accessor is None:
            return []
        try:
            regions = accessor(timestamp=timestamp)
        except TypeError:
            regions = accessor()
        except Exception:
            return []
        return [item for item in regions if isinstance(item, dict)]

    def _isFeederDetectionBboxIgnoredByTracker(
        self,
        role: str,
        bbox: Tuple[int, int, int, int],
        *,
        timestamp: float | None = None,
    ) -> bool:
        normalized_role = self._internalFeederRole(role)
        tracker = getattr(self, "_feeder_trackers", {}).get(normalized_role)
        if tracker is None:
            return False
        accessor = getattr(tracker, "is_detection_center_ignored", None)
        if accessor is None:
            return False
        try:
            return bool(
                accessor(
                    self._bboxCenterPoint(bbox),
                    timestamp=timestamp,
                )
            )
        except TypeError:
            try:
                return bool(accessor(self._bboxCenterPoint(bbox)))
            except Exception:
                return False
        except Exception:
            return False

    def getFeederIgnoredDetectionOverlayData(self, role: str) -> list[dict[str, object]]:
        capture = self.getCaptureThreadForRole(role)
        frame = capture.latest_frame.raw if capture is not None and capture.latest_frame is not None else None
        if frame is None:
            return []
        frame_timestamp = (
            float(capture.latest_frame.timestamp)
            if capture is not None and capture.latest_frame is not None
            else None
        )
        frame_h, frame_w = frame.shape[:2]
        data: list[dict[str, object]] = []
        for spec in self._ignoredFeederDetectionZoneSpecs(role):
            data.append(
                {
                    "label": spec.get("label") or "ignored",
                    "bbox": [
                        int(round(float(spec["x1"]) * frame_w)),
                        int(round(float(spec["y1"]) * frame_h)),
                        int(round(float(spec["x2"]) * frame_w)),
                        int(round(float(spec["y2"]) * frame_h)),
                    ],
                }
            )
        for region in self._trackerIgnoredStaticRegions(role, timestamp=frame_timestamp):
            center = region.get("center_px")
            radius_px = region.get("radius_px")
            if (
                not isinstance(center, (list, tuple))
                or len(center) != 2
                or not all(isinstance(value, (int, float)) for value in center)
                or not isinstance(radius_px, (int, float))
            ):
                continue
            cx = float(center[0])
            cy = float(center[1])
            radius = max(1.0, float(radius_px))
            data.append(
                {
                    "label": "ghost",
                    "bbox": [
                        max(0, int(round(cx - radius))),
                        max(0, int(round(cy - radius))),
                        min(frame_w, int(round(cx + radius))),
                        min(frame_h, int(round(cy + radius))),
                    ],
                }
            )
        return data

    def _filterFeederDetectionResultToChannel(
        self,
        role: str,
        detection: ClassificationDetectionResult | None,
    ) -> ClassificationDetectionResult | None:
        if detection is None:
            return None
        channel = self._channelInfoForRole(role)
        if channel is None:
            return detection
        kept = tuple(
            bbox
            for bbox in detection.bboxes
            if (
                self._isPointInsideChannelMask(channel, self._bboxCenterPoint(bbox))
                and self._isFeederDetectionBboxPlausibleForRole(role, bbox)
                and not self._isFeederDetectionBboxIgnoredForRole(role, bbox)
                and not self._isFeederDetectionBboxIgnoredByTracker(role, bbox)
            )
        )
        if kept == detection.bboxes:
            return detection
        updated_bbox = kept[0] if kept else None
        updated_found = bool(kept)
        if is_dataclass(detection):
            return replace(
                detection,
                bbox=updated_bbox,
                bboxes=kept,
                found=updated_found,
            )
        return type(detection)(
            **{
                **getattr(detection, "__dict__", {}),
                "bbox": updated_bbox,
                "bboxes": kept,
                "found": updated_found,
            }
        )

    def _filterLiveFeederTracksToChannel(
        self,
        role: str,
        tracks: list,
    ) -> list:
        channel = self._channelInfoForRole(role)
        if channel is None:
            return list(tracks)
        kept: list = []
        for track in tracks:
            center = getattr(track, "center", (0.0, 0.0))
            if not self._isPointInsideChannelMask(channel, center):
                continue
            bbox = getattr(track, "bbox", None)
            if (
                isinstance(bbox, (list, tuple))
                and len(bbox) >= 4
                and self._isFeederDetectionBboxIgnoredForRole(
                    role,
                    (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                )
            ):
                continue
            if (
                isinstance(bbox, (list, tuple))
                and len(bbox) >= 4
                and self._isFeederDetectionBboxIgnoredByTracker(
                    role,
                    (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                    timestamp=float(getattr(track, "last_seen_ts", 0.0) or 0.0),
                )
            ):
                continue
            kept.append(track)
        return kept

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

    def _getOrBuildHiveProcessor(self, algorithm_id: str):
        cached = self._hive_ml_processors.get(algorithm_id)
        if cached is not None:
            return cached
        from .detection_registry import detection_algorithm_definition
        from .ml import create_processor

        definition = detection_algorithm_definition(algorithm_id)
        if definition is None or definition.kind != "hive" or definition.model_path is None:
            return None
        try:
            processor = create_processor(
                model_path=definition.model_path,
                model_family=definition.model_family or "yolo",
                runtime=definition.runtime or "onnx",
                imgsz=int(definition.imgsz or 320),
            )
        except Exception as exc:
            self.gc.logger.warning("Failed to build Hive processor %s: %s", algorithm_id, exc)
            return None
        self._hive_ml_processors[algorithm_id] = processor
        return processor

    def _resolveZonePolygon(
        self,
        scope: DetectionScope,
        role: str,
        frame_shape: tuple[int, int],
    ) -> np.ndarray | None:
        """Return polygon as int32 ndarray in frame pixel coords, or None.

        Falls back to the saved polygons in ``blob_manager.getChannelPolygons()``
        when the in-memory state (per-channel detectors, carousel polygon) is
        still empty — that happens pre-home, before ``initFeederDetection`` has
        populated ``_per_channel_detectors`` / ``_carousel_polygon``.
        """
        h, w = frame_shape[:2]
        if scope == "classification":
            polygon = self._classification_masks.get(role)
            if polygon is None or len(polygon) < 3:
                return None
            scaled = self._scalePolygon(polygon, w, h)
            if scaled is None:
                return None
            return np.asarray(scaled, dtype=np.int32)

        if scope == "feeder":
            channel = self._channelInfoForRole(role)
            if channel is not None and channel.polygon is not None and len(channel.polygon) >= 3:
                return np.asarray(channel.polygon, dtype=np.int32)
            key = self._channelPolygonKeyForRole(role)
            if key is None:
                return None
            return self._loadSavedPolygon(key, w, h)

        if scope == "carousel":
            if self._carousel_polygon is not None and len(self._carousel_polygon) >= 3:
                return np.asarray(self._carousel_polygon, dtype=np.int32)
            return self._loadSavedPolygon("carousel", w, h)

        return None

    def _loadSavedPolygon(
        self,
        key: str,
        target_w: int,
        target_h: int,
    ) -> np.ndarray | None:
        """Read + scale a polygon from ``blob_manager.getChannelPolygons()``."""
        try:
            from blob_manager import getChannelPolygons
        except Exception:
            return None
        saved = getChannelPolygons()
        if not isinstance(saved, dict):
            return None
        polygon_data = saved.get("polygons") or {}
        pts = polygon_data.get(key)
        if not isinstance(pts, list) or len(pts) < 3:
            return None
        saved_res = saved.get("resolution") or [1920, 1080]
        try:
            src_w, src_h = int(saved_res[0]), int(saved_res[1])
        except (TypeError, ValueError):
            return None
        if src_w <= 0 or src_h <= 0:
            return None
        sx = float(target_w) / float(src_w)
        sy = float(target_h) / float(src_h)
        try:
            scaled = np.array(
                [[float(p[0]) * sx, float(p[1]) * sy] for p in pts],
                dtype=np.int32,
            )
        except (TypeError, ValueError):
            return None
        return scaled

    def _ensureHandoffZones(self) -> None:
        """Idempotent lazy-init of the handoff zones.

        Runs on each tracker update. Once zones are set for both roles, the
        method is a no-op. Waits until a real camera frame has arrived so we
        can scale from the saved polygon resolution to the live one.
        """
        entry_roles = set(self._piece_handoff_manager._entry_zones.keys())
        exit_roles = set(self._piece_handoff_manager._exit_zones.keys())
        required_ready = (
            ("c_channel_2" in exit_roles and "c_channel_3" in entry_roles)
            and (
                not self._usesClassificationChannelSetup()
                or ("c_channel_3" in exit_roles and "carousel" in entry_roles)
            )
        )
        if required_ready:
            return
        # Both cameras must have produced a frame so we know their resolution.
        for role in self._feederTrackerRoles():
            capture = self.getCaptureThreadForRole(role)
            if capture is None or capture.latest_frame is None:
                return
        try:
            from blob_manager import getChannelPolygons
            saved = getChannelPolygons()
        except Exception:
            return
        if not isinstance(saved, dict):
            return
        self._configureHandoffZonesFromSaved(
            saved.get("polygons") or {},
            saved.get("resolution") or [1920, 1080],
        )
        self._configureChannelGeometryFromSaved(saved)

    def setFeederTrackerActive(self, active: bool) -> None:
        """Enable/disable live piece tracking. Called by SorterController on
        lifecycle transitions so we only track pieces while the machine is
        actually running. Leaving the active state flushes live tracks into
        the history buffer via ``resetFeederTrackers`` so the sidebar keeps
        showing the last run's results.
        """
        new_state = bool(active)
        if new_state == self._feeder_tracker_active:
            return
        self._feeder_tracker_active = new_state
        if not new_state:
            try:
                self.resetFeederTrackers()
            except Exception:
                pass

    def _updateFeederTracker(
        self,
        role: str,
        detection: "ClassificationDetectionResult | None",
        timestamp: float,
        frame_bgr: "np.ndarray | None" = None,
    ) -> None:
        """Push the latest detection bboxes into the per-role SORT tracker.

        Runs for the configured feeder-tracker chain (normally
        ``c_channel_2``/``c_channel_3`` and, in classification-channel
        setup, also ``carousel``). Safe to call with
        ``detection=None`` — tracker still ticks with an empty detection list
        so coasting/death logic runs. ``frame_bgr`` is used to snapshot the
        first sighting of each new track for the history panel.
        """
        if not self._feeder_tracker_active:
            return
        tracker = self._feeder_trackers.get(role)
        if tracker is None:
            return
        self._ensureHandoffZones()
        if detection is None or not detection.bboxes:
            tracks = tracker.update([], [], float(timestamp), frame_bgr=frame_bgr)
        else:
            bboxes = [tuple(int(v) for v in bb) for bb in detection.bboxes]
            # Per-bbox scores aren't kept separately on the detection result —
            # use the overall score as a uniform proxy (good enough for the
            # score-threshold filter; Hungarian doesn't consume score).
            uniform_score = float(detection.score) if detection.score is not None else 0.9
            scores = [uniform_score] * len(bboxes)
            tracks = tracker.update(bboxes, scores, float(timestamp), frame_bgr=frame_bgr)
        self._feeder_track_cache[role] = (
            float(timestamp),
            self._filterLiveFeederTracksToChannel(role, tracks),
        )
        self._piece_handoff_manager.prune(float(timestamp))
        # Keep the rolling pre-buffer fed for drop-zone burst capture.
        if role == "carousel" and frame_bgr is not None:
            self._drop_zone_burst_collector.rolling_buffer.push(frame_bgr, float(timestamp))

    def getFeederTracks(self, role: str) -> list:
        cached = self._feeder_track_cache.get(role)
        if cached is None:
            return []
        return list(cached[1])

    def getFeederTrackAngularExtents(
        self,
        role: str,
        *,
        force_detection: bool = False,
    ) -> list:
        tracker = self._feeder_trackers.get(role)
        if tracker is None:
            return []
        if role in self._feederTrackerRoles():
            algorithm = self.getFeederDetectionAlgorithm(role)
            if self._isDynamicDetectionAlgorithm(algorithm):
                self._getFeederDynamicDetection(role, force=force_detection)
        if not hasattr(tracker, "get_live_track_angular_extents"):
            return []
        from subsystems.classification_channel.zone_manager import TrackAngularExtent

        extents = tracker.get_live_track_angular_extents()
        return [
            TrackAngularExtent(
                global_id=int(item["global_id"]),
                center_deg=float(item["center_deg"]),
                half_width_deg=float(item["half_width_deg"]),
                last_seen_ts=float(item["last_seen_ts"]),
                hit_count=int(item["hit_count"]),
                first_seen_ts=float(item.get("first_seen_ts", item["last_seen_ts"])),
                piece_uuid=(
                    item["piece_uuid"]
                    if isinstance(item.get("piece_uuid"), str)
                    and item["piece_uuid"].strip()
                    else None
                ),
            )
            for item in extents
        ]

    def getFeederTrackerLiveGlobalIds(self, role: str) -> set[int]:
        """Return the set of ``global_id``s currently alive on ``role``'s tracker.

        Used by:

        * the classification-channel Running state to verify that a piece
          claimed to be on the carousel is no longer tracked upstream
          (``c_channel_3``) before committing Brickognize;
        * the distribution Sending state to verify that a dropped piece has
          physically left the classification channel (``carousel``) before
          reopening the downstream distribution gate.

        Returns an empty set if the tracker or the ``live_global_ids``
        accessor is unavailable — callers must treat "empty / unavailable"
        as "no tracker evidence" and fall back to the configured cooldown
        rather than assuming the piece has exited.
        """
        tracker = self._feeder_trackers.get(role)
        if tracker is None:
            return set()
        accessor = getattr(tracker, "live_global_ids", None)
        if accessor is None:
            return set()
        try:
            return set(accessor())
        except Exception:
            return set()

    def markCarouselPendingDrop(
        self,
        global_id: int,
        *,
        protect_for_s: float | None = None,
    ) -> None:
        """Pin a carousel track against the stagnant-false-track filter while
        the piece is physically waiting at the drop zone.

        Called by the classification-channel state machine once a piece is
        committed to drop. Without this, the carousel tracker's aggressive
        stagnant filter (``max_age_s=1.5``, ``min_displacement_px=24``) would
        kill the track mid-wait — stranding ``live_global_ids("carousel")``
        and breaking both the distribution gate check and the drop handoff.

        No-op if the tracker has no ``mark_pending_drop`` accessor (e.g. a
        ByteTrack fallback) or is unavailable.
        """
        tracker = self._feeder_trackers.get("carousel")
        if tracker is None:
            return
        accessor = getattr(tracker, "mark_pending_drop", None)
        if accessor is None:
            return
        try:
            if protect_for_s is None:
                accessor(int(global_id))
            else:
                accessor(int(global_id), protect_for_s=float(protect_for_s))
        except Exception:
            pass

    def getFeederTrackGeometry(self, role: str) -> dict[str, float] | None:
        tracker = self._feeder_trackers.get(role)
        geom = getattr(tracker, "_channel_geom", None)
        if geom is None:
            return None
        return {
            "center_x": float(geom.center_x),
            "center_y": float(geom.center_y),
            "r_inner": float(geom.r_inner),
            "r_outer": float(geom.r_outer),
            "sector_count": float(geom.sector_count),
        }

    def triggerDropZoneBurst(self, global_id: int) -> None:
        """Trigger ±2s burst capture for a newly-arrived C4 piece.

        Grabs the rolling pre-buffer snapshot plus ~30 live post-trigger
        frames, runs the carousel detector on each, and attaches the results
        to the piece's history entry. Fires in a background thread — returns
        immediately.
        """
        algorithm = self.getCarouselDetectionAlgorithm()

        def detect_fn(frame_bgr: "np.ndarray") -> "tuple[tuple[int,int,int,int] | None, float | None]":
            try:
                result = self._runHiveDetection(algorithm, frame_bgr, scope="carousel", role="carousel")
                if result is None or not result.found or result.bbox is None:
                    return None, None
                bb = result.bbox
                return (int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])), result.score
            except Exception:
                return None, None

        def get_latest_frame() -> "tuple[np.ndarray, float] | None":
            capture = self._carousel_capture
            if capture is None:
                return None
            frame = capture.latest_frame
            if frame is None:
                return None
            return frame.raw.copy(), float(frame.timestamp)

        if algorithm.startswith("hive:"):
            self._drop_zone_burst_collector.trigger(global_id, detect_fn, get_latest_frame)

    def setClassificationChannelZoneOverlay(
        self,
        zones: list[dict[str, object]],
        *,
        intake_angle_deg: float | None = None,
        drop_angle_deg: float | None = None,
        drop_tolerance_deg: float | None = None,
        point_of_no_return_deg: float | None = None,
    ) -> None:
        self._classification_channel_zone_overlay = list(zones)
        self._classification_channel_zone_overlay_meta = {
            "intake_angle_deg": intake_angle_deg,
            "drop_angle_deg": drop_angle_deg,
            "drop_tolerance_deg": drop_tolerance_deg,
            "point_of_no_return_deg": point_of_no_return_deg,
        }

    def getClassificationChannelZoneOverlayData(self) -> dict[str, object]:
        return {
            "zones": list(self._classification_channel_zone_overlay),
            "geometry": self.getFeederTrackGeometry("carousel"),
            **self._classification_channel_zone_overlay_meta,
        }

    def _liveTrackPayload(self, role: str, global_id: int) -> dict | None:
        tracker = self._feeder_trackers.get(role)
        if tracker is None:
            return None
        live_track = next(
            (internal for internal in tracker._tracks.values() if internal.global_id == global_id),
            None,
        )
        if live_track is None:
            return None
        geom = tracker._channel_geom if tracker is not None else None
        sector_snaps_payload = [
            {
                "sector_index": s.sector_index,
                "start_angle_deg": s.start_angle_deg,
                "end_angle_deg": s.end_angle_deg,
                "captured_ts": s.captured_ts,
                "bbox_x": s.bbox_x,
                "bbox_y": s.bbox_y,
                "width": s.width,
                "height": s.height,
                "jpeg_b64": s.jpeg_b64,
                "r_inner": getattr(s, "r_inner", 0.0),
                "r_outer": getattr(s, "r_outer", 0.0),
                "piece_jpeg_b64": getattr(s, "piece_jpeg_b64", ""),
                "piece_bbox_x": getattr(s, "piece_bbox_x", 0),
                "piece_bbox_y": getattr(s, "piece_bbox_y", 0),
                "piece_width": getattr(s, "piece_width", 0),
                "piece_height": getattr(s, "piece_height", 0),
            }
            for s in live_track.sector_snapshots
        ]
        return {
            "source_role": role,
            "handoff_from": live_track.handoff_from,
            "first_seen_ts": live_track.first_seen_ts,
            "last_seen_ts": live_track.last_seen_ts,
            "duration_s": max(0.0, live_track.last_seen_ts - live_track.first_seen_ts),
            "hit_count": live_track.hit_count,
            "path_points": len(live_track.path),
            "snapshot_width": live_track.snapshot_width,
            "snapshot_height": live_track.snapshot_height,
            "snapshot_jpeg_b64": live_track.snapshot_jpeg_b64,
            "path": [list(p) for p in live_track.path],
            "channel_center_x": geom.center_x if geom is not None else None,
            "channel_center_y": geom.center_y if geom is not None else None,
            "channel_radius_inner": geom.r_inner if geom is not None else None,
            "channel_radius_outer": geom.r_outer if geom is not None else None,
            "sector_count": geom.sector_count if geom is not None else 0,
            "sector_snapshot_count": len(sector_snaps_payload),
            "sector_snapshots": sector_snaps_payload,
            "composite_jpeg_b64": "",
            "composite_width": 0,
            "composite_height": 0,
        }

    def getLatestFeederTrack(self, role: str, *, max_age_s: float = 1.0) -> dict | None:
        cached = self._feeder_track_cache.get(role)
        if cached is None:
            return None
        _ts, tracks = cached
        now = time.time()
        candidates = [
            track
            for track in tracks
            if now - float(track.last_seen_ts) <= max(0.0, max_age_s)
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda track: (float(track.last_seen_ts), int(track.hit_count)))
        return latest.to_dict()

    def _attachFeederTrackInfo(self, result: Dict[str, object], role: str) -> None:
        """Append serialized tracks + count to a feeder debug payload."""
        tracks = self.getFeederTracks(role)
        result["tracks"] = [track.to_dict() for track in tracks]
        result["track_count"] = len(tracks)

    def _channelDetectionsFromTracks(
        self,
        role: str,
        tracks: list,
    ) -> list[ChannelDetection]:
        channel = self._channelInfoForRole(role)
        if channel is None:
            return []
        detections: list[ChannelDetection] = []
        for track in tracks:
            if getattr(track, "coasting", False):
                continue
            if role in {"c_channel_2", "c_channel_3"} and int(
                getattr(track, "hit_count", 0) or 0
            ) < 2:
                continue
            bbox = getattr(track, "bbox", None)
            if not isinstance(bbox, tuple) or len(bbox) < 4:
                continue
            detections.append(
                ChannelDetection(
                    bbox=cast(Tuple[int, int, int, int], tuple(int(value) for value in bbox[:4])),
                    channel_id=channel.channel_id,
                    channel=channel,
                )
            )
        return detections

    def resetFeederTrackers(self) -> None:
        # Tracker.reset() flushes live confirmed tracks into the history buffer
        # before clearing — the user still sees them in the sidebar afterward.
        for tracker in self._feeder_trackers.values():
            tracker.reset()
        self._piece_handoff_manager.reset()
        self._feeder_track_cache.clear()

    # ------------------------------------------------------------------
    # Phase 3: Piece-dossier segment archival
    # ------------------------------------------------------------------

    def attachPieceTransportForSegmentArchival(self, transport: Any) -> None:
        """Wire a :class:`PieceTransport` so archived segments resolve their
        owning ``piece_uuid`` via ``get_piece_uuid_for_tracked_global_id``.

        Called from the machine-runtime bring-up once transport exists.
        ``None`` unbinds; segments will still land in SQLite under a
        stub uuid keyed by ``tracked_global_id`` but won't link back to
        the live classification-channel dossier.
        """
        self._piece_transport = transport

    def _archive_segment_to_dossier(self, tracked_global_id: int, segment: Any) -> None:
        """Side-channel callback fired by :class:`PieceHistoryBuffer` every
        time a segment gets recorded.

        Pulls the owning ``piece_uuid`` from the transport, writes the
        per-sector wedge/piece crops + any baseline snapshot to
        ``blob/piece_crops/<uuid>/seg<seq>/`` as JPEGs, then persists a
        ``piece_segments`` row via :func:`remember_piece_segment` with
        crop paths (relative to ``BLOB_DIR``) instead of base64 blobs.

        If the transport doesn't know about ``tracked_global_id`` yet
        (carousel track archived before C4 adopted it), a fresh stub
        dossier is minted so the segment has somewhere to hang off of.
        All I/O is best-effort — any exception just emits a WARNING and
        returns; the tracker must never be blocked by archival.
        """
        try:
            self._archive_segment_to_dossier_impl(int(tracked_global_id), segment)
        except Exception as exc:  # noqa: BLE001 — archival must not propagate
            try:
                self.gc.logger.warning(
                    f"_archive_segment_to_dossier: failed for gid="
                    f"{tracked_global_id}: {exc}"
                )
            except Exception:
                pass

    def _archive_segment_to_dossier_impl(
        self, tracked_global_id: int, segment: Any
    ) -> None:
        import uuid as _uuid
        import time as _time

        from blob_manager import write_piece_crop
        from local_state import (
            get_piece_dossier_by_tracked_global_id,
            remember_piece_dossier,
            remember_piece_segment,
        )
        from vision.tracking.history import segment_sector_angular_span_deg

        transport = self._piece_transport
        piece_uuid: str | None = None
        if transport is not None:
            try:
                piece_uuid = transport.get_piece_uuid_for_tracked_global_id(
                    int(tracked_global_id)
                )
            except Exception:
                piece_uuid = None

        # Transport-cache miss → fall back to the SQLite dossier index
        # before minting a fresh uuid. The C3 early-bind (Phase 4) already
        # persists a dossier keyed by ``tracked_global_id`` as soon as a
        # piece clears the motion-gate, so repeated archival calls on the
        # same gid must reuse that uuid instead of minting duplicates.
        if not piece_uuid:
            try:
                existing = get_piece_dossier_by_tracked_global_id(
                    int(tracked_global_id)
                )
            except Exception:
                existing = None
            if isinstance(existing, dict):
                candidate = existing.get("uuid") or existing.get("piece_uuid")
                if isinstance(candidate, str) and candidate.strip():
                    piece_uuid = candidate.strip()
                    if transport is not None and hasattr(transport, "bindStubPieceUuid"):
                        try:
                            transport.bindStubPieceUuid(
                                int(tracked_global_id), piece_uuid
                            )
                        except Exception:
                            pass

        if not piece_uuid:
            # Motion-gate on segment archival: a segment whose sector
            # snapshots barely span a few degrees is almost certainly a
            # static apparatus ghost that slipped past the early-bind
            # filter. Refuse to mint a stub dossier for it; the segment
            # stays unarchived and the ghost leaves no DB trace.
            span_deg = segment_sector_angular_span_deg(
                getattr(segment, "sector_snapshots", None)
            )
            if span_deg < 3.0:
                try:
                    self.gc.logger.info(
                        f"_archive_segment_to_dossier_impl: skipping stationary "
                        f"ghost segment gid={tracked_global_id} "
                        f"angular_span_deg={span_deg:.2f}"
                    )
                except Exception:
                    pass
                return

            piece_uuid = str(_uuid.uuid4())
            now = _time.time()
            first_seen_ts = (
                float(getattr(segment, "first_seen_ts", now) or now)
                if isinstance(getattr(segment, "first_seen_ts", None), (int, float))
                else now
            )
            try:
                remember_piece_dossier(
                    {
                        "uuid": piece_uuid,
                        "tracked_global_id": int(tracked_global_id),
                        "stage": "created",
                        "classification_status": "pending",
                        "created_at": first_seen_ts,
                        "updated_at": now,
                        "first_carousel_seen_ts": first_seen_ts,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — best effort
                try:
                    self.gc.logger.warning(
                        f"_archive_segment_to_dossier_impl: stub dossier "
                        f"failed for uuid={piece_uuid}: {exc}"
                    )
                except Exception:
                    pass
            # Expose the mapping to the transport so subsequent archival
            # calls (next segment on the same gid) reuse the same uuid.
            if transport is not None and hasattr(transport, "bindStubPieceUuid"):
                try:
                    transport.bindStubPieceUuid(int(tracked_global_id), piece_uuid)
                except Exception:
                    pass

        sequence = int(getattr(segment, "sector_count", 0) or 0)
        # sequence on disk needs to be a monotonically-increasing integer
        # per piece_uuid. Fall back to a derived value from first_seen_ts
        # if the segment doesn't carry one — same piece + same timestamp
        # is idempotent on the (piece_uuid, sequence) upsert key.
        if sequence <= 0:
            raw_fs = getattr(segment, "first_seen_ts", None)
            if isinstance(raw_fs, (int, float)) and raw_fs > 0:
                sequence = int(raw_fs * 1000) % 2_000_000_000
            else:
                sequence = 0

        # Persist the baseline snapshot (frame at track birth) once per
        # segment under ``snapshot_000.jpg`` so the detail page can draw
        # the wedge overlay over the same background the sector crops
        # came from.
        snapshot_b64 = getattr(segment, "snapshot_jpeg_b64", "") or ""
        snapshot_path: str | None = None
        if snapshot_b64:
            try:
                raw = base64.b64decode(snapshot_b64)
            except (ValueError, TypeError):
                raw = b""
            if raw:
                written = write_piece_crop(
                    piece_uuid, sequence, "snapshot", 0, raw
                )
                if written is not None:
                    snapshot_path = str(written)

        sector_payloads: list[dict[str, Any]] = []
        for idx, snap in enumerate(getattr(segment, "sector_snapshots", []) or []):
            wedge_path: str | None = None
            piece_path: str | None = None
            wedge_b64 = getattr(snap, "jpeg_b64", "") or ""
            piece_b64 = getattr(snap, "piece_jpeg_b64", "") or ""
            if wedge_b64:
                try:
                    wedge_raw = base64.b64decode(wedge_b64)
                except (ValueError, TypeError):
                    wedge_raw = b""
                if wedge_raw:
                    written = write_piece_crop(
                        piece_uuid, sequence, "wedge", idx, wedge_raw
                    )
                    if written is not None:
                        wedge_path = str(written)
            if piece_b64:
                try:
                    piece_raw = base64.b64decode(piece_b64)
                except (ValueError, TypeError):
                    piece_raw = b""
                if piece_raw:
                    written = write_piece_crop(
                        piece_uuid, sequence, "piece", idx, piece_raw
                    )
                    if written is not None:
                        piece_path = str(written)
            sector_payloads.append(
                {
                    "sector_index": int(getattr(snap, "sector_index", idx) or idx),
                    "start_angle_deg": float(getattr(snap, "start_angle_deg", 0.0) or 0.0),
                    "end_angle_deg": float(getattr(snap, "end_angle_deg", 0.0) or 0.0),
                    "captured_ts": float(getattr(snap, "captured_ts", 0.0) or 0.0),
                    "bbox_x": int(getattr(snap, "bbox_x", 0) or 0),
                    "bbox_y": int(getattr(snap, "bbox_y", 0) or 0),
                    "width": int(getattr(snap, "width", 0) or 0),
                    "height": int(getattr(snap, "height", 0) or 0),
                    "r_inner": float(getattr(snap, "r_inner", 0.0) or 0.0),
                    "r_outer": float(getattr(snap, "r_outer", 0.0) or 0.0),
                    "jpeg_path": wedge_path,
                    "piece_bbox_x": int(getattr(snap, "piece_bbox_x", 0) or 0),
                    "piece_bbox_y": int(getattr(snap, "piece_bbox_y", 0) or 0),
                    "piece_width": int(getattr(snap, "piece_width", 0) or 0),
                    "piece_height": int(getattr(snap, "piece_height", 0) or 0),
                    "piece_jpeg_path": piece_path,
                }
            )

        path_serialized: list[list[float]] = []
        for sample in getattr(segment, "path", []) or []:
            try:
                if isinstance(sample, (list, tuple)) and len(sample) >= 3:
                    path_serialized.append(
                        [float(sample[0]), float(sample[1]), float(sample[2])]
                    )
            except Exception:
                continue

        payload: dict[str, Any] = {
            "tracked_global_id": int(tracked_global_id),
            "first_seen_ts": float(getattr(segment, "first_seen_ts", 0.0) or 0.0),
            "last_seen_ts": float(getattr(segment, "last_seen_ts", 0.0) or 0.0),
            "hit_count": int(getattr(segment, "hit_count", 0) or 0),
            "channel_center_x": getattr(segment, "channel_center_x", None),
            "channel_center_y": getattr(segment, "channel_center_y", None),
            "channel_radius_inner": getattr(segment, "channel_radius_inner", None),
            "channel_radius_outer": getattr(segment, "channel_radius_outer", None),
            "snapshot_width": int(getattr(segment, "snapshot_width", 0) or 0),
            "snapshot_height": int(getattr(segment, "snapshot_height", 0) or 0),
            "snapshot_path": snapshot_path,
            "path": path_serialized,
            "sector_snapshots": sector_payloads,
            "recognize_result": getattr(segment, "auto_recognition", None),
        }
        role = str(getattr(segment, "source_role", "") or "")
        try:
            remember_piece_segment(
                piece_uuid=piece_uuid,
                role=role,
                sequence=int(sequence),
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            try:
                self.gc.logger.warning(
                    f"remember_piece_segment failed piece_uuid={piece_uuid} "
                    f"seq={sequence}: {exc}"
                )
            except Exception:
                pass

    def listFeederTrackHistory(
        self,
        limit: int | None = None,
        *,
        min_sectors: int = 0,
    ) -> list[dict]:
        """Combined list: currently-live tracks first, then recent deaths.

        Live tracks get ``live: True`` plus a rough duration from the last
        cached tracker snapshot. ``min_sectors`` filters historical entries
        so only pieces that visited at least that many angular sectors in
        any single segment are included — live tracks are always shown.
        """
        historical = self._piece_history.list_summaries(
            limit=limit, min_sectors=min_sectors
        )
        seen_ids = {item["global_id"] for item in historical}
        live: list[dict] = []
        for role, (_ts, tracks) in self._feeder_track_cache.items():
            tracker = self._feeder_trackers.get(role)
            for t in tracks:
                if t.global_id in seen_ids:
                    continue
                # Apply the same sector-count filter to live tracks so the
                # sidebar only surfaces pieces that have traveled far enough
                # to produce meaningful snapshots. Classification-channel
                # tracks should still show up even before they have covered
                # several sectors, otherwise the live overview hides exactly
                # the new setup the operator is debugging.
                if min_sectors > 0 and tracker is not None and role != "carousel":
                    live_track = next(
                        (lt for lt in tracker._tracks.values() if lt.global_id == t.global_id),
                        None,
                    )
                    if live_track is None or len(live_track.sector_snapshots) < min_sectors:
                        continue
                seen_ids.add(t.global_id)
                thumb = tracker.get_live_thumb(t.global_id) if tracker is not None else ""
                live.append(
                    {
                        "global_id": t.global_id,
                        "created_at": t.origin_seen_ts,
                        "finished_at": t.last_seen_ts,
                        "duration_s": max(0.0, t.last_seen_ts - t.origin_seen_ts),
                        "roles": [t.source_role],
                        "handoff_count": 1 if t.handoff_from else 0,
                        "segment_count": 1,
                        "total_hit_count": t.hit_count,
                        "composite_jpeg_b64": thumb,
                        "live": True,
                    }
                )
        live.sort(key=lambda x: x["finished_at"], reverse=True)
        combined = live + [{**h, "live": False} for h in historical]
        if limit is not None:
            combined = combined[:limit]
        return combined

    def getFeederTrackHistoryDetail(self, global_id: int) -> dict | None:
        """Detail from history buffer, augmented with any still-live segment."""
        detail = self._piece_history.get_detail(global_id)
        live_segments = [
            payload
            for role in self._feeder_trackers.keys()
            for payload in [self._liveTrackPayload(role, global_id)]
            if payload is not None
        ]
        burst_frames = self.getBurstFrames(global_id) or []
        if detail is not None:
            existing_roles = {
                segment.get("source_role")
                for segment in detail.get("segments", [])
                if isinstance(segment, dict)
            }
            appended = [
                payload for payload in live_segments
                if payload.get("source_role") not in existing_roles
            ]
            if appended:
                next_segments = list(detail.get("segments", [])) + appended
                next_segments.sort(key=lambda segment: float(segment.get("first_seen_ts", 0.0)))
                detail = {
                    **detail,
                    "segments": next_segments,
                    "roles": [segment.get("source_role") for segment in next_segments],
                    "segment_count": len(next_segments),
                    "handoff_count": sum(
                        1
                        for segment in next_segments
                        if isinstance(segment, dict) and segment.get("handoff_from") is not None
                    ),
                    "total_hit_count": sum(
                        int(segment.get("hit_count", 0))
                        for segment in next_segments
                        if isinstance(segment, dict)
                    ),
                    "finished_at": max(
                        float(segment.get("last_seen_ts", detail.get("finished_at", 0.0)))
                        for segment in next_segments
                        if isinstance(segment, dict)
                    ),
                    "live": True,
                }
            detail["burst_frames"] = burst_frames
            return detail
        if live_segments:
            live_segments.sort(key=lambda segment: float(segment.get("first_seen_ts", 0.0)))
            created_at = min(float(segment.get("first_seen_ts", 0.0)) for segment in live_segments)
            finished_at = max(float(segment.get("last_seen_ts", 0.0)) for segment in live_segments)
            return {
                "global_id": global_id,
                "created_at": created_at,
                "finished_at": finished_at,
                "duration_s": max(0.0, finished_at - created_at),
                "roles": [segment.get("source_role") for segment in live_segments],
                "handoff_count": sum(
                    1 for segment in live_segments if segment.get("handoff_from") is not None
                ),
                "segment_count": len(live_segments),
                "total_hit_count": sum(int(segment.get("hit_count", 0)) for segment in live_segments),
                "live": True,
                "segments": live_segments,
                "burst_frames": burst_frames,
            }
        return None

    def getFeederTrackPreview(
        self,
        global_id: int,
        *,
        preferred_roles: tuple[str, ...] = ("carousel", "c_channel_3", "c_channel_2"),
    ) -> str | None:
        if not isinstance(global_id, int):
            return None
        for role in preferred_roles:
            tracker = self._feeder_trackers.get(role)
            if tracker is None:
                continue
            crop_accessor = getattr(tracker, "get_live_piece_crop", None)
            if crop_accessor is not None:
                try:
                    piece_crop = crop_accessor(global_id)
                except Exception:
                    piece_crop = ""
                if isinstance(piece_crop, str) and piece_crop:
                    return piece_crop
            if not hasattr(tracker, "get_live_thumb"):
                continue
            try:
                thumb = tracker.get_live_thumb(global_id)
            except Exception:
                thumb = ""
            if isinstance(thumb, str) and thumb:
                return thumb
        detail = self.getFeederTrackHistoryDetail(global_id)
        if not isinstance(detail, dict):
            return None
        segments = detail.get("segments") or []
        for role in preferred_roles:
            role_segments = [
                segment for segment in segments
                if isinstance(segment, dict) and segment.get("source_role") == role
            ]
            role_segments.sort(
                key=lambda segment: float(segment.get("last_seen_ts", segment.get("first_seen_ts", 0.0))),
                reverse=True,
            )
            for segment in role_segments:
                sector_snapshots = segment.get("sector_snapshots") or []
                for snap in reversed(sector_snapshots):
                    piece_jpeg = snap.get("piece_jpeg_b64") if isinstance(snap, dict) else None
                    if isinstance(piece_jpeg, str) and piece_jpeg:
                        return piece_jpeg
                composite = segment.get("composite_jpeg_b64")
                if isinstance(composite, str) and composite:
                    return composite
        composite = detail.get("composite_jpeg_b64")
        if isinstance(composite, str) and composite:
            return composite
        return None

    # -- Drop-zone burst capture -------------------------------------------------

    _BURST_MAX_EDGE_PX = 640
    _BURST_JPEG_QUALITY = 75

    def _encodeBurstFrame(self, frame: np.ndarray) -> str | None:
        """Downscale-and-JPEG-encode one raw camera frame for the burst store."""
        if frame is None or not hasattr(frame, "shape") or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        longest = max(h, w)
        if longest > self._BURST_MAX_EDGE_PX:
            scale = self._BURST_MAX_EDGE_PX / float(longest)
            try:
                frame = cv2.resize(
                    frame,
                    (int(round(w * scale)), int(round(h * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            except Exception:
                return None
        try:
            ok, buf = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, self._BURST_JPEG_QUALITY],
            )
        except Exception:
            return None
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def _burstCaptureThreadsByRole(self) -> list[tuple[str, "CaptureThread | None"]]:
        """Ordered list of (role, capture) pairs to drain for burst capture."""
        return [
            ("c_channel_3", self._c_channel_3_capture),
            ("carousel", self._carousel_capture),
        ]

    def _drainBurstFrames(
        self,
        role: str,
        capture: "CaptureThread | None",
        count: int,
    ) -> list[dict]:
        if capture is None or count <= 0:
            return []
        drain = getattr(capture, "drain_ring_buffer", None)
        if drain is None:
            return []
        try:
            frames = drain(count) or []
        except Exception:
            return []
        encoded: list[dict] = []
        for cf in frames:
            raw = getattr(cf, "raw", None)
            if raw is None:
                continue
            jpeg_b64 = self._encodeBurstFrame(raw)
            if not jpeg_b64:
                continue
            encoded.append(
                {
                    "role": role,
                    "captured_ts": float(getattr(cf, "timestamp", 0.0) or 0.0),
                    "jpeg_b64": jpeg_b64,
                }
            )
        return encoded

    def captureBurst(
        self,
        global_id: int,
        pre_count: int = 30,
        post_count: int = 30,
        post_window_s: float = 2.0,
    ) -> None:
        """Drain pre-event frames now, schedule post-event frames in ``post_window_s``.

        Pre-event frames are stored IMMEDIATELY so the detail page can surface
        the free-fall moments even if the post-event timer never fires (e.g.
        the process is shut down between the trigger and the landing).
        """
        try:
            if not isinstance(global_id, int) or global_id <= 0:
                return
            pre_frames: list[dict] = []
            for role, capture in self._burstCaptureThreadsByRole():
                pre_frames.extend(self._drainBurstFrames(role, capture, pre_count))
            if pre_frames:
                # Pre-event frames may span both cameras — sort chronologically
                # so the filmstrip reads left-to-right as time progresses.
                pre_frames.sort(key=lambda f: float(f.get("captured_ts") or 0.0))
                self._burst_store.store(global_id, pre_frames)

            if post_count <= 0 or post_window_s <= 0.0:
                return

            with self._burst_lock:
                existing = self._burst_timers.pop(global_id, None)
            if existing is not None:
                try:
                    existing.cancel()
                except Exception:
                    pass

            timer = threading.Timer(
                float(post_window_s),
                self._finalizeBurst,
                args=(global_id, post_count),
            )
            timer.daemon = True
            with self._burst_lock:
                self._burst_timers[global_id] = timer
            timer.start()
        except Exception as exc:
            try:
                self.gc.logger.warning(f"captureBurst({global_id}) failed: {exc}")
            except Exception:
                pass

    def _finalizeBurst(self, global_id: int, post_count: int) -> None:
        """Collect post-event frames from the ring buffers and merge them in."""
        try:
            post_frames: list[dict] = []
            for role, capture in self._burstCaptureThreadsByRole():
                post_frames.extend(self._drainBurstFrames(role, capture, post_count))
            if post_frames:
                post_frames.sort(key=lambda f: float(f.get("captured_ts") or 0.0))
                self._burst_store.store(global_id, post_frames)
        except Exception as exc:
            try:
                self.gc.logger.warning(f"_finalizeBurst({global_id}) failed: {exc}")
            except Exception:
                pass
        finally:
            with self._burst_lock:
                self._burst_timers.pop(global_id, None)

    def getBurstFrames(self, global_id: int) -> list[dict] | None:
        return self._burst_store.get(global_id)

    def findRecentFeederTrackHistoryDetailByRole(
        self,
        *,
        source_role: str,
        before_ts: float,
        max_age_s: float = 6.0,
        limit: int = 40,
        required_global_id: int | None = None,
    ) -> dict | None:
        summaries = self._piece_history.list_summaries(limit=limit, min_sectors=1)
        best_global_id: int | None = None
        best_age_s = float("inf")
        for entry in summaries:
            roles = entry.get("roles") or []
            if source_role not in roles:
                continue
            finished_at = entry.get("finished_at")
            if not isinstance(finished_at, (int, float)):
                continue
            age_s = float(before_ts) - float(finished_at)
            if age_s < -0.25 or age_s > max_age_s or age_s >= best_age_s:
                continue
            candidate_id = int(entry.get("global_id"))
            if required_global_id is not None and candidate_id != int(required_global_id):
                continue
            best_global_id = candidate_id
            best_age_s = age_s
        if best_global_id is None:
            return None
        return self.getFeederTrackHistoryDetail(best_global_id)

    def _configureFeederHandoffZones(self, polys: Dict[str, np.ndarray]) -> None:
        """Derive exit/entry polygons from the loaded channel polygons.

        Phase-1 heuristic: take the channel polygon's bounding-rect and carve
        the visible outlet side for each channel into a simple rectangular
        handoff zone. This only needs to be roughly correct
        — the tracker just asks "did the track die near the border?" and
        "did the new track appear near the entry?" within the 2 s handoff
        window. Tight geometry is not required.

        If the rig has the cameras oriented differently we may need TOML
        overrides later. On the current live mount c_channel_2 hands off from
        the left / lower-left side into c_channel_3, while c_channel_3 still
        exits toward the classification channel on the right.
        """
        # Role-to-polygon-key mapping mirrors ``_ROLE_TO_POLY_KEY`` in
        # ``_initOverlays``. We duplicate the tiny dict because this method is
        # called before that one runs.
        role_to_key = {"c_channel_2": "second_channel", "c_channel_3": "third_channel"}
        if self._usesClassificationChannelSetup():
            role_to_key["carousel"] = "classification_channel"

        def _rect_to_polygon(x1: float, y1: float, x2: float, y2: float) -> list[tuple[float, float]]:
            return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

        for role, key in role_to_key.items():
            poly = polys.get(key)
            if poly is None or len(poly) < 3:
                continue
            x, y, w, h = cv2.boundingRect(np.asarray(poly, dtype=np.int32))
            if role == "c_channel_2":
                # Live camera-D shows the real c_channel_2 outlet on the left
                # / lower-left side of the ring. The old right-half heuristic
                # never saw exiting tracks there, which completely killed the
                # c_channel_2 -> c_channel_3 handoff history.
                ex2 = x + w // 2
                self._piece_handoff_manager.set_zones(
                    role,
                    exit_polygon=_rect_to_polygon(x, y, ex2, y + h),
                )
            elif role == "c_channel_3":
                # Entry = left HALF mirrors c_channel_2's exit.
                en2 = x + w // 2
                self._piece_handoff_manager.set_zones(
                    role,
                    entry_polygon=_rect_to_polygon(x, y, en2, y + h),
                )
                if self._usesClassificationChannelSetup():
                    ex1 = x + w // 2
                    self._piece_handoff_manager.set_zones(
                        role,
                        exit_polygon=_rect_to_polygon(ex1, y, x + w, y + h),
                    )
            elif role == "carousel":
                # The dedicated classification channel now intakes on the
                # upper-right / right-hand side of the platter, but the exact
                # birth position of a new carousel track still varies with
                # camera mounting and how the piece lands after handoff.
                # Using the full channel rect as the entry region makes the
                # c_channel_3 -> carousel identity claim much more robust on
                # the live machine while still staying bounded to the actual
                # classification platter.
                self._piece_handoff_manager.set_zones(
                    role,
                    entry_polygon=_rect_to_polygon(x, y, x + w, y + h),
                )

    def _runHiveDetection(
        self,
        algorithm_id: str,
        frame_bgr,
        *,
        scope: DetectionScope,
        role: str,
    ) -> ClassificationDetectionResult | None:
        processor = self._getOrBuildHiveProcessor(algorithm_id)
        if processor is None or frame_bgr is None:
            return None
        polygon = self._resolveZonePolygon(scope, role, frame_bgr.shape)
        crop = frame_bgr
        off_x, off_y = 0, 0
        if polygon is not None:
            result = self._cropFrameToPolygonRegion(frame_bgr, polygon)
            if result is not None:
                crop, (off_x, off_y) = result
        try:
            detections = processor.infer(crop)
        except Exception as exc:
            self.gc.logger.warning("Hive inference %s failed: %s", algorithm_id, exc)
            return None
        if not detections:
            return ClassificationDetectionResult(
                bbox=None,
                bboxes=(),
                score=0.0,
                algorithm=algorithm_id,
                found=False,
            )
        # Translate crop-space bboxes back to full-frame coordinates so the
        # live overlay + downstream pipeline see frame-absolute boxes.
        shifted = [
            (
                det.bbox[0] + off_x,
                det.bbox[1] + off_y,
                det.bbox[2] + off_x,
                det.bbox[3] + off_y,
            )
            for det in detections
        ]
        top_box = shifted[0]
        return ClassificationDetectionResult(
            bbox=top_box,
            bboxes=tuple(shifted),
            score=detections[0].score,
            algorithm=algorithm_id,
            found=True,
        )

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
        algorithm = self.getFeederDetectionAlgorithm(role)
        if algorithm.startswith("hive:"):
            # Hive inference is local but ~30-50ms per 320 crop on CPU. If we
            # ran it inline per frame-encode (10fps target), the encode thread
            # would stall for multiple cameras in parallel. Throttle to ~5fps
            # — overlay rendering reads whichever detection is most recent.
            cached = self._feeder_dynamic_detection_cache.get(role)
            now = frame.timestamp
            if cached is not None and not force:
                last_ts, last_det = cached
                if now - float(last_ts) < HIVE_INFERENCE_MIN_INTERVAL_S:
                    return self._filterFeederDetectionResultToChannel(role, last_det)
            detection = self._filterFeederDetectionResultToChannel(
                role,
                self._runHiveDetection(algorithm, frame.raw, scope="feeder", role=role),
            )
            self._feeder_dynamic_detection_cache[role] = (now, detection)
            self._updateFeederTracker(role, detection, now, frame_bgr=frame.raw)
            return detection
        cached = self._filterFeederDetectionResultToChannel(
            role,
            self._getCachedFeederDynamicDetection(role, frame.timestamp),
        )
        if algorithm == "gemini_sam" and not force:
            track_cache = self._feeder_track_cache.get(role)
            if (
                cached is not None
                and track_cache is not None
                and float(track_cache[0]) != float(frame.timestamp)
            ):
                self._updateFeederTracker(
                    role,
                    cached,
                    frame.timestamp,
                    frame_bgr=frame.raw,
                )
            elif cached is not None and track_cache is None:
                self._updateFeederTracker(
                    role,
                    cached,
                    frame.timestamp,
                    frame_bgr=frame.raw,
                )
            # Cloud Gemini must stay off the hot render path. Live overlays and
            # frame encoding consume the most recent cached result; the
            # auxiliary detection loop refreshes that cache asynchronously.
            return cached
        if not force:
            track_cache = self._feeder_track_cache.get(role)
            if (
                cached is not None
                and track_cache is not None
                and float(track_cache[0]) != float(frame.timestamp)
            ):
                self._updateFeederTracker(
                    role,
                    cached,
                    frame.timestamp,
                    frame_bgr=frame.raw,
                )
            elif cached is not None and track_cache is None:
                self._updateFeederTracker(
                    role,
                    cached,
                    frame.timestamp,
                    frame_bgr=frame.raw,
                )
            return cached
        detection = self._filterFeederDetectionResultToChannel(
            role,
            self._computeFeederGeminiDetection(role, frame, force_call=True),
        )
        self._feeder_dynamic_detection_cache[role] = (frame.timestamp, detection)
        self._updateFeederTracker(role, detection, frame.timestamp, frame_bgr=frame.raw)
        return detection

    def _channelDetectionsFromDynamicResult(
        self,
        role: str,
        detection: ClassificationDetectionResult | None,
    ) -> list[ChannelDetection]:
        channel = self._channelInfoForRole(role)
        detection = self._filterFeederDetectionResultToChannel(role, detection)
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
        algorithm = self.getCarouselDetectionAlgorithm()
        if algorithm.startswith("hive:"):
            now = frame.timestamp
            cached = self._carousel_dynamic_detection_cache
            if cached is not None and not force:
                last_ts, last_det = cached
                if now - float(last_ts) < HIVE_INFERENCE_MIN_INTERVAL_S:
                    return last_det
            detection = self._runHiveDetection(algorithm, frame.raw, scope="carousel", role="carousel")
            self._carousel_dynamic_detection_cache = (now, detection)
            return detection
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
        if role in self._feederTrackerRoles():
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
        if role in self._feederTrackerRoles():
            return "feeder"
        if role == "carousel":
            return "carousel"
        return "classification"

    def _sampleCollectionEnabledForRole(self, role: str) -> bool:
        if role in self._feederTrackerRoles():
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
        if role not in self._feederTrackerRoles():
            return
        self._queueAuxiliaryTeacherCapture(
            role=role,
            capture_reason="channel_move_complete",
            due_at=time.time() + max(0.0, delay_s),
            trigger_algorithm=self.getFeederDetectionAlgorithm(role),
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
        if self._camera_layout == "split_feeder":
            detections: list[ChannelDetection] = []
            for role in self._feederTrackerRoles():
                algorithm = self.getFeederDetectionAlgorithm(role)
                if self._isDynamicDetectionAlgorithm(algorithm):
                    # For dynamic split-feeder channels, drive the feeder
                    # state machine from tracker-confirmed live tracks rather
                    # than raw detector blobs. This filters out static guide /
                    # mount ghosts that the detector may repeatedly see even
                    # though the track layer has already aged them out.
                    self._getFeederDynamicDetection(role, force=False)
                    detections.extend(
                        self._channelDetectionsFromTracks(
                            role,
                            self.getFeederTracks(role),
                        )
                    )
                    continue
                analysis = self._per_channel_analysis.get(role)
                if analysis is not None:
                    detections.extend(analysis.getDetections())
            return detections
        if self._feeder_analysis is None:
            return []
        return self._feeder_analysis.getDetections()

    def getFeederDetectionAvailability(self, *, max_frame_age_s: float = 1.5) -> tuple[bool, str | None]:
        now = time.time()

        if self._camera_layout == "split_feeder":
            required_roles = {
                role: self.getCaptureThreadForRole(role)
                for role in self._feederTrackerRoles()
            }
            for role, capture in required_roles.items():
                if capture is None:
                    return False, f"{role} camera is not configured."
                frame = capture.latest_frame
                if frame is None:
                    return False, f"{role} camera has no live frame."
                if now - frame.timestamp > max_frame_age_s:
                    return False, f"{role} camera frame is stale."
                algorithm = self.getFeederDetectionAlgorithm(role)
                if (not self._isDynamicDetectionAlgorithm(algorithm)) and role not in self._per_channel_analysis:
                    return False, f"{role} feeder detector is not running."
            return True, None

        algorithm = self.getFeederDetectionAlgorithm()
        if self._feeder_capture is None:
            return False, "feeder camera is not configured."
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return False, "feeder camera has no live frame."
        if now - frame.timestamp > max_frame_age_s:
            return False, "feeder camera frame is stale."
        if (not self._isDynamicDetectionAlgorithm(algorithm)) and self._feeder_analysis is None:
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
        algorithm = self.getFeederDetectionAlgorithm(role)
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
                self._attachFeederTrackInfo(result, role)
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
            self._attachFeederTrackInfo(result, role)
            return result

        if algorithm.startswith("hive:"):
            # Route through _getFeederDynamicDetection so the tracker is
            # always updated — running _runHiveDetection directly here would
            # bypass _updateFeederTracker.
            detection = self._getFeederDynamicDetection(role, force=force)
            if detection is None:
                result.update(
                    {
                        "found": False,
                        "bbox": None,
                        "candidate_bboxes": [],
                        "bbox_count": 0,
                        "score": None,
                        "message": "Hive model failed to load or returned no result.",
                    }
                )
                self._attachFeederTrackInfo(result, role)
                return result
            result.update(
                {
                    "found": bool(detection.bboxes),
                    "bbox": list(detection.bbox) if detection.bbox is not None else None,
                    "candidate_bboxes": [list(b) for b in detection.bboxes],
                    "bbox_count": len(detection.bboxes),
                    "score": self._detectionScoreValue(detection),
                    "message": (
                        f"Hive model found {len(detection.bboxes)} candidate(s)."
                        if detection.bboxes
                        else "Hive model did not find a piece in the current frame."
                    ),
                }
            )
            self._attachFeederTrackInfo(result, role)
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
        self._attachFeederTrackInfo(result, role)
        return result

    def debugFeederDetection(self, role: str, *, include_capture: bool = False) -> Dict[str, object]:
        if role not in self._feederTrackerRoles():
            raise ValueError(f"Unsupported feeder role '{role}'")
        capture = self.getCaptureThreadForRole(role)
        if capture is None:
            return {
                "camera": role,
                "algorithm": self.getFeederDetectionAlgorithm(role),
                "found": False,
                "message": "No camera is configured for this channel.",
            }
        frame = capture.latest_frame
        if frame is None:
            return {
                "camera": role,
                "algorithm": self.getFeederDetectionAlgorithm(role),
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
            detection = self._filterFeederDetectionResultToChannel(
                "carousel",
                self._getCarouselDynamicDetection(force=force),
            )
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

        if algorithm.startswith("hive:"):
            detection = self._filterFeederDetectionResultToChannel(
                "carousel",
                self._runHiveDetection(algorithm, frame.raw, scope="carousel", role="carousel"),
            )
            if detection is None:
                result.update(
                    {
                        "found": False,
                        "bbox": None,
                        "candidate_bboxes": [],
                        "bbox_count": 0,
                        "score": None,
                        "message": "Hive model failed to load or returned no result.",
                    }
                )
                return result
            result.update(
                {
                    "found": bool(detection.bboxes),
                    "bbox": list(detection.bbox) if detection.bbox is not None else None,
                    "candidate_bboxes": [list(b) for b in detection.bboxes],
                    "bbox_count": len(detection.bboxes),
                    "score": self._detectionScoreValue(detection),
                    "message": (
                        f"Hive model found {len(detection.bboxes)} candidate(s) on the carousel."
                        if detection.bboxes
                        else "Hive model did not find a piece on the carousel."
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
        gemini_roles = [
            role
            for role in self._feederTrackerRoles()
            if self.getFeederDetectionAlgorithm(role) == "gemini_sam"
        ]
        pending_refresh: list[tuple[str, Any]] = []
        for role in gemini_roles:
            capture = self.getCaptureThreadForRole(role)
            frame = capture.latest_frame if capture is not None else None
            if frame is None:
                continue
            cached = self._feeder_dynamic_detection_cache.get(role)
            if cached is not None and cached[0] == frame.timestamp:
                track_cache = self._feeder_track_cache.get(role)
                if track_cache is None or float(track_cache[0]) != float(frame.timestamp):
                    self._updateFeederTracker(
                        role,
                        cached[1],
                        frame.timestamp,
                        frame_bgr=frame.raw,
                    )
                continue
            pending_refresh.append((role, frame))

        if pending_refresh:
            cursor = self._aux_feeder_refresh_cursor % len(pending_refresh)
            role, frame = pending_refresh[cursor]
            self._aux_feeder_refresh_cursor = (cursor + 1) % len(pending_refresh)
            detection = self._filterFeederDetectionResultToChannel(
                role,
                self._computeFeederGeminiDetection(role, frame, force_call=False),
            )
            self._feeder_dynamic_detection_cache[role] = (frame.timestamp, detection)
            self._updateFeederTracker(role, detection, frame.timestamp, frame_bgr=frame.raw)
        else:
            self._aux_feeder_refresh_cursor = 0

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

    def captureFreshClassificationChannelFrame(
        self,
        timeout_s: float = 1.0,
    ) -> Optional[CameraFrame]:
        if self._carousel_capture is None:
            return None
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            frame = self._carousel_capture.latest_frame
            if frame is not None and frame.timestamp > start_time:
                return frame
            time.sleep(0.05)
        return self._carousel_capture.latest_frame

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

    def getClassificationChannelDetectionCandidates(
        self,
        *,
        force: bool = False,
        frame: CameraFrame | None = None,
    ) -> List[Tuple[int, int, int, int]]:
        if frame is None:
            capture = self._carousel_capture
            frame = capture.latest_frame if capture is not None else None
        if frame is None:
            return []

        payload = self._buildCarouselDetectionPayload(frame, force=force)
        raw_candidates = payload.get("candidate_bboxes")
        if not isinstance(raw_candidates, list):
            return []

        candidates: List[Tuple[int, int, int, int]] = []
        for candidate in raw_candidates:
            if not isinstance(candidate, list) or len(candidate) < 4:
                continue
            try:
                candidates.append(tuple(int(value) for value in candidate[:4]))
            except (TypeError, ValueError):
                continue
        return candidates

    def getClassificationChannelCombinedBbox(
        self,
        *,
        force: bool = False,
        frame: CameraFrame | None = None,
    ) -> Tuple[int, int, int, int] | None:
        if frame is None:
            capture = self._carousel_capture
            frame = capture.latest_frame if capture is not None else None
        if frame is None:
            return None

        payload = self._buildCarouselDetectionPayload(frame, force=force)
        bbox = payload.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            try:
                return tuple(int(value) for value in bbox[:4])
            except (TypeError, ValueError):
                return None
        return None

    def getClassificationChannelSampleFromFrame(
        self,
        frame: CameraFrame | None,
    ) -> Dict[str, np.ndarray | None]:
        zone_crop: np.ndarray | None = None
        if frame is not None:
            zone_crop, _ = self._carouselRegionCrop(frame.raw)
        return {
            "zone": zone_crop,
            "frame": frame.raw.copy() if frame is not None else None,
        }

    def getClassificationChannelCrop(
        self,
        *,
        force: bool = False,
        frame: CameraFrame | None = None,
    ) -> np.ndarray | None:
        if frame is None:
            capture = self._carousel_capture
            frame = capture.latest_frame if capture is not None else None
        if frame is None:
            return None

        bbox = self.getClassificationChannelCombinedBbox(force=force, frame=frame)
        if bbox is None:
            return None

        x1, y1, x2, y2 = bbox
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        margin_x = max(18, int(round(width * 0.14)))
        margin_y = max(18, int(round(height * 0.14)))
        h, w = frame.raw.shape[:2]
        crop_x1 = max(0, x1 - margin_x)
        crop_y1 = max(0, y1 - margin_y)
        crop_x2 = min(w, x2 + margin_x)
        crop_y2 = min(h, y2 + margin_y)
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return None
        return frame.raw[crop_y1:crop_y2, crop_x1:crop_x2].copy()

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
        # Clamp to frame bounds — negative origin would wrap via numpy slicing.
        x = max(0, x)
        y = max(0, y)
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
