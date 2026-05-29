"""motor_test.py — tiny web UI for end-to-end stepper/servo testing.

Initialises hardware via the real mkIRLConfig/mkIRLInterface pathways, then
serves a single-page app on localhost so you can drive every motor manually.

Usage (from software/sorter/backend/):
    uv run python scripts/motor_test.py [--port 8765] [--debug]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

# ── backend imports ───────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import glob
import subprocess
import cv2
from flask import Flask, Response, jsonify, request
from global_config import GlobalConfig, Timeouts
from logger import Logger
from hardware.sorter_interface import StepperMotor, ServoMotor, DigitalOutputPin, DigitalInputPin
import irl.config as _irl_bootstrap  # must precede machine_platform import to resolve circular dep
from machine_platform.control_board import discover_control_boards
from subsystems.distribution.chute import HOME_SPEED_MICROSTEPS_PER_SEC, HOME_TIMEOUT_MS

# ── global state ──────────────────────────────────────────────────────────────

app = Flask(__name__)
_steppers: dict[str, StepperMotor] = {}
_servos: list[ServoMotor] = []
_digital_outputs: list[dict[str, Any]] = []
_chute_home_pin: DigitalInputPin | None = None
_chute_endstop_active_high: bool = True
_lock = threading.Lock()

_cameras: dict[str, int] = {}        # name -> device index
_camera_frames: dict[str, bytes] = {}  # name -> latest JPEG bytes
_camera_lock = threading.Lock()

_gc: GlobalConfig | None = None
_chute_home_channel: int = 0


def _get_steppers() -> dict[str, StepperMotor]:
    return _steppers


def _get_servos() -> list[ServoMotor]:
    return _servos


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    steppers = {
        name: {"enabled": m.enabled, "can_home": name == "chute_stepper" and _chute_home_pin is not None}
        for name, m in _get_steppers().items()
    }
    servos = [{"index": i, "enabled": s.enabled} for i, s in enumerate(_get_servos())]
    digital_outputs = [{"index": d["index"], "label": d["label"], "value": d["value"]} for d in _digital_outputs]
    return jsonify({"steppers": steppers, "servos": servos, "digital_outputs": digital_outputs})


@app.post("/api/stepper/enable")
def api_stepper_enable():
    name = request.json.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].enabled = True
    return jsonify({"ok": True})


@app.post("/api/stepper/disable")
def api_stepper_disable():
    name = request.json.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].enabled = False
    return jsonify({"ok": True})


@app.post("/api/stepper/speed")
def api_stepper_speed():
    body = request.json
    name = body.get("name")
    max_speed = int(body.get("max_speed", 2000))
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        steppers[name].set_speed_limits(16, max_speed)
    return jsonify({"ok": True})


@app.post("/api/stepper/move")
def api_stepper_move():
    body: dict[str, Any] = request.json or {}
    name = body.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404

    motor = steppers[name]
    blocking = bool(body.get("blocking", True))

    with _lock:
        if "steps" in body:
            steps = int(body["steps"])
            ok = motor.move_steps_blocking(steps) if blocking else motor.move_steps(steps)
        elif "degrees" in body:
            degrees = float(body["degrees"])
            ok = motor.move_degrees_blocking(degrees) if blocking else motor.move_degrees(degrees)
        else:
            return jsonify({"error": "provide steps or degrees"}), 400

    return jsonify({"ok": ok})


@app.post("/api/stepper/stop")
def api_stepper_stop():
    name = request.json.get("name")
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    with _lock:
        if not bool(steppers[name].stopped):
            steppers[name].move_at_speed(0)
    return jsonify({"ok": True})


@app.post("/api/stepper/home")
def api_stepper_home():
    name = request.json.get("name")
    if name != "chute_stepper":
        return jsonify({"error": "homing only supported for chute_stepper"}), 400
    steppers = _get_steppers()
    if name not in steppers:
        return jsonify({"error": f"unknown stepper {name!r}"}), 404
    if _chute_home_pin is None:
        return jsonify({"error": "no home pin configured for chute_stepper"}), 500
    stepper = steppers[name]
    with _lock:
        stepper.home(HOME_SPEED_MICROSTEPS_PER_SEC, _chute_home_pin, home_pin_active_high=_chute_endstop_active_high)
    start = time.monotonic()
    while not stepper.stopped:
        if (time.monotonic() - start) * 1000 > HOME_TIMEOUT_MS:
            return jsonify({"ok": False, "error": "homing timed out"})
        time.sleep(0.01)
    triggered = bool(_chute_home_pin.value) == _chute_endstop_active_high
    return jsonify({"ok": triggered, "triggered": triggered})


@app.post("/api/servo/move")
def api_servo_move():
    body = request.json
    idx = int(body.get("index", 0))
    angle = int(body.get("angle", 90))
    release = bool(body.get("release", False))
    servos = _get_servos()
    if idx >= len(servos):
        return jsonify({"error": f"servo index {idx} out of range"}), 404
    with _lock:
        ok = servos[idx].move_to_and_release(angle) if release else servos[idx].move_to(angle)
    return jsonify({"ok": ok})


@app.post("/api/servo/enable")
def api_servo_enable():
    idx = int(request.json.get("index", 0))
    servos = _get_servos()
    if idx >= len(servos):
        return jsonify({"error": f"servo index {idx} out of range"}), 404
    with _lock:
        servos[idx].enabled = True
    return jsonify({"ok": True})


@app.post("/api/servo/disable")
def api_servo_disable():
    idx = int(request.json.get("index", 0))
    servos = _get_servos()
    if idx >= len(servos):
        return jsonify({"error": f"servo index {idx} out of range"}), 404
    with _lock:
        servos[idx].enabled = False
    return jsonify({"ok": True})


@app.get("/api/cameras")
def api_cameras():
    return jsonify({"cameras": list(_cameras.keys())})


@app.get("/api/camera/stream/<name>")
def api_camera_stream(name: str):
    if name not in _cameras:
        return jsonify({"error": "unknown camera"}), 404

    def generate():
        while True:
            with _camera_lock:
                frame = _camera_frames.get(name)
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(1 / 15)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/digital_output/set")
def api_digital_output_set():
    body = request.json
    idx = int(body.get("index", 0))
    value = bool(body.get("value", False))
    if idx >= len(_digital_outputs):
        return jsonify({"error": f"digital output index {idx} out of range"}), 404
    with _lock:
        _digital_outputs[idx]["pin"].value = value
        _digital_outputs[idx]["value"] = value
    return jsonify({"ok": True, "index": idx, "value": value})


@app.post("/api/reconnect")
def api_reconnect():
    global _steppers, _servos, _digital_outputs, _chute_home_pin, _chute_endstop_active_high
    if _gc is None:
        return jsonify({"ok": False, "error": "not initialised"}), 500
    with _lock:
        _steppers.clear()
        _servos.clear()
        _digital_outputs.clear()
        _chute_home_pin = None
        _chute_endstop_active_high = True

        boards = discover_control_boards(_gc, required_stepper_names=[])

        for board in boards:
            identity = board.identity
            for ds in board.iter_steppers():
                name = ds.canonical_name
                if name in _steppers:
                    name = f"{name}__{identity.port}"
                _steppers[name] = ds.stepper
                ds.stepper.enabled = True
                if ds.canonical_name == "chute_stepper" and _chute_home_pin is None:
                    _chute_home_pin = board.get_input(_chute_home_channel)
            _servos.extend(board.servos)
            for i, dout in enumerate(board.interface.digital_outputs):
                label = f"24V rail {i}" if len(board.interface.digital_outputs) <= 2 else f"output {i}"
                _digital_outputs.append({"index": i, "label": label, "pin": dout, "value": dout.value})

    return jsonify({
        "ok": True,
        "steppers": list(_steppers.keys()),
        "servos": len(_servos),
        "digital_outputs": len(_digital_outputs),
    })


# ── HTML ──────────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>motor test</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e4ef; --muted: #6b7280; --accent: #6366f1;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308;
    font-family: ui-monospace, 'Cascadia Code', monospace;
  }
  body { background: var(--bg); color: var(--text); min-height: 100vh; padding: 24px; }
  h1 { font-size: 1.1rem; font-weight: 600; color: var(--muted); margin-bottom: 24px;
       letter-spacing: .08em; text-transform: uppercase; }
  h2 { font-size: .75rem; font-weight: 600; color: var(--muted); letter-spacing: .1em;
       text-transform: uppercase; margin: 32px 0 12px; }
  .cards { display: flex; flex-wrap: wrap; gap: 16px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
          padding: 16px; width: 320px; display: flex; flex-direction: column; gap: 10px; }
  .card-title { font-size: .9rem; font-weight: 600; }
  .row { display: flex; gap: 8px; align-items: center; }
  .row label { font-size: .75rem; color: var(--muted); width: 60px; flex-shrink: 0; }
  input[type=number], input[type=range] { flex: 1; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 5px 8px; font-family: inherit; font-size: .8rem; }
  input[type=range] { padding: 0; }
  .speed-val { font-size: .75rem; color: var(--muted); width: 40px; text-align: right; }
  button { border: none; border-radius: 6px; cursor: pointer; font-family: inherit;
           font-size: .78rem; font-weight: 500; padding: 6px 12px; transition: opacity .15s; }
  button:hover { opacity: .85; }
  button:active { opacity: .7; }
  .btn-accent { background: var(--accent); color: #fff; }
  .btn-green  { background: var(--green);  color: #000; }
  .btn-red    { background: var(--red);    color: #fff; }
  .btn-muted  { background: var(--border); color: var(--text); }
  .btn-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
                background: var(--red); }
  .status-dot.on { background: var(--green); }
  .feedback { font-size: .72rem; color: var(--muted); min-height: 1.2em; }
  .feedback.ok  { color: var(--green); }
  .feedback.err { color: var(--red); }
  .cam-row { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 4px; }
  .cam-wrap { display: flex; flex-direction: column; align-items: center; gap: 4px; flex-shrink: 0; }
  .cam-wrap img { height: 160px; width: auto; border-radius: 6px;
                  border: 1px solid var(--border); background: var(--surface); }
  .cam-label { font-size: .7rem; color: var(--muted); }
</style>
</head>
<body>
<h1>motor test <button id="reconnect-btn" style="margin-left:16px;font-size:.7rem;padding:4px 10px;background:var(--yellow);color:#000;border:none;border-radius:4px;cursor:pointer">reconnect</button></h1>

<h2>cameras</h2>
<div id="camera-row" class="cam-row"></div>

<h2>steppers</h2>
<div id="stepper-cards" class="cards"></div>

<h2>servos</h2>
<div id="servo-cards" class="cards"></div>

<h2>24V rails</h2>
<div id="dout-cards" class="cards"></div>

<script>
const post = (url, body) =>
  fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
    .then(r => r.json());

function feedback(el, res) {
  el.textContent = res.ok ? 'ok' : (res.error || 'error');
  el.className = 'feedback ' + (res.ok ? 'ok' : 'err');
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.textContent = ''; el.className = 'feedback'; }, 2500);
}

function mkStepperCard(name, info, keyNum) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.name = name;

  const keyBadge = keyNum != null
    ? `<span style="margin-left:auto;background:var(--border);color:var(--muted);font-size:.7rem;padding:2px 6px;border-radius:4px">${keyNum}</span>`
    : '';

  card.innerHTML = `
    <div class="row">
      <div class="status-dot ${info.enabled ? 'on' : ''}"></div>
      <span class="card-title">${name}</span>
      ${keyBadge}
    </div>
    <div class="row">
      <label>speed</label>
      <input type="range" class="speed-range" min="50" max="6000" step="50" value="2000">
      <span class="speed-val">2000</span>
      <button class="btn-muted set-speed-btn">set</button>
    </div>
    <div class="row">
      <label>steps</label>
      <input type="number" class="steps-input" value="200" step="1">
      <button class="btn-accent move-steps-btn">move</button>
    </div>
    <div class="row">
      <label>degrees</label>
      <input type="number" class="deg-input" value="90" step="1">
      <button class="btn-accent move-deg-btn">move</button>
    </div>
    <div class="btn-row">
      <button class="btn-green enable-btn">enable</button>
      <button class="btn-red disable-btn">disable</button>
      <button class="btn-muted stop-btn">stop</button>
      ${info.can_home ? '<button class="btn-accent home-btn">home</button>' : ''}
    </div>
    <div class="feedback"></div>
  `;

  const dot = card.querySelector('.status-dot');
  const fb = card.querySelector('.feedback');
  const speedRange = card.querySelector('.speed-range');
  const speedVal = card.querySelector('.speed-val');

  speedRange.addEventListener('input', () => { speedVal.textContent = speedRange.value; });

  card.querySelector('.set-speed-btn').onclick = () =>
    post('/api/stepper/speed', {name, max_speed: +speedRange.value}).then(r => feedback(fb, r));

  card.querySelector('.move-steps-btn').onclick = () =>
    post('/api/stepper/move', {name, steps: +card.querySelector('.steps-input').value})
      .then(r => feedback(fb, r));

  card.querySelector('.move-deg-btn').onclick = () =>
    post('/api/stepper/move', {name, degrees: +card.querySelector('.deg-input').value})
      .then(r => feedback(fb, r));

  card.querySelector('.enable-btn').onclick = () =>
    post('/api/stepper/enable', {name}).then(r => { if(r.ok) dot.classList.add('on'); feedback(fb, r); });

  card.querySelector('.disable-btn').onclick = () =>
    post('/api/stepper/disable', {name}).then(r => { if(r.ok) dot.classList.remove('on'); feedback(fb, r); });

  card.querySelector('.stop-btn').onclick = () =>
    post('/api/stepper/stop', {name}).then(r => feedback(fb, r));

  if (info.can_home) {
    card.querySelector('.home-btn').onclick = () => {
      fb.textContent = 'homing…';
      fb.className = 'feedback';
      post('/api/stepper/home', {name}).then(r => feedback(fb, r));
    };
  }

  return card;
}

function mkServoCard(idx, info) {
  const card = document.createElement('div');
  card.className = 'card';
  let currentAngle = 90;

  card.innerHTML = `
    <div class="row">
      <div class="status-dot ${info.enabled ? 'on' : ''}"></div>
      <span class="card-title">servo ${idx}</span>
      <span class="current-angle" style="margin-left:auto;font-size:.75rem;color:var(--muted)">@ ${currentAngle}°</span>
    </div>
    <div class="row">
      <label>angle</label>
      <input type="number" class="angle-input" value="10" min="0" max="180" step="1">
    </div>
    <div class="btn-row">
      <button class="btn-accent nudge-left-btn">◀ nudge</button>
      <button class="btn-accent nudge-right-btn">nudge ▶</button>
    </div>
    <div class="btn-row">
      <button class="btn-accent move-btn">move to</button>
      <button class="btn-muted release-btn">move + release</button>
      <button class="btn-green enable-btn">enable</button>
      <button class="btn-red disable-btn">disable</button>
    </div>
    <div class="feedback"></div>
  `;

  const dot = card.querySelector('.status-dot');
  const fb = card.querySelector('.feedback');
  const angleInput = card.querySelector('.angle-input');
  const currentAngleEl = card.querySelector('.current-angle');

  function updateCurrentAngle(a) {
    currentAngle = Math.max(0, Math.min(180, a));
    currentAngleEl.textContent = `@ ${currentAngle}°`;
  }

  async function enableAndMove(angle) {
    await post('/api/servo/enable', {index: idx});
    dot.classList.add('on');
    const r = await post('/api/servo/move', {index: idx, angle});
    updateCurrentAngle(angle);
    feedback(fb, r);
  }

  card.querySelector('.nudge-left-btn').onclick = () =>
    enableAndMove(currentAngle - +angleInput.value);

  card.querySelector('.nudge-right-btn').onclick = () =>
    enableAndMove(currentAngle + +angleInput.value);

  card.querySelector('.move-btn').onclick = () => {
    const a = +angleInput.value;
    post('/api/servo/move', {index: idx, angle: a}).then(r => { updateCurrentAngle(a); feedback(fb, r); });
  };

  card.querySelector('.release-btn').onclick = () =>
    post('/api/servo/move', {index: idx, angle: +angleInput.value, release: true}).then(r => feedback(fb, r));

  card.querySelector('.enable-btn').onclick = () =>
    post('/api/servo/enable', {index: idx}).then(r => { if(r.ok) dot.classList.add('on'); feedback(fb, r); });

  card.querySelector('.disable-btn').onclick = () =>
    post('/api/servo/disable', {index: idx}).then(r => { if(r.ok) dot.classList.remove('on'); feedback(fb, r); });

  return card;
}

function mkDoutCard(info) {
  const card = document.createElement('div');
  card.className = 'card';

  card.innerHTML = `
    <div class="row">
      <div class="status-dot ${info.value ? 'on' : ''}"></div>
      <span class="card-title">${info.label}</span>
      <span style="margin-left:auto;font-size:.75rem;color:var(--muted)">${info.value ? 'ON' : 'OFF'}</span>
    </div>
    <div class="btn-row">
      <button class="btn-green on-btn">on</button>
      <button class="btn-red off-btn">off</button>
    </div>
    <div class="feedback"></div>
  `;

  const dot = card.querySelector('.status-dot');
  const fb = card.querySelector('.feedback');
  const stateLabel = card.querySelector('.status-dot + .card-title + span');

  function setState(v) {
    if (v) { dot.classList.add('on'); } else { dot.classList.remove('on'); }
    stateLabel.textContent = v ? 'ON' : 'OFF';
  }

  card.querySelector('.on-btn').onclick = () =>
    post('/api/digital_output/set', {index: info.index, value: true})
      .then(r => { if(r.ok) setState(true); feedback(fb, r); });

  card.querySelector('.off-btn').onclick = () =>
    post('/api/digital_output/set', {index: info.index, value: false})
      .then(r => { if(r.ok) setState(false); feedback(fb, r); });

  return card;
}

async function initCameras() {
  const {cameras} = await fetch('/api/cameras').then(r => r.json());
  const row = document.getElementById('camera-row');
  if (!cameras.length) {
    row.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no cameras detected</p>';
    return;
  }
  for (const name of cameras) {
    const wrap = document.createElement('div');
    wrap.className = 'cam-wrap';
    const img = document.createElement('img');
    img.src = `/api/camera/stream/${name}`;
    img.onerror = () => { img.alt = 'no signal'; img.style.opacity = '0.3'; };
    const label = document.createElement('span');
    label.className = 'cam-label';
    label.textContent = name;
    wrap.appendChild(img);
    wrap.appendChild(label);
    row.appendChild(wrap);
  }
}

const _stepperCards = [];

async function init() {
  initCameras();
  const {steppers, servos, digital_outputs} = await fetch('/api/status').then(r => r.json());

  const sc = document.getElementById('stepper-cards');
  for (const [i, [name, info]] of Object.entries(steppers).entries()) {
    const card = mkStepperCard(name, info, i + 1);
    _stepperCards.push(card);
    sc.appendChild(card);
  }
  if (!Object.keys(steppers).length)
    sc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no steppers detected</p>';

  const vc = document.getElementById('servo-cards');
  for (const [i, info] of servos.entries())
    vc.appendChild(mkServoCard(i, info));
  if (!servos.length)
    vc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no servos detected</p>';

  const dc = document.getElementById('dout-cards');
  for (const d of (digital_outputs || []))
    dc.appendChild(mkDoutCard(d));
  if (!(digital_outputs && digital_outputs.length))
    dc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no digital outputs detected</p>';
}

init();

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  const idx = parseInt(e.key) - 1;
  if (isNaN(idx) || idx < 0 || idx >= _stepperCards.length) return;
  _stepperCards[idx].querySelector('.move-steps-btn').click();
});

document.getElementById('reconnect-btn').onclick = async () => {
  const btn = document.getElementById('reconnect-btn');
  btn.textContent = 'reconnecting…';
  btn.disabled = true;

  const r = await fetch('/api/reconnect', {method:'POST'}).then(r => r.json());
  btn.textContent = r.ok ? 'reconnect' : 'failed';
  btn.disabled = false;
  setTimeout(() => { btn.textContent = 'reconnect'; }, 2000);

  if (!r.ok) return;

  _stepperCards.length = 0;
  document.getElementById('stepper-cards').innerHTML = '';
  document.getElementById('servo-cards').innerHTML = '';
  document.getElementById('dout-cards').innerHTML = '';

  const {steppers, servos, digital_outputs} = await fetch('/api/status').then(r => r.json());

  const sc = document.getElementById('stepper-cards');
  for (const [i, [name, info]] of Object.entries(steppers).entries()) {
    const card = mkStepperCard(name, info, i + 1);
    _stepperCards.push(card);
    sc.appendChild(card);
  }
  if (!Object.keys(steppers).length)
    sc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no steppers detected</p>';

  const vc = document.getElementById('servo-cards');
  for (const [i, info] of servos.entries())
    vc.appendChild(mkServoCard(i, info));
  if (!servos.length)
    vc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no servos detected</p>';

  const dc = document.getElementById('dout-cards');
  for (const d of (digital_outputs || []))
    dc.appendChild(mkDoutCard(d));
  if (!(digital_outputs && digital_outputs.length))
    dc.innerHTML = '<p style="color:var(--muted);font-size:.8rem">no digital outputs detected</p>';
};
</script>
</body>
</html>"""


@app.get("/")
def index():
    return PAGE


# ── startup ───────────────────────────────────────────────────────────────────

def buildGc(debug: bool) -> GlobalConfig:
    gc = GlobalConfig()
    gc.logger = Logger(debug_level=3 if debug else 1)
    gc.timeouts = Timeouts()
    gc.disable_chute = False
    gc.disable_servos = False
    return gc


def _enumerate_cameras() -> dict[str, int]:
    """Return {label: device_index} for /dev/video* nodes that have actual capture formats."""
    result: dict[str, int] = {}
    for path in sorted(glob.glob("/dev/video[0-9]*")):
        try:
            out = subprocess.run(
                ["v4l2-ctl", "-d", path, "--list-formats"],
                capture_output=True, text=True, timeout=2,
            ).stdout
            if "'" in out:  # format entries look like [0]: 'MJPG'
                idx = int(path.removeprefix("/dev/video"))
                result[f"video{idx}"] = idx
        except Exception:
            pass
    return result


def _camera_capture_loop(name: str, index: int) -> None:
    from vision.camera import _open_capture_source

    cap = _open_capture_source(index, fourcc="MJPG", width=320, height=240)
    if not cap.isOpened():
        print(f"Camera {name!r} (video{index}) failed to open — skipping")
        cap.release()
        return
    ret, frame = cap.read()
    if not ret:
        print(f"Camera {name!r} (video{index}) failed first read — skipping")
        cap.release()
        return
    while True:
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        with _camera_lock:
            _camera_frames[name] = buf.tobytes()
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue


def _load_chute_home_config() -> int:
    machine_toml = Path(__file__).resolve().parents[3] / "machine.toml"
    if not machine_toml.exists():
        return 0
    with machine_toml.open("rb") as f:
        data = tomllib.load(f)
    return data.get("chute", {}).get("home_pin_channel", 0)


def main() -> None:
    global _steppers, _servos, _chute_home_pin, _chute_endstop_active_high, _cameras, _gc, _chute_home_channel

    parser = argparse.ArgumentParser(description="Motor test web UI")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    gc = buildGc(args.debug)
    _gc = gc
    gc.logger.info("motor_test: discovering control boards (no required steppers)")
    boards = discover_control_boards(gc, required_stepper_names=[])

    chute_home_channel = _load_chute_home_config()
    _chute_home_channel = chute_home_channel
    _chute_endstop_active_high = True

    for board in boards:
        identity = board.identity
        gc.logger.info(
            f"Found board: {identity.family}:{identity.role} on {identity.port} — "
            f"steppers={list(board.logical_stepper_names)}"
        )
        for ds in board.iter_steppers():
            name = ds.canonical_name
            if name in _steppers:
                name = f"{name}__{identity.port}"
            _steppers[name] = ds.stepper
            ds.stepper.enabled = True
            if ds.canonical_name == "chute_stepper" and _chute_home_pin is None:
                _chute_home_pin = board.get_input(chute_home_channel)
        _servos.extend(board.servos)
        for i, dout in enumerate(board.interface.digital_outputs):
            label = f"24V rail {i}" if len(board.interface.digital_outputs) <= 2 else f"output {i}"
            _digital_outputs.append({"index": i, "label": label, "pin": dout, "value": dout.value})

    _cameras = _enumerate_cameras()
    for cam_name, cam_index in _cameras.items():
        t = threading.Thread(target=_camera_capture_loop, args=(cam_name, cam_index), daemon=True)
        t.start()
        time.sleep(0.3)

    print(f"\nDetected {len(_steppers)} stepper(s): {', '.join(_steppers) or 'none'}")
    print(f"Detected {len(_servos)} servo(s)")
    print(f"Detected {len(_digital_outputs)} digital output(s)")
    print(f"Cameras: {', '.join(f'{n}={i}' for n, i in _cameras.items()) or 'none'}")
    import socket
    hostname = socket.gethostname()
    print(f"\nOpen http://{hostname}:{args.port}  (or http://<pi-ip>:{args.port})\n")

    app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
