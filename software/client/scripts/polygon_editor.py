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
    .canvas-wrap { flex: 1; display: flex; justify-content: center; align-items: center; overflow: hidden; }
    canvas { max-width: 100%; max-height: 100%; cursor: crosshair; display: block; }
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
    <span id="status">loading... | shift-click to set section 0</span>
  </div>
  <div class="canvas-wrap">
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

    function cameraForChannel(ch) {
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

    canvas.addEventListener('click', e => {
      const [x, y] = canvasCoords(e);
      if (e.shiftKey && (currentChannel === 'second' || currentChannel === 'third')) {
        sectionZeroPoints[currentChannel] = [x, y];
        return;
      }
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


@app.route("/save", methods=["POST"])
def save():
    body = request.get_json()
    # save channel polygons (feeder camera)
    setChannelPolygons({
        "polygons": body["polygons"],
        "user_pts": body["user_pts"],
        "channel_angles": body["channel_angles"],
        "section_zero_pts": body["section_zero_pts"],
    })
    # save classification polygons
    setClassificationPolygons({
        "polygons": body["class_polygons"],
        "user_pts": body["class_user_pts"],
    })
    return jsonify({"ok": True})


if __name__ == "__main__":
    camera_setup = getCameraSetup()
    if camera_setup is None or "feeder" not in camera_setup:
        print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
        sys.exit(1)

    captures["feeder"] = CaptureThread("feeder", mkCameraConfig(camera_setup["feeder"]))
    captures["feeder"].start()

    if "classification_top" in camera_setup:
        captures["classification_top"] = CaptureThread(
            "classification_top", mkCameraConfig(camera_setup["classification_top"])
        )
        captures["classification_top"].start()

    if "classification_bottom" in camera_setup:
        captures["classification_bottom"] = CaptureThread(
            "classification_bottom", mkCameraConfig(camera_setup["classification_bottom"])
        )
        captures["classification_bottom"].start()

    print(f"Server starting on http://localhost:{PORT}")
    print(f"Cameras: {list(captures.keys())}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
