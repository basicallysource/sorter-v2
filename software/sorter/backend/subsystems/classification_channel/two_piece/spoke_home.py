import math
import time
from dataclasses import dataclass, replace
from typing import Any

import cv2
import numpy as np

from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter

from .constants import C4_TRAVEL_SIGN

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
    # Fins (spokes) on the rotor, evenly spaced.
    fin_count: int = 5

    @property
    def fin_pitch_deg(self) -> float:
        return 360.0 / max(1, self.fin_count)

    @property
    def fin_offsets_deg(self) -> np.ndarray:
        return np.arange(max(1, self.fin_count), dtype=np.float32) * np.float32(self.fin_pitch_deg)


@dataclass(frozen=True)
class DetectorResult:
    angle_deg: float
    score: float
    success: bool
    failure_reason: str
    prominence_ratio: float
    annulus_used: Annulus


DETECTOR_PARAMS = DetectorParams()


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
    fin_pitch_deg: float = 72.0,
) -> float:
    return (float(reference_angle_deg) - float(spoke_angle_deg)) % float(fin_pitch_deg)


def loadSpokeHomeGeometry(
    frame_shape: tuple[int, int],
) -> tuple[Annulus, tuple[float, float]] | None:
    """The classification channel's ring at this frame's size, and the point on
    its outer edge at the zones' reference angle, where a spoke rests at home."""
    from zones.store import loadChannel

    zones = loadChannel(4)
    if zones is None:
        return None
    frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
    ring = zones.scaledTo((frame_w, frame_h)).ring
    annulus = Annulus(
        center_x=ring.center[0],
        center_y=ring.center[1],
        inner_radius=ring.inner_radius,
        outer_radius=ring.outer_radius,
    )
    return annulus, _pointForAngle(
        annulus.center_x, annulus.center_y, annulus.outer_radius, zones.reference_angle
    )


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
        fin_count=params.fin_count,
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
    thetas = np.arange(0.0, params.fin_pitch_deg, 0.5, dtype=np.float32)
    offsets = params.fin_offsets_deg
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
    thetas = np.arange(0.0, params.fin_pitch_deg, params.search_step_deg, dtype=np.float32)
    offsets_deg = params.fin_offsets_deg
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
                peak_theta = float(refined % params.fin_pitch_deg)

    return DetectorResult(
        angle_deg=peak_theta,
        score=peak_score,
        success=success,
        failure_reason=failure_reason,
        prominence_ratio=prominence_ratio,
        annulus_used=annulus,
    )


def clearPiecesFromChannel(
    gc: Any,
    irl: Any,
    irl_config: Any,
) -> None:
    # Closed-loop pre-home purge: advance the carousel forward (same travel
    # direction as the normal classification flow) until the channel reads clear,
    # using the shared routine the C4 stuck-incident auto-resolve also uses so
    # both agree on direction and on when the channel is actually empty.
    from .channel_clear import clearChannelByAdvancing

    clearChannelByAdvancing(
        gc, irl, irl_config, label="C4 rev01 spoke home pre-purge"
    )


def maybeRunSpokeHome(
    gc: Any,
    irl: Any,
    irl_config: Any,
    vision: Any,
) -> bool:
    clearPiecesFromChannel(gc, irl, irl_config)
    # Where a fin rests over the exit, in motor microsteps, once homing has put
    # it there (read by the classification flow); None until then.
    irl.c4_fin_rest_microsteps = None
    try:
        from toml_config import getClassificationChannelRev01Config
        from .rev01_config import configFromDict
        rotor = configFromDict(getClassificationChannelRev01Config())
    except Exception:
        from .rev01_config import defaultConfig
        rotor = defaultConfig()
    params = replace(DETECTOR_PARAMS, fin_count=max(1, int(rotor.fin_count)))

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
    if rotor.fin_at_exit:
        # Skip the first second: the lamp has only just come on.
        result = readFinAngle(capture, annulus, params, newer_than=time.time() + 1.0)
        if result is None:
            gc.logger.warning("C4 rev01 spoke home skipped: the fins did not read the same in 3 frames running")
            return False
    else:
        result = detectSpokeAngle(frame, annulus, params)
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
    platter = C4FiveSectorPlatter.from_irl_config(irl_config)
    fin_target = _finOverExitAngle(rotor) if rotor.fin_at_exit else None
    if fin_target is not None:
        # A fin's exit-side edge on the exit zone's far edge: the fin is turned
        # there the way the channel travels, never back.
        target_deg, reverse = fin_target
        ahead = (result.angle_deg - target_deg) if reverse else (target_deg - result.angle_deg)
        delta_output_deg = ahead % params.fin_pitch_deg
        home_offset_output_deg = 0.0
        reference_angle_deg = target_deg
        motor_microsteps = platter.output_degrees_to_motor_microsteps(C4_TRAVEL_SIGN * delta_output_deg)
    else:
        delta_output_deg = computeForwardAlignmentDeltaDeg(
            result.angle_deg,
            reference_angle_deg,
            params.fin_pitch_deg,
        )
        home_offset_output_deg = float(rotor.home_offset_output_deg)
        delta_output_deg += home_offset_output_deg
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
    if fin_target is not None:
        irl.c4_fin_rest_microsteps = int(stepper.position) + int(motor_microsteps)
    if motor_microsteps == 0:
        return True
    return bool(stepper.move_steps(int(motor_microsteps)))


def readFinAngle(
    capture: Any,
    annulus: Annulus,
    params: DetectorParams,
    *,
    newer_than: float,
    reads: int = 3,
    agree_deg: float = 2.0,
    timeout_s: float = 4.0,
) -> DetectorResult | None:
    """The fins' angle, read from the camera's frames taken after
    `newer_than` (time.time()), once `reads` frames in a row agree within
    `agree_deg`. A frame taken while the camera's exposure is still settling
    (just after the lamp comes on) reads a confident but wrong angle, so one
    frame is never enough. Frames are read at half size, around the zones'
    centre. None if they do not agree in time."""
    pitch = params.fin_pitch_deg
    half = Annulus(
        center_x=annulus.center_x / 2.0,
        center_y=annulus.center_y / 2.0,
        inner_radius=annulus.inner_radius / 2.0,
        outer_radius=annulus.outer_radius / 2.0,
    )
    fast = replace(params, center_refine_radius_frac=0.0)
    results: list[DetectorResult] = []
    seen_at = None
    deadline = time.time() + float(timeout_s)
    while time.time() < deadline:
        frame = getattr(capture, "latest_frame", None)
        stamp = getattr(frame, "timestamp", None)
        raw = getattr(frame, "raw", None)
        if raw is None or stamp is None or stamp <= newer_than or stamp == seen_at:
            time.sleep(0.02)
            continue
        seen_at = stamp
        small = cv2.resize(raw, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        result = detectSpokeAngle(small, half, fast)
        if not result.success:
            results.clear()
            continue
        results.append(result)
        if len(results) < reads:
            continue
        last = results[-reads:]
        first = last[0].angle_deg
        offsets = [((r.angle_deg - first + pitch / 2.0) % pitch) - pitch / 2.0 for r in last]
        if max(offsets) - min(offsets) <= agree_deg:
            angle = (first + sum(offsets) / len(offsets)) % pitch
            return replace(last[-1], angle_deg=angle)
    return None


def finMoveToExit(angle_deg: float, rotor: Any) -> float | None:
    """How far on, the way the channel travels, a fin at `angle_deg` (or any
    fin, they repeat every pitch) must turn to rest over the exit; None
    without saved zones."""
    target = _finOverExitAngle(rotor)
    if target is None:
        return None
    target_deg, reverse = target
    pitch = 360.0 / max(1, int(rotor.fin_count))
    ahead = (angle_deg - target_deg) if reverse else (target_deg - angle_deg)
    return ahead % pitch


def _finOverExitAngle(rotor: Any) -> tuple[float, bool] | None:
    """Where a fin's middle rests so its exit-side edge is on the exit zone's
    far edge (the one pieces leave it by), in the zones' angles, and whether the
    channel travels toward lower angles. None without saved zones."""
    from zones.store import loadChannel

    zones = loadChannel(4)
    if zones is None or zones.exit is None:
        return None
    reverse = bool(zones.reverse)
    half = float(rotor.fin_width_deg) / 2.0
    if reverse:
        return (float(zones.exit.start) - half) % 360.0, True
    return (float(zones.exit.end) + half) % 360.0, False
