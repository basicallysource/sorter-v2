"""Color calibration for the classification chamber camera.

Locks white balance / exposure / gain to known-good values by sweeping candidate
settings against a physical LEGO-tile target and scoring each capture versus a
committed reference snapshot. This is a precondition for the HSV detection rework:
the new pipeline needs stable hue/saturation, which requires the camera's auto
adjustments off and pinned to good values.

Target: a 4x2 LEGO tile grid. Top row = saturated colors (red, green, blue,
yellow); bottom row = a grayscale ramp (black, dark_gray, light_gray, white).

Platform note: on this machine (macOS/AVFoundation) OpenCV cannot set camera
controls, so settings are applied out-of-band via `uvc-util` (the same path the
runtime CaptureThread uses). Frames are still read through VisionManager. On V4L2
the same controls would go through cv2; that backend is not implemented here yet.

Subcommands:
    roi        One-time: click the 8 tile centers, save ROI pixel coords.
    reference  One-time: capture the current frame, sample each ROI, save the
               per-tile BGR/HSV reference the sweep optimizes toward.
    sweep      Sweep WB x exposure x gain, score vs reference, report the best.

Outputs are written under software/client/calibration/ for human review; nothing
is auto-applied to config. Commit the chosen values to CLASSIFICATION_CAMERA_LOCK
in irl/config.py by hand.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from global_config import make_global_config
from irl.config import (
    make_irl_config, make_irl_interface, CLASSIFICATION_TOP_UVC_NAME, CAROUSEL_UVC_NAME,
)
from vision import VisionManager
from vision.camera import _resolve_uvc_util, UVC_UTIL_ENV_VAR

# --- target definition -------------------------------------------------------

COLOR_TILES = ["red", "green", "blue", "yellow"]  # top row, saturated
GRAY_TILES = ["black", "dark_gray", "light_gray", "white"]  # bottom row, ramp
TILE_ORDER = COLOR_TILES + GRAY_TILES  # click order, left->right, top then bottom
DEFAULT_ROI_SIZE = 40  # half-not; full square side length in pixels

# --- paths -------------------------------------------------------------------

CALIBRATION_DIR = Path(__file__).resolve().parent.parent / "calibration"
# target_rois.json holds every camera's tile ROIs keyed by the camera's profile
# key, so cameras share one file without colliding.
ROIS_PATH = CALIBRATION_DIR / "target_rois.json"


# --- camera profiles ---------------------------------------------------------

class CameraProfile:
    """Per-camera targeting + output paths so one script calibrates either the
    classification top camera or the carousel camera. classification_top keeps
    the legacy un-suffixed file names; other cameras get a per-key suffix so
    their reference/sweep artifacts don't collide."""

    def __init__(self, cli_name: str, key: str, uvc_name: str, frame_name: str,
                 lock_const: str):
        self.cli_name = cli_name        # --camera value
        self.key = key                  # key inside the rois/reference JSON
        self.uvc_name = uvc_name        # uvc-util device name
        self.frame_name = frame_name    # vision.getFrame(...) argument
        self.lock_const = lock_const    # config.py dict to paste results into
        suffix = "" if key == "top_camera" else f"_{key}"
        self.reference_path = CALIBRATION_DIR / f"reference_snapshot{suffix}.json"
        self.reference_image_path = CALIBRATION_DIR / f"reference_snapshot{suffix}.png"
        self.sweep_out_dir = CALIBRATION_DIR / f"sweep_output{suffix}"


PROFILES = {
    "classification_top": CameraProfile(
        "classification_top", "top_camera", CLASSIFICATION_TOP_UVC_NAME,
        "classification_top", "CLASSIFICATION_CAMERA_LOCK",
    ),
    "carousel": CameraProfile(
        "carousel", "carousel_camera", CAROUSEL_UVC_NAME,
        "carousel", "CAROUSEL_CAMERA_LOCK",
    ),
}

# --- scoring weights (WB matters most for downstream HSV) --------------------

# Neutrality is normalized per-tile by that tile's own luminance (chromaticity-
# style ratio), so it doesn't scale with brightness -- otherwise an absolute
# R/G/B spread grows with exposure and the optimizer chases underexposure to
# minimize it. NEUTRALITY_SCALE brings the resulting ~0-2 ratio sum back into
# the same rough magnitude as luminance_err/color_err so the weight below still
# means roughly the same thing.
NEUTRALITY_SCALE = 50.0
WEIGHT_NEUTRALITY = 2.0
WEIGHT_LUMINANCE = 1.0
WEIGHT_COLOR = 1.0

# Any BGR channel at/above this is treated as clipped/blown-out: the color info
# in that tile is gone, so heavily penalize it regardless of how "neutral" or
# bright the clipped value happens to look.
CLIP_THRESHOLD = 250
CLIP_PENALTY = 100.0


# =============================================================================
# uvc-util control wrapper
# =============================================================================


class UvcControl:
    """Thin wrapper over the `uvc-util` CLI, selecting the camera by UVC name."""

    def __init__(self, device_name: str):
        self.device_name = device_name
        self.binary = _resolve_uvc_util()
        if self.binary is None:
            raise RuntimeError(
                f"uvc-util not found. Set {UVC_UTIL_ENV_VAR} or add it to PATH."
            )

    def _run(self, args: list[str]) -> str:
        result = subprocess.run(
            [self.binary, "-N", self.device_name, *args],
            check=False, capture_output=True, text=True, timeout=5,
        )
        return (result.stdout or result.stderr).strip()

    def set(self, control: str, value) -> None:
        self._run(["-s", f"{control}={value}"])

    def get(self, control: str) -> str:
        return self._run(["-o", control])

    def query_range(self, control: str) -> dict:
        """Parse min/max/step/default/current from `-S`. Missing fields => None."""
        text = self._run(["-S", control])
        out: dict[str, int | None] = {
            "minimum": None, "maximum": None, "step": None,
            "default": None, "current": None,
        }
        for line in text.splitlines():
            line = line.strip()
            for key, prefix in (
                ("minimum", "minimum:"), ("maximum", "maximum:"),
                ("step", "step-size:"),
                ("default", "default-value:"), ("current", "current-value:"),
            ):
                if line.startswith(prefix):
                    raw = line[len(prefix):].strip()
                    try:
                        out[key] = int(raw)
                    except ValueError:
                        pass
        return out

    def apply(self, *, exposure: int, wb: int, gain: int) -> None:
        """Apply one manual combination. Auto flags off first, then values."""
        self.set("auto-exposure-mode", 1)  # 1 = manual
        self.set("exposure-time-abs", exposure)
        self.set("auto-white-balance-temp", "false")
        self.set("white-balance-temp", wb)
        self.set("gain", gain)


# =============================================================================
# shared helpers
# =============================================================================


def start_vision(profile: CameraProfile):
    """Bring up GlobalConfig + IRL + VisionManager and wait for the target frame."""
    gc = make_global_config()
    irl_config = make_irl_config()
    irl = make_irl_interface(irl_config, gc)
    vision = VisionManager(irl_config, gc, irl)
    vision.start()
    print(f"waiting for {profile.cli_name} camera frames...")
    for _ in range(80):
        if vision.get_frame(profile.frame_name) is not None:
            break
        time.sleep(0.1)
    if vision.get_frame(profile.frame_name) is None:
        print(f"ERROR: no frames from the {profile.cli_name} camera "
              f"(is it assigned in camera_setup?).")
        return None, None
    return vision, irl


def grab_frame(vision: VisionManager, profile: CameraProfile) -> "np.ndarray | None":
    frame = vision.get_frame(profile.frame_name)
    if frame is None:
        return None
    return frame.raw  # BGR


def load_rois(profile: CameraProfile) -> dict:
    if not ROIS_PATH.exists():
        raise FileNotFoundError(
            f"{ROIS_PATH} missing. Run the `roi` subcommand first."
        )
    with open(ROIS_PATH) as f:
        data = json.load(f)
    if profile.key not in data:
        raise FileNotFoundError(
            f"No ROIs for '{profile.key}' in {ROIS_PATH}. "
            f"Run `roi --camera {profile.cli_name}` first."
        )
    return data[profile.key]["tiles"]


def sample_tile(image: "np.ndarray", roi: dict) -> tuple[list[int], list[int]]:
    """Mean BGR + HSV over the ROI square, clamped to image bounds."""
    h, w = image.shape[:2]
    half = roi["size"] // 2
    x0 = max(0, roi["x"] - half)
    x1 = min(w, roi["x"] + half)
    y0 = max(0, roi["y"] - half)
    y1 = min(h, roi["y"] + half)
    patch = image[y0:y1, x0:x1]
    mean_bgr = patch.reshape(-1, 3).mean(axis=0)
    bgr_u8 = np.uint8([[mean_bgr]])  # 1x1 for color conversion
    hsv = cv2.cvtColor(bgr_u8, cv2.COLOR_BGR2HSV)[0, 0]
    return [int(round(v)) for v in mean_bgr], [int(v) for v in hsv]


def sample_all(image: "np.ndarray", rois: dict) -> dict:
    return {name: sample_tile(image, rois[name]) for name in rois}


def luminance(bgr: list[int]) -> float:
    b, g, r = bgr
    return 0.299 * r + 0.587 * g + 0.114 * b


def hue_distance(h1: int, h2: int) -> int:
    """Circular hue distance on OpenCV's 0-179 scale."""
    d = abs(h1 - h2)
    return min(d, 180 - d)


# =============================================================================
# subcommand: roi
# =============================================================================


def cmd_roi(args) -> int:
    profile = args.profile
    vision, irl = start_vision(profile)
    if vision is None:
        return 1
    image = grab_frame(vision, profile)
    if image is None:
        return 1

    clicks: list[tuple[int, int]] = []
    display = image.copy()

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < len(TILE_ORDER):
            clicks.append((x, y))
            cv2.circle(display, (x, y), 5, (0, 255, 0), -1)
            cv2.putText(
                display, TILE_ORDER[len(clicks) - 1], (x + 6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
            )

    print("\nClick each tile center IN THIS ORDER (top row L->R, then bottom):")
    print("  " + " , ".join(TILE_ORDER))
    print("Press 'u' to undo last, 's' to save once all 8 placed, 'q' to abort.\n")

    try:
        cv2.namedWindow("ROI setup", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("ROI setup", on_mouse)
    except cv2.error as e:
        print(f"ERROR: OpenCV GUI unavailable ({e}). Cannot run interactive ROI "
              f"setup in this build. Edit {ROIS_PATH} by hand instead.")
        return 1

    while True:
        cv2.imshow("ROI setup", display)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("q"):
            print("aborted.")
            cv2.destroyAllWindows()
            cv2.waitKey(1)
            vision.stop()
            return 1
        if key == ord("u") and clicks:
            clicks.pop()
            display = image.copy()
            for i, (cx, cy) in enumerate(clicks):
                cv2.circle(display, (cx, cy), 5, (0, 255, 0), -1)
                cv2.putText(display, TILE_ORDER[i], (cx + 6, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        if key == ord("s"):
            if len(clicks) != len(TILE_ORDER):
                print(f"  need all {len(TILE_ORDER)} clicks "
                      f"({len(clicks)} placed so far).")
                continue
            break

    cv2.destroyAllWindows()
    cv2.waitKey(1)
    vision.stop()

    tiles = {
        name: {"x": cx, "y": cy, "size": args.size}
        for name, (cx, cy) in zip(TILE_ORDER, clicks)
    }
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    # Merge into the shared rois file under this camera's key so the other
    # camera's ROIs are preserved.
    data = {}
    if ROIS_PATH.exists():
        with open(ROIS_PATH) as f:
            data = json.load(f)
    data[profile.key] = {"tiles": tiles}
    with open(ROIS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nsaved {len(tiles)} ROIs for '{profile.key}' -> {ROIS_PATH}")
    return 0


# =============================================================================
# subcommand: reference
# =============================================================================


def cmd_reference(args) -> int:
    profile = args.profile
    rois = load_rois(profile)
    vision, irl = start_vision(profile)
    if vision is None:
        return 1
    image = grab_frame(vision, profile)
    if image is None:
        return 1

    uvc = UvcControl(profile.uvc_name)
    settings = {
        "wb_temperature": uvc.query_range("white-balance-temp")["current"],
        "exposure": uvc.query_range("exposure-time-abs")["current"],
        "gain": uvc.query_range("gain")["current"],
    }

    tiles: dict[str, dict] = {}
    for name, roi in rois.items():
        bgr, hsv = sample_tile(image, roi)
        entry: dict = {"bgr": bgr, "hsv": hsv}
        if name in GRAY_TILES:
            entry["expected_neutral"] = True
            entry["target_luminance"] = round(luminance(bgr), 1)
        tiles[name] = entry

    snapshot = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "camera_settings": settings,
        profile.key: tiles,
    }
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    with open(profile.reference_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    cv2.imwrite(str(profile.reference_image_path), image)
    print(f"saved reference -> {profile.reference_path}")
    print(f"saved reference image -> {profile.reference_image_path}")
    print(f"camera settings at capture: {settings}")
    for name in TILE_ORDER:
        print(f"  {name:11s} bgr={tiles[name]['bgr']} hsv={tiles[name]['hsv']}")
    vision.stop()
    return 0


# =============================================================================
# subcommand: sweep
# =============================================================================


def build_sweep_values(uvc: UvcControl, args) -> tuple[list[int], list[int], list[int]]:
    """Resolve candidate WB / exposure / gain lists, clamped to camera limits."""
    wb_r = uvc.query_range("white-balance-temp")
    exp_r = uvc.query_range("exposure-time-abs")
    gain_r = uvc.query_range("gain")

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    wb_lo = wb_r["minimum"] or 2800
    wb_hi = wb_r["maximum"] or 6500
    exp_lo = exp_r["minimum"] or 1
    exp_hi = exp_r["maximum"] or 5000
    gain_lo = gain_r["minimum"] or 0
    gain_hi = gain_r["maximum"] or 100

    if args.reset:
        # Starting fresh against a new camera: the 3-10 exposure default and
        # --wb-start/--wb-end/--wb-step defaults below were tuned for the old
        # sensor and may be meaningless here. Ignore overrides and build a
        # broad discovery sweep from this camera's actual reported ranges.
        print(
            f"--reset: discovered ranges -- "
            f"exposure-time-abs: {exp_lo}-{exp_hi} (step {exp_r['step']}), "
            f"white-balance-temp: {wb_lo}-{wb_hi} (step {wb_r['step']}), "
            f"gain: {gain_lo}-{gain_hi} (step {gain_r['step']})"
        )
        wb_vals = sorted(set(int(round(x)) for x in np.linspace(wb_lo, wb_hi, num=8)))
        exp_vals = sorted(set(
            int(round(x)) for x in np.geomspace(max(1, exp_lo), exp_hi, num=8)
        ))
        gain_vals = sorted(set(int(round(x)) for x in np.linspace(gain_lo, gain_hi, num=5)))
        return wb_vals, exp_vals, gain_vals

    wb_vals = [
        clamp(v, wb_lo, wb_hi)
        for v in range(args.wb_start, args.wb_end + 1, args.wb_step)
    ]
    wb_vals = sorted(set(wb_vals))

    if args.exposures:
        exp_vals = [clamp(v, exp_lo, exp_hi) for v in args.exposures]
    else:
        # exposure-time-abs is integer with step-size 1; everything above ~10
        # saturates this sensor (see calibration/README.md), so the productive
        # range is whole numbers 3-10.
        exp_vals = [v for v in range(3, 11) if exp_lo <= v <= exp_hi]

    if args.gains:
        gain_vals = [clamp(v, gain_lo, gain_hi) for v in args.gains]
    else:
        gain_vals = [gain_lo]

    return wb_vals, sorted(set(exp_vals)), sorted(set(gain_vals))


def score_capture(measured: dict, reference: dict, profile: CameraProfile) -> dict:
    """Score one capture vs reference. Lower total is better."""
    ref_tiles = reference[profile.key]
    neutrality = 0.0
    for name in GRAY_TILES:
        b, g, r = measured[name][0]
        spread = abs(r - g) + abs(g - b) + abs(r - b)
        lum = luminance(measured[name][0])
        neutrality += spread / max(lum, 1.0)
    neutrality *= NEUTRALITY_SCALE

    lum_err = 0.0
    for name in GRAY_TILES:
        meas_l = luminance(measured[name][0])
        ref_l = ref_tiles[name].get("target_luminance", luminance(ref_tiles[name]["bgr"]))
        lum_err += abs(meas_l - ref_l)

    color_err = 0.0
    for name in COLOR_TILES:
        m_hsv = measured[name][1]
        r_hsv = ref_tiles[name]["hsv"]
        color_err += hue_distance(m_hsv[0], r_hsv[0]) + abs(m_hsv[1] - r_hsv[1])

    clip_penalty = 0.0
    for name in TILE_ORDER:
        b, g, r = measured[name][0]
        clip_penalty += CLIP_PENALTY * sum(
            1 for ch in (b, g, r) if ch >= CLIP_THRESHOLD
        )

    total = (
        WEIGHT_NEUTRALITY * neutrality
        + WEIGHT_LUMINANCE * lum_err
        + WEIGHT_COLOR * color_err
        + clip_penalty
    )
    return {
        "neutrality": round(neutrality, 2),
        "luminance_err": round(lum_err, 2),
        "color_err": round(color_err, 2),
        "clip_penalty": round(clip_penalty, 2),
        "total": round(total, 2),
    }


def save_comparison(reference_image, best_image, rois, best, out_path) -> None:
    """Side-by-side reference vs best capture with per-tile ROI boxes + deltas."""
    if reference_image is None or best_image is None:
        return
    h = max(reference_image.shape[0], best_image.shape[0])

    def annotate(img):
        canvas = img.copy()
        for name, roi in rois.items():
            half = roi["size"] // 2
            cv2.rectangle(
                canvas, (roi["x"] - half, roi["y"] - half),
                (roi["x"] + half, roi["y"] + half), (0, 255, 0), 2,
            )
            cv2.putText(canvas, name, (roi["x"] - half, roi["y"] - half - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        return canvas

    left = annotate(reference_image)
    right = annotate(best_image)
    pad_l = cv2.copyMakeBorder(left, 0, h - left.shape[0], 0, 0, cv2.BORDER_CONSTANT)
    pad_r = cv2.copyMakeBorder(right, 0, h - right.shape[0], 0, 0, cv2.BORDER_CONSTANT)
    combo = np.hstack([pad_l, pad_r])
    cv2.putText(combo, "REFERENCE", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(combo, f"BEST  total={best['score']['total']}",
                (left.shape[1] + 10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.imwrite(str(out_path), combo)


def cmd_sweep(args) -> int:
    profile = args.profile
    rois = load_rois(profile)
    if not profile.reference_path.exists():
        print(f"ERROR: {profile.reference_path} missing. Run `reference` first.")
        return 1
    with open(profile.reference_path) as f:
        reference = json.load(f)
    reference_image = (
        cv2.imread(str(profile.reference_image_path))
        if profile.reference_image_path.exists() else None
    )

    vision, irl = start_vision(profile)
    if vision is None:
        return 1
    uvc = UvcControl(profile.uvc_name)

    wb_vals, exp_vals, gain_vals = build_sweep_values(uvc, args)
    combos = [(w, e, g) for w in wb_vals for e in exp_vals for g in gain_vals]
    total_combos = len(combos)
    eta_s = total_combos * (args.settle_ms / 1000.0 + 0.3)
    print(f"sweeping {total_combos} combinations "
          f"(WB:{len(wb_vals)} x exp:{len(exp_vals)} x gain:{len(gain_vals)}), "
          f"~{eta_s/60:.1f} min")

    results: list[dict] = []
    best: dict | None = None
    best_image = None

    for i, (wb, exp, gain) in enumerate(combos):
        uvc.apply(exposure=exp, wb=wb, gain=gain)
        time.sleep(args.settle_ms / 1000.0)
        image = grab_frame(vision, profile)
        if image is None:
            print(f"  [{i+1}/{total_combos}] no frame, skipping")
            continue
        measured = sample_all(image, rois)
        score = score_capture(measured, reference, profile)
        record = {
            "wb": wb, "exposure": exp, "gain": gain,
            "score": score, "tiles": measured,
        }
        results.append(record)
        if best is None or score["total"] < best["score"]["total"]:
            best = record
            best_image = image.copy()
        if (i + 1) % 10 == 0 or i + 1 == total_combos:
            print(f"  [{i+1}/{total_combos}] wb={wb} exp={exp} gain={gain} "
                  f"total={score['total']} (best={best['score']['total']})")

    if best is None:
        print("ERROR: no successful captures.")
        vision.stop()
        return 1

    # optional fine pass around the best WB
    if args.fine and len(wb_vals) > 1:
        wb_r = uvc.query_range("white-balance-temp")
        wb_lo = wb_r["minimum"] or 2800
        wb_hi = wb_r["maximum"] or 6500
        center = best["wb"]
        fine_wb = sorted(set(
            max(wb_lo, min(wb_hi, center + d)) for d in range(-200, 201, 50)
        ))
        print(f"fine WB pass around {center}: {fine_wb}")
        for wb in fine_wb:
            uvc.apply(exposure=best["exposure"], wb=wb, gain=best["gain"])
            time.sleep(args.settle_ms / 1000.0)
            image = grab_frame(vision, profile)
            if image is None:
                continue
            measured = sample_all(image, rois)
            score = score_capture(measured, reference, profile)
            record = {"wb": wb, "exposure": best["exposure"], "gain": best["gain"],
                      "score": score, "tiles": measured}
            results.append(record)
            if score["total"] < best["score"]["total"]:
                best = record
                best_image = image.copy()

    profile.sweep_out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = profile.sweep_out_dir / f"results_{ts}.json"
    csv_path = profile.sweep_out_dir / f"results_{ts}.csv"
    best_path = profile.sweep_out_dir / f"best_{ts}.json"
    compare_path = profile.sweep_out_dir / f"compare_{ts}.png"

    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    with open(best_path, "w") as f:
        json.dump(best, f, indent=2)
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wb", "exposure", "gain", "neutrality",
                         "luminance_err", "color_err", "clip_penalty", "total"])
        for r in sorted(results, key=lambda r: r["score"]["total"]):
            s = r["score"]
            writer.writerow([r["wb"], r["exposure"], r["gain"],
                             s["neutrality"], s["luminance_err"],
                             s["color_err"], s["clip_penalty"], s["total"]])
    save_comparison(reference_image, best_image, rois, best, compare_path)

    print("\n=== BEST ===")
    print(f"  wb={best['wb']}  exposure={best['exposure']}  gain={best['gain']}")
    print(f"  score={best['score']}")
    print("  grayscale neutrality (R/G/B spread per tile):")
    for name in GRAY_TILES:
        b, g, r = best["tiles"][name][0]
        print(f"    {name:11s} bgr=[{b},{g},{r}]  lum={luminance([b,g,r]):.0f}")
    print("  color tiles (hsv):")
    for name in COLOR_TILES:
        print(f"    {name:11s} hsv={best['tiles'][name][1]}  "
              f"ref={reference[profile.key][name]['hsv']}")
    print(f"\nresults  -> {results_path}")
    print(f"sorted   -> {csv_path}")
    print(f"best     -> {best_path}")
    print(f"compare  -> {compare_path}")
    print(f"\nCommit into {profile.lock_const} (irl/config.py):")
    print(f"  exposure={float(best['exposure'])}, "
          f"wb_temperature={float(best['wb'])}, gain={float(best['gain'])}")
    vision.stop()
    return 0


# =============================================================================
# entrypoint
# =============================================================================


def _add_camera_arg(p) -> None:
    p.add_argument("--camera", choices=sorted(PROFILES.keys()),
                   default="classification_top",
                   help="which camera to calibrate (default: classification_top)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_roi = sub.add_parser("roi", help="click the 8 tile centers, save ROIs")
    p_roi.add_argument("--size", type=int, default=DEFAULT_ROI_SIZE,
                       help="ROI square side length in px")
    _add_camera_arg(p_roi)
    p_roi.set_defaults(func=cmd_roi)

    p_ref = sub.add_parser("reference", help="capture the reference snapshot")
    _add_camera_arg(p_ref)
    p_ref.set_defaults(func=cmd_reference)

    p_sweep = sub.add_parser("sweep", help="sweep settings, score vs reference")
    p_sweep.add_argument("--wb-start", type=int, default=3000)
    p_sweep.add_argument("--wb-end", type=int, default=6500)
    p_sweep.add_argument("--wb-step", type=int, default=250)
    p_sweep.add_argument("--exposures", type=int, nargs="*", default=None,
                         help="explicit exposure-time-abs candidates (1-5000)")
    p_sweep.add_argument("--gains", type=int, nargs="*", default=None,
                         help="explicit gain candidates (0-100)")
    p_sweep.add_argument("--settle-ms", type=int, default=500,
                         help="wait after each setting change before capture")
    p_sweep.add_argument("--fine", action="store_true",
                         help="add a fine WB pass around the best coarse result")
    p_sweep.add_argument("--reset", action="store_true",
                         help="ignore tuned defaults/overrides and build a broad "
                              "discovery sweep from this camera's reported "
                              "exposure/WB/gain ranges (use after swapping cameras)")
    _add_camera_arg(p_sweep)
    p_sweep.set_defaults(func=cmd_sweep)

    args = parser.parse_args()
    args.profile = PROFILES[args.camera]
    # mkGlobalConfig() (called via startVision -> mkIRLConfig/mkIRLInterface) runs
    # its own argparse against sys.argv with only a --disable flag; strip our own
    # subcommand/args so it doesn't choke on them (same pattern as
    # calibrate_classification_baseline.py).
    sys.argv = sys.argv[:1]
    return args.func(args)


if __name__ == "__main__":
    code = main()
    # On macOS, OpenCV's Cocoa-backed imshow/destroyAllWindows can leave a native
    # event-loop thread alive that Python's daemon-thread cleanup never reaches,
    # hanging the process after main() has finished. Force-exit instead.
    os._exit(code)
