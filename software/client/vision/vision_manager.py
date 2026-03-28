from typing import Optional, List, Dict, Tuple, Union
import base64
import time
import threading
import cv2
import numpy as np

from global_config import GlobalConfig, RegionProviderType
from irl.config import IRLConfig, IRLInterface
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
from .mog2_channel_detector import Mog2ChannelDetector
from .feeder_analysis_thread import FeederAnalysisThread
from .classification_analysis_thread import ClassificationAnalysisThread
from .diff_configs import CarouselDiffConfig, ClassificationDiffConfig, DEFAULT_CAROUSEL_DIFF_CONFIG, DEFAULT_CLASSIFICATION_DIFF_CONFIG

TELEMETRY_INTERVAL_S = 30
FRAME_ENCODE_INTERVAL_MS = 100


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

        self._feeder_detector: Mog2ChannelDetector | None = None
        self._carousel_heatmap: HeatmapDiff = HeatmapDiff()  # overwritten after configs set

        self._channel_polygons: Dict[str, np.ndarray] = {}
        self._channel_angles: Dict[str, float] = {}
        self._channel_masks: Dict[str, np.ndarray] = {}
        self._carousel_polygon: List[Tuple[float, float]] | None = None

        self._feeder_analysis: FeederAnalysisThread | None = None
        self._cached_feeder_frame: CameraFrame | None = None
        self._cached_feeder_frame_ts: float = 0.0

        self._classification_masks: Dict[str, np.ndarray] = {}
        self._classification_mask_bboxes: Dict[str, Tuple[int, int, int, int]] = {}
        self._classification_polygon_resolution: Tuple[int, int] = (1920, 1080)
        self._loadClassificationPolygons()
        self._carousel_diff_config: CarouselDiffConfig = DEFAULT_CAROUSEL_DIFF_CONFIG
        self._diff_config: ClassificationDiffConfig = DEFAULT_CLASSIFICATION_DIFF_CONFIG
        self._carousel_heatmap = self._makeCarouselHeatmap()

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

    def initFeederDetection(self) -> bool:
        from blob_manager import getChannelPolygons

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

        feeder_lab = self.getLatestFeederLab()
        mask_shape = feeder_lab.shape[:2] if feeder_lab is not None else (1080, 1920)

        channel_masks: Dict[str, np.ndarray] = {}
        for key, pts in polys.items():
            ch_mask = np.zeros(mask_shape, dtype=np.uint8)
            cv2.fillPoly(ch_mask, [pts], 255)
            channel_masks[key] = ch_mask
        self._channel_masks = channel_masks

        channel_steppers = {
            "second_channel": self._irl.second_c_channel_rotor_stepper,
            "third_channel": self._irl.third_c_channel_rotor_stepper,
        }

        def is_channel_rotating(name: str) -> bool:
            stepper = channel_steppers.get(name)
            if stepper is None:
                return False
            return not stepper.stopped

        self._feeder_detector = Mog2ChannelDetector(
            channel_polygons=polys,
            channel_masks=channel_masks,
            channel_angles=self._channel_angles,
            is_channel_rotating=is_channel_rotating,
        )

        self._feeder_analysis = FeederAnalysisThread(
            detector=self._feeder_detector,
            get_gray=self.getLatestFeederRaw,
            profiler=self.gc.profiler,
        )
        self._feeder_analysis.start()
        self.gc.logger.info("Feeder MOG2 detection initialized")
        return True

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
            color_thresh_ab=c.color_thresh_ab,
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
        mode = self._classificationColorMode()

        baseline_dir = BLOB_DIR / "classification_baseline"
        loaded_any = False

        for cam_key, capture in [("top", self._classification_top_capture), ("bottom", self._classification_bottom_capture)]:
            if capture is None:
                continue
            baseline_min_path, baseline_max_path = self._classificationBaselinePaths(baseline_dir, cam_key, mode)
            read_mode = cv2.IMREAD_COLOR if mode == "lab" else cv2.IMREAD_GRAYSCALE
            baseline_min = cv2.imread(str(baseline_min_path), read_mode)
            baseline_max = cv2.imread(str(baseline_max_path), read_mode)
            if baseline_min is None or baseline_max is None:
                self.gc.logger.warn(f"Classification {cam_key} {mode} baseline not found. Run: scripts/calibrate_classification_baseline.py")
                continue

            calibration_frames: List[np.ndarray] = []
            frame_pattern = f"{cam_key}_frame_lab_*.png" if mode == "lab" else f"{cam_key}_frame_*.png"
            for p in sorted(globmod.glob(str(baseline_dir / frame_pattern))):
                cal_frame = cv2.imread(p, read_mode)
                if cal_frame is not None:
                    calibration_frames.append(cal_frame)

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

            self.gc.logger.info(f"Classification {cam_key} baseline loaded ({mode}, margin={cfg.envelope_margin}, adaptive_k={cfg.adaptive_std_k}, {len(calibration_frames)} cal frames)")
            loaded_any = True

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

        if self._feeder_detector is not None:
            annotated = self._feeder_detector.annotateFrame(annotated)
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

        bbox = self.getClassificationCombinedBbox(cam)
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
            cv2.putText(annotated, f"crop +{base}px{bias_label}", (mx1, my1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

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

    def _cropToBbox(self, frame: np.ndarray, bbox: Tuple[int, int, int, int],
                    margins: Tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        x1 = max(0, min(x1 - margins[0], w))
        y1 = max(0, min(y1 - margins[1], h))
        x2 = max(0, min(x2 + margins[2], w))
        y2 = max(0, min(y2 + margins[3], h))
        return frame[y1:y2, x1:x2]

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
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        top_frame, bottom_frame = self.captureFreshClassificationFrames(timeout_s)

        top_crop: np.ndarray | None = None
        if top_frame is not None:
            bbox = self.getClassificationCombinedBbox("top")
            if bbox is not None:
                margins = self._edgeBiasedMargins(bbox, "top")
                top_crop = self._cropToBbox(top_frame.raw, bbox, margins)

        bottom_crop: np.ndarray | None = None
        if bottom_frame is not None:
            bbox = self.getClassificationCombinedBbox("bottom")
            if bbox is not None:
                margins = self._edgeBiasedMargins(bbox, "bottom")
                bottom_crop = self._cropToBbox(bottom_frame.raw, bbox, margins)

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
