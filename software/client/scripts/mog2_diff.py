"""
MOG2 background subtraction test for feeder channel detection.
Continuously adapts to rotating faceted rotors while detecting pieces.

Run: /opt/homebrew/opt/python@3.11/bin/python3.11 client/scripts/mog2_diff.py
Then open http://localhost:8098 in a browser.
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

from blob_manager import getCameraSetup, getChannelPolygons
from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface

EXPAND_RADIUS_CHANNELS_PX = 0

# motor constants
STEPS_PER_PULSE = 800
STEP_DELAY_US = 400
PULSE_INTERVAL_S = 0.5

PORT = 8098

DEFAULT_PARAMS = {
    "history": 500,           # MOG2 history length (frames)
    "var_threshold": 16.0,    # MOG2 variance threshold (lower = more sensitive)
    "learning_rate": 0.005,   # how fast background adapts (0=frozen, 1=instant)
    "blur_kernel": 5,         # gaussian blur before MOG2
    "min_contour_area": 100,  # minimum contour area for detection
    "morph_kernel": 5,        # morphological open/close kernel size
    "heat_gain": 3.0,         # visual amplification for overlay
}


# --- Channel geometry ---

def loadChannelPolygons():
    saved = getChannelPolygons()
    if saved is None:
        return None
    polygon_data = saved.get("polygons", {})
    result = {}
    for key in ("second_channel", "third_channel"):
        pts = polygon_data.get(key)
        if pts:
            result[key] = np.array(pts, dtype=np.int32)
    return result if result else None


def buildPolygonMask(polygons, shape):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for pts in polygons.values():
        cv2.fillPoly(mask, [pts], 255)
    if EXPAND_RADIUS_CHANNELS_PX != 0:
        k = abs(EXPAND_RADIUS_CHANNELS_PX) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        if EXPAND_RADIUS_CHANNELS_PX > 0:
            mask = cv2.dilate(mask, kernel)
        else:
            mask = cv2.erode(mask, kernel)
    if np.count_nonzero(mask) == 0:
        return None
    return mask


# --- Motor control ---

class MotorRunner:
    def __init__(self, irl):
        self.irl = irl
        self._second_running = False
        self._third_running = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        next_is_second = True
        while True:
            with self._lock:
                run_second = self._second_running
                run_third = self._third_running
            pulsed = False
            if next_is_second:
                if run_second:
                    self.irl.second_c_channel_rotor_stepper.moveSteps(
                        -STEPS_PER_PULSE, STEP_DELAY_US,
                    )
                    pulsed = True
                next_is_second = False
            else:
                if run_third:
                    self.irl.third_c_channel_rotor_stepper.moveSteps(
                        -STEPS_PER_PULSE, STEP_DELAY_US,
                    )
                    pulsed = True
                next_is_second = True
            if not pulsed:
                # if the scheduled channel wasn't running, try the other one
                if next_is_second and run_second:
                    self.irl.second_c_channel_rotor_stepper.moveSteps(
                        -STEPS_PER_PULSE, STEP_DELAY_US,
                    )
                elif not next_is_second and run_third:
                    self.irl.third_c_channel_rotor_stepper.moveSteps(
                        -STEPS_PER_PULSE, STEP_DELAY_US,
                    )
            time.sleep(PULSE_INTERVAL_S)

    def toggleSecond(self):
        with self._lock:
            self._second_running = not self._second_running
            return self._second_running

    def toggleThird(self):
        with self._lock:
            self._third_running = not self._third_running
            return self._third_running

    @property
    def second_running(self):
        with self._lock:
            return self._second_running

    @property
    def third_running(self):
        with self._lock:
            return self._third_running


# --- Main app state ---

class AppState:
    def __init__(self, device_index, motor_runner):
        self.cap = cv2.VideoCapture(device_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_gray = None
        self.channel_polygons = loadChannelPolygons()
        self.channel_mask = None
        self.mog2 = None
        self.running = True
        self.params = dict(DEFAULT_PARAMS)
        self.frame_count = 0
        self.motor_runner = motor_runner
        self._thread = threading.Thread(target=self._captureLoop, daemon=True)
        self._thread.start()

    def _rebuildMog2(self):
        p = self.params
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=int(p["history"]),
            varThreshold=p["var_threshold"],
            detectShadows=False,
        )

    def _captureLoop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            with self.lock:
                self.latest_frame = frame
                self.latest_gray = gray

    def getAnnotatedFrame(self):
        with self.lock:
            frame = self.latest_frame
            gray = self.latest_gray
        if frame is None or gray is None:
            return None

        if self.channel_mask is None and self.channel_polygons is not None:
            self.channel_mask = buildPolygonMask(self.channel_polygons, gray.shape)

        annotated = frame.copy()

        if self.channel_mask is None:
            cv2.putText(annotated, "NO CHANNELS - run polygon_editor.py first", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            return annotated

        if self.mog2 is None:
            self._rebuildMog2()

        p = self.params
        blur_k = int(p["blur_kernel"]) | 1
        morph_k = int(p["morph_kernel"]) | 1
        learning_rate = p["learning_rate"]
        heat_gain = p["heat_gain"]
        min_area = int(p["min_contour_area"])

        blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)
        fg_mask_raw = self.mog2.apply(blurred, learningRate=learning_rate)
        fg_mask = cv2.bitwise_and(fg_mask_raw, self.channel_mask)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_k, morph_k))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        bboxes = []
        for contour in contours:
            if cv2.contourArea(contour) < min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            bboxes.append((x, y, x + w, y + h))

        mask_bool = self.channel_mask > 0
        fg_bool = fg_mask > 0
        hot_count = int(np.count_nonzero(fg_bool))

        out = annotated.copy()
        out[mask_bool] = (annotated[mask_bool] * 0.5).astype(np.uint8)

        display = np.zeros_like(gray)
        display[fg_bool & mask_bool] = np.clip(
            fg_mask[fg_bool & mask_bool].astype(np.float32) * heat_gain, 0, 255
        ).astype(np.uint8)
        heatmap = cv2.applyColorMap(display, cv2.COLORMAP_JET)
        show_heat = fg_bool & mask_bool
        out[show_heat] = (
            annotated[show_heat].astype(np.float32) * 0.2
            + heatmap[show_heat].astype(np.float32) * 0.8
        ).clip(0, 255).astype(np.uint8)

        if self.channel_polygons:
            for name, pts in self.channel_polygons.items():
                color = (255, 200, 0) if "second" in name else (0, 200, 255)
                cv2.polylines(out, [pts], True, color, 2)

        for x1, y1, x2, y2 in bboxes:
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        triggered = len(bboxes) > 0
        color = (0, 0, 255) if triggered else (0, 255, 0)
        label = f"DETECTED: {len(bboxes)}" if triggered else "clear"
        cv2.putText(out, label, (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        cv2.putText(out, f"fg_px: {hot_count}", (30, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

        # motor status
        mr = self.motor_runner
        ch2_label = "CH2: ON" if mr.second_running else "CH2: off"
        ch3_label = "CH3: ON" if mr.third_running else "CH3: off"
        ch2_color = (0, 200, 255) if mr.second_running else (100, 100, 100)
        ch3_color = (0, 200, 255) if mr.third_running else (100, 100, 100)
        cv2.putText(out, ch2_label, (30, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, ch2_color, 2)
        cv2.putText(out, ch3_label, (30, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, ch3_color, 2)

        self.frame_count += 1
        return out


# --- Flask app ---

app = Flask(__name__)
state: AppState = None  # type: ignore[assignment]

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MOG2 Background Subtraction - Feeder Channels</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #111; color: #eee; font-family: monospace;
               display: flex; flex-direction: column; align-items: center; }
        h1 { margin: 12px 0 8px; font-size: 18px; }
        .top-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; flex-wrap: wrap; }
        button { padding: 8px 20px; font-size: 14px; cursor: pointer;
                 background: #2a6; color: #fff; border: none; border-radius: 4px; }
        button:hover { background: #3b7; }
        button.motor { background: #555; }
        button.motor.active { background: #c62; }
        button.motor:hover { background: #777; }
        button.motor.active:hover { background: #e73; }
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
    <h1>MOG2 Background Subtraction - Feeder Channels</h1>
    <div class="top-row">
        <button onclick="resetMog2()">Reset MOG2</button>
        <button id="btn_ch2" class="motor" onclick="toggleMotor('second')">Channel 2 Motor</button>
        <button id="btn_ch3" class="motor" onclick="toggleMotor('third')">Channel 3 Motor</button>
        <span id="status">MOG2 learning...</span>
    </div>
    <div class="controls" id="controls"></div>
    <img id="feed" src="/feed" />
    <script>
        const PARAMS = [
            { key: 'history', label: 'History',
              desc: 'Number of frames MOG2 uses to model background (higher = slower adaptation)',
              min: 50, max: 2000, step: 50 },
            { key: 'var_threshold', label: 'Variance Threshold',
              desc: 'How many sigma from a mode to be foreground (lower = more sensitive)',
              min: 4, max: 64, step: 1 },
            { key: 'learning_rate', label: 'Learning Rate',
              desc: 'How fast background adapts (0 = frozen, 0.01 = slow, 0.1 = fast)',
              min: 0, max: 0.1, step: 0.001 },
            { key: 'blur_kernel', label: 'Blur Kernel',
              desc: 'Gaussian blur size before MOG2 (smooths sensor noise)',
              min: 1, max: 21, step: 2 },
            { key: 'min_contour_area', label: 'Min Contour Area',
              desc: 'Minimum foreground blob area (px^2) to count as detection',
              min: 10, max: 1000, step: 10 },
            { key: 'morph_kernel', label: 'Morph Kernel',
              desc: 'Morphological open/close kernel size (cleans up noise blobs)',
              min: 1, max: 15, step: 2 },
            { key: 'heat_gain', label: 'Heat Gain',
              desc: 'Visual amplification for heatmap overlay',
              min: 1, max: 10, step: 0.5 },
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

        async function resetMog2() {
            const res = await fetch('/reset', { method: 'POST' });
            const data = await res.json();
            document.getElementById('status').textContent = data.ok
                ? 'MOG2 reset at ' + new Date().toLocaleTimeString()
                : 'Reset failed';
        }

        async function toggleMotor(channel) {
            const res = await fetch('/motor/' + channel, { method: 'POST' });
            const data = await res.json();
            const btnId = channel === 'second' ? 'btn_ch2' : 'btn_ch3';
            const btn = document.getElementById(btnId);
            if (data.running) {
                btn.classList.add('active');
                btn.textContent = (channel === 'second' ? 'Channel 2' : 'Channel 3') + ' Motor (ON)';
            } else {
                btn.classList.remove('active');
                btn.textContent = (channel === 'second' ? 'Channel 2' : 'Channel 3') + ' Motor';
            }
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

@app.route("/reset", methods=["POST"])
def reset_mog2():
    state._rebuildMog2()
    return jsonify({"ok": True})

@app.route("/motor/<channel>", methods=["POST"])
def toggle_motor(channel):
    if channel == "second":
        running = state.motor_runner.toggleSecond()
    elif channel == "third":
        running = state.motor_runner.toggleThird()
    else:
        return jsonify({"error": "unknown channel"}), 400
    return jsonify({"running": running, "channel": channel})

@app.route("/params", methods=["GET"])
def get_params():
    return jsonify(state.params)

@app.route("/params", methods=["POST"])
def set_params():
    updates = request.get_json()
    rebuild = False
    for k, v in updates.items():
        if k in state.params:
            state.params[k] = float(v)
            if k in ("history", "var_threshold"):
                rebuild = True
    if rebuild:
        state._rebuildMog2()
    return jsonify(state.params)

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


if __name__ == "__main__":
    if loadChannelPolygons() is None:
        print("ERROR: No channel polygons saved. Run client/scripts/polygon_editor.py first.")
        sys.exit(1)

    camera_setup = getCameraSetup()
    if camera_setup is None or "feeder" not in camera_setup:
        print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
        sys.exit(1)

    device_index = camera_setup["feeder"]
    print(f"Using feeder camera device index: {device_index}")

    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)

    for servo in irl.servos:
        servo.open()

    motor_runner = MotorRunner(irl)
    state = AppState(device_index, motor_runner)
    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
