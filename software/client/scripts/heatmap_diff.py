"""
Heatmap diff tool for feeder platform detection.
Shows a live diff between a baseline image and the current feed,
masked to the carousel polygon loaded from blob_manager.

Run: /opt/homebrew/opt/python@3.11/bin/python3.11 client/scripts/heatmap_diff.py
Then open http://localhost:8099 in a browser.
"""

import sys
import time
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, render_template_string, jsonify, request

sys.path.insert(0, str(Path(__file__).parent.parent))
from blob_manager import getCameraSetup, getChannelPolygons

PORT = 8099

DEFAULT_PARAMS = {
    "pixel_thresh": 8,
    "blur_kernel": 5,
    "heat_gain": 12.0,
    "min_hot_pixels": 50,
    "trigger_score": 2.0,
    "baseline_frames": 10,
    "current_frames": 10,
    "capture_interval_ms": 50,
}


def makePlatformMask(corners, shape):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    pts = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask


class AppState:
    def __init__(self, device_index, carousel_polygon):
        self.cap = cv2.VideoCapture(device_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.lock = threading.Lock()
        self.baseline_gray = None
        self.platform_corners = carousel_polygon
        self.platform_mask = None
        self.latest_frame = None
        self._gray_ring = deque(maxlen=30)
        self.running = True
        self.params = dict(DEFAULT_PARAMS)
        self._thread = threading.Thread(target=self._captureLoop, daemon=True)
        self._thread.start()

    def _captureLoop(self):
        last_ring_time = 0.0
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            now = time.time()
            with self.lock:
                self.latest_frame = frame
            # build mask on first frame if we have polygon
            if self.platform_mask is None and self.platform_corners is not None:
                self.platform_mask = makePlatformMask(self.platform_corners, frame.shape)
            interval_s = self.params["capture_interval_ms"] / 1000.0
            if now - last_ring_time >= interval_s:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                with self.lock:
                    self._gray_ring.append(gray)
                last_ring_time = now

    def _averageGrays(self, count):
        with self.lock:
            n = min(count, len(self._gray_ring))
            if n == 0:
                return None
            frames = list(self._gray_ring)[-n:]
        acc = frames[0].astype(np.float32)
        for f in frames[1:]:
            acc += f.astype(np.float32)
        return (acc / len(frames)).astype(np.uint8)

    def captureBaseline(self):
        if self.platform_corners is None:
            return False
        n = int(self.params["baseline_frames"])
        avg = self._averageGrays(n)
        if avg is None:
            return False
        self.baseline_gray = avg
        return True

    def getHeatmapFrame(self):
        with self.lock:
            frame = self.latest_frame
        if frame is None:
            return None

        annotated = frame.copy()

        if self.platform_corners is not None:
            pts = np.array([[int(x), int(y)] for x, y in self.platform_corners], dtype=np.int32)
            cv2.polylines(annotated, [pts], True, (255, 255, 0), 2)

        if self.baseline_gray is None or self.platform_corners is None or self.platform_mask is None:
            cv2.putText(annotated, "NO BASELINE - press 'Capture Baseline'", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            return annotated

        p = self.params
        pixel_thresh = p["pixel_thresh"]
        blur_k = int(p["blur_kernel"]) | 1
        heat_gain = p["heat_gain"]
        min_hot_px = int(p["min_hot_pixels"])
        trigger_score = p["trigger_score"]

        n_current = int(p.get("current_frames", 3))
        avg_gray = self._averageGrays(n_current)
        if avg_gray is None:
            return annotated

        diff = cv2.absdiff(avg_gray, self.baseline_gray)
        diff = cv2.GaussianBlur(diff, (blur_k, blur_k), 0)

        # mask to platform region
        diff[self.platform_mask == 0] = 0

        hot = diff > pixel_thresh
        hot_pixel_count = int(np.count_nonzero(hot))

        if hot_pixel_count > 0:
            hot_mean = float(np.mean(diff[hot]))
        else:
            hot_mean = 0.0

        score = hot_mean if hot_pixel_count >= min_hot_px else 0.0
        triggered = score >= trigger_score

        display = np.zeros_like(diff)
        display[hot] = np.clip(
            diff[hot].astype(np.float32) * heat_gain, 0, 255
        ).astype(np.uint8)

        heatmap = cv2.applyColorMap(display, cv2.COLORMAP_JET)

        mask_bool = self.platform_mask > 0
        hot_camera = display > 0

        blended = annotated.copy()
        blended[mask_bool] = (annotated[mask_bool] * 0.5).astype(np.uint8)
        show_heat = mask_bool & hot_camera
        blended[show_heat] = (
            annotated[show_heat].astype(np.float32) * 0.2
            + heatmap[show_heat].astype(np.float32) * 0.8
        ).clip(0, 255).astype(np.uint8)

        pts = np.array([[int(x), int(y)] for x, y in self.platform_corners], dtype=np.int32)
        cv2.polylines(blended, [pts], True, (255, 255, 0), 2)

        score_color = (0, 0, 255) if triggered else (0, 255, 0)
        cv2.putText(blended, f"score: {score:.1f}", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, score_color, 2)
        cv2.putText(blended, f"hot_px: {hot_pixel_count}", (30, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        label = "PIECE DETECTED" if triggered else "clear"
        cv2.putText(blended, label, (30, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, score_color, 2)

        return blended


app = Flask(__name__)
state: AppState = None  # type: ignore[assignment]

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Heatmap Diff - Feeder Platform</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #111; color: #eee; font-family: monospace;
               display: flex; flex-direction: column; align-items: center; }
        h1 { margin: 12px 0 8px; font-size: 18px; }
        .top-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
        button { padding: 8px 20px; font-size: 14px; cursor: pointer;
                 background: #2a6; color: #fff; border: none; border-radius: 4px; }
        button:hover { background: #3b7; }
        #status { color: #aaa; font-size: 13px; }
        img { max-width: 95vw; max-height: 70vh; border: 1px solid #333; }
        .controls { display: flex; flex-wrap: wrap; gap: 16px; margin: 10px 0;
                     padding: 10px 16px; background: #1a1a1a; border-radius: 6px;
                     border: 1px solid #333; max-width: 95vw; }
        .param { display: flex; flex-direction: column; gap: 2px; min-width: 200px; }
        .param label { font-size: 12px; color: #999; }
        .param .row { display: flex; align-items: center; gap: 8px; }
        .param input[type=range] { flex: 1; accent-color: #2a6; }
        .param .val { font-size: 14px; min-width: 50px; text-align: right; color: #4f8; }
        .param .desc { font-size: 10px; color: #666; }
    </style>
</head>
<body>
    <h1>Feeder Platform Heatmap Diff</h1>
    <div class="top-row">
        <button onclick="captureBaseline()">Capture Baseline</button>
        <span id="status">No baseline captured yet</span>
    </div>
    <div class="controls" id="controls"></div>
    <img id="feed" src="/feed" />
    <script>
        const PARAMS = [
            { key: 'pixel_thresh', label: 'Pixel Threshold',
              desc: 'Per-pixel diff must exceed this to count as hot',
              min: 0, max: 50, step: 1 },
            { key: 'blur_kernel', label: 'Blur Kernel',
              desc: 'Gaussian blur size',
              min: 1, max: 21, step: 2 },
            { key: 'heat_gain', label: 'Heat Gain',
              desc: 'Visual amplification for heatmap display',
              min: 1, max: 50, step: 1 },
            { key: 'min_hot_pixels', label: 'Min Hot Pixels',
              desc: 'Need at least this many hot pixels to consider it a detection',
              min: 0, max: 500, step: 5 },
            { key: 'trigger_score', label: 'Trigger Score',
              desc: 'Mean hot-pixel intensity must exceed this to trigger detection',
              min: 0, max: 30, step: 0.5 },
            { key: 'baseline_frames', label: 'Baseline Frames',
              desc: 'Number of frames averaged for baseline',
              min: 1, max: 30, step: 1 },
            { key: 'current_frames', label: 'Current Frames',
              desc: 'Number of recent frames averaged before diffing',
              min: 1, max: 30, step: 1 },
            { key: 'capture_interval_ms', label: 'Capture Interval (ms)',
              desc: 'Time between ring buffer samples',
              min: 0, max: 200, step: 5 },
        ];

        let currentValues = {};

        async function loadParams() {
            const res = await fetch('/params');
            currentValues = await res.json();
            renderControls();
        }

        function renderControls() {
            const el = document.getElementById('controls');
            el.innerHTML = '';
            for (const p of PARAMS) {
                const val = currentValues[p.key] ?? 0;
                const div = document.createElement('div');
                div.className = 'param';
                div.innerHTML = `
                    <label>${p.label}</label>
                    <div class="row">
                        <input type="range" min="${p.min}" max="${p.max}" step="${p.step}"
                               value="${val}" oninput="updateParam('${p.key}', this.value, this)" />
                        <span class="val" id="val_${p.key}">${val}</span>
                    </div>
                    <span class="desc">${p.desc}</span>
                `;
                el.appendChild(div);
            }
        }

        async function updateParam(key, value, input) {
            const numVal = parseFloat(value);
            currentValues[key] = numVal;
            document.getElementById('val_' + key).textContent = numVal;
            await fetch('/params', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: numVal }),
            });
        }

        async function captureBaseline() {
            const res = await fetch('/baseline', { method: 'POST' });
            const data = await res.json();
            document.getElementById('status').textContent = data.ok
                ? 'Baseline captured at ' + new Date().toLocaleTimeString()
                : 'Failed - no carousel polygon found. Run channel_polygon_editor.py first.';
        }

        setInterval(() => {
            const img = document.getElementById('feed');
            img.src = '/feed?' + Date.now();
        }, 30000);

        loadParams();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/baseline", methods=["POST"])
def capture_baseline():
    ok = state.captureBaseline()
    return jsonify({"ok": ok})

@app.route("/params", methods=["GET"])
def get_params():
    return jsonify(state.params)

@app.route("/params", methods=["POST"])
def set_params():
    updates = request.get_json()
    for k, v in updates.items():
        if k in state.params:
            state.params[k] = float(v)
    return jsonify(state.params)

def generateFrames():
    while True:
        frame = state.getHeatmapFrame()
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


if __name__ == "__main__":
    camera_setup = getCameraSetup()
    if camera_setup is None or "feeder" not in camera_setup:
        print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
        sys.exit(1)

    # load carousel polygon from blob_manager
    saved = getChannelPolygons()
    carousel_polygon = None
    if saved:
        carousel_pts = saved.get("polygons", {}).get("carousel")
        if carousel_pts and len(carousel_pts) >= 3:
            carousel_polygon = [(float(p[0]), float(p[1])) for p in carousel_pts]

    if carousel_polygon is None:
        print("WARNING: No carousel polygon found. Run channel_polygon_editor.py first.")
        print("         Heatmap diff will not work until a polygon is drawn.")

    device_index = camera_setup["feeder"]
    print(f"Using feeder camera device index: {device_index}")

    state = AppState(device_index, carousel_polygon)
    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
