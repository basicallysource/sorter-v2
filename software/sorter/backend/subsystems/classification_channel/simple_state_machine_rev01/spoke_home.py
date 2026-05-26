import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from blob_manager import getChannelPolygons
from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter

SPOKE_COUNT = 5
SPOKE_SEPARATION_DEG = 360.0 / SPOKE_COUNT


@dataclass(frozen=True)
class Annulus:
    center_x: float
    center_y: float
    inner_radius: float
    outer_radius: float


@dataclass(frozen=True)
class DetectorParams:
    polar_n_theta: int = 1080
    polar_n_r: int = 256
    preblur_sigma_px: float = 1.5
    use_gradient_magnitude: bool = True
    clip_outer_frac: float = 0.98
    clip_inner_extra_frac: float = 0.05
    spoke_smooth_deg: float = 5.0
    search_step_deg: float = 0.25
    refine_window_deg: float = 1.0
    edge_taper_frac: float = 0.04
    center_refine_radius_frac: float = 0.15
    center_refine_stage_steps_frac: tuple[float, ...] = (0.024, 0.008, 0.0025)
    center_refine_polar_n_theta: int = 360
    min_peak_prominence_ratio: float = 1.20


@dataclass(frozen=True)
class DetectorResult:
    angle_deg: float
    score: float
    success: bool
    failure_reason: str
    prominence_ratio: float
    annulus_used: Annulus


DETECTOR_PARAMS = DetectorParams()


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _scalePoint(
    point: tuple[float, float],
    src_w: float,
    src_h: float,
    frame_w: int,
    frame_h: int,
) -> tuple[float, float]:
    return (
        float(point[0]) * float(frame_w) / float(src_w),
        float(point[1]) * float(frame_h) / float(src_h),
    )


def _pointForAngle(
    center_x: float,
    center_y: float,
    radius: float,
    angle_deg: float,
) -> tuple[float, float]:
    theta = math.radians(float(angle_deg))
    return (
        float(center_x) + float(radius) * math.cos(theta),
        float(center_y) + float(radius) * math.sin(theta),
    )


def angleForPoint(
    x: float,
    y: float,
    center_x: float,
    center_y: float,
) -> float:
    return math.degrees(math.atan2(float(y) - float(center_y), float(x) - float(center_x))) % 360.0


def computeForwardAlignmentDeltaDeg(
    spoke_angle_deg: float,
    reference_angle_deg: float,
) -> float:
    return (float(reference_angle_deg) - float(spoke_angle_deg)) % SPOKE_SEPARATION_DEG


def loadSpokeHomeGeometry(
    frame_shape: tuple[int, int],
) -> tuple[Annulus, tuple[float, float]] | None:
    saved = getChannelPolygons()
    if not isinstance(saved, dict):
        return None
    arc_params = saved.get("arc_params")
    if not isinstance(arc_params, dict):
        return None
    raw_arc = arc_params.get("classification_channel")
    if not isinstance(raw_arc, dict):
        return None

    center = raw_arc.get("center")
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    center_x = _number(center[0])
    center_y = _number(center[1])
    inner_radius = _number(raw_arc.get("inner_radius"))
    outer_radius = _number(raw_arc.get("outer_radius"))
    if (
        center_x is None
        or center_y is None
        or inner_radius is None
        or outer_radius is None
        or outer_radius <= inner_radius
    ):
        return None

    resolution = raw_arc.get("resolution")
    if not isinstance(resolution, (list, tuple)) or len(resolution) < 2:
        resolution = saved.get("resolution")
    if not isinstance(resolution, (list, tuple)) or len(resolution) < 2:
        return None
    src_w = _number(resolution[0])
    src_h = _number(resolution[1])
    if src_w is None or src_h is None or src_w <= 0 or src_h <= 0:
        return None

    frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
    scaled_center_x, scaled_center_y = _scalePoint(
        (center_x, center_y),
        src_w,
        src_h,
        frame_w,
        frame_h,
    )
    radius_scale = (float(frame_w) / float(src_w) + float(frame_h) / float(src_h)) * 0.5
    annulus = Annulus(
        center_x=scaled_center_x,
        center_y=scaled_center_y,
        inner_radius=float(inner_radius) * radius_scale,
        outer_radius=float(outer_radius) * radius_scale,
    )

    section_zero_pts = saved.get("section_zero_pts")
    if isinstance(section_zero_pts, dict):
        raw_zero = section_zero_pts.get("classification_channel")
        if isinstance(raw_zero, (list, tuple)) and len(raw_zero) >= 2:
            zero_x = _number(raw_zero[0])
            zero_y = _number(raw_zero[1])
            if zero_x is not None and zero_y is not None:
                return annulus, _scalePoint((zero_x, zero_y), src_w, src_h, frame_w, frame_h)

    channel_angles = saved.get("channel_angles")
    if isinstance(channel_angles, dict):
        zero_angle_deg = _number(channel_angles.get("classification_channel"))
        if zero_angle_deg is not None:
            return annulus, _pointForAngle(
                annulus.center_x,
                annulus.center_y,
                annulus.outer_radius,
                zero_angle_deg,
            )

    return None


def _clampAnnulusToImage(
    annulus: Annulus,
    image_shape: tuple[int, int],
) -> Annulus:
    height, width = image_shape[:2]
    max_radius = min(
        annulus.center_x,
        float(width) - annulus.center_x,
        annulus.center_y,
        float(height) - annulus.center_y,
    )
    if annulus.outer_radius <= max_radius:
        return annulus
    return Annulus(
        center_x=annulus.center_x,
        center_y=annulus.center_y,
        inner_radius=min(annulus.inner_radius, max_radius * 0.5),
        outer_radius=max_radius,
    )


def _polarWarp(
    image: np.ndarray,
    annulus: Annulus,
    params: DetectorParams,
) -> np.ndarray:
    polar = cv2.warpPolar(
        image,
        (params.polar_n_r, params.polar_n_theta),
        (annulus.center_x, annulus.center_y),
        annulus.outer_radius,
        cv2.WARP_POLAR_LINEAR + cv2.INTER_LINEAR,
    )
    if not np.all(np.isfinite(polar)):
        polar = np.where(np.isfinite(polar), polar, 0.0).astype(polar.dtype)
    return polar


def _annulusRadialMask(
    annulus: Annulus,
    params: DetectorParams,
) -> np.ndarray:
    r_norm = np.linspace(0.0, 1.0, params.polar_n_r, dtype=np.float32)
    inner_norm = (annulus.inner_radius / annulus.outer_radius) + params.clip_inner_extra_frac
    outer_norm = params.clip_outer_frac
    mask = np.zeros(params.polar_n_r, dtype=np.float32)
    inside = (r_norm >= inner_norm) & (r_norm <= outer_norm)
    mask[inside] = 1.0
    taper = params.edge_taper_frac * (outer_norm - inner_norm)
    if taper > 0:
        for idx, radius in enumerate(r_norm):
            if radius < inner_norm or radius > outer_norm:
                continue
            dist_inner = (radius - inner_norm) / max(taper, 1e-6)
            dist_outer = (outer_norm - radius) / max(taper, 1e-6)
            taper_value = min(dist_inner, dist_outer, 1.0)
            mask[idx] = 0.5 - 0.5 * np.cos(np.pi * np.clip(taper_value, 0.0, 1.0))
    return mask


def _scoreCenter(
    feature_image: np.ndarray,
    annulus: Annulus,
    params: DetectorParams,
) -> float:
    coarse_params = DetectorParams(
        polar_n_theta=params.center_refine_polar_n_theta,
        polar_n_r=max(96, params.polar_n_r // 2),
        preblur_sigma_px=params.preblur_sigma_px,
        use_gradient_magnitude=params.use_gradient_magnitude,
        clip_outer_frac=params.clip_outer_frac,
        clip_inner_extra_frac=params.clip_inner_extra_frac,
        spoke_smooth_deg=params.spoke_smooth_deg,
        search_step_deg=params.search_step_deg,
        refine_window_deg=params.refine_window_deg,
        edge_taper_frac=params.edge_taper_frac,
        center_refine_radius_frac=params.center_refine_radius_frac,
        center_refine_stage_steps_frac=params.center_refine_stage_steps_frac,
        center_refine_polar_n_theta=params.center_refine_polar_n_theta,
        min_peak_prominence_ratio=params.min_peak_prominence_ratio,
    )
    polar = _polarWarp(feature_image, annulus, coarse_params)
    mask = _annulusRadialMask(annulus, coarse_params)
    signal = (polar * mask[np.newaxis, :]).sum(axis=1).astype(np.float64)
    if not np.isfinite(signal).all():
        signal = np.where(np.isfinite(signal), signal, 0.0)
    bin_per_deg = coarse_params.polar_n_theta / 360.0
    if params.spoke_smooth_deg > 0:
        sigma = max(0.5, params.spoke_smooth_deg * bin_per_deg)
        kernel_size = max(3, int(round(sigma * 6)) | 1)
        kernel = cv2.getGaussianKernel(kernel_size, sigma).flatten()
        extended = np.concatenate([signal, signal, signal])
        signal = np.convolve(extended, kernel, mode="same")[coarse_params.polar_n_theta : coarse_params.polar_n_theta * 2]
    thetas = np.arange(0.0, SPOKE_SEPARATION_DEG, 0.5, dtype=np.float32)
    offsets = np.array([0.0, 72.0, 144.0, 216.0, 288.0], dtype=np.float32)
    idx = ((thetas[:, None] + offsets[None, :]) * bin_per_deg) % coarse_params.polar_n_theta
    values = signal[idx.astype(np.int64)].sum(axis=1)
    finite = np.isfinite(values)
    if not finite.any():
        return 0.0
    values = values[finite]
    return float(np.max(values)) / max(abs(float(np.median(values))), 1e-9)


def _refineCenterForSpokes(
    image: np.ndarray,
    annulus: Annulus,
    params: DetectorParams,
) -> Annulus:
    if params.center_refine_radius_frac <= 0 or not params.center_refine_stage_steps_frac:
        return annulus
    height, width = image.shape[:2]
    min_dim = float(min(height, width))
    radius_px = params.center_refine_radius_frac * min_dim
    if radius_px < 1.0:
        return annulus

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    blurred = cv2.GaussianBlur(gray, (0, 0), params.preblur_sigma_px)
    if params.use_gradient_magnitude:
        grad_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
        feature_image = cv2.magnitude(grad_x, grad_y)
    else:
        feature_image = blurred.astype(np.float32)

    best_center_x = annulus.center_x
    best_center_y = annulus.center_y
    current_window = radius_px
    for step_frac in params.center_refine_stage_steps_frac:
        step_px = max(1.0, step_frac * min_dim)
        offsets = np.arange(-current_window, current_window + 1e-6, step_px)
        stage_best_x = best_center_x
        stage_best_y = best_center_y
        stage_best_score = -np.inf
        for offset_y in offsets:
            for offset_x in offsets:
                if offset_x * offset_x + offset_y * offset_y > current_window * current_window + 1e-6:
                    continue
                candidate = Annulus(
                    center_x=best_center_x + float(offset_x),
                    center_y=best_center_y + float(offset_y),
                    inner_radius=annulus.inner_radius,
                    outer_radius=annulus.outer_radius,
                )
                candidate = _clampAnnulusToImage(candidate, image.shape)
                if candidate.outer_radius <= candidate.inner_radius:
                    continue
                score = _scoreCenter(feature_image, candidate, params)
                if score > stage_best_score:
                    stage_best_score = score
                    stage_best_x = candidate.center_x
                    stage_best_y = candidate.center_y
        best_center_x = stage_best_x
        best_center_y = stage_best_y
        current_window = step_px
    return Annulus(
        center_x=best_center_x,
        center_y=best_center_y,
        inner_radius=annulus.inner_radius,
        outer_radius=annulus.outer_radius,
    )


def _radialIntegralSignal(
    image_gray: np.ndarray,
    annulus: Annulus,
    params: DetectorParams,
) -> np.ndarray:
    blurred = cv2.GaussianBlur(image_gray, (0, 0), params.preblur_sigma_px)
    if params.use_gradient_magnitude:
        grad_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
        feature_image = cv2.magnitude(grad_x, grad_y)
    else:
        feature_image = blurred.astype(np.float32)
    polar = _polarWarp(feature_image, annulus, params)
    mask = _annulusRadialMask(annulus, params)
    signal = (polar * mask[np.newaxis, :]).sum(axis=1)
    if not params.use_gradient_magnitude:
        signal = np.abs(signal - signal.mean())
    bin_per_deg = params.polar_n_theta / 360.0
    sigma_bins = max(0.5, params.spoke_smooth_deg * bin_per_deg)
    kernel_size = max(3, int(round(sigma_bins * 6)) | 1)
    kernel = cv2.getGaussianKernel(kernel_size, sigma_bins).flatten()
    extended = np.concatenate([signal, signal, signal])
    smoothed = np.convolve(extended, kernel, mode="same")
    signal_len = len(signal)
    return smoothed[signal_len : signal_len * 2]


def detectSpokeAngle(
    image: np.ndarray,
    annulus: Annulus,
    params: DetectorParams = DETECTOR_PARAMS,
) -> DetectorResult:
    annulus = _clampAnnulusToImage(annulus, image.shape)
    annulus = _refineCenterForSpokes(image, annulus, params)
    annulus = _clampAnnulusToImage(annulus, image.shape)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if annulus.outer_radius <= annulus.inner_radius or annulus.outer_radius < 10:
        return DetectorResult(
            angle_deg=float("nan"),
            score=0.0,
            success=False,
            failure_reason="annulus_invalid",
            prominence_ratio=1.0,
            annulus_used=annulus,
        )
    signal = _radialIntegralSignal(gray, annulus, params)
    thetas = np.arange(0.0, SPOKE_SEPARATION_DEG, params.search_step_deg, dtype=np.float32)
    offsets_deg = np.array([0.0, 72.0, 144.0, 216.0, 288.0], dtype=np.float32)
    bin_per_deg = params.polar_n_theta / 360.0
    angle_grid_deg = (thetas[:, None] + offsets_deg[None, :]) % 360.0
    angle_grid_bins = angle_grid_deg * bin_per_deg
    idx_lo = np.floor(angle_grid_bins).astype(np.int64) % params.polar_n_theta
    idx_hi = (idx_lo + 1) % params.polar_n_theta
    frac = (angle_grid_bins - np.floor(angle_grid_bins)).astype(np.float32)
    values = signal[idx_lo] * (1 - frac) + signal[idx_hi] * frac
    scores = values.sum(axis=1)
    finite_mask = np.isfinite(scores)
    if not finite_mask.any():
        return DetectorResult(
            angle_deg=float("nan"),
            score=float("nan"),
            success=False,
            failure_reason="nan_signal",
            prominence_ratio=1.0,
            annulus_used=annulus,
        )
    scores = np.where(finite_mask, scores, scores[finite_mask].min())
    peak_idx = int(np.argmax(scores))
    peak_theta = float(thetas[peak_idx])
    peak_score = float(scores[peak_idx])
    median_score = float(np.median(scores))
    prominence_ratio = peak_score / max(abs(median_score), 1e-9)
    success = prominence_ratio >= params.min_peak_prominence_ratio
    failure_reason = "" if success else "low_prominence"

    half_window = int(round(params.refine_window_deg / params.search_step_deg))
    if 1 <= peak_idx - half_window and peak_idx + half_window < len(scores):
        lo = peak_idx - half_window
        hi = peak_idx + half_window + 1
        xs = thetas[lo:hi].astype(np.float64)
        ys = scores[lo:hi].astype(np.float64)
        coeffs = np.polyfit(xs, ys, 2)
        if coeffs[0] < 0:
            refined = -coeffs[1] / (2 * coeffs[0])
            if xs[0] <= refined <= xs[-1]:
                peak_theta = float(refined % SPOKE_SEPARATION_DEG)

    return DetectorResult(
        angle_deg=peak_theta,
        score=peak_score,
        success=success,
        failure_reason=failure_reason,
        prominence_ratio=prominence_ratio,
        annulus_used=annulus,
    )


def maybeRunSpokeHome(
    gc: Any,
    irl: Any,
    irl_config: Any,
    vision: Any,
) -> bool:
    machine_setup = getattr(irl_config, "machine_setup", None)
    if machine_setup is None or not bool(getattr(machine_setup, "uses_classification_channel", False)):
        return False

    capture = None
    if hasattr(vision, "getCaptureThreadForRole"):
        capture = vision.getCaptureThreadForRole("classification_channel")
        if capture is None:
            capture = vision.getCaptureThreadForRole("carousel")
    if capture is None or getattr(capture, "latest_frame", None) is None:
        gc.logger.warning("C4 rev01 spoke home skipped: no live classification-channel frame")
        return False

    frame = capture.latest_frame.raw
    if frame is None:
        gc.logger.warning("C4 rev01 spoke home skipped: live frame is empty")
        return False

    geometry = loadSpokeHomeGeometry(frame.shape[:2])
    if geometry is None:
        gc.logger.warning("C4 rev01 spoke home skipped: saved classification-channel geometry incomplete")
        return False
    annulus, zero_point = geometry

    # This duplicates the older wall-phase work on purpose so the rev01 spoke-home
    # path stays isolated here, matching where Spencer already understood and used it.
    result = detectSpokeAngle(frame, annulus, DETECTOR_PARAMS)
    if not result.success:
        gc.logger.warning(
            f"C4 rev01 spoke home skipped: detector failed ({result.failure_reason}, prominence={result.prominence_ratio:.2f})"
        )
        return False

    reference_angle_deg = angleForPoint(
        zero_point[0],
        zero_point[1],
        result.annulus_used.center_x,
        result.annulus_used.center_y,
    )
    delta_output_deg = computeForwardAlignmentDeltaDeg(
        result.angle_deg,
        reference_angle_deg,
    )
    try:
        from toml_config import getClassificationChannelRev01Config
        from .rev01_config import configFromDict
        home_offset_output_deg = configFromDict(getClassificationChannelRev01Config()).home_offset_output_deg
    except Exception:
        home_offset_output_deg = 0.0
    delta_output_deg += home_offset_output_deg
    platter = C4FiveSectorPlatter.from_irl_config(irl_config)
    motor_microsteps = platter.output_degrees_to_motor_microsteps(delta_output_deg)
    stepper = getattr(irl, "classification_channel_rotor_stepper", None) or getattr(
        irl,
        "c_channel_4_rotor_stepper",
        None,
    )
    if stepper is None:
        gc.logger.warning("C4 rev01 spoke home skipped: classification stepper unavailable")
        return False

    gc.logger.info(
        "C4 rev01 spoke home: "
        f"spoke_angle={result.angle_deg:.2f} "
        f"reference_angle={reference_angle_deg:.2f} "
        f"home_offset={home_offset_output_deg:.2f} "
        f"forward_delta_output_deg={delta_output_deg:.2f} "
        f"motor_microsteps={motor_microsteps} "
        f"prominence={result.prominence_ratio:.2f}"
    )
    if motor_microsteps == 0:
        return True
    return bool(stepper.move_steps(int(motor_microsteps)))
