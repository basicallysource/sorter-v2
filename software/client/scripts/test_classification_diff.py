"""
Classification chamber diff tuning UI.
Shows live heatmap diff with adjustable params + envelope margin.
Rotate carousel to test false positives on empty platform.

Run from /software/client: uv run python scripts/test_classification_diff.py
Then open http://localhost:8099 in a browser.
"""

import sys
import time
import threading
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, render_template_string, jsonify, request

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from vision.camera import CaptureThread
from vision.heatmap_diff import HeatmapDiff
from vision.diff_configs import DEFAULT_CLASSIFICATION_DIFF_CONFIG
from blob_manager import BLOB_DIR, getCameraSetup, getClassificationPolygons
from irl.config import mkCameraConfig
import glob as globmod

PORT = 8099
DEGREES_PER_STEP = -90
DEGREES_BACKOFF = 0
BACKOFF_SPEED = 50
SCALE = 0.25

ENVELOPE_PARAMS = {"envelope_margin", "adaptive_std_k", "mask_erode_px"}

app = Flask(__name__)


def loadBaselineFrames(baseline_dir: Path, prefix: str) -> list[np.ndarray]:
    frames = []
    paths = sorted(globmod.glob(str(baseline_dir / f"{prefix}_frame_*.png")))
    for p in paths:
        gray = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            frames.append(gray)
    return frames


def buildMask(cam_key: str, shape: tuple[int, ...]) -> np.ndarray:
    saved = getClassificationPolygons()
    if saved is None:
        return np.ones(shape[:2], dtype=np.uint8) * 255
    res = saved.get("resolution")
    polygons = saved.get("polygons", {})
    pts = polygons.get(cam_key)
    if pts is None or len(pts) < 3:
        return np.ones(shape[:2], dtype=np.uint8) * 255
    polygon = np.array(pts, dtype=np.int32)
    if res and len(res) == 2:
        src_w, src_h = int(res[0]), int(res[1])
        h, w = shape[:2]
        if src_w != w or src_h != h:
            polygon = (polygon.astype(np.float64) * [w / src_w, h / src_h]).astype(np.int32)
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)
    return mask


def computeStddevMap(frames: list[np.ndarray]) -> np.ndarray:
    stack = np.stack(frames, axis=0).astype(np.float32)
    return np.std(stack, axis=0).astype(np.float32)


class AppState:
    def __init__(self, capture: CaptureThread, carousel_stepper, irl_config, baseline_min: np.ndarray, baseline_max: np.ndarray, mask: np.ndarray, calibration_frames: list[np.ndarray]):
        self.capture = capture
        self.carousel_stepper = carousel_stepper
        self._normal_speed = irl_config.carousel_stepper.default_steps_per_second
        self._baseline_min_orig = baseline_min.copy()
        self._baseline_max_orig = baseline_max.copy()
        self._mask_orig = mask.copy()
        self._mask_bbox = cv2.boundingRect(mask)  # (x, y, w, h) of polygon region
        self._calibration_frames = calibration_frames
        self._stddev_map: np.ndarray | None = None
        if len(calibration_frames) >= 2:
            self._stddev_map = computeStddevMap(calibration_frames)

        self.heatmap = HeatmapDiff(scale=SCALE)
        self.lock = threading.Lock()
        self.detection_log: list[dict] = []
        self.rotation_count = 0

        _cfg = DEFAULT_CLASSIFICATION_DIFF_CONFIG
        self._default_params: dict[str, float] = {
            "envelope_margin": float(_cfg.envelope_margin),
            "adaptive_std_k": float(_cfg.adaptive_std_k),
            "pixel_thresh": float(_cfg.pixel_thresh),
            "blur_kernel": float(_cfg.blur_kernel),
            "min_hot_pixels": float(_cfg.min_hot_pixels),
            "trigger_score": float(_cfg.trigger_score),
            "min_contour_area": float(_cfg.min_contour_area),
            "min_hot_thickness": float(_cfg.min_hot_thickness_px),
            "max_contour_aspect": float(_cfg.max_contour_aspect),
            "heat_gain": float(_cfg.heat_gain),
            "current_frames": float(_cfg.current_frames),
            "min_bbox_dim": float(_cfg.min_bbox_dim),
            "min_bbox_area": float(_cfg.min_bbox_area),
            "crop_margin_px": float(_cfg.crop_margin_px),
            "edge_bias_mult": float(_cfg.edge_bias_mult),
            "edge_bias_threshold_px": float(_cfg.edge_bias_threshold_px),
            # script-only
            "mask_erode_px": 0.0,
        }
        self.params: dict[str, float] = dict(self._default_params)

        self._rebuildHeatmap()
        self._running = True
        self._thread = threading.Thread(target=self._feedLoop, daemon=True)
        self._thread.start()

    def _applyModuleConstants(self) -> None:
        import vision.heatmap_diff as hd_mod
        p = self.params
        hd_mod.PIXEL_THRESH = int(p["pixel_thresh"])
        hd_mod.BLUR_KERNEL = int(p["blur_kernel"])
        hd_mod.MIN_HOT_PIXELS = int(p["min_hot_pixels"])
        hd_mod.TRIGGER_SCORE = int(p["trigger_score"])
        hd_mod.MIN_CONTOUR_AREA = int(p["min_contour_area"])
        hd_mod.MIN_HOT_THICKNESS_PIXELS = int(p["min_hot_thickness"])
        hd_mod.MAX_CONTOUR_ASPECT_RATIO = float(p["max_contour_aspect"])
        hd_mod.HEAT_GAIN = float(p["heat_gain"])
        hd_mod.CURRENT_FRAMES = int(p["current_frames"])

    def _rebuildEnvelope(self) -> None:
        p = self.params
        margin = int(p["envelope_margin"])
        adaptive_k = p["adaptive_std_k"]
        erode_px = int(p["mask_erode_px"])

        bl_min = self._baseline_min_orig.copy()
        bl_max = self._baseline_max_orig.copy()
        mask = self._mask_orig.copy()

        if adaptive_k > 0 and self._stddev_map is not None:
            adaptive_margin = np.clip(self._stddev_map * adaptive_k, 0, 100).astype(np.uint8)
            bl_min = np.clip(bl_min.astype(np.int16) - adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)
            bl_max = np.clip(bl_max.astype(np.int16) + adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)

        if margin > 0:
            bl_min = np.clip(bl_min.astype(np.int16) - margin, 0, 255).astype(np.uint8)
            bl_max = np.clip(bl_max.astype(np.int16) + margin, 0, 255).astype(np.uint8)

        if erode_px > 0:
            k = max(1, int(erode_px))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2 + 1, k * 2 + 1))
            mask = cv2.erode(mask, kernel)

        self.heatmap = HeatmapDiff(scale=SCALE)
        self.heatmap.loadEnvelope(bl_min, bl_max, mask)

    def _rebuildHeatmap(self) -> None:
        self._applyModuleConstants()
        self._rebuildEnvelope()

    def _feedLoop(self) -> None:
        while self._running:
            frame = self.capture.latest_frame
            if frame is not None:
                gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
                self.heatmap.pushFrame(gray)
            time.sleep(0.04)

    def _edgeBiasedMargins(
        self,
        bbox: tuple[int, int, int, int],
        base_margin: int,
        mult: float,
        threshold: int,
        mask_x1: int, mask_y1: int, mask_x2: int, mask_y2: int,
    ) -> tuple[int, int, int, int]:
        dist_left = bbox[0] - mask_x1
        dist_top = bbox[1] - mask_y1
        dist_right = mask_x2 - bbox[2]
        dist_bottom = mask_y2 - bbox[3]

        def biased(dist: int) -> int:
            if threshold <= 0 or dist >= threshold:
                return base_margin
            proximity = 1.0 - (dist / threshold)
            return int(base_margin * (1.0 + (mult - 1.0) * proximity))

        return (biased(dist_left), biased(dist_top), biased(dist_right), biased(dist_bottom))

    def getAnnotatedFrame(self) -> np.ndarray | None:
        frame = self.capture.latest_frame
        if frame is None:
            return None

        annotated = frame.raw.copy()
        annotated = self.heatmap.annotateFrame(annotated, label="diff", text_y=50)

        bboxes = self.heatmap.computeBboxes()
        min_dim = int(self.params["min_bbox_dim"])
        min_area = int(self.params["min_bbox_area"])
        filtered = []
        for bbox in bboxes:
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w >= min_dim and h >= min_dim and w * h >= min_area:
                filtered.append(bbox)

        n_filtered = len(bboxes) - len(filtered)
        if n_filtered > 0:
            cv2.putText(annotated, f"bbox filtered: {n_filtered}", (30, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 255), 2)

        crop_margin = int(self.params["crop_margin_px"])
        edge_mult = self.params["edge_bias_mult"]
        edge_thresh = int(self.params["edge_bias_threshold_px"])
        fh, fw = frame.raw.shape[:2]
        mask_x, mask_y, mask_w, mask_h = self._mask_bbox
        for bbox in filtered:
            margins = self._edgeBiasedMargins(bbox, crop_margin, edge_mult, edge_thresh, mask_x, mask_y, mask_x + mask_w, mask_y + mask_h)
            mx1 = max(0, bbox[0] - margins[0])
            my1 = max(0, bbox[1] - margins[1])
            mx2 = min(fw, bbox[2] + margins[2])
            my2 = min(fh, bbox[3] + margins[3])
            cv2.rectangle(annotated, (mx1, my1), (mx2, my2), (0, 200, 255), 2, cv2.LINE_AA)
            label_parts = []
            for side, val in zip(["L", "T", "R", "B"], margins):
                if val != crop_margin:
                    label_parts.append(f"{side}:{val}")
            bias_label = f"  ({', '.join(label_parts)})" if label_parts else ""
            cv2.putText(annotated, f"crop +{crop_margin}px{bias_label}", (mx1, my1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

        detected = len(filtered) > 0
        label = f"DETECTED: {len(filtered)}" if detected else "clear"
        color = (0, 0, 255) if detected else (0, 255, 0)
        cv2.putText(annotated, label, (30, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)

        cv2.putText(annotated, f"rotations: {self.rotation_count}", (30, 165),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 2)

        return annotated

    def rotateCarousel(self) -> None:
        self.carousel_stepper.move_degrees_blocking(DEGREES_PER_STEP, timeout_ms=15000)
        # time.sleep(0.2)
        # self.carousel_stepper.set_speed_limits(16, BACKOFF_SPEED)
        # self.carousel_stepper.move_degrees_blocking(DEGREES_BACKOFF, timeout_ms=10000)
        # self.carousel_stepper.set_speed_limits(16, self._normal_speed)
        self.rotation_count += 1


state: AppState = None  # type: ignore[assignment]


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Classification Diff Tuner</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #111; color: #eee; font-family: monospace;
               display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 340px; min-width: 340px; padding: 12px; overflow-y: auto;
                   background: #1a1a1a; border-right: 1px solid #333;
                   display: flex; flex-direction: column; gap: 6px; }
        .sidebar h2 { font-size: 15px; margin: 0 0 4px; color: #aaa; }
        .main { flex: 1; display: flex; flex-direction: column; align-items: center;
                justify-content: center; overflow: hidden; }
        img { max-width: 100%; max-height: 100%; display: block; }
        .actions { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
        button { padding: 6px 16px; font-size: 13px; cursor: pointer;
                 background: #2a6; color: #fff; border: none; border-radius: 4px;
                 font-family: monospace; }
        button:hover { background: #3b7; }
        button.warn { background: #b63; }
        button.warn:hover { background: #d84; }
        .section { border-top: 1px solid #333; padding-top: 8px; margin-top: 4px; }
        .section-label { font-size: 11px; color: #666; text-transform: uppercase;
                         letter-spacing: 1px; margin-bottom: 4px; }
        .param { margin-bottom: 6px; }
        .param label { font-size: 12px; color: #999; display: block; }
        .param .row { display: flex; align-items: center; gap: 6px; }
        .param input[type=range] { flex: 1; accent-color: #2a6; }
        .param .val { font-size: 13px; min-width: 45px; text-align: right; color: #4f8; }
        .param .desc { font-size: 10px; color: #555; }
        #log { font-size: 11px; color: #888; max-height: 150px; overflow-y: auto;
               border-top: 1px solid #333; padding-top: 6px; margin-top: auto; }
        #log div { padding: 1px 0; }
        #log .fp { color: #f66; }
        #log .tn { color: #6f6; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="actions">
            <button onclick="rotate()">Rotate -90&deg;</button>
            <button class="warn" onclick="resetParams()">Reset All</button>
            <button onclick="copyParams()">Copy Params</button>
            <span id="copy-status" style="font-size:11px;color:#888;"></span>
        </div>

        <div class="section">
            <div class="section-label">Envelope Improvements</div>
            <div class="param">
                <label>Envelope Margin (&plusmn;N)</label>
                <div class="row">
                    <input type="range" min="0" max="40" step="1" data-key="envelope_margin" />
                    <span class="val"></span>
                </div>
                <span class="desc">Flat margin added to min/max envelope</span>
            </div>
            <div class="param">
                <label>Adaptive Std K</label>
                <div class="row">
                    <input type="range" min="0" max="5" step="0.25" data-key="adaptive_std_k" />
                    <span class="val"></span>
                </div>
                <span class="desc">Per-pixel margin = K &times; stddev from calibration frames</span>
            </div>
            <div class="param">
                <label>Mask Erode (px)</label>
                <div class="row">
                    <input type="range" min="0" max="60" step="1" data-key="mask_erode_px" />
                    <span class="val"></span>
                </div>
                <span class="desc">Shrink polygon mask inward to exclude edges</span>
            </div>
        </div>

        <div class="section">
            <div class="section-label">Heatmap Diff Params</div>
            <div class="param">
                <label>Pixel Threshold</label>
                <div class="row">
                    <input type="range" min="2" max="40" step="1" data-key="pixel_thresh" />
                    <span class="val"></span>
                </div>
                <span class="desc">Min diff value to count as hot pixel</span>
            </div>
            <div class="param">
                <label>Blur Kernel</label>
                <div class="row">
                    <input type="range" min="1" max="21" step="2" data-key="blur_kernel" />
                    <span class="val"></span>
                </div>
                <span class="desc">Gaussian blur on diff map</span>
            </div>
            <div class="param">
                <label>Min Hot Pixels</label>
                <div class="row">
                    <input type="range" min="10" max="500" step="10" data-key="min_hot_pixels" />
                    <span class="val"></span>
                </div>
                <span class="desc">Min hot pixels to compute score</span>
            </div>
            <div class="param">
                <label>Trigger Score</label>
                <div class="row">
                    <input type="range" min="5" max="60" step="1" data-key="trigger_score" />
                    <span class="val"></span>
                </div>
                <span class="desc">Score threshold for detection</span>
            </div>
            <div class="param">
                <label>Min Contour Area</label>
                <div class="row">
                    <input type="range" min="10" max="1000" step="10" data-key="min_contour_area" />
                    <span class="val"></span>
                </div>
                <span class="desc">Min contour area at diff scale</span>
            </div>
            <div class="param">
                <label>Min Hot Thickness</label>
                <div class="row">
                    <input type="range" min="2" max="30" step="1" data-key="min_hot_thickness" />
                    <span class="val"></span>
                </div>
                <span class="desc">Erosion thickness filter (kills thin edge lines)</span>
            </div>
            <div class="param">
                <label>Max Contour Aspect</label>
                <div class="row">
                    <input type="range" min="1" max="10" step="0.5" data-key="max_contour_aspect" />
                    <span class="val"></span>
                </div>
                <span class="desc">Max aspect ratio for contours</span>
            </div>
            <div class="param">
                <label>Current Frames (avg)</label>
                <div class="row">
                    <input type="range" min="1" max="10" step="1" data-key="current_frames" />
                    <span class="val"></span>
                </div>
                <span class="desc">Number of frames averaged for current</span>
            </div>
            <div class="param">
                <label>Heat Gain (visual)</label>
                <div class="row">
                    <input type="range" min="1" max="20" step="0.5" data-key="heat_gain" />
                    <span class="val"></span>
                </div>
                <span class="desc">Heatmap overlay brightness</span>
            </div>
        </div>

        <div class="section">
            <div class="section-label">BBox Filters &amp; Crop</div>
            <div class="param">
                <label>Min BBox Dimension (px)</label>
                <div class="row">
                    <input type="range" min="0" max="300" step="10" data-key="min_bbox_dim" />
                    <span class="val"></span>
                </div>
            </div>
            <div class="param">
                <label>Min BBox Area (px&sup2;)</label>
                <div class="row">
                    <input type="range" min="0" max="80000" step="1000" data-key="min_bbox_area" />
                    <span class="val"></span>
                </div>
            </div>
            <div class="param">
                <label>Crop Margin (px)</label>
                <div class="row">
                    <input type="range" min="0" max="200" step="5" data-key="crop_margin_px" />
                    <span class="val"></span>
                </div>
                <span class="desc">Extra margin around bbox for final crop sent to classifier</span>
            </div>
            <div class="param">
                <label>Edge Bias Multiplier</label>
                <div class="row">
                    <input type="range" min="1" max="5" step="0.25" data-key="edge_bias_mult" />
                    <span class="val"></span>
                </div>
                <span class="desc">Multiply margin on sides near mask edge (1 = no bias)</span>
            </div>
            <div class="param">
                <label>Edge Bias Threshold (px)</label>
                <div class="row">
                    <input type="range" min="0" max="200" step="5" data-key="edge_bias_threshold_px" />
                    <span class="val"></span>
                </div>
                <span class="desc">Distance from mask edge where bias kicks in</span>
            </div>
        </div>

        <div id="log"></div>
    </div>
    <div class="main">
        <img id="feed" src="/feed" />
    </div>
    <script>
        let params = {};

        async function loadParams() {
            const res = await fetch('/params');
            params = await res.json();
            document.querySelectorAll('.param input[type=range]').forEach(input => {
                const key = input.dataset.key;
                if (params[key] !== undefined) {
                    input.value = params[key];
                    input.closest('.param').querySelector('.val').textContent = params[key];
                }
            });
        }

        document.querySelectorAll('.param input[type=range]').forEach(input => {
            input.addEventListener('input', async () => {
                const key = input.dataset.key;
                const val = parseFloat(input.value);
                input.closest('.param').querySelector('.val').textContent = val;
                params[key] = val;
                await fetch('/params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ [key]: val }),
                });
            });
        });

        async function rotate() {
            await fetch('/rotate', { method: 'POST' });
            addLog('rotated -90 deg');
        }

        async function copyParams() {
            const res = await fetch('/params_export');
            const text = await res.text();
            await navigator.clipboard.writeText(text);
            const el = document.getElementById('copy-status');
            el.textContent = 'copied!';
            setTimeout(() => { el.textContent = ''; }, 2000);
        }

        async function resetParams() {
            const res = await fetch('/reset', { method: 'POST' });
            params = await res.json();
            document.querySelectorAll('.param input[type=range]').forEach(input => {
                const key = input.dataset.key;
                if (params[key] !== undefined) {
                    input.value = params[key];
                    input.closest('.param').querySelector('.val').textContent = params[key];
                }
            });
            addLog('reset all params to defaults');
        }

        function addLog(msg, cls) {
            const el = document.getElementById('log');
            const div = document.createElement('div');
            div.textContent = new Date().toLocaleTimeString() + ' ' + msg;
            if (cls) div.className = cls;
            el.appendChild(div);
            el.scrollTop = el.scrollHeight;
        }

        loadParams();
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


def generateFrames():
    while True:
        frame = state.getAnnotatedFrame()
        if frame is None:
            time.sleep(0.03)
            continue
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(0.033)


@app.route("/feed")
def feed():
    return Response(generateFrames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/params", methods=["GET"])
def get_params():
    return jsonify(state.params)


@app.route("/params", methods=["POST"])
def set_params():
    updates = request.get_json()
    needs_envelope_rebuild = False
    needs_constants = False
    for k, v in updates.items():
        if k in state.params:
            state.params[k] = float(v)
            if k in ENVELOPE_PARAMS:
                needs_envelope_rebuild = True
            else:
                needs_constants = True
    if needs_envelope_rebuild:
        state._rebuildHeatmap()
    elif needs_constants:
        state._applyModuleConstants()
        state.heatmap._cached_result = None
    return jsonify(state.params)


@app.route("/params_export")
def params_export():
    lines = ["classification diff params:"]
    for k, v in state.params.items():
        default = state._default_params[k]
        marker = "  <-- changed" if v != default else ""
        lines.append(f"  {k}: {v}{marker}")
    changed = {k: v for k, v in state.params.items() if v != state._default_params[k]}
    if changed:
        lines.append("")
        lines.append(f"changed from default: {changed}")
    else:
        lines.append("")
        lines.append("(all defaults)")
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/reset", methods=["POST"])
def reset_params():
    state.params = dict(state._default_params)
    state._rebuildHeatmap()
    return jsonify(state.params)


@app.route("/rotate", methods=["POST"])
def rotate():
    state.rotateCarousel()
    return jsonify({"ok": True})


if __name__ == "__main__":
    camera_setup = getCameraSetup()
    if camera_setup is None or "classification_top" not in camera_setup:
        print("ERROR: No classification_top camera found. Run camera_setup.py first.")
        sys.exit(1)

    baseline_dir = BLOB_DIR / "classification_baseline"
    min_img = cv2.imread(str(baseline_dir / "top_baseline_min.png"), cv2.IMREAD_GRAYSCALE)
    max_img = cv2.imread(str(baseline_dir / "top_baseline_max.png"), cv2.IMREAD_GRAYSCALE)
    if min_img is None or max_img is None:
        print("ERROR: no baseline images. run calibrate_classification_baseline.py first.")
        sys.exit(1)

    calibration_frames = loadBaselineFrames(baseline_dir, "top")
    print(f"loaded {len(calibration_frames)} calibration frames")

    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    capture = CaptureThread("classification_top", mkCameraConfig(camera_setup["classification_top"]))
    capture.start()

    print("waiting for camera...")
    time.sleep(2.0)

    frame = capture.latest_frame
    if frame is not None:
        cam_h, cam_w = frame.raw.shape[:2]
        bl_h, bl_w = min_img.shape[:2]
        if cam_w != bl_w or cam_h != bl_h:
            print(f"rescaling baseline {bl_w}x{bl_h} -> {cam_w}x{cam_h}")
            min_img = cv2.resize(min_img, (cam_w, cam_h), interpolation=cv2.INTER_AREA)
            max_img = cv2.resize(max_img, (cam_w, cam_h), interpolation=cv2.INTER_AREA)
            calibration_frames = [cv2.resize(f, (cam_w, cam_h), interpolation=cv2.INTER_AREA) for f in calibration_frames]

    mask = buildMask("top", min_img.shape)

    state = AppState(capture, irl.carousel_stepper, irl_config, min_img, max_img, mask, calibration_frames)

    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
