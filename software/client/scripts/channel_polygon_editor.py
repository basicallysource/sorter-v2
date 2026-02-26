"""
Channel & carousel polygon editor.
All regions are click-to-draw polygons stored in blob_manager.
Shift-click on a channel tab to place the section-0 reference point.

Run: /opt/homebrew/opt/python@3.11/bin/python3.11 client/scripts/channel_polygon_editor.py
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

from blob_manager import getCameraSetup, getChannelPolygons, setChannelPolygons
from irl.config import mkCameraConfig
from vision.camera import CaptureThread

PORT = 8100

app = Flask(__name__)
capture: CaptureThread = None  # type: ignore[assignment]

HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Channel Polygon Editor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #111; color: #eee; font-family: monospace;
           display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
    .topbar { display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: #1a1a1a; border-bottom: 1px solid #333; flex-shrink: 0; }
    .tab { padding: 5px 14px; cursor: pointer; border-radius: 4px; background: #2a2a2a;
           border: 2px solid transparent; color: #eee; font-family: monospace; font-size: 13px; }
    .tab.second.active { border-color: #ffc800; }
    .tab.third.active  { border-color: #00c8ff; }
    .tab.carousel.active { border-color: #00ff80; }
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

    let currentChannel = 'second';
    let userPoints = { second: [], third: [], carousel: [] };
    // section-0 reference points (pixel coords) for each channel
    let sectionZeroPoints = { second: null, third: null };

    let frameImg = new Image();

    function setChannel(ch) {
      currentChannel = ch;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelector('.tab.' + ch).classList.add('active');
    }

    function clearCurrent() {
      userPoints[currentChannel] = [];
      if (currentChannel !== 'carousel') sectionZeroPoints[currentChannel] = null;
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
      if (e.shiftKey && currentChannel !== 'carousel') {
        // shift-click sets section-0 reference point
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

    function drawPolygon(ch, active) {
      const pts = computePolygon(ch);
      if (pts.length < 2) return;
      let r, g, b;
      if (ch === 'second')       { r = 255; g = 200; b = 0; }
      else if (ch === 'third')   { r = 0; g = 200; b = 255; }
      else                       { r = 0; g = 255; b = 128; }
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

      // draw section-0 reference line
      if (ch !== 'carousel' && sectionZeroPoints[ch] && pts.length >= 2) {
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

          // draw marker at reference point
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
      for (const ch of ['second', 'third', 'carousel'])
        if (ch !== currentChannel) drawPolygon(ch, false);
      drawPolygon(currentChannel, true);

      const nUser = userPoints[currentChannel].length;
      let extra = '';
      if (currentChannel !== 'carousel') {
        const angle = computeAngle(currentChannel);
        extra = angle !== null ? `  |  sec0: ${angle.toFixed(1)}deg` : '  |  shift-click to set sec 0';
      }
      document.getElementById('status').textContent =
        `${currentChannel}: ${nUser} pts${extra}  |  right-click to remove`;
    }

    function pollFrame() {
      const img = new Image();
      img.onload = () => { frameImg = img; render(); };
      img.src = '/frame?' + Date.now();
    }

    async function savePolygons() {
      const polygons = {};
      const user_pts = {};
      for (const ch of ['second', 'third', 'carousel']) {
        const key = ch === 'carousel' ? 'carousel' : ch + '_channel';
        polygons[key] = computePolygon(ch).map(p => [Math.round(p.pos[0]), Math.round(p.pos[1])]);
        user_pts[ch] = userPoints[ch].map(p => [Math.round(p[0]), Math.round(p[1])]);
      }
      // compute angles from section-0 reference points
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
      const res = await fetch('/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ polygons, user_pts, channel_angles, section_zero_pts }),
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
    frame_obj = capture.latest_frame
    if frame_obj is None:
        return Response(status=204)
    _, buf = cv2.imencode(".jpg", frame_obj.raw, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(buf.tobytes(), mimetype="image/jpeg")


@app.route("/init")
def init():
    saved = getChannelPolygons()
    if saved is None:
        return jsonify({})
    return jsonify({
        "user_pts": saved.get("user_pts", {}),
        "section_zero_pts": saved.get("section_zero_pts", {}),
    })


@app.route("/save", methods=["POST"])
def save():
    body = request.get_json()
    setChannelPolygons(body)
    return jsonify({"ok": True})


if __name__ == "__main__":
    camera_setup = getCameraSetup()
    if camera_setup is None or "feeder" not in camera_setup:
        print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
        sys.exit(1)

    capture = CaptureThread("feeder", mkCameraConfig(camera_setup["feeder"]))
    capture.start()

    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
