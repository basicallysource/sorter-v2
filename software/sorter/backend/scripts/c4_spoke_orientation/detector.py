from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class Annulus:
    """Operator-defined classification-channel annulus in *image pixels*.

    center_x, center_y: pixel coordinates of the platter center (where the
        hub sits).
    inner_radius: radius (px) where the central hub ends and the visible
        spoke region begins.
    outer_radius: radius (px) of the outer rim of the platter — the edge
        beyond which we no longer want to consider pixels.
    """
    center_x: float
    center_y: float
    inner_radius: float
    outer_radius: float


@dataclass(frozen=True)
class DetectorParams:
    """All knobs that affect the quality of the spoke-orientation detection.

    Anything outside this class is a fixed algorithmic detail; everything
    that could plausibly need tuning lives here.
    """

    # --- Geometry resolution ---
    polar_n_theta: int = 1080
    """Angular resolution of the polar warp. 1080 = 1/3-degree bins."""
    polar_n_r: int = 256
    """Radial resolution of the polar warp."""

    # --- Preprocessing ---
    preblur_sigma_px: float = 1.5
    """Gaussian sigma applied to the grayscale image before polar warp.
    Reduces sensor noise and small specular highlights."""
    use_gradient_magnitude: bool = True
    """If True, score on Sobel gradient magnitude (edge energy). If False,
    score on raw intensity deviation. Gradient is more invariant to
    spoke-vs-sector brightness sign across machines."""
    clip_outer_frac: float = 0.98
    """Inner edge of the polar warp ignored as fraction of outer radius —
    cuts the very-outer rim where the wall curls and dominates edges."""
    clip_inner_extra_frac: float = 0.05
    """Additional padding (fraction of outer radius) added to the inner
    radius to push past the hub plastic lip."""

    # --- Angular template ---
    spoke_smooth_deg: float = 5.0
    """Gaussian smoothing in the theta direction applied to the radial
    integral signal before scoring. Must be wider than spoke thickness
    so each spoke shows up as ONE peak (not two edges)."""
    search_step_deg: float = 0.25
    """Step size for the brute-force angular search in [0, 72) degrees."""

    # --- Sub-pixel refinement ---
    refine_window_deg: float = 1.0
    """After brute search, fit a parabola to scores in ±this window
    around the peak to refine."""

    # --- Annulus mask softening ---
    edge_taper_frac: float = 0.04
    """Cosine taper width as a fraction of (r_out-r_in), applied at both
    the inner and outer radial limits inside the annulus, so the rim
    transition does not contribute spurious gradient energy."""

    # --- Center refinement (coarse-to-fine 2D search) ---
    center_refine_radius_frac: float = 0.15
    """Allow the spoke center to slide up to ±this fraction of the
    image's min dimension away from the operator/Hough-supplied annulus
    center, to absorb camera-tilt / off-axis-mount / mis-annotated
    centers. 0.15 = ±15 %."""
    center_refine_stage_steps_frac: tuple[float, ...] = (0.024, 0.008, 0.0025)
    """Step sizes (as fractions of min image dim) for the coarse-to-fine
    grid search stages. The first stage covers the full
    ``center_refine_radius_frac`` window at the coarsest step; subsequent
    stages narrow the window to ±step_prev around the previous best and
    sample with the next-finer step."""
    center_refine_polar_n_theta: int = 360
    """Polar-warp theta resolution used during the (much slower) center
    refinement search. Lower than the final-pass ``polar_n_theta`` for
    speed; we only need rough scores to pick a winning center."""

    # --- Acceptance / confidence ---
    min_peak_prominence_ratio: float = 1.20
    """A detection is considered successful only if the best-spoke score
    is at least this ratio above the *median* score over the 0..72°
    sweep. Below that, the detector reports failure (success=False) and
    the visualization should call attention to it (e.g. red overlay)."""


@dataclass(frozen=True)
class HubAutoDetectParams:
    """Knobs for auto-locating the platter (outer rim) center in an image.

    The detector will Hough-search for a circle whose radius is in
    [min_radius_frac, max_radius_frac] * min(W,H), then pick the one
    whose center is closest to the per-machine default center.
    """
    enabled: bool = True
    min_radius_frac: float = 0.28
    max_radius_frac: float = 0.50
    search_window_frac: float = 0.18
    """Detected center must lie within this fraction of min(W,H) of the
    hand-tuned default center, otherwise we fall back to the default."""
    dp: float = 1.5
    param1: float = 120.0
    param2: float = 60.0
    downscale_max_dim: int = 1024


@dataclass(frozen=True)
class DetectorResult:
    angle_deg: float
    """Detected spoke orientation in [0, 72) degrees. Each of the five
    spokes sits at this angle + k*72 around the center, where the angle
    is measured CCW from +x in image coordinates (y-down)."""
    score: float
    """Raw peak score from the search — only useful for relative
    comparison between candidate angles, not absolute confidence."""
    success: bool
    """True iff the score-curve had a clean peak above the configured
    prominence ratio. False means the detector did not find a
    convincing 5-spoke pattern; ``angle_deg`` should NOT be trusted."""
    failure_reason: str
    """Empty string on success. Otherwise a short tag explaining why
    the detection was rejected (``low_prominence``, ``nan_signal``,
    ``annulus_invalid``)."""
    prominence_ratio: float
    """peak / median of the score curve. >= 1.0 always; the further
    above 1.0, the more confident."""
    annulus_used: Annulus
    """The annulus actually used for detection — may differ from the
    hand-tuned default if hub auto-detection succeeded."""
    score_curve: np.ndarray = field(repr=False)
    """1D array of len = len(thetas_searched), the cost-function values
    over the candidate angles. Useful for debugging / plotting."""
    thetas_searched_deg: np.ndarray = field(repr=False)
    """The angle grid corresponding to score_curve."""


def autoDetectAnnulus(
    image: np.ndarray, default: Annulus, params: HubAutoDetectParams
) -> Annulus:
    """Try to refine the annulus center + outer radius from the image.

    Falls back to ``default`` if no acceptable circle is found.
    """
    if not params.enabled:
        return default
    h, w = image.shape[:2]
    min_dim = min(h, w)
    scale = min(1.0, params.downscale_max_dim / max(h, w))
    if scale < 1.0:
        small = cv2.resize(image, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    else:
        small = image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    gray = cv2.medianBlur(gray, 5)
    s_min_dim = min(gray.shape[:2])
    min_r = int(params.min_radius_frac * s_min_dim)
    max_r = int(params.max_radius_frac * s_min_dim)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=params.dp,
        minDist=max(50, min_r),
        param1=params.param1, param2=params.param2,
        minRadius=min_r, maxRadius=max_r,
    )
    if circles is None or len(circles[0]) == 0:
        return default
    candidates = circles[0]
    default_cx_small = default.center_x * scale
    default_cy_small = default.center_y * scale
    window_px = params.search_window_frac * s_min_dim
    best = None
    best_dist = float("inf")
    for cx, cy, r in candidates:
        d = float(np.hypot(cx - default_cx_small, cy - default_cy_small))
        if d <= window_px and d < best_dist:
            best_dist = d
            best = (cx, cy, r)
    if best is None:
        return default
    cx, cy, r = best
    return Annulus(
        center_x=float(cx / scale),
        center_y=float(cy / scale),
        inner_radius=default.inner_radius,
        outer_radius=float(r / scale),
    )


def _clampAnnulusToImage(annulus: Annulus, image_shape: tuple[int, int]) -> Annulus:
    h, w = image_shape[:2]
    max_radius = min(
        annulus.center_x, w - annulus.center_x,
        annulus.center_y, h - annulus.center_y,
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
    image: np.ndarray, annulus: Annulus, params: DetectorParams
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


def _annulusRadialMask(annulus: Annulus, params: DetectorParams) -> np.ndarray:
    n_r = params.polar_n_r
    r_norm = np.linspace(0.0, 1.0, n_r, dtype=np.float32)
    inner_norm = (annulus.inner_radius / annulus.outer_radius) + params.clip_inner_extra_frac
    outer_norm = params.clip_outer_frac
    mask = np.zeros(n_r, dtype=np.float32)
    inside = (r_norm >= inner_norm) & (r_norm <= outer_norm)
    mask[inside] = 1.0
    taper = params.edge_taper_frac * (outer_norm - inner_norm)
    if taper > 0:
        for i, r in enumerate(r_norm):
            if r < inner_norm or r > outer_norm:
                continue
            d_in = (r - inner_norm) / max(taper, 1e-6)
            d_out = (outer_norm - r) / max(taper, 1e-6)
            t = min(d_in, d_out, 1.0)
            mask[i] = 0.5 - 0.5 * np.cos(np.pi * np.clip(t, 0.0, 1.0))
    return mask


def _scoreCenter(
    feat: np.ndarray, annulus: Annulus, params: DetectorParams,
) -> float:
    """Cheap 5-spoke prominence score used by the center-refinement grid.

    ``feat`` is the precomputed gradient-magnitude (or intensity) feature
    image. Returns peak/median of the 5-spoke template over a coarse
    theta sweep at a reduced polar resolution."""
    coarse_params = replace(
        params,
        polar_n_theta=params.center_refine_polar_n_theta,
        polar_n_r=max(96, params.polar_n_r // 2),
    )
    polar = _polarWarp(feat, annulus, coarse_params)
    mask = _annulusRadialMask(annulus, coarse_params)
    signal = (polar * mask[np.newaxis, :]).sum(axis=1).astype(np.float64)
    if not np.isfinite(signal).all():
        signal = np.where(np.isfinite(signal), signal, 0.0)
    n_theta = coarse_params.polar_n_theta
    bin_per_deg = n_theta / 360.0
    if params.spoke_smooth_deg > 0:
        sigma = max(0.5, params.spoke_smooth_deg * bin_per_deg)
        ksize = max(3, int(round(sigma * 6)) | 1)
        kernel = cv2.getGaussianKernel(ksize, sigma).flatten()
        ext = np.concatenate([signal, signal, signal])
        signal = np.convolve(ext, kernel, mode="same")[n_theta:2 * n_theta]
    thetas = np.arange(0.0, 72.0, 0.5, dtype=np.float32)
    offsets = np.array([0.0, 72.0, 144.0, 216.0, 288.0], dtype=np.float32)
    idx = ((thetas[:, None] + offsets[None, :]) * bin_per_deg) % n_theta
    vals = signal[idx.astype(np.int64)].sum(axis=1)
    finite = np.isfinite(vals)
    if not finite.any():
        return 0.0
    vals = vals[finite]
    return float(np.max(vals)) / max(abs(float(np.median(vals))), 1e-9)


def _refineCenterForSpokes(
    image: np.ndarray, annulus: Annulus, params: DetectorParams,
) -> Annulus:
    if params.center_refine_radius_frac <= 0 or not params.center_refine_stage_steps_frac:
        return annulus
    h, w = image.shape[:2]
    min_dim = float(min(h, w))
    radius_px = params.center_refine_radius_frac * min_dim
    if radius_px < 1.0:
        return annulus

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    blurred = cv2.GaussianBlur(gray, (0, 0), params.preblur_sigma_px)
    if params.use_gradient_magnitude:
        gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
        feat = cv2.magnitude(gx, gy)
    else:
        feat = blurred.astype(np.float32)

    best_cx = annulus.center_x
    best_cy = annulus.center_y
    best_prom = -np.inf
    cur_window = radius_px
    for stage_idx, step_frac in enumerate(params.center_refine_stage_steps_frac):
        step_px = max(1.0, step_frac * min_dim)
        offsets = np.arange(-cur_window, cur_window + 1e-6, step_px)
        stage_best_cx, stage_best_cy = best_cx, best_cy
        stage_best_prom = -np.inf
        for dy in offsets:
            for dx in offsets:
                if dx * dx + dy * dy > cur_window * cur_window + 1e-6:
                    continue
                cand = Annulus(
                    center_x=best_cx + float(dx),
                    center_y=best_cy + float(dy),
                    inner_radius=annulus.inner_radius,
                    outer_radius=annulus.outer_radius,
                )
                cand = _clampAnnulusToImage(cand, image.shape)
                if cand.outer_radius <= cand.inner_radius:
                    continue
                prom = _scoreCenter(feat, cand, params)
                if prom > stage_best_prom:
                    stage_best_prom = prom
                    stage_best_cx = cand.center_x
                    stage_best_cy = cand.center_y
        best_cx, best_cy = stage_best_cx, stage_best_cy
        best_prom = max(best_prom, stage_best_prom)
        # narrow window for next stage to ±(previous step)
        cur_window = step_px
    return Annulus(
        center_x=best_cx, center_y=best_cy,
        inner_radius=annulus.inner_radius, outer_radius=annulus.outer_radius,
    )


def _radialIntegralSignal(
    image_gray: np.ndarray, annulus: Annulus, params: DetectorParams
) -> np.ndarray:
    blurred = cv2.GaussianBlur(
        image_gray, ksize=(0, 0), sigmaX=params.preblur_sigma_px
    )

    if params.use_gradient_magnitude:
        gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
        feat = cv2.magnitude(gx, gy)
    else:
        feat = blurred.astype(np.float32)

    polar = _polarWarp(feat, annulus, params)
    mask = _annulusRadialMask(annulus, params)
    weighted = polar * mask[np.newaxis, :]
    signal = weighted.sum(axis=1)

    if not params.use_gradient_magnitude:
        signal = np.abs(signal - signal.mean())

    bin_per_deg = params.polar_n_theta / 360.0
    sigma_bins = max(0.5, params.spoke_smooth_deg * bin_per_deg)
    ksize = max(3, int(round(sigma_bins * 6)) | 1)
    kernel = cv2.getGaussianKernel(ksize, sigma_bins).flatten()
    extended = np.concatenate([signal, signal, signal])
    sm = np.convolve(extended, kernel, mode="same")
    n = len(signal)
    return sm[n : 2 * n]


def detectSpokeAngle(
    image: np.ndarray,
    annulus: Annulus,
    params: Optional[DetectorParams] = None,
    hub_params: Optional[HubAutoDetectParams] = None,
) -> DetectorResult:
    if params is None:
        params = DetectorParams()
    if hub_params is None:
        hub_params = HubAutoDetectParams()

    annulus = autoDetectAnnulus(image, annulus, hub_params)
    annulus = _clampAnnulusToImage(annulus, image.shape)
    annulus = _refineCenterForSpokes(image, annulus, params)
    annulus = _clampAnnulusToImage(annulus, image.shape)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if annulus.outer_radius <= annulus.inner_radius or annulus.outer_radius < 10:
        empty_scores = np.zeros(int(72.0 / params.search_step_deg) + 1, dtype=np.float32)
        empty_thetas = np.arange(0.0, 72.0, params.search_step_deg, dtype=np.float32)
        return DetectorResult(
            angle_deg=float("nan"),
            score=0.0,
            success=False,
            failure_reason="annulus_invalid",
            prominence_ratio=1.0,
            annulus_used=annulus,
            score_curve=empty_scores,
            thetas_searched_deg=empty_thetas,
        )
    signal = _radialIntegralSignal(gray, annulus, params)
    n_theta = params.polar_n_theta

    thetas = np.arange(0.0, 72.0, params.search_step_deg, dtype=np.float32)
    offsets_deg = np.array([0.0, 72.0, 144.0, 216.0, 288.0], dtype=np.float32)
    bin_per_deg = n_theta / 360.0

    angle_grid_deg = (thetas[:, None] + offsets_deg[None, :]) % 360.0
    angle_grid_bins = angle_grid_deg * bin_per_deg
    idx_lo = np.floor(angle_grid_bins).astype(np.int64) % n_theta
    idx_hi = (idx_lo + 1) % n_theta
    frac = (angle_grid_bins - np.floor(angle_grid_bins)).astype(np.float32)
    vals = signal[idx_lo] * (1 - frac) + signal[idx_hi] * frac
    scores = vals.sum(axis=1)

    finite_mask = np.isfinite(scores)
    if not finite_mask.any():
        return DetectorResult(
            angle_deg=float("nan"),
            score=float("nan"),
            success=False,
            failure_reason="nan_signal",
            prominence_ratio=1.0,
            annulus_used=annulus,
            score_curve=scores,
            thetas_searched_deg=thetas,
        )
    scores = np.where(finite_mask, scores, scores[finite_mask].min())
    peak_idx = int(np.argmax(scores))
    peak_theta = float(thetas[peak_idx])
    peak_score = float(scores[peak_idx])
    median_score = float(np.median(scores))
    prominence = peak_score / max(abs(median_score), 1e-9)
    success = prominence >= params.min_peak_prominence_ratio
    failure_reason = "" if success else "low_prominence"

    half_w = int(round(params.refine_window_deg / params.search_step_deg))
    if 1 <= peak_idx - half_w and peak_idx + half_w < len(scores):
        lo = peak_idx - half_w
        hi = peak_idx + half_w + 1
        xs = thetas[lo:hi].astype(np.float64)
        ys = scores[lo:hi].astype(np.float64)
        coeffs = np.polyfit(xs, ys, 2)
        if coeffs[0] < 0:
            refined = -coeffs[1] / (2 * coeffs[0])
            if xs[0] <= refined <= xs[-1]:
                peak_theta = float(refined % 72.0)

    return DetectorResult(
        angle_deg=peak_theta,
        score=peak_score,
        success=success,
        failure_reason=failure_reason,
        prominence_ratio=prominence,
        annulus_used=annulus,
        score_curve=scores,
        thetas_searched_deg=thetas,
    )


def defaultAnnulusForMachine(machine_slug: str, image_shape: tuple[int, int]) -> Annulus:
    """Hand-tuned per-machine annulus heuristics expressed as fractions of
    the image, so they work across both 1080p and 4K captures of the same
    rig. Tune by visual inspection of one image per machine.

    image_shape: (height, width).
    """
    h, w = image_shape
    min_dim = float(min(h, w))
    defaults = {
        "sorty": dict(cx=0.500, cy=0.500, r_in=0.075, r_out=0.410),
        "sorter_v2_v2.5": dict(cx=0.500, cy=0.510, r_in=0.075, r_out=0.395),
        "sorter_v2_v2_cyrill": dict(cx=0.500, cy=0.500, r_in=0.075, r_out=0.410),
        "dave_s_machine": dict(cx=0.500, cy=0.380, r_in=0.060, r_out=0.420),
        "still_fresh": dict(cx=0.590, cy=0.570, r_in=0.055, r_out=0.410),
    }
    d = defaults.get(machine_slug, dict(cx=0.5, cy=0.5, r_in=0.08, r_out=0.40))
    return Annulus(
        center_x=d["cx"] * w,
        center_y=d["cy"] * h,
        inner_radius=d["r_in"] * min_dim,
        outer_radius=d["r_out"] * min_dim,
    )


def drawDetection(
    image: np.ndarray, annulus: Annulus, result: DetectorResult
) -> np.ndarray:
    out = image.copy()
    cx, cy = int(round(annulus.center_x)), int(round(annulus.center_y))
    spoke_color = (0, 255, 0) if result.success else (0, 0, 255)
    annulus_color = (0, 255, 255) if result.success else (0, 0, 255)

    cv2.circle(out, (cx, cy), max(1, int(round(annulus.outer_radius))), annulus_color, 2)
    cv2.circle(out, (cx, cy), max(1, int(round(annulus.inner_radius))), annulus_color, 2)
    cv2.circle(out, (cx, cy), 4, (0, 0, 255), -1)

    if result.success:
        for k in range(5):
            theta = np.deg2rad(result.angle_deg + 72.0 * k)
            x1 = cx + annulus.inner_radius * np.cos(theta)
            y1 = cy + annulus.inner_radius * np.sin(theta)
            x2 = cx + annulus.outer_radius * np.cos(theta)
            y2 = cy + annulus.outer_radius * np.sin(theta)
            cv2.line(out, (int(round(x1)), int(round(y1))),
                     (int(round(x2)), int(round(y2))), spoke_color, 3)
        label = f"theta = {result.angle_deg:.2f} deg  prom = {result.prominence_ratio:.2f}x"
    else:
        h, w = out.shape[:2]
        thickness = max(8, min(w, h) // 60)
        cv2.rectangle(out, (0, 0), (w - 1, h - 1), (0, 0, 255), thickness)
        label = f"FAIL ({result.failure_reason})  prom = {result.prominence_ratio:.2f}x"

    cv2.putText(out, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(out, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return out
