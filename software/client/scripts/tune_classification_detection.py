"""Live tuner for the HSV classification detection thresholds.

Brings up the vision stack, loads the classification baseline, and shows the
detection pipeline live so you can place test pieces and tune `low_sat_thresh`
and `pixel_thresh` against the RAW diff map (not just the thresholded mask the
main-app overlay shows). Trackbar changes apply instantly — no app restart.

Panels (left to right):
  1. live camera with detection bboxes drawn
  2. saturation channel + low-sat gate region (where hue is ignored)
  3. raw combined diff (JET colormap, pre-threshold)
  4. hot mask after threshold + geometry filters

Keys:  p = print current config line to paste into ClassificationDiffConfig
       q / ESC = quit

Usage (from software/client/, target removed, place real pieces):
    .venv/bin/python scripts/tune_classification_detection.py [--cam top|bottom]
"""

import sys
import os
import time
import argparse
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from vision import VisionManager
from vision.heatmap_diff import _hueArcDistance, HUE_DIFF_SCALE

WINDOW = "classification detection tuner"


def _inspectPixel(cx, cy, panel_w, panel_h, live, hs, heatmap, low_sat,
                  v_cur_full=None, v_lo_full=None, v_hi_full=None) -> None:
    """Print the H/S, envelope, and per-channel diff at a clicked point in the
    top-left (live) panel — turns 'why isn't it detected' into measured numbers.

    If a V (value/brightness) envelope and live V frame are supplied, also report
    V vs its envelope — to gauge whether brightness is a usable extra signal for
    pieces hue+saturation can't separate (e.g. the contaminated bottom reds)."""
    fh, fw = live.shape[:2]
    fx = min(fw - 1, int(cx * fw / panel_w))
    fy = min(fh - 1, int(cy * fh / panel_h))
    h_cur, s_cur = int(hs[fy, fx, 0]), int(hs[fy, fx, 1])

    bl_min, bl_max = heatmap._baseline_min, heatmap._baseline_max
    if bl_min is None or bl_max is None:
        print(f"  ({fx},{fy}) H={h_cur} S={s_cur}  (no envelope loaded)")
        return
    # Envelope is stored at the heatmap's diff scale (0.25).
    dh, dw = bl_min.shape[:2]
    dx = min(dw - 1, int(fx * heatmap._scale))
    dy = min(dh - 1, int(fy * heatmap._scale))
    h_min, s_min = int(bl_min[dy, dx, 0]), int(bl_min[dy, dx, 1])
    h_max, s_max = int(bl_max[dy, dx, 0]), int(bl_max[dy, dx, 1])

    h_dist = float(_hueArcDistance(np.array(h_cur), np.array(h_min), np.array(h_max)))
    h_diff = min(255.0, h_dist * HUE_DIFF_SCALE)
    s_diff = max(0, s_min - s_cur, s_cur - s_max)

    # non-hue diff = S, plus V when the value channel is in play (matches
    # heatmap_diff._envelopeDiffHS so `combined` equals actual detection).
    non_hue = s_diff
    v_str = ""
    if v_cur_full is not None and v_lo_full is not None and v_hi_full is not None:
        # V envelope PNGs are full-res (V is not rotated/downscaled here).
        v_cur = int(v_cur_full[fy, fx])
        v_min = int(v_lo_full[fy, fx])
        v_max = int(v_hi_full[fy, fx])
        v_diff = max(0, v_min - v_cur, v_cur - v_max)
        if getattr(heatmap, "_channel_mode", "hs") == "hsv":
            non_hue = max(non_hue, v_diff)
        v_str = f" | V={v_cur} envV=[{v_min},{v_max}] v_diff={v_diff}"

    gated = s_cur < low_sat
    combined = non_hue if gated else max(h_diff, non_hue)
    label = "LOW-SAT->no hue" if gated else "max(h,s,v)"
    print(
        f"  ({fx},{fy}) cur H={h_cur} S={s_cur} | env H=[{h_min},{h_max}] S=[{s_min},{s_max}] "
        f"| h_diff={h_diff:.0f} s_diff={s_diff} "
        f"| {label} -> combined={combined:.0f} "
        f"(thresh={heatmap._pixel_thresh}){v_str}"
    )


def _panelLabel(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cam", choices=["top", "bottom", "carousel"], default="top")
    args = parser.parse_args()
    cam = args.cam

    # mkGlobalConfig runs its own argparse against sys.argv (only knows
    # --disable); strip our flags so it doesn't choke.
    sys.argv = sys.argv[:1]

    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    # No motion is needed for camera tuning — keep all steppers de-energized.
    irl.disableSteppers()
    vision = VisionManager(irl_config, gc, irl)
    vision.start()

    # Frame source: classification cameras expose annotated properties; the
    # carousel uses the generic getFrame accessor.
    frame_name = {"top": "classification_top", "bottom": "classification_bottom",
                  "carousel": "carousel"}[cam]
    get_frame_prop = lambda: vision.getFrame(frame_name)

    print("waiting for camera frames (up to 15s)...")
    deadline = time.time() + 15.0
    while time.time() < deadline and get_frame_prop() is None:
        time.sleep(0.25)
    if get_frame_prop() is None:
        print(f"ERROR: no {cam} camera frames (is it assigned in camera_setup?)")
        vision.stop()
        return 1

    if cam == "carousel":
        if not vision.loadCarouselHsvBaseline():
            print("ERROR: no carousel HSV baseline. Run: "
                  "scripts/calibrate_classification_baseline.py --camera carousel --wipe")
            vision.stop()
            return 1
        heatmap = vision._carousel_hsv_heatmap
        analysis = None
        get_hs = vision._getLatestCarouselHSV
    else:
        if not vision.loadClassificationBaseline():
            print("ERROR: no classification baseline loaded. "
                  "Run scripts/calibrate_classification_baseline.py --wipe first.")
            vision.stop()
            return 1
        if cam == "top":
            heatmap = vision._classification_top_heatmap
            analysis = vision._classification_top_analysis
        else:
            heatmap = vision._classification_bottom_heatmap
            analysis = vision._classification_bottom_analysis
        # Match the getter's channel count to the heatmap mode (hsv -> 3ch).
        hsv_mode = heatmap is not None and getattr(heatmap, "_channel_mode", "hs") == "hsv"
        if cam == "top":
            get_hs = vision._getLatestClassificationTopHSV if hsv_mode else vision._getLatestClassificationTopHS
        else:
            get_hs = vision._getLatestClassificationBottomHSV if hsv_mode else vision._getLatestClassificationBottomHS

    if heatmap is None or not heatmap.has_baseline:
        print(f"ERROR: {cam} heatmap/baseline not available")
        vision.stop()
        return 1

    # Stop the analysis thread so only this loop drives the heatmap (avoids
    # racing pushFrame / the diff cache between two threads).
    if analysis is not None:
        analysis.stop()

    # Load the full-res V (brightness) envelope for the inspector only — V isn't
    # used in detection, this just lets us measure whether it's a usable signal.
    from blob_manager import BLOB_DIR
    bdir = BLOB_DIR / "classification_baseline"
    v_lo = cv2.imread(str(bdir / f"{cam}_baseline_v_min.png"), cv2.IMREAD_GRAYSCALE)
    v_hi = cv2.imread(str(bdir / f"{cam}_baseline_v_max.png"), cv2.IMREAD_GRAYSCALE)

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.createTrackbar("low_sat", WINDOW, int(heatmap._low_sat_thresh), 255, lambda v: None)
    cv2.createTrackbar("pixel_thresh", WINDOW, int(heatmap._pixel_thresh), 100, lambda v: None)

    mouse = {"click": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse["click"] = (x, y)

    cv2.setMouseCallback(WINDOW, on_mouse)

    print("\nplace a test piece in the chamber. tune the trackbars; click the piece "
          "in the top-left panel to inspect its H/S vs the envelope; 'p' to print "
          "values, 'q' to quit.\n")

    panel_h = 360
    while True:
        low_sat = cv2.getTrackbarPos("low_sat", WINDOW)
        pixel_thresh = cv2.getTrackbarPos("pixel_thresh", WINDOW)
        heatmap._low_sat_thresh = low_sat
        heatmap._pixel_thresh = pixel_thresh

        hs = get_hs()
        frame = get_frame_prop()
        if hs is not None:
            heatmap.pushFrame(hs)
        # Invalidate the cache so the new thresholds take effect this iteration.
        heatmap._cached_result = None
        result = heatmap._computeDiffMap()

        live = frame.raw if frame is not None else np.zeros((panel_h, panel_h, 3), np.uint8)
        bboxes = heatmap.computeBboxes() if result is not None else []
        live_draw = live.copy()
        for x1, y1, x2, y2 in bboxes:
            cv2.rectangle(live_draw, (x1, y1), (x2, y2), (0, 255, 0), 3)

        # saturation channel + low-sat gate overlay (red tint where hue ignored)
        s_full = hs[:, :, 1] if hs is not None else np.zeros((panel_h, panel_h), np.uint8)
        s_vis = cv2.cvtColor(s_full, cv2.COLOR_GRAY2BGR)
        low_mask = s_full < low_sat
        s_vis[low_mask] = (s_vis[low_mask] * 0.4 + np.array([0, 0, 150]) * 0.6).astype(np.uint8)

        if result is not None:
            diff, hot, mask_bool = result
            diff_vis = cv2.applyColorMap(diff, cv2.COLORMAP_JET)
            diff_vis[~mask_bool] = 0
            hot_vis = cv2.cvtColor((hot.astype(np.uint8) * 255), cv2.COLOR_GRAY2BGR)
        else:
            diff_vis = np.zeros((panel_h, panel_h, 3), np.uint8)
            hot_vis = np.zeros((panel_h, panel_h, 3), np.uint8)

        # All four panels share the camera aspect ratio; force a common
        # (panel_w, panel_h) so the 2x2 grid rows/cols line up exactly.
        ph, pw = live_draw.shape[:2]
        panel_w = int(pw * panel_h / ph)

        # Click in the top-left (live) panel -> print that pixel's H/S/V diagnostics.
        click = mouse["click"]
        if click is not None:
            mouse["click"] = None
            cx, cy = click
            if cx < panel_w and cy < panel_h and hs is not None:
                v_full = (cv2.cvtColor(live, cv2.COLOR_BGR2HSV)[:, :, 2]
                          if frame is not None else None)
                _inspectPixel(cx, cy, panel_w, panel_h, live, hs, heatmap, low_sat,
                              v_cur_full=v_full, v_lo_full=v_lo, v_hi_full=v_hi)

        def fit(img):
            return cv2.resize(img, (panel_w, panel_h))

        tl = _panelLabel(fit(live_draw), f"live  bboxes={len(bboxes)}")
        tr = _panelLabel(fit(s_vis), f"saturation (red=low-sat<{low_sat})")
        bl = _panelLabel(fit(diff_vis), f"raw diff (thresh={pixel_thresh})")
        br = _panelLabel(fit(hot_vis), "hot mask")
        grid = np.vstack([np.hstack([tl, tr]), np.hstack([bl, br])])
        cv2.imshow(WINDOW, grid)

        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("p"):
            print(f"  low_sat_thresh={low_sat}, pixel_thresh={pixel_thresh}")

    cv2.destroyAllWindows()
    cv2.waitKey(1)
    vision.stop()
    return 0


if __name__ == "__main__":
    code = main()
    # macOS: OpenCV's Cocoa imshow can leave a native event-loop thread alive
    # that hangs process exit; force-terminate like the other GUI scripts.
    os._exit(code)
