from typing import Optional, List, Dict, Tuple, Union
from dataclasses import replace
import base64
import time
import threading
import cv2
import numpy as np

from global_config import GlobalConfig, RegionProviderType
from irl.config import IRLConfig, IRLInterface, CAROUSEL_DETECTION_MODE
from defs.events import CameraName, FrameEvent, FrameData, FrameResultData
from defs.channel import ChannelDetection
from blob_manager import VideoRecorder, get_classification_polygons
from .camera import CaptureThread
from .types import CameraFrame, VisionResult, DetectedMask
from .regions import RegionName, Region
from .aruco_region_provider import ArucoRegionProvider
from .default_region_provider import DefaultRegionProvider
from .handdrawn_region_provider import HanddrawnRegionProvider
from .heatmap_diff import HeatmapDiff
from .hsv_correction import load_hsv_correction, bgr_to_hsv_scaled, is_noop as _hsvIsNoop
from .mog2_channel_detector import Mog2ChannelDetector
from .feeder_analysis_thread import FeederAnalysisThread
from .classification_analysis_thread import ClassificationAnalysisThread
from .diff_configs import CarouselDiffConfig, ClassificationDiffConfig, DEFAULT_CAROUSEL_DIFF_CONFIG, DEFAULT_CLASSIFICATION_DIFF_CONFIG

TELEMETRY_INTERVAL_S = 30
FRAME_ENCODE_INTERVAL_MS = 100


class VisionManager:
    _irl_config: IRLConfig
    _feeder_capture: Optional[CaptureThread]
    _c_channel_2_capture: Optional[CaptureThread]
    _c_channel_3_capture: Optional[CaptureThread]
    _carousel_capture: Optional[CaptureThread]
    _classification_capture: Optional[CaptureThread]
    _video_recorder: Optional[VideoRecorder]
    _region_provider: Union[ArucoRegionProvider, DefaultRegionProvider, HanddrawnRegionProvider]

    def __init__(self, irl_config: IRLConfig, gc: GlobalConfig, irl: IRLInterface):
        self.gc = gc
        self._irl_config = irl_config
        self._irl = irl
        self._feeder_camera_config = irl_config.feeder_camera
        self._disabled_cameras = set(gc.disable_video_streams)

        # Feeder is optional: a machine may not have one. When absent (or
        # disabled) the feeder capture, detection, and region provider are all
        # skipped and the rest of the system runs.
        self._feeder_capture = (
            CaptureThread("feeder", irl_config.feeder_camera)
            if irl_config.feeder_camera is not None and "feeder" not in self._disabled_cameras
            else None
        )

        self._is_split_feeder = (
            getattr(irl_config, "c_channel_2_camera", None) is not None
            and getattr(irl_config, "c_channel_3_camera", None) is not None
        )
        self._c_channel_2_capture = (
            CaptureThread("c_channel_2", irl_config.c_channel_2_camera)
            if self._is_split_feeder else None
        )
        self._c_channel_3_capture = (
            CaptureThread("c_channel_3", irl_config.c_channel_3_camera)
            if self._is_split_feeder else None
        )

        self._carousel_capture = (
            CaptureThread("carousel", irl_config.carousel_camera)
            if getattr(irl_config, "carousel_camera", None) is not None else None
        )

        # Single classification chamber camera.
        self._classification_capture = (
            CaptureThread("classification", irl_config.classification_camera)
            if irl_config.classification_camera is not None
            and "classification" not in self._disabled_cameras else None
        )

        self._video_recorder = VideoRecorder() if gc.should_write_camera_feeds else None

        self._telemetry = None
        self._last_telemetry_save = 0.0

        if self._feeder_capture is None:
            # No feeder camera -> no feeder-based regions.
            self._region_provider = DefaultRegionProvider()
        elif gc.region_provider == RegionProviderType.HANDDRAWN:
            self._region_provider = HanddrawnRegionProvider()
        elif gc.region_provider == RegionProviderType.ARUCO:
            self._region_provider = ArucoRegionProvider(gc, self._feeder_capture, irl_config)
        else:
            self._region_provider = DefaultRegionProvider()

        self._feeder_detector: Mog2ChannelDetector | None = None
        self._carousel_heatmap: HeatmapDiff = HeatmapDiff()  # overwritten after configs set
        # Optional HSV heatmap for the carousel camera (CAROUSEL_DETECTION_MODE
        # == "hsv"); loaded from the carousel_* baseline. None when the carousel
        # uses the legacy grayscale single-snapshot detection.
        self._carousel_hsv_heatmap: HeatmapDiff | None = None
        # Which carousel detector the runtime uses. "hsv" routes triggering
        # through the pre-calibrated rotational envelope (same path the tuner
        # validates); "gray" uses the legacy live-snapshot diff.
        self._carousel_hsv_mode = (CAROUSEL_DETECTION_MODE == "hsv")

        self._channel_polygons: Dict[str, np.ndarray] = {}
        self._channel_angles: Dict[str, float] = {}
        self._channel_masks: Dict[str, np.ndarray] = {}
        self._carousel_polygon: List[Tuple[float, float]] | None = None

        self._feeder_analysis: FeederAnalysisThread | None = None
        self._feeder_analysis_ch3: FeederAnalysisThread | None = None
        self._cached_feeder_frame: CameraFrame | None = None
        self._cached_feeder_frame_ts: float = 0.0

        self._classification_masks: Dict[str, np.ndarray] = {}
        self._classification_mask_bboxes: Dict[str, Tuple[int, int, int, int]] = {}
        self._classification_polygon_resolution: Tuple[int, int] = (1920, 1080)
        self._load_classification_polygons()
        self._carousel_diff_config: CarouselDiffConfig = DEFAULT_CAROUSEL_DIFF_CONFIG
        carousel_trigger_score = getattr(irl_config, "carousel_trigger_score", None)
        if carousel_trigger_score is not None:
            self._carousel_diff_config = replace(
                self._carousel_diff_config, trigger_score=carousel_trigger_score
            )
            self.gc.logger.info(
                f"Carousel heatmap trigger_score overridden to {carousel_trigger_score} (from machine config)"
            )
        self._diff_config: ClassificationDiffConfig = DEFAULT_CLASSIFICATION_DIFF_CONFIG
        # Optional HSV correction applied in the classification HS getters; must
        # match what the baseline calibration applied. None => no-op.
        self._hsv_correction = load_hsv_correction()
        if self._diff_config.use_hsv:
            self.gc.logger.info(
                "Classification detection: HSV (hue+saturation) mode"
                + ("" if _hsvIsNoop(self._hsv_correction) else " with HSV correction")
            )
        self._carousel_heatmap = self._make_carousel_heatmap()
        self.gc.logger.info(
            f"Carousel detection mode: {'HSV envelope' if self._carousel_hsv_mode else 'gray snapshot'}"
        )

        self._classification_heatmap: HeatmapDiff | None = None
        self._classification_analysis: ClassificationAnalysisThread | None = None

        self._cached_frame_events: List[FrameEvent] = []
        self._cached_frame_events_lock = threading.Lock()
        self._frame_encode_thread: threading.Thread | None = None
        self._frame_encode_stop = threading.Event()

    def set_telemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def set_aruco_smoothing_time_seconds(self, smoothing_time_s: float) -> None:
        if isinstance(self._region_provider, ArucoRegionProvider):
            self._region_provider.set_smoothing_time_seconds(smoothing_time_s)

    def start(self) -> None:
        if self._feeder_capture:
            self._feeder_capture.start()
        if self._c_channel_2_capture:
            self._c_channel_2_capture.start()
        if self._c_channel_3_capture:
            self._c_channel_3_capture.start()
        if self._carousel_capture:
            self._carousel_capture.start()
        if self._classification_capture:
            self._classification_capture.start()
        self._region_provider.start()
        self._frame_encode_stop.clear()
        self._frame_encode_thread = threading.Thread(
            target=self._frame_encode_loop, daemon=True
        )
        self._frame_encode_thread.start()

    def stop(self) -> None:
        self._frame_encode_stop.set()
        if self._frame_encode_thread:
            self._frame_encode_thread.join(timeout=2.0)
        if self._feeder_analysis:
            self._feeder_analysis.stop()
        if self._feeder_analysis_ch3:
            self._feeder_analysis_ch3.stop()
        if self._classification_analysis:
            self._classification_analysis.stop()
        self._region_provider.stop()
        if self._feeder_capture:
            self._feeder_capture.stop()
        if self._c_channel_2_capture:
            self._c_channel_2_capture.stop()
        if self._c_channel_3_capture:
            self._c_channel_3_capture.stop()
        if self._carousel_capture:
            self._carousel_capture.stop()
        if self._classification_capture:
            self._classification_capture.stop()
        if self._video_recorder:
            self._video_recorder.close()

    def init_feeder_detection(self) -> bool:
        from blob_manager import get_channel_polygons

        if self._feeder_capture is None and not self._is_split_feeder:
            self.gc.logger.info("No feeder camera; skipping feeder detection.")
            return False

        saved = get_channel_polygons()
        polygon_data = saved.get("polygons", {}) if saved else {}
        if not any(polygon_data.get(k) for k in ("second_channel", "third_channel")):
            # Split-feeder mode treats feeder channel polygons as optional: the
            # carousel pipeline still runs and the split branch skips channels
            # without polygons, so a missing/empty set is not fatal here.
            if self._is_split_feeder:
                self.gc.logger.info(
                    "Channel polygons not found; split-feeder running without feeder channel detection."
                )
                return True
            self.gc.logger.warn("Channel polygons not found. Run: scripts/polygon_editor.py")
            return False

        self._channel_angles = saved.get("channel_angles", {})

        # The polygon editor draws on a canvas sized to each camera's NATIVE resolution and
        # saves points in those native pixel coords (alongside the per-channel resolution).
        # The mask is built at that same resolution, so points are used as-is — no rescaling.
        def _scale_pts(raw_pts, cam_w: int, cam_h: int) -> np.ndarray:
            return np.array([[int(x), int(y)] for x, y in raw_pts], dtype=np.int32)

        # Use the resolutions recorded by polygon_editor at save time — the capture
        # threads may not have a frame yet when initFeederDetection is called.
        def _saved_size(key: str) -> tuple[int, int]:
            res = saved.get(key)
            if isinstance(res, (list, tuple)) and len(res) == 2:
                return int(res[0]), int(res[1])
            return 1920, 1080

        channel_steppers = {
            "second_channel": self._irl.second_c_channel_rotor_stepper,
            "third_channel": self._irl.third_c_channel_rotor_stepper,
        }

        def is_channel_rotating(name: str) -> bool:
            stepper = channel_steppers.get(name)
            return stepper is not None and not stepper.stopped

        if self._is_split_feeder:
            def _make_get_gray(capture: CaptureThread):
                def get_gray() -> np.ndarray | None:
                    frame = capture.latest_frame
                    return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY) if frame is not None else None
                return get_gray

            # Set carousel polygon scaled to c_channel_3 camera space (carousel is
            # visible in that camera view and the polygon was drawn there).
            carousel_raw = polygon_data.get("carousel")
            if carousel_raw and len(carousel_raw) >= 3:
                # Points already in the carousel camera's native coords (editor canvas).
                self._carousel_polygon = [(float(x), float(y)) for x, y in carousel_raw]

            res_key_map = {
                "second_channel": "resolution",
                "third_channel": "third_resolution",
            }
            for channel_name, capture, analysis_attr in [
                ("second_channel", self._c_channel_2_capture, "_feeder_analysis"),
                ("third_channel", self._c_channel_3_capture, "_feeder_analysis_ch3"),
            ]:
                raw_pts = polygon_data.get(channel_name)
                if capture is None or not raw_pts:
                    continue
                cam_w, cam_h = _saved_size(res_key_map[channel_name])
                scaled = _scale_pts(raw_pts, cam_w, cam_h)
                ch_mask = np.zeros((cam_h, cam_w), dtype=np.uint8)
                cv2.fillPoly(ch_mask, [scaled], 255)
                detector = Mog2ChannelDetector(
                    channel_polygons={channel_name: scaled},
                    channel_masks={channel_name: ch_mask},
                    channel_angles=self._channel_angles,
                    is_channel_rotating=is_channel_rotating,
                )
                analysis = FeederAnalysisThread(
                    detector=detector,
                    get_gray=_make_get_gray(capture),
                    profiler=self.gc.profiler,
                )
                setattr(self, analysis_attr, analysis)
                analysis.start()
                self.gc.logger.info(
                    f"Feeder split: {channel_name} mask={cam_w}x{cam_h} (native polygon coords)"
                )
        else:
            cam_w, cam_h = _saved_size("resolution")

            polys: Dict[str, np.ndarray] = {}
            channel_masks: Dict[str, np.ndarray] = {}
            for key in ("second_channel", "third_channel"):
                raw_pts = polygon_data.get(key)
                if not raw_pts:
                    continue
                scaled = _scale_pts(raw_pts, cam_w, cam_h)
                polys[key] = scaled
                ch_mask = np.zeros((cam_h, cam_w), dtype=np.uint8)
                cv2.fillPoly(ch_mask, [scaled], 255)
                channel_masks[key] = ch_mask

            self._channel_polygons = polys
            self._channel_masks = channel_masks

            carousel_pts = polygon_data.get("carousel")
            if carousel_pts and len(carousel_pts) >= 3:
                self._carousel_polygon = [(float(x), float(y)) for x, y in carousel_pts]

            self._feeder_detector = Mog2ChannelDetector(
                channel_polygons=polys,
                channel_masks=channel_masks,
                channel_angles=self._channel_angles,
                is_channel_rotating=is_channel_rotating,
            )
            self._feeder_analysis = FeederAnalysisThread(
                detector=self._feeder_detector,
                get_gray=self.get_latest_feeder_gray,
                profiler=self.gc.profiler,
            )
            self._feeder_analysis.start()
            self.gc.logger.info(f"Feeder single: mask={cam_w}x{cam_h} (native polygon coords)")

        self.gc.logger.info("Feeder MOG2 detection initialized")
        return True

    def _make_carousel_heatmap(self) -> HeatmapDiff:
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

    def _make_classification_heatmap(self) -> HeatmapDiff:
        c = self._diff_config
        # prescaled=True: the getters (_bgrToHS/_bgrToHSV) and the calibration
        # baseline both already produce working-resolution HSV (downscale before
        # convert), so HeatmapDiff must not downscale again. scale stays the
        # full->working ratio for bbox/threshold mapping.
        return HeatmapDiff(
            scale=c.scale,
            prescaled=True,
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
            channel_mode=("hsv" if c.use_value else "hs") if c.use_hsv else "gray",
            low_sat_thresh=c.low_sat_thresh,
        )

    def _load_channel_envelope(
        self, baseline_dir, cam_key: str, channel: str, margin: int, adaptive_k: float,
        max_value: int = 255,
    ):
        """Load one channel's min/max envelope PNGs and its per-frame stack,
        widen by the per-channel margin and (optional) adaptive std, and return
        (baseline_min, baseline_max) as uint8 arrays — or None if the envelope
        PNGs are missing. `channel` is 'h'/'s' (HSV mode) or '' (legacy gray).
        `max_value` caps the widened envelope: 179 for hue (OpenCV's valid range)
        so widening can't push it past the hue period into nonsense like 235."""
        import glob as globmod

        suffix = f"_{channel}" if channel else ""
        min_path = baseline_dir / f"{cam_key}_baseline{suffix}_min.png"
        max_path = baseline_dir / f"{cam_key}_baseline{suffix}_max.png"
        if not (min_path.exists() and max_path.exists()):
            return None

        bl_min = cv2.imread(str(min_path), cv2.IMREAD_GRAYSCALE)
        bl_max = cv2.imread(str(max_path), cv2.IMREAD_GRAYSCALE)
        if bl_min is None or bl_max is None:
            return None

        frames: List[np.ndarray] = []
        # Per-frame stacks for the adaptive-std margin. HSV channels use a
        # distinct "{cam}_{ch}frame_*" prefix so the legacy gray glob
        # "{cam}_frame_*" never picks them up.
        frame_glob = f"{cam_key}_{channel}frame_*.png" if channel else f"{cam_key}_frame_*.png"
        for p in sorted(globmod.glob(str(baseline_dir / frame_glob))):
            f = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if f is not None:
                frames.append(f)

        if len(frames) >= 2 and adaptive_k > 0:
            # Robust (MAD-based) spread, not naive std: a pixel that is floor on
            # 62/64 frames with 1-2 stray glints has a large std but ~0 MAD, so
            # the margin doesn't re-widen what the percentile envelope tightened.
            stack = np.stack(frames, axis=0).astype(np.float32)
            median = np.median(stack, axis=0)
            mad = np.median(np.abs(stack - median), axis=0)
            robust_std = 1.4826 * mad  # MAD -> std for a normal distribution
            adaptive_margin = np.clip(robust_std * adaptive_k, 0, 100).astype(np.int16)
            bl_min = np.clip(bl_min.astype(np.int16) - adaptive_margin, 0, max_value).astype(np.uint8)
            bl_max = np.clip(bl_max.astype(np.int16) + adaptive_margin, 0, max_value).astype(np.uint8)

        if margin > 0:
            bl_min = np.clip(bl_min.astype(np.int16) - margin, 0, max_value).astype(np.uint8)
            bl_max = np.clip(bl_max.astype(np.int16) + margin, 0, max_value).astype(np.uint8)

        return bl_min, bl_max

    def load_classification_baseline(self) -> bool:
        from blob_manager import BLOB_DIR

        cfg = self._diff_config
        use_hsv = cfg.use_hsv
        baseline_dir = BLOB_DIR / "classification_baseline"
        loaded_any = False

        # Single classification camera: load the "classification" baseline into the top slot.
        for cam_key, capture in [("classification", self._classification_capture)]:
            if capture is None:
                continue

            if use_hsv:
                # Hue capped at 179 (its valid range) so widening can't overflow.
                h_env = self._load_channel_envelope(baseline_dir, cam_key, "h", cfg.envelope_margin, cfg.adaptive_std_k, max_value=179)
                s_env = self._load_channel_envelope(baseline_dir, cam_key, "s", cfg.envelope_margin_s, cfg.adaptive_std_k)
                if h_env is None or s_env is None:
                    self.gc.logger.warn(
                        f"Classification {cam_key} HSV baseline not found. "
                        f"Run: scripts/calibrate_classification_baseline.py --wipe"
                    )
                    continue
                channels_min = [h_env[0], s_env[0]]
                channels_max = [h_env[1], s_env[1]]
                if cfg.use_value:
                    v_env = self._load_channel_envelope(baseline_dir, cam_key, "v", cfg.envelope_margin_v, cfg.adaptive_std_k)
                    if v_env is None:
                        self.gc.logger.warn(
                            f"Classification {cam_key} value envelope not found; "
                            f"falling back to H/S only. Re-run calibration to enable V."
                        )
                    else:
                        channels_min.append(v_env[0])
                        channels_max.append(v_env[1])
                # Stack into 2- or 3-channel min/max envelopes; HeatmapDiff adapts
                # to the channel count (H,S or H,S,V) per pixel.
                baseline_min = np.stack(channels_min, axis=-1)
                baseline_max = np.stack(channels_max, axis=-1)
            else:
                gray_env = self._load_channel_envelope(baseline_dir, cam_key, "", cfg.envelope_margin, cfg.adaptive_std_k)
                if gray_env is None:
                    self.gc.logger.warn(f"Classification {cam_key} baseline not found. Run: scripts/calibrate_classification_baseline.py")
                    continue
                baseline_min, baseline_max = gray_env

            # The baseline is captured at working resolution (full * scale), and
            # the live getters feed frames at the same working resolution, so
            # rescale the envelope to the live camera's working resolution if it
            # differs from the resolution the baseline was captured at.
            frame = capture.latest_frame
            if frame is not None:
                cam_h, cam_w = frame.raw.shape[:2]
                work_w = max(1, int(cam_w * cfg.scale))
                work_h = max(1, int(cam_h * cfg.scale))
                bl_h, bl_w = baseline_min.shape[:2]
                if work_w != bl_w or work_h != bl_h:
                    self.gc.logger.info(
                        f"Classification {cam_key} baseline {bl_w}x{bl_h} -> working {work_w}x{work_h}, rescaling"
                    )
                    baseline_min = cv2.resize(baseline_min, (work_w, work_h), interpolation=cv2.INTER_AREA)
                    baseline_max = cv2.resize(baseline_max, (work_w, work_h), interpolation=cv2.INTER_AREA)

            polygon = self._classification_masks.get(cam_key)
            if polygon is not None:
                scaled = self._scale_polygon(polygon, baseline_min.shape[1], baseline_min.shape[0])
                mask = np.zeros(baseline_min.shape[:2], dtype=np.uint8)
                cv2.fillPoly(mask, [scaled], 255)
            else:
                mask = np.ones(baseline_min.shape[:2], dtype=np.uint8) * 255

            # Intersect with the stable-pixel mask from calibration: pixels that
            # wobbled too much across the carousel sweep (tray-edge/marker/shadow)
            # are dropped so their ballooned envelope can't blind detection there.
            stable_path = baseline_dir / f"{cam_key}_stable_mask.png"
            if stable_path.exists():
                stable = cv2.imread(str(stable_path), cv2.IMREAD_GRAYSCALE)
                if stable is not None:
                    if stable.shape[:2] != mask.shape[:2]:
                        stable = cv2.resize(stable, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)
                    before = int(np.count_nonzero(mask))
                    mask = cv2.bitwise_and(mask, stable)
                    after = int(np.count_nonzero(mask))
                    dropped = 100.0 * (1 - after / before) if before else 0.0
                    self.gc.logger.info(
                        f"Classification {cam_key} stable mask applied: "
                        f"dropped {dropped:.1f}% of in-polygon pixels"
                    )

            # boundingRect is in working-res pixels; map it back to full res so
            # it can be compared against detection bboxes (which computeBboxes
            # already upscales by 1/scale) in _edgeBiasedMargins.
            mx, my, mw, mh = cv2.boundingRect(mask)
            inv = 1.0 / cfg.scale if cfg.scale < 1.0 else 1.0
            self._classification_mask_bboxes[cam_key] = (
                int(mx * inv), int(my * inv), int((mx + mw) * inv), int((my + mh) * inv)
            )

            heatmap = self._make_classification_heatmap()
            heatmap.load_envelope(baseline_min, baseline_max, mask)

            # Match the live getter's channel count to the envelope: 3ch (H,S,V)
            # only if the V envelope actually loaded, else 2ch (H,S), else gray.
            with_value = use_hsv and baseline_min.ndim == 3 and baseline_min.shape[2] == 3
            if with_value:
                get_frame = self._get_latest_classification_hsv
            elif use_hsv:
                get_frame = self._get_latest_classification_hs
            else:
                get_frame = self._get_latest_classification_gray

            analysis = ClassificationAnalysisThread(
                name=cam_key,
                heatmap=heatmap,
                get_gray=get_frame,
                profiler=self.gc.profiler,
                logger=self.gc.logger,
                min_bbox_dimension_px=cfg.min_bbox_dim,
                min_bbox_area_px=cfg.min_bbox_area,
            )
            self._classification_heatmap = heatmap
            self._classification_analysis = analysis
            analysis.start()

            mode = ("HSV+V" if with_value else "HSV") if use_hsv else "gray"
            self.gc.logger.info(
                f"Classification {cam_key} baseline loaded ({mode}, "
                f"margin_h={cfg.envelope_margin}, margin_s={cfg.envelope_margin_s}, "
                f"margin_v={cfg.envelope_margin_v}, adaptive_k={cfg.adaptive_std_k}, "
                f"low_sat_thresh={cfg.low_sat_thresh})"
            )
            loaded_any = True

        return loaded_any

    def _get_latest_classification_gray(self) -> np.ndarray | None:
        if self._classification_capture is None:
            return None
        frame = self._classification_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    def _bgr_to_hs(self, bgr: np.ndarray) -> np.ndarray:
        """BGR frame -> 2-channel (H, S) at working resolution, hue-rotated and
        corrected (matching the baseline calibration). The downscale happens on
        the BGR before the HSV conversion, so the conversion runs on scale**2 as
        many pixels and is symmetric with the envelope (also captured at scale).
        V is discarded: luminance varies with rotation and LED nonuniformity."""
        return bgr_to_hsv_scaled(bgr, self._diff_config.scale, self._hsv_correction, keep_value=False)

    def _get_latest_classification_hs(self) -> np.ndarray | None:
        if self._classification_capture is None:
            return None
        frame = self._classification_capture.latest_frame
        if frame is None:
            return None
        return self._bgr_to_hs(frame.raw)

    def _bgr_to_hsv(self, bgr: np.ndarray) -> np.ndarray:
        """BGR frame -> 3-channel (H, S, V) at working resolution, hue rotated +
        correction (same transform as the baseline; downscale-before-convert).
        Unlike _bgrToHS, V is kept so opaque pieces that block the backlight
        (darker than the glowing floor) register on the value channel."""
        return bgr_to_hsv_scaled(bgr, self._diff_config.scale, self._hsv_correction, keep_value=True)

    def _get_latest_classification_hsv(self) -> np.ndarray | None:
        if self._classification_capture is None:
            return None
        frame = self._classification_capture.latest_frame
        if frame is None:
            return None
        return self._bgr_to_hsv(frame.raw)

    def _get_latest_carousel_hsv(self) -> np.ndarray | None:
        if self._carousel_capture is None:
            return None
        frame = self._carousel_capture.latest_frame
        if frame is None:
            return None
        return self._bgr_to_hsv(frame.raw)

    def load_carousel_hsv_baseline(self) -> bool:
        """Load the carousel camera's HSV envelope baseline (the carousel_* PNGs
        from `calibrate_classification_baseline.py --camera carousel`) into a
        dedicated HSV heatmap. Additive — leaves the legacy grayscale carousel
        heatmap untouched. Used by the tuner and the CAROUSEL_DETECTION_MODE
        =="hsv" path. Reuses the classification HSV diff config as a starting
        point (tune via tune_classification_detection.py --camera carousel)."""
        from blob_manager import BLOB_DIR, get_channel_polygons

        if self._carousel_capture is None:
            self.gc.logger.warn("Carousel camera not configured; cannot load HSV baseline.")
            return False

        cfg = self._diff_config
        baseline_dir = BLOB_DIR / "classification_baseline"
        h_env = self._load_channel_envelope(baseline_dir, "carousel", "h", cfg.envelope_margin, cfg.adaptive_std_k, max_value=179)
        s_env = self._load_channel_envelope(baseline_dir, "carousel", "s", cfg.envelope_margin_s, cfg.adaptive_std_k)
        if h_env is None or s_env is None:
            self.gc.logger.warn(
                "Carousel HSV baseline not found. Run: "
                "scripts/calibrate_classification_baseline.py --camera carousel --wipe"
            )
            return False
        channels_min = [h_env[0], s_env[0]]
        channels_max = [h_env[1], s_env[1]]
        if cfg.use_value:
            v_env = self._load_channel_envelope(baseline_dir, "carousel", "v", cfg.envelope_margin_v, cfg.adaptive_std_k)
            if v_env is not None:
                channels_min.append(v_env[0])
                channels_max.append(v_env[1])
        baseline_min = np.stack(channels_min, axis=-1)
        baseline_max = np.stack(channels_max, axis=-1)

        # Rescale to the live carousel resolution if needed.
        # Baseline is captured at working resolution (full * scale); rescale to
        # the live carousel's working resolution to match the prescaled heatmap.
        frame = self._carousel_capture.latest_frame
        if frame is not None:
            cam_h, cam_w = frame.raw.shape[:2]
            work_w = max(1, int(cam_w * cfg.scale))
            work_h = max(1, int(cam_h * cfg.scale))
            if (work_w, work_h) != (baseline_min.shape[1], baseline_min.shape[0]):
                baseline_min = cv2.resize(baseline_min, (work_w, work_h), interpolation=cv2.INTER_AREA)
                baseline_max = cv2.resize(baseline_max, (work_w, work_h), interpolation=cv2.INTER_AREA)

        # Mask from the saved carousel polygon (drawn on the carousel camera in
        # polygon_editor), scaled to the envelope resolution.
        mask = np.ones(baseline_min.shape[:2], dtype=np.uint8) * 255
        saved = get_channel_polygons()
        if saved:
            pts = (saved.get("polygons") or {}).get("carousel")
            if pts and len(pts) >= 3:
                res = saved.get("carousel_resolution") or [baseline_min.shape[1], baseline_min.shape[0]]
                poly = np.array(pts, dtype=np.float64)
                poly[:, 0] *= baseline_min.shape[1] / res[0]
                poly[:, 1] *= baseline_min.shape[0] / res[1]
                mask = np.zeros(baseline_min.shape[:2], dtype=np.uint8)
                cv2.fillPoly(mask, [poly.astype(np.int32)], 255)

        stable_path = baseline_dir / "carousel_stable_mask.png"
        if stable_path.exists():
            stable = cv2.imread(str(stable_path), cv2.IMREAD_GRAYSCALE)
            if stable is not None:
                if stable.shape[:2] != mask.shape[:2]:
                    stable = cv2.resize(stable, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)
                mask = cv2.bitwise_and(mask, stable)

        heatmap = self._make_classification_heatmap()
        heatmap.load_envelope(baseline_min, baseline_max, mask)
        self._carousel_hsv_heatmap = heatmap
        self.gc.logger.info("Carousel HSV baseline loaded.")
        return True

    def get_classification_bboxes(self, cam: str = "classification") -> List[Tuple[int, int, int, int]]:
        if self._classification_analysis:
            return self._classification_analysis.get_bboxes()
        return []

    def get_classification_combined_bbox(self, cam: str = "classification") -> Tuple[int, int, int, int] | None:
        if self._classification_analysis:
            return self._classification_analysis.get_combined_bbox()
        return None

    def get_latest_feeder_gray(self) -> np.ndarray | None:
        if self._feeder_capture is None:
            return None
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    def get_latest_carousel_gray(self) -> np.ndarray | None:
        """Use the dedicated carousel camera if assigned. Otherwise, in split
        mode carousel is visible in c_channel_3; falling back to feeder."""
        if self._carousel_capture is not None:
            frame = self._carousel_capture.latest_frame
        elif self._is_split_feeder and self._c_channel_3_capture is not None:
            frame = self._c_channel_3_capture.latest_frame
        elif self._feeder_capture is not None:
            frame = self._feeder_capture.latest_frame
        else:
            return None
        if frame is None:
            return None
        return cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)

    def get_regions(self) -> dict[RegionName, Region]:
        if self._feeder_capture is None:
            return {}
        prof = self.gc.profiler
        prof.hit("vision.get_regions.calls")
        with prof.timer("vision.get_regions.total_ms"):
            frame = self._feeder_capture.latest_frame
            if frame is None:
                return {}
            return self._region_provider.get_regions(frame.raw)

    def get_feeder_heatmap_detections(self) -> list[ChannelDetection]:
        detections = []
        if self._feeder_analysis is not None:
            detections.extend(self._feeder_analysis.get_detections())
        if self._feeder_analysis_ch3 is not None:
            detections.extend(self._feeder_analysis_ch3.get_detections())
        return detections

    def is_carousel_hsv_mode(self) -> bool:
        """True when the carousel uses the pre-calibrated HSV envelope detector
        (CAROUSEL_DETECTION_MODE == "hsv"); the runtime loads its baseline at
        startup."""
        return self._carousel_hsv_mode

    def _active_carousel_heatmap(self) -> HeatmapDiff:
        """The heatmap the runtime triggers against: the pre-calibrated HSV
        envelope in HSV mode (when loaded), else the gray snapshot heatmap."""
        if self._carousel_hsv_mode and self._carousel_hsv_heatmap is not None:
            return self._carousel_hsv_heatmap
        return self._carousel_heatmap

    def capture_carousel_baseline(self) -> bool:
        # HSV mode triggers against the static pre-calibrated rotational
        # envelope, so there's no per-entry snapshot to capture — just confirm
        # the envelope is loaded so the Detecting state can proceed.
        if self._carousel_hsv_mode:
            loaded = self._carousel_hsv_heatmap is not None and self._carousel_hsv_heatmap.has_baseline
            if not loaded:
                self.gc.logger.warn(
                    "Carousel HSV baseline not loaded; run loadCarouselHsvBaseline at startup."
                )
            return loaded
        if self._carousel_polygon is None:
            return False
        gray = self.get_latest_carousel_gray()
        if gray is None:
            return False
        # Exclude the varying pixels recorded by the rotational sweep, the same
        # way the HSV carousel path does (loadCarouselHsvBaseline). The mask is
        # produced by calibrate_classification_baseline.py regardless of
        # detection mode; its value-std component is exactly the right signal
        # for a grayscale diff. Absent -> polygon-only mask (prior behavior).
        stable_mask = self._load_carousel_stable_mask()
        return self._carousel_heatmap.capture_baseline(
            self._carousel_polygon, gray.shape, extra_mask=stable_mask
        )

    def _load_carousel_stable_mask(self) -> "np.ndarray | None":
        from blob_manager import BLOB_DIR

        stable_path = BLOB_DIR / "classification_baseline" / "carousel_stable_mask.png"
        if not stable_path.exists():
            return None
        stable = cv2.imread(str(stable_path), cv2.IMREAD_GRAYSCALE)
        if stable is not None:
            self.gc.logger.info("Carousel gray baseline: applying stable-pixel mask.")
        return stable

    def clear_carousel_baseline(self) -> None:
        # The HSV envelope is the persistent pre-calibrated baseline; only the
        # gray mode captures a per-entry snapshot that needs clearing.
        if self._carousel_hsv_mode:
            return
        self._carousel_heatmap.clear_baseline()

    def is_carousel_triggered(self) -> Tuple[bool, float, int]:
        score, hot_px = self._active_carousel_heatmap().compute_diff()
        return score >= self._carousel_diff_config.trigger_score, score, hot_px

    def record_frames(self) -> None:
        prof = self.gc.profiler
        prof.hit("vision.record_frames.calls")
        with prof.timer("vision.record_frames.total_ms"):
            # Feed the active carousel detector: working-res HSV in HSV mode,
            # full-res gray in legacy mode.
            if self._carousel_hsv_mode and self._carousel_hsv_heatmap is not None:
                hsv = self._get_latest_carousel_hsv()
                if hsv is not None:
                    self._carousel_hsv_heatmap.push_frame(hsv)
            else:
                gray = self.get_latest_carousel_gray()
                if gray is not None:
                    self._carousel_heatmap.push_frame(gray)

            if self._video_recorder:
                with prof.timer("vision.record_frames.video_recorder_write_ms"):
                    for camera in ["feeder", "classification"]:
                        frame = self.get_frame(camera)
                        if frame:
                            self._video_recorder.write_frame(
                                camera, frame.raw, frame.annotated
                            )
            with prof.timer("vision.record_frames.save_telemetry_frames_ms"):
                self._save_telemetry_frames()

    def _save_telemetry_frames(self) -> None:
        if self._telemetry is None:
            return
        now = time.time()
        if now - self._last_telemetry_save < TELEMETRY_INTERVAL_S:
            return
        self._last_telemetry_save = now

        CAMERA_NAME_MAP = {
            "feeder": "c_channel",
            "classification": "classification_chamber",
        }
        for internal_name, telemetry_name in CAMERA_NAME_MAP.items():
            frame = self.get_frame(internal_name)
            if frame and frame.raw is not None:
                self._telemetry.save_capture(
                    telemetry_name,
                    frame.raw,
                    frame.annotated,
                    "interval",
                )

    @property
    def feeder_frame(self) -> Optional[CameraFrame]:
        if self._feeder_capture is None:
            return None
        frame = self._feeder_capture.latest_frame
        if frame is None:
            return None

        if self._cached_feeder_frame is not None and frame.timestamp == self._cached_feeder_frame_ts:
            return self._cached_feeder_frame

        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()
        annotated = self._region_provider.annotate_frame(annotated)

        if self._feeder_detector is not None:
            annotated = self._feeder_detector.annotate_frame(annotated)
            from subsystems.feeder.analysis import get_bbox_sections
            from defs.consts import (
                CH3_PRECISE_SECTIONS, CH3_DROPZONE_SECTIONS,
                CH2_PRECISE_SECTIONS, CH2_DROPZONE_SECTIONS,
            )
            for det in self.get_feeder_heatmap_detections():
                x1, y1, x2, y2 = det.bbox
                secs = get_bbox_sections(det.bbox, det.channel)
                precise = bool(secs & set(CH3_PRECISE_SECTIONS if det.channel_id == 3 else CH2_PRECISE_SECTIONS))
                drop = bool(secs & set(CH3_DROPZONE_SECTIONS if det.channel_id == 3 else CH2_DROPZONE_SECTIONS))
                label = f"ch{det.channel_id} {sorted(secs)} p={precise} d={drop}"
                cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)

        carousel_hm = self._active_carousel_heatmap()
        if self._carousel_capture is None and carousel_hm.has_baseline:
            annotated = carousel_hm.annotate_frame(annotated, label="carousel", text_y=80)

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
    def classification_frame(self) -> Optional[CameraFrame]:
        if self._classification_capture is None:
            return None
        frame = self._classification_capture.latest_frame
        if frame is None:
            return None
        return self._annotate_classification_frame(frame, "classification", self._classification_heatmap)

    def _annotate_classification_frame(
        self, frame: CameraFrame, cam: str, heatmap: HeatmapDiff | None
    ) -> CameraFrame:
        if heatmap is None or not heatmap.has_baseline:
            return frame
        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()
        annotated = heatmap.annotate_frame(annotated, label=f"class_{cam}", text_y=30)

        bbox = self.get_classification_combined_bbox(cam)
        if bbox is not None:
            margins = self._edge_biased_margins(bbox, cam)
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

    def _make_channel_frame(
        self, capture: "CaptureThread", analysis: "FeederAnalysisThread | None"
    ) -> Optional[CameraFrame]:
        frame = capture.latest_frame
        if frame is None:
            return None
        annotated = frame.annotated if frame.annotated is not None else frame.raw.copy()
        if analysis is not None and analysis._detector is not None:
            annotated = analysis._detector.annotate_frame(annotated)
        return CameraFrame(raw=frame.raw, annotated=annotated, results=[], timestamp=frame.timestamp)

    def get_frame(self, camera_name: str) -> Optional[CameraFrame]:
        if camera_name == "feeder":
            return self.feeder_frame
        elif camera_name == "c_channel_2" and self._c_channel_2_capture is not None:
            return self._make_channel_frame(self._c_channel_2_capture, self._feeder_analysis)
        elif camera_name == "c_channel_3" and self._c_channel_3_capture is not None:
            return self._make_channel_frame(self._c_channel_3_capture, self._feeder_analysis_ch3)
        elif camera_name == "carousel" and self._carousel_capture is not None:
            frame = self._make_channel_frame(self._carousel_capture, None)
            carousel_hm = self._active_carousel_heatmap()
            if frame is not None and carousel_hm.has_baseline:
                annotated = carousel_hm.annotate_frame(frame.annotated, label="carousel", text_y=80)
                frame = CameraFrame(raw=frame.raw, annotated=annotated, results=frame.results, timestamp=frame.timestamp)
            return frame
        elif camera_name == "classification":
            return self.classification_frame
        return None

    def get_feeder_aruco_tags(self) -> Dict[int, Tuple[float, float]]:
        if isinstance(self._region_provider, ArucoRegionProvider):
            return self._region_provider.get_tags()
        return {}

    def get_feeder_aruco_tags_raw(self) -> Dict[int, Tuple[float, float]]:
        if isinstance(self._region_provider, ArucoRegionProvider):
            return self._region_provider.get_raw_tags()
        return {}

    # stubbed — no inference engine
    def get_feeder_detections_by_class(self) -> Dict[int, List[VisionResult]]:
        return {}

    # stubbed — no inference engine
    def get_feeder_masks_by_class(self) -> Dict[int, List[DetectedMask]]:
        return {}

    def capture_fresh_classification_frames(
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[CameraFrame], Optional[CameraFrame]]:
        """Wait for a fresh classification frame. Returns (frame, None) — the second
        slot is legacy (there was a second 'bottom' camera) and kept for the snapping
        call signature."""
        if self._classification_capture is None:
            return (None, None)
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            frame = self._classification_capture.latest_frame
            if frame and frame.timestamp > start_time:
                return (frame, None)
            time.sleep(0.05)
        return (self._classification_capture.latest_frame, None)

    def _load_classification_polygons(self) -> None:
        saved = get_classification_polygons()
        if saved is None:
            return
        res = saved.get("resolution")
        if res and len(res) == 2:
            self._classification_polygon_resolution = (int(res[0]), int(res[1]))
        polygons = saved.get("polygons", {})
        # Single classification region under the "classification" key (was top/bottom).
        for key in ("classification",):
            pts = polygons.get(key)
            if pts and len(pts) >= 3:
                self._classification_masks[key] = np.array(pts, dtype=np.int32)

    def _scale_polygon(self, polygon: np.ndarray, frame_w: int, frame_h: int) -> np.ndarray:
        src_w, src_h = self._classification_polygon_resolution
        if src_w == frame_w and src_h == frame_h:
            return polygon
        scale_x = frame_w / src_w
        scale_y = frame_h / src_h
        scaled = polygon.astype(np.float64)
        scaled[:, 0] *= scale_x
        scaled[:, 1] *= scale_y
        return scaled.astype(np.int32)

    def _mask_to_region(self, frame: np.ndarray, key: str) -> np.ndarray:
        polygon = self._classification_masks.get(key)
        if polygon is None:
            return frame
        h, w = frame.shape[:2]
        polygon = self._scale_polygon(polygon, w, h)
        white = np.full_like(frame, 255)
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [polygon], 255)
        result = np.where(mask[:, :, np.newaxis] == 255, frame, white)
        return result

    def _crop_to_bbox(self, frame: np.ndarray, bbox: Tuple[int, int, int, int],
                    margins: Tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        x1 = max(0, min(x1 - margins[0], w))
        y1 = max(0, min(y1 - margins[1], h))
        x2 = max(0, min(x2 + margins[2], w))
        y2 = max(0, min(y2 + margins[3], h))
        return frame[y1:y2, x1:x2]

    def _edge_biased_margins(self, bbox: Tuple[int, int, int, int],
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

    def get_classification_crops(
        self, timeout_s: float = 1.0
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        top_frame, bottom_frame = self.capture_fresh_classification_frames(timeout_s)

        top_crop: np.ndarray | None = None
        if top_frame is not None:
            bbox = self.get_classification_combined_bbox("classification")
            if bbox is not None:
                margins = self._edge_biased_margins(bbox, "classification")
                top_crop = self._crop_to_bbox(top_frame.raw, bbox, margins)

        return (top_crop, None)

    def _encode_frame(self, frame: np.ndarray) -> str:
        with self.gc.profiler.timer("vision.encode_frame.imencode_ms"):
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.gc.profiler.timer("vision.encode_frame.base64_ms"):
            return base64.b64encode(buffer).decode("utf-8")

    def get_frame_event(self, camera_name: CameraName) -> Optional[FrameEvent]:
        self.gc.profiler.hit(f"vision.get_frame_event.calls.{camera_name.value}")
        self.gc.profiler.start_timer("vision.get_frame_event.total_ms")
        frame = self.get_frame(camera_name.value)
        if frame is None:
            self.gc.profiler.end_timer("vision.get_frame_event.total_ms")
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

        raw_b64 = self._encode_frame(frame.raw)
        annotated_b64 = (
            self._encode_frame(frame.annotated) if frame.annotated is not None else None
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
        self.gc.profiler.end_timer("vision.get_frame_event.total_ms")
        return event

    def get_all_frame_events(self) -> List[FrameEvent]:
        with self._cached_frame_events_lock:
            return list(self._cached_frame_events)

    def _frame_encode_loop(self) -> None:
        while not self._frame_encode_stop.is_set():
            prof = self.gc.profiler
            prof.hit("vision.frame_encode_thread.calls")
            with prof.timer("vision.frame_encode_thread.total_ms"):
                events: List[FrameEvent] = []
                for camera in CameraName:
                    event = self.get_frame_event(camera)
                    if event:
                        events.append(event)
                with self._cached_frame_events_lock:
                    self._cached_frame_events = events
            self._frame_encode_stop.wait(FRAME_ENCODE_INTERVAL_MS / 1000.0)
