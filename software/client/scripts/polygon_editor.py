"""
Channel, carousel & classification polygon editor.
All regions are click-to-draw polygons stored in blob_manager.
Shift-click on a channel tab to place the section-0 reference point.

Run: /opt/homebrew/opt/python@3.11/bin/python3.11 client/scripts/polygon_editor.py
Then open http://localhost:8100. Left-click adds a vertex, shift-click sets section 0,
right-click removes nearest vertex.
"""

import sys
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template_string, request

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from blob_manager import (
    getCameraSetup, getChannelPolygons, setChannelPolygons,
    getClassificationPolygons, setClassificationPolygons,
)
from irl.config import mkCameraConfig
from vision.camera import CaptureThread

PORT = 8100

FEEDER_CHANNELS = ['second', 'third', 'carousel']
CLASSIFICATION_CHANNELS = ['class_top', 'class_bottom']
ALL_CHANNELS = FEEDER_CHANNELS + CLASSIFICATION_CHANNELS

app = Flask(__name__)
captures: dict[str, CaptureThread] = {}

HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Polygon Editor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #111; color: #eee; font-family: monospace;
           display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
    .topbar { display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: #1a1a1a; border-bottom: 1px solid #333; flex-shrink: 0; flex-wrap: wrap; }
    .sep { width: 1px; height: 24px; background: #444; }
    .tab { padding: 5px 14px; cursor: pointer; border-radius: 4px; background: #2a2a2a;
           border: 2px solid transparent; color: #eee; font-family: monospace; font-size: 13px; }
    .tab.second.active { border-color: #ffc800; }
    .tab.third.active  { border-color: #00c8ff; }
    .tab.carousel.active { border-color: #00ff80; }
    .tab.class_top.active { border-color: #ff6090; }
    .tab.class_bottom.active { border-color: #b060ff; }
    button.action { padding: 5px 12px; cursor: pointer; border-radius: 4px;
                    background: #2a6; color: #fff; border: none; font-family: monospace; font-size: 13px; }
    button.danger { background: #833; }
    #status { color: #888; font-size: 12px; margin-left: auto; }
    .canvas-wrap { flex: 1; display: flex; justify-content: center; align-items: center; overflow: hidden; position: relative; }
    canvas { max-width: 100%; max-height: 100%; cursor: crosshair; display: block; }
    .help-panel { position: absolute; top: 10px; left: 10px; z-index: 10; }
    .help-toggle { background: rgba(30,30,30,0.85); border: 1px solid #555; color: #ccc;
                   padding: 4px 10px; cursor: pointer; border-radius: 4px; font-family: monospace; font-size: 12px; }
    .help-toggle:hover { background: rgba(50,50,50,0.9); }
    .help-body { display: none; background: rgba(20,20,20,0.92); border: 1px solid #444;
                 border-radius: 4px; padding: 10px 14px; margin-top: 4px; font-size: 12px;
                 line-height: 1.7; color: #ccc; min-width: 280px; position: relative; }
    .help-body.open { display: block; }
    .help-body kbd { background: #333; border: 1px solid #555; border-radius: 3px;
                     padding: 1px 5px; font-family: monospace; font-size: 11px; color: #eee; }
    .help-close { position: absolute; top: 6px; right: 8px; background: none; border: none;
                  color: #888; font-size: 16px; cursor: pointer; font-family: monospace; line-height: 1; padding: 0; }
    .help-close:hover { color: #eee; }
  </style>
</head>
<body>
  <div class="topbar">
    <button class="tab second active" onclick="setChannel('second')">Second Channel</button>
    <button class="tab third" onclick="setChannel('third')">Third Channel</button>
    <button class="tab carousel" onclick="setChannel('carousel')">Carousel</button>
    <div class="sep"></div>
    <button class="tab class_top" onclick="setChannel('class_top')">Class. Top</button>
    <button class="tab class_bottom" onclick="setChannel('class_bottom')">Class. Bottom</button>
    <div class="sep"></div>
    <button class="action danger" onclick="clearCurrent()">Clear</button>
    <button class="action" onclick="savePolygons()">Save</button>
    <span id="status">loading... | drag to move | scroll to resize | shift-click for sec 0</span>
  </div>
  <div class="canvas-wrap">
    <div class="help-panel">
      <button class="help-toggle" onclick="document.querySelector('.help-body').classList.toggle('open')">? Controls</button>
      <div class="help-body open">
        <button class="help-close" onclick="document.querySelector('.help-body').classList.remove('open')">&times;</button>
        <b>Drawing</b><br>
        <kbd>Click</kbd> &mdash; add vertex<br>
        <kbd>Right-click</kbd> &mdash; remove nearest vertex<br>
        <br>
        <b>Editing</b><br>
        <kbd>Drag</kbd> inside polygon &mdash; move it<br>
        <kbd>Scroll</kbd> &mdash; expand / shrink polygon<br>
        <br>
        <b>Feeder channels only</b><br>
        <kbd>Shift + Click</kbd> &mdash; set section-0 reference point<br>
        <br>
        <b>Toolbar</b><br>
        <kbd>Clear</kbd> &mdash; delete current channel polygon<br>
        <kbd>Save</kbd> &mdash; persist all polygons<br>
      </div>
    </div>
    <canvas id="c" width="1920" height="1080"></canvas>
  </div>
  <script>
    const canvas = document.getElementById('c');
    const ctx = canvas.getContext('2d');

    const FEEDER_CHANNELS = ['second', 'third', 'carousel'];
    const CLASSIFICATION_CHANNELS = ['class_top', 'class_bottom'];
    const ALL_CHANNELS = FEEDER_CHANNELS.concat(CLASSIFICATION_CHANNELS);

    let currentChannel = 'second';
    let userPoints = { second: [], third: [], carousel: [], class_top: [], class_bottom: [] };
    let sectionZeroPoints = { second: null, third: null };

    let frameImg = new Image();
    let cameraMapOverride = {};

    // Load camera map for split_feeder mode
    fetch('/camera_map').then(r => r.json()).then(m => { cameraMapOverride = m; }).catch(() => {});

    function cameraForChannel(ch) {
      if (cameraMapOverride[ch]) return cameraMapOverride[ch];
      if (CLASSIFICATION_CHANNELS.includes(ch)) {
        return ch === 'class_top' ? 'classification_top' : 'classification_bottom';
      }
      return 'feeder';
    }

    function setChannel(ch) {
      currentChannel = ch;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelector('.tab.' + ch).classList.add('active');
    }

    function clearCurrent() {
      userPoints[currentChannel] = [];
      if (currentChannel === 'second' || currentChannel === 'third')
        sectionZeroPoints[currentChannel] = null;
    }

    function canvasCoords(e) {
      const rect = canvas.getBoundingClientRect();
      return [
        (e.clientX - rect.left) * canvas.width / rect.width,
        (e.clientY - rect.top)  * canvas.height / rect.height,
      ];
    }

    let dragging = false;
    let didDrag = false;
    let dragStart = null;
    let dragOrigPts = null;
    let dragOrigSec0 = null;
    const DRAG_THRESHOLD = 5;

    function pointInPolygon(x, y, pts) {
      if (pts.length < 3) return false;
      let inside = false;
      for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
        const xi = pts[i][0], yi = pts[i][1];
        const xj = pts[j][0], yj = pts[j][1];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi)
          inside = !inside;
      }
      return inside;
    }

    function getSortedPolyPts(ch) {
      return computePolygon(ch).map(p => p.pos);
    }

    canvas.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      const [x, y] = canvasCoords(e);
      const sorted = getSortedPolyPts(currentChannel);
      if (sorted.length >= 3 && pointInPolygon(x, y, sorted) && !e.shiftKey) {
        dragging = true;
        dragStart = [x, y];
        dragOrigPts = userPoints[currentChannel].map(p => [...p]);
        if (sectionZeroPoints[currentChannel])
          dragOrigSec0 = [...sectionZeroPoints[currentChannel]];
        else
          dragOrigSec0 = null;
      }
    });

    canvas.addEventListener('mousemove', e => {
      if (!dragging) return;
      const [x, y] = canvasCoords(e);
      const dx = x - dragStart[0];
      const dy = y - dragStart[1];
      for (let i = 0; i < dragOrigPts.length; i++) {
        userPoints[currentChannel][i] = [dragOrigPts[i][0] + dx, dragOrigPts[i][1] + dy];
      }
      if (dragOrigSec0 && sectionZeroPoints[currentChannel]) {
        sectionZeroPoints[currentChannel] = [dragOrigSec0[0] + dx, dragOrigSec0[1] + dy];
      }
    });

    canvas.addEventListener('mouseup', e => {
      if (e.button !== 0) return;
      if (dragging) {
        const [x, y] = canvasCoords(e);
        const dist = Math.hypot(x - dragStart[0], y - dragStart[1]);
        if (dist < DRAG_THRESHOLD) {
          userPoints[currentChannel] = dragOrigPts;
          if (dragOrigSec0) sectionZeroPoints[currentChannel] = dragOrigSec0;
          userPoints[currentChannel].push([dragStart[0], dragStart[1]]);
        } else {
          didDrag = true;
        }
        dragging = false;
        dragStart = null;
        dragOrigPts = null;
        dragOrigSec0 = null;
      }
    });

    canvas.addEventListener('click', e => {
      if (didDrag) { didDrag = false; return; }
      const [x, y] = canvasCoords(e);
      if (e.shiftKey && (currentChannel === 'second' || currentChannel === 'third')) {
        sectionZeroPoints[currentChannel] = [x, y];
        return;
      }
      const sorted = getSortedPolyPts(currentChannel);
      if (sorted.length >= 3 && pointInPolygon(x, y, sorted)) return;
      userPoints[currentChannel].push([x, y]);
    });

    canvas.addEventListener('contextmenu', e => {
      e.preventDefault();
      const [x, y] = canvasCoords(e);
      const pts = userPoints[currentChannel];
      let minDist = Infinity, minIdx = -1;
      for (let i = 0; i < pts.length; i++) {
        const d = Math.hypot(pts[i][0] - x, pts[i][1] - y);
        if (d < minDist) { minDist = d; minIdx = i; }
      }
      if (minIdx >= 0 && minDist < 40) pts.splice(minIdx, 1);
    });

    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const pts = userPoints[currentChannel];
      if (pts.length < 3) return;
      const scale = e.deltaY > 0 ? 0.95 : 1.05;
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      for (let i = 0; i < pts.length; i++) {
        pts[i] = [cx + (pts[i][0] - cx) * scale, cy + (pts[i][1] - cy) * scale];
      }
    }, { passive: false });

    function computePolygon(ch) {
      const pts = userPoints[ch].map(pos => ({ pos }));
      if (pts.length < 2) return pts;
      const cx = pts.reduce((s, p) => s + p.pos[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.pos[1], 0) / pts.length;
      pts.sort((a, b) =>
        Math.atan2(a.pos[1] - cy, a.pos[0] - cx) -
        Math.atan2(b.pos[1] - cy, b.pos[0] - cx)
      );
      return pts;
    }

    function getPolygonCenter(ch) {
      const pts = computePolygon(ch);
      if (pts.length < 2) return null;
      const cx = pts.reduce((s, p) => s + p.pos[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.pos[1], 0) / pts.length;
      return [cx, cy];
    }

    function computeAngle(ch) {
      const ref = sectionZeroPoints[ch];
      if (!ref) return null;
      const center = getPolygonCenter(ch);
      if (!center) return null;
      const dx = ref[0] - center[0];
      const dy = ref[1] - center[1];
      return Math.atan2(dy, dx) * (180 / Math.PI);
    }

    const CHANNEL_COLORS = {
      second:       [255, 200, 0],
      third:        [0, 200, 255],
      carousel:     [0, 255, 128],
      class_top:    [255, 96, 144],
      class_bottom: [176, 96, 255],
    };

    function drawPolygon(ch, active) {
      const pts = computePolygon(ch);
      if (pts.length < 2) return;
      const [r, g, b] = CHANNEL_COLORS[ch];
      const a = active ? 1.0 : 0.35;

      ctx.beginPath();
      ctx.moveTo(pts[0].pos[0], pts[0].pos[1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].pos[0], pts[i].pos[1]);
      ctx.closePath();
      ctx.fillStyle = `rgba(${r},${g},${b},${active ? 0.12 : 0.05})`;
      ctx.fill();
      ctx.strokeStyle = `rgba(${r},${g},${b},${a})`;
      ctx.lineWidth = active ? 2 : 1;
      ctx.stroke();

      for (const pt of pts) {
        const [x, y] = pt.pos;
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
        ctx.fill();
      }

      // section-0 reference line (feeder channels only)
      if ((ch === 'second' || ch === 'third') && sectionZeroPoints[ch] && pts.length >= 2) {
        const center = getPolygonCenter(ch);
        const ref = sectionZeroPoints[ch];
        if (center) {
          ctx.beginPath();
          ctx.moveTo(center[0], center[1]);
          ctx.lineTo(ref[0], ref[1]);
          ctx.strokeStyle = `rgba(255,255,255,${active ? 0.9 : 0.3})`;
          ctx.lineWidth = active ? 2 : 1;
          ctx.setLineDash([6, 4]);
          ctx.stroke();
          ctx.setLineDash([]);

          ctx.beginPath();
          ctx.arc(ref[0], ref[1], 8, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${active ? 0.9 : 0.3})`;
          ctx.fill();
          ctx.fillStyle = '#000';
          ctx.font = 'bold 10px monospace';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText('0', ref[0], ref[1]);
          ctx.textAlign = 'start';
          ctx.textBaseline = 'alphabetic';
        }
      }
    }

    function render() {
      if (!frameImg.naturalWidth) return;
      ctx.drawImage(frameImg, 0, 0, canvas.width, canvas.height);

      // only draw polygons that share the same camera
      const curCam = cameraForChannel(currentChannel);
      for (const ch of ALL_CHANNELS) {
        if (ch === currentChannel) continue;
        if (cameraForChannel(ch) === curCam) drawPolygon(ch, false);
      }
      drawPolygon(currentChannel, true);

      const nUser = userPoints[currentChannel].length;
      let extra = '';
      if (currentChannel === 'second' || currentChannel === 'third') {
        const angle = computeAngle(currentChannel);
        extra = angle !== null ? `  |  sec0: ${angle.toFixed(1)}deg` : '  |  shift-click to set sec 0';
      }
      document.getElementById('status').textContent =
        `${currentChannel}: ${nUser} pts${extra}  |  right-click to remove`;
    }

    function pollFrame() {
      const cam = cameraForChannel(currentChannel);
      const img = new Image();
      img.onload = () => { frameImg = img; render(); };
      img.src = '/frame?cam=' + cam + '&t=' + Date.now();
    }

    async function savePolygons() {
      // save feeder/channel polygons
      const polygons = {};
      const user_pts = {};
      for (const ch of FEEDER_CHANNELS) {
        const key = ch === 'carousel' ? 'carousel' : ch + '_channel';
        polygons[key] = computePolygon(ch).map(p => [Math.round(p.pos[0]), Math.round(p.pos[1])]);
        user_pts[ch] = userPoints[ch].map(p => [Math.round(p[0]), Math.round(p[1])]);
      }
      const channel_angles = {};
      for (const ch of ['second', 'third']) {
        const angle = computeAngle(ch);
        channel_angles[ch] = angle !== null ? angle : 0;
      }
      const section_zero_pts = {};
      for (const ch of ['second', 'third']) {
        if (sectionZeroPoints[ch]) {
          section_zero_pts[ch] = [Math.round(sectionZeroPoints[ch][0]), Math.round(sectionZeroPoints[ch][1])];
        }
      }

      // save classification polygons
      const class_polygons = {};
      const class_user_pts = {};
      for (const ch of CLASSIFICATION_CHANNELS) {
        const key = ch === 'class_top' ? 'top' : 'bottom';
        class_polygons[key] = computePolygon(ch).map(p => [Math.round(p.pos[0]), Math.round(p.pos[1])]);
        class_user_pts[ch] = userPoints[ch].map(p => [Math.round(p[0]), Math.round(p[1])]);
      }

      const res = await fetch('/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          polygons, user_pts, channel_angles, section_zero_pts,
          class_polygons, class_user_pts,
        }),
      });
      const result = await res.json();
      document.getElementById('status').textContent = result.ok ? 'Saved.' : 'Save failed.';
    }

    async function loadSaved() {
      try {
        const res = await fetch('/init');
        const data = await res.json();
        if (data.user_pts) {
          if (data.user_pts.second)   userPoints.second   = data.user_pts.second;
          if (data.user_pts.third)    userPoints.third    = data.user_pts.third;
          if (data.user_pts.carousel) userPoints.carousel = data.user_pts.carousel;
        }
        if (data.section_zero_pts) {
          if (data.section_zero_pts.second) sectionZeroPoints.second = data.section_zero_pts.second;
          if (data.section_zero_pts.third)  sectionZeroPoints.third  = data.section_zero_pts.third;
        }
        if (data.class_user_pts) {
          if (data.class_user_pts.class_top)    userPoints.class_top    = data.class_user_pts.class_top;
          if (data.class_user_pts.class_bottom) userPoints.class_bottom = data.class_user_pts.class_bottom;
        }
      } catch(e) {}
    }

    setInterval(pollFrame, 100);
    pollFrame();
    loadSaved();
  </script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/frame")
def frame():
    cam = request.args.get("cam", "feeder")
    cap = captures.get(cam)
    if cap is None:
        return Response(status=204)
    frame_obj = cap.latest_frame
    if frame_obj is None:
        return Response(status=204)
    _, buf = cv2.imencode(".jpg", frame_obj.raw, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(buf.tobytes(), mimetype="image/jpeg")


@app.route("/init")
def init():
    result = {}
    saved = getChannelPolygons()
    if saved:
        result["user_pts"] = saved.get("user_pts", {})
        result["section_zero_pts"] = saved.get("section_zero_pts", {})
    class_saved = getClassificationPolygons()
    if class_saved:
        result["class_user_pts"] = class_saved.get("user_pts", {})
    return jsonify(result)


def _getCaptureResolution(cam: str) -> list[int]:
    cap = captures.get(cam)
    if cap and cap.latest_frame is not None:
        h, w = cap.latest_frame.raw.shape[:2]
        return [w, h]
    return [1920, 1080]


@app.route("/save", methods=["POST"])
def save():
    body = request.get_json()
    feeder_res = _getCaptureResolution("feeder")
    class_top_res = _getCaptureResolution("classification_top")
    class_bottom_res = _getCaptureResolution("classification_bottom")
    # save channel polygons (feeder camera)
    setChannelPolygons({
        "polygons": body["polygons"],
        "user_pts": body["user_pts"],
        "channel_angles": body["channel_angles"],
        "section_zero_pts": body["section_zero_pts"],
        "resolution": feeder_res,
    })
    # save classification polygons — use top cam resolution (both should match)
    setClassificationPolygons({
        "polygons": body["class_polygons"],
        "user_pts": body["class_user_pts"],
        "resolution": class_top_res or class_bottom_res or feeder_res,
    })
    return jsonify({"ok": True})


if __name__ == "__main__":
    import os
    import tomllib

    # Check for split_feeder layout from TOML
    camera_layout = "default"
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    cameras_section = {}
    if params_path and os.path.exists(params_path):
        try:
            with open(params_path, "rb") as f:
                raw_toml = tomllib.load(f)
            cameras_section = raw_toml.get("cameras", {})
            camera_layout = cameras_section.get("layout", "default")
        except Exception:
            pass

    if camera_layout == "split_feeder":
        # split_feeder: one camera per channel + carousel + optional classification
        for role in ("c_channel_2", "c_channel_3", "carousel"):
            idx = cameras_section.get(role)
            if isinstance(idx, int):
                captures[role] = CaptureThread(role, mkCameraConfig(device_index=idx))
                captures[role].start()

        # Map split_feeder cameras to polygon editor channel names
        # second_channel polygon → c_channel_2 camera
        # third_channel polygon → c_channel_3 camera
        # carousel polygon → carousel camera
        CAMERA_FOR_CHANNEL_OVERRIDE = {
            "second": "c_channel_2",
            "third": "c_channel_3",
            "carousel": "carousel",
        }

        for role in ("classification_top", "classification_bottom"):
            source = cameras_section.get(role)
            if isinstance(source, str):
                captures[role] = CaptureThread(role, mkCameraConfig(url=source))
                captures[role].start()
            elif isinstance(source, int):
                captures[role] = CaptureThread(role, mkCameraConfig(device_index=source))
                captures[role].start()

        CAMERA_FOR_CHANNEL_OVERRIDE["class_top"] = "classification_top"
        CAMERA_FOR_CHANNEL_OVERRIDE["class_bottom"] = "classification_bottom"

        # Monkey-patch the JS camera mapping via a global
        @app.route("/camera_map")
        def camera_map():
            return jsonify(CAMERA_FOR_CHANNEL_OVERRIDE)
    else:
        camera_setup = getCameraSetup()
        if camera_setup is None or "feeder" not in camera_setup:
            print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
            sys.exit(1)

        captures["feeder"] = CaptureThread("feeder", mkCameraConfig(device_index=camera_setup["feeder"]))
        captures["feeder"].start()

        if "classification_top" in camera_setup:
            captures["classification_top"] = CaptureThread(
                "classification_top", mkCameraConfig(device_index=camera_setup["classification_top"])
            )
            captures["classification_top"].start()

        if "classification_bottom" in camera_setup:
            captures["classification_bottom"] = CaptureThread(
                "classification_bottom", mkCameraConfig(device_index=camera_setup["classification_bottom"])
            )
            captures["classification_bottom"].start()

        @app.route("/camera_map")
        def camera_map():
            return jsonify({})

    print(f"Server starting on http://localhost:{PORT}")
    print(f"Layout: {camera_layout}")
    print(f"Cameras: {list(captures.keys())}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
