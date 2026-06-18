import sys
import os
import time
import threading
import glob as globmod
from datetime import datetime

import random

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
from vision import VisionManager
from vision.hsv_correction import loadHsvCorrection, bgrToHsvScaled, isNoop
from vision.diff_configs import DEFAULT_CLASSIFICATION_DIFF_CONFIG
from blob_manager import BLOB_DIR, getClassificationPolygons, getChannelPolygons

LOW_SAT_THRESH = DEFAULT_CLASSIFICATION_DIFF_CONFIG.low_sat_thresh
# Capture the envelope at the same working resolution the detector runs at, with
# the downscale applied to BGR before the HSV conversion (bgrToHsvScaled). The
# runtime getters use this same scale, so the stored envelope and live frames
# share one transform. Changing it (here or in the config) invalidates baselines.
CLASSIFICATION_SCALE = DEFAULT_CLASSIFICATION_DIFF_CONFIG.scale

MAX_FRAMES = 64
DEGREES_PER_FRAME = -90
MOVE_TIMEOUT_MS = 2000

# Chute wiggle: vibrate the chute while capturing the baseline so the envelope
# includes the small pixel shifts that normal machine vibration causes, making
# runtime detection robust to it. 5 Hz approximates the operating vibration.
DEFAULT_CHUTE_WIGGLE_HZ = 5.0
DEFAULT_CHUTE_WIGGLE_STEPS = 40   # microsteps amplitude of the back-and-forth


class ChuteWiggler:
    """Oscillate the chute stepper +/- amplitude at a fixed frequency in a
    background thread. Moves are net-zero (alternating sign), and any leftover
    half-cycle is corrected on stop, so the chute returns to its start position.
    The MCU bus serializes transactions, so this runs safely alongside the
    carousel moves in the capture loop."""

    def __init__(self, stepper, hz: float, amplitude_steps: int, logger=None):
        self._stepper = stepper
        self._half_period = 1.0 / (2.0 * hz) if hz > 0 else 0.083
        self._amplitude = int(amplitude_steps)
        self._logger = logger
        self._stop = threading.Event()
        self._thread = None
        self._net = 0

    def start(self) -> None:
        self._stop.clear()
        self._net = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        direction = 1
        warned = False
        while not self._stop.is_set():
            try:
                self._stepper.move_steps(direction * self._amplitude)
                self._net += direction * self._amplitude
            except Exception as e:  # don't let a transient bus error kill the wiggle
                if self._logger and not warned:
                    self._logger.warn(f"chute wiggle move failed (continuing): {e}")
                    warned = True
            direction = -direction
            self._stop.wait(self._half_period)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        # Return the chute to where it started if we ended mid-cycle.
        if self._net != 0:
            try:
                self._stepper.move_steps(-self._net)
            except Exception:
                pass
            self._net = 0

# Reference for the post-sweep sanity check. The runtime HSV detection treats
# the magenta floor as background; if the color-calibration step recorded its
# expected hue/saturation we compare the captured envelope's mean against it.
# This file is optional — the tile-target reference_snapshot.json does NOT
# contain a background entry, so the check is skipped unless this is provided.
BACKGROUND_REF_PATH = (
    Path(__file__).resolve().parent.parent / "calibration" / "background_reference.json"
)
SANITY_HUE_TOLERANCE = 10     # OpenCV 8-bit hue units
SANITY_SAT_TOLERANCE = 30     # 0-255

# OpenCV 8-bit hue has period 180. The envelope min/max are naive (non-circular),
# which is safe because getLatestHSV applies a constant hue rotation (see
# vision.hsv_correction.HUE_ROTATION) that moves the magenta background to ~H90,
# far from the 0/180 wrap. Both calibration and runtime rotate identically, so
# the stored envelope and live frames share the same rotated hue space.

# Stable-pixel mask thresholds. A pixel is kept for detection only if its hue,
# saturation, AND value are all stable across the carousel sweep. Edge pixels
# that wobble between floor / tray-rim / marker / shadow as the trays rotate
# have huge variance -> their min/max envelope balloons until it swallows any
# piece (the [0,235] hue envelopes you see at the bottom edge). Masking them out
# is correct: an unreliable pixel should be excluded, not made permissive.
# Value (brightness) is the strongest "not always floor" signal -- the backlit
# floor glows bright, anything that isn't floor is darker. Defaults are CLI
# overridable; the sweep prints the std distribution so they can be tuned.
DEFAULT_MAX_HUE_STD = 12.0    # circular hue std, OpenCV 8-bit hue units
DEFAULT_MAX_SAT_STD = 25.0    # saturation std, 0-255
DEFAULT_MAX_VAL_STD = 30.0    # value/brightness std, 0-255

# Envelope percentile: the final envelope is [P, 100-P] instead of naive min/max,
# so 1-2 stray frames per pixel (registration glints, tray-rim flashes) don't
# balloon it. P=2 clips ~1.3 of 64 frames at each tail -- enough for the observed
# rare excursions while barely touching clean pixels.
DEFAULT_PERCENTILE = 2.0


def _circularHueStd(sum_cos: np.ndarray, sum_sin: np.ndarray, n: int) -> np.ndarray:
    """Per-pixel circular standard deviation of hue (OpenCV 8-bit, period 180),
    from accumulated cos/sin sums. Wrap-aware, so a pixel oscillating across the
    0/180 boundary isn't falsely flagged. Returns std in hue units."""
    C = sum_cos / n
    S = sum_sin / n
    R = np.clip(np.sqrt(C * C + S * S), 1e-6, 1.0)
    std_rad = np.sqrt(-2.0 * np.log(R))
    return std_rad * (90.0 / np.pi)  # radians -> hue units (period 180)


def computeStableMask(
    h_frames: list[np.ndarray],
    s_frames: list[np.ndarray],
    v_frames: list[np.ndarray],
    max_hue_std: float,
    max_sat_std: float,
    max_val_std: float,
) -> tuple[np.ndarray, dict]:
    """Build a 255/0 mask of pixels stable enough across the sweep to be trusted
    for detection. Accumulates per-pixel circular-hue / saturation / value std
    incrementally (no giant float stack), then keeps pixels under all three
    thresholds. Returns (mask_uint8, stats)."""
    n = len(h_frames)
    shape = h_frames[0].shape
    sum_cos = np.zeros(shape, np.float64)
    sum_sin = np.zeros(shape, np.float64)
    sum_s = np.zeros(shape, np.float64)
    sum_s2 = np.zeros(shape, np.float64)
    sum_v = np.zeros(shape, np.float64)
    sum_v2 = np.zeros(shape, np.float64)
    for h, s, v in zip(h_frames, s_frames, v_frames):
        ang = h.astype(np.float64) * (np.pi / 90.0)  # 0-179 -> 0-2pi
        sum_cos += np.cos(ang)
        sum_sin += np.sin(ang)
        sf = s.astype(np.float64)
        sum_s += sf
        sum_s2 += sf * sf
        vf = v.astype(np.float64)
        sum_v += vf
        sum_v2 += vf * vf

    h_std = _circularHueStd(sum_cos, sum_sin, n)
    s_std = np.sqrt(np.maximum(0.0, sum_s2 / n - (sum_s / n) ** 2))
    v_std = np.sqrt(np.maximum(0.0, sum_v2 / n - (sum_v / n) ** 2))

    stable = (h_std <= max_hue_std) & (s_std <= max_sat_std) & (v_std <= max_val_std)
    mask = stable.astype(np.uint8) * 255
    stats = {
        "masked_pct": 100.0 * float(1.0 - stable.mean()),
        "h_std_p50": float(np.percentile(h_std, 50)),
        "h_std_p95": float(np.percentile(h_std, 95)),
        "s_std_p50": float(np.percentile(s_std, 50)),
        "s_std_p95": float(np.percentile(s_std, 95)),
        "v_std_p50": float(np.percentile(v_std, 50)),
        "v_std_p95": float(np.percentile(v_std, 95)),
    }
    return mask, stats


def loadExistingChannel(baseline_dir: Path, prefix: str, channel: str) -> list[np.ndarray]:
    """Load existing per-frame arrays for one channel ('h'/'s'/'v')."""
    frames = []
    paths = sorted(globmod.glob(str(baseline_dir / f"{prefix}_{channel}frame_*.png")))
    for p in paths:
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            frames.append(img)
    return frames


def saveEnvelope(baseline_dir: Path, prefix: str, channel: str, frames: list[np.ndarray],
                 percentile: float = 0.0) -> None:
    """Write low/high envelope PNGs for one channel across the rotational sweep.

    `percentile` makes the envelope robust to rare per-pixel excursions (a stray
    glint / tray-rim flash on 1-2 of the 64 frames otherwise balloons naive
    min/max). With percentile=P the envelope is [P, 100-P] instead of [min, max];
    P=0 is exactly min/max. Hue is safe to percentile linearly because rotateHue
    has moved the background off the 0/180 wrap."""
    stack = np.stack(frames, axis=0)
    if percentile > 0:
        lo = np.percentile(stack, percentile, axis=0)
        hi = np.percentile(stack, 100.0 - percentile, axis=0)
    else:
        lo = np.min(stack, axis=0)
        hi = np.max(stack, axis=0)
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_{channel}_min.png"), lo.astype(np.uint8))
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_{channel}_max.png"), hi.astype(np.uint8))


# Baseline camera targets: prefix (file/heatmap key) -> vision.getFrame() name.
CAM_FRAME_NAMES = {
    "top": "classification_top",
    "bottom": "classification_bottom",
    "carousel": "carousel",
}
# Which prefixes each --camera selection captures.
CAMERA_GROUPS = {
    "classification": ["top", "bottom"],
    "carousel": ["carousel"],
    "all": ["top", "bottom", "carousel"],
}


def getLatestHSV(vision: VisionManager, cam: str, correction) -> np.ndarray | None:
    """Working-resolution HSV (with optional correction) of the latest frame for
    the target camera (cam is the file prefix: 'top'/'bottom'/'carousel').

    Mirrors the runtime path (vision_manager._bgrToHSV): the BGR frame is
    downscaled by CLASSIFICATION_SCALE, then cvtColor + hue rotation +
    correction. Capturing the envelope at the same working resolution and with
    the same downscale-before-convert order the detector uses keeps the stored
    envelope and live frames on one identical transform."""
    frame = vision.getFrame(CAM_FRAME_NAMES[cam])
    if frame is None:
        return None
    return bgrToHsvScaled(frame.raw, CLASSIFICATION_SCALE, correction, keep_value=True)


def sanityCheck(baseline_dir: Path, prefix: str) -> None:
    """Compare the captured envelope's mean H/S against an expected background
    reference, if one exists. Proceed-with-warning (never crash) so real-world
    drift is observable on the first runs."""
    import json

    if not BACKGROUND_REF_PATH.exists():
        print(f"    sanity: no {BACKGROUND_REF_PATH.name}; skipping H/S sanity check")
        return
    try:
        with open(BACKGROUND_REF_PATH) as f:
            ref = json.load(f)
        exp_h = float(ref["hue"])
        exp_s = float(ref["saturation"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        print(f"    sanity: {BACKGROUND_REF_PATH.name} unreadable/missing hue|saturation; skipping")
        return

    def mean_env(channel: str) -> float | None:
        lo = cv2.imread(str(baseline_dir / f"{prefix}_baseline_{channel}_min.png"), cv2.IMREAD_GRAYSCALE)
        hi = cv2.imread(str(baseline_dir / f"{prefix}_baseline_{channel}_max.png"), cv2.IMREAD_GRAYSCALE)
        if lo is None or hi is None:
            return None
        nz = (lo > 0) | (hi > 0)
        if not np.any(nz):
            return None
        mid = (lo.astype(np.float32) + hi.astype(np.float32)) / 2.0
        return float(np.mean(mid[nz]))

    mean_h = mean_env("h")
    mean_s = mean_env("s")
    if mean_h is None or mean_s is None:
        print("    sanity: could not read envelope means; skipping")
        return

    dh = min(abs(mean_h - exp_h), 180 - abs(mean_h - exp_h))  # circular
    ds = abs(mean_s - exp_s)
    print(f"    sanity: envelope mean H={mean_h:.1f} (exp {exp_h:.1f}, dH={dh:.1f}), "
          f"S={mean_s:.1f} (exp {exp_s:.1f}, dS={ds:.1f})")
    if dh > SANITY_HUE_TOLERANCE or ds > SANITY_SAT_TOLERANCE:
        print("    *** SANITY WARNING: envelope H/S disagrees with background reference "
              f"(tol H±{SANITY_HUE_TOLERANCE}, S±{SANITY_SAT_TOLERANCE}). "
              "Camera lock or lighting may have changed between calibrations. ***")


def _readEnvelope(baseline_dir: Path, prefix: str, channel: str):
    lo = cv2.imread(str(baseline_dir / f"{prefix}_baseline_{channel}_min.png"), cv2.IMREAD_GRAYSCALE)
    hi = cv2.imread(str(baseline_dir / f"{prefix}_baseline_{channel}_max.png"), cv2.IMREAD_GRAYSCALE)
    return lo, hi


def _loadPolygonMask(prefix: str, shape) -> "np.ndarray | None":
    """Build the floor detection polygon mask at the envelope resolution, or
    None if no polygon is saved. Mirrors vision_manager's scaling so the report
    reflects the region detection actually runs in (excludes green surroundings
    outside the floor)."""
    # top/bottom live in the classification polygon store; the carousel polygon
    # is drawn in polygon_editor and saved in the channel store under its own
    # resolution key, so pull each from the source the runtime actually uses.
    if prefix == "carousel":
        saved = getChannelPolygons()
        res_key = "carousel_resolution"
    else:
        saved = getClassificationPolygons()
        res_key = "resolution"
    if not saved:
        return None
    pts = (saved.get("polygons") or {}).get(prefix)
    if not pts or len(pts) < 3:
        return None
    H, W = shape[:2]
    res = saved.get(res_key) or [W, H]
    poly = np.array(pts, dtype=np.float64)
    poly[:, 0] *= W / res[0]
    poly[:, 1] *= H / res[1]
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
    return mask


def _widthStats(width: np.ndarray) -> str:
    return (f"mean={float(np.mean(width)):.1f} p95={float(np.percentile(width, 95)):.1f} "
            f"max={int(np.max(width))}")


def reportEnvelopeWidth(baseline_dir: Path, prefix: str) -> None:
    """Print H/S envelope widths so a too-wide envelope (camera lock not holding
    or lighting drift mid-sweep) is caught immediately.

    Hue is reported over all pixels and over only the stable-mask (kept) pixels.
    The kept-pixel figure is the one that actually matters at runtime — the
    all-pixels number is inflated by the wobbly edges the stable mask removes.
    (Call this AFTER saveStableMask so the mask PNG exists.)"""
    h_lo, h_hi = _readEnvelope(baseline_dir, prefix, "h")
    s_lo, s_hi = _readEnvelope(baseline_dir, prefix, "s")
    if h_lo is None or h_hi is None or s_lo is None or s_hi is None:
        return

    nz = (h_lo > 0) | (h_hi > 0) | (s_lo > 0) | (s_hi > 0)
    if not np.any(nz):
        return

    stable_img = cv2.imread(str(baseline_dir / f"{prefix}_stable_mask.png"), cv2.IMREAD_GRAYSCALE)
    kept = nz & (stable_img > 0) if stable_img is not None else nz

    # The number that actually matters: kept pixels INSIDE the floor polygon.
    # Without the polygon the "kept" set still includes the green chamber
    # surroundings (masked at runtime), which inflate the width with hue-wrap
    # artifacts irrelevant to detection.
    poly_mask = _loadPolygonMask(prefix, h_lo.shape)
    floor = kept & (poly_mask > 0) if poly_mask is not None else None

    h_width = (h_hi.astype(np.int16) - h_lo.astype(np.int16))
    s_width = (s_hi.astype(np.int16) - s_lo.astype(np.int16))

    print(f"    {prefix} H envelope width (all):    {_widthStats(h_width[nz])} (want <15)")
    print(f"    {prefix} S envelope width (all):    {_widthStats(s_width[nz])} (want <40)")
    if floor is not None and np.any(floor):
        print(f"    {prefix} H envelope width (floor):  {_widthStats(h_width[floor])} <- in-polygon, the one that matters (want <15)")
        print(f"    {prefix} S envelope width (floor):  {_widthStats(s_width[floor])} <- in-polygon (want <40)")
    elif np.any(kept):
        print(f"    {prefix} H envelope width (kept):   {_widthStats(h_width[kept])} <- post-mask (no polygon found)")
        print(f"    {prefix} S envelope width (kept):   {_widthStats(s_width[kept])} <- post-mask")


def saveStableMask(
    baseline_dir: Path, prefix: str,
    h_frames, s_frames, v_frames,
    max_hue_std: float, max_sat_std: float, max_val_std: float,
) -> None:
    """Compute and save the stable-pixel mask, and report how much got dropped.
    Needs at least 2 frames to have any variance to measure."""
    if len(h_frames) < 2:
        print(f"    {prefix} stable mask: need >=2 frames, skipping")
        return
    mask, stats = computeStableMask(
        h_frames, s_frames, v_frames, max_hue_std, max_sat_std, max_val_std
    )
    cv2.imwrite(str(baseline_dir / f"{prefix}_stable_mask.png"), mask)
    print(
        f"    {prefix} stable mask: dropped {stats['masked_pct']:.1f}% of pixels "
        f"(thresholds H<={max_hue_std} S<={max_sat_std} V<={max_val_std})"
    )
    print(
        f"      std p50/p95 -> H {stats['h_std_p50']:.1f}/{stats['h_std_p95']:.1f}  "
        f"S {stats['s_std_p50']:.1f}/{stats['s_std_p95']:.1f}  "
        f"V {stats['v_std_p50']:.1f}/{stats['v_std_p95']:.1f}"
    )


class CameraCaptureState:
    """Per-camera frame stacks + finalization for one baseline run.

    Capture is driven externally (calibrateCameras) so multiple cameras can
    share a single carousel sweep — each grabs a frame at the same carousel
    position rather than each rotating the carousel itself."""

    def __init__(self, cam: str, baseline_dir: Path, wipe: bool):
        self.cam = cam
        self.prefix = cam
        self.cam_dir = baseline_dir
        if wipe:
            for p in globmod.glob(str(self.cam_dir / f"{self.prefix}_*.png")):
                os.remove(p)
        # Three parallel per-channel frame stacks. V is captured for debugging
        # only (handoff: keep it around, not used at runtime).
        self.h_frames = loadExistingChannel(self.cam_dir, self.prefix, "h")
        self.s_frames = loadExistingChannel(self.cam_dir, self.prefix, "s")
        self.v_frames = loadExistingChannel(self.cam_dir, self.prefix, "v")
        self.existing_count = min(len(self.h_frames), len(self.s_frames))
        self.frames_needed = MAX_FRAMES - self.existing_count

    @property
    def complete(self) -> bool:
        return min(len(self.h_frames), len(self.s_frames)) >= MAX_FRAMES

    def captureFrame(self, vision: VisionManager, correction) -> None:
        """Grab and store one HSV frame at the current carousel position."""
        hsv = getLatestHSV(vision, self.cam, correction)
        if hsv is None:
            print(f"    {self.cam} frame {len(self.h_frames) + 1}/{MAX_FRAMES} - no frame")
            return
        h, s, v = cv2.split(hsv)
        self.h_frames.append(h)
        self.s_frames.append(s)
        self.v_frames.append(v)
        idx = len(self.h_frames) - 1
        cv2.imwrite(str(self.cam_dir / f"{self.prefix}_hframe_{idx:03d}.png"), h)
        cv2.imwrite(str(self.cam_dir / f"{self.prefix}_sframe_{idx:03d}.png"), s)
        cv2.imwrite(str(self.cam_dir / f"{self.prefix}_vframe_{idx:03d}.png"), v)
        saveEnvelope(self.cam_dir, self.prefix, "h", self.h_frames)
        saveEnvelope(self.cam_dir, self.prefix, "s", self.s_frames)
        saveEnvelope(self.cam_dir, self.prefix, "v", self.v_frames)  # debug-only
        print(f"    {self.cam} frame {len(self.h_frames)}/{MAX_FRAMES}")

    def finalize(
        self, max_hue_std: float, max_sat_std: float, max_val_std: float,
        percentile: float, interrupted: bool,
    ) -> bool:
        if not self.h_frames:
            print(f"  {self.cam}: no frames captured")
            return False
        # Final envelope uses the robust percentile (the per-frame saves during
        # capture were fast naive min/max interim, in case of a crash).
        saveEnvelope(self.cam_dir, self.prefix, "h", self.h_frames, percentile=percentile)
        saveEnvelope(self.cam_dir, self.prefix, "s", self.s_frames, percentile=percentile)
        saveEnvelope(self.cam_dir, self.prefix, "v", self.v_frames, percentile=percentile)
        status = "interrupted" if interrupted else "done"
        print(f"  {self.cam}: {status}. {len(self.h_frames)} frames + H/S/V envelopes")
        # Save the stable mask first so reportEnvelopeWidth can show kept-pixel width.
        saveStableMask(self.cam_dir, self.prefix, self.h_frames, self.s_frames, self.v_frames,
                       max_hue_std, max_sat_std, max_val_std)
        reportEnvelopeWidth(self.cam_dir, self.prefix)
        sanityCheck(self.cam_dir, self.prefix)
        return True


def calibrateCameras(
    vision: VisionManager,
    irl,
    baseline_dir: Path,
    cams: list[str],
    correction,
    wipe: bool,
    no_jitter: bool,
    max_hue_std: float,
    max_sat_std: float,
    max_val_std: float,
    percentile: float,
) -> tuple[bool, bool]:
    """Capture every camera in a single shared carousel sweep: move the carousel
    once per step and grab a frame from each camera that still needs one. A
    multi-camera run thus rotates the carousel MAX_FRAMES times total instead of
    MAX_FRAMES per camera. Already-complete cameras skip capture but still get
    finalized (regenerating their envelope/mask/report)."""
    states = [CameraCaptureState(cam, baseline_dir, wipe) for cam in cams]
    for st in states:
        if st.frames_needed <= 0:
            print(f"  {st.cam}: already have {st.existing_count} frames (max {MAX_FRAMES}); "
                  f"regenerating envelope/mask/report (use --wipe to recapture).")
        else:
            print(f"  {st.cam}: have {st.existing_count} existing frames, capturing {st.frames_needed} more...")

    steps_needed = max((st.frames_needed for st in states), default=0)
    JITTER_RANGE = 5
    debt = 0.0
    interrupted = False
    for i in range(steps_needed):
        try:
            if not no_jitter and i % 2 == 1:
                jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
            else:
                jitter = 0.0
            move = DEGREES_PER_FRAME + jitter - debt
            debt = jitter
            irl.carousel_stepper.move_degrees_blocking(move)
            time.sleep(MOVE_TIMEOUT_MS / 1000.0)
            # One carousel position, every still-incomplete camera samples it.
            for st in states:
                if not st.complete:
                    st.captureFrame(vision, correction)
        except KeyboardInterrupt:
            interrupted = True
            print("\n  interrupted — finalizing envelopes from captured frames...")
            break

    ok = True
    for st in states:
        ok = st.finalize(max_hue_std, max_sat_std, max_val_std, percentile, interrupted) and ok
    return ok, interrupted


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--wipe", action="store_true")
    parser.add_argument("--jitter", action="store_true")
    parser.add_argument("--max-hue-std", type=float, default=DEFAULT_MAX_HUE_STD)
    parser.add_argument("--max-sat-std", type=float, default=DEFAULT_MAX_SAT_STD)
    parser.add_argument("--max-val-std", type=float, default=DEFAULT_MAX_VAL_STD)
    parser.add_argument("--percentile", type=float, default=DEFAULT_PERCENTILE)
    parser.add_argument("--no-chute-wiggle", action="store_true",
                        help="disable the chute vibration during capture")
    parser.add_argument("--chute-wiggle-hz", type=float, default=DEFAULT_CHUTE_WIGGLE_HZ)
    parser.add_argument("--chute-wiggle-steps", type=int, default=DEFAULT_CHUTE_WIGGLE_STEPS,
                        help="chute wiggle amplitude in microsteps")
    parser.add_argument("--camera", choices=sorted(CAMERA_GROUPS.keys()),
                        default="classification",
                        help="which camera(s) to baseline (default: classification = top+bottom)")
    args, rest = parser.parse_known_args()
    wipe = args.wipe
    no_jitter = not args.jitter
    # Leave unrecognized flags (e.g. mkGlobalConfig's --disable) on sys.argv.
    sys.argv = [sys.argv[0]] + rest

    gc = mkGlobalConfig()
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"calibrate_classification_baseline_{timestamp}.log"
    gc.logger._log_file = open(log_path, "a")

    correction = loadHsvCorrection()
    if isNoop(correction):
        print("HSV correction: none (identity)")
    else:
        print(f"HSV correction: {correction}")

    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    vision = VisionManager(irl_config, gc, irl)
    vision.start()

    baseline_dir = BLOB_DIR / "classification_baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    # Vibrate the chute throughout capture so the envelope absorbs vibration.
    wiggler = None
    if not args.no_chute_wiggle:
        chute_stepper = getattr(irl, "chute_stepper", None)
        if chute_stepper is None and getattr(irl, "chute", None) is not None:
            chute_stepper = getattr(irl.chute, "stepper", None)
        if chute_stepper is not None:
            wiggler = ChuteWiggler(chute_stepper, args.chute_wiggle_hz,
                                   args.chute_wiggle_steps, logger=gc.logger)
        else:
            print("chute wiggle: chute stepper not found, skipping")

    ok = True
    try:
        # Poll for the first frame instead of a fixed sleep: the AVFoundation
        # camera with locked low exposure can take several seconds to warm up
        # and deliver its first frame, which a short fixed wait would race.
        wanted = CAMERA_GROUPS[args.camera]
        FRAME_WAIT_TIMEOUT_S = 15.0
        # Cameras warm up at different rates (their uvc-util locks are applied
        # serially), so don't grab the first one and run — that drops slower
        # cameras. Once any camera appears, wait a short grace for stragglers,
        # resetting it each time a new one shows up. This avoids blocking the
        # full timeout on cameras in `wanted` that simply aren't assigned.
        STRAGGLER_GRACE_S = 4.0
        print(f"waiting for {args.camera} camera frames (up to {FRAME_WAIT_TIMEOUT_S:.0f}s)...")
        deadline = time.time() + FRAME_WAIT_TIMEOUT_S
        available: list[str] = []
        settle_deadline: float | None = None
        prev_count = 0
        while time.time() < deadline:
            available = [c for c in wanted if vision.getFrame(CAM_FRAME_NAMES[c]) is not None]
            if len(available) == len(wanted):
                break  # everything we asked for is delivering
            if available and (settle_deadline is None or len(available) > prev_count):
                settle_deadline = time.time() + STRAGGLER_GRACE_S
            prev_count = len(available)
            if settle_deadline is not None and time.time() >= settle_deadline:
                break
            time.sleep(0.25)

        if not available:
            print(f"ERROR: no {args.camera} camera(s) available "
                  f"(assign in camera_setup; wanted {wanted})")
            return 1

        print("cameras: " + " ".join(f"{c}={'yes' if c in available else 'no'}" for c in wanted))

        if wiggler is not None:
            wiggler.start()
            print(f"chute wiggle: {args.chute_wiggle_hz:.1f} Hz, "
                  f"amplitude {args.chute_wiggle_steps} microsteps")

        std_args = (args.max_hue_std, args.max_sat_std, args.max_val_std, args.percentile)
        run_ok, interrupted = calibrateCameras(
            vision, irl, baseline_dir, available, correction, wipe, no_jitter, *std_args)
        ok = run_ok and ok
        if interrupted:
            raise KeyboardInterrupt
        print(f"done. baseline in {baseline_dir}")
    except KeyboardInterrupt:
        print(f"\nstopped early. partial baseline saved in {baseline_dir}")
    finally:
        if wiggler is not None:
            wiggler.stop()
        vision.stop()
        irl.disableSteppers()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
