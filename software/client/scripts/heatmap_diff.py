"""
Heatmap diff tool for feeder platform detection.
Shows a live diff between a baseline image and the current feed,
masked to the feeding platform region detected via ArUco tags.

Run: /opt/homebrew/opt/python@3.11/bin/python3.11 client/scripts/heatmap_diff.py
Then open http://localhost:8099 in a browser.
"""

import sys
import time
import threading
from collections import deque
from pathlib import Path

import cv2
import cv2.aruco as aruco
import numpy as np
from flask import Flask, Response, render_template_string, jsonify, request

sys.path.insert(0, str(Path(__file__).parent.parent))
from blob_manager import getCameraSetup

# --- ArUco config (mirrors irl/config.py and aruco_tracker.py) ---

ARUCO_DICT = aruco.DICT_4X4_50

ARUCO_DETECTION_PARAMS = {
    "minMarkerPerimeterRate": 0.003,
    "perspectiveRemovePixelPerCell": 4,
    "perspectiveRemoveIgnoredMarginPerCell": 0.3,
    "adaptiveThreshWinSizeMin": 3,
    "adaptiveThreshWinSizeMax": 53,
    "adaptiveThreshWinSizeStep": 4,
    "errorCorrectionRate": 1.0,
    "polygonalApproxAccuracyRate": 0.05,
    "minDistanceToBorder": 3,
    "maxErroneousBitsInBorderRate": 0.35,
    "cornerRefinementMethod": 0,
    "cornerRefinementWinSize": 5,
}

CAROUSEL_PLATFORMS = [
    (4, 2, 18, 9),
    (1, 32, 35, 8),
    (6, 16, 11, 0),
    (12, 22, 28, 5),
]

REFERENCE_TAG_ID = 14  # third_c_channel_radius1_id
PLATFORM_DISTANCE_THRESHOLD_PX = 200
PLATFORM_PERIMETER_EXPANSION_PX = 30
PLATFORM_PERIMETER_CONTRACTION_PX = 25
PLATFORM_MAX_AREA_SQ_PX = 70000
PLATFORM_MIN_CORNER_ANGLE_DEG = 70

PORT = 8099

# --- Default detection params ---

DEFAULT_PARAMS = {
    "pixel_thresh": 8,       # per-pixel diff must exceed this to count as "hot"
    "blur_kernel": 5,        # gaussian blur kernel size (odd)
    "heat_gain": 12.0,       # visual amplification for heatmap display
    "min_hot_pixels": 50,    # need at least this many hot pixels to trigger
    "trigger_score": 2.0,    # score threshold for "piece detected"
    "baseline_frames": 10,   # number of frames to average for baseline
    "current_frames": 10,    # number of recent frames to average before diffing
    "capture_interval_ms": 50,  # ms between ring buffer captures (spread across flicker cycle)
}


# --- ArUco detection ---

def mkArucoDetector():
    dictionary = aruco.getPredefinedDictionary(ARUCO_DICT)
    params = aruco.DetectorParameters()
    for k, v in ARUCO_DETECTION_PARAMS.items():
        setattr(params, k, v)
    return aruco.ArucoDetector(dictionary, params)


def detectArucoTags(gray, detector):
    corners, ids, _ = detector.detectMarkers(gray)
    tags = {}
    if ids is not None:
        for i, tag_id in enumerate(ids.flatten()):
            tag_corners = corners[i][0]
            cx = float(np.mean(tag_corners[:, 0]))
            cy = float(np.mean(tag_corners[:, 1]))
            tags[int(tag_id)] = (cx, cy)
    return tags


# --- Platform geometry (mirrors vision_manager.py) ---

def getCarouselPlatforms(aruco_tags):
    platforms = []
    for corner_ids in CAROUSEL_PLATFORMS:
        detected = {}
        for idx, cid in enumerate(corner_ids):
            if cid in aruco_tags:
                detected[idx] = aruco_tags[cid]
        if len(detected) < 3:
            continue
        corners = list(detected.values())
        if len(detected) == 3:
            p0, p1, p2 = [np.array(c) for c in corners]
            candidates = [p0 + p1 - p2, p0 + p2 - p1, p1 + p2 - p0]
            best, best_score = candidates[0], float("inf")
            for cand in candidates:
                quad = [p0, p1, p2, cand]
                dists = [np.linalg.norm(quad[j] - quad[k])
                         for j in range(4) for k in range(j+1, 4)]
                score = np.std(dists)
                if score < best_score:
                    best_score = score
                    best = cand
            corners.append(tuple(best))
        # order by angle from centroid
        corners_arr = np.array(corners)
        centroid = np.mean(corners_arr, axis=0)
        angles = [np.arctan2(c[1] - centroid[1], c[0] - centroid[0]) for c in corners]
        corners = [c for _, c in sorted(zip(angles, corners))]
        platforms.append(corners)
    return platforms


def expandPerimeter(corners, expansion_px, contraction_px=0.0):
    corners_arr = np.array(corners)
    center = np.mean(corners_arr, axis=0)
    if len(corners_arr) != 4:
        result = []
        for corner in corners_arr:
            d = corner - center
            dist = np.linalg.norm(d)
            if dist > 0:
                result.append(tuple(corner + (d / dist) * expansion_px))
            else:
                result.append(tuple(corner))
        return result
    edge_0 = corners_arr[1] - corners_arr[0]
    edge_1 = corners_arr[2] - corners_arr[1]
    edge_2 = corners_arr[3] - corners_arr[2]
    edge_3 = corners_arr[0] - corners_arr[3]
    dim_0 = (np.linalg.norm(edge_0) + np.linalg.norm(edge_2)) / 2.0
    dim_1 = (np.linalg.norm(edge_1) + np.linalg.norm(edge_3)) / 2.0
    if dim_0 <= dim_1:
        short_axis = edge_0
        long_axis = edge_1
    else:
        short_axis = edge_1
        long_axis = edge_0
    short_norm = np.linalg.norm(short_axis)
    long_norm = np.linalg.norm(long_axis)
    if short_norm == 0:
        return [tuple(c) for c in corners_arr]
    short_axis = short_axis / short_norm
    long_axis = long_axis / long_norm if long_norm > 0 else long_axis
    result = []
    for corner in corners_arr:
        offset = corner - center
        short_proj = float(np.dot(offset, short_axis))
        long_proj = float(np.dot(offset, long_axis))
        new_corner = corner.copy()
        if short_proj > 0:
            new_corner = new_corner + short_axis * expansion_px
        elif short_proj < 0:
            new_corner = new_corner - short_axis * expansion_px
        if contraction_px > 0:
            if long_proj > 0:
                new_corner = new_corner - long_axis * contraction_px
            elif long_proj < 0:
                new_corner = new_corner + long_axis * contraction_px
        result.append(tuple(new_corner))
    return result


def findFeedingPlatform(aruco_tags):
    platforms = getCarouselPlatforms(aruco_tags)
    if not platforms:
        return None
    if REFERENCE_TAG_ID not in aruco_tags:
        return None
    ref_pos = np.array(aruco_tags[REFERENCE_TAG_ID])
    for corners in platforms:
        if len(corners) < 3:
            continue
        cx = np.mean([c[0] for c in corners])
        cy = np.mean([c[1] for c in corners])
        dist = np.linalg.norm(np.array([cx, cy]) - ref_pos)
        if dist > PLATFORM_DISTANCE_THRESHOLD_PX:
            continue
        expanded = expandPerimeter(corners, PLATFORM_PERIMETER_EXPANSION_PX, PLATFORM_PERIMETER_CONTRACTION_PX)
        # validate area
        ea = np.array(expanded)
        x, y = ea[:, 0], ea[:, 1]
        area = 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
        if area > PLATFORM_MAX_AREA_SQ_PX:
            continue
        # validate corner angles
        n = len(ea)
        angles_ok = True
        for i in range(n):
            prev_pt = ea[(i - 1) % n]
            curr = ea[i]
            next_pt = ea[(i + 1) % n]
            v1, v2 = prev_pt - curr, next_pt - curr
            cos_a = np.clip(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)), -1, 1)
            if np.degrees(np.arccos(cos_a)) < PLATFORM_MIN_CORNER_ANGLE_DEG:
                angles_ok = False
                break
        if not angles_ok:
            continue
        return expanded
    return None


def makePlatformMask(corners, shape):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    pts = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask


# --- Perspective warp helpers ---
# We warp the platform quad to a fixed-size canonical rectangle so that
# ArUco jitter only changes the warp slightly rather than shifting which
# pixels map to which baseline pixel.

CANONICAL_W = 200
CANONICAL_H = 150
CANONICAL_DST = np.array([
    [0, 0],
    [CANONICAL_W - 1, 0],
    [CANONICAL_W - 1, CANONICAL_H - 1],
    [0, CANONICAL_H - 1],
], dtype=np.float32)


def cornersToSrc(corners):
    return np.array(corners, dtype=np.float32)


def warpToCanonical(gray, corners):
    src = cornersToSrc(corners)
    M = cv2.getPerspectiveTransform(src, CANONICAL_DST)
    return cv2.warpPerspective(gray, M, (CANONICAL_W, CANONICAL_H)), M


def warpFromCanonical(canonical_img, corners, out_shape):
    src = cornersToSrc(corners)
    M = cv2.getPerspectiveTransform(src, CANONICAL_DST)
    M_inv = cv2.getPerspectiveTransform(CANONICAL_DST, src)
    return cv2.warpPerspective(canonical_img, M_inv, (out_shape[1], out_shape[0]))


# --- Main app state ---

class AppState:
    def __init__(self, device_index):
        self.cap = cv2.VideoCapture(device_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.detector = mkArucoDetector()
        self.lock = threading.Lock()
        self.baseline_canonical = None
        self.platform_corners = None
        self.platform_mask = None
        self.latest_frame = None
        self._gray_ring = deque(maxlen=30)  # ring buffer of recent gray frames
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

    def updatePlatform(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        tags = detectArucoTags(gray, self.detector)
        corners = findFeedingPlatform(tags)
        if corners is not None:
            self.platform_corners = corners
            self.platform_mask = makePlatformMask(corners, frame.shape)

    def captureBaseline(self):
        with self.lock:
            frame = self.latest_frame
        if frame is None:
            return False
        self.updatePlatform(frame)
        if self.platform_corners is None:
            return False
        n = int(self.params["baseline_frames"])
        avg = self._averageGrays(n)
        if avg is None:
            return False
        self.baseline_canonical, _ = warpToCanonical(avg, self.platform_corners)
        return True

    def getHeatmapFrame(self):
        with self.lock:
            frame = self.latest_frame
        if frame is None:
            return None

        self.updatePlatform(frame)
        annotated = frame.copy()

        if self.platform_corners is not None:
            pts = np.array([[int(x), int(y)] for x, y in self.platform_corners], dtype=np.int32)
            cv2.polylines(annotated, [pts], True, (255, 255, 0), 2)

        if self.baseline_canonical is None or self.platform_corners is None or self.platform_mask is None:
            cv2.putText(annotated, "NO BASELINE - press 'Capture Baseline'", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            return annotated

        p = self.params
        pixel_thresh = p["pixel_thresh"]
        blur_k = int(p["blur_kernel"]) | 1
        heat_gain = p["heat_gain"]
        min_hot_px = int(p["min_hot_pixels"])
        trigger_score = p["trigger_score"]

        # average recent frames to reduce rolling shutter flicker bands
        n_current = int(p.get("current_frames", 3))
        avg_gray = self._averageGrays(n_current)
        if avg_gray is None:
            return annotated
        current_canonical, _ = warpToCanonical(avg_gray, self.platform_corners)

        # diff in canonical space — immune to ArUco jitter
        diff_canonical = cv2.absdiff(current_canonical, self.baseline_canonical)
        diff_canonical = cv2.GaussianBlur(diff_canonical, (blur_k, blur_k), 0)

        # hot pixels in canonical space
        hot_canonical = diff_canonical > pixel_thresh
        hot_pixel_count = int(np.count_nonzero(hot_canonical))

        if hot_pixel_count > 0:
            hot_mean = float(np.mean(diff_canonical[hot_canonical]))
        else:
            hot_mean = 0.0

        score = hot_mean if hot_pixel_count >= min_hot_px else 0.0
        triggered = score >= trigger_score

        # --- visualize: warp diff back to camera space for overlay ---
        display_canonical = np.zeros_like(diff_canonical)
        display_canonical[hot_canonical] = np.clip(
            diff_canonical[hot_canonical].astype(np.float32) * heat_gain, 0, 255
        ).astype(np.uint8)

        # warp back to camera frame coordinates
        display_camera = warpFromCanonical(display_canonical, self.platform_corners, frame.shape)

        heatmap = cv2.applyColorMap(display_camera, cv2.COLORMAP_JET)

        mask_bool = self.platform_mask > 0
        hot_camera = display_camera > 0

        blended = annotated.copy()
        blended[mask_bool] = (annotated[mask_bool] * 0.5).astype(np.uint8)
        show_heat = mask_bool & hot_camera
        blended[show_heat] = (
            annotated[show_heat].astype(np.float32) * 0.2
            + heatmap[show_heat].astype(np.float32) * 0.8
        ).clip(0, 255).astype(np.uint8)

        # platform outline
        pts = np.array([[int(x), int(y)] for x, y in self.platform_corners], dtype=np.int32)
        cv2.polylines(blended, [pts], True, (255, 255, 0), 2)

        # HUD
        score_color = (0, 0, 255) if triggered else (0, 255, 0)
        cv2.putText(blended, f"score: {score:.1f}", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, score_color, 2)
        cv2.putText(blended, f"hot_px: {hot_pixel_count}", (30, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        label = "PIECE DETECTED" if triggered else "clear"
        cv2.putText(blended, label, (30, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, score_color, 2)

        return blended


# --- Flask app ---

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
              desc: 'Per-pixel diff must exceed this to count as hot (filters glass reflections)',
              min: 0, max: 50, step: 1 },
            { key: 'blur_kernel', label: 'Blur Kernel',
              desc: 'Gaussian blur size — smooths noise before thresholding',
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
              desc: 'Number of frames averaged for baseline (reduces flicker bands)',
              min: 1, max: 30, step: 1 },
            { key: 'current_frames', label: 'Current Frames',
              desc: 'Number of recent frames averaged before diffing (reduces flicker bands)',
              min: 1, max: 30, step: 1 },
            { key: 'capture_interval_ms', label: 'Capture Interval (ms)',
              desc: 'Time between ring buffer samples — spread across flicker cycle for better averaging',
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
                : 'Failed - no platform detected. Make sure ArUco tags are visible.';
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

    device_index = camera_setup["feeder"]
    print(f"Using feeder camera device index: {device_index}")

    state = AppState(device_index)
    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
