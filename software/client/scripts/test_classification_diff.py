"""
Classification chamber diff tuning UI.
Shows live heatmap diff with adjustable params + envelope margin.
Rotate carousel to test false positives on empty platform.

Run from /software/client: uv run python scripts/test_classification_diff.py
Then open http://localhost:8099 in a browser.
"""

import os
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
RECORDINGS_DIR = "recordings_diff"

ENVELOPE_PARAMS = {"envelope_margin", "adaptive_std_k"}

app = Flask(__name__)


def loadBaselineLabFrames(baseline_dir: Path, prefix: str) -> list[np.ndarray]:
    frames = []
    paths = sorted(globmod.glob(str(baseline_dir / f"{prefix}_frame_lab_*.png")))
    for p in paths:
        lab_frame = cv2.imread(p, cv2.IMREAD_COLOR)
        if lab_frame is not None:
            frames.append(lab_frame)
    return frames


def loadBaselineGrayFrames(baseline_dir: Path, prefix: str) -> list[np.ndarray]:
    frames = []
    paths = sorted(globmod.glob(str(baseline_dir / f"{prefix}_frame_*.png")))
    for p in paths:
        gray = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            frames.append(gray)
    return frames


def normalizeColorMode(value: str) -> str:
    mode = str(value).lower()
    if mode not in ("gray", "lab"):
        raise ValueError(f"invalid color_mode: {value}")
    return mode


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
    def __init__(self, capture: CaptureThread, carousel_stepper, irl_config, baseline_min: np.ndarray, baseline_max: np.ndarray, mask: np.ndarray, calibration_frames: list[np.ndarray], color_mode: str):
        self.capture = capture
        self.carousel_stepper = carousel_stepper
        self._color_mode = normalizeColorMode(color_mode)
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
        self._default_params: dict[str, float | str] = {
            "color_mode": self._color_mode,
            "envelope_margin": float(_cfg.envelope_margin),
            "adaptive_std_k": float(_cfg.adaptive_std_k),
            "pixel_thresh": float(_cfg.pixel_thresh),
            "color_thresh_ab": float(_cfg.color_thresh_ab),
            "blur_kernel": float(_cfg.blur_kernel),
            "min_hot_pixels": float(_cfg.min_hot_pixels),
            "trigger_score": float(_cfg.trigger_score),
            "min_contour_area": float(_cfg.min_contour_area),
            "min_hot_thickness": float(_cfg.min_hot_thickness_px),
            "hot_erode_iters": float(_cfg.hot_erode_iters),
            "hot_regrow_iters": float(_cfg.hot_regrow_iters),
            "max_contour_aspect": float(_cfg.max_contour_aspect),
            "heat_gain": float(_cfg.heat_gain),
            "current_frames": float(_cfg.current_frames),
            "min_bbox_dim": float(_cfg.min_bbox_dim),
            "min_bbox_area": float(_cfg.min_bbox_area),
            "crop_margin_px": float(_cfg.crop_margin_px),
            "edge_bias_mult": float(_cfg.edge_bias_mult),
            "edge_bias_threshold_px": float(_cfg.edge_bias_threshold_px),
            "bbox_diff_thresh": float(_cfg.bbox_diff_thresh),
        }
        self.params: dict[str, float | str] = dict(self._default_params)

        self._rebuildHeatmap()
        self._running = True
        self._recording = False
        self._record_writer: cv2.VideoWriter | None = None
        self._record_path: str | None = None
        self._replay_mode = False
        self._replay_cap: cv2.VideoCapture | None = None
        self._replay_idx = 0
        self._replay_total = 0
        self._replay_paused = False
        self._replay_speed = 1
        self._last_replay_out: np.ndarray | None = None
        self._replay_lock = threading.Lock()
        self._params_version = 0
        self._replay_params_ver = 0
        self._thread = threading.Thread(target=self._feedLoop, daemon=True)
        self._thread.start()

    def _applyModuleConstants(self) -> None:
        p = self.params
        h = self.heatmap
        h._pixel_thresh = int(p["pixel_thresh"])
        h._color_thresh_ab = int(p["color_thresh_ab"]) if self._color_mode == "lab" else 0
        h._blur_kernel = int(p["blur_kernel"])
        h._min_hot_pixels = int(p["min_hot_pixels"])
        h._trigger_score = int(p["trigger_score"])
        h._min_contour_area = int(p["min_contour_area"])
        h._min_hot_thickness_px = int(p["min_hot_thickness"])
        h._hot_erode_iters = int(p["hot_erode_iters"])
        h._hot_regrow_iters = int(p["hot_regrow_iters"])
        h._max_contour_aspect = float(p["max_contour_aspect"])
        h._heat_gain = float(p["heat_gain"])
        h._current_frames = int(p["current_frames"])

    def _rebuildEnvelope(self) -> None:
        p = self.params
        margin = int(p["envelope_margin"])
        adaptive_k = p["adaptive_std_k"]

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

        self.heatmap = HeatmapDiff(scale=SCALE)
        self.heatmap.loadEnvelope(bl_min, bl_max, mask)

    def _rebuildHeatmap(self) -> None:
        self._rebuildEnvelope()
        self._applyModuleConstants()

    def _feedLoop(self) -> None:
        while self._running:
            frame = self.capture.latest_frame
            if frame is not None:
                if self._color_mode == "lab":
                    diff_frame = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2LAB)
                else:
                    diff_frame = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
                self.heatmap.pushFrame(diff_frame)
                with self.lock:
                    if self._recording and self._record_writer is not None:
                        self._record_writer.write(frame.raw)
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

    def _annotate(self, raw: np.ndarray) -> np.ndarray:
        annotated = raw.copy()
        annotated = self.heatmap.annotateFrame(annotated, label="diff", text_y=50)

        bboxes = self.heatmap.computeBboxes(diff_thresh=self.params["bbox_diff_thresh"])
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
        fh, fw = raw.shape[:2]
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

        if self._replay_mode:
            speed_label = "MAX" if self._replay_speed == 0 else f"{self._replay_speed}x"
            status = "PAUSED" if self._replay_paused else speed_label
            cv2.putText(annotated, f"REPLAY {self._replay_idx}/{self._replay_total} [{status}]", (30, 165),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 100, 100), 2)
        else:
            cv2.putText(annotated, f"rotations: {self.rotation_count}", (30, 165),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 2)

        return annotated

    def getAnnotatedFrame(self) -> np.ndarray | None:
        if self._replay_mode:
            return self._getReplayFrame()
        frame = self.capture.latest_frame
        if frame is None:
            return None
        return self._annotate(frame.raw)

    def startRecording(self) -> None:
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        path = os.path.join(RECORDINGS_DIR, f"diff_{int(time.time())}.avi")
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        frame = self.capture.latest_frame
        h, w = (1080, 1920) if frame is None else frame.raw.shape[:2]
        self._record_writer = cv2.VideoWriter(path, fourcc, 25.0, (w, h))
        self._record_path = path
        self._recording = True
        print(f"Recording started: {path}")

    def stopRecording(self) -> None:
        with self.lock:
            self._recording = False
            writer = self._record_writer
            self._record_writer = None
        if writer is not None:
            writer.release()
        print(f"Recording stopped: {self._record_path}")

    def startReplay(self, path: str | None = None) -> bool:
        target = path or self._record_path
        if not target or not os.path.exists(target):
            return False
        self.stopRecording()
        with self._replay_lock:
            self._record_path = target
            self._replay_cap = cv2.VideoCapture(target)
            self._replay_total = int(self._replay_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self._replay_idx = 0
            self._replay_mode = True
            self._replay_paused = False
            self._replay_speed = 1
            self._replay_params_ver = self._params_version
        print(f"Replay started: {target} ({self._replay_total} frames)")
        return True

    def stopReplay(self) -> None:
        with self._replay_lock:
            self._replay_mode = False
            self._replay_paused = False
            cap = self._replay_cap
            self._replay_cap = None
        if cap is not None:
            cap.release()
        self._rebuildHeatmap()
        print("Replay stopped")

    def _pushReplayFrame(self, gray: np.ndarray) -> None:
        self.heatmap._last_ring_time = 0
        self.heatmap.pushFrame(gray)

    def _seekAndCompute(self, target_idx: int) -> None:
        cap = self._replay_cap
        if cap is None:
            return
        n_ctx = max(1, int(self.params["current_frames"]))
        start = max(0, target_idx - n_ctx)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        self._rebuildHeatmap()
        last_raw = None
        for i in range(start, target_idx):
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self._pushReplayFrame(gray)
            last_raw = frame
        self._replay_idx = target_idx
        if last_raw is not None:
            self._last_replay_out = self._annotate(last_raw)

    def seekReplay(self, target_idx: int) -> None:
        if not self._replay_mode:
            return
        with self._replay_lock:
            target_idx = max(1, min(target_idx, self._replay_total))
            self._seekAndCompute(target_idx)
            self._replay_paused = True
            self._replay_params_ver = self._params_version

    def _getReplayFrame(self) -> np.ndarray | None:
        if not self._replay_lock.acquire(blocking=False):
            return self._last_replay_out
        try:
            if self._params_version != self._replay_params_ver:
                self._seekAndCompute(self._replay_idx)
                self._replay_params_ver = self._params_version
                return self._last_replay_out

            cap = self._replay_cap
            if self._replay_paused or cap is None:
                return self._last_replay_out

            batch = 30 if self._replay_speed == 0 else self._replay_speed
            out = None
            for _ in range(batch):
                ret, frame = cap.read()
                if not ret:
                    self._replay_paused = True
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                self._pushReplayFrame(gray)
                self._replay_idx += 1
                out = self._annotate(frame)
            if out is not None:
                self._last_replay_out = out
            return self._last_replay_out
        finally:
            self._replay_lock.release()

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
        button.record { background: #900; }
        button.record.active { background: #f00; }
        button.replay { background: #06a; }
        button.replay:hover { background: #08c; }
        .replay-controls { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
        .replay-controls select { padding: 4px 6px; font-size: 12px; background: #222; color: #eee;
                                   border: 1px solid #555; border-radius: 4px; font-family: monospace; }
        .scrub-row { display: flex; align-items: center; gap: 6px; }
        .scrub-row input[type=range] { flex: 1; accent-color: #06a; }
        .scrub-row span { font-size: 11px; color: #aaa; }
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
            <div class="section-label">Record &amp; Replay</div>
            <div class="actions">
                <button id="btn_record" class="record" onclick="toggleRecord()">Record</button>
            </div>
            <div class="replay-controls">
                <select id="recording_select" style="max-width:200px"></select>
                <button class="replay" id="btn_replay" onclick="startReplay()">Replay</button>
                <button class="replay" id="btn_stop_replay" onclick="stopReplay()" style="display:none">Stop</button>
                <button id="btn_pause" onclick="togglePause()" style="display:none">Pause</button>
                <select id="replay_speed" onchange="setSpeed(this.value)" style="display:none">
                    <option value="1">1x</option>
                    <option value="2">2x</option>
                    <option value="4">4x</option>
                    <option value="8">8x</option>
                    <option value="0">Max</option>
                </select>
            </div>
            <div class="scrub-row" id="scrub_row" style="display:none;margin-top:4px">
                <input type="range" id="scrub_slider" min="1" max="1" value="1"
                       oninput="onScrubInput(this.value)" onchange="onScrubChange(this.value)" />
                <span id="scrub_label">0 / 0</span>
            </div>
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
                <label>Color Threshold (LAB a/b)</label>
                <div class="row">
                    <input type="range" min="0" max="40" step="1" data-key="color_thresh_ab" />
                    <span class="val"></span>
                </div>
                <span class="desc">Color-only diff threshold (0 disables color channel trigger)</span>
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
                <label>Hot Erode Iters</label>
                <div class="row">
                    <input type="range" min="1" max="4" step="1" data-key="hot_erode_iters" />
                    <span class="val"></span>
                </div>
                <span class="desc">Erode passes on hot zones before contouring</span>
            </div>
            <div class="param">
                <label>Hot Regrow Iters</label>
                <div class="row">
                    <input type="range" min="0" max="4" step="1" data-key="hot_regrow_iters" />
                    <span class="val"></span>
                </div>
                <span class="desc">Dilate passes after hot erosion (lower trims tails more)</span>
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
                <label>BBox Diff Threshold</label>
                <div class="row">
                    <input type="range" min="0" max="40" step="1" data-key="bbox_diff_thresh" />
                    <span class="val"></span>
                </div>
                <span class="desc">Only pixels with diff above this drive bbox shapes (0 = use all hot pixels)</span>
            </div>
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

        async function loadRecordings() {
            const res = await fetch('/recordings');
            const data = await res.json();
            const sel = document.getElementById('recording_select');
            sel.innerHTML = '';
            for (const r of data.recordings) {
                const opt = document.createElement('option');
                opt.value = r;
                opt.textContent = r;
                sel.appendChild(opt);
            }
        }

        async function toggleRecord() {
            const res = await fetch('/record/toggle', { method: 'POST' });
            const data = await res.json();
            const btn = document.getElementById('btn_record');
            if (data.recording) {
                btn.classList.add('active');
                btn.textContent = 'Stop Record';
            } else {
                btn.classList.remove('active');
                btn.textContent = 'Record';
                loadRecordings();
            }
        }

        async function startReplay() {
            const path = document.getElementById('recording_select').value;
            if (!path) return;
            const res = await fetch('/replay/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            const data = await res.json();
            if (data.ok) {
                document.getElementById('btn_replay').style.display = 'none';
                document.getElementById('btn_stop_replay').style.display = '';
                document.getElementById('btn_pause').style.display = '';
                document.getElementById('btn_pause').textContent = 'Pause';
                document.getElementById('replay_speed').style.display = '';
                const row = document.getElementById('scrub_row');
                const slider = document.getElementById('scrub_slider');
                row.style.display = 'flex';
                slider.max = data.total_frames;
                startStatusPoll();
            }
        }

        async function stopReplay() {
            await fetch('/replay/stop', { method: 'POST' });
            document.getElementById('btn_replay').style.display = '';
            document.getElementById('btn_stop_replay').style.display = 'none';
            document.getElementById('btn_pause').style.display = 'none';
            document.getElementById('replay_speed').style.display = 'none';
            document.getElementById('scrub_row').style.display = 'none';
            stopStatusPoll();
        }

        async function togglePause() {
            const res = await fetch('/replay/pause', { method: 'POST' });
            const data = await res.json();
            document.getElementById('btn_pause').textContent = data.paused ? 'Resume' : 'Pause';
        }

        async function setSpeed(val) {
            await fetch('/replay/speed', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speed: parseInt(val) }),
            });
        }

        let scrubTimeout = null;
        let scrubbing = false;

        function onScrubInput(val) {
            document.getElementById('scrub_label').textContent = val + ' / ' + document.getElementById('scrub_slider').max;
            scrubbing = true;
            if (scrubTimeout) clearTimeout(scrubTimeout);
            scrubTimeout = setTimeout(() => onScrubChange(val), 200);
        }

        function onScrubChange(val) {
            scrubbing = false;
            if (scrubTimeout) clearTimeout(scrubTimeout);
            scrubTimeout = null;
            fetch('/replay/seek', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frame: parseInt(val) }),
            }).then(() => {
                document.getElementById('btn_pause').textContent = 'Resume';
            });
        }

        let statusInterval = null;
        function startStatusPoll() {
            if (statusInterval) return;
            statusInterval = setInterval(async () => {
                const res = await fetch('/replay/status');
                const data = await res.json();
                if (!data.active) { stopStatusPoll(); return; }
                if (!scrubbing) {
                    const slider = document.getElementById('scrub_slider');
                    slider.max = data.total;
                    slider.value = data.frame;
                    document.getElementById('scrub_label').textContent = data.frame + ' / ' + data.total;
                }
            }, 250);
        }

        function stopStatusPoll() {
            if (statusInterval) { clearInterval(statusInterval); statusInterval = null; }
        }

        loadParams();
        loadRecordings();
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
        if not state._replay_mode:
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
            if k == "color_mode":
                state._color_mode = normalizeColorMode(v)
                state.params[k] = state._color_mode
                needs_envelope_rebuild = True
                needs_constants = True
                continue
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
    state._params_version += 1
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


@app.route("/record/toggle", methods=["POST"])
def toggle_record():
    if state._recording:
        state.stopRecording()
    else:
        state.startRecording()
    return jsonify({"recording": state._recording, "path": state._record_path})


@app.route("/recordings", methods=["GET"])
def list_recordings():
    if not os.path.isdir(RECORDINGS_DIR):
        return jsonify({"recordings": []})
    files = sorted(globmod.glob(os.path.join(RECORDINGS_DIR, "*.avi")), reverse=True)
    return jsonify({"recordings": files})


@app.route("/replay/start", methods=["POST"])
def start_replay():
    data = request.get_json() or {}
    path = data.get("path")
    ok = state.startReplay(path)
    return jsonify({"ok": ok, "total_frames": state._replay_total})


@app.route("/replay/stop", methods=["POST"])
def stop_replay():
    state.stopReplay()
    return jsonify({"ok": True})


@app.route("/replay/pause", methods=["POST"])
def pause_replay():
    state._replay_paused = not state._replay_paused
    return jsonify({"paused": state._replay_paused})


@app.route("/replay/speed", methods=["POST"])
def set_replay_speed():
    data = request.get_json() or {}
    state._replay_speed = int(data.get("speed", 1))
    return jsonify({"speed": state._replay_speed})


@app.route("/replay/seek", methods=["POST"])
def seek_replay():
    data = request.get_json() or {}
    target = int(data.get("frame", 0))
    state.seekReplay(target)
    return jsonify({"ok": True, "frame": state._replay_idx, "total": state._replay_total})


@app.route("/replay/status", methods=["GET"])
def replay_status():
    return jsonify({
        "active": state._replay_mode,
        "frame": state._replay_idx,
        "total": state._replay_total,
        "paused": state._replay_paused,
    })


if __name__ == "__main__":
    camera_setup = getCameraSetup()
    if camera_setup is None or "classification_top" not in camera_setup:
        print("ERROR: No classification_top camera found. Run camera_setup.py first.")
        sys.exit(1)

    baseline_dir = BLOB_DIR / "classification_baseline"
    color_mode = normalizeColorMode(DEFAULT_CLASSIFICATION_DIFF_CONFIG.color_mode)
    if color_mode == "lab":
        min_path = baseline_dir / "top_baseline_lab_min.png"
        max_path = baseline_dir / "top_baseline_lab_max.png"
        read_mode = cv2.IMREAD_COLOR
        load_frames = loadBaselineLabFrames
    else:
        min_path = baseline_dir / "top_baseline_min.png"
        max_path = baseline_dir / "top_baseline_max.png"
        read_mode = cv2.IMREAD_GRAYSCALE
        load_frames = loadBaselineGrayFrames
    min_img = cv2.imread(str(min_path), read_mode)
    max_img = cv2.imread(str(max_path), read_mode)
    if min_img is None or max_img is None:
        print(f"ERROR: no {color_mode} baseline images. run calibrate_classification_baseline.py first.")
        sys.exit(1)

    calibration_frames = load_frames(baseline_dir, "top")
    print(f"loaded {len(calibration_frames)} calibration frames ({color_mode})")

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

    state = AppState(capture, irl.carousel_stepper, irl_config, min_img, max_img, mask, calibration_frames, color_mode)

    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
