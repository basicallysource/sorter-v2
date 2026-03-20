"""
MOG2 background subtraction test for feeder channel detection.
Continuously adapts to rotating faceted rotors while detecting pieces.

Run from /software/client: uv run python scripts/mog2_diff.py
Then open http://localhost:8098 in a browser.
"""

import argparse
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
from vision.heatmap_diff import HeatmapDiff

CAROUSEL_SETTLE_AFTER_STOP_MS = 500

PORT = 8098

DEFAULT_PARAMS = {
    "history": 500,
    "var_threshold": 16.0,
    "learning_rate": 0.005,
    "blur_kernel": 5,
    "min_contour_area": 100,
    "morph_kernel": 5,
    "heat_gain": 3.0,
    "carousel_settle_ms": float(CAROUSEL_SETTLE_AFTER_STOP_MS),
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


def loadCarouselPolygon():
    saved = getChannelPolygons()
    if saved is None:
        return None
    polygon_data = saved.get("polygons", {})
    pts = polygon_data.get("carousel")
    if not pts:
        return None
    return [(float(p[0]), float(p[1])) for p in pts]


def buildPolygonMask(polygons, shape):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    if isinstance(polygons, dict):
        for pts in polygons.values():
            cv2.fillPoly(mask, [pts], 255)
    else:
        cv2.fillPoly(mask, [polygons], 255)
    if np.count_nonzero(mask) == 0:
        return None
    return mask


# --- Motor control ---

class MotorRunner:
    def __init__(self, irl, feeder_config):
        self.irl = irl
        self._second_running = False
        self._third_running = False
        self._lock = threading.Lock()
        self._second_steps = feeder_config.second_rotor_normal.steps_per_pulse
        self._second_speed = feeder_config.second_rotor_normal.microsteps_per_second
        self._second_delay = feeder_config.second_rotor_normal.delay_between_pulse_ms / 1000.0
        self._third_steps = feeder_config.third_rotor_normal.steps_per_pulse
        self._third_speed = feeder_config.third_rotor_normal.microsteps_per_second
        self._third_delay = feeder_config.third_rotor_normal.delay_between_pulse_ms / 1000.0

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
                    self.irl.second_c_channel_rotor_stepper.set_speed_limits(16, self._second_speed)
                    stepper = self.irl.second_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._second_steps))
                    pulsed = True
                    time.sleep(self._second_delay)
                next_is_second = False
            else:
                if run_third:
                    self.irl.third_c_channel_rotor_stepper.set_speed_limits(16, self._third_speed)
                    stepper = self.irl.third_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._third_steps))
                    pulsed = True
                    time.sleep(self._third_delay)
                next_is_second = True

            if not pulsed:
                if next_is_second and run_second:
                    self.irl.second_c_channel_rotor_stepper.set_speed_limits(16, self._second_speed)
                    stepper = self.irl.second_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._second_steps))
                    time.sleep(self._second_delay)
                elif not next_is_second and run_third:
                    self.irl.third_c_channel_rotor_stepper.set_speed_limits(16, self._third_speed)
                    stepper = self.irl.third_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._third_steps))
                    time.sleep(self._third_delay)
                else:
                    time.sleep(0.1)

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

CHANNEL_TO_MOTOR = {
    "second_channel": "second",
    "third_channel": "third",
}


class ChannelMog2:
    def __init__(self, name, polygon, shape, params):
        self.name = name
        self.mask = buildPolygonMask(polygon, shape)
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=int(params["history"]),
            varThreshold=params["var_threshold"],
            detectShadows=False,
        )

    def rebuild(self, params):
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=int(params["history"]),
            varThreshold=params["var_threshold"],
            detectShadows=False,
        )


class AppState:
    def __init__(self, device_index, motor_runner, learn_only_rotating, carousel_stepper):
        self.cap = cv2.VideoCapture(device_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_gray = None
        self.channel_polygons = loadChannelPolygons()
        self.channel_mog2s: dict[str, ChannelMog2] = {}
        self.combined_mask = None
        self.running = True
        self.params = dict(DEFAULT_PARAMS)
        self.frame_count = 0
        self.motor_runner = motor_runner
        self.learn_only_rotating = learn_only_rotating
        self.carousel_stepper = carousel_stepper
        self.carousel_polygon = loadCarouselPolygon()
        self.carousel_heatmap = HeatmapDiff()
        self._carousel_rotating = False
        self._carousel_stopped_at: float = 0.0
        self._thread = threading.Thread(target=self._captureLoop, daemon=True)
        self._thread.start()

    def _initChannelMog2s(self, shape):
        if not self.channel_polygons:
            return
        for name, polygon in self.channel_polygons.items():
            self.channel_mog2s[name] = ChannelMog2(name, polygon, shape, self.params)
        self.combined_mask = buildPolygonMask(self.channel_polygons, shape)

    def _rebuildMog2(self):
        for ch in self.channel_mog2s.values():
            ch.rebuild(self.params)

    def _isChannelRotating(self, channel_name):
        motor_key = CHANNEL_TO_MOTOR.get(channel_name)
        if motor_key == "second":
            return self.motor_runner.second_running
        if motor_key == "third":
            return self.motor_runner.third_running
        return False

    def rotateCarousel(self):
        self.carousel_stepper.move_degrees(-90.0)
        self._carousel_rotating = True
        self._carousel_stopped_at = 0.0
        self.carousel_heatmap.clearBaseline()

    def _maybeRecaptureCarouselBaseline(self, gray):
        if not self._carousel_rotating and self._carousel_stopped_at == 0.0:
            return
        if self.carousel_heatmap.has_baseline:
            return
        if self._carousel_rotating:
            if self.carousel_stepper.stopped:
                self._carousel_rotating = False
                self._carousel_stopped_at = time.time()
                print("Carousel stepper stopped, waiting for settle...")
            return
        elapsed_ms = (time.time() - self._carousel_stopped_at) * 1000
        if elapsed_ms < self.params["carousel_settle_ms"]:
            return
        if self.carousel_polygon:
            self.carousel_heatmap.captureBaseline(self.carousel_polygon, gray.shape)
            print(f"Carousel baseline captured after {elapsed_ms:.0f}ms settle")

    def _captureLoop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self.carousel_heatmap.pushFrame(gray)
            with self.lock:
                self.latest_frame = frame
                self.latest_gray = gray

    def getAnnotatedFrame(self):
        with self.lock:
            frame = self.latest_frame
            gray = self.latest_gray
        if frame is None or gray is None:
            return None

        if not self.channel_mog2s and self.channel_polygons:
            self._initChannelMog2s(gray.shape)

        annotated = frame.copy()

        if self.combined_mask is None:
            cv2.putText(annotated, "NO CHANNELS - run polygon_editor.py first", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            return annotated

        p = self.params
        blur_k = int(p["blur_kernel"]) | 1
        morph_k = int(p["morph_kernel"]) | 1
        learning_rate = p["learning_rate"]
        heat_gain = p["heat_gain"]
        min_area = int(p["min_contour_area"])

        blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)

        fg_mask = np.zeros(gray.shape[:2], dtype=np.uint8)
        for name, ch in self.channel_mog2s.items():
            if ch.mask is None:
                continue
            if self.learn_only_rotating and not self._isChannelRotating(name):
                ch_lr = 0.0
            else:
                ch_lr = learning_rate
            ch_fg_raw = ch.mog2.apply(blurred, learningRate=ch_lr)
            ch_fg = cv2.bitwise_and(ch_fg_raw, ch.mask)
            fg_mask = cv2.bitwise_or(fg_mask, ch_fg)

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

        mask_bool = self.combined_mask > 0
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
                rotating = self._isChannelRotating(name)
                frozen = self.learn_only_rotating and not rotating
                color = (255, 200, 0) if "second" in name else (0, 200, 255)
                if frozen:
                    color = (80, 80, 80)
                cv2.polylines(out, [pts], True, color, 2)
                if frozen:
                    cx = int(np.mean(pts[:, 0]))
                    cy = int(np.mean(pts[:, 1]))
                    cv2.putText(out, "FROZEN", (cx - 40, cy),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 2)

        for x1, y1, x2, y2 in bboxes:
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        triggered = len(bboxes) > 0
        color = (0, 0, 255) if triggered else (0, 255, 0)
        label = f"DETECTED: {len(bboxes)}" if triggered else "clear"
        cv2.putText(out, label, (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        cv2.putText(out, f"fg_px: {hot_count}", (30, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

        mr = self.motor_runner
        ch2_label = "CH2: ON" if mr.second_running else "CH2: off"
        ch3_label = "CH3: ON" if mr.third_running else "CH3: off"
        ch2_color = (0, 200, 255) if mr.second_running else (100, 100, 100)
        ch3_color = (0, 200, 255) if mr.third_running else (100, 100, 100)
        cv2.putText(out, ch2_label, (30, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, ch2_color, 2)
        cv2.putText(out, ch3_label, (30, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, ch3_color, 2)

        if self.learn_only_rotating:
            cv2.putText(out, "LEARN-ONLY-ROTATING", (30, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 0), 2)

        self._maybeRecaptureCarouselBaseline(gray)
        if self.carousel_heatmap.has_baseline:
            out = self.carousel_heatmap.annotateFrame(out, label="carousel", text_y=210)
        elif self._carousel_rotating:
            cv2.putText(out, "carousel rotating...", (30, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
        elif self._carousel_stopped_at > 0:
            remaining_ms = self.params["carousel_settle_ms"] - (time.time() - self._carousel_stopped_at) * 1000
            if remaining_ms > 0:
                cv2.putText(out, f"carousel settling... {remaining_ms:.0f}ms", (30, 210),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
        elif self.carousel_polygon:
            cv2.putText(out, "carousel: no baseline (press Rotate)", (30, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 2)

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
        <button onclick="rotateCarousel()">Rotate Carousel</button>
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
            { key: 'carousel_settle_ms', label: 'Carousel Settle (ms)',
              desc: 'Time to wait after stepper stops before snapping baseline',
              min: 0, max: 5000, step: 50 },
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

        async function rotateCarousel() {
            const res = await fetch('/carousel/rotate', { method: 'POST' });
            const data = await res.json();
            document.getElementById('status').textContent = data.ok
                ? 'Carousel rotating, settling ' + data.settle_ms + 'ms...'
                : 'Carousel rotate failed';
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

@app.route("/carousel/rotate", methods=["POST"])
def rotate_carousel():
    if not state.carousel_polygon:
        return jsonify({"ok": False, "error": "no carousel polygon"}), 400
    state.rotateCarousel()
    return jsonify({"ok": True, "settle_ms": state.params["carousel_settle_ms"]})

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
    parser = argparse.ArgumentParser(description="MOG2 background subtraction test")
    parser.add_argument(
        "--learn-always", action="store_true",
        help="update MOG2 background model even when motors are stopped",
    )
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + remaining

    if loadChannelPolygons() is None:
        print("ERROR: No channel polygons saved. Run client/scripts/polygon_editor.py first.")
        sys.exit(1)

    camera_setup = getCameraSetup()
    if camera_setup is None or "feeder" not in camera_setup:
        print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
        sys.exit(1)

    device_index = camera_setup["feeder"]
    print(f"Using feeder camera device index: {device_index}")
    learn_only_rotating = not args.learn_always
    if learn_only_rotating:
        print("Mode: learn-only-rotating (frozen channels won't update background)")

    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    motor_runner = MotorRunner(irl, irl_config.feeder_config)
    state = AppState(device_index, motor_runner, learn_only_rotating, irl.carousel_stepper)
    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
